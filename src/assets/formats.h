// Parses the original's .BK and .AF files from bytes already in memory. Every length and
// offset is checked; a malformed file gives an error, never a read past the end.
// The layouts come from the load code in MASTER.DAT. See docs/formats.md.
#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "logic/draw_data.h"

namespace omf::assets {

struct LoadedSprite {
  std::int16_t x = 0;
  std::int16_t y = 0;
  std::uint16_t width = 0;
  std::uint16_t height = 0;
  std::uint16_t length = 0;
  std::uint8_t index = 0;
  std::uint8_t missing = 0;  // as the loader leaves it: data came from an earlier sprite
  std::int32_t pixel_offset = -1;  // into the file's pixels; -1 means no data
};

struct Animation {
  std::array<std::uint8_t, 11> header{};
  std::vector<std::uint32_t> coordinates;
  std::string script;
  std::vector<std::string> extra_strings;
  std::vector<LoadedSprite> sprites;
};

struct Palette {
  std::array<std::uint8_t, 768> colours{};
  std::array<std::array<std::uint8_t, 256>, 19> remap{};
};

struct BkAnimation {
  std::uint8_t id = 0;
  std::array<std::uint8_t, 8> settings{};
  std::string extra;
  Animation animation;
};

struct BkFile {
  std::uint32_t file_id = 0;
  std::uint8_t unknown = 0;
  std::uint16_t width = 0;
  std::uint16_t height = 0;
  std::vector<BkAnimation> animations;
  std::vector<std::uint8_t> background;
  std::vector<Palette> palettes;
  std::array<std::uint8_t, 30> footer{};
  std::vector<std::uint8_t> pixels;
};

struct AfMove {
  std::uint8_t id = 0;
  Animation animation;
  std::array<std::uint8_t, 42> settings{};
  std::string extra;
};

struct AfFile {
  std::array<std::uint8_t, 29> header{};
  std::vector<AfMove> moves;
  std::array<std::uint8_t, 30> footer{};
  std::vector<std::uint8_t> pixels;
};

struct Error {
  std::string message;
  std::size_t offset = 0;
};

// Player 2's fighter loads with colour_shift 0x30, as 0x1b070 sets up.
bool parse_bk(const std::uint8_t* bytes, std::size_t size, BkFile& out, Error& error);
bool parse_af(const std::uint8_t* bytes, std::size_t size, std::uint8_t colour_shift, AfFile& out, Error& error);

// Adds a file's pixels to the draw data. The result is what add_sprites needs.
std::uint32_t add_pixels(DrawData& data, const std::vector<std::uint8_t>& pixels);
// Adds an animation's sprites, and returns the index of the first one.
std::uint32_t add_sprites(DrawData& data, std::uint32_t pixel_base, const Animation& animation);
// Fills the tables from one of a BK file's palettes.
bool set_tables(DrawData& data, const BkFile& file, std::size_t palette, Error& error);

}  // namespace omf::assets
