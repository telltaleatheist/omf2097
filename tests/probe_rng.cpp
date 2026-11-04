// Runs generator operations from stdin for tests/differential/test_rng.py.
//   load <path>                       table from a 256-byte file
//   set <i0> <i1> <i2> <i3> <counter> index and counter
//   next <range>                      prints: value i0 i1 i2 i3 counter
//   reseed <frame> <hold>             prints: i0 i1 i2 i3 counter
//   table                             prints the table as hex
#include <cstdio>
#include <cstring>

#include "logic/rng.h"

int main() {
  omf::RngState state;
  char op[16];
  char path[4096];
  while (std::scanf("%15s", op) == 1) {
    const auto print_state = [&state] {
      std::printf("%u %u %u %u %u\n", state.index[0], state.index[1], state.index[2], state.index[3],
                  state.reseed_counter);
    };
    if (!std::strcmp(op, "load")) {
      if (std::scanf(" %4095[^\n]", path) != 1) return 2;
      std::FILE* file = std::fopen(path, "rb");
      if (!file || std::fread(state.table.data(), 1, state.table.size(), file) != state.table.size()) return 2;
      std::fclose(file);
    } else if (!std::strcmp(op, "set")) {
      unsigned i0, i1, i2, i3, counter;
      if (std::scanf("%u %u %u %u %u", &i0, &i1, &i2, &i3, &counter) != 5) return 2;
      state.index = {static_cast<std::uint8_t>(i0), static_cast<std::uint8_t>(i1), static_cast<std::uint8_t>(i2),
                     static_cast<std::uint8_t>(i3)};
      state.reseed_counter = counter;
    } else if (!std::strcmp(op, "next")) {
      int range;
      if (std::scanf("%d", &range) != 1) return 2;
      const std::uint32_t value = omf::rng_next(state, range);
      std::printf("%u ", value);
      print_state();
    } else if (!std::strcmp(op, "reseed")) {
      unsigned frame, hold;
      if (std::scanf("%u %u", &frame, &hold) != 2) return 2;
      omf::rng_reseed(state, frame, hold != 0);
      print_state();
    } else if (!std::strcmp(op, "table")) {
      for (std::uint8_t byte : state.table) std::printf("%02x", byte);
      std::printf("\n");
    } else {
      return 2;
    }
  }
  return 0;
}
