# dink_messages/quest.py

SPECIAL_QUESTS = {
    "Desert Treasure II - The Fallen Empire",
    "Dragon Slayer II",
    "Song of the Elves",
    "While Guthix Sleeps",
    "Monkey Madness II"
}

def format_quest(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    quest = extra.get("questName", "a quest")
    completed = extra.get("completedQuests")
    total = extra.get("totalQuests")
    qp = extra.get("questPoints")
    total_qp = extra.get("totalQuestPoints")

    # ---- HEADER ----
    # Example: "<user> completed **Dragon Slayer I**"
    header = f"{user_tag} completed **{quest}**"

    # ---- IMPORTANT STATS (pipe-separated) ----
    stats = []

    # Quests progress
    if completed is not None and total is not None:
        stats.append(f"Quests: {completed}/{total}")

    # Quest Points
    if qp is not None and total_qp is not None:
        stats.append(f"QP: {qp}/{total_qp}")

    # No extra stats? Just return the header
    if not stats:
        return header

    line = " | ".join(stats)

    notify = False
    if quest in SPECIAL_QUESTS:
        notify = True
    
    return f"{header}```c\n{line}\n```", notify
