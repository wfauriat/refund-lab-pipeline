# Progress log — refund-lab-pipeline

Updated 2026-09-11. Status snapshot, not a design doc — see `WORKING_MODE.md`
for collaboration style and `TUTOR.md` for the exercise spec.

## Done

**Environment**
- `uv`-managed project scaffold, `.venv`, `pyproject.toml`.

**Ingestion (orders only)**
- Package split: `config` / `client` / `db` / `schema` / `utils` / `ingest`.
- HTTP layer (`client.py`): `auth_to_API`, `classify_response`
  (401/429/5xx → typed exceptions), `fetch_page_with_retry` (backoff via
  `compute_backoff`, re-auth on 401).
- Cursor handling: `decode_cursor` (base64+JSON). Confirmed empirically that
  `rows_served`/`last_seen_value` count from the true start of the data
  horizon, not from `since`, and must never be compared against
  `total_count`.
- Chain reject-and-retry validation in `run_pull` (`ingest.py`): validates
  each page's `next_cursor.prev_*` against the request cursor's own
  `rows_served`/`last_seen_value`; retries up to `CHAIN_RETRY_LIMIT`, then
  raises `UncompletePull`.
- Landing store (`db.py`/`schema.py`, SQLite at `landing.db`): `page_ledger`
  and `orders_raw` tables. Dedup via `UNIQUE(order_id, version,
  content_hash)` + `INSERT OR IGNORE` on `orders_raw`, and
  `UNIQUE(entity, since, until, as_of_received, page_num)` +
  `INSERT OR REPLACE` on `page_ledger`.
- Logging: per-module `logger = logging.getLogger(__name__)`,
  `basicConfig` at the `ingest.py` entrypoint, `httpx`/`httpcore` loggers
  raised to `WARNING` to cut request-level noise, "N new orders added"
  summary logged from `write_entry`'s insert `rowcount`.

**Tests** (`uv run pytest -q` → 10/10 passing)
- `tests/test_client.py`: `fetch_page_with_retry` transport retry,
  `decode_cursor`, `classify_response`, and `run_pull`'s chain-retry logic
  (recover-from-one-bad-link, retry-exhaustion).
- `tests/test_db.py`: `write_entry` dedup on identical rows, restated
  version kept as a second row, `complete_page` replaces rather than
  erroring on a re-run of the same page.

**Transformation / SQL — layers 1 and 2 done**
- `landing.db` now holds 3,940 `orders_raw` rows (was 305) after pulling a
  larger horizon. 9 `order_id`s carry a real `version 1 → 2` restatement
  chain, deliberately produced by pulling the same `since`/`until` window
  twice at two different `as_of` values (`as_of` pins knowledge time
  independent of real-world call timing) — landing.db previously had zero
  multi-version orders even at 3,931 rows, so this was needed to have
  anything real to dedup against.
- `create_stg_orders` (`db.py`): 1:1 typed view over `orders_raw`. Casts
  `version` to `INTEGER` — it's declared `TEXT` in `schema.py`, which
  text-sorts wrong past single digits (`'10' < '2'`); not yet an active bug
  at version 1–2, but silently would be at version 10+ without this cast.
- `create_orders_current` (`db.py`): dedup view over `stg_orders`, one row
  per `order_id`, latest version wins — `WITH ranked AS (SELECT *,
  ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY version DESC,
  knowledge_time DESC) AS rn FROM stg_orders) SELECT <cols> FROM ranked
  WHERE rn = 1`. Verified against `ORD-00000325`'s real restatement chain
  (correctly returns version 2, not 1) and universally via
  `COUNT(*)`/`COUNT(DISTINCT order_id)` matching. Debugging history worth
  knowing for next time: a `WITH ... AS (...)` CTE needs a trailing
  outer `SELECT` referencing it — `incomplete input` if you forget it, since
  a window-function alias (`rn`) can't be filtered on on `WHERE` in the same
  `SELECT` that computes it; and `ORDER BY a, b DESC` only applies `DESC` to
  `b` — each sort column needs its own explicit direction.
- Neither view function needs `conn.commit()` — DDL (`CREATE`/`DROP VIEW`)
  autocommits under Python's default `sqlite3` transaction handling; only
  DML (`INSERT`/`UPDATE`/`DELETE`) needs an explicit commit to persist
  (confirmed and both trailing `conn.commit()` calls removed from the two
  `create_*` functions).
- `query_daily_volume` (`db.py`): daily order count + revenue by channel
  over `orders_current`, using `strftime('%Y-%m-%d', occurred_at) AS day`.
  Runs clean, returns 346 `(day, channel)` rows.

## Todo

**Ingestion — parked, revisit after the SQL/transformation track below**
- Wire up `find_resume_point` (written, unwired, commented out in
  `ingest.py`) so a restarted pull resumes from `page_ledger` instead of
  always starting at page 1.
- Replicate ingestion for `customers` (SCD2 — `valid_from`/`valid_to`
  changes the write pattern, not just the schema), `events`, `labels`.
- Drop-file ingestion for `payments`/`products` (gzip or plain CSV, no
  manifest/checksum, arrival-time uncertainty — `late_partition`/
  `missing_delivery`/`partial_write` all live here).
- Generalize/abstract the puller once a second entity exists — not before.
- Confirm the client survives a hostility level raise (currently untested
  above whatever the default level is).

**Transformation / SQL — active track**
1. **Interpret `query_daily_volume`'s output** — the query runs, but nobody
   has yet looked at the 346 rows against TUTOR.md's baseline claims
   (weekday ~full, weekend ~three-quarters, autocorrelated shocks). This is
   the actual point of the exercise, not the SQL mechanics — pick this up
   first next session. 346 raw rows may be easier read as a further
   rollup (e.g. weekday-vs-weekend averages) than eyeballed directly.
2. Bitemporal reconstruction: "what did we believe as of date X", filtering
   on `knowledge_time` instead of `occurred_at`. Can't be a plain view in
   SQLite (views take no parameters) — will need a parameterized query.
3. Cross-channel reconciliation (orders/payments/labels) — needs payments
   and labels landed first.

**Orchestration** — not started. Scheduled, unattended, with monitoring
that would surface an incident on its own.

**Serving** — not started. Refund-risk score per order, defensible against
leakage (`leakage_column`) and censoring (`label_censoring`).

**Incident log** — `incidents.jsonl` does not exist yet. This is the actual
graded deliverable per `TUTOR.md`; monitoring/checks should start
surfacing entries from the baseline-characterization step onward, not be
deferred to the orchestration phase.
