# dink_messages/grand_exchange.py

def format_grand_exchange(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}
    item = extra.get("item") or {}

    qty = item.get("quantity", 0)
    name = item.get("name", "Unknown item")
    price_each = item.get("priceEach", 0)
    tax = item.get("sellerTax", 0)

    total_price = qty * price_each

    market = extra.get("marketPrice")
    target_price = extra.get("targetPrice")
    status = (extra.get("status") or "").upper()

    verb_map = {
        "BOUGHT": "bought",
        "SOLD": "sold",
        "CANCELLED": "cancelled",
    }
    verb = verb_map.get(status, status.lower() or "traded")

    # ---- HEADER ----
    # Example: "<user> bought **1x Rune essence** on the Grand Exchange"
    header = f"**{user_tag} {verb} {qty}x {name} on the Grand Exchange**"

    # ---- STATS (2–3 key stats, pipe-separated) ----
    stats: list[str] = []

    if price_each and qty > 1:
        stats.append(f"Each: {price_each:,} gp")

    if total_price:
        stats.append(f"Total: {total_price:,} gp")

    if tax and tax > 0:
        stats.append(f"Tax: {tax:,} gp")

    # if market is not None:
    #     stats.append(f"Market: {market:,} gp")

    # If we still have room and target exists, include it too (max 3–4 is fine)
    # if target_price is not None and len(stats) < 3:
    #     stats.append(f"Target: {target_price:,} gp")

    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}\n```"
