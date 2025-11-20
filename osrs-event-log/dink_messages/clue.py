# dink_messages/clue.py

def format_clue(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    clue_type = extra.get("clueType", "Unknown")
    completed = extra.get("numberCompleted", 0)
    items = extra.get("items", [])

    # ---- TOTAL VALUE ----
    total_value = sum(i["quantity"] * i["priceEach"] for i in items)

    if total_value < 250000:
        return None

    # ---- HIGH-VALUE ITEMS (≥ 500k) ----
    high_value_items = [
        f"{i['quantity']}x {i['name']}"
        for i in items
        if i["quantity"] * i["priceEach"] >= 500_000
    ]

    # ---- HEADER ----
    header = f"**{user_tag} completed a {clue_type} clue**"

    # ---- STATS ----
    stats = []

    stats.append(f"Completed: {completed}")
    stats.append(f"Loot: {total_value:,} gp")

    if high_value_items:
        hv_list = ", ".join(high_value_items)
        stats.append(f"High value: {hv_list}")

    line = " | ".join(stats)

    notify = False
    if total_value >= 10000000:
        notify = True

    return f"{header}```c\n{line}```", notify
