import httpx
import time
import json
import itertools
import sqlite3
import datetime
import hashlib


PORT = "8088"
API_URL = "http://127.0.0.1:" + PORT
DEV_TOKEN = "rl_live_8f2c1d94e6b74a03"

def content_hash(obj: dict) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


LEDGER = (("id", "INTEGER PRIMARY KEY AUTOINCREMENT"), ("entity", "TEXT"),
          ("page_num", "INT NOT NULL"), ("fetched_at", "TEXT"),
          ("payload_hash", "TEXT"), ("status", "TEXT"),
          ("as_of_demand", "TEXT"), ("as_of_received", "TEXT"), ("since", "TEXT"),
          ("until", "TEXT"), ("cursor", "TEXT"),
          ("next_cursor", "TEXT")  )

SCHEMA_LEDGER = "CREATE TABLE IF NOT EXISTS page_ledger (\n  " + \
    ",\n  ".join(f"{name} {decl}" for name, decl in LEDGER) + \
    "\n);"

LEDGER_COLS = tuple(name for name, _ in LEDGER)


ORDERS_RAW = (("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
                ("order_id", "TEXT NOT NULL"),
                ("customer_id", "TEXT"), ("occurred_at", "TEXT"),
                ("channel", "TEXT"), ("payment_method", "TEXT"),
                ("shipping_speed", "TEXT"), ("order_total_cents", "INT"),
                ("items", "TEXT"), ("version", "TEXT"),
                ("knowledge_time", "TEXT"), ("content_hash", "TEXT"),
                ("received_at", "TEXT"), ("source_cursor", "TEXT"),
                ("source_page", "TEXT"))

SCHEMA_ORDERS_RAW = "CREATE TABLE IF NOT EXISTS orders_raw (\n  " + \
    ",\n  ".join(f"{name} {decl}" for name, decl in ORDERS_RAW) + \
    ",\n " + "UNIQUE (order_id, version, content_hash));"

ORDERS_COLS = tuple(name for name, _ in ORDERS_RAW)


conn = sqlite3.connect("landing.db")
conn.execute("PRAGMA journal_mode=WAL")
# conn.execute("DROP TABLE IF EXISTS page_ledger") # Temp for dev rerun
conn.execute("DROP TABLE IF EXISTS orders_raw") # Temp for dev rerun
conn.executescript(SCHEMA_LEDGER)
conn.executescript(SCHEMA_ORDERS_RAW)
conn.commit()


def complete_page(resp: httpx.Response, cursor: str | None, page: int,
                  conn: sqlite3.Connection,
                  as_of_demand: str | None,
                  since: str | None = None,
                  until: str | None = None):
    payload = resp.json()
    conn.execute((f"INSERT INTO page_ledger ({', '.join(LEDGER_COLS[1:])}) "
                  f"VALUES ({', '.join('?' for _ in LEDGER_COLS[1:])});"),
            ("orders", page, datetime.datetime.now().isoformat(), "hasttemp",
            "succeeded", as_of_demand, payload["as_of"], since , until,
            cursor, payload["next_cursor"]))
    conn.commit()

def write_entry(entry: dict, conn: sqlite3.Connection,
                datepage, cursor, page):
    values = {
        "order_id": entry["order_id"],
        "customer_id": entry["customer_id"],
        "occurred_at": entry["occurred_at"],
        "channel": entry["channel"],
        "payment_method": entry["payment_method"],
        "shipping_speed": entry["shipping_speed"],
        "order_total_cents": entry["order_total_cents"],
        "items": json.dumps(entry["items"]),
        "version": entry["version"],
        "knowledge_time": entry["knowledge_time"],
        "content_hash": content_hash(
            {el: entry[el] for el in ORDERS_COLS if el in entry 
             and el != "knowledge_time"} | {
            "items": json.dumps(entry["items"])}),
        "received_at" : datepage,
        "source_cursor": cursor,
        "source_page": page
    }
    conn.execute((f"INSERT INTO orders_raw ({', '.join(ORDERS_COLS[1:])}) "
                  f"VALUES ({', '.join('?' for _ in ORDERS_COLS[1:])});"),
            tuple(values[col] for col in ORDERS_COLS[1:]))
    conn.commit()

## NOT DONE YET
def find_resume_point(conn, entity, since, until):
    row = conn.execute("""
        SELECT page_num, cursor, next_cursor, as_of_received
        FROM page_ledger
        WHERE entity = ? AND since = ? AND until = ?
        ORDER BY as_of_received DESC, page_num DESC
        LIMIT 1;
    """, (entity, since, until)).fetchone()
    if row is None:
        return (False, None, 0, None)
    if row["next_cursor"] == None:
        return (True, None, row["page_num"], row["as_of_received"])
    else:
        return (False, row["next_cursor"], row["page_num"], row["as_of_received"])


def auth_to_API(client: httpx.Client):
    resp = client.post(API_URL + "/v1/auth/token",
                   headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    live_token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {live_token}"

class NonRetryable(Exception):
    """Raised for a response we should not retry (4xx other than 401,
    malformed body, etc.)"""
    pass

class RetryableAuth(Exception):
    """401 - needs a fresh token, not a wait"""
    pass

class RetryableBackoff(Exception):
    """429/5xx - needs a wait, possibly server-specified"""
    def __init__(self, retry_after=None):
        self.retry_after = retry_after

def classify_response(resp: httpx.Response):
    """
    Look at a response and decide what family of outcome it is.
    Raises the appropriate exception, or returns normally if it's a success.
    """
    if resp.status_code == 200:
        return
    if resp.status_code == 401:
        raise RetryableAuth()
    if resp.status_code in (429, 500, 502, 503, 504):
        retry_after = resp.headers.get("retry-after")
        raise RetryableBackoff(
            retry_after=float(retry_after) if retry_after else None)
    raise NonRetryable(f"status {resp.status_code}: {resp.text[:200]}")

import random

def compute_backoff(tries: int, retry_after: float | None = None,
                     base: float = 0.2, max_delay: float = 10.0) -> float:
    if retry_after is not None:
        return retry_after
    delay = min(base * (2 ** tries), max_delay)
    jitter = random.uniform(0, delay * 0.1) 
    return delay + jitter

def fetch_page(client: httpx.Client,
               cursor: str | None,
               as_of: str | None = None,
               since: str | None = None,
               until: str | None = None):
    resp = client.get("v1/orders", 
                params={"limit":5,
                        **({"cursor": cursor} if cursor else {}),
                        **({"as_of": as_of} if as_of else {}),
                        **({"since": since} if since else {}),
                        **({"until": until} if until else {})})
    classify_response(resp)
    return resp

client = httpx.Client(base_url=API_URL, timeout=10,
                      mounts={"all://localhost": None,
                              "all://127.0.0.1": None})
auth_to_API(client)
# client.headers["Authorization"] = ""

cursor = None
as_of = "2027-01-31T00:00:00"
since = "2026-01-15T00:00:00"
until = "2026-01-25T00:00:00"
page = 1
max_retries = 5
tries = 0
orders = []
entry = []

this_pull = {
    "entity": "orders",
    "since": since,
    "until": until,
    "as_of": as_of,
}
while True:
    while tries < 5:
        try:
            resp = fetch_page(client, cursor, as_of, since, until)
            complete_page(resp, cursor, page, conn, as_of, since, until)
            datepage = datetime.datetime.now().isoformat()
            for el in resp.json()["data"]: 
                write_entry(el, conn, datepage, cursor, page)
            break
        except RetryableAuth:
            auth_to_API(client)
        except RetryableBackoff as e:
            tic = time.time()
            time.sleep(compute_backoff(tries, retry_after=e.retry_after))
        except NonRetryable as e:
            raise NonRetryable(f"page failed at cursor {cursor}") from e
        tries+=1
    else:
        raise RuntimeError(f"exhausted retries on page {page}")
    orders.extend(resp.json()["data"])
    cursor = resp.json()["next_cursor"]
    if page == 1:
        as_of = resp.json()["as_of"]
        this_pull["as_of"] = as_of
    tries = 0
    page += 1
    if cursor is None:
        break
print(this_pull)


# with open("orders_sample.jsonl", "w") as f:
#     for order in orders:
#         f.write(json.dumps(order) + "\n")



# def make_flaky_fetch_page(real_fetch_page, fail_pattern):
#     """
#     fail_pattern: a list of exceptions (or None for success) to return in order,
#     one per call. Once exhausted, falls back to real_fetch_page.
#     e.g. fail_pattern = [RetryableBackoff(), RetryableBackoff(), None]
#     forces two backoff failures then a real call on the third.
#     """
#     pattern = iter(fail_pattern)

#     def flaky_fetch_page(client, cursor):
#         try:
#             outcome = next(pattern)
#         except StopIteration:
#             return real_fetch_page(client, cursor)
#         if outcome is None:
#             return real_fetch_page(client, cursor)
#         raise outcome

#     return flaky_fetch_page

# fetch_page = make_flaky_fetch_page(
#     fetch_page,
#     fail_pattern=[
#         RetryableBackoff(retry_after=1.5),   # should sleep exactly 1.5s
#         RetryableBackoff(retry_after=None),  # should compute exponential+jitter
#         None,
#     ]
# )