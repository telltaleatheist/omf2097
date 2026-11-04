// What the compositor draws from: immutable after loading. No file I/O and no pointers
// into it from simulation state, which refers to sprites by index.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace omf {

struct SpriteRecord {
  std::int16_t x = 0;
  std::int16_t y = 0;
  std::uint16_t width = 0;
  std::uint16_t height = 0;
  std::uint16_t length = 0;  // bytes the draw loop walks
  std::uint32_t offset = 0;  // into DrawData::pixels
  bool has_data = false;     // a shared sprite whose source was never loaded has none
};

// The 256-byte tables the original keeps from 0x8bf7b, numbered by distance from there.
inline constexpr std::size_t kTableRows = 25;
inline constexpr std::size_t kRowShadow = 4;     // 0x8c37b, the default remap table
inline constexpr std::size_t kRowGrey = 5;       // 0x8c47b, brightness of each palette colour
inline constexpr std::size_t kRowBlendBase = 6;  // 0x8c57b, source value 0 of the blend lookup
inline constexpr std::size_t kRowFlippedBlendBase = 7;  // 0x8c67b

struct DrawData {
  std::vector<SpriteRecord> sprites = {SpriteRecord{}};  // index 0 means no sprite
  std::vector<std::uint8_t> pixels;
  std::array<std::uint8_t, kTableRows * 256> tables{};
};

}  // namespace omf
