# omf2097

A work-in-progress rebuild of the 1994 DOS fighting game One Must Fall 2097 in
modern C++ and SDL3, for Windows, Linux and macOS. The aim is a game that plays
like the original, quirks included, with new internet play for 1v1 fights.

**Status: early reverse engineering. There is nothing to play yet.**

This repository contains no game files. You will need your own copy of the
original game.

This project is not affiliated with the game's original authors or publisher.
For an established open-source reimplementation, see
[OpenOMF](https://github.com/omf2097/openomf).

## What's here so far

- `tools/build_analysis.sh` builds all the analysis output from your copy of the
  game in one command: ELF image, Ghidra project, runtime names, calling
  convention, decompiled export and module map. It always starts clean, so the
  same game file gives byte-identical output.
- `tools/le2elf.py` converts the game's DOS executable into an ELF image that
  Ghidra can load.
- `tools/ghidra/ExportDecomp.java` exports per-function decompilation and an
  index of calls, strings and hardware access.
- `tools/module_map.py` groups functions by the source file names embedded in
  the executable.
- `src/logic/` holds the ported game logic, as a plain C++ library. So far that's
  the random number generator (`docs/rng.md`) and the exact sprite compositor
  (`docs/formats.md`). `src/assets/` reads the game's files.
- `compose_frame`, built with the rest, draws an arena and fighter frame to a PNG.
- `tests/` has unit tests, plus differential tests that run the original code in
  an emulator against the port. Those need your copy of the game, a built
  analysis, and `python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt`.
  Without them they report as skipped. Build and run with
  `cmake -S . -B build && cmake --build build && ctest --test-dir build`.
- `docs/discoveries.md` collects what the code reveals about how the game works.
- `CLAUDE.md` records the project's decisions and design rules.

## License

MIT, for the code in this repository. It does not cover the original game or
its assets.
