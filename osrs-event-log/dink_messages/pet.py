# dink_messages/pet.py

def format_pet(payload: dict, user_tag: str):
    extra = payload.get("extra", {}) or {}

    pet = extra.get("petName", "a new pet")
    milestone = extra.get("milestone")
    duplicate = extra.get("duplicate")

    # Header
    header = f"**{user_tag} just received {pet}!**"

    # Extra lines
    stats = []

    if milestone:
        stats.append(f"Milestone: {milestone}")

    if duplicate:
        stats.append("Duplicate: Yes")

    # No stats at all → return simple header
    if not stats:
        return header, True

    block = " | ".join(stats)
    return f"{header}```c\n{block}\n```", True