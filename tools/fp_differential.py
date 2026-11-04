#!/usr/bin/env python3
"""Run the game's Watcom float helpers in Unicorn on both paths and compare bits with host IEEE.

_real87 (0x825fd) selects x87 or integer-only soft float. The x87 path runs with the
control word the startup code loads (read from 0x82988). The host is the reference, so
on arm64 this is also a cross-architecture check. Unicorn's x87 is QEMU softfloat, not a
real 387; the soft path is plain integer code and does not depend on that.

usage: fp_differential.py <master.elf> [vectors per op]
"""
import math
import random
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, UC_PROT_ALL, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP)

ELF = open(sys.argv[1], 'rb').read()
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
REAL87, CW_ADDR = 0x825fd, 0x82988
RET, STACK = 0x1f0000, 0x1e0000
STUB = 0x1f1000


def sections():
    shoff = struct.unpack_from('<I', ELF, 32)[0]
    shent, shnum = struct.unpack_from('<HH', ELF, 46)
    for i in range(shnum):
        _, typ, _, addr, off, size = struct.unpack_from('<6I', ELF, shoff + i * shent)
        if addr and typ == 1:
            yield addr, ELF[off:off + size]


class Cpu:
    def __init__(self, x87, cw=None):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x10000, 0x1f0000, UC_PROT_ALL)
        self.uc.mem_map(0x200000, 0x10000, UC_PROT_ALL)
        for addr, data in sections():
            self.uc.mem_write(addr, data)
        self.uc.mem_write(REAL87, bytes([1 if x87 else 0]))
        if cw is not None:
            self.uc.mem_write(CW_ADDR, struct.pack('<H', cw))
        self.uc.mem_write(RET, b'\xf4')
        # FNINIT; FLDCW [CW_ADDR]; HLT
        self.uc.mem_write(STUB, b'\xdb\xe3\xd9\x2d' + struct.pack('<I', CW_ADDR) + b'\xf4')
        self.uc.emu_start(STUB, STUB + 8, count=5)

    def call(self, addr, eax=0, edx=0, ebx=0, ecx=0):
        uc = self.uc
        uc.reg_write(UC_X86_REG_ESP, STACK)
        uc.mem_write(STACK, struct.pack('<I', RET))
        for r, v in ((UC_X86_REG_EAX, eax), (UC_X86_REG_EDX, edx), (UC_X86_REG_EBX, ebx), (UC_X86_REG_ECX, ecx)):
            uc.reg_write(r, v & 0xffffffff)
        uc.emu_start(addr, RET, count=20000)
        return uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)


def d2w(x):
    v = struct.unpack('<Q', struct.pack('<d', x))[0]
    return v & 0xffffffff, v >> 32


def w2d(lo, hi):
    return struct.unpack('<d', struct.pack('<Q', (hi << 32) | lo))[0]


def f2w(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def w2f(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]


def fdbl(rng):
    """Values fight code plausibly holds, plus raw exponents across the normal range."""
    k = rng.random()
    if k < 0.4:
        return rng.randint(-3000, 3000) / rng.choice((1, 2, 4, 8, 10, 16, 100, 256))
    if k < 0.8:
        return rng.uniform(-1000, 1000)
    return rng.uniform(1, 2) * 2.0 ** rng.randint(-300, 300) * rng.choice((-1, 1))


def fflt(rng):
    k = rng.random()
    if k < 0.8:
        return w2f(f2w(rng.randint(-3000, 3000) / rng.choice((1, 2, 4, 8, 10, 16, 100, 256)) if k < 0.5
                       else rng.uniform(-1000, 1000)))
    return w2f(f2w(rng.uniform(1, 2) * 2.0 ** rng.randint(-60, 60) * rng.choice((-1, 1))))


def run_double(cpu, addr, op, rng):
    bad = []
    for _ in range(N):
        a, b = fdbl(rng), fdbl(rng)
        if op is div and b == 0:
            continue
        la, ha = d2w(a)
        lb, hb = d2w(b)
        lo, hi = cpu.call(addr, la, ha, lb, hb)
        want = d2w(op(a, b))
        if (lo, hi) != want:
            bad.append((a, b, w2d(lo, hi), w2d(*want)))
    return bad


def run_float(cpu, addr, op, rng):
    bad = []
    for _ in range(N):
        a, b = fflt(rng), fflt(rng)
        if op is div and b == 0:
            continue
        w = cpu.call(addr, f2w(a), f2w(b))[0]
        try:
            want = f2w(op(a, b))
        except OverflowError:
            continue
        if w != want:
            bad.append((a, b, w2f(w), w2f(want)))
    return bad


def run_conv(cpu, addr, gen, ref, rng):
    bad = []
    for _ in range(N):
        a = gen(rng)
        got, want = ref(cpu, addr, a)
        if got != want:
            bad.append((a, got, want))
    return bad


def div(a, b):
    return a / b


def add(a, b):
    return a + b


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b


s32 = lambda v: v - (1 << 32) if v >= 1 << 31 else v
DOUBLE_OPS = [('__FDA', 0x6ae22, add), ('__FDS', 0x6ae1c, sub), ('__FDM', 0x6afd9, mul), ('__FDD', 0x6c3c2, div)]
FLOAT_OPS = [('__FSA', 0x6b620, add), ('__FSS', 0x6b616, sub), ('__FSM', 0x6b6f1, mul), ('__FSD', 0x6b778, div)]


def conv_tests():
    i32 = lambda r: r.randint(-2 ** 31, 2 ** 31 - 1)
    u32 = lambda r: r.randint(0, 2 ** 32 - 1)
    small = lambda r: r.uniform(-30000, 30000)
    yield '__I4FD', 0x6addc, i32, lambda c, a, v: (c.call(a, v), d2w(float(v)))
    yield '__U4FD', 0x6ade9, u32, lambda c, a, v: (c.call(a, v), d2w(float(v)))
    yield '__I4FS', 0x6b605, i32, lambda c, a, v: (c.call(a, v)[0], f2w(float(v)))
    yield '__U4FS', 0x6b5da, u32, lambda c, a, v: (c.call(a, v)[0], f2w(float(v)))
    yield '__FDFS', 0x6b42c, small, lambda c, a, v: (c.call(a, *d2w(v))[0], f2w(v))
    yield '__FSFD', 0x6b478, small, lambda c, a, v: (c.call(a, f2w(v)), d2w(w2f(f2w(v))))
    yield '__FDI4', 0x6b4d6, small, lambda c, a, v: (s32(c.call(a, *d2w(v))[0]), int(v))
    yield '__FSI4', 0x6b878, small, lambda c, a, v: (s32(c.call(a, f2w(v))[0]), int(w2f(f2w(v))))


cw = struct.unpack('<H', next(d for a, d in sections() if a == 0x80000)[CW_ADDR - 0x80000:CW_ADDR - 0x80000 + 2])[0]
print(f'control word at {CW_ADDR:#x}: {cw:#06x}  precision={(cw >> 8) & 3} (2=53-bit) rounding={(cw >> 10) & 3} (0=nearest)')


def uses_fpu(x87, addr, a, b, eb=0, ec=0):
    """True if the call executes any x87 opcode (ESC 0xD8-0xDF), proving which path ran."""
    cpu = Cpu(x87)
    hits = []
    cpu.uc.hook_add(UC_HOOK_CODE, lambda uc, pc, size, _: hits.append(pc) if uc.mem_read(pc, 1)[0] in range(0xd8, 0xe0) else None)
    cpu.call(addr, a, b, eb, ec)
    return bool(hits)


la, ha, lb, hb = *d2w(1.1), *d2w(2.3)
print('path check, executes x87 opcodes? (x87 mode, soft mode)')
for name, addr, _ in DOUBLE_OPS:
    print(f'  {name}: {uses_fpu(True, addr, la, ha, lb, hb)}, {uses_fpu(False, addr, la, ha, lb, hb)}')
for name, addr, _ in FLOAT_OPS:
    print(f'  {name}: {uses_fpu(True, addr, f2w(1.1), f2w(2.3))}, {uses_fpu(False, addr, f2w(1.1), f2w(2.3))}')
print(f'{N} vectors per op; value compared bit-for-bit with host IEEE\n')
print(f"{'op':10}{'x87 path':>12}{'soft path':>12}   mismatches against host")
for name, addr, op, runner in [(n, a, o, run_double) for n, a, o in DOUBLE_OPS] + [(n, a, o, run_float) for n, a, o in FLOAT_OPS]:
    res = []
    for x87 in (True, False):
        res.append(runner(Cpu(x87), addr, op, random.Random(1234)))
    print(f'{name:10}{len(res[0]):>12}{len(res[1]):>12}')
    for label, bad in (('x87', res[0]), ('soft', res[1])):
        for b in bad[:2]:
            print('   ', label, b)
for name, addr, gen, ref in conv_tests():
    res = [run_conv(Cpu(x), addr, gen, ref, random.Random(99)) for x in (True, False)]
    print(f'{name:10}{len(res[0]):>12}{len(res[1]):>12}')
    for label, bad in (('x87', res[0]), ('soft', res[1])):
        for b in bad[:2]:
            print('   ', label, b)

# The same x87 path under FNINIT's default control word: 64-bit precision, nearest.
print('\nx87 path at control word 0x037f (FNINIT default, 64-bit precision) vs host IEEE')
for name, addr, op, runner in [(n, a, o, run_double) for n, a, o in DOUBLE_OPS] + [(n, a, o, run_float) for n, a, o in FLOAT_OPS]:
    bad = runner(Cpu(True, 0x037f), addr, op, random.Random(1234))
    print(f'{name:10}{len(bad):>12}', bad[:1])

print('\nsin/cos/sqrt: real code vs host libm, on game-style angles')
names = {}
for line in open('tools/ghidra/rtl_names.tsv'):
    p = line.split('\t')
    if p[1] in ('sin', 'cos', 'sqrt'):
        names[p[1]] = int(p[0], 16)
for fn, addr in names.items():
    rng = random.Random(7)
    cx, cs = Cpu(True), Cpu(False)
    vec = [rng.uniform(0, 6.2831853) for _ in range(min(N, 5000))]
    host = getattr(math, fn)
    xh = xs = hs = 0
    for v in vec:
        a = w2d(*cx.call(addr, *d2w(v)))
        b = w2d(*cs.call(addr, *d2w(v)))
        h = host(v)
        xh += a != h
        hs += b != h
        xs += a != b
    print(f'{fn:6} at {addr:#x}: x87!=host {xh}, soft!=host {hs}, x87!=soft {xs} of {len(vec)}')
