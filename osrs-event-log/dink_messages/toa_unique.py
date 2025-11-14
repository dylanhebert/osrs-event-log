# dink_messages/toa_unique.py

def format_toa_unique(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    party = extra.get("party") or []
    points = extra.get("rewardPoints")
    levels = extra.get("raidLevels")
    prob = extra.get("probability")

    header = f"**{user_tag} rolled a purple drop from Tombs of Amascut!**"

    # ---- IMPORTANT STATS ----
    stats = []

    # Party listing
    # if party:
    #     stats.append("Party: " + ", ".join(party))

    # Reward points
    if points is not None:
        stats.append(f"Points: {points:,}")

    # Raid levels (invocation total)
    if levels is not None:
        stats.append(f"Raid Level: {levels}")

    # Probability
    if prob is not None:
        # Format cleanly (e.g., 0.2 → 20%)
        pct = round(prob * 100, 2)
        stats.append(f"Chance: {pct}%")

    # No stats? Just return the header
    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}\n```", True
