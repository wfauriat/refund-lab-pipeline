# Companion plan — landing layer, post cursor-internals session

For the next tutor session. Read alongside TUTOR.md. The user asked for this
to be written *for the next session*, not for themselves to read — so it's
fine to be direct/technical here in a way you'd pace out more slowly in
conversation with them.

## State entering this plan

- `page_ledger` and `orders_raw` schemas exist. `cursor` column had its
  `NOT NULL` removed (page 1 legitimately has no cursor) — user found this
  themselves after hitting the constraint violation.
- `complete_page()` is wired: one `page_ledger` row per page fetch, via
  `conn.execute` (they initially tried `executescript`, which doesn't take
  params — corrected), commits after insert.
- User manually decoded cursor payloads via a second shell
  (`sqlite3 landing.db "SELECT cursor FROM page_ledger WHERE id=N;" | base64 -d`)
  and empirically identified the cursor's internal fields themselves (not
  told to them):
  - `a` = as_of pinned at pull start
  - `n` = total count claimed (cross-checked against page_count*limit —
    consistent modulo a partial last page)
  - `r` = cumulative rows served so far (running offset, +limit per page)
  - `v` = keyset position (last `occurred_at` seen — pagination is keyset on
    valid time, not pure offset)
  - `pr` / `pv` = the `r` / `v` of the *previous* page (present from page 2
    onward)
  - `t` = entity name
- Not yet built: `orders_raw` row-level insert/unpack, run/pull identity
  columns, incremental watermark logic, pr/pv validation.

## Decisions the user made this session (A/B/C framing from the tutor's prior
message — do not re-litigate, just help implement)

- **A — pull identity: denormalized.** Add `since`, `until`, `as_of` columns
  directly to `page_ledger`. A "pull" = one `(entity, since, until, as_of)`
  tuple.
  - Resolved sub-question (this is the one they asked about pagination):
    `as_of` must be computed **once** at pull start and reused for every page
    of that pull, not re-fetched as "now" per request. This is what makes the
    tuple a stable resume key, and what naturally scopes `page_num` to reset
    to 1 per pull rather than accumulating globally.
  - Resume logic: on startup, look for the latest `page_ledger` row whose
    `(entity, since, until, as_of)` matches the pull about to run. If its
    chain is incomplete, resume from its `next_cursor`. Otherwise start fresh
    (`page_num=1`, `cursor=NULL`).
- **B — incremental strategy: windowed with a trailing buffer.** Next pull's
  `since` = last watermark minus an explicit safety margin (their call on
  size — start generous, tune down once they've measured actual knowledge lag
  from `knowledge_time` vs `occurred_at` deltas on landed rows). `until`
  stays open/absent. A periodic full-reconciliation re-pull is a known,
  deliberately deferred gap — flag it, don't silently build it in.
- **C — pr/pv validation: reject and retry.** Before landing a page, compare
  its cursor's `pr`/`pv` to the `r`/`v` recorded in the ledger for what
  should be the immediately preceding page of *this pull*. Mismatch → don't
  insert, retry from the last confirmed-good cursor. Still open, and worth
  raising with them: how many retries before giving up and logging an
  incident instead of looping forever? Don't decide this for them — ask.

## Suggested next-session progression

Keep the pace this session used: one small piece, verified by hand in a
second `sqlite3` shell, before adding the next. Do not hand over the
insert/query code wholesale — walk them to it the way `complete_page` was
built (they write a first attempt, you point at what breaks and why).

1. Migrate `page_ledger` to add `since`, `until`, `as_of` columns. Good
   moment to let them hit, unprompted, that `CREATE TABLE IF NOT EXISTS`
   does *not* alter an existing table's columns — they'll need
   `ALTER TABLE ... ADD COLUMN` or to drop/recreate. Let them discover which
   applies given they already have real data landed.
2. Compute `as_of` once at pull start (e.g. capture a timestamp, or hit
   `/v1/health`, before the pagination loop begins) and thread it through
   `complete_page`'s insert alongside `since`/`until` (both `None`/absent is
   a legitimate first value — that's the initial full pull).
3. Write the "find resume point" query by hand in the sqlite shell first:
   given `(entity, since, until, as_of)`, does an incomplete matching pull
   exist? Only wire it into the script's startup once they've seen it return
   the right row against data they already have.
4. `orders_raw` unpacking (already pending before this session) — one insert
   per order in `data[]`, using the `(order_id, version, content_hash)`
   unique key they chose deliberately (landing philosophy: let genuine
   content divergence at the same version land as a second row rather than
   arbitrating at ingest time — they own that trade-off, don't re-open it
   unless something they observe makes them want to revisit it).
5. Only then add the `pr`/`pv` check (C) — it depends on the previous page's
   `r`/`v` already being in the ledger, so it's naturally last of these four.
6. Crash-resume test (kill mid-pull, rerun, confirm `page_ledger` +
   `orders_raw` show no gaps/dupes) — this was step 4 in the original
   `plan_ingestion.md`; still the right acceptance test, now against the
   richer schema.
7. Incident-log reminder: prompt them to log anything odd noticed while
   building this (a pr/pv mismatch actually firing, a resume picking the
   wrong pull, an unexpected content-hash divergence) dated to when they
   actually noticed it.

## Tutoring notes carried forward

- User's working style: wants small, single verified steps. Understands the
  design discussion and trade-offs fine in the abstract, but has a hard time
  converting a design decision into the *first* concrete line of code —
  expect to need to restate the immediate next action even right after they
  agreed to a design, don't assume the translation is obvious to them. This
  is not a comprehension gap, it's a "blank page" friction — meet it with a
  narrower next step, not a longer explanation.
- They're comfortable inspecting state via a second `sqlite3` shell
  concurrently with the running script (WAL mode already enabled) — keep
  leaning on that as the verification loop; it's working well for them.
- If B's late-knowledge-arrival trap comes up again, re-derive the "why"
  explicitly (naive watermark advance on `occurred_at` permanently drops
  late-`knowledge_time` records) — it wasn't obvious to them until walked
  through, don't assume it's retained.
