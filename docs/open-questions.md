# Open questions

Everything here is **unconfirmed**: seen in passing, not traced to the end. Addresses are
in `analysis/master.elf`.

## Timing and frame pacing

Likely the next piece of work.

- The timer interrupt handler at 0x38228 increments a 16-bit counter at 0x87268. The timer
  reload is 0xffff divided by the 16-bit value at 0x81de0. That value is 8 in the image and
  no direct write to it was found, which calculates to about 145.7 Hz. This hasn't been
  measured.
- 0x55b60 turns that counter into hundredths of a second, or uses INT 1Ah if the handler
  isn't installed (0x8bb58 is 0).
- **The wait that paces frames hasn't been found.** Readers of 0x87268 to look at first:
  0x5f0c4, 0x5f380, 0x5f670, 0x5e500, 0x5e588, 0x3d850, 0x514f0, 0x11870. 0x2d428 and
  0x65820 write it.
- The game speed at 0x8e4e8 is limited to 0-19 by keys in the fight loop, and is copied
  to the high half of 0x8bb72 (so 0x8bb74). The fight loop tests whether that copy is below
  10 in two places, which may be part of pacing. How speed maps to a frame rate isn't known.
- 0x337d4 looks like a second fight-style loop: same reseed and sync-check pattern, the
  same frame counter. It has no direct callers. What it's for isn't known.

## Possible bugs

To log for a decision, not fix. None confirmed.

- Reads of registers that may be uninitialised on some path: 0x26854 (ESI), 0x1aae0 (DI),
  0x2f588 (EBP), 0x355e0 and 0x3d798 (ESI), 0x3eecc (SI). These could be paths that never
  happen.
- The timer counter resets to 0 once it passes 0x7d00, about 220 seconds at the calculated
  rate. Durations measured with 0x55b60 across a reset may come out wrong.

## Quirks to keep

Measured by `tools/fp_differential.py`, on one host, with x87 under emulation.

- Int to float conversion truncates rather than rounds, which shows from 2^24 up. 0 * x
  and 0 / x for floats give +0, never -0.
