LEDGER = (("id", "INTEGER PRIMARY KEY AUTOINCREMENT"), ("entity", "TEXT"),
          ("page_num", "INT NOT NULL"), ("fetched_at", "TEXT"),
          ("payload_hash", "TEXT"), ("status", "TEXT"),
          ("as_of_demand", "TEXT"), ("as_of_received", "TEXT"), ("since", "TEXT"),
          ("until", "TEXT"), ("cursor", "TEXT"),
          ("next_cursor", "TEXT")  )

SCHEMA_LEDGER = "CREATE TABLE IF NOT EXISTS page_ledger (\n  " + \
    ",\n  ".join(f"{name} {decl}" for name, decl in LEDGER) + \
    ",\n " + "UNIQUE (entity, since, until, as_of_received, page_num));"

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
