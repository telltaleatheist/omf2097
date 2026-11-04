#include "assets/formats.h"

#include <algorithm>
#include <cstring>

namespace omf::assets {

namespace {

class Reader {
 public:
  Reader(const std::uint8_t* bytes, std::size_t size, Error& error) : bytes_(bytes), size_(size), error_(error) {}

  bool ok() const { return ok_; }
  std::size_t at() const { return at_; }
  std::size_t size() const { return size_; }
  bool at_end() const { return at_ >= size_; }

  bool fail(const std::string& message) {
    if (ok_) {
      error_ = Error{message, at_};
      ok_ = false;
    }
    return false;
  }

  bool read(void* out, std::size_t count) {
    if (!ok_) return false;
    if (count > size_ - at_) return fail("file ends early");
    if (count != 0) std::memcpy(out, bytes_ + at_, count);
    at_ += count;
    return true;
  }

  const std::uint8_t* take(std::size_t count) {
    if (!ok_) return nullptr;
    if (count > size_ - at_) {
      fail("file ends early");
      return nullptr;
    }
    const std::uint8_t* p = bytes_ + at_;
    at_ += count;
    return p;
  }

  std::uint8_t u8() {
    std::uint8_t v = 0;
    read(&v, 1);
    return v;
  }

  std::uint16_t u16() {
    std::uint8_t b[2] = {};
    read(b, 2);
    return static_cast<std::uint16_t>(b[0] | (b[1] << 8));
  }

  std::uint32_t u32() {
    std::uint8_t b[4] = {};
    read(b, 4);
    return b[0] | (b[1] << 8) | (b[2] << 16) | (static_cast<std::uint32_t>(b[3]) << 24);
  }

 private:
  const std::uint8_t* bytes_;
  std::size_t size_;
  Error& error_;
  std::size_t at_ = 0;
  bool ok_ = true;
};

// Walks the sprite's commands as the draw loop will, so drawing can't read past its data.
bool commands_fit(const std::uint8_t* data, std::size_t length) {
  std::size_t at = 0;
  while (at < length) {
    if (length - at < 2) return false;  // the loop would read a command past the end
    const unsigned word = data[at] | (static_cast<unsigned>(data[at + 1]) << 8);
    at += 2;
    const unsigned op = word & 3;
    if (op == 3) return true;
    if (op == 1) {
      if ((word >> 2) > length - at) return false;
      at += word >> 2;
    }
  }
  return true;
}

// What the loader keeps between sprites while it reads one file (0x8bc78).
struct Sharing {
  bool enabled = false;
  std::array<std::int32_t, 256> first{};
  std::array<std::uint32_t, 256> first_length{};
};

// MASTER.DAT @ 0x5c870, 0x5e198
bool read_sprite(Reader& r, Sharing& sharing, std::uint8_t colour_shift, std::vector<std::uint8_t>& pixels, LoadedSprite& s) {
  s.length = r.u16();
  s.x = static_cast<std::int16_t>(r.u16());
  s.y = static_cast<std::int16_t>(r.u16());
  s.width = r.u16();
  s.height = r.u16();
  s.index = r.u8();
  s.missing = r.u8();
  if (!r.ok()) return false;
  if (!sharing.enabled) s.index = 0;
  if (s.index == 0) s.missing = 0;

  if (s.missing != 0 && sharing.enabled) {
    const std::int32_t source = sharing.first[s.index];
    if (source >= 0 && s.length > sharing.first_length[s.index]) return r.fail("shared sprite is longer than its source");
    s.pixel_offset = source;
    return true;
  }

  const std::uint8_t* data = r.take(s.length);
  if (data == nullptr) return false;
  // Width 0 isn't drawn. CREDITS.BK stores 768-byte palettes this way.
  if (s.width != 0 && !commands_fit(data, s.length)) return r.fail("sprite pixel run passes its data");

  if (s.index != 0 && sharing.enabled && sharing.first[s.index] >= 0) {
    // Same index as an earlier sprite: the loader discards this copy and uses that one.
    if (s.length > sharing.first_length[s.index]) return r.fail("shared sprite is longer than its source");
    s.pixel_offset = sharing.first[s.index];
    s.missing = 1;
    return true;
  }

  s.pixel_offset = static_cast<std::int32_t>(pixels.size());
  pixels.insert(pixels.end(), data, data + s.length);
  if (colour_shift != 0) {
    std::size_t at = static_cast<std::size_t>(s.pixel_offset);
    const std::size_t end = at + s.length;
    while (at + 2 <= end) {
      const unsigned word = pixels[at] | (static_cast<unsigned>(pixels[at + 1]) << 8);
      at += 2;
      if ((word & 3) == 1) {
        const std::size_t count = std::min<std::size_t>(word >> 2, end - at);
        for (std::size_t i = 0; i < count; ++i) {
          if (pixels[at + i] < 0x60) pixels[at + i] = static_cast<std::uint8_t>(pixels[at + i] + colour_shift);
        }
        at += count;
      }
    }
  }
  if (sharing.enabled) {
    sharing.first[s.index] = s.pixel_offset;
    sharing.first_length[s.index] = s.length;
  }
  return true;
}

bool read_counted_string(Reader& r, std::string& out) {
  const std::size_t length = r.u16();
  const std::uint8_t* p = r.take(length + 1);
  if (p == nullptr) return false;
  if (p[length] != 0) return r.fail("string is not terminated");
  out.assign(reinterpret_cast<const char*>(p), length);
  return true;
}

// MASTER.DAT @ 0x21090
bool read_animation(Reader& r, Sharing& sharing, std::uint8_t colour_shift, std::vector<std::uint8_t>& pixels, Animation& a) {
  if (!r.read(a.header.data(), a.header.size())) return false;
  const std::size_t coordinates = a.header[8] | (a.header[9] << 8);
  const std::size_t sprites = a.header[10];
  a.coordinates.resize(coordinates);
  for (auto& c : a.coordinates) c = r.u32();
  if (!read_counted_string(r, a.script)) return false;
  const std::size_t extras = r.u8();
  a.extra_strings.resize(extras);
  for (auto& s : a.extra_strings) {
    if (!read_counted_string(r, s)) return false;
  }
  a.sprites.resize(sprites);
  for (auto& s : a.sprites) {
    if (!read_sprite(r, sharing, colour_shift, pixels, s)) return false;
  }
  return r.ok();
}

void reset(Sharing& sharing, bool enabled) {
  sharing.enabled = enabled;
  sharing.first.fill(-1);
  sharing.first_length.fill(0);
}

}  // namespace

// MASTER.DAT @ 0x281b0
bool parse_bk(const std::uint8_t* bytes, std::size_t size, BkFile& out, Error& error) {
  Reader r(bytes, size, error);
  out = BkFile{};
  out.file_id = r.u32();
  out.unknown = r.u8();
  out.width = r.u16();
  out.height = r.u16();
  // This loader turns sprite sharing off.
  Sharing sharing;
  reset(sharing, false);
  while (r.ok()) {
    if (r.at_end()) return r.fail("no end of animations");
    const std::uint32_t next = r.u32();
    const std::uint8_t id = r.u8();
    if (!r.ok() || id >= 50) break;
    BkAnimation animation;
    animation.id = id;
    if (!r.read(animation.settings.data(), 6)) break;
    const std::uint8_t stored = r.u8();
    animation.settings[6] = stored;
    const std::size_t extra = r.u16();
    const std::uint8_t* text = r.take(extra);
    if (text == nullptr) break;
    animation.extra.assign(reinterpret_cast<const char*>(text), extra);
    if (!read_animation(r, sharing, 0, out.pixels, animation.animation)) break;
    if (next != r.at()) return r.fail("animation does not end where its header says");
    out.animations.push_back(std::move(animation));
  }
  if (!r.ok()) return false;
  const std::size_t area = static_cast<std::size_t>(out.width) * out.height;
  const std::uint8_t* background = r.take(area);
  if (background == nullptr) return false;
  out.background.assign(background, background + area);
  const std::size_t palettes = r.u8();
  out.palettes.resize(palettes);
  for (auto& p : out.palettes) {
    r.read(p.colours.data(), p.colours.size());
    for (auto& t : p.remap) r.read(t.data(), t.size());
  }
  r.read(out.footer.data(), out.footer.size());
  if (!r.ok()) return false;
  if (!r.at_end()) return r.fail("data after the end of the file");
  return true;
}

// MASTER.DAT @ 0x1b2d0
bool parse_af(const std::uint8_t* bytes, std::size_t size, std::uint8_t colour_shift, AfFile& out, Error& error) {
  Reader r(bytes, size, error);
  out = AfFile{};
  r.read(out.header.data(), out.header.size());
  Sharing sharing;
  reset(sharing, true);
  while (r.ok()) {
    if (r.at_end()) return r.fail("no end of moves");
    const std::uint8_t id = r.u8();
    if (!r.ok() || id >= 70) break;
    sharing.enabled = !(id == 12 || id == 13 || id == 14);
    AfMove move;
    move.id = id;
    if (!read_animation(r, sharing, colour_shift, out.pixels, move.animation)) break;
    r.read(move.settings.data(), move.settings.size());
    const std::size_t extra = r.u16();
    if (extra != 0) {
      const std::uint8_t* text = r.take(extra);
      if (text == nullptr) break;
      move.extra.assign(reinterpret_cast<const char*>(text), extra);
    }
    out.moves.push_back(std::move(move));
  }
  if (!r.ok()) return false;
  r.read(out.footer.data(), out.footer.size());
  if (!r.ok()) return false;
  if (!r.at_end()) return r.fail("data after the end of the file");
  return true;
}

std::uint32_t add_pixels(DrawData& data, const std::vector<std::uint8_t>& pixels) {
  const std::uint32_t base = static_cast<std::uint32_t>(data.pixels.size());
  data.pixels.insert(data.pixels.end(), pixels.begin(), pixels.end());
  return base;
}

std::uint32_t add_sprites(DrawData& data, std::uint32_t pixel_base, const Animation& animation) {
  const std::uint32_t first = static_cast<std::uint32_t>(data.sprites.size());
  for (const LoadedSprite& s : animation.sprites) {
    SpriteRecord record;
    record.x = s.x;
    record.y = s.y;
    record.width = s.width;
    record.height = s.height;
    record.length = s.length;
    // Width 0 means the data isn't commands (see read_sprite), so nothing may walk it.
    record.has_data = s.pixel_offset >= 0 && s.width != 0;
    record.offset = record.has_data ? pixel_base + static_cast<std::uint32_t>(s.pixel_offset) : 0;
    data.sprites.push_back(record);
  }
  return first;
}

bool set_tables(DrawData& data, const BkFile& file, std::size_t palette, Error& error) {
  if (palette >= file.palettes.size()) {
    error = Error{"no such palette", 0};
    return false;
  }
  const Palette& p = file.palettes[palette];
  data.tables.fill(0);
  auto row = [&data](std::size_t n) { return data.tables.data() + n * 256; };
  for (std::size_t i = 0; i < 4; ++i) std::memcpy(row(1 + i), p.remap[i].data(), 256);
  for (std::size_t i = 4; i < 19; ++i) std::memcpy(row(7 + i - 4), p.remap[i].data(), 256);
  std::memcpy(row(22), p.colours.data(), p.colours.size());
  // MASTER.DAT @ 0x56ddc
  for (std::size_t i = 0; i < 256; ++i) {
    const unsigned sum = p.colours[i * 3] + p.colours[i * 3 + 1] + p.colours[i * 3 + 2];
    row(kRowGrey)[i] = static_cast<std::uint8_t>(sum / 3);
  }
  return true;
}

}  // namespace omf::assets
