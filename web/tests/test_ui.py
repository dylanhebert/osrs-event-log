"""The parts of the UI that are logic rather than layout.

Three things here are easy to break silently and cost real information when
they do:

  * every feed row must get an icon. The icon is read out of the message text,
    so a wording change or a renamed activity would quietly leave a hole, and
    a hole looks like a rendering bug rather than a matching failure.
  * the page chooser must reach the far end of 963 pages. The link it replaced
    only stepped one page at a time, which made six years of history
    theoretically reachable and practically not.
  * changing page must not lose the filter you are looking through.

    web/.venv/Scripts/python -m web.tests.test_ui
"""

import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "web" / ".env")

from web.tests.smoke import build_scratch_db  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'} {label}{'' if condition else '  ' + detail}")
    if not condition:
        failures.append(label)


# --------------------------------------------------------------------- pager
def test_page_numbers():
    from web.format import page_numbers, page_count

    print("\npage_numbers")
    check("a single page offers nothing to choose between",
          page_numbers(1, 1) == [1], str(page_numbers(1, 1)))
    check("a short run is listed in full",
          page_numbers(3, 6) == [1, 2, 3, 4, 5, 6], str(page_numbers(3, 6)))

    deep = page_numbers(500, 963)
    check("a deep page keeps both ends reachable",
          deep[0] == 1 and deep[-1] == 963, str(deep))
    check("a deep page elides on both sides",
          deep.count(None) == 2, str(deep))
    check("a deep page stays around the current one",
          [n for n in deep if n] == [1, 498, 499, 500, 501, 502, 963], str(deep))

    first = page_numbers(1, 963)
    check("the first page elides only on the right",
          first.count(None) == 1 and first[0] == 1, str(first))
    last = page_numbers(963, 963)
    check("the last page elides only on the left",
          last.count(None) == 1 and last[-1] == 963, str(last))

    # A gap that hides exactly one page is worse than showing it: same width,
    # less information.
    nine = page_numbers(5, 9, window=2, edge=1)
    check("a gap of one page shows the page instead of an ellipsis",
          None not in nine, str(nine))

    check("every number is in range and ascending",
          all(1 <= n <= 963 for n in deep if n)
          and [n for n in deep if n] == sorted(n for n in deep if n))

    print("\npage_count")
    check("a full last page is not rounded up", page_count(100, 50) == 2)
    check("a partial last page counts", page_count(101, 50) == 3)
    check("no rows still means one page", page_count(0, 50) == 1)
    check("64,155 events at 50 a page", page_count(64155, 50) == 1284)


# ---------------------------------------------------------------- event icons
def test_event_icons(db_path):
    """Every event in the snapshot resolves to an icon.

    Run over the whole table rather than a sample. The tail is the point: the
    hiscores rows all match on their skill name, and what this is guarding is
    the couple of thousand Dink rows that name a quest or an item instead and
    have to fall back to their event type.
    """
    from web.format import event_icon

    print("\nevent_icon over the whole snapshot")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT e.source, e.event_type, e.message, p.display_name"
        " FROM events e JOIN players p ON p.id = e.player_id").fetchall()
    conn.close()

    if not rows:
        check("the snapshot has events to check", False, "events table is empty")
        return

    missing, used, by_type = [], set(), {}
    for row in rows:
        cls = event_icon(row)
        if not cls:
            missing.append((row["source"], row["event_type"]))
        else:
            used.add(cls)
            by_type.setdefault(row["event_type"], set()).add(cls)

    check(f"all {len(rows):,} events resolve to an icon",
          not missing, f"{len(missing)} without one: {set(missing)}")
    check("the icons are not all the same one", len(used) > 20, f"{len(used)} distinct")

    # A levelling event must pick out its own skill, not a generic badge. This
    # is the whole reason the icon is derived from the text.
    skill_icons = by_type.get("SKILL", set())
    check("levelling events resolve to many different skills",
          len(skill_icons) >= 20, f"{len(skill_icons)} distinct")

    # And a class that does not exist in the sprite would render an empty box.
    css = (ROOT / "web" / "static" / "css" / "icons.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"\.ic-([a-z0-9-]+)\s*\{", css))
    undefined = sorted(used - defined)
    check("every icon chosen is actually in the sprite",
          not undefined, f"missing from icons.css: {undefined[:5]}")


# ------------------------------------------------------------------- rendered
def test_rendered(db_path, password):
    os.environ["OSRS_DB_PATH"] = str(db_path)
    from web.app import create_app

    app = create_app()
    client = app.test_client()
    client.post("/login", data={"password": password})

    print("\nrendered pages")
    feed = client.get("/events").get_data(as_text=True)
    check("the feed page renders a pager", 'class="pager"' in feed)
    check("the pager offers numbered pages", 'class="pg"' in feed)
    check("the old one-way link is gone", ">Older<" not in feed)

    # The filter has to survive changing page, or paging through "milestones
    # only" quietly dumps you back into the whole feed.
    filtered = client.get("/events?milestones=1").get_data(as_text=True)
    links = re.findall(r'href="(/events\?[^"]*page=\d+[^"]*)"', filtered)
    check("filtered paging keeps its filter",
          bool(links) and all("milestones=1" in link for link in links),
          f"{[l for l in links if 'milestones=1' not in l][:2]}")

    # Deep pages must actually serve, not just be linked to.
    last = client.get("/events?page=1200")
    check("a deep page still renders", last.status_code == 200,
          str(last.status_code))

    home = client.get("/").get_data(as_text=True)
    check("home shows a milestones panel", "Latest milestones" in home)
    check("home shows events above accounts",
          home.index("Latest events") < home.index("Top accounts"))
    check("feed rows carry an icon", 'class="ic ic-' in home)

    check("the header collapses behind a menu control",
          'class="nav-toggle"' in home and 'class="menu-btn"' in home)
    check("events is the first nav link",
          home.index('href="/events"') < home.index('href="/players"'))

    public = client.get("/logout")  # noqa: F841
    signed_out = client.get("/").get_data(as_text=True)
    check("the signed-out page still renders its week",
          "Skill of the Week" in signed_out)

    # Static files are cached for a day, so a changed one has to arrive under a
    # changed URL or nobody sees it. This is not hypothetical: the CDN served a
    # whole stylesheet rewrite from cache after the deploy that shipped it.
    print("\nthe feed narrowed to one account")
    import sqlite3 as _sq
    conn = _sq.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = _sq.Row
    who = conn.execute(
        "SELECT p.rs_name, COUNT(*) n FROM events e JOIN players p ON p.id = e.player_id"
        " GROUP BY p.rs_name ORDER BY n DESC LIMIT 1").fetchone()
    name = who["rs_name"]

    one = client.get(f"/events?player={name}")
    check("a player-scoped feed renders", one.status_code == 200, str(one.status_code))
    body = one.get_data(as_text=True)

    # The `+` in a RuneScape name is the encoding OF a space in a query string,
    # so it comes back decoded and the lookup has to fold it back.
    if " " in name.replace("+", " "):
        spaced = client.get("/events?player=" + name.replace("+", " "))
        check("a name whose spaces arrived decoded still resolves",
              spaced.status_code == 200, str(spaced.status_code))

    # Every link has to carry the filter, or one click silently widens the feed
    # back to everybody.
    links = re.findall(r'href="(/events\?[^"]*)"', body)
    without = [l for l in links if "player=" not in l and "page=" in l]
    check("paging keeps the account", not without, str(without[:2]))
    tabs = [l for l in links if "milestones=1" in l]
    check("the milestones tab keeps the account",
          all("player=" in l for l in tabs), str(tabs[:2]))

    check("a player outside the member's servers 404s",
          client.get("/events?player=Definitely+Not+A+Real+Account").status_code == 404)

    print("\nmember pages")
    members_page = client.get("/members")
    check("the members index renders", members_page.status_code == 200,
          str(members_page.status_code))
    handles = re.findall(r'href="/members/([0-9a-f]{16})"',
                         members_page.get_data(as_text=True))
    check("it links to member pages by an opaque handle", bool(handles),
          "no /members/<handle> links found")
    if handles:
        one_member = client.get(f"/members/{handles[0]}")
        check("a member page renders", one_member.status_code == 200,
              str(one_member.status_code))

    # The handle is a digest, so a wrong one must behave exactly like a member
    # the viewer cannot see: 404, with nothing to distinguish the two.
    check("an unknown handle 404s",
          client.get("/members/" + "0" * 16).status_code == 404)
    check("a member id is not accepted as a handle",
          client.get("/members/123456789012345678").status_code == 404)

    print("\nstatic cache busting")
    css_url = re.search(r'href="(/static/css/app\.css[^"]*)"', signed_out)
    check("the stylesheet URL carries a version",
          bool(css_url) and "?v=" in css_url.group(1),
          css_url.group(1) if css_url else "no stylesheet link found")
    sprite = client.get(css_url.group(1)) if css_url else None
    check("the versioned URL still serves the file",
          sprite is not None and sprite.status_code == 200,
          str(sprite.status_code) if sprite else "not requested")
    check("static responses are cacheable",
          sprite is not None and "max-age" in (
              sprite.headers.get("Cache-Control") or ""),
          sprite.headers.get("Cache-Control") if sprite else "")


def main():
    scratch, _, password = build_scratch_db()
    test_page_numbers()
    test_event_icons(scratch)
    test_rendered(scratch, password)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("UI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
