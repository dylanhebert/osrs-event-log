"""Concurrent requests must not corrupt each other's database reads.

WHY THIS EXISTS

A browser opens several connections at once, so a page with ~120 icons produces
a burst of parallel requests. With one sqlite3 connection shared across threads,
those interleave cursors, and the failures are ugly and non-obvious:

    sqlite3.InterfaceError: bad parameter or other API misuse
    ValueError: list.index(x): x not in list   <- one request reading another
                                                 request's rows

The second is the dangerous one. It is not an error in the database layer, it
is one request being handed another request's data. In a site whose entire
security model is "you see only your servers", rows crossing between concurrent
requests is a correctness problem, not just a stability one.

Two things prevent it now, and this test covers both:
  * static files skip the auth context entirely, so serving a PNG runs no query
  * read-only mode gives every thread its own connection

Failures here are TIMING DEPENDENT. A pass is not proof, but a fail is proof of
a bug, and before the fix this reproduced on essentially every run.

    web/.venv/Scripts/python.exe -m web.tests.test_concurrency
"""

import collections
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "web" / ".env")

ROUNDS = 4
WORKERS = 12


def scratch():
    source = Path(os.environ["OSRS_DB_PATH"])
    tmp = Path(tempfile.mkdtemp(prefix="osrs-ui-conc-")) / "conc.db"
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(str(tmp))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    sys.path.insert(0, str(ROOT / "osrs-event-log"))
    from data import repo
    repo.db.connect(str(tmp))
    member_id = repo.db.scalar(
        "SELECT member_id FROM player_servers ps JOIN servers s ON s.id = ps.server_id"
        " WHERE s.is_active = 1 AND ps.member_id IS NOT NULL"
        " GROUP BY ps.member_id ORDER BY COUNT(*) DESC LIMIT 1")
    password, _ = repo.webauth.issue(member_id)
    repo.db.close()
    return tmp, password


def main():
    db_path, password = scratch()
    os.environ["OSRS_DB_PATH"] = str(db_path)

    from web.app import create_app
    app = create_app()

    icons = [f"/static/img/skills/{p.name}"
             for p in sorted((ROOT / "web/static/img/skills").glob("*.png"))]
    icons += [f"/static/img/activities/{p.name}"
              for p in sorted((ROOT / "web/static/img/activities").glob("*.png"))]
    pages = ["/players", "/leaderboards", "/competitions/sotw", "/competitions/botw",
             "/me", "/events", "/"]

    # Sign in once and reuse the cookie, which is what makes this bite: without
    # a session there is no auth context and therefore no query to corrupt.
    client = app.test_client()
    client.post("/login", data={"password": password})
    cookie = next((c for c in client.cookie_jar), None) if hasattr(client, "cookie_jar") else None

    results = collections.Counter()
    bodies = []
    lock = threading.Lock()

    def worker(paths):
        # A separate test client per thread, sharing the signed-in cookie jar
        # the same way separate browser connections share one session.
        local = app.test_client()
        local.post("/login", data={"password": password})
        for path in paths:
            try:
                response = local.get(path)
                with lock:
                    results[response.status_code] += 1
                    if response.status_code != 200:
                        bodies.append((path, response.status_code))
            except Exception as e:
                with lock:
                    results[type(e).__name__] += 1
                    bodies.append((path, f"{type(e).__name__}: {e}"))

    work = (icons + pages * 10) * ROUNDS
    print(f"  {len(work)} requests across {WORKERS} threads, signed in")
    threads = [threading.Thread(target=worker, args=(work[i::WORKERS],))
               for i in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"  results: {dict(results)}")
    ok = set(results) == {200}
    if not ok:
        print("  FAILED. First few:")
        for path, why in bodies[:8]:
            print(f"    {path} -> {why}")

    shutil.rmtree(db_path.parent, ignore_errors=True)
    print()
    print("CONCURRENCY OK" if ok else "CONCURRENCY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
