# dink_messages/slayer.py

def format_slayer(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    task = extra.get("slayerTask", "a slayer task")
    tasks_completed = extra.get("slayerCompleted")
    points_gained = extra.get("slayerPoints")
    kill_count = extra.get("killCount")
    monster = extra.get("monster")

    # ---- HEADER ----
    # Example: "<user> has completed a slayer task: **Kalphites**"
    header = f"{user_tag} has completed a slayer task: **{task}**"

    # ---- IMPORTANT STATS (pipe-separated) ----
    stats = []

    # Task streak
    if tasks_completed is not None:
        stats.append(f"Tasks completed: {tasks_completed}")

    # Points
    if points_gained is not None:
        stats.append(f"Points gained: {points_gained}")

    # Monster + KC
    if monster and kill_count is not None:
        stats.append(f"{monster} KC: {kill_count}")
    elif monster:
        stats.append(f"Monster: {monster}")
    elif kill_count is not None:
        stats.append(f"Kill count: {kill_count}")

    # No extra stats? Just return the header
    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}\n```"
