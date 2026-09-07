import httpx
import time
import json
import itertools
import sqlite3
import datetime



PORT = "8088"
API_URL = "http://127.0.0.1:" + PORT
DEV_TOKEN = "rl_live_8f2c1d94e6b74a03"

SCHEMA_LEDGER = """
CREATE TABLE IF NOT EXISTS page_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT,
    cursor TEXT,
    next_cursor TEXT,
    page_num INT NOT NULL,
    fetched_at TEXT,
    payload_hash TEXT,
    status TEXT
);
"""
SCHEMA_ORDERS_RAW = """
CREATE TABLE IF NOT EXISTS orders_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT,
    order_id TEXT NOT NULL,
    customer_id TEXT,
    occurred_at TEXT,
    channel TEXT,
    payment_method TEXT,
    shipping_speed TEXT,
    order_total_cents INT,
    items TEXT,
    version TEXT,
    knowledge_time TEXT,
    received_at TEXT,
    source_cursor TEXT,
    source_page TEXT,
    UNIQUE (order_id, version, content_hash)
);
"""

conn = sqlite3.connect("landing.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.executescript(SCHEMA_LEDGER)
conn.executescript(SCHEMA_ORDERS_RAW)
conn.commit()

def complete_page(resp: httpx.Response, cursor: str | None,
                  page: int,
                  conn: sqlite3.Connection):
    conn.execute("""
    INSERT INTO page_ledger (entity, cursor, next_cursor,
                            page_num, fetched_at, payload_hash,
                            status) VALUES (?,?,?,?,?,?,?);
    """,
    ("orders", cursor, resp.json()["next_cursor"], page, 
       datetime.datetime.now().isoformat(),
         "hash1123", "succeeded"))
    conn.commit()


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

def fetch_page(client, cursor):
    resp = client.get("v1/orders", params={
            "limit":5, **({"cursor": cursor} if cursor else {})})
    classify_response(resp)
    return resp

client = httpx.Client(base_url=API_URL, timeout=10,
                      mounts={"all://localhost": None,
                              "all://127.0.0.1": None})
auth_to_API(client)
# client.headers["Authorization"] = ""

cursor = None
page = 1
max_retries = 5
tries = 0
orders = []
entry = []

while True:
    while tries < 5:
        try:
            resp = fetch_page(client, cursor)
            complete_page(resp, cursor, page, conn)
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
    tries = 0
    page += 1
    if cursor is None:
        break



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