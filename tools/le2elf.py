#!/usr/bin/env python3
"""Convert an MZ+LE executable to a static ELF32 i386 image for analysis.

Objects are placed at their LE base addresses and internal fixups are applied,
so absolute references resolve. The output is for static analysis only: it does
not run. Refuses to write anything if the image has features it cannot convert
faithfully (compressed pages, imports, unknown fixup types).

usage: le2elf.py <input> <output.elf> [--map out.json]
"""
import json
import struct
import sys
from collections import Counter

PAGE_LEGAL, PAGE_ITERATED, PAGE_INVALID, PAGE_ZERO = 0, 1, 2, 3


def u32(d, o):
    return struct.unpack_from('<I', d, o)[0]


def u16(d, o):
    return struct.unpack_from('<H', d, o)[0]


def convert(d):
    if d[:2] != b'MZ':
        sys.exit('not an MZ file')
    le = u32(d, 0x3c)
    if d[le:le + 2] != b'LE':
        sys.exit('no LE header at e_lfanew')

    h = {
        'pages': u32(d, le + 0x14),
        'eip_obj': u32(d, le + 0x18), 'eip': u32(d, le + 0x1c),
        'esp_obj': u32(d, le + 0x20), 'esp': u32(d, le + 0x24),
        'page_size': u32(d, le + 0x28), 'last_page': u32(d, le + 0x2c),
        'obj_tab': u32(d, le + 0x40), 'obj_cnt': u32(d, le + 0x44),
        'page_map': u32(d, le + 0x48),
        'fix_page': u32(d, le + 0x68), 'fix_rec': u32(d, le + 0x6c),
        'imp_cnt': u32(d, le + 0x74),
        'data_pages': u32(d, le + 0x80),
    }
    if h['imp_cnt']:
        sys.exit(f"{h['imp_cnt']} imported modules: not supported")

    # Page map: 3-byte big-endian file page number, then a flags byte.
    page_file = {}
    for i in range(h['pages']):
        e = le + h['page_map'] + i * 4
        num = (d[e] << 16) | (d[e + 1] << 8) | d[e + 2]
        page_file[i + 1] = (num, d[e + 3])

    objects = []
    for i in range(h['obj_cnt']):
        e = le + h['obj_tab'] + i * 24
        vsize, base, flags, idx, n = struct.unpack_from('<IIIII', d, e)
        objects.append(dict(num=i + 1, vsize=vsize, base=base, flags=flags,
                            page_index=idx, page_count=n))

    mem = {}
    page_owner = {}
    for o in objects:
        buf = bytearray(o['vsize'])
        for p in range(o['page_count']):
            logical = o['page_index'] + p
            num, kind = page_file[logical]
            page_owner[logical] = (o, p * h['page_size'])
            if kind in (PAGE_INVALID, PAGE_ZERO):
                continue
            if kind != PAGE_LEGAL:
                sys.exit(f'page {logical}: unsupported page type {kind}')
            size = h['last_page'] if logical == h['pages'] else h['page_size']
            off = h['data_pages'] + (num - 1) * h['page_size']
            raw = d[off:off + size]
            if len(raw) != size:
                sys.exit(f'page {logical}: truncated at file offset {off:#x}')
            start = p * h['page_size']
            take = min(len(raw), max(0, len(buf) - start))
            buf[start:start + take] = raw[:take]
        mem[o['num']] = buf

    by_num = {o['num']: o for o in objects}
    stats = Counter()
    selectors = []

    def apply(src_type, logical, srcoff, tobj, toff):
        o, pstart = page_owner[logical]
        buf = mem[o['num']]
        pos = pstart + srcoff
        kind = src_type & 0x0f
        target = by_num[tobj]['base'] + toff
        stats[kind] += 1
        # Page-spanning fixups appear as negative source offsets on the next
        # page; writes are bounds-checked against the object as a whole.
        if pos < 0:
            stats['negative_srcoff'] += 1
        if kind == 0x07:                      # 32-bit offset
            if pos + 4 > len(buf):
                sys.exit(f'fixup past end of object {o["num"]} at {pos:#x}')
            struct.pack_into('<I', buf, pos, target)
        elif kind == 0x08:                    # 32-bit self-relative
            if pos + 4 > len(buf):
                sys.exit(f'fixup past end of object {o["num"]} at {pos:#x}')
            struct.pack_into('<I', buf, pos, (target - (o['base'] + pos + 4)) & 0xffffffff)
        elif kind == 0x05:                    # 16-bit offset
            struct.pack_into('<H', buf, pos, target & 0xffff)
        elif kind == 0x02:                    # 16-bit selector: no flat equivalent
            selectors.append(dict(obj=o['num'], addr=o['base'] + pos, target_obj=tobj))
        elif kind == 0x06:                    # 16:32 far pointer
            struct.pack_into('<I', buf, pos, target)
            selectors.append(dict(obj=o['num'], addr=o['base'] + pos + 4, target_obj=tobj))
        elif kind == 0x03:                    # 16:16 far pointer
            struct.pack_into('<H', buf, pos, target & 0xffff)
            selectors.append(dict(obj=o['num'], addr=o['base'] + pos + 2, target_obj=tobj))
        else:
            sys.exit(f'unsupported fixup source type {src_type:#x}')

    fp = le + h['fix_page']
    fr = le + h['fix_rec']
    for logical in range(1, h['pages'] + 1):
        if logical not in page_owner:
            continue
        cur = fr + u32(d, fp + (logical - 1) * 4)
        end = fr + u32(d, fp + logical * 4)
        while cur < end:
            src, tgt = d[cur], d[cur + 1]
            cur += 2
            if tgt & 0x03:
                sys.exit(f'non-internal fixup target {tgt:#x} on page {logical}')
            has_list = bool(src & 0x20)
            if has_list:
                count = d[cur]
                cur += 1
            else:
                srcoff = struct.unpack_from('<h', d, cur)[0]
                cur += 2
            if tgt & 0x40:
                tobj = u16(d, cur)
                cur += 2
            else:
                tobj = d[cur]
                cur += 1
            toff = 0
            if (src & 0x0f) != 0x02:          # selector fixups carry no offset
                if tgt & 0x10:
                    toff = u32(d, cur)
                    cur += 4
                else:
                    toff = u16(d, cur)
                    cur += 2
            if has_list:
                for _ in range(count):
                    apply(src, logical, struct.unpack_from('<h', d, cur)[0], tobj, toff)
                    cur += 2
            else:
                apply(src, logical, srcoff, tobj, toff)
        if cur != end:
            sys.exit(f'fixup records for page {logical} overran: {cur:#x} != {end:#x}')

    return h, objects, mem, stats, selectors


def write_elf(path, h, objects, mem):
    n = len(objects)
    entry = next(o for o in objects if o['num'] == h['eip_obj'])['base'] + h['eip']
    align = 0x1000
    phoff = 52
    cur = phoff + n * 32
    placed = []
    for o in objects:
        cur = (cur + align - 1) & ~(align - 1)
        placed.append(cur)
        cur += len(mem[o['num']])

    shstr = bytearray(b'\0')
    names = []
    for o in objects:
        names.append(len(shstr))
        shstr += (b'.text%d' if o['flags'] & 4 else b'.data%d') % o['num'] + b'\0'
    shstr_name = len(shstr)
    shstr += b'.shstrtab\0'
    shstr_off = cur
    shoff = (shstr_off + len(shstr) + 3) & ~3

    out = bytearray(shoff + (n + 2) * 40)
    out[:52] = struct.pack('<16sHHIIIIIHHHHHH',
                           b'\x7fELF\x01\x01\x01' + b'\0' * 9, 2, 3, 1, entry,
                           phoff, shoff, 0, 52, 32, n, 40, n + 2, n + 1)
    for i, o in enumerate(objects):
        body = mem[o['num']]
        pf = (4 if o['flags'] & 1 else 0) | (2 if o['flags'] & 2 else 0) | (1 if o['flags'] & 4 else 0)
        struct.pack_into('<8I', out, phoff + i * 32, 1, placed[i], o['base'], o['base'],
                         len(body), len(body), pf, align)
        out[placed[i]:placed[i] + len(body)] = body
        sf = 2 | (1 if o['flags'] & 2 else 0) | (4 if o['flags'] & 4 else 0)
        struct.pack_into('<10I', out, shoff + (i + 1) * 40, names[i], 1, sf, o['base'],
                         placed[i], len(body), 0, 0, 16, 0)
    out[shstr_off:shstr_off + len(shstr)] = shstr
    struct.pack_into('<10I', out, shoff + (n + 1) * 40, shstr_name, 3, 0, 0,
                     shstr_off, len(shstr), 0, 0, 1, 0)
    open(path, 'wb').write(out)
    return entry


def main():
    args = sys.argv[1:]
    map_path = None
    if '--map' in args:
        i = args.index('--map')
        map_path = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    d = open(args[0], 'rb').read()
    h, objects, mem, stats, selectors = convert(d)
    entry = write_elf(args[1], h, objects, mem)

    print({k: (hex(v) if isinstance(v, int) else v) for k, v in h.items()})
    for o in objects:
        print(f"obj{o['num']}: base={o['base']:#010x} vsize={o['vsize']:#x} flags={o['flags']:#x} "
              f"pages={o['page_index']}+{o['page_count']}")
    print('fixups by source type:', {(hex(k) if isinstance(k, int) else k): v for k, v in stats.items()})
    print('selector sites left unpatched:', len(selectors))
    print(f'entry={entry:#x}')
    if map_path:
        json.dump(dict(entry=entry, header=h, objects=objects, selectors=selectors),
                  open(map_path, 'w'), indent=1)


main()
