# dink_messages/kill_count.py

def format_kill_count(payload: dict, user_tag: str) -> str:
    extra = payload.get("extra", {}) or {}
    boss = extra.get("boss")
    count = extra.get("count")
    pb = " **(PB!)**" if extra.get("isPersonalBest") else ""
    return f"{user_tag} is now **{boss} KC {count}**{pb}"
