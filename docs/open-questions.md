# Open questions

Everything here is **unconfirmed**: seen in passing, not traced to the end. Addresses are
in `analysis/master.elf`.

## Timing and frame pacing

Mostly answered in `fight-loop.md`, as calculated rather than measured values. Still open:

- Real frame rates at each speed, and which machine counts as the reference.
- How input timers that use real time should map to ticks, and what to do about input being
  polled between ticks in local play but not in network play.
- What the original's network wait does exactly (0x2db18).

## Hit testing and the fight's structure

See `fight-loop.md`. Static jobs that remain:

- Which arenas' scripts fill the pixel table at object manager +0x20, and so which arena colours
  trigger objects.
- Which objects set the script flag that moves them by sin and cos, and whether they can hit.
- Which particle and effect sprites use fighter colour ranges, and at which layers.
- What the options at bits 6-8 and 15 of 0x8e5e2 are called, from `ENGLISH.DAT`.
- Which sprites use remap index 7 (file table 4, which takes fighter colours out of range).

## Questions only a real run can answer

- The low byte of the back buffer's heap address, which the dither pattern uses. See `formats.md`.

## Possible bugs

To log for a decision, not fix. None confirmed.

- Reads of registers that may be uninitialised on some path: 0x26854 (ESI), 0x1aae0 (DI),
  0x2f588 (EBP), 0x355e0 and 0x3d798 (ESI), 0x3eecc (SI). These could be paths that never
  happen.
- Player 2's own pixels can block player 2's attack points on player 1, at the default draw
  order. This one is likely a balance quirk to keep, not a bug, but it's listed for Owen.
- The original copies only two bits of the settings at 0x8e5e2 between machines. Other settings could
  differ between them, including bit 7, which gates fight logic. Whether that could desync them isn't
  confirmed. The shadow level is probably not a cause, since the default shadow table leaves fighter
  colours unchanged.
- 0x8bb64 feeds object motion and is reset by a debug key combination, local to one machine.
- A rare source pixel in 0x30-0x5f counts as player 2 even on player 1's sprite.
- A shadow at level 3 on an empty placeholder sprite (`formats.md`) gives the original's memset a negative length, which would
  crash it. Found under emulation. Whether the game ever asks for this isn't known. The port does nothing in that case.
- A local on-screen message covers the fighters in the picture hit tests read (`fight-loop.md`).
- The timer counter resets to 0 once it passes 0x7d00, about 220 seconds at the calculated
  rate. Durations measured with 0x55b60 across a reset may come out wrong.

## Quirks to keep

Measured by `tools/fp_differential.py`, on one host, with x87 under emulation.

- Int to float conversion truncates rather than rounds, which shows from 2^24 up. 0 * x
  and 0 / x for floats give +0, never -0.
