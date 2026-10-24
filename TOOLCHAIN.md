# Building a LÖVE runtime for the Vita (LuaJIT 2.1)

isage's prebuilt `11.4-vita` eboot links **LuaJIT 2.0.5** (hyln9/vita-luajit).
This rebuilds the runtime against patched **LuaJIT 2.1.0-beta3**, which supports
the Gen 3 importer syntax. The game payload uses source Lua by default.

The current runtime uses **vitaGL + sdl2_vitagl**. Older PVR/gl4es build
instructions are superseded. Keep existing local SDK libraries when updating
the source branches; an engine update does not require replacing them.

## Toolchain

| Piece | Configuration |
|---|---|
| VitaSDK | `C:/vitasdk`, GCC 15.2.0 / arm-vita-eabi |
| MSYS2 | make, autoconf, automake, libtool, pkgconf, patch |
| SDL2 | `sdl2_vitagl` (remove conflicting `sdl2` package) |
| Renderer | `vitaGL`; the prior hardware test used `SAFE_DRAW=1 NO_SPLASHSCREEN=1` |
| Audio/data libs | freetype, openal-soft, libmodplug, mpg123, libvorbis, libogg, libtheora, zlib, libpng, physfs |
| LuaJIT | patched SonicMastr/LuaJIT-Vita `v2.1` at `c329ddd10691c1875f26087ba23c2ae278515e24` |
| LÖVE | isage/love at `6633ca5ba9294cd735c62ca519a9ea3a9870e0bb` plus `patches/love-vita-psp2.patch` |

Apply native patches only to clean source. For existing patched checkouts,
inspect `git diff` before updating; never reset away local native changes.
`baselines/` stays local and ignored.

### Gotchas hit here

- Several vdpm packages ship `.pc` files with a Linux CI prefix
  (`/usr/local/vitasdk/...`) or a literal `$VITASDK`; rewrite `prefix=` in
  `C:/vitasdk/arm-vita-eabi/lib/pkgconfig/*.pc` to `C:/vitasdk/arm-vita-eabi`.
  FreeType also `Requires: libpng`, but only `libpng16.pc` is installed - copy
  it to `libpng.pc`.
- `aclocal` needs SDL2's `sdl2.m4` (from the SDL2 source tree) in
  `/c/msys64/usr/share/aclocal/`, or `platform/vita/automagic` dies on
  `AM_PATH_SDL2`.
- This shell sets `NoDefaultCurrentDirectoryInExePath=1`; a `.bat` that runs
  MSVC builds has to clear it or `cmd` cannot find programs in the cwd.

## The packaging wall: vita-elf-create crashes on big binaries

`vita-elf-create` dies with a heap corruption (`0xC0000374`, exit 127 under
bash) partway through module-info creation. It is **size dependent**, not a
bad relocation or a bad tool build:

| binary | relocations | text | result |
|---|---|---|---|
| `-O2 -g` then `strip --strip-debug` | 192,569 | 0x6afc7c | crashes |
| `-Os -g0` | 160,900 | 0x61631c | converts fine |

Ruled out: tool version (2026 and 2022 builds crash identically), the strip
flag, weak vs regular PowerVR stubs, TLS (none), GOT/PIC relocations (none),
`sceLibcHeapSize`-style symbols, section count (54), and C++ exceptions --
small C++ binaries with the same relocation types convert fine. Upstream has
a similar open report (vitasdk/vita-toolchain#274, godot).

So: **build with `-g0` and keep the binary small** (`-ffunction-sections
-fdata-sections -Wl,--gc-sections`). If a build starts crashing the tool
again, shrink it rather than hunting relocations. The shipped build
(`-O2` + NEON tuning + section GC) lands at 184,126 relocations and converts,
so the wall sits between 184k and 192k on this binary.

## Flags worth copying from Rinnegatamante's ports

His Vita ports (DaedalusX64-vitaGL, lpp-vita) build with:

    -march=armv7-a -mtune=cortex-a9 -mfpu=neon -mfloat-abi=hard
    -fno-optimize-sibling-calls -fno-lto

and set `ATTRIBUTE2=12` in `param.sfo` (`VITA_MKSFOEX_FLAGS "-d ATTRIBUTE2=12"`),
which asks for the extended memory mode -- relevant here because the runtime
requests a 196 MB newlib heap. `build_game_vpk.py --extended-memory` does the
same. He also uses `-ffast-math`, which is deliberately **not** copied: it
changes float semantics across a whole game engine for unclear gain.

## Build

```sh
git clone https://github.com/isage/love vendor/love-vita
cd vendor/love-vita
git checkout 6633ca5ba9294cd735c62ca519a9ea3a9870e0bb
git apply ../../patches/love-vita-psp2.patch
platform/vita/automagic          # under MSYS2 bash
FLAGS='-O2 -g0 -march=armv7-a -mtune=cortex-a9 -mfpu=neon -mfloat-abi=hard
       -fno-optimize-sibling-calls -ffunction-sections -fdata-sections'
./configure --host=arm-vita-eabi --prefix=$VITASDK/arm-vita-eabi/ \
  --disable-shared --enable-static \
  --with-lua=luajit --with-luaversion=2.1 \
  --disable-library-enet --disable-library-luasocket \
  CFLAGS="$FLAGS" CXXFLAGS="$FLAGS" LDFLAGS='-Wl,--gc-sections'
make -j12
vita-elf-create -s ./src/love ./love.velf && vita-make-fself ./love.velf ./love.self
```

Two build-order traps: libtool records link flags inside `src/liblove.la`, so
after changing `.pc` files delete `src/liblove.la src/.libs/liblove.*` or the
stale flags come back; and `-lpthread` must appear exactly once (it arrives
via LÖVE's own check, and `openal.pc` used to add `-pthread` as well, which
made every pthread symbol a duplicate definition).

`PKG_CONFIG_PATH` and `PKG_CONFIG_LIBDIR` must both point at
`C:/vitasdk/arm-vita-eabi/lib/pkgconfig`, and `C:/vitasdk/bin` must be on PATH.

The resulting `love.self` replaces `eboot.bin` in the VPK
(`build_game_vpk.py --eboot <path>`).

For the Emerald world-entry shader crash after engine `e3b3d5aa`, use the
[incremental shader guard and logging rebuild](docs/shader-link-diagnostics.md).
It reuses the existing configured runtime and preserves local native fixes.

## Runtime settings in the saved patch

`LOVE_VITA_HEAP_MB` defaults to 196 (overridable at compile time); the JIT pool
remains 4 MB and libc heap 16 MB. Package with extended memory, which the game
packer now enables by default. `LOVE_VITA_HEAP_MB=256` is not the saved setting.

Rear touch is disabled before SDL initializes. Non-indexed native draws advance
vertex binding offsets and use `first=0`; `advanceVertexOffsets` is declared
before its first use. Existing indexed draw paths remain in place. Voxel mods are out of scope;
mesh splitting and voxel-specific renderer work are no longer planned.

After native source changes, rebuild and repackage; updating `game.love` alone
cannot change `eboot.bin`:

```sh
make -j12
vita-elf-create -s ./src/love ./love.velf
vita-make-fself ./love.velf ./love.self
cd ../..
python build_game_vpk.py --engine B:/gen1recomp --eboot vendor/love-vita/love.self
```
