# Progress log — refund-lab-pipeline

Updated 2026-09-10. Status snapshot, not a design doc — see `WORKING_MODE.md`
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

**Transformation / SQL — active track, starting now**
1. Baseline characterization query over `orders_raw` (daily volume, channel
   mix) — assigned, not yet run.
2. Conformed "current state" view: one row per `order_id`, latest version
   wins (window functions — `ROW_NUMBER()`/`PARTITION BY`). Note: as of
   this snapshot no `order_id` in `orders_raw` yet has two rows at
   different versions, so this won't change row counts on today's data —
   expected to start mattering as more simulated days land.
3. Bitemporal reconstruction: "what did we believe as of date X", filtering
   on `knowledge_time` instead of `occurred_at`.
4. Cross-channel reconciliation (orders/payments/labels) — needs payments
   and labels landed first.

**Orchestration** — not started. Scheduled, unattended, with monitoring
that would surface an incident on its own.

**Serving** — not started. Refund-risk score per order, defensible against
leakage (`leakage_column`) and censoring (`label_censoring`).

**Incident log** — `incidents.jsonl` does not exist yet. This is the actual
graded deliverable per `TUTOR.md`; monitoring/checks should start
surfacing entries from the baseline-characterization step onward, not be
deferred to the orchestration phase.
