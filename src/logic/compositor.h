// The indexed compositor: the sprite queue and the 320x200 picture hit tests read.
// See docs/fight-loop.md and docs/formats.md.
#pragma once

#include <array>
#include <cstdint>
#include <type_traits>

#include "logic/draw_data.h"

namespace omf {

inline constexpr int kScreenWidth = 320;
inline constexpr int kScreenHeight = 200;
inline constexpr int kQueueSize = 220;

// Draw flags (entry flags, and 0x8e494 while drawing).
enum DrawFlag : std::uint16_t {
  kFlipX = 0x0001,
  kFlipY = 0x0004,
  kNewEntry = 0x0008,
  kSquash = 0x0010,  // ground-plane remap, drawn on every fourth row
  kRemapShift = 5,   // 3 bits: a remap table row
  kRemapMask = 0x00e0,
  kBlendLookup = 0x0100,
  kAdditive = 0x0200,
  kBlendGrey = 0x0400,
  kShiftColours = 0x0800,
  kText = 0x2000,
};

inline constexpr std::uint32_t kEntryShadow = 0x1000;  // in QueueEntry::extra

struct QueueEntry {
  std::uint16_t state = 0;  // bit 0 in use, bit 1 unchanged from last frame, bit 2 new, bits 3-6 priority
  std::uint16_t pad0 = 0;
  std::int32_t shadow_base = 0;
  std::uint32_t extra = 0;
  std::int32_t x = 0;
  std::int32_t y = 0;
  std::int32_t bbox_x0 = 0;
  std::int32_t bbox_x1 = 0;
  std::int32_t bbox_y0 = 0;
  std::int32_t bbox_y1 = 0;
  std::array<std::uint32_t, 4> reserved1{};
  std::int32_t shadow_y0 = 0;
  std::int32_t shadow_y1 = 0;
  std::array<std::uint32_t, 2> reserved2{};
  std::uint16_t flags = 0;
  std::uint8_t scale_x = 0;
  std::uint8_t scale_y = 0;
  std::uint8_t opacity = 0;
  std::uint8_t param_b = 0;
  std::uint8_t param_a = 0;
  std::uint8_t pad1 = 0;
  std::uint32_t previous_sprite = 0;
  std::uint32_t sprite = 0;  // index into DrawData::sprites, or a text id with kText; 0 is empty
};

struct SpriteQueue {
  std::array<QueueEntry, kQueueSize> entries{};
};

// What the routines leave behind in globals (0x8e494, 0x8e4a4-0x8e4b0, 0x8e4c4-0x8e4c8, 0x8b951).
struct DrawState {
  std::uint16_t flags = 0;
  std::uint8_t scale_x = 100;
  std::uint8_t scale_y = 100;
  std::uint8_t opacity = 0xff;
  std::uint8_t param_b = 0xff;
  std::uint8_t param_a = 0xff;
  std::uint8_t additive_seen = 0;
  std::int32_t bbox_x0 = 0;
  std::int32_t bbox_x1 = 0;
  std::int32_t bbox_y0 = 0;
  std::int32_t bbox_y1 = 0;
};

// Inputs set elsewhere in the game.
struct DrawSettings {
  std::int16_t clip_x0 = 0;       // 0x8e49c
  std::int16_t clip_y0 = 0;       // 0x8e49e
  std::int16_t clip_x1 = 320;     // 0x8e4a0
  std::int16_t clip_y1 = 200;     // 0x8e4a2
  std::uint8_t additive_step = 1;   // 0x8b948
  std::uint8_t additive_count = 0;  // 0x8b949
  std::uint8_t additive_base = 0;   // 0x8b950
  std::uint8_t shadow_level = 0;    // bits 2-3 of 0x8e5e2
  // The dither pattern starts from the low byte of the pixel's memory address in the
  // original, so it depends on where the back buffer was allocated. See docs/formats.md.
  std::uint8_t buffer_address_low = 0;
  std::array<std::uint8_t, 3> pad{};
};

struct CompositorState {
  SpriteQueue queue;
  DrawState draw;
  DrawSettings settings;
  std::array<std::uint8_t, kScreenWidth * kScreenHeight> buffer{};
};

static_assert(std::is_trivially_copyable<CompositorState>::value);
static_assert(std::is_standard_layout<CompositorState>::value);
static_assert(sizeof(QueueEntry) == 0x54);

// Called during composition. The HUD draws at layer 15; text entries go through the font.
struct ComposeHooks {
  void* context = nullptr;
  void (*hud)(void* context, CompositorState& state) = nullptr;
  void (*text)(void* context, CompositorState& state, std::uint32_t text_id, int x, int y, int colour) = nullptr;
  bool text_enabled = true;  // the font object's flag at +0x1c, bit 1, clear
};

struct QueueRequest {
  int layer = 0;
  int x = 0;
  int y = 0;
  std::uint32_t sprite = 0;
  std::uint16_t flags = 0;
  std::uint8_t scale_x = 100;
  std::uint8_t scale_y = 100;
  std::uint8_t opacity = 0xff;
  std::uint8_t param_b = 0xff;
  std::uint8_t param_a = 0xff;
  std::uint8_t priority = 10;
  std::uint32_t extra = 0;
};

// Returns the layer used, or 0 if the sprite was empty or the queue had no room.
int queue_add(SpriteQueue& queue, const DrawData& data, const QueueRequest& request);
void queue_next_frame(SpriteQueue& queue);
void compose(CompositorState& state, const DrawData& data, const ComposeHooks& hooks);

// The individual routines, exposed for tests.
void draw_sprite(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y);
void draw_shadow(CompositorState& state, const DrawData& data, const SpriteRecord& sprite, int x, int y);

}  // namespace omf
