# JSON → SQLite migration

How the storage change works, how to verify it, and how to cut over and roll
back.

Shell snippets use placeholders for anything deployment-specific:

| | |
|---|---|
| `$APP_ROOT` | the repo checkout on the server |
| `$APP_DIR` | the inner `osrs-event-log` directory — **the working directory is load-bearing**, every path is built from `pathlib.Path().absolute()` |
| `$APP_VENV` | the virtualenv |
| `$BACKUP_DIR` | where backups land |
| `$OPS_SCRIPTS` | wherever `backup-json.sh` / `backup-db.sh` live |

---

## Why

State was two whole-file JSON documents rewritten in full on every change:

| file | size | contents |
|---|---|---|
| `data/db_runescape.json` | 470 KB | 69 players, current skills + minigames |
| `data/db_discord.json` | 326 KB | flat key-value store, 674 composite-string keys |
| `data/sotw/sotw_config.json` | | skill-of-the-week state |
| `data/botw/botw_config.json` | | boss-of-the-week state |

That works, but it cannot answer "show me this player's Slayer XP over the last
year" or "what happened in this server yesterday", which is what a read-only web
UI needs. It also had a real bug: the looper buffered every player's stats in
memory and wrote the whole file once at the end of a cycle, so a process killed
mid-loop had already posted to Discord but recorded nothing, and the next cycle
re-posted the same milestones.

---

## What changed

```
data/schema.sql            16 tables, 5 views
data/repo/                 plain functions over SQLite, no discord.py
data/handlers/             unchanged signatures, now thin adapters over repo
common/util.py             hiscore_value() -> hiscore_int(), + format_rank_str()
activity/PlayerUpdate.py   integer comparisons, formatting moved to display time
cogs/looper.py             one change: per-player transactional save
cogs/dink_webhook.py       one addition: record the event
cogs/cmds/*                untouched
```

The database lives at `data/osrs.db`. It is gitignored — **the droplet holds the
only copy**, same as the JSON files did.

### Values are integers now

The JSON stored numbers the way the old scraped HTML hiscores page rendered
them: `"102,315,637"`, and `'--'` for unranked. The database stores real
integers with `NULL` for unranked, and all comma formatting happens at display
time via `util.format_int_str()` / `util.format_rank_str()`.

This is the highest-risk part of the change. Change detection compares stored
against fetched, so if the two disagree by so much as a formatting detail, every
skill of every player reads as changed and the bot posts a milestone for all of
them, in every server, with no rate limit and no undo. T2 below exists
specifically to prove that cannot happen.

### `NULL` means "the key was absent"

Not false, and not zero. 52 of 87 player-server links have no `botw_opt` and 2
have no `sotw_opt`, because those fields were added after the rows were created;
the bot already tolerated that with `try`/`except`. Storing `NULL` preserves the
absence so the reverse export can omit the key again. Every read path
`COALESCE`s to the default.

### Two views worth knowing about

`pollable_players` is the guard against a mass-spam event, and **the looper must
select from it, never from `players`**. 12 players sit in a server's player list
with no `db_runescape.json` entry and have never been polled, because the old
looper iterated the runescape file rather than the player list. Polling them
would make every skill read as new and post *"This is the first time this skill
is on the Hiscores"* for each of them at once.

It filters on `players.tracked`, not on "has stat rows". A few players are
tracked with an **empty** skills dict — a leftover from when the HTML page
returned 200 for a nonexistent RSN and `;add` accepted it — and the old looper
does poll them. The view was verified to return exactly the same set of players
the old code polled, by set comparison rather than by count.

`v_sotw_standings` / `v_botw_standings` replace a Python loop that rebuilt all
288 of a server's weeks on every `;sotw stats` call.

---

## Verify before cutting over

All of these run offline: **no Discord token, no network, nothing written to the
source data**. Run them from the inner `osrs-event-log` directory.

```bash
python tools/test_roundtrip.py     # T1
python tools/test_repo_parity.py
python tools/test_zero_delta.py    # T2
python tools/test_golden_diff.py   # T3
python tools/test_events.py
python tools/test_super_user.py
```

| test | proves |
|---|---|
| **T1 round-trip** | JSON → SQLite → JSON reproduces the input exactly. This is also the rollback guarantee. |
| **repo parity** | The repo layer answers what the JSON said — every stat value, link, membership and standing. |
| **T2 zero-delta** | Replaying every player against their own stored data produces **0 changes and 0 messages**. Directly proves the migration cannot spam. |
| **T3 golden diff** | A pristine pre-migration tree and the working tree, fed identical frozen payloads, emit **byte-identical** Discord messages. |
| **events** | Recording works, and a broken database cannot stop a message reaching Discord. |
| **super user** | The owner-only check fails closed when `SUPER_USER_ID` is missing. |

### T5, the one that hits the network

```bash
python tools/test_live_readonly.py --data-dir fixtures/live-YYYY-MM-DD
python tools/test_live_readonly.py --limit 10     # smaller sample first
```

Everything above replays stored or synthetic data. T5 fetches real hiscores for
every pollable player and runs the real comparison against real migrated state,
posting nothing and writing nothing. It is the only check that exercises
fetch → parse → compare end to end against what Jagex returns today, which is
where a parser assumption would surface.

It fails if more than half the successfully-fetched players report changes —
that is the spam signature, not a busy week.

A healthy run looks like this (measured on current state, and matching the
pre-migration baseline on fetch failures):

```
70 polled
55 skipped, Overall xp unchanged
 3 walked every skill, nothing differed
12 fetch failed (404 / not on the hiscores)
 0 with real updates
 0 messages, 0 errors
```

Zero updates is normal right after the live bot has polled. It also means T5
does not exercise the milestone paths — T3 and `tools/scenarios.py` cover those.

### T3 is the one that matters most

T2 proves nothing *looks* changed. It cannot see a milestone that has stopped
firing. Storing integers breaks three things silently — no exception, no log
line:

```python
level == '99'                            # never true -> no 99 milestones
str(level) in custom_messages['levels']  # keys are strings -> no joke messages
f"... {new_data['rank']}"                # renders None or -1, not '--'
```

The old "53 of 70 players skipped" health check could never have caught any of
them. T3 builds the pre-migration tree with `git archive` from
`git merge-base master HEAD` and diffs the actual message text.

It has been verified to fail when it should: temporarily reverting `max_lvl = 99`
to `'99'` makes it report the 99 milestone demoted out of `milestones` and the
custom max-level message gone.

Base players are chosen by profile (richest / sparsest / lowest-xp / no-Overall /
has-unranked) so the "first time" and low-threshold scenarios cannot silently
drop out, and the test prints any scenario no base player could cover.

### Against live data

The tests default to `data/`. To run them against a fresh pull from the droplet:

```bash
scp -r <deploy-user>@<host>:$APP_DIR/data \
    fixtures/live-$(date +%F)
python tools/test_roundtrip.py --data-dir fixtures/live-YYYY-MM-DD
```

`fixtures/` is gitignored.

---

## Cutover

Roughly 10 seconds of downtime, which is what a normal deploy restart already
costs. **Dink does not retry**, so anything a RuneLite client posts during the
window is lost — do it at a quiet hour.

```bash
# 0. locally: all tests green against a fresh pull of live data

ssh <deploy-user>@<host>

# 1. take a backup of the JSON state first
$OPS_SCRIPTS/backup-json.sh \
    $APP_DIR \
    $BACKUP_DIR 14

# 2. stop the bot
sudo systemctl stop osrs-event-log

# 3. get the new code
git -C $APP_ROOT pull

# 3b. add SUPER_USER_ID to bot_config.json — see below. Skipping this does not
#     stop the bot, it just denies the owner-only commands.

# 4. migrate. --report writes nothing and prints what it would do
cd $APP_DIR
$APP_VENV/bin/python tools/migrate_json_to_sqlite.py --report
$APP_VENV/bin/python tools/migrate_json_to_sqlite.py --db data/osrs.db

# 5. verify on the real data before starting
$APP_VENV/bin/python tools/test_roundtrip.py
$APP_VENV/bin/python tools/test_zero_delta.py
$APP_VENV/bin/python tools/test_live_readonly.py

# 6. start
sudo systemctl start osrs-event-log
journalctl -u osrs-event-log -f -o cat | grep --line-buffered -v ' - DEBUG - '
```

**The migration aborts rather than guessing.** Any `db_discord.json` key it does
not recognise lands in `legacy_kv` with `reason='unrecognised'` and stops the
run. If live data has grown a key pattern that was not present when this was
written, step 4 fails loudly instead of silently dropping it. Do not reach for
`--allow-unknown` without reading what it found.

### Watch the first cycle

The looper runs every 20 minutes. A healthy first cycle looks like the
2026-08-04 baseline:

```
~53 players skipped ("Overall xp unchanged")
 ~5 players with real updates
~12 fetch failures / not on the hiscores
  0 crashes
```

**If most players report many changed skills, stop the service immediately.**
That is the formatting contract broken and it is about to post a milestone for
every skill of every player in every server.

```bash
sudo systemctl stop osrs-event-log
```

### New config key: `SUPER_USER_ID`

The bot owner's Discord id used to be hardcoded in 14 places across
`cogs/cmds/admin.py` and `cogs/cmds/super.py`. It now comes from
`bot_config.json`, which is gitignored — this repo is public.

```json
{
  "BOT_TOKEN": "...",
  "SUPER_USER_ID": 123456789012345678,
  ...
}
```

The check **fails closed**: if the key is missing or unparseable,
`is_super_user()` returns False for everyone. An unset key therefore locks the
owner out of `;servers`, `;message` and `;maxplayers` rather than granting them
to every user. `helpers.py` reads it with `.get()`, so an older config without
the key still starts normally.

`tools/test_super_user.py` covers both directions, including ids quoted as
strings — Discord snowflakes exceed 2^53, so a config that quotes them must
still match.

### Leave the JSON files in place for 14 days

Do not delete `db_discord.json` or `db_runescape.json` at cutover. They are the
rollback source, and `ensure_db()` uses their presence as a safety check: if
`data/osrs.db` is missing while they still exist, the bot **refuses to start**
rather than coming up with an empty database and rebuilding state on top of live
data.

---

## Rollback

The migration is reversible. `tools/export_sqlite_to_json.py` rebuilds the JSON
files, and T1 is what proves it round-trips.

If the JSON files are still in place (within the 14-day window), rolling back is
just code:

```bash
sudo systemctl stop osrs-event-log
git -C $APP_ROOT checkout <pre-migration-commit>
sudo systemctl start osrs-event-log
```

Anything that happened after the cutover is lost, which for a 20-minute poll
loop is at most one cycle of milestones.

To keep post-cutover changes instead, export first:

```bash
cd $APP_DIR
$APP_VENV/bin/python tools/export_sqlite_to_json.py \
    --db data/osrs.db --out data --force
```

List order and JSON key order will differ from the originals; nothing reads
either as ordered except SOTW/BOTW history, which is preserved exactly via the
`seq` column.

---

## Backups

Switch the `deploy` crontab from `backup-json.sh` to `backup-db.sh`:

```cron
# remove
20 3 * * * $OPS_SCRIPTS/backup-json.sh $APP_DIR $BACKUP_DIR 14 >> $BACKUP_DIR/backup.log 2>&1

# add
20 3 * * * $OPS_SCRIPTS/backup-db.sh $APP_DIR/data/osrs.db $BACKUP_DIR 14 >> $BACKUP_DIR/backup.log 2>&1
```

This is an improvement, not just a swap: `backup-db.sh` uses `sqlite3 .backup`,
which takes an atomic snapshot of a live database. `backup-json.sh` had no such
guarantee — the bot rewrote JSON with a plain truncate-and-write, so a backup
could in principle catch a partial file.

Keep `backup-json.sh` in the crontab until the JSON files are deleted, so the
rollback source is backed up too.

---

## Notes for the web UI

Not built yet. The schema is shaped so it does not need to be designed around.

- It should be a separate service on its own port, behind the same reverse
  proxy, and must not share a process with the bot.
- Import `data.repo` directly. It has no discord.py dependency, which is the
  whole reason the repo/adapter split exists.
- Open the database read-only (`file:...?mode=ro`). WAL means a reader never
  blocks the bot's writes.
- `v_player_skills`, `v_player_activities`, `v_sotw_standings` and
  `v_botw_standings` exist so the UI owns no query logic.
- History starts at the migration date. There is no historical XP anywhere in
  the JSON to backfill — the migration seeds one row per current value so a
  chart has an origin point, and the series grow from there at roughly 400k
  rows/year.
- `events.title` is `NULL` for hiscores events for now; the message text carries
  the skill or boss name. Filling it in is additive.
