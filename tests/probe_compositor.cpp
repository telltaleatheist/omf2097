// Runs the formats and compositor from stdin for the differential tests.
//   af <path> <colour shift>            prints: sprites added, first index
//   bk <path>                           same, and keeps the file for "tables" and "background"
//   tables <palette>
//   sprites                             prints every sprite record and a checksum of its data
//   reset <text enabled> <hud pixels>
//   clear                               an empty queue
//   settings <x0> <y0> <x1> <y1> <step> <count> <base> <level> <address low>
//   draw <flags> <sx> <sy> <opacity> <b> <a> <x0> <x1> <y0> <y1> <additive seen>
//   background | fill <seed>
//   add <layer> <x> <y> <sprite> <flags> <sx> <sy> <opacity> <a> <b> <priority> <extra>   prints: slot
//   compose | next
//   dump                                prints the buffer in hex, the draw state and the queue
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "assets/formats.h"
#include "logic/compositor.h"

namespace {

std::vector<std::uint8_t> read_file(const std::string& path) {
  std::vector<std::uint8_t> bytes;
  std::FILE* file = std::fopen(path.c_str(), "rb");
  if (!file) return bytes;
  std::fseek(file, 0, SEEK_END);
  bytes.resize(static_cast<std::size_t>(std::ftell(file)));
  std::fseek(file, 0, SEEK_SET);
  if (std::fread(bytes.data(), 1, bytes.size(), file) != bytes.size()) bytes.clear();
  std::fclose(file);
  return bytes;
}

void hud_marker(void* context, omf::CompositorState& state) {
  const int pixels = *static_cast<int*>(context);
  for (int i = 0; i < pixels; ++i) {
    std::uint8_t& p = state.buffer[static_cast<std::size_t>(100 * omf::kScreenWidth + 150 + i)];
    p = static_cast<std::uint8_t>(p + 7);
  }
}

std::uint32_t checksum(const std::uint8_t* bytes, std::size_t size) {
  std::uint32_t h = 2166136261u;
  for (std::size_t i = 0; i < size; ++i) h = (h ^ bytes[i]) * 16777619u;
  return h;
}

}  // namespace

int main() {
  static omf::DrawData data;
  static omf::CompositorState state;
  static omf::assets::BkFile bk;
  int hud_pixels = 0;
  omf::ComposeHooks hooks;
  hooks.context = &hud_pixels;
  hooks.hud = hud_marker;
  char op[32];
  char path[4096];
  while (std::scanf("%31s", op) == 1) {
    if (!std::strcmp(op, "af") || !std::strcmp(op, "bk")) {
      const bool is_bk = op[0] == 'b';
      int shift = 0;
      if (is_bk) {
        if (std::scanf(" %4095[^\n]", path) != 1) return 2;
      } else if (std::scanf(" %d %4095[^\n]", &shift, path) != 2) {
        return 2;
      }
      const auto bytes = read_file(path);
      omf::assets::Error error;
      std::uint32_t first = static_cast<std::uint32_t>(data.sprites.size());
      if (is_bk) {
        if (!omf::assets::parse_bk(bytes.data(), bytes.size(), bk, error)) {
          std::printf("error %zu %s\n", error.offset, error.message.c_str());
          continue;
        }
        const std::uint32_t base = omf::assets::add_pixels(data, bk.pixels);
        for (const auto& a : bk.animations) omf::assets::add_sprites(data, base, a.animation);
      } else {
        omf::assets::AfFile af;
        if (!omf::assets::parse_af(bytes.data(), bytes.size(), static_cast<std::uint8_t>(shift), af, error)) {
          std::printf("error %zu %s\n", error.offset, error.message.c_str());
          continue;
        }
        const std::uint32_t base = omf::assets::add_pixels(data, af.pixels);
        for (const auto& m : af.moves) omf::assets::add_sprites(data, base, m.animation);
      }
      std::printf("ok %zu %u\n", data.sprites.size() - first, first);
    } else if (!std::strcmp(op, "tables")) {
      int palette;
      if (std::scanf("%d", &palette) != 1) return 2;
      omf::assets::Error error;
      if (!omf::assets::set_tables(data, bk, static_cast<std::size_t>(palette), error)) return 3;
    } else if (!std::strcmp(op, "sprites")) {
      for (std::size_t i = 1; i < data.sprites.size(); ++i) {
        const omf::SpriteRecord& s = data.sprites[i];
        std::printf("%d %d %u %u %u %u %u\n", s.x, s.y, s.width, s.height, s.length, s.has_data ? 1 : 0,
                    s.has_data ? checksum(data.pixels.data() + s.offset, s.length) : 0);
      }
    } else if (!std::strcmp(op, "reset")) {
      int text;
      if (std::scanf("%d %d", &text, &hud_pixels) != 2) return 2;
      hooks.text_enabled = text != 0;
    } else if (!std::strcmp(op, "clear")) {
      state.queue = omf::SpriteQueue{};
    } else if (!std::strcmp(op, "settings")) {
      int v[9];
      for (int& x : v) {
        if (std::scanf("%d", &x) != 1) return 2;
      }
      omf::DrawSettings& s = state.settings;
      s.clip_x0 = static_cast<std::int16_t>(v[0]);
      s.clip_y0 = static_cast<std::int16_t>(v[1]);
      s.clip_x1 = static_cast<std::int16_t>(v[2]);
      s.clip_y1 = static_cast<std::int16_t>(v[3]);
      s.additive_step = static_cast<std::uint8_t>(v[4]);
      s.additive_count = static_cast<std::uint8_t>(v[5]);
      s.additive_base = static_cast<std::uint8_t>(v[6]);
      s.shadow_level = static_cast<std::uint8_t>(v[7]);
      s.buffer_address_low = static_cast<std::uint8_t>(v[8]);
    } else if (!std::strcmp(op, "draw")) {
      int v[11];
      for (int& x : v) {
        if (std::scanf("%d", &x) != 1) return 2;
      }
      omf::DrawState& d = state.draw;
      d.flags = static_cast<std::uint16_t>(v[0]);
      d.scale_x = static_cast<std::uint8_t>(v[1]);
      d.scale_y = static_cast<std::uint8_t>(v[2]);
      d.opacity = static_cast<std::uint8_t>(v[3]);
      d.param_b = static_cast<std::uint8_t>(v[4]);
      d.param_a = static_cast<std::uint8_t>(v[5]);
      d.bbox_x0 = v[6];
      d.bbox_x1 = v[7];
      d.bbox_y0 = v[8];
      d.bbox_y1 = v[9];
      d.additive_seen = static_cast<std::uint8_t>(v[10]);
    } else if (!std::strcmp(op, "background")) {
      if (bk.background.size() != state.buffer.size()) return 3;
      std::memcpy(state.buffer.data(), bk.background.data(), state.buffer.size());
    } else if (!std::strcmp(op, "fill")) {
      unsigned seed;
      if (std::scanf("%u", &seed) != 1) return 2;
      for (std::uint8_t& p : state.buffer) {
        seed = seed * 1103515245u + 12345u;
        p = static_cast<std::uint8_t>(seed >> 16);
      }
    } else if (!std::strcmp(op, "add")) {
      int v[12];
      for (int& x : v) {
        if (std::scanf("%d", &x) != 1) return 2;
      }
      omf::QueueRequest r;
      r.layer = v[0];
      r.x = v[1];
      r.y = v[2];
      r.sprite = static_cast<std::uint32_t>(v[3]);
      r.flags = static_cast<std::uint16_t>(v[4]);
      r.scale_x = static_cast<std::uint8_t>(v[5]);
      r.scale_y = static_cast<std::uint8_t>(v[6]);
      r.opacity = static_cast<std::uint8_t>(v[7]);
      r.param_a = static_cast<std::uint8_t>(v[8]);
      r.param_b = static_cast<std::uint8_t>(v[9]);
      r.priority = static_cast<std::uint8_t>(v[10]);
      r.extra = static_cast<std::uint32_t>(v[11]);
      std::printf("%d\n", omf::queue_add(state.queue, data, r));
    } else if (!std::strcmp(op, "compose")) {
      omf::compose(state, data, hooks);
    } else if (!std::strcmp(op, "next")) {
      omf::queue_next_frame(state.queue);
    } else if (!std::strcmp(op, "dump")) {
      for (std::uint8_t p : state.buffer) std::printf("%02x", p);
      const omf::DrawState& d = state.draw;
      std::printf("\n%u %u %u %u %u %u %d %d %d %d %u\n", d.flags, d.scale_x, d.scale_y, d.opacity, d.param_b, d.param_a,
                  d.bbox_x0, d.bbox_x1, d.bbox_y0, d.bbox_y1, d.additive_seen);
      for (const omf::QueueEntry& e : state.queue.entries) {
        std::printf("%u %u %d %d %d %d %d %d %d %d %u %u %u %u %u %u %u %u\n", e.state, e.extra, e.x, e.y, e.bbox_x0, e.bbox_x1,
                    e.bbox_y0, e.bbox_y1, e.shadow_y0, e.shadow_y1, e.flags, e.scale_x, e.scale_y, e.opacity, e.param_b, e.param_a,
                    e.previous_sprite, e.sprite);
      }
    } else {
      return 2;
    }
  }
  return 0;
}
