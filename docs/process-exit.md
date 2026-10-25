# Vita application close workaround

The latest candidate replaces the high-level exit call with the raw process
export after dump `1792907482` showed an audio worker executing during runtime
teardown. Follow [the raw-exit instructions](raw-process-exit.md), retaining
`G1R_CUSTOM_HEAP=1` for the next device test. The trace below describes the
original reason for adding a process-exit workaround.

The October 24 dump `psp2core-1792880736` matches the uploaded `love(3)` ELF.
Its main thread faults in SceLibKernel during texture deletion:
`Window::close` → `Graphics::unSetMode` → `Volatile::unloadAll` →
`Font::unloadVolatile` → Image destruction → `gpu_free_texture_data`.
The shutdown breadcrumb stops before explicit window closure completes.
Moving graphics teardown ahead of `lua_close` therefore did not fix it.
The origin of the invalid free remains unresolved.

The newer `1792898060` dump reaches texture deletion during ordinary Lua GC,
where this process-exit workaround does not apply. See the
[graphics-heap investigation and native candidate](graphics-heap.md).

`love-vita-process-exit.patch` is an incremental **exit workaround**. G1R sets
`G1R_VITA_SHUTDOWN_READY` only after its application shutdown hooks complete.
When the boot coroutine then returns a real quit, native main waits for GPU
work with `glFinish`, flushes C streams, and calls `sceKernelExitProcess`.
The OS reclaims process resources without running the failing Lua/graphics
finalizers. Returning to the launcher never sets the flag. A native restart
still uses the ordinary state teardown; an unmodified game never sets the flag.

Update both standard checkouts, then run the existing helper in MSYS2:

```sh
bash /b/gen1recomp-vita-standard/scripts/rebuild_shader_diagnostics.sh
```

The helper now preflights both patches before applying either, backs up the
current runtime under `baselines/before-process-exit`, and preserves existing
local source changes, configure flags and heap settings. Do not reapply the
full LOVE patch to the existing runtime. Then repackage in PowerShell:

```powershell
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install the VPK without deleting data or re-importing. Keep GPU tracing off.
Copy `ux0:/data/g1r-shutdown.txt` after closing; the last expected breadcrumb
is `native GPU finish complete; exiting process`. If it still crashes, also
copy the new dump and rebuilt `vendor/love-vita/src/love` symbol file.

The host test checks the exact exit gate: ordinary quits, restarts and missing
log files, preserving exit status and skipping finalizers only for the flagged
real quit. The patch applies to the pristine LOVE base and on top of the saved
Vita patch. Full target compilation and device behavior require the Vita setup.
