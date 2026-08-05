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
| **`icons.png`** | **The sprite actually served: all 121 icons in one 12x11 grid** |
| `../css/icons.css` | Generated `.ic-*` classes, one background-position per icon |
| `skills/*.png` | Source art for 25 skills. Not served; kept so the sprite can be rebuilt offline |
| `activities/*.png` | Source art for 89 bosses, raids and minigames. Same |
| `types/*.png` | Source art for 7 event types, see below |
| `icon-manifest.json` | Maps a database name to `{file, cls}` |

## The seven event-type icons

The activity feed puts an icon on every row, chosen by reading the skill or
boss out of the message text. That works for 99.3% of hiscores events, because
their wording always names what happened. Dink events often do not: they name a
quest, an item or another player, none of which the hiscores track.

These seven cover what is left. Each is a wiki page's lead image, chosen in
`web/tools/fetch_icons.py`:

| event type | wiki page |
|---|---|
| `QUEST` | Quest point |
| `GRAND_EXCHANGE` | Grand Exchange |
| `DEATH` | Grave |
| `COMBAT_ACHIEVEMENT` | Combat Achievements |
| `ACHIEVEMENT_DIARY` | Achievement Diary |
| `LOOT` | Coins |
| `PET` | Rocky |

`PET` is one pet standing for all of them: no page depicts pets in general, and
the one that comes closest illustrates itself with a menagerie scene that is
unreadable at 20px.

Four more types needed no new art because the sprite already had the right
picture under an activity or skill name: `COLLECTION` borrows Collections
Logged, `CLUE` borrows Clue Scrolls (all), `SLAYER` borrows the Slayer skill,
and `PLAYER_KILL` borrows Bounty Hunter. Those borrows live in `web/format.py`
rather than here, since they are a mapping and not a file.

## Why a sprite

A single player page references over a hundred icons. As separate `<img>` tags
that is a hundred-plus round trips for 3 KB files, and any one of them can fail
on its own. The sprite is **one** cached request: 217 KB, against 336 KB spread
over 114 requests.

Cells are 40px drawn into a 20px box, so the art stays crisp on 2x displays
without shipping a second sheet.

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
