# dink_messages/collection.py

def format_collection(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    item = extra.get("itemName", "Unknown item")
    price = extra.get("price", 0)

    completed = extra.get("completedEntries")
    total = extra.get("totalEntries")

    current_rank = extra.get("currentRank", "UNRANKED")
    next_rank = extra.get("nextRank")
    rank_prog = extra.get("rankProgress", 0)
    logs_needed = extra.get("logsNeededForNextRank", 0)

    dropper = extra.get("dropperName", None)
    kc = extra.get("dropperKillCount")

    # ---- HEADER ----
    # Example: "<user> added **Zamorak chaps** to their Collection Log"
    header = f"**{user_tag} added {item} to their Collection Log**"

    # ---- STATS (2–3 important ones, pipe-separated) ----
    stats: list[str] = []

    # Source + KC are nice context
    if dropper:
        if kc is not None:
            stats.append(f"From: {dropper} (KC: {kc})")
        else:
            stats.append(f"From: {dropper}")

    # Entries progress
    if completed is not None and total is not None:
        stats.append(f"Entries: {completed}/{total}")

    # Rank progress
    rank_total = rank_prog + logs_needed if logs_needed is not None else None
    # if next_rank and rank_total:
    #     stats.append(f"Rank: {current_rank} → {next_rank} ({rank_prog}/{rank_total})")
    # elif current_rank:
    #     stats.append(f"Rank: {current_rank}")

    # Optional: include price if you want a 3rd stat in some cases
    if price and len(stats) < 3:
        stats.append(f"Price: {price:,} gp")

    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}```"
