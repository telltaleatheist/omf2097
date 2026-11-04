// Behaviour on a made-up sprite. tests/differential/test_compositor.py checks against the original.
#include <cstdint>
#include <cstring>
#include <vector>

#include "check.h"
#include "logic/compositor.h"

using namespace omf;

namespace {

// Two rows at y 0 and 1, two pixels each at column 1.
DrawData make_data() {
  DrawData data;
  const std::vector<std::uint8_t> c = {
      2,          0,  // y 0
      1 << 2,     0,  // x 1
      (2 << 2) | 1, 0, 0x11, 0x12,
      (1 << 2) | 2, 0,  // y 1
      1 << 2,     0,
      (2 << 2) | 1, 0, 0x21, 0x22,
      3,          0,
  };
  data.pixels = c;
  SpriteRecord s;
  s.x = 0;
  s.y = 0;
  s.width = 3;
  s.height = 2;
  s.length = static_cast<std::uint16_t>(c.size());
  s.offset = 0;
  s.has_data = true;
  data.sprites.push_back(s);
  for (std::size_t row = 0; row < kTableRows; ++row) {
    for (std::size_t i = 0; i < 256; ++i) data.tables[row * 256 + i] = static_cast<std::uint8_t>(i);
  }
  return data;
}

std::uint8_t at(const CompositorState& s, int x, int y) {
  return s.buffer[static_cast<std::size_t>(y * kScreenWidth + x)];
}

QueueRequest request(int layer, int x, int y) {
  QueueRequest r;
  r.layer = layer;
  r.x = x;
  r.y = y;
  r.sprite = 1;
  return r;
}

void hud_marks(void* context, CompositorState& state) {
  *static_cast<int*>(context) = state.buffer[0];
}

}  // namespace

TEST("a plain sprite lands at its position, and clipping stops at the edges") {
  static CompositorState state;
  const DrawData data = make_data();
  queue_add(state.queue, data, request(20, 10, 10));
  queue_add(state.queue, data, request(21, -1, 0));
  queue_add(state.queue, data, request(22, 318, 199));
  compose(state, data, ComposeHooks{});
  CHECK(at(state, 11, 10) == 0x11);
  CHECK(at(state, 12, 11) == 0x22);
  CHECK(at(state, 0, 0) == 0x11);
  CHECK(at(state, 319, 199) == 0x11);
  CHECK(at(state, 0, 1) == 0x21);
}

TEST("later layers draw over earlier ones, and the HUD hook runs at layer 15") {
  static CompositorState state;
  const DrawData data = make_data();
  QueueRequest low = request(3, -1, 0);
  queue_add(state.queue, data, low);
  QueueRequest high = request(30, -1, 0);
  high.flags = kShiftColours;
  queue_add(state.queue, data, high);
  int seen = -1;
  ComposeHooks hooks;
  hooks.context = &seen;
  hooks.hud = hud_marks;
  compose(state, data, hooks);
  CHECK(seen == 0x11);
  CHECK(at(state, 0, 0) == 0x41);
}

TEST("a full layer moves to the next free one") {
  static CompositorState state;
  const DrawData data = make_data();
  CHECK(queue_add(state.queue, data, request(20, 0, 0)) == 20);
  CHECK(queue_add(state.queue, data, request(20, 0, 0)) == 21);
  CHECK(queue_add(state.queue, data, request(0, 0, 0)) == 1);
  queue_next_frame(state.queue);
  CHECK(state.queue.entries[20].sprite == 0);
  CHECK(state.queue.entries[20].previous_sprite == 1);
}

TEST("a snapshot is a plain copy") {
  static CompositorState state;
  static CompositorState copy;
  const DrawData data = make_data();
  queue_add(state.queue, data, request(20, 5, 5));
  copy = state;
  compose(state, data, ComposeHooks{});
  compose(copy, data, ComposeHooks{});
  CHECK(std::memcmp(&state, &copy, sizeof state) == 0);
  std::printf("  CompositorState is %zu bytes\n", sizeof state);
}
