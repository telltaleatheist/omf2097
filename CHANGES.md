# Changes from the original

Every way this rebuild deliberately differs from the original game, in plain words.

- `RANDOM.DAT` will be read before the game needs it, rather than on the first random number.
  You'd see a missing file as an error at startup rather than at that first moment.
