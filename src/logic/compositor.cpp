#include "logic/compositor.h"

#include <cstring>

namespace omf {

namespace {

constexpr int kStride = kScreenWidth;
constexpr int kGroundRow = 0xbe;
constexpr int kDitherStep = 0x6b;

struct Clip {
  int x0, y0, x1, y1;
};

Clip clip_of(const DrawSettings& settings) {
  return {settings.clip_x0, settings.clip_y0, settings.clip_x1, settings.clip_y1};
}

// A sprite is a list of 16-bit commands: low 2 bits the operation, the rest its value.
enum Op { kOpSetX = 0, kOpPixels = 1, kOpSetY = 2, kOpEnd = 3 };

struct Command {
  int op;
  int value;
};

Command read_command(const std::uint8_t* pixels, std::uint32_t at) {
  const unsigned word = pixels[at] | (static_cast<unsigned>(pixels[at + 1]) << 8);
  return {static_cast<int>(word & 3), static_cast<int>(word >> 2)};
}

// Pixels are written only inside the clip window, so a window larger than the screen must
// not reach past the buffer: the original has none, and would corrupt memory.
bool span_in_buffer(int x0, int y, int count) {
  return y >= 0 && y < kScreenHeight && x0 >= 0 && x0 + count <= kScreenWidth;
}

std::uint8_t dither_start(const DrawSettings& settings, int x, int y) {
  return static_cast<std::uint8_t>(settings.buffer_address_low + y * kStride + x);
}

std::uint8_t table_at(const DrawData& data, std::size_t row, std::uint8_t column) {
  // Rows past the known tables are other memory in the original. See docs/formats.md.
  return row < kTableRows ? data.tables[row * 256 + column] : 0;
}

struct Span {
  std::uint8_t* out;
  const std::uint8_t* in;
  int count;
  std::uint8_t dither;
};

void copy_forward(const Span& s, std::uint8_t opacity) {
  if (opacity == 0xff) {
    std::memcpy(s.out, s.in, static_cast<std::size_t>(s.count));
    return;
  }
  std::uint8_t d = s.dither;
  for (int i = 0; i < s.count; ++i, d = static_cast<std::uint8_t>(d + kDitherStep)) {
    if (d <= opacity) s.out[i] = s.in[i];
  }
}

void copy_flipped(const Span& s, std::uint8_t opacity) {
  if (opacity == 0xff) {
    for (int i = 0; i < s.count; ++i) s.out[s.count - 1 - i] = s.in[i];
    return;
  }
  std::uint8_t d = s.dither;
  for (int i = 0; i < s.count; ++i, d = static_cast<std::uint8_t>(d + kDitherStep)) {
    if (d <= opacity) s.out[i] = s.in[s.count - 1 - i];
  }
}

// MASTER.DAT @ 0x5a2b4 (and 0x5a2d8 flipped)
void copy_shifting_colours(const Span& s, bool flipped) {
  for (int i = 0; i < s.count; ++i) {
    std::uint8_t v = s.in[flipped ? s.count - 1 - i : i];
    if (v < 0x30) v = static_cast<std::uint8_t>(v + 0x30);
    s.out[i] = v;
  }
}

// MASTER.DAT @ 0x5a3d0
void add_forward(const Span& s, const CompositorState& state) {
  const DrawSettings& p = state.settings;
  for (int i = 0; i < s.count; ++i) {
    const std::uint8_t src = s.in[i];
    std::uint8_t amount = static_cast<std::uint8_t>(src * p.additive_step);
    if (state.draw.additive_seen != 0) {
      // Measured against an earlier additive sprite: the sum stops at the top of the ramp.
      const std::uint32_t above = static_cast<std::uint32_t>(s.out[i]) - p.additive_base;
      if (above >= p.additive_step && p.additive_step != 0) {
        const std::uint32_t level = above / p.additive_step;
        if (src + level > p.additive_count) {
          amount = static_cast<std::uint8_t>(static_cast<std::uint8_t>(p.additive_count - static_cast<std::uint8_t>(level)) *
                                             p.additive_step);
        }
      }
    }
    s.out[i] = static_cast<std::uint8_t>(s.out[i] + amount);
  }
}

// MASTER.DAT @ 0x5a484: the flipped form does nothing once an additive sprite has been drawn.
void add_flipped(const Span& s, const CompositorState& state) {
  if (state.draw.additive_seen != 0) return;
  for (int i = 0; i < s.count; ++i) {
    s.out[s.count - 1 - i] = static_cast<std::uint8_t>(s.out[s.count - 1 - i] + s.in[i] * state.settings.additive_step);
  }
}

// MASTER.DAT @ 0x5d300 and 0x5d338. The two start one table apart, as in the original.
void blend_lookup(const Span& s, const DrawData& data, bool flipped) {
  for (int i = 0; i < s.count; ++i) {
    const std::uint8_t src = s.in[flipped ? s.count - 1 - i : i];
    const std::size_t row = (flipped ? kRowFlippedBlendBase : kRowBlendBase) + src;
    s.out[i] = table_at(data, row, s.out[i]);
  }
}

// MASTER.DAT @ 0x5a4b8 and 0x5a540
void blend_grey(const Span& s, const DrawData& data, std::uint8_t opacity, bool flipped) {
  std::uint8_t d = s.dither;
  for (int i = 0; i < s.count; ++i, d = static_cast<std::uint8_t>(d + kDitherStep)) {
    if (d > opacity) continue;
    std::uint8_t v = s.in[flipped ? s.count - 1 - i : i];
    if ((v & 0x80) == 0) {
      v = static_cast<std::uint8_t>((table_at(data, kRowGrey, s.out[i]) >> 3) + (v & 0xf0) + ((v & 0x0f) >> 1));
    }
    s.out[i] = v;
  }
}

void remap_span(std::uint8_t* out, int count, const DrawData& data, std::size_t row) {
  for (int i = 0; i < count; ++i) out[i] = table_at(data, row, out[i]);
}

void remap_dithered(std::uint8_t* out, int count, const DrawData& data, std::size_t row, std::uint8_t opacity,
                    std::uint8_t dither) {
  for (int i = 0; i < count; ++i, dither = static_cast<std::uint8_t>(dither + kDitherStep)) {
    if (dither <= opacity) out[i] = table_at(data, row, out[i]);
  }
}

// Works out a run's visible columns. Returns the source pixels to skip.
struct Run {
  int x0, x1, skip;
};

Run clip_run(int origin, int offset, int count, bool flip, const Clip& clip) {
  Run run{};
  if (!flip) {
    run.x0 = origin + offset;
    run.x1 = run.x0 + count;
  } else {
    run.x1 = origin - offset;
    run.x0 = run.x1 - count;
  }
  if (run.x0 < clip.x0) {
    if (!flip) run.skip = clip.x0 - run.x0;
    run.x0 = clip.x0;
  }
  if (run.x1 > clip.x1) {
    if (flip) run.skip = run.x1 - clip.x1;
    run.x1 = clip.x1;
  }
  return run;
}

void set_bbox_x(DrawState& draw, const SpriteRecord& sprite, int x, bool flip, int& origin) {
  if (!flip) {
    draw.bbox_x0 = x + sprite.x;
    draw.bbox_x1 = draw.bbox_x0 + static_cast<std::int16_t>(sprite.width);
    origin = draw.bbox_x0;
  } else {
    draw.bbox_x1 = x + 1 - sprite.x;
    draw.bbox_x0 = draw.bbox_x1 - static_cast<std::int16_t>(sprite.width);
    origin = draw.bbox_x1;
  }
}

// MASTER.DAT @ 0x5aa3c, the plain path
void draw_plain(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  DrawState& draw = state.draw;
  const bool flip_x = (draw.flags & kFlipX) != 0;
  const bool flip_y = (draw.flags & kFlipY) != 0;
  const Clip clip = clip_of(state.settings);
  int origin_x = 0;
  set_bbox_x(draw, sprite, x, flip_x, origin_x);
  int origin_y;
  if (!flip_y) {
    draw.bbox_y0 = y + sprite.y;
    origin_y = draw.bbox_y0;
    draw.bbox_y1 = origin_y + static_cast<std::int16_t>(sprite.height) + 1;
  } else {
    origin_y = y - sprite.y;
    draw.bbox_y0 = origin_y - static_cast<std::int16_t>(sprite.height);
    draw.bbox_y1 = origin_y + 1;
  }
  if (!sprite.has_data) return;

  const std::uint8_t* pixels = data.pixels.data() + sprite.offset;
  std::uint32_t at = 0;
  int column = 0;
  int row = 0;
  while (at < sprite.length) {
    const Command c = read_command(pixels, at);
    at += 2;
    if (c.op == kOpSetX) {
      column = c.value;
    } else if (c.op == kOpPixels) {
      if (row >= clip.y0 && row < clip.y1) {
        const Run run = clip_run(origin_x, column, c.value, flip_x, clip);
        const int count = run.x1 - run.x0;
        if (count > 0 && span_in_buffer(run.x0, row, count)) {
          const Span span{state.buffer.data() + row * kStride + run.x0, pixels + at + run.skip, count, 0};
          if (flip_x) {
            copy_flipped(span, 0xff);
          } else {
            copy_forward(span, 0xff);
          }
        }
      }
      at += static_cast<std::uint32_t>(c.value);
    } else if (c.op == kOpSetY) {
      if (!flip_y) {
        row = origin_y + c.value;
        if (row >= clip.y1) return;
      } else {
        row = origin_y - c.value;
        if (row < clip.y0) return;
      }
      column = 0;
    } else {
      return;
    }
  }
}

// MASTER.DAT @ 0x5aa3c, the path with modes
void draw_with_modes(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  DrawState& draw = state.draw;
  const std::uint16_t flags = draw.flags;
  const bool flip_x = (flags & kFlipX) != 0;
  const bool flip_y = (flags & kFlipY) != 0;
  const bool squash = (flags & kSquash) != 0;
  const Clip clip = clip_of(state.settings);
  const int scale = draw.scale_y;
  const std::uint8_t opacity = draw.opacity;
  int origin_x = 0;
  set_bbox_x(draw, sprite, x, flip_x, origin_x);

  const int height = static_cast<std::int16_t>(sprite.height);
  int origin_y;
  if (!flip_y) {
    if (!squash) {
      draw.bbox_y0 = y + (sprite.y * scale) / 100;
      draw.bbox_y1 = (height * scale) / 100 + draw.bbox_y0 + 3;
      origin_y = draw.bbox_y0;
    } else {
      const int quarter = height >> 2;
      const int scaled = (scale * quarter) / 100;
      draw.bbox_y0 = (y - scaled) + quarter;
      draw.bbox_y1 = scaled + draw.bbox_y0 + 1;
      origin_y = draw.bbox_y0;
    }
  } else if (!squash) {
    origin_y = y - (sprite.y * scale) / 100;
    draw.bbox_y0 = origin_y - (height * scale) / 100;
    draw.bbox_y1 = origin_y + 1;
  } else {
    const int quarter = height >> 2;
    const int scaled = (scale * quarter) / 100;
    origin_y = (y + scaled) - quarter;
    draw.bbox_y0 = origin_y - scaled;
    draw.bbox_y1 = origin_y + 1;
  }
  if (!sprite.has_data) return;

  const std::uint8_t* pixels = data.pixels.data() + sprite.offset;
  std::uint32_t at = 0;
  int column = 0;
  int row = 0;
  bool every_fourth = false;
  while (at < sprite.length) {
    const Command c = read_command(pixels, at);
    const std::uint8_t low_byte = pixels[at];
    at += 2;
    if (c.op == kOpSetX) {
      column = c.value;
    } else if (c.op == kOpPixels) {
      if (row >= clip.y0 && row < clip.y1) {
        const Run run = clip_run(origin_x, column, c.value, flip_x, clip);
        const int count = run.x1 - run.x0;
        if (count > 0 && span_in_buffer(run.x0, row, count)) {
          std::uint8_t* out = state.buffer.data() + row * kStride + run.x0;
          const Span span{out, pixels + at + run.skip, count, dither_start(state.settings, run.x0, row)};
          if (squash) {
            if (every_fourth) {
              if (opacity == 0xff) {
                remap_span(out, count, data, kRowShadow);
              } else {
                remap_dithered(out, count, data, kRowShadow, opacity, span.dither);
              }
            }
          } else if (flags & kBlendGrey) {
            blend_grey(span, data, opacity, flip_x);
          } else if (flags & kBlendLookup) {
            blend_lookup(span, data, flip_x);
          } else if (flags & kAdditive) {
            if (flip_x) {
              add_flipped(span, state);
            } else {
              add_forward(span, state);
            }
          } else if (flags & kShiftColours) {
            copy_shifting_colours(span, flip_x);
          } else if (flip_x) {
            copy_flipped(span, opacity);
          } else {
            copy_forward(span, opacity);
          }
        }
      }
      at += static_cast<std::uint32_t>(c.value);
    } else if (c.op == kOpSetY) {
      int offset = c.value;
      if (!flip_y) {
        if (squash) offset >>= 2;
        if (scale != 100) offset = (scale * c.value) / 100;
        row = origin_y + offset;
        if (row >= clip.y1) return;
      } else {
        if (squash) offset >>= 2;
        offset = -offset;
        if (scale != 100) offset = (scale * -c.value) / 100;
        row = origin_y + offset;
        if (row < clip.y0) return;
      }
      every_fourth = (low_byte & 0x0c) == 0;
      column = 0;
    } else {
      return;
    }
  }
}

// MASTER.DAT @ 0x5a5d8, used with the span routine at 0x5a158
void draw_remapped(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  DrawState& draw = state.draw;
  const std::uint16_t flags = draw.flags;
  const bool flip_x = (flags & kFlipX) != 0;
  const bool flip_y = (flags & kFlipY) != 0;
  const Clip clip = clip_of(state.settings);
  const int scale = draw.scale_y;
  const std::size_t table_row = (flags & kRemapMask) >> kRemapShift;
  int origin_x = 0;
  set_bbox_x(draw, sprite, x, flip_x, origin_x);

  const int height = static_cast<std::int16_t>(sprite.height);
  int origin_y;
  if (!flip_y) {
    draw.bbox_y0 = y + (sprite.y * scale) / 100;
    draw.bbox_y1 = (height * scale) / 100 + draw.bbox_y0 + 3;
    origin_y = draw.bbox_y0;
  } else {
    origin_y = y - (sprite.y * scale) / 100;
    draw.bbox_y0 = origin_y - (height * scale) / 100;
    draw.bbox_y1 = origin_y + 1;
  }
  if (!sprite.has_data) return;

  const std::uint8_t* pixels = data.pixels.data() + sprite.offset;
  std::uint32_t at = 0;
  int column = 0;
  int row = 0;
  while (at < sprite.length) {
    const Command c = read_command(pixels, at);
    at += 2;
    if (c.op == kOpSetX) {
      column = c.value;
    } else if (c.op == kOpPixels) {
      if (row >= clip.y0 && row < clip.y1) {
        const Run run = clip_run(origin_x, column, c.value, flip_x, clip);
        const int count = run.x1 - run.x0;
        if (count > 0 && span_in_buffer(run.x0, row, count)) {
          remap_span(state.buffer.data() + row * kStride + run.x0, count, data, table_row);
        }
      }
      at += static_cast<std::uint32_t>(c.value);
    } else if (c.op == kOpSetY) {
      if (!flip_y) {
        int offset = c.value;
        if (scale != 100) offset = (scale * offset) / 100;
        row = origin_y + offset;
        if (row >= clip.y1) return;
      } else {
        int offset = -c.value;
        if (scale != 100) offset = (offset * scale) / 100;
        row = origin_y + offset;
        if (row < clip.y0) return;
      }
      column = 0;
    } else {
      return;
    }
  }
}

void shadow_bbox_y(DrawState& draw, const SpriteRecord& sprite, int y) {
  const int top = -((kGroundRow - y) >> 2);
  const int height = static_cast<std::int16_t>(sprite.height);
  int low;
  int high;
  if ((draw.flags & kFlipY) == 0) {
    high = -((kGroundRow - (height + y)) >> 2);
    low = top;
  } else {
    low = -((kGroundRow - (y - height)) >> 2);
    high = top;
  }
  draw.bbox_y1 = high + kGroundRow + 1;
  draw.bbox_y0 = low + kGroundRow;
}

// MASTER.DAT @ 0x5bc7c, for levels other than 3: one row in four, darkened
void shadow_simple(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  DrawState& draw = state.draw;
  const bool flip_x = (draw.flags & kFlipX) != 0;
  const bool flip_y = (draw.flags & kFlipY) != 0;
  const Clip clip = clip_of(state.settings);
  const std::uint8_t opacity = draw.opacity;
  int origin;
  int left;
  if (!flip_x) {
    origin = x + sprite.x;
    draw.bbox_x1 = origin + static_cast<std::int16_t>(sprite.width);
    left = origin;
  } else {
    draw.bbox_x1 = x - sprite.x;
    origin = draw.bbox_x1;
    left = draw.bbox_x1 - static_cast<std::int16_t>(sprite.width);
  }
  draw.bbox_x0 = left - 1;

  if (sprite.has_data && sprite.length != 0) {
    const std::uint8_t* pixels = data.pixels.data() + sprite.offset;
    std::uint32_t at = 0;
    int column = 0;
    int row = 0;
    bool visible = false;
    while (at < sprite.length) {
      const Command c = read_command(pixels, at);
      at += 2;
      if (c.op == kOpSetX) {
        column = c.value;
      } else if (c.op == kOpPixels) {
        if (row >= clip.y0 && row < clip.y1) {
          const Run run = clip_run(origin, column, c.value, flip_x, clip);
          const int count = run.x1 - run.x0;
          if (count > 0 && visible && span_in_buffer(run.x0, row, count)) {
            std::uint8_t* out = state.buffer.data() + row * kStride + run.x0;
            if (opacity == 0xff) {
              remap_span(out, count, data, kRowShadow);
            } else {
              remap_dithered(out, count, data, kRowShadow, opacity, dither_start(state.settings, run.x0, row));
            }
          }
        }
        at += static_cast<std::uint32_t>(c.value);
      } else if (c.op == kOpSetY) {
        if (!flip_y) {
          row = kGroundRow - ((kGroundRow - (y + c.value)) >> 2);
          if (row >= clip.y1) return;
        } else {
          row = kGroundRow - ((kGroundRow - (y - c.value)) >> 2);
          if (row < clip.y0) return;
        }
        const int source_row = c.value + y;
        visible = source_row == (source_row >> 2) * 4;
        column = 0;
      } else {
        break;
      }
    }
  }
  shadow_bbox_y(draw, sprite, y);
}

// MASTER.DAT @ 0x5a214
void flush_shadow_row(std::uint8_t* out, const std::uint8_t* counts, int count, const DrawData& data,
                      std::uint8_t opacity, std::uint8_t dither) {
  for (int i = 0; i < count; ++i, dither = static_cast<std::uint8_t>(dither + kDitherStep)) {
    if (counts[i] != 0 && (opacity == 0xff || dither <= opacity)) {
      out[i] = table_at(data, counts[i], out[i]);
    }
  }
}

// MASTER.DAT @ 0x5bc7c, level 3: four source rows gather into one, and the count picks the table
void shadow_gathered(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  DrawState& draw = state.draw;
  const bool flip_x = (draw.flags & kFlipX) != 0;
  const bool flip_y = (draw.flags & kFlipY) != 0;
  const Clip clip = clip_of(state.settings);
  const std::uint8_t opacity = draw.opacity;
  int origin;
  if (!flip_x) {
    draw.bbox_x0 = x + sprite.x;
    draw.bbox_x1 = draw.bbox_x0 + static_cast<std::int16_t>(sprite.width);
    origin = draw.bbox_x0;
  } else {
    draw.bbox_x1 = x - sprite.x;
    draw.bbox_x0 = draw.bbox_x1 - static_cast<std::int16_t>(sprite.width);
    origin = draw.bbox_x1;
  }
  const auto bound = [](int v) { return v < 0 ? 0 : (v > kScreenWidth - 1 ? kScreenWidth : v); };
  const int clear_from = bound(draw.bbox_x0);
  const int clear_to = bound(draw.bbox_x1);
  std::array<std::uint8_t, kScreenWidth> counts{};

  if (sprite.has_data && sprite.length != 0) {
    const std::uint8_t* pixels = data.pixels.data() + sprite.offset;
    std::uint32_t at = 0;
    int column = 0;
    int row = 0;
    int low = kScreenWidth;
    int high = 0;
    while (at < sprite.length) {
      const Command c = read_command(pixels, at);
      at += 2;
      if (c.op == kOpSetX) {
        column = c.value;
      } else if (c.op == kOpPixels) {
        if (row >= clip.y0 && row < clip.y1) {
          const Run run = clip_run(origin, column, c.value, flip_x, clip);
          if (run.x1 > run.x0) {
            for (int i = run.x0; i < run.x1; ++i) {
              if (i >= 0 && i < kScreenWidth) counts[static_cast<std::size_t>(i)] = static_cast<std::uint8_t>(counts[static_cast<std::size_t>(i)] + 1);
            }
            if (run.x0 < low) low = run.x0;
            if (high < run.x1) high = run.x1;
          }
        }
        at += static_cast<std::uint32_t>(c.value);
      } else if (c.op == kOpSetY) {
        if (!flip_y) {
          row = kGroundRow - ((kGroundRow - (y + c.value)) >> 2);
          if (row >= clip.y1) return;
        } else {
          row = kGroundRow - ((kGroundRow - (y - c.value)) >> 2);
          if (row < clip.y0) return;
        }
        const int source_row = c.value + y;
        if (source_row == (source_row >> 2) * 4 && high != 0) {
          const int count = high - low;
          if (count > 0 && span_in_buffer(low, row, count)) {
            flush_shadow_row(state.buffer.data() + row * kStride + low, counts.data() + low, count, data, opacity,
                             dither_start(state.settings, low, row));
          }
          high = 0;
          low = kScreenWidth;
          counts = {};
          if (clear_from < clear_to) std::memset(counts.data() + clear_from, 0, static_cast<std::size_t>(clear_to - clear_from));
        }
        column = 0;
      } else {
        break;
      }
    }
  }
  shadow_bbox_y(draw, sprite, y);
}

}  // namespace

// MASTER.DAT @ 0x5aa3c
void draw_sprite(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  if (sprite.width == 0) return;
  const DrawState& draw = state.draw;
  if ((draw.flags & kRemapMask) != 0) {
    draw_remapped(state, data, sprite, x, y);
  } else if ((draw.flags & (kFlipX | kFlipY)) == draw.flags && draw.opacity == 0xff && draw.scale_x == 100 &&
             draw.scale_y == 100) {
    draw_plain(state, data, sprite, x, y);
  } else {
    draw_with_modes(state, data, sprite, x, y);
  }
}

// MASTER.DAT @ 0x5bc7c
void draw_shadow(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y) {
  if (state.settings.shadow_level == 3) {
    shadow_gathered(state, data, sprite, x, y);
  } else {
    shadow_simple(state, data, sprite, x, y);
  }
}

// MASTER.DAT @ 0x5caa0
int queue_add(SpriteQueue& queue, const DrawData& data, const QueueRequest& r) {
  if (r.sprite == 0) return 0;
  auto& entries = queue.entries;
  int start = r.layer == 0 ? 1 : r.layer;
  int slot = start;
  while (slot < kQueueSize && entries[static_cast<std::size_t>(slot)].sprite != 0) ++slot;
  if (slot > kQueueSize - 1) {
    slot = kQueueSize - 1;
    while (slot > 0 && entries[static_cast<std::size_t>(slot)].sprite != 0) --slot;
  }
  if (slot == 0) {
    // Full: take the first entry at or after the layer with no higher priority.
    slot = start;
    if (start < kQueueSize) {
      while (slot < kQueueSize) {
        const QueueEntry& e = entries[static_cast<std::size_t>(slot)];
        if (e.sprite == 0 || ((e.state & 0x7f) >> 3) <= r.priority) break;
        ++slot;
      }
    }
    if (slot > kQueueSize - 1) {
      slot = kQueueSize - 1;
      while (slot > 0) {
        const QueueEntry& e = entries[static_cast<std::size_t>(slot)];
        if (e.sprite == 0 || ((e.state >> 3) & 0x0f) <= r.priority) break;
        --slot;
      }
      if (slot == 0) return 0;
    }
  }

  QueueEntry& e = entries[static_cast<std::size_t>(slot)];
  if (e.scale_x == r.scale_x && e.scale_y == r.scale_y && e.opacity == r.opacity && e.param_a == r.param_a &&
      e.param_b == r.param_b && e.x == r.x && e.y == r.y && e.flags == r.flags && e.previous_sprite == r.sprite) {
    e.state = static_cast<std::uint16_t>(e.state | 2);
  }
  e.state = static_cast<std::uint16_t>((e.state & 0xff87) | ((r.priority & 0xff0f) << 3));
  e.shadow_base = 0;
  e.scale_x = r.scale_x;
  e.scale_y = r.scale_y;
  e.opacity = r.opacity;
  e.param_a = r.param_a;
  e.param_b = r.param_b;
  e.extra = r.extra;

  int y = r.y;
  if ((r.flags & kSquash) != 0 && (r.flags & kText) == 0) {
    const int sprite_y = data.sprites[r.sprite].y;
    if ((r.flags & kFlipY) == 0) {
      y = kGroundRow - ((kGroundRow - (y + sprite_y)) >> 2);
    } else {
      y = kGroundRow - ((kGroundRow - (y - sprite_y)) >> 2);
    }
  }
  e.x = r.x;
  e.sprite = r.sprite;
  e.flags = r.flags;
  e.y = y;
  e.state = static_cast<std::uint16_t>(e.state | 1);
  if ((r.flags & kNewEntry) == 0) {
    e.state = static_cast<std::uint16_t>(e.state & 0xfffb);
  } else {
    e.reserved1 = {};
    e.state = static_cast<std::uint16_t>(e.state | 4);
  }
  return slot;
}

// MASTER.DAT @ 0x5cd48
void queue_next_frame(SpriteQueue& queue) {
  auto& entries = queue.entries;
  if (entries[0].sprite == 0) entries[0].state = static_cast<std::uint16_t>(entries[0].state & 0xfffe);
  for (std::size_t i = 0;; ++i) {
    const std::uint32_t sprite = entries[i].sprite;
    entries[i].sprite = 0;
    entries[i].previous_sprite = sprite;
    if (i + 1 == entries.size()) break;
    if (entries[i + 1].sprite == 0) entries[i + 1].state = static_cast<std::uint16_t>(entries[i + 1].state & 0xfffe);
  }
}

// MASTER.DAT @ 0x5d0a0
void compose(CompositorState& state, const DrawData& data, const ComposeHooks& hooks) {
  DrawState& draw = state.draw;
  draw.additive_seen = 0;
  for (int layer = 0; layer < kQueueSize; ++layer) {
    if (layer == 15 && hooks.hud != nullptr) hooks.hud(hooks.context, state);
    QueueEntry& e = state.queue.entries[static_cast<std::size_t>(layer)];
    if (e.sprite == 0) continue;
    draw.scale_x = e.scale_x;
    draw.scale_y = e.scale_y;
    draw.opacity = e.opacity;
    draw.param_b = e.param_b;
    draw.param_a = e.param_a;
    // Flags of 0xff draw nothing, but the entry still takes the bounding box left over.
    if (e.flags != 0xff) {
      if ((e.flags & kText) == 0) {
        const SpriteRecord& sprite = data.sprites[e.sprite];
        draw.flags = e.flags;
        if ((e.extra & kEntryShadow) != 0 && e.y < 0xbf) {
          // Not the entry's y: queue_add always clears this field, so a shadow ignores height.
          const int base = (e.flags & kFlipY) == 0 ? sprite.y + e.shadow_base : e.shadow_base - sprite.y;
          draw_shadow(state, data, sprite, e.x, base + 0xb2);
          draw.flags = e.flags;
          e.shadow_y0 = draw.bbox_y0;
          e.shadow_y1 = draw.bbox_y1;
        }
        draw_sprite(state, data, sprite, e.x, e.y);
        if ((e.flags & kAdditive) != 0) draw.additive_seen = 1;
      } else if (hooks.text_enabled) {
        if (hooks.text != nullptr) {
          hooks.text(hooks.context, state, e.sprite, e.x, e.y + 1, 0xf8);
          hooks.text(hooks.context, state, e.sprite, e.x + 1, e.y, 0xf8);
          hooks.text(hooks.context, state, e.sprite, e.x, e.y, 0xe7);
        }
        draw.bbox_x1 += 1;
        draw.bbox_y1 += 1;
      }
    }
    e.bbox_x0 = draw.bbox_x0;
    e.bbox_x1 = draw.bbox_x1;
    e.bbox_y0 = draw.bbox_y0;
    e.bbox_y1 = draw.bbox_y1;
  }
}

}  // namespace omf
