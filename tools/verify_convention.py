#!/usr/bin/env python3
"""Measure the calling convention from instruction dumps (tools/ghidra/DumpInsns.java)
and classify each function into a prototype model for tools/ghidra/ApplyWatcom.java.

A path-sensitive walker tracks which registers still hold their entry value and
what is on the stack. It yields, per function: registers read before written,
registers not restored at RET, stack arguments read and RET cleanup. Callee
effects feed back to a fixed point.

usage: verify_convention.py <insns.jsonl> <out.json> <models.tsv>
"""
import collections
import json
import re
import sys

ARG = ['EAX', 'EDX', 'EBX', 'ECX']
GPR = ARG + ['ESI', 'EDI', 'EBP']
FAM = {}
for full, parts in dict(EAX='AL AH AX', EBX='BL BH BX', ECX='CL CH CX', EDX='DL DH DX', ESI='SI', EDI='DI', EBP='BP').items():
    FAM[full] = full
    for p in parts.split():
        FAM[p] = full
# Registers INT services may hand back, which Ghidra's p-code does not model as written.
# They count as defined for reads, but not as clobbered: DOS and DPMI preserve most of them.
INT_WRITES = {'EAX', 'EBX', 'ECX', 'EDX', 'ESI', 'EDI'}
PATH_LIMIT = 60000


def fam(rs):
    return {FAM[r] for r in rs if r in FAM}


I = {}
for line in open(sys.argv[1]):
    d = json.loads(line)
    d['a'] = int(d['a'], 16)
    d['to'] = [int(x, 16) for x in d['to']]
    d['rd'], d['wr'] = fam(d['in']), fam(d['out'])
    p = d['t'].split(None, 1)
    d['m'], d['ops'] = p[0], p[1] if len(p) > 1 else ''
    ops = d['ops'].split(',')
    if d['m'] in ('XOR', 'SUB') and len(ops) == 2 and ops[0] == ops[1] and ops[0] in FAM:
        d['rd'] = d['rd'] - {FAM[ops[0]]}
    I[d['a']] = d
A = sorted(I)
idx = {a: i for i, a in enumerate(A)}
NEXT = {a: a + I[a]['n'] for a in A}
FUNCS = sorted(a for a in A if I[a]['f'] is not None and int(I[a]['f'], 16) == a)
FSET = set(FUNCS)


# DOS terminate: MOV AH,0x4c shortly before INT 0x21 ends the path.
for a in A:
    d = I[a]
    d['exit'] = d['t'] == 'INT 0x21' and any(I[A[j]]['t'].startswith('MOV AH,0x4c') for j in range(max(0, idx[a] - 4), idx[a]))


def is_call(d):
    return d['m'] == 'CALL'


def succs(d):
    if d['exit']:
        return []
    out = [NEXT[d['a']]] if d['fall'] else []
    if not is_call(d):
        out += d['to']
    return [x for x in out if x in I]


LIVE = collections.defaultdict(set)
CLOB = collections.defaultdict(set)
PURGE = collections.defaultdict(int)
BODY, POPS = {}, {}
for f in FUNCS:
    seen, todo = set(), [f]
    while todo:
        a = todo.pop()
        if a not in seen and a in I:
            seen.add(a)
            todo += succs(I[a])
    BODY[f] = seen
    POPS[f] = {FAM[I[a]['ops']] for a in seen if I[a]['m'] == 'POP' and I[a]['ops'] in FAM}

# A function returns if a RET, a computed jump or a returning tail target is reachable
# without crossing a call to a function already known not to return (greatest fixed point).
NORETURN = set(FUNCS)


def returns(f):
    seen, todo = set(), [f]
    while todo:
        a = todo.pop()
        if a in seen or a not in I:
            continue
        seen.add(a)
        d = I[a]
        if d['m'] == 'RET' or (d['m'] == 'JMP' and not d['to']):
            return True
        if is_call(d):
            if not (d['to'] and d['to'][0] in NORETURN):
                todo.append(NEXT[a])
            continue
        if d['flow'] == 'UNCONDITIONAL_JUMP' and d['to'] and d['to'][0] in FSET and d['to'][0] != f:
            if d['to'][0] not in NORETURN:
                return True
            continue
        todo += succs(d)
    return False


while True:
    back = {f for f in NORETURN if returns(f)}
    if not back:
        break
    NORETURN -= back

ESP_REF = re.compile(r'\[ESP(?: \+ (0x[0-9a-f]+))?\]')
EBP_REF = re.compile(r'\[EBP \+ (0x[0-9a-f]+)\]')


def walk(f):
    """One abstract pass: returns live-in regs, clobbered regs, stack arg bytes, RET purges."""
    live, clob, rets = set(), set(), set()
    stack_args = 0
    frame_lost = False
    start = (f, frozenset(), tuple(), None)  # addr, regs no longer original, stack tags, EBP depth
    seen, todo = set(), [start]
    defined0 = frozenset()
    todo = [(f, frozenset(), frozenset(), tuple(), None)]
    while todo and len(seen) < PATH_LIMIT:
        a, defined, changed, st, bp = todo.pop()
        key = (a, defined, changed, st, bp)
        if key in seen or a not in I:
            continue
        seen.add(key)
        d = I[a]
        m, ops = d['m'], d['ops']
        reads = set(d['rd'])
        defined2, changed2, st2, bp2 = set(defined), set(changed), list(st), bp
        if m == 'PUSH' and ops in FAM and FAM[ops] in POPS[f]:
            reads.clear()
        call_targets = d['to'] if is_call(d) else []
        for t in call_targets:
            reads |= LIVE[t]
        if reads - defined and f in FIRST_READ_WATCH:
            for r in reads - defined:
                FIRST_READ.setdefault((f, r), a)
        live |= reads - defined
        # stack argument references
        for o in ESP_REF.findall(d['t']):
            off = int(o, 16) if o else 0
            depth = len(st2) * 4
            if off >= depth + 4:
                stack_args = max(stack_args, off - depth - 4 + 4)
        if bp is not None:
            for o in EBP_REF.findall(d['t']):
                off = int(o, 16) - (len(st2) - len(st2) + 0)
                if off >= 8:
                    stack_args = max(stack_args, off - 8 + 4)
        if m == 'PUSH':
            tag = FAM[ops] if ops in FAM and FAM[ops] not in changed else None
            st2.append(tag)
        elif m == 'POP':
            tag = st2.pop() if st2 else None
            if ops in FAM:
                r = FAM[ops]
                defined2.add(r)
                if tag == r:
                    changed2.discard(r)
                else:
                    changed2.add(r)
        elif m == 'SUB' and ops.startswith('ESP,0x'):
            st2 += [None] * (int(ops[4:], 16) // 4)
        elif m == 'ADD' and ops.startswith('ESP,0x'):
            del st2[len(st2) - min(len(st2), int(ops[4:], 16) // 4):]
        elif m == 'MOV' and ops == 'EBP,ESP':
            bp2 = len(st2)
        elif m == 'MOV' and ops == 'ESP,EBP' and bp is not None:
            del st2[bp:]
        if m == 'INT':
            defined2 |= INT_WRITES
        if m != 'POP':
            for r in d['wr']:
                defined2.add(r)
                changed2.add(r)
        if is_call(d):
            defined2.add('EAX')
            changed2.add('EAX')
            for t in call_targets:
                changed2 |= CLOB[t]
                n = PURGE[t] // 4
                if n:
                    del st2[len(st2) - min(len(st2), n):]
            if not call_targets:
                changed2.add('EAX')
        if is_call(d) and call_targets and call_targets[0] in NORETURN:
            continue
        if m == 'RET':
            clob |= changed2
            rets.add(int(ops, 16) if ops else 0)
            continue
        if m == 'JMP' and not d['to']:
            continue
        # A tail jump to another function behaves like call + ret.
        jump_out = [t for t in d['to'] if t in FSET and t != f and not is_call(d)] if d['flow'] == 'UNCONDITIONAL_JUMP' else []
        if jump_out:
            for t in jump_out:
                live |= LIVE[t] - defined2
                clob |= changed2 | CLOB[t]
                rets.add(PURGE[t])
            continue
        for s in succs(d):
            todo.append((s, frozenset(defined2), frozenset(changed2), tuple(st2), bp2))
    return live, clob, stack_args, rets, len(seen) >= PATH_LIMIT


FIRST_READ_WATCH = set(FUNCS)
FIRST_READ = {}
RESULT = {}
for it in range(10):
    changed = False
    for f in FUNCS:
        r = walk(f)
        if not (LIVE[f] == r[0] and CLOB[f] == r[1] and PURGE[f] == max(r[3] or {0})):
            changed = True
        LIVE[f], CLOB[f], PURGE[f] = set(r[0]), set(r[1]), max(r[3] or {0})
        RESULT[f] = r
    if it == 0:
        DIRECT = {f: set(RESULT[f][0]) for f in FUNCS}
    if not changed:
        break
print(f'fixed point after {it + 1} passes')

# call-site evidence
CALLS, CLEAN = collections.Counter(), collections.Counter()
SETUP = collections.defaultdict(collections.Counter)
KIND = collections.Counter()
BAD = collections.Counter()
INDIRECT = {}
POPPED = {}
for f in FUNCS:
    for a in BODY[f]:
        d = I[a]
        if not is_call(d):
            continue
        i, s = idx[a] - 1, set()
        while i >= 0 and idx[a] - i <= 10:
            p = I[A[i]]
            if p['m'] == 'CALL' or p['flow'] != 'FALL_THROUGH':
                break
            s |= p['wr']
            i -= 1
        if not d['to']:
            INDIRECT[a] = max([ARG.index(r) + 1 for r in s if r in ARG] or [0])
            continue
        t = d['to'][0]
        CALLS[t] += 1
        q = NEXT[a]
        for _ in range(4):  # Watcom may delay the stack cleanup a few instructions
            n = I.get(q)
            if not n or n['m'] in ('CALL', 'PUSH', 'POP') or n['flow'] != 'FALL_THROUGH':
                break
            if n['t'].startswith('ADD ESP,0x'):
                CLEAN[t] += 1
                POPPED[a] = (t, int(n['ops'][4:], 16) // 4)
                break
            q = NEXT[q]
        for r in ARG:
            if r in s:
                SETUP[t][r] += 1
        q, wr = NEXT[a], {'EAX'}
        for _ in range(12):
            n = I.get(q)
            if not n:
                break
            for r in n['rd'] - wr:
                if r in GPR[1:]:
                    kept = r not in CLOB[t]
                    KIND[(r, 'callee keeps' if kept else 'callee clobbers')] += 1
                    if not kept:
                        BAD[(t, r)] += 1
            wr |= n['wr']
            if n['flow'] != 'FALL_THROUGH' or n['m'] == 'CALL':
                break
            q = NEXT[q]


RUNTIME_START = 0x6addc
DOUBLE_RET = collections.Counter({t: n for (t, r), n in BAD.items() if r == 'EDX'})


def claimed_regs(f):
    # A transitive read counts only if call sites really set the register up: a read
    # reached through a callee is often an infeasible path, not an argument.
    claimed = set(DIRECT[f]) & set(ARG)
    for r in (LIVE[f] & set(ARG)) - claimed:
        if not CALLS[f] or SETUP[f][r] * 2 >= CALLS[f]:
            claimed.add(r)
    return claimed


def classify(f):
    live, clob = LIVE[f] & set(ARG), CLOB[f] & set(ARG)
    args = RESULT[f][2]
    if not live and args:
        if PURGE[f]:
            return 'stdstack'
        if CALLS[f] and CLEAN[f] * 2 >= CALLS[f] and not (clob - {'EAX'}):
            return 'cdeclkeep'
    if f < RUNTIME_START and DOUBLE_RET[f] >= 1 and 'EDX' in CLOB[f]:
        return 'dbl'
    rank = 1
    for r in claimed_regs(f) | (clob - {'EAX'}):
        rank = max(rank, ARG.index(r) + 1)
    return f'a{rank}'


MODEL = {f: classify(f) for f in FUNCS}

print(f'functions analysed: {len(FUNCS)}; path limit hit: {sum(RESULT[f][4] for f in FUNCS)}')
hist = collections.Counter(tuple(r for r in ARG if r in DIRECT[f]) for f in FUNCS)
print('\n== read before written by the function itself, ignoring callees ==')
for k, v in hist.most_common():
    print(f'{v:5}  {"+".join(k) or "(none)"}')
print('\n== registers not restored at RET (all paths, including via callees) ==')
for r in GPR:
    print(f'{r}: {sum(r in CLOB[f] for f in FUNCS)}')
print('\n== non-argument registers live on entry (non-standard) ==')
odd = [f for f in FUNCS if DIRECT[f] & {'ESI', 'EDI', 'EBP'}]
print(len(odd))
for f in odd:
    print(f'  {f:05x}', [(r, f'{FIRST_READ[(f, r)]:05x}', I[FIRST_READ[(f, r)]]['t'][:30]) for r in sorted(DIRECT[f] & {'ESI', 'EDI', 'EBP'})])
print('\n== reads of a register after a call, before redefinition ==')
for k, v in sorted(KIND.items()):
    print(k, v)
print('by callee for clobbering callees:', [(f'{t:05x}', r, n) for (t, r), n in BAD.most_common(30)])
print('\n== RET cleanup vs stack arguments read ==')
c = collections.Counter()
for f in FUNCS:
    c[('RET n' if PURGE[f] else 'RET', 'reads stack args' if RESULT[f][2] else 'no stack args')] += 1
for k, v in sorted(c.items()):
    print(k, v)
print('\n== model assignment ==')
print(collections.Counter(MODEL.values()).most_common())
print('noreturn:', [f'{f:05x}' for f in sorted(NORETURN)])
print('EDX:EAX returning game functions:', [f'{f:05x}' for f in FUNCS if MODEL[f] == 'dbl'])
print('stack-only callee-pop:', [f'{f:05x}' for f in FUNCS if MODEL[f] == 'stdstack'])
print('stack-only caller-pop:', [f'{f:05x}' for f in FUNCS if MODEL[f] == 'cdeclkeep'])
print('indirect call sites:', len(INDIRECT))

json.dump({f'{f:08x}': dict(live=sorted(LIVE[f]), direct=sorted(DIRECT[f]), clobbers=sorted(CLOB[f]),
                            purge=PURGE[f], stack_args=RESULT[f][2], calls=CALLS[f], caller_clean=CLEAN[f],
                            setup=dict(SETUP[f]), model=MODEL[f], noreturn=f in NORETURN)
           for f in FUNCS}, open(sys.argv[2], 'w'), indent=0)
with open(sys.argv[3], 'w') as out:
    for f in FUNCS:
        out.write(f'F\t{f:08x}\t{MODEL[f]}\t{PURGE[f]}\t{int(f in NORETURN)}\t{max([ARG.index(r) + 1 for r in claimed_regs(f)] or [0])}\n')
    for a, k in sorted(INDIRECT.items()):
        out.write(f'I\t{a:08x}\ta{max(k, 1)}\t{k}\n')
    # Stack-only caller-pop calls: the ADD ESP after the call gives the argument count.
    for a, (t, k) in sorted(POPPED.items()):
        if MODEL.get(t) == 'cdeclkeep':
            out.write(f'V\t{a:08x}\t{t:08x}\t{k}\n')
