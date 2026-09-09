import httpx
import sqlite3
import datetime
import json


from .config import API_URL
from .client import auth_to_API, fetch_page_with_retry, decode_cursor
from .db import init_db, complete_page, write_entry

CHAIN_RETRY_LIMIT = 3

class UncompletePull(Exception):
    """ Pull could not complete all the way through
    """
    pass

def run_pull(entity: str, since: str, until: str, as_of: str,
             conn: sqlite3.Connection, client: httpx.Client) -> dict:
    page = 1
    orders = []
    cursor = None
    this_pull = {
        "entity": entity,
        "since": since,
        "until": until,
        "as_of": as_of,
        "orders": []
    }
    while True:
        for attempt in range(CHAIN_RETRY_LIMIT):
            payload = fetch_page_with_retry(client, entity, cursor,
                                    as_of, since, until)
            if cursor is None or payload["next_cursor"] is None:
                break
            this_position = decode_cursor(payload["cursor"])
            assert this_position is not None
            claimed_prev = decode_cursor(payload["next_cursor"])
            assert claimed_prev is not None
            if (claimed_prev["prev_rows_served"] == \
                this_position["rows_served"]) & \
                (claimed_prev["prev_last_seen_value"] == \
                this_position["last_seen_value"]):
                break
        else:
            raise UncompletePull(f"Could not complete pull at page {page} "
                        f"from cursor {json.dumps(decode_cursor(cursor))}")
        data = payload["data"]
        timestamp = datetime.datetime.now().isoformat()
        for row in data: 
            write_entry(row, conn, timestamp, cursor, page)
        complete_page(conn, payload, entity,
                        cursor, page, as_of, since, until)
        orders.extend(payload["data"])            
        cursor = payload["next_cursor"]
        if page == 1:
            as_of = payload["as_of"]
            this_pull["as_of"] = as_of
        page += 1
        if cursor is None:
            break
    this_pull["orders"] = orders
    return this_pull


if __name__ == "__main__":

    conn = init_db()

    client = httpx.Client(base_url=API_URL, timeout=10,
                        mounts={"all://localhost": None,
                                "all://127.0.0.1": None})
    auth_to_API(client)

    entity = "orders"
    as_of = "2027-01-31T00:00:00"
    since = "2026-01-15T00:00:00"
    until = "2026-01-25T00:00:00"
    pulled = run_pull(entity, since, until, as_of,
             conn, client)
    print(pulled["orders"][0])




## NOT DONE YET
# def find_resume_point(conn, entity, since, until):
#     row = conn.execute("""
#         SELECT page_num, cursor, next_cursor, as_of_received
#         FROM page_ledger
#         WHERE entity = ? AND since = ? AND until = ?
#         ORDER BY as_of_received DESC, page_num DESC
#         LIMIT 1;
#     """, (entity, since, until)).fetchone()
#     if row is None:
#         return (False, None, 0, None)
#     if row["next_cursor"] == None:
#         return (True, None, row["page_num"], row["as_of_received"])
#     else:
#         return (False, row["next_cursor"], row["page_num"], row["as_of_received"])
