# dink_messages/loot.py

def format_loot(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra", {}) or {}
    items = extra.get("items", [])
    source = extra.get("source", "Unknown source")
    kc = extra.get("killCount")
    rare_prob = extra.get("rarestProbability")

    # ---- MAIN ITEM LINE ----
    total_value = sum(i["quantity"] * i["priceEach"] for i in items)
    items_str = ", ".join(f"{i['quantity']}x {i['name']}" for i in items)

    # ---- HIGH-VALUE ITEMS (≥ 500k) ----
    high_value_items = [
        f"{i['quantity']}x {i['name']}"
        for i in items
        if i["quantity"] * i["priceEach"] >= 500_000
    ]

    header = f"**{user_tag} got {items_str} from {source}**"

    # ---- STATS (pipe-separated) ----
    stats = []

    if total_value:
        stats.append(f"Value: {total_value:,} gp")

    if kc is not None:
        stats.append(f"KC: {kc}")

    # Rare chance if included in the webhook
    if rare_prob is not None:
        percent = rare_prob * 100
        stats.append(f"Chance: {percent:.5f}%")

    # High-value drops
    if high_value_items:
        stats.append(f"High value: {', '.join(high_value_items)}")

    # If no stats, return header only
    if not stats:
        return header

    line = " | ".join(stats)
    
    notify = False
    if total_value >= 10000000:
        notify = True

    return f"{header}```c\n{line}```", notify
