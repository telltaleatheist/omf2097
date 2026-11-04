#!/usr/bin/env python3
"""Group exported functions into source modules using embedded *.cpp names.

A function naming a .cpp file anchors that module. Unanchored functions lying
between two anchors of the same module are attributed to it ('inferred'); all
others stay unassigned. Functions from RUNTIME_START up are the Watcom runtime
('address'). Attribution is a work-splitting aid, not proof.

usage: module_map.py <index.jsonl> <out.json>
"""
import json
import re
import sys

F = sorted((json.loads(l) for l in open(sys.argv[1])), key=lambda f: int(f['addr'], 16))
CPP = re.compile(r'^[a-z0-9_]+\.cpp$', re.I)
RUNTIME_START = 0x6addc  # __I4FD; see tools/ghidra/rtl_names.tsv

for f in F:
    names = {s.lower() for s in f['strings'] if CPP.match(s)}
    f['anchors'] = sorted(names)
    f['module'] = f['anchors'][0] if len(names) == 1 else None
    f['basis'] = 'anchor' if f['module'] else ('conflict' if names else None)
    if int(f['addr'], 16) >= RUNTIME_START and not f['module']:
        f['module'], f['basis'] = 'watcom_rtl', 'address'

last = None
for i, f in enumerate(F):
    if f['module']:
        if last is not None and F[last]['module'] == f['module']:
            for g in F[last + 1:i]:
                if g['basis'] is None:
                    g['module'], g['basis'] = f['module'], 'inferred'
        last = i
    elif f['basis'] == 'conflict':
        last = None

mods = {}
for f in F:
    if f['module']:
        m = mods.setdefault(f['module'], dict(funcs=0, anchored=0, bytes=0, lo=f['addr'], hi=f['addr'], members=[]))
        m['funcs'] += 1
        m['anchored'] += f['basis'] == 'anchor'
        m['bytes'] += f['size']
        m['hi'] = f['addr']
        m['members'].append(f['addr'])

un = [f for f in F if not f['module']]
json.dump(dict(modules=mods, unassigned=[f['addr'] for f in un],
               conflicts={f['addr']: f['anchors'] for f in F if f['basis'] == 'conflict'}),
          open(sys.argv[2], 'w'), indent=1)

total = sum(f['size'] for f in F)
for name, m in sorted(mods.items(), key=lambda kv: kv[1]['lo']):
    print(f"{name:18} {m['lo']}-{m['hi']} funcs={m['funcs']:3} anchored={m['anchored']:3} bytes={m['bytes']}")
print(f"assigned funcs={len(F) - len(un)}/{len(F)} bytes={total - sum(f['size'] for f in un)}/{total}")
print('conflicts:', {f['addr']: f['anchors'] for f in F if f['basis'] == 'conflict'})
big = sorted(un, key=lambda f: -f['size'])[:12]
print('largest unassigned:', [(f['addr'], f['size']) for f in big])
