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

- `tools/le2elf.py` converts the game's DOS executable into an ELF image that
  Ghidra can load.
- `tools/ghidra/ExportDecomp.java` exports per-function decompilation and an
  index of calls, strings and hardware access.
- `tools/module_map.py` groups functions by the source file names embedded in
  the executable.
- `CLAUDE.md` records the project's decisions and design rules.

## License

MIT, for the code in this repository. It does not cover the original game or
its assets.
