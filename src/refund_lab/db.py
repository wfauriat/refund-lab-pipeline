import datetime
import sqlite3
import json

from .utils import content_hash
from .config import LANDING_DB
from .schema import (LEDGER, LEDGER_COLS, SCHEMA_LEDGER,
                     ORDERS_RAW, ORDERS_COLS, SCHEMA_ORDERS_RAW)

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(LANDING_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    # conn.execute("DROP TABLE IF EXISTS page_ledger") # Temp for dev rerun
    # conn.execute("DROP TABLE IF EXISTS orders_raw") # Temp for dev rerun
    conn.executescript(SCHEMA_LEDGER)
    conn.executescript(SCHEMA_ORDERS_RAW)
    conn.commit()
    return conn


def complete_page(conn: sqlite3.Connection,
                  payload: dict, entity: str,
                  cursor: str | None, page: int,
                  as_of_demand: str | None,
                  since: str | None = None,
                  until: str | None = None):
    conn.execute((f"INSERT OR REPLACE INTO page_ledger ("
                  f"{', '.join(LEDGER_COLS[1:])}) "
                  f"VALUES ({', '.join('?' for _ in LEDGER_COLS[1:])});"),
            (entity, page, datetime.datetime.now().isoformat(),
             content_hash(payload),
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
        "content_hash": content_hash({k: v for k, v in entry.items() if
                                       k != "knowledge_time"}),
        "received_at" : datepage,
        "source_cursor": cursor,
        "source_page": page
    }
    conn.execute((f"INSERT OR IGNORE INTO orders_raw ("
                  f"{', '.join(ORDERS_COLS[1:])}) "
                  f"VALUES ({', '.join('?' for _ in ORDERS_COLS[1:])});"),
            tuple(values[col] for col in ORDERS_COLS[1:]))