#include "logic/rng.h"

namespace omf {

namespace {

std::uint8_t low_byte(std::uint32_t value) {
  return static_cast<std::uint8_t>(value & 0xff);
}

}  // namespace

// MASTER.DAT @ 0x5e2b0
std::uint32_t rng_next(RngState& state, std::int32_t range) {
  const std::uint32_t tap0 = state.table[state.index[0]];
  const std::uint32_t tap1 = state.table[state.index[1]];
  const std::uint32_t tap2 = state.table[state.index[2]];
  const std::uint32_t tap3 = state.table[state.index[3]];
  const std::uint32_t low_mix = tap0 ^ tap1 ^ tap3;
  // Multiplication wraps at 32 bits, and a negative range wraps with it, as in the original.
  const std::uint32_t scale = static_cast<std::uint32_t>(range);

  std::uint32_t result;
  if (range > 0xffff) {
    // Scales in units of 256, then uses a raw table byte as the low byte.
    const std::uint32_t sample = (tap2 << 8) | low_mix;
    result = (((sample * (scale >> 8)) >> 16) << 8) ^ tap2;
  } else if (range > 0xff) {
    const std::uint32_t sample = ((tap1 ^ tap2 ^ tap3) << 8) | low_mix;
    result = (sample * scale) >> 16;
  } else {
    result = (low_mix * scale) >> 8;
  }

  state.index[0] = low_byte(state.index[0] + 1u);
  state.index[1] = low_byte(state.index[1] - 2u);
  state.index[2] = low_byte(state.index[2] + 7u);
  state.index[3] = low_byte(state.index[3] + 3u);
  return result;
}

// MASTER.DAT @ 0x5e45c
void rng_reseed(RngState& state, std::uint32_t frame, bool hold) {
  if (hold) {
    return;
  }
  state.reseed_counter += 1;
  const std::uint32_t counter = state.reseed_counter;
  state.index[0] = low_byte(frame * 3u + counter);
  state.index[1] = low_byte((frame >> 1) + counter * 3u);
  state.index[2] = low_byte((frame >> 3) + (counter >> 1));
  state.index[3] = low_byte((frame >> 5) + counter * 4u);
}

}  // namespace omf
