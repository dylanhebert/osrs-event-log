# dink_messages/pet.py

def format_pet(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra", {}) or {}
    pet = extra.get("petName", "a new pet")
    milestone = extra.get("milestone")
    suffix = f" ({milestone})" if milestone else ""
    return f"{user_tag} just received **{pet}**{suffix}!", True
