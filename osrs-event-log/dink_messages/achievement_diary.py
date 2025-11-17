# dink_messages/achievement_diary.py

def format_achievement_diary(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    area = extra.get("area", "Unknown area")
    difficulty = extra.get("difficulty", "UNKNOWN")
    total_diaries = extra.get("total")

    tasks_completed = extra.get("tasksCompleted")
    tasks_total = extra.get("tasksTotal")

    area_tasks_completed = extra.get("areaTasksCompleted")
    area_tasks_total = extra.get("areaTasksTotal")

    # ---- HEADER ----
    # Example: "Green Donut completed the **HARD Varrock** Achievement Diary"
    header = (
        f"**{user_tag} completed the {difficulty} {area} Achievement Diary**"
    )

    # ---- IMPORTANT STATS ----
    stats = []

    # Completed diaries count
    if total_diaries is not None:
        stats.append(f"Diaries: {total_diaries}")

    # Total tasks progress (entire diary system)
    if tasks_completed is not None and tasks_total is not None:
        stats.append(f"Tasks: {tasks_completed}/{tasks_total}")

    # This specific area's tasks
    if area_tasks_completed is not None and area_tasks_total is not None:
        stats.append(f"{area}: {area_tasks_completed}/{area_tasks_total}")

    if not stats:
        return header

    line = " | ".join(stats)

    notify = False
    if difficulty == "ELITE":
        notify = True

    return f"{header}```c\n{line}```", notify
