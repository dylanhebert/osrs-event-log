# Image credits

All artwork here is Jagex's, taken from the [Old School RuneScape
Wiki](https://oldschool.runescape.wiki), whose content is CC BY-NC-SA 3.0. This
is a non-commercial fan project for a private Discord community, and the site is
behind a sign-in rather than public, which is the basis for using it. Swap these
for original artwork if that ever stops being true.

| path | what |
|---|---|
| `crier.png` | Header mark: the Varrock town crier's chathead, at 2x for high-DPI screens |
| `favicon.ico` | The same, padded to square, at 16/32/48/64 |
| `icon-32.png`, `icon-180.png` | PNG favicon and Apple touch icon |
| `skills/*.png` | 25 skill icons, keyed by the skill name in the database |
| `activities/*.png` | 89 boss, raid and minigame icons |
| `icon-manifest.json` | Maps a database name to a filename |

## Why a manifest rather than deriving the filename

The mapping is not mechanical. Several activity names are not wiki page titles
(`Rifts closed` is Guardians of the Rift, `LMS - Rank` is Last Man Standing,
`Colosseum Glory` is Fortis Colosseum), the clue tiers are item pages rather
than boss pages, and `Overall` has no skill icon at all so it borrows the stats
tab. Deriving a filename would silently miss those; a manifest makes each
decision explicit and reviewable.

**A missing entry is normal, not an error.** Jagex adds bosses and skills, and
the repo layer inserts unknown names on sight, so a name can be in the database
before anyone has fetched an icon for it. The templates render the name alone in
that case, never a broken image.

## Regenerating

Icons come from the wiki API's `pageimages` for bosses (which follows redirects
and picks each page's lead image) and from `images/<Skill>_icon.png` for skills,
then are downscaled to 48px and optimised. They render at 20px, so 48px covers
2x displays; that downscale cut the set from 698 KB to 336 KB.

The town crier icons are padded to square rather than cropped so that neither
the hat nor the beard is lost; the header keeps the original proportions
instead, since it has the room.
