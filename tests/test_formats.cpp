// Loader behaviour on made-up files: nothing here comes from the game.
#include <cstdint>
#include <vector>

#include "assets/formats.h"
#include "check.h"

using namespace omf::assets;

namespace {

using Bytes = std::vector<std::uint8_t>;

void u8(Bytes& b, unsigned v) { b.push_back(static_cast<std::uint8_t>(v)); }
void u16(Bytes& b, unsigned v) {
  u8(b, v & 0xff);
  u8(b, (v >> 8) & 0xff);
}
void u32(Bytes& b, std::uint32_t v) {
  u16(b, v & 0xffff);
  u16(b, v >> 16);
}

// One row of two pixels at column 1: set y 0, set x 1, 2 pixels, end.
Bytes sprite_commands() {
  Bytes c;
  u16(c, 0 << 2 | 2);
  u16(c, 1 << 2 | 0);
  u16(c, 2 << 2 | 1);
  u8(c, 5);
  u8(c, 0x40);
  u16(c, 3);
  return c;
}

void put_sprite(Bytes& b, const Bytes& commands, unsigned index, unsigned missing) {
  u16(b, static_cast<unsigned>(commands.size()));
  u16(b, 0xffff);  // x -1
  u16(b, 2);
  u16(b, 4);
  u16(b, 1);
  u8(b, index);
  u8(b, missing);
  if (!missing) b.insert(b.end(), commands.begin(), commands.end());
}

void put_animation(Bytes& b, const Bytes& commands, unsigned sprites, unsigned index) {
  for (int i = 0; i < 8; ++i) u8(b, 0);
  u16(b, 1);  // one coordinate
  u8(b, sprites);
  u32(b, 0x12345678);
  u16(b, 2);
  u8(b, 'A');
  u8(b, '1');
  u8(b, 0);
  u8(b, 0);  // no extra strings
  for (unsigned i = 0; i < sprites; ++i) put_sprite(b, commands, index, 0);
}

Bytes make_bk() {
  Bytes b;
  u32(b, 7);
  u8(b, 0);
  u16(b, 4);
  u16(b, 2);
  const std::size_t at = b.size();
  Bytes animation;
  for (int i = 0; i < 7; ++i) u8(animation, 0);
  u16(animation, 0);
  put_animation(animation, sprite_commands(), 1, 0);
  u32(b, static_cast<std::uint32_t>(at + 5 + animation.size()));
  u8(b, 3);
  b.insert(b.end(), animation.begin(), animation.end());
  u32(b, 0);
  u8(b, 50);
  for (int i = 0; i < 8; ++i) u8(b, 0x70);  // background
  u8(b, 1);
  for (int i = 0; i < 768 + 19 * 256; ++i) u8(b, i % 64);
  for (int i = 0; i < 30; ++i) u8(b, 0);
  return b;
}

Bytes make_af() {
  Bytes b(29, 0);
  u8(b, 2);
  put_animation(b, sprite_commands(), 2, 9);
  for (int i = 0; i < 42; ++i) u8(b, 0);
  u16(b, 0);
  u8(b, 70);
  for (int i = 0; i < 30; ++i) u8(b, 0);
  return b;
}

}  // namespace

TEST("a good BK parses") {
  const Bytes file = make_bk();
  BkFile bk;
  Error error;
  CHECK(parse_bk(file.data(), file.size(), bk, error));
  CHECK(bk.animations.size() == 1);
  CHECK(bk.animations[0].id == 3);
  CHECK(bk.animations[0].animation.sprites.size() == 1);
  CHECK(bk.animations[0].animation.sprites[0].x == -1);
  CHECK(bk.background.size() == 8);
  CHECK(bk.palettes.size() == 1);
}

TEST("a good AF parses, and a repeated index shares the first sprite's data") {
  const Bytes file = make_af();
  AfFile af;
  Error error;
  CHECK(parse_af(file.data(), file.size(), 0, af, error));
  CHECK(af.moves.size() == 1);
  const auto& sprites = af.moves[0].animation.sprites;
  CHECK(sprites.size() == 2);
  CHECK(sprites[0].missing == 0);
  CHECK(sprites[1].missing == 1);
  CHECK(sprites[0].pixel_offset == sprites[1].pixel_offset);
}

TEST("the colour shift applies only below 0x60, and only to pixels") {
  const Bytes file = make_af();
  AfFile af;
  Error error;
  CHECK(parse_af(file.data(), file.size(), 0x30, af, error));
  // Commands stay as they were. Pixel 5 moves up, pixel 0x40 is under 0x60 and moves too.
  const auto& p = af.pixels;
  CHECK(p.size() == 10);
  CHECK(p[6] == 0x35);
  CHECK(p[7] == 0x70);
  CHECK(p[0] == 2);
}

TEST("every truncated file fails cleanly") {
  const Bytes bk = make_bk();
  for (std::size_t n = 0; n < bk.size(); ++n) {
    BkFile out;
    Error error;
    CHECK(!parse_bk(bk.data(), n, out, error));
  }
  const Bytes af = make_af();
  for (std::size_t n = 0; n < af.size(); ++n) {
    AfFile out;
    Error error;
    CHECK(!parse_af(af.data(), n, 0, out, error));
  }
}

TEST("a pixel run past the sprite's data fails") {
  Bytes c;
  u16(c, 200 << 2 | 1);
  u16(c, 3);
  Bytes file(29, 0);
  u8(file, 2);
  put_animation(file, c, 1, 0);
  for (int i = 0; i < 42; ++i) u8(file, 0);
  u16(file, 0);
  u8(file, 70);
  for (int i = 0; i < 30; ++i) u8(file, 0);
  AfFile out;
  Error error;
  CHECK(!parse_af(file.data(), file.size(), 0, out, error));
}

TEST("corrupted bytes never read out of bounds") {
  // Meant to be run with sanitizers; here it checks only that a result comes back.
  for (const Bytes& base : {make_bk(), make_af()}) {
    for (std::size_t at = 0; at < base.size() && at < 400; ++at) {
      for (unsigned value : {0x00u, 0x01u, 0x7fu, 0xffu}) {
        Bytes file = base;
        file[at] = static_cast<std::uint8_t>(value);
        BkFile bk;
        AfFile af;
        Error error;
        parse_bk(file.data(), file.size(), bk, error);
        parse_af(file.data(), file.size(), 0, af, error);
      }
    }
  }
  CHECK(true);
}

TEST("a BK with data after its end fails") {
  Bytes file = make_bk();
  file.push_back(0);
  BkFile out;
  Error error;
  CHECK(!parse_bk(file.data(), file.size(), out, error));
}

TEST("the tables land in the rows the original uses") {
  const Bytes file = make_bk();
  BkFile bk;
  Error error;
  CHECK(parse_bk(file.data(), file.size(), bk, error));
  bk.palettes[0].remap[3][9] = 0xaa;
  bk.palettes[0].remap[4][9] = 0xbb;
  bk.palettes[0].colours[3] = 30;
  bk.palettes[0].colours[4] = 30;
  bk.palettes[0].colours[5] = 0;
  omf::DrawData data;
  CHECK(set_tables(data, bk, 0, error));
  CHECK(data.tables[omf::kRowShadow * 256 + 9] == 0xaa);
  CHECK(data.tables[7 * 256 + 9] == 0xbb);
  CHECK(data.tables[omf::kRowGrey * 256 + 1] == 20);
  CHECK(!set_tables(data, bk, 1, error));
}
