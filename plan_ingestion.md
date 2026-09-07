Good place to pause. Here's the path ahead, as a checklist you can hand to your next session (or just keep for yourself):

**1. Wire the hash + insert logic**
- `compute_content_hash(order)` — vendor fields only, `sort_keys=True`, `sha256`.
- `compute_payload_hash(raw_response_body)` — same idea, page granularity.
- Insert function for `orders_raw`: try `INSERT`, catch `sqlite3.IntegrityError` (true duplicate), let genuine divergence through as a new row.

**2. Wire the ledger bookkeeping into the pagination loop**
- Before each page fetch: write an `attempting` row (cursor, page_num, entity).
- After success: update to `succeeded`, fill in `next_cursor`, `payload_hash`.
- On startup: query `page_ledger` for the last `succeeded` row, resume from its `next_cursor` instead of `None`.
- Decide: check `payload_hash` before unpacking a page (skip re-processing if you've already fully landed this exact delivery).

**3. Unpack pages into rows**
- For each page response, iterate `data[]`, compute hash, insert one row per order into `orders_raw` — not one row per page.

**4. Test crash-resume for real**
- Kill the script mid-run (Ctrl+C or a forced exception) partway through a pull.
- Rerun it. Confirm: no gaps, no unwanted duplicate rows, ledger correctly identifies where to resume.

**5. Basic sanity checks on landed data**
- Row counts per day, matched loosely against what you'd expect.
- Spot-check that a known restatement (if you catch one) produced two distinct rows, not a silent overwrite.

**6. Only after orders is solid — generalize**
- Extend the same pattern to `customers`, `events`, `labels` (all API-channel, same pagination/auth mechanics).
- Then payments/products — different channel entirely (daily file drops, no cursor/auth), will need genuinely new ingestion logic, not just a copy-paste of what you have.

**7. Testing, formalized**
- Move `compute_backoff`, hash functions, and retry-branch logic into a proper test file (you flagged this earlier and deferred it — good time to circle back).

**8. Keep the incident-log habit running in parallel**
- Anything odd you noticed during this session (mojibake, unexpected nulls, type drift, the restatement you haven't caught yet) — log it now if you haven't, dated to when you actually noticed it, not backdated.

That's phase 1 (ingestion) essentially complete once steps 1–4 are solid; steps 5–8 are the bridge into phase 2 (landing/storage) and good ongoing hygiene. Good session — you built and defended a real design, not just code that happened to run.