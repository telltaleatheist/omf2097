# The random number generator

Ported in `src/logic/rng.cpp` from `MASTER.DAT` 0x5e2b0 (draw) and 0x5e45c (reseed).
Checked against the original by `tests/differential/test_rng.py`.

## How it works

The generator has no arithmetic state in the usual sense. It reads a fixed 256-byte
table, `RANDOM.DAT`, at four positions, and moves those positions on each draw.

| State | Original address | Notes |
|---|---|---|
| Table | 0x90f14 | Loaded on the first draw. Never written again. A permutation of 0-255. |
| Positions 0-3 | 0x91014-0x91017 | Bytes, wrapping. Start at 0. |
| Reseed counter | 0x84388 | 32 bits. Starts at 0. Other code also writes it. |

**A draw** XORs table bytes to get a sample, scales it by the range, then moves the
positions by +1, -2, +7 and +3. The range picks the formula (signed comparison, so a
negative range counts as small):

| Range | Sample | Result |
|---|---|---|
| up to 0xff | `t0^t1^t3` | `sample * range >> 8` |
| 0x100 to 0xffff | `(t1^t2^t3) << 8 \| t0^t1^t3` | `sample * range >> 16` |
| 0x10000 and up | `t2 << 8 \| t0^t1^t3` | `((sample * (range >> 8)) >> 16 << 8) ^ t2` |

`tN` is the table byte at position N. Multiplication wraps at 32 bits.

**A reseed** adds one to the counter `c`, then sets the positions from a frame number
`f`: `3f + c`, `(f >> 1) + 3c`, `(f >> 3) + (c >> 1)`, `(f >> 5) + 4c`, each cut to a
byte. If the caller's flag is set (mask 0x02 of the byte at 0x8bb72) it does nothing at
all, including leaving the counter alone. The port takes that flag as a `hold` argument,
because the byte belongs to other systems.

## What it depends on

- `RANDOM.DAT`. Nothing else: no clock, no floats, no platform-dependent operations.
- The frame number and whatever the callers do to the counter.

libc `rand` is a separate generator (0x6c21f, a linear congruential one). It has one call
site, at 0x4bc99, which only sets the reseed counter at startup from the clock.

## Differences from the original

- The original loads the table on the first draw, and stops the game with an error if the
  file is missing. In the port the caller fills `RngState::table` first, since the logic
  library does no file I/O. The test confirms the original's first-draw load reads exactly
  256 bytes into the table and doesn't change the result of that draw. A missing or short
  file is left to whoever writes the loader. The original doesn't check for a short file.
- The original's reseed leaves a meaningless value in EAX. The port returns nothing. Of the
  ten call sites, seven visibly don't use it. The other three (0x101ea, 0x11147, 0x100e4)
  run on towards a function exit or a jump, and weren't followed further.

## Rollback

`RngState` is a plain struct with no pointers or padding, so a snapshot is a copy and a
hash can use the raw bytes. The table never changes, so strictly it needn't be in a
snapshot. It stays in the struct so the struct stands alone and a state hash notices two
machines with different files. It costs 256 bytes per snapshot, which can be revisited.

## What the callers do (read, not yet ported)

These matter for rollback and are not confirmed in depth:

- **Likely shared with drawing.** 0x100c0 and 0x10668 set the counter to the frame number
  and reseed with a frame of 0 at both start and end, drawing 5 and 27 times in between.
  They look like effects or drawing code, and 0x5e2b0 has 27 calling functions, some not
  obviously simulation. If drawing does consume this generator, rollback must not re-run drawing on
  the simulated state, and fights could depend on what gets drawn. This needs checking when
  those functions are ported.
- **The hold flag** is set by the fight loop at several points, and 0x30608 sets it around a
  redraw (0x3396c, which itself reseeds). It looks like a way to redraw without disturbing
  the generator, possibly while paused. That purpose is inferred.
- **The fight loop reseeds with the frame number** at 0x31f65. 0x337d4 has the same pattern.
  Fight start sets the counter to the frame number (0x30e69).
