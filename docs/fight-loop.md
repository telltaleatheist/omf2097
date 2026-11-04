# The fight loop: simulation, drawing and pace

How one frame of a fight works in `MASTER.DAT`, written to decide the rebuild's structure.
Addresses are in `analysis/master.elf`. **Verified** means read in the code or measured from
the game files. **Inferred** means a reasoned reading of what the code is for. Calculated
numbers are labelled, and nothing here has been measured on a running game.

## The short version

- Simulation and drawing are not separate in the original. The per-frame "scene" function
  (0x3396c) runs game logic and composes the picture.
- **Hit detection reads the composed picture.** A hit is an attack point landing on a pixel in
  the opponent's colour range, in the 64,000-byte back buffer.
- The fight's random numbers are shared with the scene function and never restored.
- All of this is integer work on simulation state and settings. No clock or video hardware
  feeds it, so rollback remains possible, but the composite is part of the simulation.
- One simulation tick runs per loop iteration. Nothing skips or catches up when late.

## One frame of 0x30c08

The loop body starts at the call at 0x31e13 and runs to its test near the end of 0x30c08. The
order below is verified by reading. What each step is for is partly inferred, from what it touches.

| # | Step | Where | Kind |
|---|---|---|---|
| 1 | Copies back buffer to display copy, scrolled for screen shake (inferred) | 0x27348 | drawing |
| 2 | Read or queue local input, one input packet | 0x57970 | input |
| 3 | Physics and movement, fighter 1 then 2 | 0x112a4 | simulation |
| 4 | Fighter logic, each fighter | 0x11b3c | simulation, some effect spawns |
| 5 | Body push | 0x178c8, 0x1115c | simulation |
| 6 | Extra update when a fighter's state byte +0x4e is 5, which looks like AI control | 0x1aae0 | simulation |
| 7 | **Hit tests between fighters, on the existing buffer** | 0x3092c | simulation |
| 8 | Input and AI decisions, once per tick for each fighter | 0x58448, 0x514f0 with argument 1 | input, AI |
| 9 | **Reseed from the frame number** | 0x5e45c | simulation |
| 10 | Every 60 frames, build and send a sync check | 0x2df98, 0x55cc4, 0x2d1f4 | network |
| 11 | Per-tick network and recording work, sets libc's seed | 0x2e5c4 | network |
| 12 | Frame number + 1 | 0x84398 | simulation |
| 13 | More per-fighter updates, not read in detail | 0x52f50, 0x1667c | simulation |
| 14 | Keys: speed, pause, help, debug | loop body | input |
| 15 | **Scene pass** (below) | 0x3396c through its thunk at 0x1e5c8 | both |
| 16 | Extra input polling if speed is under 10 and not networked | 0x58448, 0x514f0 with argument 0 | input |
| 17 | **Speed delay** | 0x55bfc | wait |
| 18 | Hit pause delay when one was requested | 0x55bfc | wait |
| 19 | Copy HUD regions to the display copy | 0x5efbc | drawing |
| 20 | Palette, optional retrace wait, then copy dirty blocks to the display | 0x5cea8, or 0x5f274 for a full-screen update | drawing, wait |
| 21 | Clear the sprite queue for the next pass | 0x5cd48 | drawing |
| 22 | Extra input polling if speed is under 8 and not networked | as 16 | input |
| 23 | Debug frame-rate text | loop body | drawing |
| 24 | End-of-fight effect, once | 0x30608 | both |
| 25 | Round end and music | loop body | simulation, audio |

Steps 3-13 are in the same order as the unreferenced function 0x337d4 (below). Audio is
triggered by simulation as it goes (for example through 0x11870, inferred from sound calls),
not as its own step.

### The scene pass, 0x3396c

1. Reseed from frame - 1, unless held.
2. **Objects, 0x21930.** For each of 200 object slots: timers, motion (0x245b8), animation
   script steps (0x1ed60), **hit tests against the existing buffer** (0x215c8, with 0x21930 then
   calling 0x17ea8 directly), new objects, and queuing sprites.
3. **Background copy, inside 0x21930**, after that loop. If the object manager has a background
   pointer (+0x14), all 64,000 bytes are copied over the back buffer. The previous composite is
   gone from here on.
4. Ambient arena objects are stepped and queued, still inside 0x21930.
5. **Fighters, 0x13d44, for each fighter.** Animation script step, spawns, blood, screen shake
   requests, flags on the opponent, and queuing the fighter's sprite.
6. Palette work (0x5ec68).
7. **Compose, 0x5d0a0.** Draws the queue into the back buffer, in layer order from 0 to 219.
   At layer 15 it calls the HUD routine (0x332b0 through 0x1e5c0). Each sprite's shadow is drawn
   just before it.
8. Reseed from frame - 2, unless held.
9. **Ambient object triggers, 0x23c5c.** 50 draws from the generator at least, then **hit tests
   against the new composite** (0x215c8, then 0x23fcc, which calls 0x17ea8).

### What each hit test reads

| Caller | When | Reads |
|---|---|---|
| 0x3092c, through 0x16c88, then 0x215c8 | Tick, step 7 | The composite from the previous iteration's step 7 of the scene pass, as left by anything after it |
| 0x21930, then 0x215c8 | Scene, step 2 | The same composite. Nothing writes the back buffer between the tick and this point (see below) |
| 0x23c5c, then 0x215c8 | Scene, step 9 | This pass's new composite |

Writes to the back buffer between composition and the tick's hit tests, as far as read:

- **HUD region copies, 0x5efbc:** read. They copy from the back buffer to the display copy, and
  don't write the back buffer on the path read.
- **On-screen messages, 0x5cd80**, from 0x5cea8: text through the font routine, which draws into
  the back buffer. Not traced to the end. If they do land there, a message shown on one machine
  only could change hits on that machine.
- **Debug frame-rate text**, step 23: through the same font routine.

### Can they be separated?

Not as the original is laid out, but the tangles are specific:

- **Simulation reads what only drawing writes.** That is the composite, above.
- **Game logic in the "draw" function.** Scene steps 2, 4, 5 and 9 are simulation.
- **Sprite queue fields feed back.** Scripts set draw modes and flags (0x84984, 0x847f6/8) that
  are read while queuing. Queue contents depend on simulation only, as far as read.
- **Random numbers cross the boundary**, below.

In the other direction, composition has no effect on state other than the back buffer and
some draw-related globals, as far as read.

### 0x337d4

It has the same steps as 3-13 in the same order, with no input read, keys, scene pass, delay or
flip. **Nothing references it**: no call, no jump, and no pointer anywhere in the image.
Likely left-over code, possibly for catching up during a replay. The rebuild can ignore it,
though it is useful evidence of which steps the authors thought of as "the tick".

## The random number generator and drawing

See `rng.md` for how the generator works.

**Drawing shares the generator, and the sequence is not restored.** The scene pass reseeds twice
and draws from it, and the next tick's steps 3-8 draw from whatever it left, because the tick
doesn't reseed until step 9. Effect spawners (0x100c0, 0x10668) overwrite the state instead of
restoring it: they set the counter to the frame number and reseed with a frame of 0, at both
start and end. So their own draw counts don't leak, but the fact that they ran does.

Callers reachable from the fight. The index misses paths through the scene thunk, so 0x3396c,
0x13d44 and 0x23c5c are included by hand.

| Function | Draws, reseeds | Class | Evidence |
|---|---|---|---|
| 0x30c08 | 1, 2 | simulation | Picks a value at setup; reseeds at start and in the tick |
| 0x514f0 | 53, 0 | simulation, AI only | Draws are on the AI path; returns early for AI when polled with argument 0 |
| 0x534a0 | 5, 0 | simulation, AI only | Called from 0x514f0's AI path |
| 0x18de4 | 5, 0 | simulation | Percentage rolls, then changes fighter state |
| 0x13d44 | 10, 0 | simulation | Rolls for spawns, and changes state |
| 0x1ed60 | 3, 0 | simulation | Script steps: writes an angle and spawn offsets |
| 0x245b8 | 2, 0 | simulation | Object motion |
| 0x24080 | 1, 0 | simulation | Object spawn |
| 0x100c0 | 5, 2 | effect spawn | Spawns objects, nothing else. Those objects land in the composite |
| 0x10280 | 4, 0 | effect spawn | Same |
| 0x10668 | 27, 2 | effect spawn | Same, mostly particles |
| 0x23c5c | 2, 0 | simulation | Ambient triggers; can lead to hits |
| 0x3396c | 0, 2 | simulation | The reseeds described above |
| 0x337d4 | 0, 1 | unused | No references |

None is purely drawing. The sprite drawing routines (0x5d0a0 and below) don't use the generator.

### What can change the number of draws

- **Video hardware, frame timing, frame skipping:** nothing found. No path skips a scene pass.
- **Real time:** no. Polling between ticks can't reach a draw for a fighter under AI control,
  because 0x514f0 returns early for AI when its argument is 0. For a human it reaches no draw
  (0x58148, and only a fatal-error path from 0x51318).
- **Settings:** yes. In 0x23c5c, the first draw for each of 50 ambient slots is unconditional,
  but the follow-up draw depends on bits 0x10 and 0x80 of 0x8e5e2 (and whether the slot is
  flagged as a hazard). 0x10280 and 0x10010 use the same bits. So both machines need the same
  settings.
- **Scene state:** yes, through simulation state only, such as how many objects are alive.
- **The composite:** yes, indirectly. A hit test's result decides what runs next, and that can
  draw.

Each machine does need to run this logic, but it isn't drawing logic in the sense that matters.
It needs no pixels on screen, only simulation state and settings, plus the composite.

## Hit testing

0x215c8 takes an animation's current frame, then tests each of its attack points whose tag
matches. For each, it reads the back buffer at x + y * 320 (0x5e888), or 0xff off-screen:

- **The range check.** An argument picks the wanted range: 1-0x2f for player 1, 0x30-0x5f for
  player 2, or both. The first point landing in range is the hit, and 1 or 2 is returned. The target
  also has to pass a check on its own flags (+0x941 bit 0x40, or +0x5c bit 8), or the hit is dropped.
- **The pixel table.** The value also indexes a 256-byte table at object manager +0x20. If that
  entry is non-zero, its value and the coordinates are recorded (0x8e4da, 0x8e4de, 0x8e4e2).

**What the pixel table does.** Verified. It is filled by animation script commands in 0x21930,
which set a range of pixel values to one number. Its result is read only by 0x16c88, for a
fighter's attack points: it stores the value and position on the attacking fighter (+0x910 to
+0x918). 0x23c5c then passes that to 0x23a6c, which looks for live objects of the animation with
that number, tests the point against the object's sprite, and if it lands: gives the object an
owner, can spawn a further object, and can switch its animation.

So **arena pixels can affect fights**, by triggering arena objects when an attack point lands on
a marked colour. Which arenas' scripts actually do this hasn't been checked. That is a static
job: map the script command in 0x1ed60 and scan the five `ARENA*.BK` files.

### What the classification depends on

The answers come from the code and from histograms of the game's files. They were made with a
sprite and palette layout recalled from OpenOMF's format notes and then checked: each sprite was
accepted only if it decoded cleanly with the scheme read from 0x5aa3c. They cover all sprites in
a file, including effects, not just fighter bodies.

**Backgrounds: can't be mistaken for a fighter.** In all five arenas, every one of the 64,000
background pixels is 0x60 or above, and none of the eight remap tables moves any value at or
above 0x60 into 1-0x5f.

**Fighter sprites don't guarantee their range.**

| File | Sprites | 0 | 1-0x2f | 0x30-0x5f | 0x60 and up |
|---|---|---|---|---|---|
| FIGHTR0 | 108 | 89 | 108,705 | 22 | 1,954 |
| FIGHTR1 | 141 | 44 | 258,857 | 7 | 5,102 |
| FIGHTR2 | 166 | 65 | 291,478 | 0 | 1,912 |
| FIGHTR3 | 105 | 102 | 149,212 | 28 | 14,845 |
| FIGHTR4 | 170 | 66 | 209,861 | 14 | 42,595 |
| FIGHTR5 | 140 | 8 | 244,114 | 5 | 2,327 |
| FIGHTR6 | 150 | 94 | 191,432 | 31 | 1,910 |
| FIGHTR7 | 151 | 222 | 265,911 | 45 | 1,945 |
| FIGHTR8 | 76 | 30 | 127,800 | 19 | 1,905 |
| FIGHTR9 | 82 | 193 | 105,445 | 54 | 2,005 |
| FIGHTR10 | 171 | 66 | 402,635 | 9 | 5,584 |

Player 2's colours come from a draw mode (flag 0x800, routines 0x5a2b4 and 0x5a2d8) that adds
0x30 to any source value below 0x30. How that flag gets set for player 2 looks like a field on
the pilot (+0xf4), which is inferred. So:

- Most fighter pixels classify as their owner.
- A source value of 0x60 and up is never a hit, for either player. Such pixels make up a sizeable
  share of some files, and could be effects rather than bodies, which isn't separated here.
- A rare source value in 0x30-0x5f counts as **player 2's colour even when drawn on player 1**.
- Objects use the same drawing and classification, so an attack point landing on a projectile
  or particle in its owner's colours counts as hitting the owner, with no check that it is a
  fighter. Which particle sprites have which colours is an open static question.
- ARENA4 has sprites with 37,131 pixels in 1-0x2f, and ARENA1 and ARENA3 have a few. Whether they
  draw unmodified isn't known, but if so, a point landing on them registers as hitting player 1.

**Overlaps: the later draw wins.** Normally player 1 is layer 0x1e and player 2 is 0x1f, so
player 2 draws on top. Several conditions change it: +5 when the opponent has certain flags set,
0x3c or 0x11 on the fighter's own flags. Objects use their own layer plus 2, from 2 to 65, so
they can be on either side. The consequence, if the fighters overlap at the default layers: a
player 2 attack point on an overlap sees player 2's own pixels and so misses player 1, while a
player 1 attack point can't be shielded by player 1's own body. So draw order can affect who can
be hit. The mechanism is verified. How much it matters in play isn't.

**What can write over a fighter:**

| Draw | Effect on a fighter's pixels | Setting-dependent? |
|---|---|---|
| The other fighter | Replaces with its own colours or above | No |
| Objects, particles | Replaces with the sprite's value, if layered above | Partly: some spawns are gated by 0x8e5e2 bits 0x10 and 0x80 |
| Shadows (0x5bc7c, flag 0x1000, y below 0xbf) | Remap table 4: in every arena's every palette all 95 fighter colours become non-fighter colours. **A shadowed pixel can't be hit** | **Yes**, bits 2-3 of 0x8e5e2. Off at level 0. Flagged objects' shadows at level 2 and up. Level 3 also queues extra remap draws at layer 2, below fighters |
| Other remap draws (flag bits 0x10, 0xe0) | Tables 0-3 and 5-7 keep all 95 fighter colours in range, and in their own player's range in the samples read | No, script-driven |
| Additive (flag 0x200, 0x5a3d0) | Adds a scaled source value to the pixel, which can cross a range boundary | No, script-driven |
| Blend (flag 0x400, 0x5a4b8, and flag 0x100, 0x5d300) | New value computed from source and destination | No, script-driven |
| HUD (layer 15) | Below default fighter layers, so doesn't cover fighters. Can cover low-layer objects | No |
| Arena foreground objects | Above fighters when their layer is. Values of 0x60 and up would block hits | Partly, through the same bits |
| On-screen messages, debug text | See above, not traced to the end | Messages are local events |

The memory table at 0x8c37b is treated here as table 4 of the arena file, because the code's
base (0x8bf7b) plus 4 * 0x100 lands there and the flag bits index it in the same way. That
mapping is inferred. The remaining tables weren't checked past index 7.

**Could the original have desynced on this?** The settings the original copies between machines
(0x2e8a0) include only bits 4 and 5 of 0x8e5e2, so not the shadow level or bit 7. Shadows can
change hits, so two machines with different shadow settings could diverge. Likely a real
original bug, if it can be reached. Unconfirmed.

**Can the static answer settle it?** It settles what's possible, and the options below can be
judged from it. It can't say how often each case happens. See "Questions for a real run".

### Options for the rebuild

These aren't chosen here. Both must give the same hit results as the original.

**A. A real indexed composite in the simulation.** Keep 64,000 bytes, compose every tick with
the original's draw modes and order, including shadows, objects and the background.

- Everything above reproduces itself, including quirks not yet found.
- Snapshot size per frame (estimate): fighters 2 * 0xa294, objects 0x991c, pilots 2 * 0x1ac,
  sprite queue 0x483c, input 0x498, back buffer 64,000, plus a few KB of globals. **About 210 KB.**
  Some of that is loaded data rather than state, so splitting it would shrink this. The buffer
  can leave the snapshot if it is rebuilt from the saved queue and background, for the cost of one
  extra composition after each rollback.
- Compositor work per re-simulated frame (estimate): one 64,000-byte background copy, plus sprites.
  At most 220 queue entries; a typical fight frame is perhaps tens of thousands of pixels. Of the
  order of 100,000-300,000 byte operations, which is well under a millisecond on a current CPU.
- Could be stored apart from the screen image: the rebuild's display can still be drawn however it
  likes.

**B. A lighter hit mask.** Only what can affect hits. It would have to reproduce, in draw order:

- Each fighter's source pixels, with the player 2 shift and the values that stay as they are.
- Every object above or below fighters whose pixels fall in 1-0x5f or that cover a fighter.
- Shadows, because they remove fighter pixels, at the agreed setting.
- Additive, blend and remap modes, on anything that could end up in or leave those ranges.
- Exact values wherever the pixel table has entries, which can include background values. So the
  background can be dropped from the mask only if the arena's scripts mark no background colours.
- The HUD only if it can ever land in range where no fighter is. Its colours haven't been checked
  fully.

What B could leave out on present evidence: palette work, the display copy, and the background in
arenas whose scripts don't use the pixel table. It wouldn't save much, since sprite work is most of
the cost, and it would need proof for each thing it drops. Whether the fighter-sprite values of 0x60
and above can be simplified depends on the same run.

For reference: as remembered, not checked here, OpenOMF tests attack points against the target's
sprite rather than a composite. That is a simplification of the same idea, and it wouldn't give the
same results in the cases above.

## Scene passes per tick

There are eight references to the scene thunk at 0x1e5c8:

| Site | Path | When | Passes |
|---|---|---|---|
| 0x326c5 | Loop body | Every iteration, nothing skips it | 1 |
| 0x321f7 | Key 0xe0, likely pause | Hold set; needs 0x8e4bc and 0x8e4c0 at 0 | 1 |
| 0x32215, 0x63709, via 0x63314 and 0x37b80 | Key 0xe0's menu | Hold set | Depends on menu use |
| 0x30908 helper | After key 0x3f9, key 0xd3, and from 0x63314 | Hold set | 1 each, plus flip |
| 0x55daa, in 0x55d00 | Key 0x3f9 prompt | Hold set, after the key wait | 1 |
| 0x3216c, via 0x37b80 | Key 0xd3, help | Hold set | Once per redraw of the screen, so depends on how long it stays up, not confirmed |
| 0x30631, in 0x30608 | End-of-fight effect | Sets hold itself, clears it after, once per fight | 1 |

None of these runs unless the key or end-of-fight condition happens. In online play, Owen's decision
removes the pause paths. Fades in the fight loop that were read (0x5e500, 0x5f2c4, 0x5ec68) don't call
the scene. Between rounds, the same loop continues and scene passes continue one per tick.

The keys come from the shared input value at the input object's +4, so as far as read they would run
on both machines in the original's network play, apart from the prompts tied to the local player.

### What runs under hold (mask 0x02 of 0x8bb72)

Needed for offline pause, kept as the original.

**Stops:**

- Reseeds (0x5e45c does nothing).
- Object motion and everything after it in 0x245b8.
- All of 0x23c5c: ambient triggers and their hit tests.
- In 0x21930: script effects (sound, killing objects, table fills, spawns), timers, and the block
  containing object hit tests, sin/cos paths, spawns and frame advance.
- In 0x13d44: the block with spawns, blood, opponent flags, and rolls.

**Still runs:**

- The animation script step (0x1ed60), from both 0x21930 and 0x13d44. It can draw from the generator
  where a script's command calls for it, and it is the only draw found that isn't gated.
- Queuing sprites, the background copy, and composition. So the back buffer is rebuilt from the
  paused state.
- Palette work, and the debug colour writes.

Offline, pausing can move the generator, and only on frames whose script has those commands. Since
the tick reseeds at step 9, the effect lasts only until then. It still affects what the next tick's
steps 3-8 draw.

### Options reachable from the pause menus

Reached from 0x63314, including its call to 0x608fc, and 0x37b80. These would need locking while online.

| Setting | Address | Effect | Lock? |
|---|---|---|---|
| Shadow level (0-3) | 0x8e5e2 bits 2-3 | Changes which pixels can be hit | **Yes** |
| Option at bit 7 | 0x8e5e2 | Gates hazard-type logic in 0x10010, 0x10280, 0x23c5c, also read in 0x3396c | **Yes** |
| Option at bit 8 | 0x8e5e3 bit 0 | Read in fight logic at 0x11b3c, 0x1ed60, and in 0x3396c | **Yes**, until shown harmless |
| Option at bit 6 | 0x8e5e2 | Read only in 0x27348, the display copy, so likely screen shake. Display only | No, if that holds |
| Option at bit 15 | 0x8e5e2 | Copied to bit 4 of 0x8e5e0 when the menu closes. No other direct reader of bit 15 found | Check bit 4's readers |
| Retrace wait | 0x8e5e2 bit 11 | Pace only | No |
| Game speed | 0x8e4e8, 0x8bb74 | Pace only, plus the polling in steps 16 and 22 | Must match, since rollback needs one rate |
| Volumes | 0x8e5e8, 0x8e5e9 | Sound routines only, inferred | No |

Not in the pause menus, but fight-affecting and copied between machines by the original: hit pause
and related fields at 0x8e5d6-0x8e5de, 0x8e5ba-0x8e5c0, parts of 0x8e5e0 and 0x8e5e4 (0x8e5e0 bit 2
is read in 0x112a4), and bits 4-5 of 0x8e5e2 (bit 4 is the ambient and hazard gate above; bit 5
selects a script variant in 0x1d6f8). The menu names of the options at bits 6-8 and 15 weren't resolved:
`ENGLISH.DAT`'s index-to-text mapping wasn't worked out.

## Sin and cos

**They can reach simulation.**

- **0x21930, four sites (0x22863, 0x2290f, 0x229cd, 0x22a80).** When a script sets a flag
  for the current object (0x847f0 bit 0x1000), its x and y come from sums of sin and cos of a
  frame-like counter (0x8bb64), then are multiplied by 256 and truncated to int. Those are the object's
  position, and the same object goes on to the hit tests. So if such an object can hit, the results
  reach a fight directly. Which objects use the flag is an open static question.
- **0x10668, three sites (0x1077e, 0x107a8, 0x107e8).** Directions for spawned particles from an angle set by scripts
  (0x847ea). They land in particle velocities, and from there in the composite, so they can reach
  hits indirectly when particles cover a fighter.

Both results are cut to 1/256 units, so small low-order differences only change the result when a
value is close to a rounding step. That matters for "rebuilt vs original". It doesn't help between
machines, which must match exactly, so the rebuild needs its own fixed sin and cos. The target to
match against is what a real FPU returns on the original's path: see the real-run list.

- **Four more sites (0x259f5, 0x25aa1, 0x25b5f, 0x25c18)** are in the unreferenced code described in
  "Coverage" below, and look like a copy of the 0x21930 ones.

Also, 0x8bb64 is reset in the fight loop when three raw keys are held, with a debug frame-rate display.
That looks local to one machine, and would change these objects' motion. Unconfirmed as reachable
in network play.

## Frame pacing

**One tick per iteration, verified.** The loop has no time-based branch that repeats or skips the
tick or the scene pass. If a machine is late it just runs slower. Time is read in the loop only for
the debug display, message expiry and input windows. So what "play identical" has to match is the
tick sequence, whatever rate it runs at.

**The wait is deliberately simple.** At speed under 10 the loop calls 0x55bfc with (10 - speed) * 5.
That routine divides by 10 and spins until that many hundredths of a second have passed on the timer,
polling input and sound while it waits. 0x5cea8's palette step can also wait for vertical retrace, but
only when the palette changed and bit 11 of 0x8e5e2 is set, and it gives up after about three timer ticks.

Calculated maximum rate from the delay alone. Real rates are lower by the work done each frame and
timer granularity, and depend on the machine.

| Speed (0x8bb74) | Delay, hundredths | Maximum rate |
|---|---|---|
| 0 | 5 | 20 Hz |
| 1, 2 | 4 | 25 Hz |
| 3, 4 | 3 | 33 Hz |
| 5, 6 | 2 | 50 Hz |
| 7, 8 | 1 | 100 Hz |
| 9 | 0 | No delay, the call returns at once |
| 10-19 | none | No delay, machine speed only |

- Speed is 0x8e4e8, copied to 0x8bb74. The fight's speed keys allow 0-19. 0x56334 caps the copy at 10
  when reading it from settings. Speeds 10-19 behave identically in this code. They look like a
  leftover or hidden range.
- The speed also changes input: at under 10 there is an extra poll between ticks, and at under 8 another
  (steps 16 and 22), but only when not networked. Those polls are real-time too, in 0x55bfc when 0x84962 is
  set.
- **So real-time input matters.** Human input is sampled between ticks in local play, and handled in
  0x514f0 and 0x51318, so a tap shorter than a tick can still register. In the original's network play
  those polls are switched off. This affects "working like the shared-keyboard mode", so it needs a
  decision.
- **Two input timers run on real time, not ticks.** 0x514f0 holds a button state for 15 hundredths of a
  second (+0x920, +0x924) when 0x84962 is set, and it times a window with +0x44 and +0x48. Rollback needs
  these in ticks. The conversion depends on speed, which needs care to match what players feel.
- **Hit pause is a real-time delay** in step 18: (0x8e5d8 * 24) / 10 hundredths, when a hit asks for one.
  No ticks pass during it, so in rollback it has to become display time only, or be counted in frames
  as a deliberate change.
- Other readers of the timer in a fight: 0x13d44 and 0x11870 for sound re-trigger timing (inferred from
  their use), 0x5f380 and 0x5f0c4 for bounded waits.

**0x81de0 doesn't change, as far as can be found.** It's 8 in the image, with no direct write. The only
nearby writes are dwords at 0x81dd2-0x81ddc, ending at 0x81ddf. No block copy over it was found, though
one through a computed pointer can't be fully excluded. Timer rate: 1,193,182 / (65,535 / 8) gives about
145.7 Hz (calculated). The handler also uses it to pass every eighth tick to the old timer, which fits
8 being a design constant.

The network wait itself wasn't fully traced. 0x2e5c4 calls 0x2db18, which loops up to 0x640 times around
the driver routines at 0x6aa38 and 0x6a89f. Likely lockstep.

## Rollback state: first inventory

Heap objects and their sizes are verified from their allocations. What in them is state versus loaded
data is mostly not worked out.

| What | Where | Size | Notes |
|---|---|---|---|
| Fighters | [0x84970], [0x84974] | 0xa294 each | Positions at +0xa8 to +0xb4, script frame at +0x98. Per-move data at +0x970 + 0x230 per move looks like mostly loaded data, unverified |
| Pilots | [0x84978], [0x8497c] | 0x1ac each | Health at around +0x106 |
| Object manager | [0x8e614] | 0x991c | 200 objects of 0x44 from +0x63fc; 50 ambient slots of 0x1f8 from +0x18c; pixel table at +0x20; background pointer at +0x14 |
| Back buffer | [0x8e484] | 64,000 | See the options above |
| Background | manager +0x14 | 64,000 | Unchanged during a fight, inferred. Not state unless a script changes it |
| Sprite queue | [0x8e4d4] | 0x483c | 220 entries of 0x54. Rebuilt each pass |
| Input | [0x8e618] | 0x498 | Includes the frame's input and key value |
| RNG | `RngState`, 0x90f14 etc. | 264 | See `rng.md` |
| Frame number | 0x84398 | 4 | |
| Fight's frame-like counter | 0x8bb64 | 4 | Feeds sin and cos |
| Screen shake and related | 0x8b8e8-0x8b8f2 | small | Display, but set by hits |
| Script globals | 0x847ec-0x84848 | small | Rewritten per script step. May not need saving if every reader runs after a step, unverified |
| Other scalar globals | see below | unknown | |
| Palette state | 0x8bb5c + 0x1a1f and + 0x201f | 2 * 768 | Fades in fights. Not read by simulation, as far as seen |
| Heap allocated while fighting | | unknown | No allocation found in the tick or scene pass, but not exhaustively checked. 0x213e4 and 0x6a354 use need a closer look |

**Other globals written by the tick and scene code**, found by scanning absolute-address writes in the 208
reachable functions. These are ranges to examine, not a final list: 0x82ea8-0x82eb5 (shake), 0x82ee8-0x82efc,
0x82f3c-0x82f74 (network), 0x8356c-0x8357c, 0x84378-0x84395, 0x847bd, 0x847ec-0x84848, 0x84978-0x84998 (draw
state among them), 0x87268-0x8726a, 0x87280-0x87289, 0x8b8e8-0x8b8f2, 0x8b948-0x8b951, 0x8bb6e-0x8bb72,
0x8e494-0x8e4b0 (compositor scratch), 0x8e4c0-0x8e4e6, 0x8e5bc-0x8e5c0, 0x8e5d5-0x8e5e4, 0x905e4-0x905ee
(messages), 0x90ed0-0x90f04 (compositor scratch), 0x91014-0x91038, plus smaller ones. In all: 210 addresses
in 46 ranges.

### CPU requirement if logic re-runs

Static sizes (not execution counts): the tick's reachable game code is about 25,000 instructions, and the scene
pass's about 28,000, with a large overlap (34,000 in total). Most of that doesn't run on a given frame. The pass
without sprite work loops over 200 object slots, 50 ambient slots and two fighters. A rough estimate is 50,000 to
300,000 instructions per pass in the original's terms. That's not measured. On a current CPU even eight re-simulated
frames per displayed frame should fit comfortably, but the estimate needs replacing with a measurement once the logic
is ported.

## Coverage

- The RNG tables cover every direct call in decoded code. There are **no calls to 0x5e2b0 or 0x5e45c in
  decoded game code outside known functions.** About 3,000 decoded instructions sit outside functions, in
  17 regions. Calls from undecoded bytes can't be excluded.
- The largest region, 0x24af7-0x26853, has object-handling code much like 0x21930, including sin, cos, spawns
  and hold tests, but no direct draws. Its undecoded start is a jump table at 0x24aa0 and a function prologue at
  0x24ac0. No call, jump or pointer to 0x24ac0 was found. So it looks unused, like 0x337d4.
- The call graph comes from direct calls plus the thunk table at 0x1e5c0. The object and fighter logic has few
  indirect calls, but they weren't each resolved.

## Questions for a real run

None needed right now for the structure. These would firm up the details. Each needs the original running in an
instrumented DOS environment (a test tool only, per `CLAUDE.md`).

1. **How often do overlays decide a hit?** Log every call to 0x5e888 from 0x215c8: point, value and caller. At each
   call, compare with a composite of only the two fighters and see how often the outcome differs. Run several recorded
   fights across arenas, at shadow level 0 and 3. This decides how much option B would have to reproduce.
2. **Do shadows change fight results?** Play one recording (`.REC`) twice with shadow level 0 and 3, and compare the
   logged health and position each frame. The game's record and play paths (0x2b484, 0x2b370) make this repeatable
   if they aren't themselves affected.
3. **Real frame rate at each speed.** Log the frame counter against the timer on a machine of the original's era, or a
   DOS environment set to one, at speeds 0, 5, 8, 9 and 10. Calculated values above are upper bounds only. Which real
   machine counts as the reference is a question for Owen.
4. **Real FPU sin and cos.** Values from a real 387 or better on the game's path, at angles sampled from the two callers.
   Emulated x87 isn't good enough for this one.
5. **Pause and hold.** Compare the generator's state before and after one pause and resume, on a frame whose script has
   a draw in it.
