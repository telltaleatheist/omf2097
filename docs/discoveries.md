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

## Hitting things

From the hit test at 0x215c8 (details: `fight-loop.md`).

- **Hits are pixel-perfect, against the actual picture.** An attack is a set of points on the
  attacker's sprite, and it hits when a point lands on a pixel in the opponent's colours, in the
  picture composed for the frame.
- **Likely, player 2's body can get in the way of their own attacks.** Player 2 is normally drawn
  on top, so where the fighters overlap, player 2's points see their own pixels. Player 1 doesn't
  have this problem. How much this matters in a real fight hasn't been measured.
- **Likely, projectiles and particles can register as the fighter who owns them**, because the test
  only looks at colours.

## Game speed

From the fight loop at 0x30c08 (details: `fight-loop.md`).

- **Game speed is a simple wait.** The game runs one step per frame and then waits a set time, so
  speed changes how long each step takes on screen, not what happens in it. At speed 9 and up there's
  no wait at all, and the game runs as fast as the machine allows. Speeds 10-19 are all the same.
- **The fight's speed keys go to 19**, past the menu's limit of 10, but that adds nothing.
