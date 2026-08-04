"""Deterministic hiscores payloads that cross every milestone boundary.

Feeds T3 (old code vs new code produce identical messages) and T4 (the
milestone logic still fires under integers).

A zero-delta run proves the migration will not spam, but it cannot prove the
opposite failure: that a milestone has quietly stopped firing. Those paths only
execute when a value crosses a threshold, and nothing in the live data is
sitting on one. So the thresholds are crossed on purpose here.

Every scenario targets a branch in activity/PlayerUpdate.py, and several target
comparisons that used to be against strings — `level == '99'` and the
string-keyed custom_messages['levels'] lookup. Those fail silently under
integers: no error, no log line, the milestone simply never appears.
"""

import copy

# Skills chosen because every tracked player has them and they are not the
# current SOTW skill in the shipped config, so the accumulator path stays out of
# the comparison.
LEVEL_SKILL = "Attack"
XP_SKILL = "Slayer"


def _payload(stats):
    """Stored stats (ints, None for unranked) -> an index_lite.json body."""
    def out(value):
        return -1 if value is None else int(value)

    return {
        "skills": [{"id": i, "name": name,
                    "rank": out(v.get("rank")),
                    "level": out(v.get("level")),
                    "xp": out(v.get("xp"))}
                   for i, (name, v) in enumerate(stats.get("skills", {}).items())],
        "activities": [{"id": i, "name": name,
                        "rank": out(v.get("rank")),
                        "score": out(v.get("score"))}
                       for i, (name, v) in enumerate(stats.get("minigames", {}).items())],
    }


def _bump_overall(stats, xp_delta=0, level_delta=0):
    overall = stats["skills"].get("Overall")
    if overall:
        overall["xp"] += xp_delta
        overall["level"] += level_delta


def _set_overall(stats, level=None, xp=None):
    overall = stats["skills"].get("Overall")
    if overall:
        if level is not None:
            overall["level"] = level
        if xp is not None:
            overall["xp"] = xp


def build(base_stats):
    """Return (scenarios, skipped) for one player's stored stats.

    `scenarios` is [(label, payload, note), ...]; `skipped` is the labels that
    do not apply to this player — a maxed account cannot level up to 99, an
    account with all 25 skills cannot gain one for the first time.

    Skipped labels are returned rather than dropped so the caller can report
    coverage. A scenario that silently vanishes turns a passing test into a
    vacuous one, which for the 99-milestone path is exactly the failure the test
    exists to catch.

    Overall xp is moved in every scenario that should produce output, because
    the looper's early-out returns before touching anything else if it has not.
    """
    scenarios = []
    skipped = []

    def add(label, mutate, note):
        stats = copy.deepcopy(base_stats)
        if mutate(stats) is False:
            skipped.append(label)
        else:
            scenarios.append((label, _payload(stats), note))

    # --- nothing happened ------------------------------------------------- #
    add("no_change", lambda s: None,
        "identical input; must produce no messages at all")

    # --- xp gain, no level change ----------------------------------------- #
    def xp_only(stats):
        skill = stats["skills"].get(XP_SKILL)
        if not skill:
            return False
        skill["xp"] += 50_000
        _bump_overall(stats, xp_delta=50_000)
    add("xp_gain_no_levelup", xp_only,
        "xp moves but level does not; no message, but the player is not skipped")

    # --- ordinary level up ------------------------------------------------- #
    def level_up(stats):
        skill = stats["skills"].get(LEVEL_SKILL)
        if not skill or skill["level"] >= 98:
            return False
        skill["level"] += 1
        skill["xp"] += 100_000
        _bump_overall(stats, xp_delta=100_000, level_delta=1)
    add("level_up_plain", level_up,
        "regular skill update, no custom message")

    # --- level up onto a level with a custom message ----------------------- #
    # custom_messages['levels'] is keyed by STRINGS ("92", "69", ...). Under
    # integers this lookup silently misses and the joke never appears.
    for level in (92, 69, 50):
        def to_level(stats, level=level):
            skill = stats["skills"].get(LEVEL_SKILL)
            if not skill:
                return False
            skill["level"] = level
            skill["xp"] += 250_000
            _bump_overall(stats, xp_delta=250_000, level_delta=3)
        add(f"level_up_custom_{level}", to_level,
            f"custom_messages['levels']['{level}'] must still be appended")

    # --- 99 -------------------------------------------------------------- #
    # `level == '99'` was a string comparison. Under integers it is False
    # forever: the 99 goes to the regular skills list instead of milestones,
    # and the max_levels message disappears. Nothing errors.
    def to_99(stats):
        skill = stats["skills"].get(LEVEL_SKILL)
        if not skill:
            return False
        skill["level"] = 99
        skill["xp"] = 13_034_431
        _bump_overall(stats, xp_delta=1_000_000, level_delta=5)
    add("level_up_99", to_99,
        "MILESTONE + custom_messages['max_levels'] message")

    # --- xp thresholds ----------------------------------------------------- #
    def xp_10m(stats):
        skill = stats["skills"].get(XP_SKILL)
        if not skill or skill["xp"] >= 10_000_000:
            return False
        skill["xp"] = 10_000_001
        _bump_overall(stats, xp_delta=10_000_000)
    add("skill_xp_10m", xp_10m, "10M skill xp threshold")

    def overall_100m(stats):
        overall = stats["skills"].get("Overall")
        if not overall or overall["xp"] >= 100_000_000:
            return False
        _set_overall(stats, xp=100_000_001)
    add("overall_xp_100m", overall_100m, "100M overall xp MILESTONE")

    # --- total level thresholds -------------------------------------------- #
    for total in (2000, 2200):
        def to_total(stats, total=total):
            overall = stats["skills"].get("Overall")
            if not overall or overall["level"] >= total:
                return False
            _set_overall(stats, level=total, xp=overall["xp"] + 5_000_000)
        add(f"total_level_{total}", to_total, f"{total} total level MILESTONE")

    def maxed(stats):
        overall = stats["skills"].get("Overall")
        if not overall or overall["level"] == 2376:
            return False
        _set_overall(stats, level=2376, xp=overall["xp"] + 20_000_000)
    add("total_level_maxed", maxed, "2376 MAXED milestone")

    # --- a skill appearing for the first time ------------------------------ #
    def new_skill(stats):
        for candidate in ("Sailing", "Construction", "Hunter", "Runecraft"):
            if candidate not in stats["skills"]:
                stats["skills"][candidate] = {"rank": 90_000, "level": 8, "xp": 1_500}
                _bump_overall(stats, xp_delta=1_500, level_delta=8)
                return
        return False
    add("skill_first_time", new_skill,
        "'first time this skill is on the Hiscores'")

    # --- bosses ------------------------------------------------------------ #
    def boss_first(stats):
        for candidate in ("Zulrah", "Vorkath", "Giant Mole", "Kraken"):
            if candidate not in stats["minigames"]:
                stats["minigames"][candidate] = {"rank": 120_000, "score": 1}
                _bump_overall(stats, xp_delta=10_000)
                return
        return False
    add("boss_first_kill", boss_first,
        "first kill; custom_messages['bosses'] entries go to MILESTONES")

    def boss_500(stats):
        for name, values in stats["minigames"].items():
            if "Clue" in name or "Bounty" in name:
                continue
            if values["score"] < 500:
                values["score"] = 501
                _bump_overall(stats, xp_delta=200_000)
                return
        return False
    add("boss_500_kc", boss_500, "500 kill count MILESTONE")

    # --- clues ------------------------------------------------------------- #
    def clue_first(stats):
        for tier in ("Clue Scrolls (master)", "Clue Scrolls (elite)",
                     "Clue Scrolls (hard)", "Clue Scrolls (easy)"):
            if tier not in stats["minigames"]:
                stats["minigames"][tier] = {"rank": 40_000, "score": 1}
                _bump_overall(stats, xp_delta=5_000)
                return
        return False
    add("clue_first_time", clue_first, "first clue of a tier")

    def clue_100(stats):
        for name, values in stats["minigames"].items():
            if "Clue" in name and "(all)" not in name and values["score"] < 100:
                values["score"] = 101
                _bump_overall(stats, xp_delta=5_000)
                return
        return False
    add("clue_100", clue_100, "100 clues of a tier MILESTONE")

    # --- rank movement ------------------------------------------------------ #
    # rank must never drive change detection, and an unranked value must render
    # as '--' rather than 'None' or '-1'.
    def unrank(stats):
        skill = stats["skills"].get(XP_SKILL)
        if not skill:
            return False
        skill["rank"] = None
        skill["xp"] += 75_000
        _bump_overall(stats, xp_delta=75_000)
    add("rank_becomes_unranked", unrank,
        "rank -> unranked; message must show '--'")

    def rerank(stats):
        for name, values in stats["skills"].items():
            if values.get("rank") is None:
                values["rank"] = 55_555
                values["xp"] += 25_000
                _bump_overall(stats, xp_delta=25_000)
                return
        return False
    add("rank_becomes_ranked", rerank, "unranked -> ranked")

    def rank_only(stats):
        skill = stats["skills"].get(XP_SKILL)
        if not skill:
            return False
        skill["rank"] = (skill.get("rank") or 10_000) + 37
    add("rank_drift_only", rank_only,
        "only rank moved; must be skipped, rank drifts between any two fetches")

    return scenarios, skipped


def pick_base_players(all_stats):
    """A spread of players, so that every scenario applies to at least one.

    One base player cannot cover the whole matrix: a near-maxed account is the
    only one that can sit just below 2200 total, and is also the only one that
    can NOT gain a skill for the first time. Picking by profile rather than
    taking the richest player is what stops the first-time and low-threshold
    branches from silently dropping out of the test.

    Returns {role: rs_name}, deduplicated, sorted for determinism.
    """
    usable = {name: stats for name, stats in all_stats.items() if stats.get("skills")}
    if not usable:
        return {}

    def size(name):
        return (len(usable[name].get("skills", {}))
                + len(usable[name].get("minigames", {})))

    def overall_xp(name):
        overall = usable[name]["skills"].get("Overall")
        return overall["xp"] if overall else 0

    picks = {}
    picks["richest"] = max(sorted(usable), key=size)
    picks["sparsest"] = min(sorted(usable), key=size)
    picks["lowest_xp"] = min(sorted(usable), key=overall_xp)

    no_overall = [n for n in sorted(usable) if "Overall" not in usable[n]["skills"]]
    if no_overall:
        # Cannot take the Overall early-out, so every skill is compared
        # individually — a genuinely different path through the looper.
        picks["no_overall"] = no_overall[0]

    unranked = [n for n in sorted(usable)
                if any(v.get("rank") is None for v in usable[n]["skills"].values())]
    if unranked:
        picks["has_unranked"] = unranked[0]

    seen, out = set(), {}
    for role, name in picks.items():
        if name not in seen:
            seen.add(name)
            out[role] = name
    return out
