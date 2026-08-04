-- osrs-event-log — SQLite schema
--
-- Replaces data/db_discord.json, data/db_runescape.json,
-- data/sotw/sotw_config.json and data/botw/botw_config.json.
--
-- Two conventions run through the whole file; both exist to make the JSON
-- round-trip exact, and both matter when reading this later:
--
--   1. NULL MEANS "THE JSON KEY WAS ABSENT", not "false" and not "zero".
--      The live data is missing `botw_opt` on 52 of 87 player-server links and
--      `sotw_opt` on 2 of them, because those fields were added after the rows
--      were created. The bot already tolerates that with try/except. Storing
--      NULL preserves the absence, so the reverse export can omit the key again
--      and the round-trip test passes. Every read path must COALESCE to the
--      default. See data/repo/ for where that happens.
--
--   2. RANK NULL MEANS UNRANKED. The scraped HTML page rendered it '--';
--      index_lite.json returns -1. Both become NULL here. rank is never used
--      for change detection — only printed — so this cannot cause a false
--      "changed" result. 82 skill rows and 290 activity rows are NULL today.
--
-- Values are real INTEGERs. The JSON stored comma-formatted strings
-- ("102,315,637") because the old HTML page rendered them that way. All comma
-- formatting now happens at display time only.

PRAGMA foreign_keys = ON;


-- ---------------------------------------------------------------------------
-- Meta
-- ---------------------------------------------------------------------------

CREATE TABLE schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

-- Whole-blob config rows, one for 'sotw' and one for 'botw'. The bot reads and
-- writes these dicts atomically (SOTW_CONFIG is a module global that is
-- replaced wholesale by update_sotw_config), so splitting them into columns
-- would add drift risk for no gain. Query into them with json_extract() —
-- e.g. json_extract(value, '$.current_skill').
CREATE TABLE app_config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL          -- JSON
) WITHOUT ROWID;

-- The loss guarantee. Any db_discord.json key that does not become a row
-- somewhere else lands here verbatim, so the reverse export can reproduce the
-- file exactly. Nothing reads this at runtime.
--
-- `reason` splits two very different cases:
--   'unrecognised'  the migration does not know this key pattern. It ABORTS on
--                   these, because an unfamiliar key may carry live meaning
--                   that the new repo layer would then never read.
--   anything else   understood, deliberately not modelled, and explained in the
--                   migration report. These do not abort.
CREATE TABLE legacy_kv (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,         -- JSON
    reason  TEXT NOT NULL
) WITHOUT ROWID;


-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------

CREATE TABLE servers (
    id              INTEGER PRIMARY KEY,   -- Discord guild snowflake, not autoincrement
    channel_id      INTEGER,               -- NULL = no channel set, bot stays silent
    role_id         INTEGER,               -- NULL = fall back to @here
    sotw_opt        INTEGER,
    sotw_progress   INTEGER,
    botw_opt        INTEGER,
    botw_progress   INTEGER,
    -- active_servers and removed_servers were two separate lists; a server that
    -- is removed and re-added keeps its settings, which is why removal is a
    -- flag rather than a delete.
    is_active       INTEGER NOT NULL DEFAULT 1,
    removed_at      TEXT,
    -- Guild display name, kept in step by the bot (schema version 3). The JSON
    -- never held this: the bot always had discord.Guild objects to hand, so it
    -- had no reason to store one. The web UI has no Discord connection at all,
    -- so without this column its only honest label for a server is an ordinal.
    --
    -- NULL until the bot has been up once since this column was added, and for
    -- any server it can no longer see. Read paths must cope with NULL rather
    -- than assume a name is present.
    --
    -- Deliberately LAST in the table. ALTER TABLE ADD COLUMN appends, so
    -- putting it anywhere else here would leave a freshly created database with
    -- a different column order from a migrated one, for no gain.
    name            TEXT,
    -- Discord's icon hash for the guild, e.g. 'a1b2c3...'; 'a_'-prefixed means
    -- animated and is served as .gif rather than .png.
    --
    -- The HASH, not a URL. The URL is derivable from (id, hash) and pinning one
    -- would bake in a CDN host that is Discord's to change. NULL means the
    -- guild has no icon, or the bot has not seen it since this column existed;
    -- the UI falls back to a monogram either way.
    icon_hash       TEXT
);


CREATE TABLE players (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Stored in RS form with '+' for spaces ("Green+Donut"), matching the JSON
    -- keys and util.name_to_rs(). NOCASE so a differently-cased RSN from Dink
    -- cannot create a duplicate player.
    rs_name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    -- util.name_to_discord() output, materialised so the future web UI never
    -- has to import bot code to render a name.
    display_name    TEXT NOT NULL,
    -- NULL = player has not set up Dink.
    --
    -- Deliberately NOT unique. The webhook validates the key and then routes on
    -- payload['playerName'], so the key is a bearer token rather than an
    -- identity, and live data has two accounts sharing one. A UNIQUE here would
    -- reject real production state to enforce something the code never relied
    -- on. The migration reports duplicates instead.
    dink_link_key   TEXT,
    sotw_xp         INTEGER NOT NULL DEFAULT 0,
    botw_kills      INTEGER NOT NULL DEFAULT 0,
    -- 1 = the player had an entry in db_runescape.json, which is what the old
    -- looper iterated. NOT the same as "has stat rows": a few players are
    -- tracked with an empty skills dict, a leftover from when the scraped HTML
    -- page returned 200 for a nonexistent RSN and ;add accepted it. The looper
    -- polls them today, so it must keep polling them, and the export must still
    -- emit an (empty) db_runescape entry for them or the round-trip breaks.
    tracked         INTEGER NOT NULL DEFAULT 0,
    first_seen      TEXT NOT NULL,
    -- Last time the hiscores were fetched and parsed for this player, whether
    -- or not anything had changed. NOT the last time their stats were written —
    -- most players are unchanged on any given cycle, and a UI needs to tell
    -- "nothing has changed since Tuesday" apart from "we have not been able to
    -- reach this account since Tuesday". NULL means never successfully fetched.
    last_polled     TEXT
);

-- Replaces the top-level `dinklinks` list, which existed purely as a membership
-- index for the webhook's per-request validity check.
CREATE INDEX idx_players_dink ON players(dink_link_key) WHERE dink_link_key IS NOT NULL;


-- Replaces player:<name>#server:<id>#* AND player:<name>#all_servers AND the
-- denormalised member:<id>#server:<id>#players list, which is derivable and so
-- is regenerated on export rather than stored.
--
-- INVARIANT: a player with zero rows here had no `all_servers` key in the JSON.
-- remove_player() deletes that key when the list empties, so an empty list
-- never persists; 0 of 81 players had one. The export relies on this to decide
-- whether to emit the key. The migration asserts it.
CREATE TABLE player_servers (
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    member_id   INTEGER,           -- NULL = player was used here before and is now open
    mention     INTEGER,           -- NULL = key absent, read as True
    sotw_opt    INTEGER,           -- NULL = key absent, read as True (2 of 87)
    botw_opt    INTEGER,           -- NULL = key absent, read as True (52 of 87)
    PRIMARY KEY (player_id, server_id)
) WITHOUT ROWID;

CREATE INDEX idx_player_servers_server ON player_servers(server_id);
CREATE INDEX idx_player_servers_member ON player_servers(server_id, member_id);


-- ---------------------------------------------------------------------------
-- Web UI credentials
-- ---------------------------------------------------------------------------
-- Added after the initial migration (schema version 2). See
-- tools/migrate_add_web_auth.py for applying this to an existing database.
--
-- The read-only web UI signs people in as a DISCORD MEMBER, not as a player: a
-- member may own up to three players, and "can see everyone I share a server
-- with" is a member-level idea. member_id is the same snowflake stored in
-- player_servers.member_id, which is the only place membership is recorded.
--
-- There is no `servers` or `players` foreign key here on purpose. A credential
-- outlives any individual link — what a signed-in member may see is recomputed
-- from player_servers on every request, so losing every link revokes access
-- without anything having to delete this row.
--
-- ONLY A HASH IS STORED. The password is generated by the bot, DM'd once, and
-- never persisted in the clear; the command issues a fresh one each time rather
-- than being able to remind anyone of the old one. A stolen database or backup
-- therefore yields no working credentials — unlike players.dink_link_key, which
-- is a plaintext bearer token and is a weakness to avoid repeating, not a
-- precedent to copy.
--
-- sha256 with no salt is deliberate and is not the usual password-storage
-- mistake. These are 256-bit values from secrets.token_urlsafe(32), not
-- human-chosen passwords: there is no dictionary to attack, no rainbow table
-- that can cover the keyspace, and nothing for a slow KDF to buy. Salting would
-- also break the login lookup, which finds the member BY hash because the
-- browser sends only the password.
CREATE TABLE web_credentials (
    member_id     INTEGER PRIMARY KEY,   -- Discord user snowflake
    token_hash    TEXT    NOT NULL,      -- sha256 hex of the issued password
    issued_at     TEXT    NOT NULL,
    -- How many times a password has been issued to this member. Not security
    -- relevant; it exists so "I keep having to re-run this" is visible.
    issued_count  INTEGER NOT NULL DEFAULT 1
) WITHOUT ROWID;

-- Login sends a password and nothing else, so the member is found by hash.
-- UNIQUE both indexes that lookup and rejects the astronomically unlikely
-- collision rather than signing the wrong person in.
CREATE UNIQUE INDEX idx_web_credentials_hash ON web_credentials(token_hash);


-- ---------------------------------------------------------------------------
-- Reference
-- ---------------------------------------------------------------------------
-- Stable ids so a Jagex rename does not orphan history. Seeded from
-- data/sotw/all_skills.json and data/botw/all_bosses.json plus whatever the
-- live data already contains; the repo layer inserts on first sight of an
-- unknown name, which is how a newly released skill (Sailing) arrives.

CREATE TABLE skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER            -- hiscores display order; NULL sorts last
);

CREATE TABLE activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER
);


-- ---------------------------------------------------------------------------
-- Stats — current
-- ---------------------------------------------------------------------------
-- The looper's hot path. One row per player per skill, exactly the shape and
-- size of today's in-memory dict, so change detection does not get slower.

CREATE TABLE player_skill_current (
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    skill_id    INTEGER NOT NULL REFERENCES skills(id),
    level       INTEGER NOT NULL,
    xp          INTEGER NOT NULL,
    rank        INTEGER,           -- NULL = unranked
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (player_id, skill_id)
) WITHOUT ROWID;


CREATE TABLE player_activity_current (
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    score       INTEGER NOT NULL,
    rank        INTEGER,           -- NULL = unranked
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (player_id, activity_id)
) WITHOUT ROWID;


-- ---------------------------------------------------------------------------
-- Stats — history
-- ---------------------------------------------------------------------------
-- Append-only. A row is written ONLY when a value actually changed, in the same
-- transaction as the matching _current update, so the two cannot drift.
--
-- There is no history to backfill: the JSON held only a current snapshot. The
-- migration seeds one row per current value so a chart has an origin point,
-- then these grow from migration day forward at roughly 400k rows/year.
-- Writing every skill on every poll instead would be ~45M rows/year.

CREATE TABLE player_skill_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    skill_id    INTEGER NOT NULL REFERENCES skills(id),
    level       INTEGER NOT NULL,
    xp          INTEGER NOT NULL,
    rank        INTEGER,
    recorded_at TEXT NOT NULL
);

CREATE INDEX idx_psh_series ON player_skill_history(player_id, skill_id, recorded_at);
CREATE INDEX idx_psh_time   ON player_skill_history(recorded_at);


CREATE TABLE player_activity_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    score       INTEGER NOT NULL,
    rank        INTEGER,
    recorded_at TEXT NOT NULL
);

CREATE INDEX idx_pah_series ON player_activity_history(player_id, activity_id, recorded_at);
CREATE INDEX idx_pah_time   ON player_activity_history(recorded_at);


-- ---------------------------------------------------------------------------
-- Event feed
-- ---------------------------------------------------------------------------
-- New. Nothing populates this from the JSON — it starts empty and captures both
-- sources going forward. Dink events in particular are currently formatted,
-- posted to Discord and discarded, so this is the first time they are retained.
-- `posted = 0` records a Discord send that failed, which today is only a log line.

CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER REFERENCES players(id) ON DELETE SET NULL,
    server_id   INTEGER REFERENCES servers(id) ON DELETE SET NULL,
    source      TEXT    NOT NULL,  -- 'hiscores' | 'dink'
    event_type  TEXT    NOT NULL,  -- LEVEL, XP_MILESTONE, LOOT, PET, QUEST, ...
    title       TEXT,              -- skill / boss / item name, for filtering
    message     TEXT    NOT NULL,  -- the text as posted
    payload     TEXT,              -- raw Dink body as JSON, NULL for hiscores
    occurred_at TEXT    NOT NULL,
    posted      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_events_time        ON events(occurred_at DESC);
CREATE INDEX idx_events_player_time ON events(player_id, occurred_at DESC);
CREATE INDEX idx_events_server_time ON events(server_id, occurred_at DESC);
CREATE INDEX idx_events_type        ON events(source, event_type);


-- ---------------------------------------------------------------------------
-- Skill / Boss of the Week
-- ---------------------------------------------------------------------------
-- Replaces server:<id>#sotw_history and #botw_history, which were JSON lists of
-- {date, skill|boss, players:[{player, xp|kills, rank}]}. 497 SOTW weeks and
-- 212 BOTW weeks across 4 servers.
--
-- `seq` preserves the original list position. Order is meaningful here (history
-- is displayed chronologically) and dates are not guaranteed unique or sorted,
-- so the round-trip needs an explicit ordinal rather than ORDER BY ended_on.

CREATE TABLE sotw_weeks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    skill_name  TEXT    NOT NULL,  -- free text, not an FK: historical skills may be renamed
    ended_on    TEXT    NOT NULL,  -- ISO yyyy-mm-dd; JSON stored %m-%d-%y, export converts back
    seq         INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_sotw_weeks_seq ON sotw_weeks(server_id, seq);


-- player_id is nullable and player_name is authoritative. A week from 2021 can
-- name a player who has since been removed entirely, so an FK alone would
-- either reject the migration or force inventing player rows. The name gives an
-- exact round-trip and correct rendering; the id is filled in when the player
-- still exists, so the UI can still join.
CREATE TABLE sotw_week_players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id     INTEGER NOT NULL REFERENCES sotw_weeks(id) ON DELETE CASCADE,
    player_id   INTEGER REFERENCES players(id) ON DELETE SET NULL,
    player_name TEXT    NOT NULL,
    xp          INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    seq         INTEGER NOT NULL
);

CREATE INDEX idx_sotw_wp_week   ON sotw_week_players(week_id, seq);
CREATE INDEX idx_sotw_wp_player ON sotw_week_players(player_id);


CREATE TABLE botw_weeks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    boss_name   TEXT    NOT NULL,
    ended_on    TEXT    NOT NULL,
    seq         INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_botw_weeks_seq ON botw_weeks(server_id, seq);


CREATE TABLE botw_week_players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id     INTEGER NOT NULL REFERENCES botw_weeks(id) ON DELETE CASCADE,
    player_id   INTEGER REFERENCES players(id) ON DELETE SET NULL,
    player_name TEXT    NOT NULL,
    kills       INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    seq         INTEGER NOT NULL
);

CREATE INDEX idx_botw_wp_week   ON botw_week_players(week_id, seq);
CREATE INDEX idx_botw_wp_player ON botw_week_players(player_id);


-- ---------------------------------------------------------------------------
-- Views for the read-only web UI
-- ---------------------------------------------------------------------------
-- Not used by the bot. These exist so the UI can be a thin Flask app that owns
-- no query logic, and so the shape it depends on is versioned with the schema.

-- THE GHOST GUARD. The looper must select from this view, never from players.
--
-- It reproduces exactly what the old looper polled: it iterated
-- db_runescape.json (hence `tracked`) and then get_all_player_info() dropped
-- any player with no active server. 69 of 91 players qualify.
--
-- The ones that do not are "ghosts": they sit in a server's all_players list
-- with no db_runescape entry at all. Most are in servers the bot was removed
-- from, but not all. Selecting from `players` instead would start polling them,
-- every skill would read as new, and the bot would post "This is the first time
-- this skill is on the Hiscores" for each of them, in every server they belong
-- to.
--
-- `tracked` rather than "has stat rows" is deliberate — see players.tracked.
CREATE VIEW pollable_players AS
SELECT p.*
FROM players p
WHERE p.tracked = 1
  AND EXISTS (
        SELECT 1 FROM player_servers ps
        JOIN servers s ON s.id = ps.server_id
        WHERE ps.player_id = p.id AND s.is_active = 1
      );


CREATE VIEW v_player_skills AS
SELECT p.id            AS player_id,
       p.rs_name,
       p.display_name,
       sk.name         AS skill,
       sk.sort_order,
       c.level, c.xp, c.rank, c.updated_at
FROM player_skill_current c
JOIN players p ON p.id = c.player_id
JOIN skills  sk ON sk.id = c.skill_id;


CREATE VIEW v_player_activities AS
SELECT p.id            AS player_id,
       p.rs_name,
       p.display_name,
       a.name          AS activity,
       a.sort_order,
       c.score, c.rank, c.updated_at
FROM player_activity_current c
JOIN players    p ON p.id = c.player_id
JOIN activities a ON a.id = c.activity_id;


-- Trophy standings. Currently a Python loop that rebuilds every one of a
-- server's 288 weeks on each `;sotw stats` call.
CREATE VIEW v_sotw_standings AS
SELECT w.server_id,
       wp.player_name,
       COUNT(*)                                        AS weeks_placed,
       SUM(wp.xp)                                      AS xp_all,
       SUM(CASE WHEN wp.rank = 1 THEN 1 ELSE 0 END)    AS rank_1,
       SUM(CASE WHEN wp.rank = 2 THEN 1 ELSE 0 END)    AS rank_2,
       SUM(CASE WHEN wp.rank = 3 THEN 1 ELSE 0 END)    AS rank_3,
       SUM(CASE wp.rank WHEN 1 THEN 3 WHEN 2 THEN 2 WHEN 3 THEN 1 ELSE 0 END) AS rank_weight
FROM sotw_week_players wp
JOIN sotw_weeks w ON w.id = wp.week_id
GROUP BY w.server_id, wp.player_name;


CREATE VIEW v_botw_standings AS
SELECT w.server_id,
       wp.player_name,
       COUNT(*)                                        AS weeks_placed,
       SUM(wp.kills)                                   AS kills_all,
       SUM(CASE WHEN wp.rank = 1 THEN 1 ELSE 0 END)    AS rank_1,
       SUM(CASE WHEN wp.rank = 2 THEN 1 ELSE 0 END)    AS rank_2,
       SUM(CASE WHEN wp.rank = 3 THEN 1 ELSE 0 END)    AS rank_3,
       SUM(CASE wp.rank WHEN 1 THEN 3 WHEN 2 THEN 2 WHEN 3 THEN 1 ELSE 0 END) AS rank_weight
FROM botw_week_players wp
JOIN botw_weeks w ON w.id = wp.week_id
GROUP BY w.server_id, wp.player_name;
