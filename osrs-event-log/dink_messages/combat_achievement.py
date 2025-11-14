# dink_messages/combat_achievement.py

def format_combat_achievement(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    tier = extra.get("tier") or extra.get("currentTier") or "UNKNOWN"
    task = extra.get("task", "Unknown task")

    task_points = extra.get("taskPoints")
    total_points = extra.get("totalPoints")
    total_possible = extra.get("totalPossiblePoints")

    tier_progress = extra.get("tierProgress")
    tier_total_points = extra.get("tierTotalPoints")

    next_tier = extra.get("nextTier")
    just_completed_tier = extra.get("justCompletedTier")

    # ---- TIER COMPLETION CASE ----
    if just_completed_tier:
        # Header: "<user> completed the MASTER Combat Achievements tier"
        header = (
            f"{user_tag} completed the **{just_completed_tier}** "
            f"Combat Achievements tier"
        )

        stats: list[str] = []

        # Final task that pushed the tier over the line
        if task:
            stats.append(f"Final task: {task}")

        # Overall points
        if total_points is not None and total_possible is not None:
            stats.append(f"Total points: {total_points}/{total_possible}")

        # Next tier if available
        if next_tier:
            stats.append(f"Next tier: {next_tier}")

        if not stats:
            return header

        line = " | ".join(stats)
        return f"{header}```c\n{line}\n```"

    # ---- NORMAL COMBAT TASK CASE ----
    # Header: "<user> completed a GRANDMASTER combat task: Peach Conjurer"
    header = f"{user_tag} completed a **{tier}** combat task: **{task}**"

    stats: list[str] = []

    # Task points gained
    if task_points is not None:
        stats.append(f"Task points: +{task_points}")

    # Tier progress within this tier
    if tier_progress is not None and tier_total_points is not None:
        stats.append(f"Tier ({tier}): {tier_progress}/{tier_total_points}")

    # Overall points across all tiers
    if total_points is not None and total_possible is not None:
        stats.append(f"Total points: {total_points}/{total_possible}")

    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}\n```"

