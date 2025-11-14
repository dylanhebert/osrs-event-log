# dink_messages/kill_count.py

def format_kill_count(payload: dict, user_tag: str):
    extra = payload.get("extra", {}) or {}

    # Only trigger on PB
    if not extra.get("isPersonalBest"):
        return None

    boss = extra.get("boss")
    count = extra.get("count")
    iso_time = extra.get("time")

    # ---- Format ISO8601 "PT46M34S" → "46:34" ----
    formatted_time = None
    if iso_time and iso_time.startswith("PT"):
        mins = 0
        secs = 0

        # Extract minutes
        if "M" in iso_time:
            part = iso_time.split("PT")[1]
            mins = int(part.split("M")[0])

        # Extract seconds
        if "S" in iso_time:
            after_m = iso_time.split("M")[-1] if "M" in iso_time else iso_time[2:]
            secs = int(after_m.replace("S", ""))

        formatted_time = f"{mins}:{secs:02d}"

    # ---- Build message ----
    if formatted_time:
        return f"{user_tag} set a **new {boss} Personal Best!**\n```c\nKC: {count} | Time: {formatted_time}\n```"
    else:
        return f"{user_tag} set a **new {boss} Personal Best!**\n```c\nKC: {count}\n```"

