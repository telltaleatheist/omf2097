# File formats and how sprites are drawn

The layouts here come from `MASTER.DAT`'s load code, and are checked by running that code. For every
animation in all 19 `.BK` and 11 `.AF` files, `tests/differential/test_formats.py` runs the original
animation loader (0x21090) in Unicorn and compares the sprites it builds with a separate Python reader,
and that reader with the C++ loader in `src/assets/`. OpenOMF wasn't used for any of it.

Numbers are little-endian. Offsets in the tables below are from the start of each structure.

## .BK: arenas and screens (0x281b0)

| Field | Size |
|---|---|
| File id | 4 |
| Unknown | 1 |
| Background width, height | 2, 2 |
| Animations, until one has id 50 or more | |
| Background pixels | width * height |
| Palette count | 1 |
| Each palette: colours, then 19 remap tables | 768 + 19 * 256 |
| Trailer | 30 |

Each animation entry in a `.BK`:

| Field | Size |
|---|---|
| File offset of the next entry | 4 |
| Id (50 or more ends the list, with nothing after it) | 1 |
| Six small settings, stored to fields of the ambient slot | 1, 1, 1, 1, 2 |
| One setting | 1 |
| Length of a string, then the string | 2, length |
| Animation (below) | |

The loader can skip an animation through the "next entry" offset, when told to by a table in the object
manager (+0x122). It also shares identical animations between slots to save memory. Neither changes what's
drawn, so the port loads everything and keeps each copy.

## .AF: fighters (0x1b2d0)

| Field | Size |
|---|---|
| Header: two 16-bit, a 32-bit, one byte, a 16-bit, four 32-bit floats, two bytes | 29 |
| Moves, each with a one-byte id, until an id of 70 or more | |
| Trailer | 30 |

Each move: the animation below, 42 bytes of settings, then a 16-bit length and that many bytes.

## Animations (0x21090)

| Field | Size |
|---|---|
| Header. Offset 8 is the coordinate count, offset 10 the sprite count | 11 |
| Coordinates | 4 each |
| Script: length, text, terminator | 2, length, 1 |
| Extra string count, then each as for the script | 1 |
| Sprites | |

## Sprites (0x5c870)

| Field | Size |
|---|---|
| Length of the data | 2 |
| x, y offset (signed) | 2, 2 |
| Width, height | 2, 2 |
| Index, then "missing" | 1, 1 |
| Data, unless shared | length |

The data is 16-bit commands. The low 2 bits are the operation and the rest its value.

| Operation | Meaning |
|---|---|
| 0 | Set the column |
| 1 | The next `value` bytes are pixels |
| 2 | Set the row, and go back to column 0 |
| 3 | End |

**Sharing.** While loading a fighter, a table of data by index (0x8bc78) lets sprites share data. A sprite
marked missing has no data of its own and takes the index's data. A sprite with data whose index is already
taken has its copy discarded, and takes the earlier one too. Moves 12, 13 and 14, and all `.BK` files, turn this off:
their index and missing fields are forced to 0. The table is cleared for each fighter.

**Player 2's colours are made at load time** (0x5e198, set up by 0x1b070). Every pixel below 0x60 in sprite data read
for player 2 gets 0x30 added. That includes a stored 0, which becomes 0x30. Values from 0x30 to 0x5f go to 0x60 and up.

**Things found in the files, all explained:**

- `CREDITS.BK` stores 768-byte palettes as sprites of width 0. The draw routine skips width 0, so the data is
  never walked as commands. The loader checks commands only on sprites with a width.
- 32 sprites are empty placeholders, with length 0 and width and height of 0xec79. One is in `ARENA4.BK`.

## Remap tables

The original keeps these in one block, numbered here by distance from 0x8bf7b. A file palette's 19 tables go in
two parts: the first 4 at 0x8c07b, the other 15 at 0x8c67b. Which palette is loaded comes from the object manager.

| Row | Address | Holds |
|---|---|---|
| 0 | 0x8bf7b | The end of the sharing table, never reached as a table: row 0 is read only for a count of 0, which is skipped |
| 1-4 | 0x8c07b | File tables 0-3. Row 4 is the default remap, used by shadows |
| 5 | 0x8c47b | Brightness of each colour, made by 0x56ddc: the average of red, green, blue |
| 6 | 0x8c57b | No write to it was found, so all 0 as far as read |
| 7-21 | 0x8c67b | File tables 4-18. Row 7 also darkens message boxes (0x5e8dc) |
| 22-24 | 0x8d57b | The current palette's 768 colours, read as if they were tables |
| 25 and up | | Other memory. See "Not modelled" |

Measured in every palette of the five arenas:

- File tables 0-3 leave all 95 fighter colours (1-0x5f) in range. File table 3 leaves them exactly unchanged.
- File table 4 moves all 95 out of range.
- No table moves a colour of 0x60 or more into 1-0x5f.

## Drawing (0x5d0a0 and below)

The queue has 220 entries, drawn in order. Adding an entry (0x5caa0) takes the first free slot at or after the requested
layer, or the last free one before it, or failing that replaces one of no higher priority. Entries are
always kept in slot order, so a full layer pushes a sprite on top of later ones.

Three paths, chosen by flags:

| Flags | Path |
|---|---|
| Any of 0xe0 | 0x5a5d8: replace pixels through remap table row (flags >> 5) |
| Only flips, opacity 0xff, both scales 100 | Plain copy, in 0x5aa3c |
| Anything else | The modes in 0x5aa3c |

In the third path, the first set flag wins, in this order:

| Flag | Effect | Routine |
|---|---|---|
| 0x10 | Ground-plane squash: y offsets are divided by 4, and only rows whose value has low bits 0 remap through row 4 | Inline, 0x5a188 |
| 0x400 | A new value from the source and the destination's brightness | 0x5a4b8, 0x5a540 |
| 0x100 | A two-dimensional lookup by source and destination | 0x5d300, 0x5d338 |
| 0x200 | Adds source * step to the destination | 0x5a3d0, 0x5a484 |
| 0x800 | Adds 0x30 to source values below 0x30 | 0x5a2b4, 0x5a2d8 |
| None | Copy | 0x5a304, 0x5a35c |

Quirks kept, each checked against the original:

- The 0x100 lookup starts one table further on when flipped: row 6 + source, or row 7 + source.
- After a sprite with 0x200 has been drawn in a pass, further sprites with it stop at the top of a colour ramp. Flipped ones
  draw nothing at all.
- The horizontal scale has no effect beyond selecting this path.
- Opacity isn't blending. It is a dither: a counter starts from the low byte of the pixel's address and goes up by 0x6b per pixel,
  and the pixel is drawn only if the counter is at or under the opacity.
- A shadow's position ignores the entry's y. It uses a field that 0x5caa0 always clears, plus the sprite's own offset.

**Shadows (0x5bc7c)** are drawn immediately before their sprite, when the entry asks for one and its y is under 0xbf.
Their rows squash towards row 0xbe. Below level 3, one source row in four remaps through row 4. At level 3, runs are counted
into a row, and each pixel remaps through the row numbered by its count.

## What the port leaves out

- **The dirty-block table (0x8728c).** Only used to update the screen. The rebuild presents the whole picture. So do the display copy and
  the scratch values the routines use within one call.
- **Text entries (flag 0x2000)** call the font, through a hook. The font isn't ported yet.

## Not modelled

- **Blend lookup past source value 17.** Rows 25 and up are other program memory. The port reads them as 0. Frames using the script tag that
  sets this flag (`br`) were scanned. In the arenas they stay at 15 or below, in `ARENA4.BK`. Only `VS.BK`, a menu screen,
  goes higher, to 27. The scan was with a simple pattern on script text, so it's inferred, not proven.
- **Rows 22-24** follow the palette in the original, and code outside this work rewrites it. The port's tables are fixed when built, so
  they would need refreshing if a real case needs them.
- **The back buffer's address.** The dither uses the low byte of the real heap address in the original. `DrawSettings::buffer_address_low`
  stands in for it. Both machines use the same value, so it can't desync, but the value that matches the original is unknown, and takes a
  real run to find. It affects only which pixels of a dithered sprite are drawn.
- **A clip window outside the screen.** The original would write past a row or the buffer. In the game the window stays
  inside, as far as read (0x27348, 0x1b070). The port checks each span and skips any that isn't inside.
