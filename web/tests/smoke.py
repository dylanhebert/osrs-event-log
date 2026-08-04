"""Route smoke test: every page renders, signed out and signed in.

Uses Flask's test client, so it needs no running server and no port. It signs in
by inserting a credential into a THROWAWAY COPY of the snapshot, never the
snapshot itself and never anything on the droplet.

    web/.venv/Scripts/python -m web.tests.smoke
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "web" / ".env")


def build_scratch_db():
    """Copy the snapshot somewhere writable and give one member a password.

    The web UI cannot create a credential: it never writes. So the test does
    what the bot would do, against a copy, using the same repo function the cog
    will call.
    """
    source = Path(os.environ["OSRS_DB_PATH"])
    tmp = Path(tempfile.mkdtemp(prefix="osrs-ui-smoke-")) / "smoke.db"
    shutil.copy2(source, tmp)

    sys.path.insert(0, str(ROOT / "osrs-event-log"))
    from data import repo

    repo.db.connect(str(tmp))
    member_id = repo.db.scalar(
        "SELECT member_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE s.is_active = 1 AND ps.member_id IS NOT NULL"
        " GROUP BY ps.member_id ORDER BY COUNT(*) DESC LIMIT 1")
    password, _ = repo.webauth.issue(member_id)
    repo.db.close()
    return tmp, member_id, password


def main():
    scratch, member_id, password = build_scratch_db()
    os.environ["OSRS_DB_PATH"] = str(scratch)

    from web.app import create_app
    app = create_app()
    client = app.test_client()

    failures = []

    def check(label, response, expect=200, forbid_names=True):
        ok = response.status_code == expect
        print(f"  {'ok  ' if ok else 'FAIL'} {label:52} {response.status_code}")
        if not ok:
            failures.append(f"{label}: {response.status_code} != {expect}")
        return response

    print("\nSIGNED OUT")
    check("GET /", client.get("/"))
    check("GET /login", client.get("/login"))
    check("GET /me -> redirect to login", client.get("/me"), 302)
    check("GET /players -> redirect to login", client.get("/players"), 302)
    check("GET /events -> redirect to login", client.get("/events"), 302)
    check("GET /competitions/sotw -> redirect", client.get("/competitions/sotw"), 302)
    check("GET /healthz", client.get("/healthz"))

    body = client.get("/").get_data(as_text=True)
    # The public page must contain aggregates and no player names.
    import sqlite3
    conn = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
    names = [r[0] for r in conn.execute("SELECT rs_name FROM players")]
    leaked = [n for n in names if n.replace("+", " ") in body or n in body]
    print(f"  {'ok  ' if not leaked else 'FAIL'} public page leaks no player names"
          f"{'' if not leaked else ': ' + ', '.join(leaked[:3])}")
    if leaked:
        failures.append(f"public page leaked {len(leaked)} names")

    print("\nSIGN IN")
    resp = client.post("/login", data={"password": "definitely-not-it"})
    check("POST /login with a bad password stays on the page", resp)
    resp = client.post("/login", data={"password": password})
    check("POST /login with the real password redirects", resp, 302)

    print("\nSIGNED IN")
    check("GET /", client.get("/"))
    check("GET /me", client.get("/me"))
    check("GET /players", client.get("/players"))
    check("GET /players?all=1", client.get("/players?all=1"))
    check("GET /events", client.get("/events"))
    check("GET /events?source=hiscores", client.get("/events?source=hiscores"))
    check("GET /competitions/sotw", client.get("/competitions/sotw"))
    check("GET /competitions/botw", client.get("/competitions/botw"))
    check("GET /competitions/nope", client.get("/competitions/nope"), 404)
    check("GET /leaderboards", client.get("/leaderboards"))
    check("GET /leaderboards?skill=Slayer", client.get("/leaderboards?skill=Slayer"))

    # Server scoping on the leaderboards: every server the member is in works,
    # a server they are not in 404s, and narrowing can only ever shrink the set.
    own_servers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ps.server_id FROM player_servers ps"
        " JOIN servers s ON s.id = ps.server_id"
        " WHERE ps.member_id = ? AND s.is_active = 1", (member_id,))]
    for server_id in own_servers:
        check(f"GET /leaderboards for one of your servers",
              client.get(f"/leaderboards?server={server_id}"))
    check("GET /leaderboards?server=999999 (not yours) 404s",
          client.get("/leaderboards?server=999999"), 404)

    all_body = client.get("/leaderboards?skill=Overall").get_data(as_text=True)
    all_rows = all_body.count("<tr>")
    narrowed = client.get(
        f"/leaderboards?skill=Overall&server={own_servers[0]}").get_data(as_text=True)
    shrank = narrowed.count("<tr>") <= all_rows
    print(f"  {'ok  ' if shrank else 'FAIL'} narrowing to one server never widens "
          f"the board ({narrowed.count('<tr>')} <= {all_rows})")
    if not shrank:
        failures.append("server filter widened the leaderboard")

    # Walk every visible player page, which is where most of the template
    # surface lives and where the odd data cases show up.
    with app.test_request_context():
        pass
    visible = conn.execute(
        "SELECT DISTINCT p.rs_name FROM players p"
        " JOIN player_servers ps ON ps.player_id = p.id"
        " WHERE ps.server_id IN (SELECT ps2.server_id FROM player_servers ps2"
        "   JOIN servers s ON s.id = ps2.server_id"
        "   WHERE ps2.member_id = ? AND s.is_active = 1)",
        (member_id,)).fetchall()
    bad = []
    for (rs_name,) in visible:
        r = client.get(f"/players/{rs_name}")
        if r.status_code != 200:
            bad.append((rs_name, r.status_code))
    print(f"  {'ok  ' if not bad else 'FAIL'} {len(visible)} player pages render"
          f"{'' if not bad else ': ' + str(bad[:3])}")
    if bad:
        failures.append(f"{len(bad)} player pages failed")

    # A player who exists but is NOT in the member's servers must 404, not 403
    # and not render.
    outsider = conn.execute(
        "SELECT p.rs_name FROM players p WHERE p.id NOT IN ("
        "  SELECT ps.player_id FROM player_servers ps"
        "  WHERE ps.server_id IN (SELECT ps2.server_id FROM player_servers ps2"
        "    JOIN servers s ON s.id = ps2.server_id"
        "    WHERE ps2.member_id = ? AND s.is_active = 1)) LIMIT 1",
        (member_id,)).fetchone()
    if outsider:
        check(f"GET a player outside your servers 404s",
              client.get(f"/players/{outsider[0]}"), 404)

    check("GET history.json", client.get(
        f"/players/{visible[0][0]}/history.json?skill=Overall"))

    print("\nSIGN OUT")
    check("POST /logout", client.post("/logout"), 302)
    check("GET /players is protected again", client.get("/players"), 302)

    conn.close()
    shutil.rmtree(scratch.parent, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL ROUTES OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
