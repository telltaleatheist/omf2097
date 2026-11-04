# omf

Rebuild of One Must Fall 2097 that plays like the original on modern systems,
with new internet play. Public, MIT: github.com/telltaleatheist/omf2097.

## Decisions (Owen, 2026-11-03)

- Play-identical, not byte-identical. No period compiler, no DOS emulation in
  the shipped game.
- Modern C++ and SDL3 on Windows, Linux and macOS.
- Rewrite logic freely where that is the sensible modern way. What must match
  is how it plays, not how the code was organised. No reproducing DOS-era
  techniques for their own sake.
- Online: rollback, 1v1 fights only, working like the local shared-keyboard
  2-player mode. Tournament stays offline.
- Bugs: fix crashes, hangs and desyncs. Keep balance quirks, exploits and odd
  move interactions. Anything in between goes to Owen. Every change from the
  original gets a plain-words line in CHANGES.md.

## Proposed, not yet confirmed by Owen

- Join by room code through a small rendezvous server, with NAT punching and a
  relay fallback.
- Assets are not bundled: the rebuild reads them from a copy of the original.
- DOSBox-X for recording reference fights (a test tool only).

## Determinism

Rollback needs the fight simulation to give bit-identical results on every
platform, x86-64 and arm64. So:

- All simulation state lives in copyable structures that can be snapshotted and
  hashed. No pointers into engine types, no state hidden in the renderer.
- No wall-clock time, no libm or other platform-dependent results in the
  simulation. Floats only if proven deterministic (`-ffp-contract=off`, no x87);
  otherwise fixed-point.
- Two different tolerances. Rebuilt vs original: compared against the original,
  with how close is close enough decided per system. Machine vs machine: exact.

## Reference: MW3

`/Volumes/Callisto/Projects/mw3-re` is Owen's finished rebuild of this kind.
Read it, don't edit it; other sessions work there. Worth reusing:

- Game logic as a plain C++ library with no engine types, and a thin SDL3 layer
  (CLAUDE.md there).
- Unicorn differential tests (`tests/differential/original.py`).
- Lead and worker sessions, one item at a time, each in its own git worktree;
  every piece arrives with a test, break tests showing the test catches errors,
  and a doc.
- `docs/fixes.md`, `CHANGES.md` and `docs/discoveries.md` for fixes, changes
  and player-facing finds.
- Vendored ENet in `third_party/` as a possible UDP transport.

Do not reuse its float tolerance for anything machine-to-machine.

## Layout

- `game-original/` the game, read-only, never committed or published. The real
  program is `GAME/MASTER.DAT` (MZ+LE, Watcom C/C++32). Launch chain, from
  strings only: OMF.EXE -> SETUP.EXE -> FILE0001.EXE -> MASTER.DAT.
- `tools/build_analysis.sh` rebuilds all of `analysis/` from the game file. It
  deletes and recreates its output; its clean output is the canonical one.
- `tools/le2elf.py` makes `analysis/master.elf`; object 1 at 0x10000, object 2
  at 0x80000, entry 0x6c5bc. Addresses in comments use this image.
- `src/logic/` the game logic: plain C++ with no SDL or engine types. `rng.cpp`
  is the pattern for ports, with `tests/differential/` running the original in
  Unicorn against it and break tests proving the comparison catches errors.
- `docs/` how things work, `docs/open-questions.md` what is unconfirmed,
  `docs/discoveries.md` player-facing finds.
- `analysis/ghidra/` the persistent Ghidra project (one writer at a time),
  `analysis/decomp/` per-function C and index, `analysis/modules.json` the
  module map (hints: many entries are inferred from address position).
- Ghidra headless: `JAVA_HOME=/opt/homebrew/opt/openjdk@21`,
  `/opt/homebrew/Cellar/ghidra/12.1.4/libexec/support/analyzeHeadless`.
- REA cannot open the LE directly; give it `analysis/master.elf`.

This repo is public. Game files, decompiled output and anything converted from
them are never committed (`.gitignore` covers the known ones; check what you
stage, and add files by name rather than `git add .`).
