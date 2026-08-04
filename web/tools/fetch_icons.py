"""Fetch skill and activity icons from the OSRS Wiki into web/static/img/.

Step one of two. Run this, then web/tools/build_sprite.py, which packs what
this downloads into the single sprite the site actually serves.

    web\\.venv\\Scripts\\python.exe -m web.tools.fetch_icons
    web\\.venv\\Scripts\\python.exe -m web.tools.build_sprite

Only needed when Jagex adds a skill or boss. The names come from the database,
so a newly seen activity is picked up automatically: the repo layer inserts
unknown names on sight, and an icon simply does not exist for it until this runs.
"""
import json
import os
import pathlib
import re
import sqlite3
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "static" / "img"
SKILL_DIR = OUT / "skills"
ACT_DIR = OUT / "activities"
for d in (SKILL_DIR, ACT_DIR):
    d.mkdir(parents=True, exist_ok=True)

WIKI = "https://oldschool.runescape.wiki"
UA = "osrs-event-log/1.0 (non-commercial fan project; contact via GitHub)"


def _names_from_db():
    """Every skill and activity the database knows about."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / "web" / ".env")
    db_path = os.environ.get("OSRS_DB_PATH")
    if not db_path:
        raise SystemExit("OSRS_DB_PATH is not set; see web/.env.example")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            "skills": [r[0] for r in conn.execute(
                "SELECT name FROM skills ORDER BY sort_order, name")],
            "activities": [r[0] for r in conn.execute(
                "SELECT name FROM activities ORDER BY sort_order, name")],
        }
    finally:
        conn.close()


names = _names_from_db()

# Activity names that are not wiki page titles, or whose page has no lead image.
ALIASES = {
    "Barrows Chests": "Barrows",
    "Bounty Hunter - Hunter": "Bounty Hunter",
    "Bounty Hunter - Rogue": "Bounty Hunter",
    "Bounty Hunter (Legacy) - Hunter": "Bounty Hunter",
    "Bounty Hunter (Legacy) - Rogue": "Bounty Hunter",
    "Clue Scrolls (all)": "Clue scroll",
    "Clue Scrolls (beginner)": "Clue scroll (beginner)",
    "Clue Scrolls (easy)": "Clue scroll (easy)",
    "Clue Scrolls (medium)": "Clue scroll (medium)",
    "Clue Scrolls (hard)": "Clue scroll (hard)",
    "Clue Scrolls (elite)": "Clue scroll (elite)",
    "Clue Scrolls (master)": "Clue scroll (master)",
    "Collections Logged": "Collection log",
    "Colosseum Glory": "Fortis Colosseum",
    "LMS - Rank": "Last Man Standing",
    "PvP Arena - Rank": "PvP Arena",
    "Soul Wars Zeal": "Soul Wars",
    "Rifts closed": "Guardians of the Rift",
    "Chambers of Xeric: Challenge Mode": "Chambers of Xeric",
    "Theatre of Blood: Hard Mode": "Theatre of Blood",
    "Tombs of Amascut: Expert Mode": "Tombs of Amascut",
    "The Corrupted Gauntlet": "Corrupted Gauntlet",
    "The Gauntlet": "Crystalline Hunllef",
    "Cal'varion": "Calvar'ion",
    "Phosani's Nightmare": "Phosani's Nightmare",
    "Nightmare": "The Nightmare",
    "Doom of Mokhaiotl": "Doom of Mokhaiotl",
    "Mimic": "The Mimic",
}


def slug(name):
    """Stable, filesystem-safe filename for a skill or activity name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def get(url, binary=False):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    return data if binary else json.loads(data)


def save(path, url):
    try:
        path.write_bytes(get(url, binary=True))
        return True
    except Exception as e:
        print(f"      download failed: {e}")
        return False


# --------------------------------------------------------------- skills
print(f"SKILLS ({len(names['skills'])})")
skill_map, skill_missing = {}, []
for skill in names["skills"]:
    # Overall has no skill icon; the wiki uses the stats icon for it.
    title = "Stats" if skill == "Overall" else f"{skill}_icon"
    url = f"{WIKI}/images/{urllib.parse.quote(title)}.png"
    target = SKILL_DIR / f"{slug(skill)}.png"
    try:
        if save(target, url):
            skill_map[skill] = target.name
            print(f"  ok   {skill}")
        else:
            skill_missing.append(skill)
    except Exception:
        skill_missing.append(skill)
        print(f"  MISS {skill}")
    time.sleep(0.15)

# --------------------------------------------------------------- activities
print(f"\nACTIVITIES ({len(names['activities'])})")
wanted = {a: ALIASES.get(a, a) for a in names["activities"]}
titles = sorted(set(wanted.values()))

thumbs = {}
for i in range(0, len(titles), 40):
    batch = titles[i:i + 40]
    api = (f"{WIKI}/api.php?action=query&format=json&redirects=1"
           f"&prop=pageimages&pithumbsize=64&titles="
           + urllib.parse.quote("|".join(batch)))
    try:
        data = get(api)
    except Exception as e:
        print(f"  api batch failed: {e}")
        continue
    query = data.get("query", {})
    # Follow redirects and normalisations back to what we asked for.
    remap = {}
    for entry in query.get("redirects", []) + query.get("normalized", []):
        remap[entry["to"]] = entry["from"]
    for page in query.get("pages", {}).values():
        thumb = (page.get("thumbnail") or {}).get("source")
        if not thumb:
            continue
        title = page.get("title")
        thumbs[title] = thumb
        if title in remap:
            thumbs[remap[title]] = thumb
    time.sleep(0.3)

act_map, act_missing = {}, []
for activity, title in wanted.items():
    url = thumbs.get(title)
    if not url:
        act_missing.append(activity)
        continue
    target = ACT_DIR / f"{slug(activity)}.png"
    if save(target, url):
        act_map[activity] = target.name
        print(f"  ok   {activity}")
    else:
        act_missing.append(activity)
    time.sleep(0.1)

# --------------------------------------------------------------- manifest
manifest = {"skills": skill_map, "activities": act_map}
(OUT / "icon-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

print(f"\nskills     {len(skill_map)}/{len(names['skills'])}"
      f"  missing: {skill_missing or 'none'}")
print(f"activities {len(act_map)}/{len(names['activities'])}")
if act_missing:
    print("  missing:")
    for a in act_missing:
        print(f"    - {a}")
