#!/usr/bin/env python3
"""Count convention damage in exported decompilation: usage: decomp_metrics.py <decomp dir> [<decomp dir> ...]"""
import glob
import os
import re
import sys

PATTERNS = {
    'extraout_': r'\bextraout_\w+',
    'in_<reg> (read of unmodelled register)': r'\bin_(?:E?[A-D]X|[A-D][LH]|E?[SD]I|EBP|BP)\b',
    'unaff_<reg>': r'\bunaff_\w+',
    'in_stack_': r'\bin_stack_\w+',
    'CONCAT44': r'\bCONCAT44\b',
    '__regparm': r'\b__regparm\d\b',
    '__cdecl': r'\b__cdecl\b',
    '__watcall': r'\b__watcall\d\b',
}


def measure(d):
    files = glob.glob(os.path.join(d, 'c', '*.c'))
    per = {k: [0, 0] for k in PATTERNS}
    suspicious = set()
    for p in files:
        src = open(p, encoding='utf-8').read()
        for k, pat in PATTERNS.items():
            n = len(re.findall(pat, src))
            per[k][0] += n
            per[k][1] += bool(n)
        if re.search(PATTERNS['extraout_'] + '|' + PATTERNS['in_<reg> (read of unmodelled register)'] + '|' + PATTERNS['unaff_<reg>'] + '|' + PATTERNS['in_stack_'], src):
            suspicious.add(os.path.basename(p))
    return len(files), per, suspicious


cols = [measure(d) for d in sys.argv[1:]]
print(f"{'metric':42}" + ''.join(f"{os.path.basename(os.path.dirname(d + '/'))[:18]:>22}" for d in sys.argv[1:]))
for k in PATTERNS:
    print(f'{k:42}' + ''.join(f'{c[1][k][0]:>12} in {c[1][k][1]:>5}' for c in cols))
print(f"{'functions with any of the first four':42}" + ''.join(f'{len(c[2]):>22}' for c in cols))
print(f"{'decompiled functions':42}" + ''.join(f'{c[0]:>22}' for c in cols))
