#!/usr/bin/env python3
"""Breaks the compositor on purpose, one line at a time, and checks the differential test notices.

Each break edits a temporary copy of the source, so the real source is untouched.

usage: break_compositor.py --cxx <compiler> --elf <master.elf> --game <game dir>
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

# name, text in compositor.cpp, replacement
BREAKS = [
    ('wrong layer order', 'QueueEntry& e = state.queue.entries[static_cast<std::size_t>(layer)];',
     'QueueEntry& e = state.queue.entries[static_cast<std::size_t>(kQueueSize - 1 - layer)];'),
    ('HUD at the wrong layer', 'if (layer == 15 && hooks.hud', 'if (layer == 16 && hooks.hud'),
    ('shadow after its sprite instead of before', """          draw_shadow(state, data, sprite, e.x, base + 0xb2);
          draw.flags = e.flags;
          e.shadow_y0 = draw.bbox_y0;
          e.shadow_y1 = draw.bbox_y1;
        }
        draw_sprite(state, data, sprite, e.x, e.y);""", """          draw_sprite(state, data, sprite, e.x, e.y);
          draw_shadow(state, data, sprite, e.x, base + 0xb2);
          draw.flags = e.flags;
          e.shadow_y0 = draw.bbox_y0;
          e.shadow_y1 = draw.bbox_y1;
        } else {
        draw_sprite(state, data, sprite, e.x, e.y);
        }"""),
    ('shadow uses the entry y', 'sprite.y + e.shadow_base : e.shadow_base - sprite.y', 'sprite.y + e.y : e.y - sprite.y'),
    ('wrong left clip', '    run.x0 = clip.x0;\n', '    run.x0 = clip.x0 + 1;\n'),
    ('wrong right clip', 'if (run.x1 > clip.x1) {\n    if (flip) run.skip = run.x1 - clip.x1;\n    run.x1 = clip.x1;',
     'if (run.x1 > clip.x1 - 1) {\n    if (flip) run.skip = run.x1 - (clip.x1 - 1);\n    run.x1 = clip.x1 - 1;'),
    ('clip skip on the wrong side', 'if (!flip) run.skip = clip.x0 - run.x0;', 'if (flip) run.skip = clip.x0 - run.x0;'),
    ('wrong plain top clip', """      if (row >= clip.y0 && row < clip.y1) {
        const Run run = clip_run(origin_x, column, c.value, flip_x, clip);
        const int count = run.x1 - run.x0;
        if (count > 0 && span_in_buffer(run.x0, row, count)) {
          const Span span{state.buffer""", """      if (row > clip.y0 && row < clip.y1) {
        const Run run = clip_run(origin_x, column, c.value, flip_x, clip);
        const int count = run.x1 - run.x0;
        if (count > 0 && span_in_buffer(run.x0, row, count)) {
          const Span span{state.buffer"""),
    ('plain copy flipped wrong way', 'for (int i = 0; i < s.count; ++i) s.out[s.count - 1 - i] = s.in[i];',
     'for (int i = 0; i < s.count; ++i) s.out[i] = s.in[i];'),
    ('dither step', 'constexpr int kDitherStep = 0x6b;', 'constexpr int kDitherStep = 0x6a;'),
    ('dither start ignores the address', 'settings.buffer_address_low + y * kStride + x', 'y * kStride + x'),
    ('dither compare', 'if (d <= opacity) s.out[i] = s.in[i];', 'if (d < opacity) s.out[i] = s.in[i];'),
    ('colour shift amount', 'if (v < 0x30) v = static_cast<std::uint8_t>(v + 0x30);', 'if (v < 0x30) v = static_cast<std::uint8_t>(v + 0x2f);'),
    ('colour shift limit', 'if (v < 0x30) v = static', 'if (v < 0x60) v = static'),
    ('additive step', 'std::uint8_t amount = static_cast<std::uint8_t>(src * p.additive_step);', 'std::uint8_t amount = static_cast<std::uint8_t>(src);'),
    ('additive ramp stop ignored', 'if (src + level > p.additive_count) {', 'if (false) {'),
    ('flipped additive runs after an additive sprite', 'if (state.draw.additive_seen != 0) return;\n', ''),
    ('additive state not set', 'if ((e.flags & kAdditive) != 0) draw.additive_seen = 1;', ''),
    ('blend lookup base', '(flipped ? kRowFlippedBlendBase : kRowBlendBase) + src', 'kRowBlendBase + src'),
    ('grey blend shift', '(table_at(data, kRowGrey, s.out[i]) >> 3)', '(table_at(data, kRowGrey, s.out[i]) >> 2)'),
    ('grey blend keeps high values wrong', 'if ((v & 0x80) == 0) {\n      v = static_cast<std::uint8_t>((table_at', 'if (true) {\n      v = static_cast<std::uint8_t>((table_at'),
    ('remap table index', 'const std::size_t table_row = (flags & kRemapMask) >> kRemapShift;', 'const std::size_t table_row = kRowShadow;'),
    ('squash draws every row', 'every_fourth = (low_byte & 0x0c) == 0;', 'every_fourth = true;'),
    ('shadow level 3 uses the simple path', 'if (state.settings.shadow_level == 3) {', 'if (state.settings.shadow_level == 99) {'),
    ('shadow row selection', 'visible = source_row == (source_row >> 2) * 4;', 'visible = true;'),
    ('shadow gathered table', 'out[i] = table_at(data, counts[i], out[i]);', 'out[i] = table_at(data, kRowShadow, out[i]);'),
    ('bounding box', 'draw.bbox_y1 = origin_y + static_cast<std::int16_t>(sprite.height) + 1;', 'draw.bbox_y1 = origin_y + static_cast<std::int16_t>(sprite.height);'),
    ('no-draw entry skips the bounding box', '    if (e.flags != 0xff) {\n      if ((e.flags & kText) == 0) {', '    if (e.flags == 0xff) continue;\n    {\n      if ((e.flags & kText) == 0) {'),
    ('queue priority test', '((e.state & 0x7f) >> 3) <= r.priority', '((e.state & 0x7f) >> 3) < r.priority'),
    ('queue search direction', 'while (slot < kQueueSize && entries[static_cast<std::size_t>(slot)].sprite != 0) ++slot;', 'while (slot > 1 && entries[static_cast<std::size_t>(slot)].sprite != 0) --slot;'),
    ('next frame keeps sprites', '    entries[i].sprite = 0;\n', ''),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cxx', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--scenes', type=int, default=6)
    args = ap.parse_args()
    if not os.path.exists(args.elf) or not os.path.isdir(args.game):
        print('SKIP: master.elf or the game files were not found')
        sys.exit(77)
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('SKIP: unicorn is not installed: .venv/bin/pip install -r tests/requirements.txt')
        sys.exit(77)
    import test_compositor

    source = open(os.path.join(ROOT, 'src/logic/compositor.cpp')).read()
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        def build(text, name):
            path = os.path.join(tmp, 'variant.cpp')
            open(path, 'w').write(text)
            out = os.path.join(tmp, name)
            subprocess.run([args.cxx, '-std=c++17', '-O1', '-w', '-I', os.path.join(ROOT, 'src'), path,
                            os.path.join(ROOT, 'src/assets/formats.cpp'), os.path.join(ROOT, 'tests/probe_compositor.cpp'),
                            '-o', out], check=True)
            return out

        clean = test_compositor.run(build(source, 'clean'), args.elf, args.game, args.scenes, quiet=True, min_hits=False, check_shadows=False)
        if clean:
            print(f'FAIL: the unbroken source does not pass at this size: {clean[:300]}')
            return 1
        for number, (name, old, new) in enumerate(BREAKS):
            if source.count(old) != 1:
                failed.append(f'{name}: the text to change must appear exactly once in compositor.cpp')
                continue
            problem = test_compositor.run(build(source.replace(old, new), f'b{number}'), args.elf, args.game, args.scenes,
                                          quiet=True, min_hits=False, check_shadows=False)
            if problem:
                print(f'caught: {name}: {problem[:100]}')
            else:
                failed.append(f'{name}: the differential test did not notice')
    if failed:
        print('FAIL:')
        for line in failed:
            print(' ', line)
        return 1
    print(f'{len(BREAKS)} breaks caught')
    return 0


if __name__ == '__main__':
    sys.exit(main())
