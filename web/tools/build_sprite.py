"""Pack every skill and activity icon into one sprite sheet plus its CSS.

Step two of two. Run web/tools/fetch_icons.py first.

    python -m web.tools.fetch_icons
    python -m web.tools.build_sprite

MAINTENANCE SCRIPT, NOT PART OF THE APP. It needs Pillow, which is deliberately
NOT in requirements-web.txt: the site never resizes an image at runtime, and the
droplet has no reason to carry an imaging library. Run these with any Python
that has Pillow available.

114 separate <img> requests for 3 KB files is a lot of round trips for very
little payload. One sprite is one request, cached once, and removes any
possibility of an individual icon failing to load.

Re-runnable: it reads either manifest shape, so building twice is harmless.
"""
import json
import math
import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMG = ROOT / "web" / "static" / "img"
CSS = ROOT / "web" / "static" / "css"

CELL = 40          # source cell, drawn into a 20px box for 2x crispness
DISPLAY = CELL // 2

manifest = json.loads((IMG / "icon-manifest.json").read_text(encoding="utf-8"))

def _filename(entry):
    """Accept either manifest shape so this script can be re-run.

    fetch_icons.py writes {name: "file.png"}; this script rewrites it to
    {name: {"file": ..., "cls": ...}}. Reading both makes a rebuild idempotent
    instead of failing on its own previous output.
    """
    return entry["file"] if isinstance(entry, dict) else entry


# The class prefix is the kind's first two letters: sk-, ac-, ty-. Distinct
# prefixes matter because a name can appear in more than one kind -- Slayer is
# both a skill and, as SLAYER, an event type.
KINDS = ("skills", "activities", "types")

entries = []   # (css_class, source_path)
for kind in KINDS:
    for name, entry in sorted(manifest.get(kind, {}).items()):
        filename = _filename(entry)
        entries.append((f"{kind[:2]}-{pathlib.Path(filename).stem}",
                        IMG / kind / filename))

cols = 12
rows = math.ceil(len(entries) / cols)
sheet = Image.new("RGBA", (cols * CELL, rows * CELL), (0, 0, 0, 0))

positions = {}
for index, (css_class, path) in enumerate(entries):
    icon = Image.open(path).convert("RGBA")
    # Scale to FILL the cell, up or down. Image.thumbnail() only ever shrinks,
    # which left the small wiki skill icons (many are 17-25px) sitting tiny
    # inside a 40px cell and rendering at half the size they should. The <img>
    # tags this replaced used object-fit: contain, which scales up to fill the
    # box, so matching that is what keeps the icons the size they were.
    scale = CELL / max(icon.size)
    icon = icon.resize((max(1, round(icon.width * scale)),
                        max(1, round(icon.height * scale))), Image.LANCZOS)
    col, row = index % cols, index // cols
    x = col * CELL + (CELL - icon.width) // 2
    y = row * CELL + (CELL - icon.height) // 2
    sheet.paste(icon, (x, y), icon)
    positions[css_class] = (col, row)

sprite_path = IMG / "icons.png"
sheet.save(sprite_path, optimize=True)

lines = [
    "/* GENERATED: see web/static/img/CREDITS.md for how to rebuild.",
    "   One sprite instead of 114 separate requests. Cells are "
    f"{CELL}px drawn into a {DISPLAY}px box, so the art stays crisp on 2x",
    "   displays without shipping a second sheet. */",
    "",
    ".ic {",
    "  display: inline-block; flex: none;",
    f"  width: {DISPLAY}px; height: {DISPLAY}px;",
    "  background-image: url(../img/icons.png);",
    f"  background-size: {cols * DISPLAY}px {rows * DISPLAY}px;",
    "  background-repeat: no-repeat;",
    "  image-rendering: -webkit-optimize-contrast;",
    "}",
    "",
]
for css_class, (col, row) in sorted(positions.items()):
    lines.append(f".ic-{css_class} {{ background-position: "
                 f"{-col * DISPLAY}px {-row * DISPLAY}px; }}")

(CSS / "icons.css").write_text("\n".join(lines) + "\n", encoding="utf-8")

# The manifest gains the css class per name, so the template does not have to
# recompute a slug that must stay in step with this script.
for kind in KINDS:
    manifest[kind] = {
        name: {"file": _filename(entry),
               "cls": f"{kind[:2]}-{pathlib.Path(_filename(entry)).stem}"}
        for name, entry in manifest.get(kind, {}).items()}
(IMG / "icon-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

singles = sum(p.stat().st_size for _, p in entries)
print(f"  {len(entries)} icons -> {cols}x{rows} grid, {sheet.width}x{sheet.height}px")
print(f"  sprite      {sprite_path.stat().st_size/1024:.0f} KB   (1 request)")
print(f"  was         {singles/1024:.0f} KB across {len(entries)} requests")
print(f"  css         {(CSS/'icons.css').stat().st_size/1024:.0f} KB")
