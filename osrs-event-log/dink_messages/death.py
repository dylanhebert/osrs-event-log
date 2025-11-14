# dink_messages/death.py

def format_death(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    # Only handle PvP deaths
    if not extra.get("isPvp", False):
        return None  # NPC deaths ignored

    pker = extra.get("killerName", "Unknown player")
    value_lost = extra.get("valueLost", 0)

    # Lost items for high-value callout (≥500k)
    lost_items = extra.get("lostItems", [])
    high_value = [
        f"{i['quantity']}x {i['name']}"
        for i in lost_items
        if i["quantity"] * i["priceEach"] >= 500_000
    ]

    location = extra.get("location") or {}
    region_id = location.get("regionId")

    # ---- HEADER ----
    # Example: "<user> was PKed by **Zezima**"
    header = f"{user_tag} was PKed by **{pker}**"

    # ---- STATS ----
    stats = []

    stats.append(f"Lost: {value_lost:,} gp")

    # if region_id is not None:
    #     stats.append(f"Region: {region_id}")

    if high_value:
        stats.append(f"High value: {', '.join(high_value)}")

    line = " | ".join(stats)

    return f"{header}```c\n{line}\n```"
