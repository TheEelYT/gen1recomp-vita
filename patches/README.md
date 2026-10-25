# Native patches

The C changes that make the Vita build work. They live here as patches because
the trees they apply to are under `vendor/`, which `.gitignore` excludes (about
a gigabyte of toolchain, GPU blobs and a ROM). Without these files the port is
not reproducible from a fresh clone.

The LuaJIT and LOVE patches were checked with `--dry-run` against pristine sources.

## `vitagl-shader-link-guard.patch`

An incremental guard for vitaGL's deferred shader compilation. Failed stage
compilation must leave link status false instead of passing a null program to
SceGxm. It also captures compiler errors and failed source when logging is
enabled. See [the rebuild instructions](../docs/shader-link-diagnostics.md).
Apply this to the existing vitaGL source, preserving local changes; do not
reapply the full LOVE or LuaJIT patches to a previously patched runtime.

## `love-vita-process-exit.patch`

An incremental application-close workaround for the font-atlas allocator fault.
After G1R completes its shutdown hooks, native main finishes GPU work and exits
the process without running the crashing graphics finalizers. This does not
repair the underlying invalid free. See [the evidence and rebuild steps](../docs/process-exit.md).
The existing rebuild helper applies both incremental patches.

The current version calls `_sceKernelExitProcessForUser`, the raw process
export, after the earlier high-level call still reached runtime teardown.
`love-vita-process-exit-raw-upgrade.patch` upgrades a runtime that already has
the earlier workaround. The helper selects the applicable patch, checks the
SDK stub, and adds its library without replacing the runtime's existing link
settings. See [the matching audio-worker dump and rebuild](../docs/raw-process-exit.md).

The later field crash also reaches texture deletion during ordinary Lua GC.
See [the graphics-heap candidate](../docs/graphics-heap.md) for the matching
`love(4)` trace and the opt-in rebuild with vitaGL's supported custom allocator.
This uses a build flag and adds no further native source patch.

## `luajit-vita-psp2.patch`

Applies to **SonicMastr/LuaJIT-Vita branch `v2.1`**, commit
`c329ddd10691c1875f26087ba23c2ae278515e24` — the exact tree vdpm packages as
`luajit` 2.1.0-beta3.

```sh
curl -L -o luajit-vita.tar.gz \
  https://codeload.github.com/SonicMastr/LuaJIT-Vita/tar.gz/c329ddd10691c1875f26087ba23c2ae278515e24
mkdir luajit-vita-src && tar xzf luajit-vita.tar.gz -C luajit-vita-src --strip-components=1
cd luajit-vita-src && patch -p1 < ../patches/luajit-vita-psp2.patch
```

Then build and install with `../build_luajit.sh install`, which also verifies
the result (see below).

Four files:

- **`lj_mcode.c`** — the executable-memory pool. `sceKernelAllocMemBlockForVM`
  takes no address, so LuaJIT's careful hint is discarded and the kernel puts
  every block after the newlib heap, ~140 MB past the code and far outside the
  ±14 MB an ARM relative branch reaches. Areas are now carved out of one pool
  that `love.cpp` reserves *before* the heap exists, which also sidesteps the
  kernel refusing VM blocks under 1 MB. Also: the instruction-cache flush uses
  the pool's known block uid instead of looking one up by an address rounded
  down to a megabyte (that only ever matched when each area was its own block),
  and the VM domain is no longer toggled per trace, because it is process-wide
  and LÖVE's audio workers raced it.
- **`lj_jit.h`** — `jit_State.postproc` becomes `uint8_t`. It was an enum, and
  the ARM EABI sizes enums as small as possible while an x86 host compiler
  gives them 4 bytes. Two `uint8_t` fields follow, so nothing absorbed the
  difference and every field from `trace` on sat 4 bytes later in buildvm's
  view than in the library's. **That is the bug in the shipped vdpm package**:
  the VM read `J->trace` at +272 while the library wrote it at +268, so
  entering a trace loaded the adjacent `freetrace` (= 1) and jumped through it.
- **`lj_dispatch.h`** — `align1`/`align2` padded to 1..16 instead of 0..15.
  The count can be zero, and a zero-length array is a gcc extension MSVC
  rejects, which matters because buildvm has to be built with the host
  compiler and has to see exactly this layout.
- **`lj_ircall.h`** — accept `_MSC_VER` for the fp64 helper names. buildvm only
  writes them into a table; the target is always gcc.

`build_luajit.sh` disassembles `lj_BC_JLOOP` in the result and refuses to
install unless the offset it encodes equals `GG_DISP2J + offsetof(jit_State,
trace)` computed for the target. Any host/target layout drift is caught before
anything reaches a console.

## `love-vita-psp2.patch`

Applies to isage/love commit `6633ca5ba9294cd735c62ca519a9ea3a9870e0bb`
in `vendor/love-vita` (a git tree, so
`git apply` works and `git apply --reverse --check` confirms a match).

```sh
cd vendor/love-vita && git apply ../../patches/love-vita-psp2.patch
```

Six files:

- **`love.cpp`** — retains the 196 MB heap and disables rear touch before SDL
  initialization; replaces libc's `sbrk.o` wholesale (all four symbols, or the
  linker pulls the original back for the ones left out) so the LuaJIT code pool
  is reserved *before* `_init_vita_heap` creates the heap; that is what puts it
  inside branch range. Also opens the VM domain once for good, a mutex for the
  pool's free-page bitmap, the startup report in `ux0:data/g1r-mem.txt`, and
  the frame log in `ux0:data/g1r-frames.txt` (only frames over 250 ms, so it
  cannot distort what it measures).
- **`modules/thread/LuaThread.cpp`** — `jit.off()` in every worker state.
  Measured by elimination: one state compiling repeatedly is fine, three more
  running interpreted alongside it are fine, but the moment those states
  compile too the process dies.
- **`modules/window/sdl/Window.cpp`** — request an ES 2.0 context (vitaGL
  reports "OpenGL ES 2.0"), log SDL's failures, and write the real window and
  drawable sizes to `ux0:data/g1r-screen.txt`. That report is what found the
  window sitting at 1024x768 on a 960x544 panel.
- **`modules/graphics/opengl/Graphics.cpp`** — advances vertex-buffer offsets
  for non-indexed draws on Vita and passes `first=0` to vitaGL. Includes the
  forward declaration needed before `Graphics::draw`.
- **`modules/graphics/opengl/OpenGL.cpp`** — assume highp in fragment shaders.
  vitaGL has no `glGetShaderPrecisionFormat`, and a null check is not enough
  because the missing symbol resolves to a non-null address.
- **`modules/graphics/opengl/Shader.cpp`** — skip the uniform readback loop;
  vitaGL has no `glGetUniformfv`/`glGetUniformiv`.

Note `git diff` on that tree also shows `platform/vita/*` churn (`compile`,
`ltmain.sh`, `depcomp`, `debian/*`). Those are autotools regenerating its own
scaffolding and are deliberately left out of the patch.
