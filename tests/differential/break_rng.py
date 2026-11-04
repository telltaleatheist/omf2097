#!/usr/bin/env python3
"""Breaks the port on purpose, one line at a time, and checks the differential test notices.

Each break edits a temporary copy of src/logic/rng.cpp, so the real source is untouched.

usage: break_rng.py --cxx <compiler> --elf <master.elf> --random-dat <RANDOM.DAT>
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

# name, text in rng.cpp, replacement, a word the failure message must contain
BREAKS = [
    ('wrong step on index 0', 'state.index[0] + 1u', 'state.index[0] + 2u', 'index0'),
    ('wrong step on index 1', 'state.index[1] - 2u', 'state.index[1] - 1u', 'index1'),
    ('wrong step on index 2', 'state.index[2] + 7u', 'state.index[2] + 5u', 'index2'),
    ('wrong step on index 3', 'state.index[3] + 3u', 'state.index[3] + 7u', 'index3'),
    ('tap reads the wrong index', 'state.table[state.index[3]]', 'state.table[state.index[2]]', 'value'),
    ('low mix leaves out a tap', 'tap0 ^ tap1 ^ tap3', 'tap0 ^ tap3', 'value'),
    ('middle branch uses the wrong taps', '(tap1 ^ tap2 ^ tap3) << 8', '(tap0 ^ tap2 ^ tap3) << 8', 'value'),
    ('large branch starts one too high', 'range > 0xffff', 'range > 0x10000', 'value'),
    ('middle branch starts one too low', 'range > 0xff)', 'range >= 0xff)', 'value'),
    ('large branch loses the raw low byte', ' ^ tap2;', ';', 'value'),
    ('hold is ignored', 'if (hold) {', 'if (false) {', 'counter'),
    ('counter does not advance', 'state.reseed_counter += 1;', '', 'counter'),
    ('reseed uses the wrong frame shift', '(frame >> 5)', '(frame >> 4)', 'index3'),
    ('reseed uses the wrong counter shift', '(counter >> 1)', '(counter >> 2)', 'index2'),
    ('reseed uses the wrong multiplier', 'frame * 3u', 'frame * 5u', 'index0'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cxx', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--random-dat', required=True)
    ap.add_argument('--ops', type=int, default=6000)
    args = ap.parse_args()
    for path in (args.elf, args.random_dat):
        if not os.path.exists(path):
            print(f'SKIP: {path} not found')
            sys.exit(77)
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('SKIP: unicorn is not installed: .venv/bin/pip install -r tests/requirements.txt')
        sys.exit(77)
    import test_rng

    source = open(os.path.join(ROOT, 'src/logic/rng.cpp')).read()
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        def build(text, name):
            path = os.path.join(tmp, 'rng_variant.cpp')
            open(path, 'w').write(text)
            out = os.path.join(tmp, name)
            subprocess.run([args.cxx, '-std=c++17', '-O1', '-I', os.path.join(ROOT, 'src'), path,
                            os.path.join(ROOT, 'tests/probe_rng.cpp'), '-o', out], check=True)
            return out

        clean = test_rng.run(build(source, 'clean'), args.elf, args.random_dat, args.ops, seeds=(1,), quiet=True)
        if clean:
            print(f'FAIL: the unbroken source does not pass at this size: {clean}')
            sys.exit(1)
        for number, (name, old, new, expect) in enumerate(BREAKS):
            if source.count(old) != 1:
                failed.append(f'{name}: "{old}" must appear exactly once in rng.cpp')
                continue
            problem = test_rng.run(build(source.replace(old, new), f'b{number}'), args.elf, args.random_dat,
                                   args.ops, seeds=(1,), quiet=True)
            if not problem:
                failed.append(f'{name}: the differential test did not notice')
            elif expect not in problem:
                failed.append(f'{name}: noticed, but not in {expect}: {problem}')
            else:
                print(f'caught: {name}: {problem[:110]}')
    if failed:
        print('FAIL:')
        for line in failed:
            print(' ', line)
        sys.exit(1)
    print(f'{len(BREAKS)} breaks caught')


if __name__ == '__main__':
    main()
