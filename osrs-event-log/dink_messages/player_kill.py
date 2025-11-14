# dink_messages/player_kill.py

def format_player_kill(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra") or {}

    victim = extra.get("victimName", "a player")
    victim_level = extra.get("victimCombatLevel")
    equipment = extra.get("victimEquipment") or {}
    world = extra.get("world")
    hp = extra.get("myHitpoints")
    last_hit = extra.get("myLastDamage")

    header = f"**{user_tag} has PK'd {victim}**"

    # ---- IMPORTANT STATS ----
    stats = []

    # Combat level
    if victim_level is not None:
        stats.append(f"Combat Lvl: {victim_level}")

    # World
    # if world is not None:
    #     stats.append(f"World: {world}")

    # HP remaining
    # if hp is not None:
    #     stats.append(f"Your HP: {hp}")

    # Last damage dealt
    if last_hit is not None:
        stats.append(f"Last hit: {last_hit}")

    # Total gear value (if equipment present)
    if equipment:
        total = 0
        for slot, item in equipment.items():
            price = item.get("priceEach", 0)
            total += price
        stats.append(f"Loot Value: {total:,} gp")

    # Nothing extra? Return just the header
    if not stats:
        return header

    line = " | ".join(stats)
    return f"{header}```c\n{line}\n```"
