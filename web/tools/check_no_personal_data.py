"""Fail if the staged diff carries live personal data. Run before committing.

    web/.venv/Scripts/python.exe -m web.tools.check_no_personal_data

THIS EXITS NON-ZERO. The check existed before as a snippet pasted into a shell
one-liner that only printed its findings, so a `&&` after it ran regardless and
a real RuneScape name went into a commit while the check was reporting it. A
guard that reports without failing is not a guard.

Checks only the ADDED lines. A diff that removes a name necessarily contains
it, and flagging that would make the scrubbing commits unpassable.

Matching is on word boundaries. Plain substring matching is useless here: one
Discord username in this data is "Play", which appears inside "Player",
"PlayerUpdate" and "players", so it matched almost every file in the tree.
"""

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Anything shorter than this is a word, not a name.
MIN_LENGTH = 6

SOURCES = [
    ("RuneScape name", "SELECT rs_name FROM players"),
    ("RuneScape name", "SELECT display_name FROM players"),
    ("server name", "SELECT name FROM servers"),
    ("Discord name", "SELECT username FROM discord_members"),
    ("Discord name", "SELECT display_name FROM discord_members"),
    ("member id", "SELECT DISTINCT member_id FROM player_servers"),
    ("server id", "SELECT id FROM servers"),
    ("channel id", "SELECT channel_id FROM servers"),
    ("dink key", "SELECT dink_link_key FROM players"),
    ("token hash", "SELECT token_hash FROM web_credentials"),
]

# Things that are not in the database but must not be published either.
PATTERNS = [
    (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "an IP address"),
    (r"(?i)greendonut", "the server's domain"),
    (r"/home/deploy", "a server path"),
    (r"(?i)\bdylan\b|\bhebert\b", "the author's real name"),
]


# This file has to contain the strings it looks for, so scanning it would
# always fail. Nothing else is exempt.
SELF = "web/tools/check_no_personal_data.py"


def staged_additions():
    """Added lines from the staged diff, per file, excluding this checker."""
    diff = subprocess.run(
        ["git", "diff", "--cached"], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace").stdout
    kept, skipping = [], False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            skipping = SELF in line
        elif line.startswith("+") and not line.startswith("+++") and not skipping:
            kept.append(line)
    return "\n".join(kept)


def live_values(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = []
    for label, query in SOURCES:
        try:
            rows = conn.execute(query).fetchall()
        except sqlite3.Error:
            continue                      # a table this snapshot predates
        for (value,) in rows:
            text = "" if value is None else str(value)
            if len(text) < MIN_LENGTH:
                continue
            # Stored with "+" for spaces; a leak can be written either way.
            for form in {text, text.replace("+", " ")}:
                out.append((label, form))
    conn.close()
    return out


def main():
    db_path = ROOT / "fixtures" / "ui-dev.db"
    if not db_path.exists():
        print(f"no snapshot at {db_path}, cannot check. Refusing to pass.")
        return 2

    added = staged_additions()
    if not added.strip():
        print("nothing staged.")
        return 0

    found = []
    for label, value in live_values(db_path):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])",
            re.IGNORECASE)
        if pattern.search(added):
            found.append((label, value))
    for pattern, label in PATTERNS:
        if re.search(pattern, added):
            found.append((label, re.search(pattern, added).group(0)))

    print(f"checked {len(added):,} added characters")
    if not found:
        print("CLEAN")
        return 0

    print(f"\n{len(found)} LEAK(S) in the staged diff:")
    for label, value in found:
        print(f"  {label}: {value}")
        for line in added.splitlines():
            if value.lower() in line.lower():
                print(f"      {line.strip()[:100]}")
                break
    print("\nReplace them with invented names and stage again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
