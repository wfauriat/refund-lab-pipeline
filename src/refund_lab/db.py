import datetime
import sqlite3
import json
import logging

from .utils import content_hash
from .config import LANDING_DB
from .schema import (LEDGER, LEDGER_COLS, SCHEMA_LEDGER,
                     ORDERS_RAW, ORDERS_COLS, SCHEMA_ORDERS_RAW)


logger = logging.getLogger(__name__)

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
                datepage, cursor, page) -> bool:
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
    cur = conn.execute((f"INSERT OR IGNORE INTO orders_raw ("
                  f"{', '.join(ORDERS_COLS[1:])}) "
                  f"VALUES ({', '.join('?' for _ in ORDERS_COLS[1:])});"),
            tuple(values[col] for col in ORDERS_COLS[1:]))
    # Does not commit on purpose, complete page does the commit after all rows
    return bool(cur.rowcount)


def create_stg_orders(conn: sqlite3.Connection):
    conn.execute(f"DROP VIEW IF EXISTS stg_orders;")
    conn.execute(f"CREATE VIEW stg_orders AS "
                 f"SELECT order_id, customer_id, occurred_at, "
                 f"channel, payment_method, "
                 f"shipping_speed, order_total_cents, knowledge_time, "
                 f"content_hash, CAST(version AS INTEGER) AS version "
                 f"FROM orders_raw")
    # Default : DDL does commit on default, DML does not. 


def create_orders_current(conn: sqlite3.Connection):
    # CTE (WITH ranked AS (...)): a named, query-scoped temp result.           
    # ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...): window function —     
    # numbers rows within each order_id group without collapsing them,         
    # so the outer SELECT can filter to rn = 1 (latest version per order).  
    conn.execute(f"DROP VIEW IF EXISTS orders_current")
    conn.execute(f"CREATE VIEW orders_current AS "
                 f"WITH ranked AS ("
                 f"SELECT *, "
                 f"ROW_NUMBER() OVER (PARTITION BY order_id "
                 f"ORDER BY version DESC, knowledge_time DESC) AS rn "
                 f"FROM stg_orders) "
                 f"SELECT order_id, customer_id, occurred_at, "
                 f"channel, payment_method, shipping_speed, "
                 f"order_total_cents, knowledge_time, content_hash, "
                 f" version FROM ranked WHERE rn = 1;")

def query_daily_volume(conn: sqlite3.Connection) \
    -> list[tuple[str, str, int, int]]:
    QUERY_DAILY_VOLUME = """
    SELECT strftime('%Y-%m-%d', occurred_at) AS day, channel, 
    COUNT(*) AS count,
    SUM(order_total_cents) AS total_cents
    FROM orders_current
    GROUP BY day, channel
    ORDER BY day ASC, channel DESC;
    """
    cursor = conn.execute(QUERY_DAILY_VOLUME)
    result = []
    for row in cursor.fetchall():
        date, channel, count, total_cents = row
        result.append((date, channel, count, total_cents))
    return result


def query_weekday_weekend_split(conn: sqlite3.Connection) -> \
    list[tuple[str, int, int, float]]:
    QUERY_WEEKDAY_WEEKEND_SPLIT = """
    WITH per_dow AS (
        SELECT strftime('%w', occurred_at) AS dow, 
            COUNT(*) AS n,
            COUNT(DISTINCT strftime('%Y-%m-%d', occurred_at)) AS n_days
        FROM orders_current GROUP BY dow )
    SELECT CASE WHEN dow IN ('0', '6') THEN 'weekend' 
        ELSE 'weekday' END AS bucket,
        SUM(n) AS total_orders,
        SUM(n_days) AS total_days,
        ROUND(SUM(n) * 1.0 / SUM(n_days), 2) AS avg_orders_per_day
    FROM per_dow GROUP BY bucket;    
    """
    cursor = conn.execute(QUERY_WEEKDAY_WEEKEND_SPLIT)
    result = []
    for row in cursor.fetchall():
        bucket, total_orders, total_days, avg_orders_per_day = row
        result.append((bucket, total_orders,
                       total_days, avg_orders_per_day))
    return result

def query_orders_as_of(conn: sqlite3.Connection, as_of: str) -> list:
    QUERY_ORDERS_AS_OF = """
    WITH ranked AS (
        SELECT *,
                ROW_NUMBER() OVER (
                PARTITION BY order_id ORDER BY version DESC,
                knowledge_time DESC) AS rn
        FROM stg_orders
        WHERE knowledge_time <= ?
    )
    SELECT order_id, customer_id, occurred_at, 
           channel, payment_method, shipping_speed, 
           order_total_cents, knowledge_time, content_hash, 
           version FROM ranked 
    WHERE rn = 1
    """
    cursor = conn.execute(QUERY_ORDERS_AS_OF, (as_of,))
    result = []
    for row in cursor.fetchall():
        result.append(row)
    return result