#!/bin/sh
# Re-apply the runtime names and the Watcom convention to the Ghidra project, then re-export.
# Idempotent. usage: tools/ghidra/apply_convention.sh [work dir, default analysis/convention]
set -e
cd "$(dirname "$0")/../.."
WORK=${1:-analysis/convention}
export JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}
GH=/opt/homebrew/Cellar/ghidra/12.1.4/libexec/support/analyzeHeadless
mkdir -p "$WORK"
run() { "$GH" analysis/ghidra omf -process master.elf -noanalysis -scriptPath tools/ghidra "$@"; }
run -postScript ApplyRtlNames.java tools/ghidra/rtl_names.tsv > "$WORK/names.log" 2>&1
run -readOnly -postScript DumpInsns.java "$WORK/insns.jsonl" > "$WORK/dump.log" 2>&1
python3 tools/verify_convention.py "$WORK/insns.jsonl" "$WORK/convention.json" "$WORK/models.tsv" > "$WORK/verify.txt"
run -postScript ApplyWatcom.java "$WORK/models.tsv" > "$WORK/apply.log" 2>&1
rm -rf analysis/decomp/c analysis/decomp/index.jsonl
mkdir -p analysis/decomp
run -readOnly -postScript ExportDecomp.java analysis/decomp > "$WORK/export.log" 2>&1
python3 tools/module_map.py analysis/decomp/index.jsonl analysis/modules.json > "$WORK/modules.txt"
grep -hE 'RTL_NAMES|RTL_SKIP|RTL_NOCREATE|FALSE_FUNCTION|ASSIGNED|PARAM_PASS|CALLSITE_OVERRIDES|PARAMS_RESTORED|EXPORT|SCRIPT ERROR|COMMIT_FAILED' "$WORK"/*.log
