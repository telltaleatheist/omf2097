#!/usr/bin/env python3
"""Runs the original queue and compositor in Unicorn against the C++, on real sprites and
palettes, and compares the whole 64,000-byte buffer, the draw state and the queue.

The HUD callback and the font routine are stubbed the same way on both sides.

usage: test_compositor.py --probe <probe_compositor> --elf <master.elf> --game <game dir> [--scenes N]
"""
import argparse
import glob
import os
import random
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

QUEUE_RESET, QUEUE_ADD, QUEUE_NEXT, COMPOSE, GREY_TABLE, DRAW_TEXT = 0x5e284, 0x5caa0, 0x5cd48, 0x5d0a0, 0x56ddc, 0x3474c
DRAW_SHADOW = 0x5bc7c
HEAP = 0x400000
BUFFERS = 0x800000
STUB = 0x1f1000
TABLES_A, TABLES_B, PALETTE, SCREEN_OBJECT = 0x8c07b, 0x8c67b, 0x8d57b, 0x8bb5c

ROUTINES = {
    0x5a304: 'copy', 0x5a35c: 'copy flipped', 0x5a2b4: 'shift colours', 0x5a2d8: 'shift colours flipped',
    0x5a3d0: 'additive', 0x5a484: 'additive flipped', 0x5d300: 'blend lookup', 0x5d338: 'blend lookup flipped',
    0x5a4b8: 'blend grey', 0x5a540: 'blend grey flipped', 0x5a188: 'remap dithered', 0x5a158: 'remap table',
    0x5bc7c: 'shadow', 0x5a214: 'shadow gathered', 0x3474c: 'text',
}


def skip(why):
    print(f'SKIP: {why}')
    sys.exit(77)


def max_pixel(sprite):
    d = sprite.data
    at = top = 0
    while at + 2 <= sprite.length:
        word = d[at] | (d[at + 1] << 8)
        at += 2
        if word & 3 == 1:
            run = d[at:at + (word >> 2)]
            if run:
                top = max(top, max(run))
            at += word >> 2
        elif word & 3 == 3:
            break
    return top


def extent(sprite):
    """The sprite's drawn area, in its own columns and rows: (first column, end column, first row, last row)."""
    d = sprite.data
    at = column = row = 0
    x0, x1, y0, y1 = 1 << 30, 0, 1 << 30, 0
    while at + 2 <= sprite.length:
        word = d[at] | (d[at + 1] << 8)
        at += 2
        op, value = word & 3, word >> 2
        if op == 0:
            column = value
        elif op == 1:
            x0, x1 = min(x0, column), max(x1, column + value)
            y0, y1 = min(y0, row), max(y1, row)
            at += value
        elif op == 2:
            row = value
        else:
            break
    return x0, x1, y0, y1


def plain_entry(layer, x, y, sprite, flags=0, opacity=0xff):
    return (layer, x, y, sprite, flags, 100, 100, opacity, 0xff, 0xff, 5, 0)


def flat_scene(clip):
    s = Scene()
    s.settings = (*clip, 2, 6, 0x60, 0, 0x10)
    s.draw = (0, 100, 100, 0xff, 0xff, 0xff, 0, 0, 0, 0, 0)
    return s


def boundary_scenes(sprites, usable):
    """Scenes that sit exactly on the things random positions rarely hit."""
    big = [i for i in usable if sprites[i - 1].width >= 40 and sprites[i - 1].height >= 30 and sprites[i - 1].width < 0x8000][:6]
    scenes = []
    # A sprite at each layer around the HUD call, over the pixels the hook changes.
    for layer in (14, 15, 16):
        s = flat_scene((0, 0, 320, 200))
        s.hud = 16
        sp = sprites[big[0] - 1]
        x0, x1, y0, y1 = extent(sp)
        s.adds = [plain_entry(layer, 158 - sp.x - (x0 + x1) // 2, 100 - sp.y - (y0 + y1) // 2, big[0])]
        scenes.append(s)
    # Runs touching each edge of the clip window exactly, and one pixel either side.
    for clip in ((0, 0, 320, 200), (37, 21, 250, 160)):
        cx0, cy0, cx1, cy1 = clip
        for number in big[:3]:
            sp = sprites[number - 1]
            x0, x1, y0, y1 = extent(sp)
            for nudge in (-1, 0, 1):
                s = flat_scene(clip)
                middle_x = (cx0 + cx1) // 2 - sp.x - (x0 + x1) // 2
                middle_y = (cy0 + cy1) // 2 - sp.y - (y0 + y1) // 2
                s.adds = [
                    plain_entry(20, cx0 - sp.x - x0 + nudge, middle_y, number),
                    plain_entry(21, cx1 - sp.x - x1 + nudge, middle_y, number),
                    plain_entry(22, middle_x, cy0 - sp.y - y0 + nudge, number),
                    plain_entry(23, middle_x, cy1 - 1 - sp.y - y1 + nudge, number),
                    # Flipped: columns run the other way from x + 1 - sprite x.
                    plain_entry(24, cx0 + x1 - 1 + sp.x + nudge, middle_y, number, 1),
                    plain_entry(25, cx1 + x0 - 1 + sp.x + nudge, middle_y, number, 1),
                    # With modes, through the other path.
                    plain_entry(26, cx0 - sp.x - x0 + nudge, middle_y, number, 0x800),
                    plain_entry(27, cx1 - sp.x - x1 + nudge, middle_y, number, 0x800),
                    plain_entry(28, cx0 - sp.x - x0 + nudge, middle_y, number, 0x20),
                    plain_entry(29, middle_x, cy1 - 1 - sp.y - y1 + nudge, number, 0x400),
                ]
                scenes.append(s)
    return scenes


class Scene:
    """One compose: what goes in, and a text form of it for the probe."""

    def __init__(self):
        self.settings = None
        self.draw = None
        self.fill = None  # None means the arena background
        self.text_enabled = 1
        self.hud = 0
        self.adds = []
        self.next_first = False


def make_scene(rng, pool, low_pool):
    s = Scene()
    kind = rng.random()
    if kind < 0.6:
        clip = (0, 0, 320, 200)
    elif kind < 0.8:
        clip = (rng.randint(0, 8), 0, rng.randint(312, 320), 200)
    else:
        x0, y0 = rng.randint(0, 200), rng.randint(0, 120)
        clip = (x0, y0, rng.randint(x0 + 1, 320), rng.randint(y0 + 1, 200))
    s.settings = (*clip, rng.randint(1, 6), rng.randint(0, 15), rng.choice((0, 0x60, 0x80, 0xc0)), rng.randint(0, 3),
                  rng.choice((0, 4, 0x10, 0x20, 0x7c, 0x80, 0xfc, rng.randrange(256))))
    s.draw = (rng.randrange(0x10000) & 0x0fff, 100, 100, 0xff, 0xff, 0xff, rng.randint(-5, 5), 0, 0, 0, rng.randint(0, 1))
    s.fill = None if rng.random() < 0.7 else rng.randrange(1 << 30)
    s.text_enabled = 0 if rng.random() < 0.1 else 1
    s.hud = rng.choice((0, 0, 4, 16))
    n = 250 if rng.random() < 0.08 else rng.randint(1, 16)
    for _ in range(n):
        s.adds.append(make_entry(rng, pool, low_pool, n >= 200))
    return s


def make_entry(rng, pool, low_pool, crowd):
    k = rng.random()
    flags = rng.choice((0, 1, 4, 5))
    sprite = rng.choice(pool)
    scale = (100, 100)
    opacity = 0xff
    if k < 0.28:
        pass
    elif k < 0.38:
        opacity = rng.choice((0x20, 0x60, 0x80, 0xc0, rng.randrange(0xff)))
    elif k < 0.46:
        flags |= 0x10
        opacity = rng.choice((0xff, 0xff, 0x80))
    elif k < 0.56:
        flags |= rng.randint(1, 7) << 5
    elif k < 0.64:
        flags |= 0x100
        sprite = rng.choice(low_pool)
    elif k < 0.72:
        flags |= 0x200
    elif k < 0.80:
        flags |= 0x400
        opacity = rng.choice((0xff, 0xff, 0x90))
    elif k < 0.88:
        flags |= 0x800
    elif k < 0.92:
        scale = (rng.choice((50, 100, 150)), rng.choice((50, 75, 100, 125, 200)))
    elif k < 0.95:
        flags = 0xff
    elif k < 0.97:
        flags |= 0x2000
        sprite = -1
    else:
        flags |= 8
    edge = rng.random()
    if edge < 0.55:
        x, y = rng.randint(0, 319), rng.randint(0, 199)
    elif edge < 0.7:
        x, y = rng.choice((rng.randint(-200, 5), rng.randint(315, 520))), rng.randint(-40, 240)
    elif edge < 0.85:
        x, y = rng.randint(-40, 360), rng.choice((rng.randint(-200, 5), rng.randint(195, 400)))
    else:
        x, y = rng.choice((0, 319, 320, -1)), rng.choice((0, 199, 200, -1))
    layer = rng.choice((0, 1, 2, 14, 15, 16, 17, 30, 31, 35, 60, 219, rng.randint(0, 219)))
    if crowd:
        layer = rng.choice((0, 30, 200, 219))
    extra = 0x1000 if rng.random() < 0.25 and not flags & 0x2000 else 0
    return (layer, x, y, sprite, flags, scale[0], scale[1], opacity, rng.choice((0xff, 0xff, 3)), rng.choice((0xff, 0xff, 5)),
            rng.randint(0, 15), extra)


class OriginalSide:
    def __init__(self, elf, sprites, tables, colours, background):
        from original import Original
        from unicorn import UC_HOOK_CODE, UC_PROT_ALL
        self.o = Original(elf)
        uc = self.o.uc
        uc.mem_map(HEAP, 0x400000, UC_PROT_ALL)
        uc.mem_map(BUFFERS, 0x100000, UC_PROT_ALL)
        self.background = background
        self.hits = {name: 0 for name in ROUTINES.values()}
        self.queue = HEAP
        self.stubs = {}
        at = HEAP + 0x5000
        self.records = [0]
        self.index_of = {0: 0}
        for i, s in enumerate(sprites):
            ptr = 0
            if s.data is not None and s.width != 0:
                ptr = at
                self.o.write(at, s.data[:s.length])
                at += (s.length + 3) & ~3
            rec = at
            at += 16
            self.o.write(rec, struct.pack('<IHhhHHBB', ptr, s.length, s.x, s.y, s.width, s.height, s.index, s.missing))
            self.records.append(rec)
            self.index_of[rec] = i + 1
        self.text_flag = at
        self.o.write(0x8e610, struct.pack('<I', at))
        self.o.write(0x84998, struct.pack('<I', 0x8c37b))
        self.o.write(0x8499c, struct.pack('<I', 0x8bf7b))
        self.o.write(0x8e498, struct.pack('<H', 0x140))
        self.o.write(TABLES_A, tables[:0x400])
        self.o.write(TABLES_B, tables[0x400:0x400 + 0xf00])
        self.o.write(PALETTE, colours)
        self.o.write(SCREEN_OBJECT + 0x1a1f, colours)
        self.o.call(GREY_TABLE, eax=SCREEN_OBJECT)
        self.o.write(DRAW_TEXT, b'\xc2\x08\x00')  # ret 8
        self.o.call(QUEUE_RESET, eax=self.queue)
        for addr, name in ROUTINES.items():
            def bump(_uc, _a, _n, _d, name=name):
                self.hits[name] += 1
            uc.hook_add(UC_HOOK_CODE, bump, begin=addr, end=addr)

    def hud_stub(self, pixels):
        """Adds 7 to a run of pixels, the same as the probe's hook. Written once for each size,
        because Unicorn keeps translated code even if the memory under it changes."""
        address = STUB + pixels * 0x100
        if pixels not in self.stubs:
            code = b'\x53\x8b\x1d' + struct.pack('<I', 0x8e484)   # push ebx; mov ebx,[back buffer]
            for i in range(pixels):
                code += b'\x80\x83' + struct.pack('<I', 100 * 320 + 150 + i) + b'\x07'  # add byte [ebx+n],7
            code += b'\x5b\xc3'  # pop ebx; ret
            self.o.write(address, code)
            self.stubs[pixels] = address
        return address

    def run(self, scene):
        o = self.o
        low = scene.settings[8]
        buffer = BUFFERS + 0x10000 + low
        o.write(0x8e48c, struct.pack('<I', buffer))
        o.write(0x8e484, struct.pack('<I', buffer))
        x0, y0, x1, y1, step, count, base, level, _ = scene.settings
        o.write(0x8e49c, struct.pack('<hhhh', x0, y0, x1, y1))
        o.write(0x8b948, bytes([step, count]))
        o.write(0x8b950, bytes([base]))
        o.write(0x8e5e2, bytes([level << 2, 0]))
        flags, sx, sy, op, b, a, bx0, bx1, by0, by1, seen = scene.draw
        o.write(0x8e494, struct.pack('<H', flags))
        o.write(0x8e4c4, bytes([sx, sy, op, b, a]))
        o.write(0x8e4a4, struct.pack('<iiii', bx0, bx1, by0, by1))
        o.write(0x8b951, bytes([seen]))
        o.write(self.text_flag + 0x1c, bytes([0 if scene.text_enabled else 2]))
        if scene.fill is None:
            o.write(buffer, self.background)
        else:
            state = scene.fill
            out = bytearray(64000)
            for i in range(64000):
                state = (state * 1103515245 + 12345) & 0xffffffff
                out[i] = (state >> 16) & 0xff
            o.write(buffer, bytes(out))
        slots = []
        for layer, x, y, sprite, fl, sx, sy, op, a, b, pri, extra in scene.adds:
            rec = 0x51500 if sprite == -1 else self.records[sprite]
            stack = (rec, fl, sx, sy, op, a, b, pri, extra)
            slots.append(self.call_stack(QUEUE_ADD, stack, eax=self.queue, edx=layer, ebx=x & 0xffffffff, ecx=y & 0xffffffff))
        o.call(COMPOSE, eax=self.queue, edx=self.hud_stub(scene.hud))
        return slots, o.read(buffer, 64000), self.state()

    def run_shadows_only(self, scene):
        from original import REGS  # noqa: F401
        o = self.o
        buffer = BUFFERS + 0x10000
        o.write(0x8e48c, struct.pack('<I', buffer))
        o.write(0x8e484, struct.pack('<I', buffer))
        x0, y0, x1, y1, step, count, base, level, _ = scene.settings
        o.write(0x8e49c, struct.pack('<hhhh', x0, y0, x1, y1))
        o.write(0x8e5e2, bytes([level << 2, 0]))
        o.write(0x8e494, struct.pack('<H', 0))
        o.write(0x8e4c4, bytes([100, 100, 0xff, 0xff, 0xff]))
        o.write(buffer, self.background)
        for layer, x, y, sprite, *_ in scene.adds:
            o.call(DRAW_SHADOW, eax=self.records[sprite], edx=x, ebx=y)
        return [], o.read(buffer, 64000), None

    def call_stack(self, addr, stack, **regs):
        from original import REGS, RETURN_TO, STACK_TOP
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EFLAGS, UC_X86_REG_ESP
        uc = self.o.uc
        for name, reg in REGS.items():
            uc.reg_write(reg, regs.get(name, 0xdead0000) & 0xffffffff)
        uc.reg_write(UC_X86_REG_EFLAGS, 2)
        uc.reg_write(UC_X86_REG_ESP, STACK_TOP)
        frame = struct.pack('<I', RETURN_TO) + b''.join(struct.pack('<I', v & 0xffffffff) for v in stack)
        uc.mem_write(STACK_TOP, frame)
        uc.emu_start(addr, RETURN_TO, count=50_000_000)
        return struct.unpack('<i', struct.pack('<I', uc.reg_read(UC_X86_REG_EAX)))[0]

    def state(self):
        o = self.o
        flags = struct.unpack('<H', o.read(0x8e494, 2))[0]
        sx, sy, op, b, a = o.read(0x8e4c4, 5)
        bbox = struct.unpack('<iiii', o.read(0x8e4a4, 16))
        seen = o.read(0x8b951, 1)[0]
        draw = [flags, sx, sy, op, b, a, *bbox, seen]
        entries = []
        raw = o.read(self.queue + 0xc, 220 * 0x54)
        for i in range(220):
            e = raw[i * 0x54:(i + 1) * 0x54]
            st = struct.unpack_from('<H', e, 0)[0]
            extra, x, y, bx0, bx1, by0, by1 = struct.unpack_from('<Iiiiiii', e, 8)
            sy0, sy1 = struct.unpack_from('<ii', e, 0x34)
            fl = struct.unpack_from('<H', e, 0x44)[0]
            esx, esy, eop, eb, ea = e[0x46], e[0x47], e[0x48], e[0x49], e[0x4a]
            prev, sprite = struct.unpack_from('<II', e, 0x4c)
            entries.append([st, extra, x, y, bx0, bx1, by0, by1, sy0, sy1, fl, esx, esy, eop, eb, ea,
                            self.index_of.get(prev, 0xffff if prev else 0), self.index_of.get(sprite, 0xffff if sprite else 0)])
        return draw, entries

    def next_frame(self):
        self.o.call(QUEUE_NEXT, eax=self.queue)

    def clear(self):
        self.o.call(QUEUE_RESET, eax=self.queue)


def scene_lines(scene):
    lines = [f'reset {scene.text_enabled} {scene.hud}', 'settings ' + ' '.join(str(v) for v in scene.settings),
             'draw ' + ' '.join(str(v) for v in scene.draw)]
    lines.append('background' if scene.fill is None else f'fill {scene.fill}')
    for layer, x, y, sprite, *rest in scene.adds:
        lines.append(f'add {layer} {x} {y} {0xffff if sprite == -1 else sprite} ' + ' '.join(str(v) for v in rest))
    lines += ['compose', 'dump']
    return lines


def check_shadow_keeps_fighters(elf, game):
    """In the original itself: a shadow at each level, over a buffer of fighter colours, in
    every palette of every arena."""
    import omf_files
    for arena in sorted(glob.glob(os.path.join(game, 'ARENA*.BK'))):
        bk = omf_files.Bk(arena)
        sprites = bk.sprites() + omf_files.Af(sorted(glob.glob(os.path.join(game, 'FIGHTR*.AF')))[0], 0).sprites()
        usable = [i + 1 for i, s in enumerate(sprites) if s.data is not None and s.width > 40 and s.height > 40]
        for number, (colours, remap) in enumerate(bk.palettes):
            side = OriginalSide(elf, sprites, remap, colours, bytes(((i % 95) + 1) for i in range(64000)))
            for level in range(4):
                scene = Scene()
                scene.settings = (0, 0, 320, 200, 1, 0, 0, level, 0)
                scene.draw = (0, 100, 100, 0xff, 0xff, 0xff, 0, 0, 0, 0, 0)
                scene.adds = [(30 + i, 40 + i * 30, 80, usable[i * 7 % len(usable)], 0, 100, 100, 0xff, 0xff, 0xff, 5, 0x1000)
                              for i in range(8)]
                # Only the shadows: sprites would overwrite the buffer, so run the routine directly.
                side.clear()
                _, buffer, _ = side.run_shadows_only(scene)
                if buffer != side.background:
                    return f'{os.path.basename(arena)} palette {number} level {level}: a shadow changed a fighter colour'
    return None


def run(probe, elf, game, scenes_per_arena, seed=11, quiet=False, min_hits=True, check_shadows=True):
    """Returns the first difference as text, or None."""
    import omf_files
    arenas = sorted(glob.glob(os.path.join(game, 'ARENA*.BK')))
    fighters = sorted(glob.glob(os.path.join(game, 'FIGHTR*.AF')))
    rng = random.Random(seed)
    totals = {}
    edges = {'left': 0, 'right': 0, 'above': 0, 'below': 0, 'flip x': 0, 'flip y': 0, 'crowded': 0, 'clipped window': 0,
             'plain path': 0, 'dithered copy': 0, 'squash': 0, 'squash dithered': 0, 'scaled': 0, 'no-draw entry': 0,
             'shadow level 0': 0, 'shadow level 1': 0, 'shadow level 2': 0, 'shadow level 3': 0, 'additive after additive': 0,
             'hud': 0, 'text disabled': 0, 'evicted': 0, 'boundary scenes': 0}
    scenes_done = 0
    for arena_number, arena in enumerate(arenas):
        bk = omf_files.Bk(arena)
        palette_index = rng.randrange(len(bk.palettes))
        colours, remap = bk.palettes[palette_index]
        a, b = rng.sample(fighters, 2)
        sprites = bk.sprites() + omf_files.Af(a, 0).sprites() + omf_files.Af(b, 0x30).sprites()
        usable = [i + 1 for i, s in enumerate(sprites) if s.data is not None and s.width != 0]
        # Blend lookup indexes tables by source value, and past value 17 reads memory the port
        # doesn't model (docs/formats.md). Frames using it in the arenas stay at 15 or below.
        low = [i for i in usable if max_pixel(sprites[i - 1]) <= 17]
        if not low:
            return f'{os.path.basename(arena)}: no sprite with low enough values for blend lookup'
        side = OriginalSide(elf, sprites, remap, colours, bk.background)
        lines = [f'bk {arena}', f'af 0 {a}', f'af 48 {b}', f'tables {palette_index}']
        scenes = boundary_scenes(sprites, usable) + [make_scene(rng, usable, low) for _ in range(scenes_per_arena)]
        # Empty placeholder sprites have a negative width. At shadow level 3 that gives the
        # original a negative memset length, and it runs off the end of memory (docs/open-questions.md).
        placeholders = {i + 1 for i, s in enumerate(sprites) if s.width >= 0x8000}
        for scene in scenes:
            scene.adds = [(*a[:11], 0) if a[11] and a[3] in placeholders else a for a in scene.adds]
        for i, scene in enumerate(scenes):
            scene.next_first = bool(i) and rng.random() < 0.3
            lines.append('next' if scene.next_first else 'clear')
            lines += scene_lines(scene)
        done = subprocess.run([probe], input='\n'.join(lines) + '\n', capture_output=True, text=True)
        if done.returncode:
            return f'probe exited with {done.returncode}'
        out = iter(done.stdout.splitlines())
        for line in (next(out), next(out), next(out)):
            if not line.startswith('ok'):
                return f'loader: {line}'
        for number, scene in enumerate(scenes):
            if scene.next_first:
                side.next_frame()
            else:
                side.clear()
            slots, buffer, (draw, entries) = side.run(scene)
            for slot, add in zip(slots, scene.adds):
                got = int(next(out))
                if got != slot:
                    return f'{os.path.basename(arena)} scene {number}: queue slot for {add}: original {slot}, port {got}'
            got_buffer = bytes.fromhex(next(out))
            got_draw = [int(x) for x in next(out).split()]
            got_entries = [[int(x) for x in next(out).split()] for _ in range(220)]
            if got_buffer != buffer:
                at = next(i for i in range(64000) if got_buffer[i] != buffer[i])
                count = sum(1 for i in range(64000) if got_buffer[i] != buffer[i])
                return (f'{os.path.basename(arena)} scene {number}: buffer differs in {count} pixels, first at x={at % 320} y={at // 320}: '
                        f'original {buffer[at]:#x}, port {got_buffer[at]:#x}; settings {scene.settings}; draw {scene.draw}; adds {scene.adds[:6]}')
            if got_draw != draw:
                names = 'flags scale_x scale_y opacity b a bbox_x0 bbox_x1 bbox_y0 bbox_y1 additive'.split()
                bad = [n for n, p, q in zip(names, draw, got_draw) if p != q]
                return f'{os.path.basename(arena)} scene {number}: draw state differs in {bad}: original {draw}, port {got_draw}; adds {scene.adds[:6]}'
            for slot, (p, q) in enumerate(zip(entries, got_entries)):
                if p != q:
                    names = 'state extra x y bx0 bx1 by0 by1 sy0 sy1 flags sx sy op b a previous sprite'.split()
                    return (f'{os.path.basename(arena)} scene {number}: queue entry {slot} differs in '
                            f'{[n for n, u, v in zip(names, p, q) if u != v]}: original {p}, port {q}')
            scenes_done += 1
            edges['boundary scenes'] += number < len(boundary_scenes(sprites, usable))
            for add in scene.adds:
                _, x, y, sprite, fl, sx, sy, op, _a, _b, _p, extra = add
                edges['plain path'] += fl in (0, 1, 4, 5) and op == 0xff and sx == 100 and sy == 100
                edges['dithered copy'] += fl in (0, 1, 4, 5) and op != 0xff
                edges['squash'] += bool(fl & 0x10) and fl != 0xff and op == 0xff
                edges['squash dithered'] += bool(fl & 0x10) and fl != 0xff and op != 0xff
                edges['scaled'] += sy != 100
                edges['no-draw entry'] += fl == 0xff
                if extra and fl != 0xff:
                    edges[f'shadow level {scene.settings[7]}'] += 1
                edges['left'] += x < 0
                edges['right'] += x >= 320
                edges['above'] += y < 0
                edges['below'] += y >= 200
                edges['flip x'] += bool(fl & 1) and fl != 0xff
                edges['flip y'] += bool(fl & 4) and fl != 0xff
            edges['crowded'] += len(scene.adds) >= 200
            edges['additive after additive'] += sum(1 for add in scene.adds if add[4] != 0xff and add[4] & 0x200) >= 2
            edges['hud'] += scene.hud != 0
            edges['text disabled'] += scene.text_enabled == 0
            edges['evicted'] += len(scene.adds) > 220
            edges['clipped window'] += scene.settings[:4] != (0, 0, 320, 200)
        for k, v in side.hits.items():
            totals[k] = totals.get(k, 0) + v
    if check_shadows:
        problem = check_shadow_keeps_fighters(elf, game)
        if problem:
            return problem
    if min_hits:
        missing = [k for k, v in totals.items() if v == 0] + [k for k, v in edges.items() if v == 0]
        if missing:
            return f'the run never exercised: {missing}'
    if not quiet:
        print(f'{scenes_done} scenes across {len(arenas)} arenas match: whole buffer, draw state and queue. Routines reached: {totals}. Edges: {edges}')
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--scenes', type=int, default=30)
    args = ap.parse_args()
    if not os.path.exists(args.elf):
        skip(f'master.elf (tools/build_analysis.sh) not found at {args.elf}')
    if not os.path.isdir(args.game):
        skip(f'the game was not found at {args.game}')
    try:
        import unicorn  # noqa: F401
    except ImportError:
        skip('unicorn is not installed: .venv/bin/pip install -r tests/requirements.txt')
    problem = run(args.probe, args.elf, args.game, args.scenes)
    if problem:
        print('FAIL:', problem[:900])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
