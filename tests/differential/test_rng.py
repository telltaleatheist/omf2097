#!/usr/bin/env python3
"""Runs the original RNG in Unicorn against the C++ and compares output and all state.

usage: test_rng.py --probe <probe_rng> --elf <master.elf> --random-dat <RANDOM.DAT> [--ops N] [--quiet]
"""
import argparse
import os
import random
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NEXT_ADDR, RESEED_ADDR = 0x5e2b0, 0x5e45c
OPEN_ADDR, READ_ADDR, CLOSE_ADDR = 0x6ba67, 0x6bd39, 0x6be9a
TABLE, LOADED, INDEX, COUNTER, FLAGS = 0x90f14, 0x90f10, 0x91014, 0x84388, 0x8bb72
HOLD_MASK = 0x02
PROGRESS_FIELDS = ('value', 'index0', 'index1', 'index2', 'index3', 'counter')


def skip(why):
    print(f'SKIP: {why}')
    sys.exit(77)


def plan(rng, ops):
    """A long operation list: the game's pattern, plus edge ranges and state jumps."""
    edge = [0, 1, 2, 3, 0xff, 0x100, 0x101, 0xffff, 0x10000, 0x10001, 0x7fffffff, -1, -2, -0x100, -0x80000000, 0x2711]
    out = []
    frame = rng.randrange(0x10000)
    while len(out) < ops:
        kind = rng.random()
        if kind < 0.01:
            out.append(('set', rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256),
                        rng.choice((0, 1, 0xffffffff, 0xfffffffe, rng.randrange(1 << 32)))))
        elif kind < 0.25:
            frame = (frame + 1) & 0xffffffff
            out.append(('reseed', frame if rng.random() < 0.9 else rng.randrange(1 << 32), rng.random() < 0.3))
        elif kind < 0.5:
            out.append(('next', rng.randrange(0, 0x100)))
        elif kind < 0.75:
            out.append(('next', rng.randrange(0x100, 0x10000)))
        elif kind < 0.95:
            out.append(('next', rng.randrange(0x10000, 1 << 31)))
        elif kind < 0.98:
            out.append(('next', rng.choice(edge)))
        else:
            out.append(('next', rng.randrange(-(1 << 31), 0)))
    return out


def run_probe(probe, random_dat, ops):
    lines = [f'load {random_dat}']
    for op in ops:
        if op[0] == 'set':
            lines.append('set ' + ' '.join(str(x) for x in op[1:]))
        elif op[0] == 'next':
            lines.append(f'next {op[1]}')
        else:
            lines.append(f'reseed {op[1]} {int(op[2])}')
    lines.append('table')
    done = subprocess.run([probe], input='\n'.join(lines) + '\n', capture_output=True, text=True)
    if done.returncode:
        sys.exit(f'probe failed with {done.returncode}')
    return done.stdout.splitlines()


def state_of(orig):
    return list(orig.read(INDEX, 4)) + [orig.u32(COUNTER)]


def compare(orig, ops, probe_lines, table):
    """Returns the first difference as text, or None, and what the run covered."""
    covered = dict.fromkeys(('small', 'mid', 'large', 'negative', 'reseed', 'hold', 'index wrap', 'counter wrap'), 0)
    for number, op in enumerate(ops):
        got = [int(x) for x in probe_lines[number].split()]
        before = state_of(orig)
        if op[0] == 'set':
            orig.write(INDEX, op[1:5])
            orig.write(COUNTER, struct.pack('<I', op[5]))
            continue
        if op[0] == 'next':
            value = orig.call(NEXT_ADDR, eax=op[1])
            want = [value] + state_of(orig)
            fields = PROGRESS_FIELDS
            r = op[1]
            covered['negative' if r < 0 else 'small' if r <= 0xff else 'mid' if r <= 0xffff else 'large'] += 1
            covered['index wrap'] += any(a < b for a, b in zip(want[1:4], before[:3]))
        else:
            flags = orig.read(FLAGS, 1)[0]
            orig.write(FLAGS, [flags | HOLD_MASK if op[2] else flags & ~HOLD_MASK & 0xff])
            orig.call(RESEED_ADDR, eax=op[1])
            want = state_of(orig)
            fields = PROGRESS_FIELDS[1:]
            covered['hold' if op[2] else 'reseed'] += 1
            covered['counter wrap'] += want[4] < before[4]
        if got != want:
            names = [f for f, a, b in zip(fields, want, got) if a != b]
            return f'op {number} {op}: differs in {names}: original {want}, port {got}', covered
    if orig.read(TABLE, 256) != table or bytes.fromhex(probe_lines[len(ops)]) != table:
        return 'table changed', covered
    return None, covered


def stub_file_calls(orig, table):
    """The first draw loads RANDOM.DAT through open, read and close. Stands in for those."""
    from unicorn import UC_HOOK_CODE
    orig.write(OPEN_ADDR, b'\xb8\x05\x00\x00\x00\xc3')  # mov eax,5; ret
    orig.write(READ_ADDR, b'\x89\xd8\xc3')  # mov eax,ebx; ret
    orig.write(CLOSE_ADDR, b'\x31\xc0\xc3')  # xor eax,eax; ret
    seen = []

    def on_read(uc, _addr, _size, _data):
        from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDX
        dest, count = uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_EBX)
        seen.append((dest, count))
        uc.mem_write(dest, table[:count])

    orig.uc.hook_add(UC_HOOK_CODE, on_read, begin=READ_ADDR, end=READ_ADDR)
    return seen


def check_load_path(elf, table):
    from original import Original
    orig = Original(elf)
    assert orig.read(LOADED, 1) == b'\0' and orig.read(TABLE, 256) == bytes(256)
    seen = stub_file_calls(orig, table)
    value = orig.call(NEXT_ADDR, eax=1000)
    loaded = Original(elf)
    loaded.write(TABLE, table)
    loaded.write(LOADED, b'\1')
    same = loaded.call(NEXT_ADDR, eax=1000)
    return (seen == [(TABLE, 256)] and orig.read(TABLE, 256) == table and orig.read(LOADED, 1) == b'\1'
            and value == same and state_of(orig) == state_of(loaded))


def run(probe, elf, random_dat, ops_count, seeds=(1, 2, 3), quiet=False):
    """Returns the first difference as text, or None."""
    from original import Original
    table = open(random_dat, 'rb').read()
    if len(table) != 256:
        sys.exit(f'{random_dat}: expected 256 bytes, got {len(table)}')
    if not check_load_path(elf, table):
        return 'first-draw load of the table differs from what the port assumes'
    start = Original(elf)
    # The port's zero-initialised state must be what the program starts with.
    if state_of(start) != [0, 0, 0, 0, 0]:
        return f'image starts with non-zero state {state_of(start)}'
    totals = {}
    for seed in seeds:
        rng = random.Random(seed)
        ops = plan(rng, ops_count)
        orig = Original(elf)
        orig.write(TABLE, table)
        orig.write(LOADED, b'\1')
        probe_lines = run_probe(probe, random_dat, ops)
        # 'set' prints nothing, so line up the probe's lines with the printing ops.
        lines = iter(probe_lines)
        aligned = [next(lines) if op[0] != 'set' else '' for op in ops]
        aligned.append(next(lines))
        problem, covered = compare(orig, ops, aligned, table)
        for key, count in covered.items():
            totals[key] = totals.get(key, 0) + count
        if problem:
            return f'seed {seed}: {problem}'
    empty = [k for k, v in totals.items() if not v]
    if empty:
        return f'the run never covered: {empty}'
    if not quiet:
        print(f'{len(seeds)} sequences of {ops_count} operations match; first-draw load path matches; covered: {totals}')
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--random-dat', required=True)
    ap.add_argument('--ops', type=int, default=200000)
    args = ap.parse_args()
    for label, path in (('master.elf (tools/build_analysis.sh)', args.elf), ('RANDOM.DAT from the game', args.random_dat)):
        if not os.path.exists(path):
            skip(f'{label} not found at {path}')
    try:
        import unicorn  # noqa: F401
    except ImportError:
        skip('unicorn is not installed: .venv/bin/pip install -r tests/requirements.txt')
    problem = run(args.probe, args.elf, args.random_dat, args.ops)
    if problem:
        print('FAIL:', problem)
        sys.exit(1)


if __name__ == '__main__':
    main()
