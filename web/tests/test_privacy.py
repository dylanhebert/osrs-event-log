"""Crawl every page and prove the private columns never reach a response.

This is the test that actually enforces the privacy rules. Code review does not:
one `SELECT *`, one debug template, one error page that echoes a row, and a
webhook bearer token is on the internet. So this pulls the real secrets out of
the database, visits every route as a signed-in member, and fails if any of them
appears anywhere in any response body or header.

WHAT IT GUARDS
    players.dink_link_key     bearer tokens for the public Dink webhook. Anyone
                              holding one can post events as any player.
    player_servers.member_id  real Discord user ids
    events.payload            raw Dink bodies, which carry dinkAccountHash
    web_credentials.token_hash the sign-in hashes

It also checks that the SIGNED-OUT pages contain no player names at all, which
is the whole basis of the "aggregates only" public view.

    web/.venv/Scripts/python -m web.tests.test_privacy
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "web" / ".env")


def scratch_copy():
    """Work on a copy, and seed it with a Dink key and a payload if live data
    happens not to have one, so the test cannot pass vacuously."""
    source = Path(os.environ["OSRS_DB_PATH"])
    tmp = Path(tempfile.mkdtemp(prefix="osrs-ui-privacy-")) / "privacy.db"
    shutil.copy2(source, tmp)

    sys.path.insert(0, str(ROOT / "osrs-event-log"))
    from data import repo

    repo.db.connect(str(tmp))
    canaries = {}

    # A Dink key on a player who is definitely visible.
    row = repo.db.one(
        "SELECT p.id, p.rs_name FROM players p"
        " JOIN player_servers ps ON ps.player_id = p.id"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE s.is_active = 1 LIMIT 1")
    canaries["dink_key"] = "CANARY-dink-key-must-never-render"
    repo.db.execute("UPDATE players SET dink_link_key = ? WHERE id = ?",
                    (canaries["dink_key"], row["id"]))

    # An event with a payload, since live data may have only hiscores events,
    # which store payload NULL.
    canaries["payload_value"] = "CANARY-dinkAccountHash-must-never-render"
    repo.events = repo.events
    repo.db.execute(
        "INSERT INTO events (player_id, server_id, source, event_type, title,"
        " message, payload, occurred_at, posted) VALUES (?,?,?,?,?,?,?,?,1)",
        (row["id"], None, "dink", "LOOT", None,
         "Canary received some loot",
         json.dumps({"dinkAccountHash": canaries["payload_value"],
                     "playerName": row["rs_name"]}),
         "2026-08-04T21:00:00Z"))

    member_id = repo.db.scalar(
        "SELECT member_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE s.is_active = 1 AND ps.member_id IS NOT NULL"
        " GROUP BY ps.member_id ORDER BY COUNT(*) DESC LIMIT 1")
    password, _ = repo.webauth.issue(member_id)
    token_hash = repo.db.scalar(
        "SELECT token_hash FROM web_credentials WHERE member_id = ?", (member_id,))
    repo.db.close()

    canaries["member_id"] = str(member_id)
    canaries["token_hash"] = token_hash
    return tmp, member_id, password, canaries


def collect_secrets(db_path, canaries):
    """Every value that must never appear in a response."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    secrets = {}

    for (key,) in conn.execute(
            "SELECT dink_link_key FROM players WHERE dink_link_key IS NOT NULL"):
        secrets[key] = "players.dink_link_key"

    for (member_id,) in conn.execute(
            "SELECT DISTINCT member_id FROM player_servers"
            " WHERE member_id IS NOT NULL"):
        secrets[str(member_id)] = "player_servers.member_id"

    for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE payload IS NOT NULL"):
        try:
            blob = json.loads(payload)
        except (TypeError, ValueError):
            continue
        for field in ("dinkAccountHash", "accountHash"):
            if blob.get(field):
                secrets[str(blob[field])] = f"events.payload.{field}"

    for (token_hash,) in conn.execute("SELECT token_hash FROM web_credentials"):
        secrets[token_hash] = "web_credentials.token_hash"

    conn.close()
    return secrets


def main():
    scratch, member_id, password, canaries = scratch_copy()
    os.environ["OSRS_DB_PATH"] = str(scratch)

    secrets = collect_secrets(scratch, canaries)
    print(f"guarding {len(secrets)} secret values "
          f"({len(set(secrets.values()))} distinct sources)")
    for source in sorted(set(secrets.values())):
        print(f"  - {source}: "
              f"{sum(1 for v in secrets.values() if v == source)}")

    from web.app import create_app
    app = create_app()
    client = app.test_client()

    conn = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
    names = [r[0] for r in conn.execute("SELECT rs_name FROM players")]
    visible = [r[0] for r in conn.execute(
        "SELECT DISTINCT p.rs_name FROM players p"
        " JOIN player_servers ps ON ps.player_id = p.id"
        " WHERE ps.server_id IN (SELECT ps2.server_id FROM player_servers ps2"
        "   JOIN servers s ON s.id = ps2.server_id"
        "   WHERE ps2.member_id = ? AND s.is_active = 1)", (member_id,))]
    skills = [r[0] for r in conn.execute("SELECT name FROM skills LIMIT 5")]
    conn.close()

    failures = []

    # ---------------------------------------------------------------- #
    # 1. Signed-out pages must contain no player names at all.
    # ---------------------------------------------------------------- #
    print("\n1. signed-out pages carry no player names")
    for path in ("/", "/login", "/healthz", "/nope-404"):
        body = client.get(path).get_data(as_text=True)
        leaked = [n for n in names
                  if n in body or n.replace("+", " ") in body]
        status = "ok  " if not leaked else "FAIL"
        print(f"  {status} {path}")
        if leaked:
            failures.append(f"{path} leaked names: {leaked[:5]}")

    # ---------------------------------------------------------------- #
    # 2. Crawl everything signed in, checking bodies AND headers.
    # ---------------------------------------------------------------- #
    client.post("/login", data={"password": password})

    # /me is the highest-risk page in the app: it is built by filtering on the
    # member's own Discord id and it reports on the Dink key. Both must come
    # out as a filter and a boolean respectively, never as output.
    paths = ["/", "/me", "/players", "/players?all=1", "/events", "/events?source=dink",
             "/events?source=hiscores", "/competitions/sotw", "/competitions/botw",
             "/leaderboards", "/healthz"]
    paths += [f"/leaderboards?skill={s}" for s in skills]
    # Server-scoped leaderboards put a real guild id in the query string, so
    # these are exactly the pages most likely to echo one back into the markup.
    own_servers = [r[0] for r in sqlite3.connect(
        f"file:{scratch}?mode=ro", uri=True).execute(
        "SELECT DISTINCT ps.server_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.member_id = ? AND s.is_active = 1", (member_id,))]
    paths += [f"/leaderboards?server={s}" for s in own_servers]
    paths += [f"/leaderboards?skill=Slayer&server={s}" for s in own_servers]
    paths += [f"/players/{n}" for n in visible]
    paths += [f"/players/{n}/history.json?skill=Overall" for n in visible[:10]]

    print(f"\n2. crawling {len(paths)} pages signed in")
    checked = 0
    for path in paths:
        response = client.get(path)
        haystack = response.get_data(as_text=True) + "\n" + str(dict(response.headers))
        for secret, source in secrets.items():
            if secret and str(secret) in haystack:
                # The value itself is NOT printed. D10 in the migration notes:
                # the round-trip test used to dump the offending value on a
                # mismatch, which for Dink keys meant printing live webhook
                # bearer tokens into terminal scrollback and CI logs. A failure
                # message needs to say what leaked and where, not what the
                # secret was.
                failures.append(f"{path} leaked {source} "
                                f"(value redacted, {len(str(secret))} chars)")
        checked += 1
    print(f"  {'ok  ' if not failures else 'FAIL'} {checked} pages, "
          f"{len(secrets)} secrets each")

    # ---------------------------------------------------------------- #
    # 3. The canaries must be findable in the database, or step 2 proved
    #    nothing. A test that guards values that are not there passes for
    #    the wrong reason.
    # ---------------------------------------------------------------- #
    print("\n3. canaries are real (guards against a vacuous pass)")
    for label in ("dink_key", "payload_value", "member_id", "token_hash"):
        present = canaries[label] in secrets or str(canaries[label]) in secrets
        print(f"  {'ok  ' if present else 'FAIL'} {label} is in the guarded set")
        if not present:
            failures.append(f"canary {label} was not collected; test is vacuous")

    # And prove the crawler would actually catch a leak, by checking that the
    # canary dink key IS present in the database it just crawled.
    conn = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
    stored = conn.execute(
        "SELECT COUNT(*) FROM players WHERE dink_link_key = ?",
        (canaries["dink_key"],)).fetchone()[0]
    conn.close()
    print(f"  {'ok  ' if stored else 'FAIL'} canary dink key is stored on a "
          f"visible player ({stored} row)")
    if not stored:
        failures.append("canary dink key never made it into the database")

    # ---------------------------------------------------------------- #
    # 4. Authenticated responses must not be shared-cacheable.
    # ---------------------------------------------------------------- #
    print("\n4. authenticated responses are not shared-cacheable")
    cache = client.get("/players").headers.get("Cache-Control", "")
    ok = "private" in cache and "no-store" in cache
    print(f"  {'ok  ' if ok else 'FAIL'} /players Cache-Control: {cache}")
    if not ok:
        failures.append(f"/players Cache-Control was {cache!r}")

    shutil.rmtree(scratch.parent, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures[:20]:
            print("  -", f)
        return 1
    print("NO PRIVATE DATA REACHED ANY RESPONSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
