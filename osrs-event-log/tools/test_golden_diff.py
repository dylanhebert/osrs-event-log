#!/usr/bin/env python3
"""T3 — golden diff. The migrated bot must post exactly the same messages.

    python tools/test_golden_diff.py
    python tools/test_golden_diff.py --keep    # leave both trees for inspection

Builds a pristine pre-migration checkout from git, feeds it and the working tree
the SAME frozen hiscores payloads, and asserts the resulting Discord messages
are byte-identical.

This is the only test that catches the quiet failures. T2 proves nothing looks
changed when nothing changed; it cannot see a milestone that has stopped firing.
Under integers these all fail silently — no exception, no log line:

    level == '99'                          never true  -> no 99 milestones
    str(level) in custom_messages['levels'] never true  -> no joke messages
    f"... {new_data['xp']}"                 renders 102315637, not 102,315,637
    f"... {new_data['rank']}"               renders None or -1, not '--'

The payloads deliberately cross every threshold, because nothing in the live
data is sitting on one — see tools/scenarios.py.

Offline: no Discord token, no network. Nothing is written to the source data.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Gitignored state, taken from --data-dir so that a fixture run compares the
# same inputs on both sides. Copying these from the repo instead would feed the
# pre-migration tree whatever happens to be in data/ while the migrated side
# reads the fixture, and the diff would be meaningless.
STATE_FROM_DATA_DIR = [
    ("db_discord.json",),
    ("db_runescape.json",),
    ("sotw", "sotw_config.json"),
    ("botw", "botw_config.json"),
    ("custom_messages.json",),
    ("sotw", "all_skills.json"),
    ("botw", "all_bosses.json"),
]
TOOLS_INTO_OLD_TREE = ["harness.py", "_golden_runner.py", "__init__.py"]


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def build_old_tree(root, base_ref, dest, data_dir):
    """Export the pre-migration tree from git, then drop in the gitignored
    state files and the harness (which post-dates the base commit)."""
    os.makedirs(dest, exist_ok=True)
    archive = run(["git", "-C", root, "archive", base_ref, "osrs-event-log"])
    if archive.returncode:
        return f"git archive failed: {archive.stderr.strip()}"

    tar_path = os.path.join(dest, "_tree.tar")
    with open(tar_path, "wb") as fh:
        proc = subprocess.run(["git", "-C", root, "archive", base_ref, "osrs-event-log"],
                              stdout=fh)
    if proc.returncode:
        return "git archive failed writing tar"
    untar = run(["tar", "-xf", tar_path, "-C", dest])
    if untar.returncode:
        return f"tar failed: {untar.stderr.strip()}"
    os.remove(tar_path)

    inner = os.path.join(dest, "osrs-event-log")
    if not os.path.isdir(inner):
        return f"expected {inner} after export"

    here = os.path.dirname(os.path.abspath(__file__))
    live = os.path.dirname(here)

    for parts in STATE_FROM_DATA_DIR:
        source = os.path.join(data_dir, *parts)
        target = os.path.join(inner, "data", *parts)
        if not os.path.exists(source):
            # all_skills / all_bosses / custom_messages are tracked, so the git
            # export already has them; only the gitignored state must be there.
            if parts[-1] in ("db_discord.json", "db_runescape.json",
                             "sotw_config.json", "botw_config.json"):
                return f"missing {source}"
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)

    # Config is deployment-level, not state, so it always comes from the repo.
    bot_config = os.path.join(live, "bot_config.json")
    if not os.path.exists(bot_config):
        return f"missing {bot_config}"
    shutil.copy2(bot_config, os.path.join(inner, "bot_config.json"))

    os.makedirs(os.path.join(inner, "tools"), exist_ok=True)
    for name in TOOLS_INTO_OLD_TREE:
        source = os.path.join(here, name)
        if os.path.exists(source):
            shutil.copy2(source, os.path.join(inner, "tools", name))
        elif name == "__init__.py":
            open(os.path.join(inner, "tools", name), "w").close()
    return inner


def compare(old, new, problems):
    labels = set(old["results"]) | set(new["results"])
    for label in sorted(labels):
        before = old["results"].get(label)
        after = new["results"].get(label)
        if before is None or after is None:
            problems.append((label, "scenario missing from one side", None, None))
            continue
        if before.get("error") != after.get("error"):
            problems.append((label, "error differs",
                             before.get("error"), after.get("error")))
        if before.get("skipped") != after.get("skipped"):
            problems.append((label, "skip reason differs",
                             before.get("skipped"), after.get("skipped")))
        for bucket in ("milestones", "skills", "minigames"):
            if before[bucket] != after[bucket]:
                problems.append((label, f"{bucket} differ",
                                 before[bucket], after[bucket]))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--base-ref", default=None,
                        help="pre-migration git ref (default: the "
                             "pre-sql-migration branch, else merge-base of "
                             "master and HEAD)")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    live = os.path.dirname(here)
    root = os.path.dirname(live)

    base_ref = args.base_ref
    if base_ref is None:
        # merge-base(master, HEAD) was right while the migration lived on its
        # own branch. Once it merged, master itself became post-migration, so on
        # any branch cut afterwards that merge-base exports the NEW tree and
        # this test silently compares the migration against itself. The
        # symptom is every scenario failing with KeyError: 'current_skill',
        # because the "old" side is SQLite code handed JSON state and no
        # database.
        #
        # The real pre-migration state is preserved on the pre-sql-migration
        # branch. Prefer it, and keep the merge-base as a fallback for anyone
        # running this from a checkout that lacks the branch.
        preferred = run(["git", "-C", root, "rev-parse", "--verify",
                         "--quiet", "pre-sql-migration^{commit}"])
        if preferred.returncode == 0 and preferred.stdout.strip():
            base_ref = preferred.stdout.strip()
        else:
            merge_base = run(["git", "-C", root, "merge-base", "master", "HEAD"])
            if merge_base.returncode:
                print("  could not determine base ref; pass --base-ref",
                      file=sys.stderr)
                return 2
            base_ref = merge_base.stdout.strip()

    # Whatever ref was chosen, prove it is actually pre-migration. data/repo/
    # arrived WITH the migration, so its presence means the "old" side is the
    # new code and the comparison is meaningless. Fail here with an explanation
    # rather than 60 confusing scenario diffs.
    probe = run(["git", "-C", root, "ls-tree", "-r", "--name-only", base_ref,
                 "osrs-event-log/data/repo/"])
    if probe.returncode == 0 and probe.stdout.strip():
        print(f"  base ref {base_ref[:12]} already contains data/repo/, so it is\n"
              f"  POST-migration and cannot serve as the 'before' side.\n"
              f"  Pass --base-ref pre-sql-migration (or the last commit before\n"
              f"  the migration landed).", file=sys.stderr)
        return 2

    scratch = tempfile.mkdtemp(prefix="osrs-golden-")
    db_path = os.path.join(scratch, "osrs.db")
    payload_path = os.path.join(scratch, "payloads.json")
    old_out = os.path.join(scratch, "old.json")
    new_out = os.path.join(scratch, "new.json")

    try:
        # 1. migrate, so the new side has something to read
        migrated = run([sys.executable, os.path.join(here, "migrate_json_to_sqlite.py"),
                        "--data-dir", args.data_dir,
                        "--schema", os.path.join("data", "schema.sql"),
                        "--db", db_path])
        if migrated.returncode:
            print(migrated.stdout)
            print(migrated.stderr, file=sys.stderr)
            return migrated.returncode

        # 2. build the scenario payloads once, from the migrated data, so both
        #    sides receive byte-identical input
        from data import repo
        from tools import scenarios

        repo.connect(path=db_path)
        all_stats = repo.stats.load_all_pollable()
        bases = scenarios.pick_base_players(all_stats)
        repo.close()

        cases, notes = [], {}
        covered, never_covered = set(), {}
        for role, player in bases.items():
            built, skipped = scenarios.build(all_stats[player])
            for label, payload, note in built:
                cases.append([player, label, payload])
                notes[f"{player}::{label}"] = note
                covered.add(label)
            for label in skipped:
                never_covered.setdefault(label, []).append(player)

        # A scenario only counts as uncovered if it applied to nobody.
        never_covered = {label: players for label, players in never_covered.items()
                         if label not in covered}

        with open(payload_path, "w", encoding="utf-8") as fh:
            json.dump(cases, fh)

        print(f"  base ref      {base_ref[:12]}")
        print(f"  base players  " + ", ".join(
            f"{name} ({role})" for role, name in bases.items()))
        print(f"  cases         {len(cases)} across {len(covered)} distinct scenarios")
        if never_covered:
            print(f"\n  NOT COVERED by any base player — these scenarios did not run:")
            for label in sorted(never_covered):
                print(f"      {label}")

        # 3. pre-migration tree
        old_inner = build_old_tree(root, base_ref, os.path.join(scratch, "old"),
                                   os.path.abspath(args.data_dir))
        if not os.path.isdir(str(old_inner)):
            print(f"  FAILED to build the old tree: {old_inner}", file=sys.stderr)
            return 2

        old_run = run([sys.executable, os.path.join("tools", "_golden_runner.py"),
                       "--mode", "json",
                       "--payloads", payload_path, "--out", old_out],
                      cwd=old_inner)
        if old_run.returncode:
            print("  FAILED running the pre-migration side:", file=sys.stderr)
            print(old_run.stdout[-3000:], file=sys.stderr)
            print(old_run.stderr[-3000:], file=sys.stderr)
            return 2

        new_run = run([sys.executable, os.path.join("tools", "_golden_runner.py"),
                       "--mode", "sqlite", "--db", db_path,
                       "--payloads", payload_path, "--out", new_out],
                      cwd=live)
        if new_run.returncode:
            print("  FAILED running the migrated side:", file=sys.stderr)
            print(new_run.stdout[-3000:], file=sys.stderr)
            print(new_run.stderr[-3000:], file=sys.stderr)
            return 2

        with open(old_out, encoding="utf-8") as fh:
            old = json.load(fh)
        with open(new_out, encoding="utf-8") as fh:
            new = json.load(fh)

        problems = compare(old, new, [])

        produced = sum(1 for r in new["results"].values()
                       if r["milestones"] or r["skills"] or r["minigames"])
        messages = sum(len(r["milestones"]) + len(r["skills"]) + len(r["minigames"])
                       for r in new["results"].values())

        print("\n" + "=" * 68)
        if problems:
            print(f"  T3 GOLDEN DIFF: FAILED — {len(problems)} difference(s)")
            print("=" * 68 + "\n")
            for label, what, before, after in problems[:12]:
                print(f"  [{label}] {what}")
                if notes.get(label):
                    print(f"      expected: {notes[label]}")
                print(f"      before: {json.dumps(before)[:400]}")
                print(f"      after : {json.dumps(after)[:400]}\n")
            if len(problems) > 12:
                print(f"  ... and {len(problems) - 12} more")
            return 1

        print("  T3 GOLDEN DIFF: PASSED")
        print("=" * 68 + "\n")
        print(f"    {len(cases):>6,} cases run through both code paths")
        print(f"    {len(covered):>6,} distinct scenarios covered")
        print(f"    {produced:>6,} produced output")
        print(f"    {messages:>6,} messages, all byte-identical to the pre-migration bot")
        print("\n    Milestones, custom messages, comma formatting and '--' for")
        print("    unranked all survive the move to integers.\n")
        return 0
    finally:
        if args.keep:
            print(f"  kept {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
