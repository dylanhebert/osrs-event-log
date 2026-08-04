"""The Discord markup renderer, and proof it cannot be used to inject HTML.

events.message is the exact text the bot posted, and for Dink events that text
is built from a payload a player's RuneLite client POSTed to a public endpoint,
authenticated only by a bearer token that two accounts already share. It is
attacker-influenced input being turned into HTML, so the escaping cases below
matter more than the formatting ones.

    web/.venv/Scripts/python.exe -m web.tests.test_markup
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from web.format import discord_markup  # noqa: E402

PASSED, FAILED = [], []


def check(label, actual, expected):
    ok = actual == expected
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"       expected: {expected!r}")
        print(f"       actual:   {actual!r}")


def contains(label, actual, needle, present=True):
    ok = (needle in actual) is present
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"       {'missing' if present else 'unexpectedly present'}: {needle!r}")
        print(f"       actual: {actual!r}")


def main():
    print("escaping (the ones that matter)")
    contains("a script tag is escaped, not emitted",
             str(discord_markup("<script>alert(1)</script>")), "<script>", False)
    contains("...and shows as text",
             str(discord_markup("<script>alert(1)</script>")), "&lt;script&gt;")
    contains("an img onerror payload is escaped",
             str(discord_markup('<img src=x onerror="alert(1)">')), "<img", False)
    contains("bold markers cannot smuggle a tag",
             str(discord_markup("**<b>hi</b>**")), "<b>hi</b>", False)
    contains("...the bold itself still renders",
             str(discord_markup("**<b>hi</b>**")), "<strong>")
    contains("html inside a fenced block is escaped",
             str(discord_markup("```\n<script>x</script>```")), "<script>", False)
    contains("html inside inline code is escaped",
             str(discord_markup("`<script>x</script>`")), "<script>", False)
    contains("an ampersand is escaped once, not twice",
             str(discord_markup("Fish & chips")), "&amp; chips")

    print("\nmentions never render a Discord id")
    check("user mention", str(discord_markup("<@123456789012345678>")), "@someone")
    check("nickname mention", str(discord_markup("<@!123456789012345678>")), "@someone")
    check("role mention", str(discord_markup("<@&123456789012345678>")), "@role")
    check("channel mention", str(discord_markup("<#123456789012345678>")), "#channel")
    contains("a custom emoji keeps its name, drops its id",
             str(discord_markup("<:dink:123456789012345678>")), ":dink:")
    contains("no 18-digit id survives any of the above",
             str(discord_markup("<@123456789012345678> <@&123456789012345678>")),
             "123456789012345678", False)

    print("\nformatting")
    check("bold", str(discord_markup("**hi**")), "<strong>hi</strong>")
    check("italic with asterisks", str(discord_markup("*hi*")), "<em>hi</em>")
    check("italic with underscores", str(discord_markup("_hi_")), "<em>hi</em>")
    check("bold italic", str(discord_markup("***hi***")),
          "<strong><em>hi</em></strong>")
    check("underline", str(discord_markup("__hi__")), "<u>hi</u>")
    check("strikethrough", str(discord_markup("~~hi~~")), "<del>hi</del>")
    check("inline code", str(discord_markup("`hi`")), "<code>hi</code>")
    check("newlines become breaks", str(discord_markup("a\nb")), "a<br>b")
    contains("an underscore inside a word is left alone",
             str(discord_markup("Total_Level stays")), "<em>", False)

    print("\nfenced blocks")
    check("a fenced block with a language",
          str(discord_markup("```c\n428 XP gained```")),
          '<pre><code class="lang-c">428 XP gained</code></pre>')
    check("a fenced block without one",
          str(discord_markup("```plain text```")),
          "<pre><code>plain text</code></pre>")
    contains("formatting inside a fence stays literal",
             str(discord_markup("```c\n**not bold**```")), "**not bold**")

    # Shaped exactly like what the bot posts, with an invented name: this repo
    # is public and real player names do not belong in it.
    print("\na message shaped like a real one")
    real = ("**Zezima levelled up Sailing to 30**```c\n"
            "428 XP gained | Total Sailing XP: 13,489```")
    rendered = str(discord_markup(real))
    contains("title becomes bold", rendered,
             "<strong>Zezima levelled up Sailing to 30</strong>")
    contains("stats become a code block", rendered, '<pre><code class="lang-c">')
    contains("no stray backticks remain", rendered, "`", False)
    contains("no stray asterisks remain", rendered, "*", False)
    print(f"       -> {rendered}")

    print("\nedge cases")
    check("empty string", str(discord_markup("")), "")
    check("None", str(discord_markup(None)), "")
    contains("an unclosed fence is left as text",
             str(discord_markup("```c\nunclosed")), "<pre>", False)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for label in FAILED:
            print("  -", label)
        return 1
    print("MARKUP OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
