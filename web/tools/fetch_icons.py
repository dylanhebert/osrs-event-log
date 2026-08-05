"""Fetch skill, activity and event-type icons from the OSRS Wiki.

Step one of two. Run this, then web/tools/build_sprite.py, which packs what
this downloads into the single sprite the site actually serves.

    web\\.venv\\Scripts\\python.exe -m web.tools.fetch_icons
    web\\.venv\\Scripts\\python.exe -m web.tools.build_sprite

Only needed when Jagex adds a skill or boss. Skill and activity names come from
the database, so a newly seen activity is picked up automatically: the repo
layer inserts unknown names on sight, and an icon simply does not exist for it
until this runs.

    --kinds types           fetch only what is listed, leaving the rest alone

Adding one kind should not silently redraw the others. A full run re-downloads
every icon, so if the wiki has since replaced any of that art the sprite
changes in ways nobody asked for, mixed into a diff of a hundred binary files
where no reviewer will see it. Naming the kind keeps the change to what it
claims to be. Whatever is not fetched is carried over from the existing
manifest untouched.
"""
import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "static" / "img"
SKILL_DIR = OUT / "skills"
ACT_DIR = OUT / "activities"
TYPE_DIR = OUT / "types"
for d in (SKILL_DIR, ACT_DIR, TYPE_DIR):
    d.mkdir(parents=True, exist_ok=True)

WIKI = "https://oldschool.runescape.wiki"
UA = "osrs-event-log/1.0 (non-commercial fan project; contact via GitHub)"

ALL_KINDS = ("skills", "activities", "types")

_parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
_parser.add_argument("--kinds", nargs="+", choices=ALL_KINDS, default=list(ALL_KINDS),
                     help="which kinds to fetch. The rest keep their current "
                          "files and manifest entries.")
KINDS = set(_parser.parse_args().kinds)

# What is not being fetched is preserved rather than dropped, so a partial run
# still writes a complete manifest and build_sprite.py has everything it needs.
try:
    _existing = json.loads(
        (OUT / "icon-manifest.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    _existing = {}


def _carried_over(kind):
    """Existing manifest entries for a kind this run is not fetching."""
    entries = _existing.get(kind, {})
    # build_sprite.py rewrites values to {"file": ..., "cls": ...}; this script
    # writes plain filenames. Normalise back so both shapes round-trip.
    return {name: (e["file"] if isinstance(e, dict) else e)
            for name, e in entries.items()}


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


# Only the database-driven kinds need it open. Fetching just the event types
# should not require a database at all.
names = (_names_from_db() if {"skills", "activities"} & KINDS
         else {"skills": [], "activities": []})

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


# Event types whose feed rows name a quest, an item or another player rather
# than a tracked skill or boss, so no amount of matching against the database
# will find them an icon. Measured over 64k real events, these are the only
# ones left: everything from the hiscores names its skill or activity 99.3% of
# the time and resolves without help.
#
# Types absent from here are DELIBERATE, not forgotten. COLLECTION, CLUE,
# SLAYER and PLAYER_KILL already have art in the sprite under an activity or
# skill name, and web/format.py points them at it instead of fetching a second
# copy of the same picture.
TYPE_TITLES = {
    "QUEST": "Quest point",
    "GRAND_EXCHANGE": "Grand Exchange",
    "DEATH": "Grave",
    "COMBAT_ACHIEVEMENT": "Combat Achievements",
    "ACHIEVEMENT_DIARY": "Achievement Diary",
    "LOOT": "Coins",
    # No page depicts "a pet" in general, so one stands for all of them. The
    # alternative, Pets, illustrates its article with a menagerie scene that is
    # unreadable at 20px.
    "PET": "Rocky",
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
skill_map, skill_missing = _carried_over("skills"), []
if "skills" in KINDS:
    print(f"SKILLS ({len(names['skills'])})")
    skill_map = {}
else:
    print(f"SKILLS  skipped, {len(skill_map)} carried over")
for skill in names["skills"] if "skills" in KINDS else []:
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

def page_thumbnails(titles):
    """Lead image per wiki page title.

    A page's lead image rather than a guessed filename, because activity
    filenames are not derivable: Zulrah.png is a 404, the file is
    Zulrah_(serpentine).png.
    """
    found = {}
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
            found[title] = thumb
            if title in remap:
                found[remap[title]] = thumb
        time.sleep(0.3)
    return found


# --------------------------------------------------------------- activities
act_map, act_missing = _carried_over("activities"), []
if "activities" in KINDS:
    print(f"\nACTIVITIES ({len(names['activities'])})")
    act_map = {}
    wanted = {a: ALIASES.get(a, a) for a in names["activities"]}
    thumbs = page_thumbnails(sorted(set(wanted.values())))
else:
    print(f"\nACTIVITIES  skipped, {len(act_map)} carried over")
    wanted, thumbs = {}, {}
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

# --------------------------------------------------------------- event types
type_map, type_missing = _carried_over("types"), []
if "types" in KINDS:
    print(f"\nEVENT TYPES ({len(TYPE_TITLES)})")
    type_map = {}
    type_thumbs = page_thumbnails(sorted(set(TYPE_TITLES.values())))
else:
    print(f"\nEVENT TYPES  skipped, {len(type_map)} carried over")
    type_thumbs = {}
for event_type, title in (TYPE_TITLES.items() if "types" in KINDS else []):
    url = type_thumbs.get(title)
    if not url:
        type_missing.append(event_type)
        print(f"  MISS {event_type}  (no lead image on {title!r})")
        continue
    target = TYPE_DIR / f"{slug(event_type)}.png"
    if save(target, url):
        type_map[event_type] = target.name
        print(f"  ok   {event_type:<20} {title}")
    else:
        type_missing.append(event_type)
    time.sleep(0.1)

# --------------------------------------------------------------- manifest
manifest = {"skills": skill_map, "activities": act_map, "types": type_map}
(OUT / "icon-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

print(f"\nskills     {len(skill_map)}/{len(names['skills'])}"
      f"  missing: {skill_missing or 'none'}")
print(f"activities {len(act_map)}/{len(names['activities'])}")
if act_missing:
    print("  missing:")
    for a in act_missing:
        print(f"    - {a}")
print(f"types      {len(type_map)}/{len(TYPE_TITLES)}"
      f"  missing: {type_missing or 'none'}")
