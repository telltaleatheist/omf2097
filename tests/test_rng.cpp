// Behaviour that needs no game files: a made-up table and hand-worked answers.
// tests/differential/test_rng.py checks the port against the original.
#include <cstddef>
#include <cstring>

#include "check.h"
#include "logic/rng.h"

using omf::RngState;
using omf::rng_next;
using omf::rng_reseed;

namespace {

RngState ramp_state() {
  RngState state;
  for (int i = 0; i < 256; ++i) {
    state.table[static_cast<std::size_t>(i)] = static_cast<std::uint8_t>(i);
  }
  return state;
}

// Table bytes chosen per tap, so each answer can be worked out by hand.
RngState tap_state(std::uint8_t tap0, std::uint8_t tap1, std::uint8_t tap2, std::uint8_t tap3) {
  RngState state;
  state.index = {10, 20, 30, 40};
  state.table[10] = tap0;
  state.table[20] = tap1;
  state.table[30] = tap2;
  state.table[40] = tap3;
  return state;
}

}  // namespace

TEST("a small range scales the low mix by range / 256") {
  RngState state = tap_state(0xf0, 0x0f, 0x55, 0x00);  // mix: 0xff
  CHECK(rng_next(state, 200) == (0xffu * 200u) >> 8);
}

TEST("the range boundaries pick the documented branch") {
  RngState state = tap_state(0x01, 0x02, 0x04, 0x08);  // low mix 0x0b, high mix 0x0e
  CHECK(rng_next(state, 0xff) == (0x0bu * 0xffu) >> 8);
  state = tap_state(0x01, 0x02, 0x04, 0x08);
  CHECK(rng_next(state, 0x100) == (0x0e0bu * 0x100u) >> 16);
  state = tap_state(0x01, 0x02, 0x04, 0x08);
  CHECK(rng_next(state, 0xffff) == (0x0e0bu * 0xffffu) >> 16);
  state = tap_state(0x01, 0x02, 0x04, 0x08);
  // Above 0xffff: sample 0x040b scaled by 0x100, then the raw tap as the low byte.
  CHECK(rng_next(state, 0x10000) == ((((0x040bu * 0x100u) >> 16) << 8) ^ 0x04u));
}

TEST("a negative range wraps at 32 bits") {
  RngState state = tap_state(0x10, 0x00, 0x00, 0x00);
  CHECK(rng_next(state, -1) == ((0x10u * 0xffffffffu) >> 8));
}

TEST("each draw steps the four positions, wrapping at a byte") {
  RngState state;
  state.index = {255, 1, 250, 254};
  rng_next(state, 1);
  CHECK(state.index[0] == 0);
  CHECK(state.index[1] == 255);
  CHECK(state.index[2] == 1);
  CHECK(state.index[3] == 1);
}

TEST("without a reseed the sequence repeats every 256 draws") {
  RngState state = ramp_state();
  state.index = {3, 141, 59, 26};
  const RngState start = state;
  std::uint32_t first[256];
  for (std::uint32_t& value : first) {
    value = rng_next(state, 0x7fff);
  }
  CHECK(state.index == start.index);
  for (std::uint32_t value : first) {
    CHECK(rng_next(state, 0x7fff) == value);
  }
}

TEST("reseed adds one to the counter and derives the positions from it") {
  RngState state;
  state.reseed_counter = 0x1ff;  // becomes 0x200
  rng_reseed(state, 0x1234, false);
  CHECK(state.reseed_counter == 0x200);
  CHECK(state.index[0] == ((0x1234u * 3u + 0x200u) & 0xff));
  CHECK(state.index[1] == (((0x1234u >> 1) + 0x200u * 3u) & 0xff));
  CHECK(state.index[2] == (((0x1234u >> 3) + (0x200u >> 1)) & 0xff));
  CHECK(state.index[3] == (((0x1234u >> 5) + 0x200u * 4u) & 0xff));
}

TEST("hold leaves everything alone") {
  RngState state = ramp_state();
  state.index = {1, 2, 3, 4};
  state.reseed_counter = 77;
  const RngState start = state;
  rng_reseed(state, 0x1234, true);
  CHECK(std::memcmp(&state, &start, sizeof state) == 0);
}

TEST("the counter wraps at 32 bits") {
  RngState state;
  state.reseed_counter = 0xffffffffu;
  rng_reseed(state, 0, false);
  CHECK(state.reseed_counter == 0);
  CHECK(state.index[0] == 0);
}

TEST("a copied state continues identically") {
  RngState state = ramp_state();
  rng_reseed(state, 500, false);
  RngState snapshot = state;
  std::uint32_t values[100];
  for (std::uint32_t& value : values) {
    value = rng_next(state, 1000);
  }
  for (std::uint32_t value : values) {
    CHECK(rng_next(snapshot, 1000) == value);
  }
  CHECK(std::memcmp(&state, &snapshot, sizeof state) == 0);
}
