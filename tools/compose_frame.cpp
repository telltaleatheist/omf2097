// Composes an arena and a fighter frame through the port, and writes a PNG, for checking by eye.
// usage: compose_frame <game dir> <arena 0-4> <fighter 0-10> <move> <frame> <x> <y> <flip 0|1> <shadow level> <out.png>
// Colours are the arena file's palette. The game replaces fighter colours at run time, from the pilot,
// which isn't done here, so fighters may look off-colour.
#include <cstdio>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <memory>
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

std::uint32_t crc_of(const std::uint8_t* data, std::size_t size, std::uint32_t crc = 0xffffffffu) {
  for (std::size_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
  }
  return crc;
}

void put_u32(std::vector<std::uint8_t>& out, std::uint32_t v) {
  for (int shift = 24; shift >= 0; shift -= 8) out.push_back(static_cast<std::uint8_t>(v >> shift));
}

void put_chunk(std::vector<std::uint8_t>& out, const char* type, const std::vector<std::uint8_t>& body) {
  put_u32(out, static_cast<std::uint32_t>(body.size()));
  const std::size_t start = out.size();
  out.insert(out.end(), type, type + 4);
  out.insert(out.end(), body.begin(), body.end());
  put_u32(out, crc_of(out.data() + start, out.size() - start) ^ 0xffffffffu);
}

bool write_png(const std::string& path, const std::uint8_t* pixels, const std::array<std::uint8_t, 768>& colours) {
  const int w = omf::kScreenWidth;
  const int h = omf::kScreenHeight;
  std::vector<std::uint8_t> raw;
  raw.reserve(static_cast<std::size_t>((w * 3 + 1) * h));
  for (int y = 0; y < h; ++y) {
    raw.push_back(0);
    for (int x = 0; x < w; ++x) {
      const std::size_t c = pixels[y * w + x];
      for (std::size_t i = 0; i < 3; ++i) raw.push_back(static_cast<std::uint8_t>(colours[c * 3 + i] * 255 / 63));
    }
  }
  std::vector<std::uint8_t> z = {0x78, 0x01};  // stored, not compressed
  std::uint32_t a = 1, b = 0;
  for (std::uint8_t v : raw) {
    a = (a + v) % 65521;
    b = (b + a) % 65521;
  }
  for (std::size_t at = 0; at < raw.size();) {
    const std::size_t n = std::min<std::size_t>(raw.size() - at, 65535);
    z.push_back(at + n == raw.size() ? 1 : 0);
    z.push_back(static_cast<std::uint8_t>(n));
    z.push_back(static_cast<std::uint8_t>(n >> 8));
    z.push_back(static_cast<std::uint8_t>(~n));
    z.push_back(static_cast<std::uint8_t>(~n >> 8));
    z.insert(z.end(), raw.begin() + static_cast<long>(at), raw.begin() + static_cast<long>(at + n));
    at += n;
  }
  put_u32(z, (b << 16) | a);
  std::vector<std::uint8_t> out = {0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a};
  std::vector<std::uint8_t> head;
  put_u32(head, static_cast<std::uint32_t>(w));
  put_u32(head, static_cast<std::uint32_t>(h));
  head.insert(head.end(), {8, 2, 0, 0, 0});
  put_chunk(out, "IHDR", head);
  put_chunk(out, "IDAT", z);
  put_chunk(out, "IEND", {});
  std::FILE* file = std::fopen(path.c_str(), "wb");
  if (!file) return false;
  const bool ok = std::fwrite(out.data(), 1, out.size(), file) == out.size();
  std::fclose(file);
  return ok;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 11) {
    std::fprintf(stderr, "usage: compose_frame <game dir> <arena> <fighter> <move> <frame> <x> <y> <flip> <shadow level> <out.png>\n");
    return 2;
  }
  const std::string game = argv[1];
  const std::string arena = game + "/ARENA" + argv[2] + ".BK";
  const std::string fighter = game + "/FIGHTR" + argv[3] + ".AF";
  const int move = std::atoi(argv[4]);
  const std::size_t frame = static_cast<std::size_t>(std::atoi(argv[5]));
  omf::assets::Error error;
  auto bk = std::make_unique<omf::assets::BkFile>();
  const auto bk_bytes = read_file(arena);
  if (!omf::assets::parse_bk(bk_bytes.data(), bk_bytes.size(), *bk, error)) {
    std::fprintf(stderr, "%s: %s at %zu\n", arena.c_str(), error.message.c_str(), error.offset);
    return 1;
  }
  omf::assets::AfFile af;
  const auto af_bytes = read_file(fighter);
  if (!omf::assets::parse_af(af_bytes.data(), af_bytes.size(), 0, af, error)) {
    std::fprintf(stderr, "%s: %s at %zu\n", fighter.c_str(), error.message.c_str(), error.offset);
    return 1;
  }
  auto data = std::make_unique<omf::DrawData>();
  if (!omf::assets::set_tables(*data, *bk, 0, error)) return 1;
  const std::uint32_t base = omf::assets::add_pixels(*data, af.pixels);
  std::uint32_t sprite = 0;
  for (const auto& m : af.moves) {
    if (m.id == move && frame < m.animation.sprites.size()) {
      sprite = omf::assets::add_sprites(*data, base, m.animation) + static_cast<std::uint32_t>(frame);
    }
  }
  if (sprite == 0) {
    std::fprintf(stderr, "no move %d frame %zu in %s\n", move, frame, fighter.c_str());
    return 1;
  }
  auto state = std::make_unique<omf::CompositorState>();
  std::copy(bk->background.begin(), bk->background.end(), state->buffer.begin());
  state->settings.shadow_level = static_cast<std::uint8_t>(std::atoi(argv[9]));
  omf::QueueRequest r;
  r.layer = 0x1e;
  r.x = std::atoi(argv[6]);
  r.y = std::atoi(argv[7]);
  r.sprite = sprite;
  r.flags = std::atoi(argv[8]) != 0 ? omf::kFlipX : 0;
  r.extra = state->settings.shadow_level != 0 ? omf::kEntryShadow : 0;
  omf::queue_add(state->queue, *data, r);
  omf::compose(*state, *data, omf::ComposeHooks{});
  if (!write_png(argv[10], state->buffer.data(), bk->palettes[0].colours)) return 1;
  std::printf("%s: move %d frame %zu, %zu bytes of state\n", argv[10], move, frame, sizeof(omf::CompositorState));
  return 0;
}
