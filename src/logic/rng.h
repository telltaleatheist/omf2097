// The fight random number generator. See docs/rng.md.
#pragma once

#include <array>
#include <cstdint>
#include <type_traits>

namespace omf {

// All of the generator's state, so a rollback snapshot is a plain copy. There is no
// padding, so hashing the raw bytes is safe.
struct RngState {
  // RANDOM.DAT. The original never writes it after loading. It stays in the state so the
  // struct stands alone and a state hash catches two machines with different files.
  std::array<std::uint8_t, 256> table{};
  // Read positions in the table, each stepped by its own amount on every draw.
  std::array<std::uint8_t, 4> index{};
  // Mixed into the positions by rng_reseed. The game also sets it directly, usually to
  // the frame number, so it is plain state rather than private to these functions.
  std::uint32_t reseed_counter = 0;
};

static_assert(std::is_trivially_copyable<RngState>::value);
static_assert(std::is_standard_layout<RngState>::value);
static_assert(sizeof(RngState) == 264);

// Draws a number scaled to `range`, then steps the read positions.
std::uint32_t rng_next(RngState& state, std::int32_t range);

// Sets the read positions from `frame` and the counter, after adding one to the counter.
// With `hold` set, nothing changes.
void rng_reseed(RngState& state, std::uint32_t frame, bool hold);

}  // namespace omf
