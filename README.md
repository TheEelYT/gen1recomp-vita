# Gen1Recomp on PS Vita (experimental)

Based on the Pokemon Gen 1 Recompilation Project by BOIS CLUB GAMES, LLC
(https://github.com/bryanthaboi/gen1recomp)

Runs the Gen1Recomp engine on isage's LÖVE 11.4 Vita port
(https://github.com/isage/love, release `11.4-vita`). No VitaSDK needed.

**This repository ships no playable artifact, and cannot.** A built VPK
necessarily contains the engine's Launcher, which its `LICENSE.MD` Additional
Term 2 makes proprietary and permits distributing "only in unmodified official
releases from BOIS CLUB GAMES, LLC". So this repo is source only: build your own
VPK from your own engine checkout. See `docs/upstream-issue-draft.md` for the
route to an official Vita build.

## Build

Use Python 3.9+ with Pillow and the patched LuaJIT 2.1 runtime described in
`TOOLCHAIN.md`. From the Windows checkouts:

```powershell
cd B:\gen1recomp-vita
python build_game_vpk.py --engine B:/gen1recomp --eboot vendor/love-vita/love.self
```

This produces `build/gen1recomp-vita.vpk`. Extended memory (`ATTRIBUTE2=12`)
is enabled by default for the 196 MB runtime heap. The default runtime path
is `vendor/love-vita/love.self`; a missing runtime fails the build instead of
silently downloading the old LuaJIT 2.0.5 executable. The game uses 22050 Hz
audio. `--audio-rate ''` keeps the engine's default rate.

To verify the Lua payload without VitaSDK, a native runtime, or driver downloads:

```powershell
python build_game_vpk.py --engine B:/gen1recomp --love-only
```

`INCLUDE` is checked against the engine's `scripts/pack_love.sh` on every build.
The payload includes all eleven ROM manifests, including Emerald, Ruby and
Sapphire. Generated ROM data, game dumps, saves and PSD source artwork are
excluded. Source Lua is the default; leave `--bytecode` off because its legacy
LuaJIT 2.0 compiler path does not match this runtime.

## Vita settings retained

- Fixed 960x544 window and 22050 Hz chip audio.
- Main-state JIT disabled by default, with the existing opt-in mod API.
- Native pad navigation, virtual filesystem ROM browser, and return to the
  launcher inside the running process.
- Sequential Gen 3 import, compact map cells and script windows, lazy FRLG
  tilesets, and separate encoding of atlas layers to limit peak memory.
- Low-memory import GC without enabling handheld frame pacing or the idle
  render governor. Discord presence remains disabled.
- Native vitaGL shader/uniform workarounds, first-vertex offset workaround,
  disabled rear touch, executable JIT pool and host/target layout verification.

The optional `build_vpk.py` probe still targets the older upstream runtime;
use `build_game_vpk.py` for the game.

## Install

1. HENkaku settings: turn on **Enable Unsafe Homebrew** (the eboot requires it).
   Recommended: a per-app clock profile (e.g. the PSVshell plugin) at 444 MHz
   CPU / 222 MHz GPU. The eboot never raises the clocks itself, and apps
   otherwise run at the 333 MHz default.
2. Install `gen1recomp-vita.vpk` with VitaShell.
3. Copy your own `.gb`/`.gbc`/`.gba` dump to `ux0:data/love2d/love/pokemon-love2d/`
   (create the folder if the game has not been launched yet).
4. Launch Gen1Recomp and press Choose on the cart: the file picker is
   unavailable on the Vita, so the importer falls back to that folder.

Crash logs: `ux0:data/SDL_Log.txt`.

## Status

The October 18 update integrates upstream engine `041e0558` (v0.3.90 code)
and retains this fork's Vita changes. The runtime fork already contains
Code-Grub's latest `b1d1932`. See `docs/upstream-sync-2026-10-18.md` for the
validation and hardware checks still needed.

Previous Vita hardware results do not validate this new engine merge. A fresh
native compile and an on-device boot/import/playback check remain required.
The port targets standard Gen1Recomp. Battle Art and all other voxel mods are
out of scope; their shader edits, mesh workarounds and cache designs are no
longer part of the build or hardware acceptance criteria. Older voxel probes
and design notes are historical experiments, not planned features.
