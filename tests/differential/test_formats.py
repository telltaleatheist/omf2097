#!/usr/bin/env python3
"""Checks the loaders against the original's own animation loader running in Unicorn.

For every animation in every .AF and .BK file, runs 0x21090 with file calls stubbed, and
compares each sprite it builds, and where it stops reading, with tests/differential/omf_files.py.
Then compares that reader with the C++ loader, through tests/probe_compositor.

usage: test_formats.py --probe <probe_compositor> --elf <master.elf> --game <game dir>
"""
import argparse
import glob
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOAD_ANIMATION = 0x21090
READ, ALLOC, FREE, GROW = 0x6bd39, 0x6a354, 0x6bf16, 0x57220
SHARED_POINTERS, COLOUR_SHIFT, SHARING = 0x8bc78, 0x8c078, 0x8c07a
HEAP = 0x400000
EXPECTED = {'.BK': 19, '.AF': 11}


def skip(why):
    print(f'SKIP: {why}')
    sys.exit(77)


def fnv(data):
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xffffffff
    return h


class Loader:
    def __init__(self, elf):
        from original import Original
        from unicorn import UC_HOOK_CODE, UC_PROT_ALL
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX
        self.o = Original(elf)
        self.uc = self.o.uc
        self.uc.mem_map(HEAP, 0x1000000, UC_PROT_ALL)
        self.d = b''
        self.at = 0
        self.next = HEAP
        self.regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX)
        for addr in (READ, ALLOC, FREE, GROW):
            self.o.write(addr, b'\xc3')
        self.uc.hook_add(UC_HOOK_CODE, self._read, begin=READ, end=READ)
        self.uc.hook_add(UC_HOOK_CODE, self._alloc, begin=ALLOC, end=ALLOC)
        self.o.write(0x8e614, struct.pack('<I', 0))
        self.o.write(0x8e494, b'\0\0\xff\xff')

    def _read(self, uc, *_):
        eax, ebx, edx = (uc.reg_read(r) for r in self.regs)
        data = self.d[self.at:self.at + ebx]
        uc.mem_write(edx, data)
        self.at += len(data)
        uc.reg_write(self.regs[0], len(data))

    def _alloc(self, uc, *_):
        size = uc.reg_read(self.regs[0])
        self.next = (self.next + 15) & ~15
        uc.reg_write(self.regs[0], self.next)
        self.next += max(size, 1)

    def start_file(self):
        self.next = HEAP + 0x1000
        self.o.write(SHARED_POINTERS, bytes(0x400))

    def run(self, d, at, shift, sharing):
        self.d = d
        self.at = at
        self.o.write(COLOUR_SHIFT, struct.pack('<H', shift))
        self.o.write(SHARING, bytes([1 if sharing else 0]))
        self.o.write(HEAP, bytes(0x400))
        self.o.call(LOAD_ANIMATION, eax=HEAP, edx=5, ebx=0, ecx=0)
        count = self.o.read(HEAP + 10, 1)[0]
        out = []
        for i in range(count):
            r = self.o.read(HEAP + 0xc + i * 16, 16)
            ptr, length, x, y, w, h, index, missing = struct.unpack('<IHhhHHBB', r)
            data = self.o.read(ptr, length) if ptr else None
            out.append((length, x, y, w, h, index, missing, data))
        return out, self.at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--all-shifts', action='store_true')
    ap.add_argument('--shift-moves', type=int, default=3)
    args = ap.parse_args()
    if not os.path.exists(args.elf):
        skip(f'master.elf (tools/build_analysis.sh) not found at {args.elf}')
    if not os.path.isdir(args.game):
        skip(f'the game was not found at {args.game}')
    try:
        import unicorn  # noqa: F401
    except ImportError:
        skip('unicorn is not installed: .venv/bin/pip install -r tests/requirements.txt')
    import omf_files

    bks = sorted(glob.glob(os.path.join(args.game, '*.BK')))
    afs = sorted(glob.glob(os.path.join(args.game, '*.AF')))
    if len(bks) != EXPECTED['.BK'] or len(afs) != EXPECTED['.AF']:
        print(f'FAIL: expected 19 .BK and 11 .AF files, found {len(bks)} and {len(afs)}')
        return 1
    loader = Loader(args.elf)
    animations = sprites = bad = 0
    for path in afs:
        for shift in (0, 0x30):
            af = omf_files.Af(path, shift)
            loader.start_file()
            d = af.bytes
            for number, (move, start, parsed) in enumerate(af.moves):
                # The original's colour shift is very slow under emulation. Unless asked, check it
                # on the first moves of each file.
                if shift and not args.all_shifts and number >= args.shift_moves:
                    break
                got, stopped = loader.run(d, start, shift, move not in (12, 13, 14))
                animations += 1
                for s, g in zip(parsed, got):
                    sprites += 1
                    same = (s.length, s.x, s.y, s.width, s.height, s.index, s.missing) == g[:7]
                    data_same = g[7] is None and s.data is None or (s.data is not None and g[7] == s.data[:s.length])
                    if not (same and data_same):
                        bad += 1
                        print(f'{os.path.basename(path)} shift {shift} move {move}: sprite differs: '
                              f'{(s.length, s.x, s.y, s.width, s.height, s.index, s.missing)} vs {g[:7]}, data same {data_same}')
                        if bad > 10:
                            return 1
                if len(parsed) != len(got):
                    bad += 1
                    print(f'{os.path.basename(path)} move {move}: {len(parsed)} sprites vs {len(got)}')
    for path in bks:
        bk = omf_files.Bk(path)
        d = open(path, 'rb').read()
        loader.start_file()
        for index, start, parsed in bk.animations:
            got, stopped = loader.run(d, start, 0, False)
            animations += 1
            for s, g in zip(parsed, got):
                sprites += 1
                if (s.length, s.x, s.y, s.width, s.height, s.index, s.missing) != g[:7] or g[7] != s.data[:s.length]:
                    bad += 1
                    print(f'{os.path.basename(path)} animation {index}: sprite differs')
    if bad:
        print(f'FAIL: {bad} sprites differ from the original loader')
        return 1

    # The C++ loader against this reader.
    lines = []
    want = []
    for path in bks:
        lines.append(f'bk {path}')
        want += omf_files.Bk(path).sprites()
    for path in afs:
        for shift in (0, 0x30):
            lines.append(f'af {shift} {path}')
            want += omf_files.Af(path, shift).sprites()
    lines.append('sprites')
    done = subprocess.run([args.probe], input='\n'.join(lines) + '\n', capture_output=True, text=True)
    if done.returncode:
        print(f'FAIL: probe exited with {done.returncode}')
        return 1
    out = done.stdout.splitlines()
    errors = [l for l in out[:len(bks) + 2 * len(afs)] if not l.startswith('ok')]
    if errors:
        print('FAIL: C++ loader rejected a game file:', errors[:3])
        return 1
    records = out[len(bks) + 2 * len(afs):]
    if len(records) != len(want):
        print(f'FAIL: {len(records)} sprites from C++, {len(want)} from the reader')
        return 1
    for i, (line, s) in enumerate(zip(records, want)):
        v = [int(x) for x in line.split()]
        drawable = s.data is not None and s.width != 0
        crc = fnv(s.data[:s.length]) if drawable else 0
        if v != [s.x, s.y, s.width, s.height, s.length, 1 if drawable else 0, crc]:
            print(f'FAIL: sprite {i} differs: {v} vs {[s.x, s.y, s.width, s.height, s.length, drawable, crc]}')
            return 1
    print(f'{len(afs)} .AF (both players) and {len(bks)} .BK: {animations} animations and {sprites} sprites match the '
          f'original loader; {len(records)} records match the C++ loader')
    return 0


if __name__ == '__main__':
    sys.exit(main())
