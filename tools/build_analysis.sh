#!/bin/sh
# Build everything under analysis/ from the game file: ELF image, a new Ghidra project,
# runtime names, the Watcom convention, decompiled export, module map. Always starts
# clean, because the result depends on the project's history; this output is canonical.
# Deletes and recreates its output directories (ghidra, decomp, convention).
#
# usage: tools/build_analysis.sh
#   OMF_GAME      the MZ+LE program, default game-original/GAME/MASTER.DAT
#   OMF_ANALYSIS  output directory, default analysis
set -eu
cd "$(dirname "$0")/.."
GAME=${OMF_GAME:-game-original/GAME/MASTER.DAT}
OUT=${OMF_ANALYSIS:-analysis}
export JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}
GH=${GHIDRA_HEADLESS:-/opt/homebrew/Cellar/ghidra/12.1.4/libexec/support/analyzeHeadless}
WORK=$OUT/convention

test -f "$GAME" || { echo "no game file at $GAME" >&2; exit 1; }
rm -rf "$OUT/ghidra" "$OUT/decomp" "$WORK"
mkdir -p "$OUT/ghidra" "$OUT/decomp" "$WORK"

python3 tools/le2elf.py "$GAME" "$OUT/master.elf" --map "$OUT/master.map.json" > "$WORK/le2elf.log"
"$GH" "$OUT/ghidra" omf -import "$OUT/master.elf" > "$WORK/import.log" 2>&1

run() { "$GH" "$OUT/ghidra" omf -process master.elf -noanalysis -scriptPath tools/ghidra "$@"; }
run -postScript ApplyRtlNames.java tools/ghidra/rtl_names.tsv > "$WORK/names.log" 2>&1
run -readOnly -postScript DumpInsns.java "$WORK/insns.jsonl" > "$WORK/dump.log" 2>&1
python3 tools/verify_convention.py "$WORK/insns.jsonl" "$WORK/convention.json" "$WORK/models.tsv" > "$WORK/verify.txt"
run -postScript ApplyWatcom.java "$WORK/models.tsv" > "$WORK/apply.log" 2>&1
run -readOnly -postScript ExportDecomp.java "$OUT/decomp" > "$WORK/export.log" 2>&1
python3 tools/module_map.py "$OUT/decomp/index.jsonl" "$OUT/modules.json" > "$WORK/modules.txt"
grep -hE 'RTL_NAMES|RTL_NOCREATE|FALSE_FUNCTION|ASSIGNED|PARAM_PASS|CALLSITE_OVERRIDES|PARAMS_RESTORED|EXPORT|SCRIPT ERROR|COMMIT_FAILED' "$WORK"/*.log
