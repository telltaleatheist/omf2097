# How One Must Fall 2097 really works

Findings from taking `MASTER.DAT` apart, written for players. Each one comes from the
game's own code; the address and the technical write-up are given so anyone can check.
"Likely" marks a guess.

## Randomness

From the generator at 0x5e2b0 (details: `rng.md`).

- **The game's random numbers come from a 256-byte file.** `RANDOM.DAT` holds each value
  from 0 to 255 exactly once, and the generator only ever mixes bytes from it. There's no
  clock involved in a draw, though the clock does set a starting counter once at 0x4bc84.
  Change the file and you change the numbers.
- **Left alone, the numbers repeat every 256 draws.** The read positions all come back to
  where they started after 256 draws. In practice the game keeps moving them, using the
  frame number.
- **Small rolls can't be perfectly even.** Any range up to 255 is cut from a single byte.
  A roll out of 100 gives some results 3 chances in 256 (1.17%) and others 2 in 256 (0.78%).
  A roll out of 3 is close to fair: 86, 85 and 85 chances.
- **The same frame can give the same numbers.** A reseed depends only on the frame number and
  a counter, so identical inputs on two machines produce identical randomness. Likely the
  reason the original's network play could work by sending only inputs.
