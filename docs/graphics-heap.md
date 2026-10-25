# Graphics heap candidate after the field crash

The subsequent dump confirms this allocator was active and identifies a
different, audio-worker fault during process cleanup. The current next step is
the [raw process-exit candidate](raw-process-exit.md), with this allocator kept
enabled. The latest helper backs up the current runtime under
`baselines/before-raw-process-exit` before upgrading the exit patch.

The October 24 dump `psp2core-1792898060` can now be symbolized with the uploaded
`love(4)` ELF. The main thread faults in SceLibKernel at `0xe0011a8c`, accessing
address `0x4`. Its app code is mapped at `0x8100c000`; subtract `0xc000` to map
code addresses to this ELF's `0x81000000` link address. The writable segment has
a different relocation and must not use the code offset.

The useful return addresses in the main-thread stack resolve as follows:

| Runtime address | ELF address | Caller |
| --- | --- | --- |
| `0x812b4f97` | `0x812a8f96` | `glDeleteTextures`, inline `gpu_free_texture_data`, `gpu_utils.h:184` |
| `0x810d43ad` | `0x810c83ac` | `OpenGL::deleteTexture` |
| `0x810d2901` | `0x810c6900` | `Image` destructor |
| `0x810d89c1` | `0x810cc9c0` | `Shader` destructor, releasing sampler textures |
| `0x8101060f` | `0x8100460e` | `love::w__gc` |
| `0x8141e77c` | `0x8141277c` | `lj_gc_step` |
| `0x81415084` | `0x81409084` | `table.concat` triggering automatic GC |
| `0x8100d5c5` | `0x810015c4` | `main`, resuming the boot coroutine |

These are selected stack return addresses, not an assertion that every word
which resembles a code address is an active frame. The matching call sites,
shader uniform and Image object support the cleanup path. This is ordinary Lua
finalization during execution, not `lua_close` or an audio-worker exception.
The shader uniform is `palTex`; its image object at `0x85c4d280` has texture ID
`0x26` and dimensions 256 by 2, matching the PPU palette image. The graphics
allocator's state includes CDRAM addresses. This establishes the failing free,
not the earlier cause: double release, prior overwrite and pending GPU writes
are not distinguished by this dump.

Engine `a8704091` has already withdrawn the image GC frequency experiment and
retains the conservative pre-image full collections. Keep that engine for this
test. The shared audio bank, shader source, image ownership and application-close
workaround remain in place. Loading pauses are still unresolved.

## Native test

vitaGL at our existing base `76f43e6` supports `HAVE_CUSTOM_HEAP=1`. Its
[README](https://github.com/Rinnegatamante/vitaGL/blob/76f43e6fbe1513cee44118da7ff2c16728c4fed2/README.md)
documents this as a replacement for `sceClibMspace` with additional diagnostics.
The [implementation](https://github.com/Rinnegatamante/vitaGL/blob/76f43e6fbe1513cee44118da7ff2c16728c4fed2/source/utils/mem_utils.c)
uses separate block descriptors and per-pool locking when the collector runs
on a worker thread. This candidate uses that existing implementation without
modifying vitaGL source beyond our previously applied shader guard.

Changing the allocator is a focused diagnostic/compatibility candidate, not a
proven correction of the original corruption. It changes native allocation
layout and adds descriptor storage to the ordinary heap. Hardware stability,
peak memory and performance need device validation. It does not increase the
runtime's configured 256 MiB heap or eliminate the loading pauses.

Update the packager and ensure the engine is at the conservative rollback:

```powershell
git -C B:\gen1recomp-vita-standard fetch origin main
git -C B:\gen1recomp-vita-standard merge --ff-only origin/main
git -C B:\gen1recomp-standard fetch origin
git -C B:\gen1recomp-standard merge --ff-only origin/dev
```

In **MSYS2 bash**, run:

```sh
G1R_CUSTOM_HEAP=1 bash /b/gen1recomp-vita-standard/scripts/rebuild_shader_diagnostics.sh
```

The default source folders remain `/b/vitagl-test` and
`/b/gen1recomp-vita/vendor/love-vita`. The helper preserves their local fixes,
configured heap size and build settings. It checks the existing patches before
applying them and never fetches or resets those native trees. It saves the
previous `love.self` and `src/love` once under
`B:\gen1recomp-vita-standard\baselines\before-graphics-heap`.

The library is rebuilt cleanly with `HAVE_CUSTOM_HEAP=1 NO_DEBUG=0` and the
existing SAFE_DRAW, no-splash and logging flags. The helper checks allocator
symbols in both `libvitaGL.a` and the linked `src/love` before producing the
SELF. A missing custom allocator or mixed allocator symbols stop the build,
preserving the previous `love.self`. The compact verification report is
`build/graphics-heap-symbols.txt`; expect `G1R_CUSTOM_HEAP=1` and `tm_alloclist`
for both binaries, without `mempool_mspace`.

Repackage in **PowerShell**:

```powershell
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install `build\gen1recomp-vita.vpk`. Keep GPU tracing off. No cache deletion or
ROM re-import is required. Try Emerald's intro, continue the save, enter a few
buildings, return to the launcher and close the app. Copy `g1r-loads.txt`,
`g1r-audio.txt` and `g1r-shutdown.txt` from `ux0:/data/`. If it crashes, retain
the new dump and the newly rebuilt `vendor/love-vita/src/love` ELF together.
The old `love(4)` ELF will not match this candidate.

For an immediate binary rollback, copy the saved `before-graphics-heap/love.self`
and `before-graphics-heap/love` back to their original runtime paths, then
repackage. Restore both files as a pair so symbols match. A source rebuild with
`G1R_CUSTOM_HEAP=0` explicitly selects the previous graphics allocator instead.

## Host validation

The rebuild-helper tests execute the real shell script against fake toolchain
commands in isolated temporary folders. They check build flags, clean rebuild,
library and linked-ELF checks, rejection of missing/mixed allocators, patch
conflicts, preservation of the previous SELF, backups and local source fixes.
The packaging, shader guard and native exit-gate tests also pass. These tests
do not compile or execute the Vita allocator. No Vita SDK/device is available
in this workspace, and the candidate must be rebuilt on the Windows setup.
