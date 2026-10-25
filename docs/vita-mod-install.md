# Large cart mod installation on Vita

On 2026-10-25, the user imported `pokemon_heart_soul-1.0.22.g1rcart` and retrieved
its save/box data, but installing its pinned `hns_exploration` mod appeared
frozen at 0% and eventually reported that a terrain entry texture could not be
read. The cart pins HnS 0.7.23 with archive SHA-256
`e549a578a5fbfed6400b01f9d9c015c9843ff924211eb9fd630e583c49b0b3e6`.
The matching release ZIP is 10,334,773 bytes. Its download digest also matches
the [release metadata](https://github.com/TheEelYT/g1r-hns/releases/tag/v0.7.23).

The existing launcher verifies that pin before extracting. The reported read
error therefore occurred after archive verification, rather than establishing
a network corruption problem. The copy helper discarded PhysFS's detailed
read error, so the precise cause of that failed read is still unknown.

## Engine changes

The Vita remote-mod installer now mounts the completed ZIP from storage,
avoiding the installer's whole-archive Lua read plus FileData copy. The cart
hash check still reads the archive once before any installed files are changed.
Temporary hash strings are collected before extraction.

Preparation counts files cooperatively. Copying also yields between assets,
with a pump budget of roughly 32 ms or 64 yields per launcher update. One
individual file read, cache compression, or write can still exceed that budget.
The existing compressed `.rgba` cache representation is preserved.

The overlay uses a spinner while native download byte counts are unavailable
and during verification/preparation. Once copying begins, it shows a real
file-based percentage, completed/total files, processed MiB, and the current
filename. An unchanging 0% is no longer used as download progress on Vita.

Failed reads get one retry after collection. Persistent errors include the
full asset path and original filesystem error; short reads are rejected.
The failed archive remains available in the application's save directory.
`ux0:/data/g1r-mod-install.txt` records bounded progress and the terminal result.
This candidate needs a device retry to determine whether the asset failure is
resolved or to obtain its underlying error.

## Slow-install follow-up

The user subsequently reported continued progress at about 2 FPS, reaching
roughly 5,200 of 7,849 files and 270 MB processed after more than 15 minutes.
This confirms progress beyond the earlier failure, but does not yet confirm
successful completion. The MiB counter measures cumulative uncompressed input
processed, not live RAM usage or the compressed size written to storage.

The first cooperative build limited each update to 6 ms/eight yields and still
redrew the complete cartridge/save screen behind the progress overlay. The
performance candidate uses the larger bounded batch above and a Vita-only
progress view that skips hidden cartridge/video/panel rendering and video
updates during installation. Native shutdown and networking remain unchanged.

Vita mod texture writes explicitly select zlib level 1 rather than the ordinary
level 6, preserving the existing cache format and default compression behavior
elsewhere. Lower compression can produce larger stored files. Per-file GC
work is retained. The diagnostic log now records cumulative elapsed, ZIP-read,
compression/write, GC and pump timings to distinguish copy costs from time
between copy slices. A Vita speed comparison remains pending.

Let an already-running installation finish. This performance update is for
subsequent installs; do not interrupt or repeat an otherwise successful HnS
install just to obtain a benchmark.

The shared cache prefix is restored at every yield and on failure. A new
manifest is published after the payload copy, so an interrupted copy cannot
appear ready. User-supplied `baseroms/` files are staged in recovery storage
before replacement deletes the old tree. Recovery persists across application
close and is removed after success. Cart saves and box data are outside these
mod-file paths.

## Update and retry

The existing working HTTPS/raw-exit native runtime is retained. In PowerShell:

```powershell
git -C B:\gen1recomp-standard pull --ff-only origin dev
git -C B:\gen1recomp-vita-standard pull --ff-only origin main
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install `build\gen1recomp-vita.vpk`, keep tracing off, and retry Install Mods
on the existing HnS cart. Neither the cart nor Emerald needs re-importing.
There is no VitaSDK/native rebuild for this change. Once an attempt has returned
an error, that attempt has ended; it is safe to leave the error screen or close
G1R normally. If extraction fails again, retain the exact new message and
`g1r-mod-install.txt`.

## Checks

Host tests exercise the lightweight progress view, bounded larger batches,
fast/default compression compatibility, cooperative preparation/copy progress, disk mounting without
an archive FileData, compressed texture round-trips, retry, detailed read errors,
short reads, cleanup after exceptions, rollback, cache-prefix restoration,
manifest publication, interrupted-update baserom recovery, and the cart hash
gate. Existing cart-fill, launch-update, version-badge, launcher-mod, inbox and
native-HTTP integration tests pass. The built Lua payload is checked against
the source files. These checks do not reproduce the Vita's original PhysFS
failure or establish HnS gameplay compatibility.
