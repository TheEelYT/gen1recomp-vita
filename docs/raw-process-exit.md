# Raw process exit after the audio-worker shutdown crash

The uploaded `love(5)` ELF matches dump `1792907482`: code maps at `0x81042000`,
with reported RX size `0x6bbd10`; the ELF link base is `0x81000000`. The ELF has
`tm_alloclist`, and the dump has the custom allocator's named heap mutexes.
The custom graphics allocator was therefore active in this run.

The faulting thread is `@src/core/game3/m4a_worker.lua`, not the graphics collector.
PC `0x81047efc` maps to ELF `0x81005efc`, the native type registry's hash-table
lookup. The selected return addresses resolve to `Type::byName`, `w__typeOf`,
Lua's C-call dispatch, `coroutine.resume`, `lua_pcall` and `LuaThread::threadFunction`.
The worker is accessing the process-wide LÖVE type registry.

The main-thread stack includes `_start`, `exit`, `_exit` and Vita descriptor
cleanup. The uploaded shutdown report reaches the old marker
`native GPU finish complete; exiting process`. Taken together, the evidence
points to an exit-time worker/registry lifetime fault: a Lua worker is still
executing while C-runtime cleanup has begun. It does not establish why that
worker was not joined, nor rule out earlier corruption. This is a different
crash path from the previous palette-texture free.

The earlier workaround called the higher-level `sceKernelExitProcess` export.
This run still reached C-runtime teardown, so that call did not achieve the
intended bypass. The replacement calls `_sceKernelExitProcessForUser`, the raw
user export that terminates the process without entering registered runtime
exit trampolines. It runs only after G1R's completed real-quit flag, `glFinish`
and stream flushing. Restarts and unflagged games keep normal teardown.

The raw user export is in the SDK's September 2026 database:
[SceProcessmgr, export `0xC053DC6B`](https://github.com/vitasdk/vita-headers/blob/747f37555fe1b2ca0c81c0b4dd812ed0855e53e7/db/360/SceProcessmgr.yml).
That SDK's header does not declare it, so the patch provides a Vita-only C
declaration. The current [SDK header](https://github.com/vitasdk/vita-headers/blob/master/include/psp2/kernel/processmgr.h)
documents the raw export as non-returning. The helper checks the installed
`libSceProcessmgr_stub.a` before modifying native files and links that library.
No SDK update is required when the existing stub supplies the symbol.

This remains an exit workaround. It does not fix the underlying graphics free,
worker lifecycle, shader compiler failures or loading pauses. The current
allocator and engine `a8704091` stay unchanged for this candidate.

## Build and device check

In PowerShell, update the packager:

```powershell
git -C B:\gen1recomp-vita-standard fetch origin main
git -C B:\gen1recomp-vita-standard merge --ff-only origin/main
```

In MSYS2, retain the custom graphics heap:

```sh
G1R_CUSTOM_HEAP=1 bash /b/gen1recomp-vita-standard/scripts/rebuild_shader_diagnostics.sh
```

The helper handles pristine sources, the previous process-exit patch and an
already-updated runtime. It preflights all native patches, saves the current
`love.self` and `src/love` pair under `baselines/before-raw-process-exit`, and
preserves source fixes and configured heap size. The generated `src/Makefile`
gets one marked `override LIBS += -lSceProcessmgr_stub` line, preserving its
existing libraries and configure settings. It checks the allocator and raw
exit import in the linked ELF before generating a SELF.

In PowerShell:

```powershell
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install `build\gen1recomp-vita.vpk`, keeping GPU tracing off. No ROM re-import or
cache deletion is required. Play Emerald briefly, return to the launcher and
close G1R. The new final marker in `ux0:/data/g1r-shutdown.txt` is:

```text
native GPU finish complete; raw process exit
```

Send that log and `g1r-loads.txt`; retain any new dump with the newly rebuilt
`vendor/love-vita/src/love` ELF. The old `love(5)` no longer matches after this
rebuild. The graphics-heap symbol report also records `G1R_RAW_PROCESS_EXIT=1`.

Host checks exercise the exact guarded raw-exit call, signed status preservation,
restart/unflagged behavior and missing log files. They model the old wrapper
entering cleanup and require the new path to bypass it. The shell tests cover
fresh/legacy/already-patched sources, missing SDK/linked symbols, allocator
checks, backups and source preservation. Both native patch paths were also
applied to the real LOVE base and the saved Vita patch with a 256 MiB override
and a local source marker. These are host checks; a full native build and
on-device validation still require the Windows Vita setup.
