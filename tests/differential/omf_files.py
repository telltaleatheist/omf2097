"""A second, small reader for the game's .BK and .AF files, for checking the C++ loader
and setting up the original in Unicorn. See docs/formats.md."""
import struct

SPRITE_HEADER = 12


class Sprite:
    def __init__(self, record, data):
        self.length, self.x, self.y, self.width, self.height, self.index, self.missing = record
        self.data = data


def _string(d, p):
    n = struct.unpack_from('<H', d, p)[0]
    return p + 2 + n + 1


def read_animation(d, p, shift, sharing):
    """Returns (sprites, end, sprites start)."""
    coords = struct.unpack_from('<H', d, p + 8)[0]
    count = d[p + 10]
    p += 11 + 4 * coords
    p = _string(d, p)
    extras = d[p]
    p += 1
    for _ in range(extras):
        p = _string(d, p)
    start = p
    out = []
    for _ in range(count):
        length, x, y, w, h, index, missing = struct.unpack_from('<HhhHHBB', d, p)
        p += SPRITE_HEADER
        if sharing is None:
            index = 0
        if index == 0:
            missing = 0
        if missing and sharing is not None:
            out.append(Sprite((length, x, y, w, h, index, missing), sharing.get(index)))
            continue
        data = bytearray(d[p:p + length])
        p += length
        if shift:
            a = 0
            while a + 2 <= length:
                word = data[a] | (data[a + 1] << 8)
                a += 2
                if word & 3 == 1:
                    for i in range(word >> 2):
                        if a + i < length and data[a + i] < 0x60:
                            data[a + i] = (data[a + i] + shift) & 0xff
                    a += word >> 2
        data = bytes(data)
        if index and sharing is not None and sharing.get(index) is not None:
            data = sharing[index]
            missing = 1
        elif sharing is not None:
            sharing[index] = data
        out.append(Sprite((length, x, y, w, h, index, missing), data))
    return out, p, start


class Bk:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.width, self.height = struct.unpack_from('<HH', d, 5)
        p = 9
        self.animations = []
        while True:
            next_at, index = struct.unpack_from('<IB', d, p)
            p += 5
            if index >= 50:
                break
            extra = struct.unpack_from('<H', d, p + 7)[0]
            p += 9 + extra
            sprites, end, _ = read_animation(d, p, 0, None)
            self.animations.append((index, p, sprites))
            p = end
            assert p == next_at
        self.background = d[p:p + self.width * self.height]
        p += self.width * self.height
        self.palettes = []
        count = d[p]
        p += 1
        for _ in range(count):
            colours = d[p:p + 768]
            p += 768
            self.palettes.append((colours, d[p:p + 19 * 256]))
            p += 19 * 256
        assert p + 30 == len(d)

    def sprites(self):
        return [s for _, _, sprites in self.animations for s in sprites]


class Af:
    def __init__(self, path, shift=0):
        d = open(path, 'rb').read()
        self.bytes = d
        p = 29
        self.moves = []
        sharing = {}
        while True:
            move = d[p]
            p += 1
            if move >= 70:
                break
            use = None if move in (12, 13, 14) else sharing
            sprites, end, _ = read_animation(d, p, shift, use)
            self.moves.append((move, p, sprites))
            p = end + 42
            extra = struct.unpack_from('<H', d, p)[0]
            p += 2 + extra
        assert p + 30 == len(d)

    def sprites(self):
        return [s for _, _, sprites in self.moves for s in sprites]
