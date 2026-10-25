# Vita HTTPS: save sync and mod downloads

The raw process-exit build was confirmed on hardware on 2026-10-25: returning
from Emerald and closing G1R both completed without a crash. The supplied
shutdown log ends with `native GPU finish complete; raw process exit`.
This networking candidate retains that exit path, the custom graphics heap,
the existing configured runtime heap, and engine image/audio settings.
Loading pauses and shader compilation failures remain open.

**Device confirmation, 2026-10-25:** the user successfully downloaded a mod
and used save sync with engine `01970377` and packager `1e72d30`. This establishes
that the native HTTPS build works for both flows on the Vita. Interrupted
transfers and Wi-Fi reconnect behavior still need separate device checks.

The subsequent large HnS cart download passed its hash gate but failed during
asset extraction. See [the cooperative installer update](vita-mod-install.md)
for the separate install-memory/progress candidate and retry instructions.

## Update and build

In PowerShell, fast-forward the standard checkouts:

```powershell
git -C B:\gen1recomp-standard fetch origin dev
git -C B:\gen1recomp-standard merge --ff-only origin/dev
git -C B:\gen1recomp-vita-standard fetch origin main
git -C B:\gen1recomp-vita-standard merge --ff-only origin/main
```

In the existing MSYS2 environment that builds the Vita runtime:

```sh
export VITASDK=/c/vitasdk
export PATH="$VITASDK/bin:$PATH"
vdpm install curl
bash /b/gen1recomp-vita-standard/scripts/rebuild_network.sh
```

The curl package brings its TLS dependencies. There is no requirement to
refresh the whole SDK, rerun configure, reset the native tree, or reapply the
full Vita patch. The current official SDK recipe builds curl with OpenSSL,
zlib and zstd; the helper reads the installed static link flags from pkg-config.
See [the SDK recipe](https://github.com/vitasdk/packages/blob/master/curl/VITABUILD)
and [vdpm usage](https://github.com/vitasdk/vdpm#usage).

The helper defaults to the known source folders `/b/vitagl-test` and
`/b/gen1recomp-vita/vendor/love-vita`. To override them, pass those two folders
in that order. Custom graphics allocation defaults to enabled. The helper
checks curl's advertised SSL feature, performs a target link probe, preflights
the incremental HTTP patch, and saves the old SELF, ELF and system wrapper
once under `baselines/before-network`. It copies the bridge header and writes
a marked Makefile include with the installed curl link flags, retaining local
source changes and existing configure settings. It then runs the existing
shader/raw-exit rebuild helper. The linked ELF must contain curl and raw-exit
symbols and the requested allocator before a new SELF is generated.

Back in PowerShell:

```powershell
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install `build\gen1recomp-vita.vpk`. Repackaging the full VPK is required:
the native TLS certificate bundle lives outside `game.love`. No ROM re-import
or cache deletion is required. Keep GPU tracing disabled.

## First device checks

1. With Wi-Fi connected, open Find Mods and refresh the catalog. Try a mod
   download, then its existing import flow. The bridge streams downloads to
   storage; it does not retain an entire archive in a Lua string.
2. Open save sync, link with the existing account codes, and retrieve a save.
   Keep a copy of the current local save before choosing a different version.
   Test uploads separately after confirming the downloaded save opens.
3. Close G1R during a transfer, relaunch, and retry. Then test a disconnected
   request and retry after restoring Wi-Fi. Shutdown cancels native transfers
   before joining the fetch workers; a new pool resets cancellation.

For failures, retain the visible message and `ux0:/data/g1r-network.txt`, plus
`g1r-shutdown.txt` if closing stalls or crashes. The bounded network report
records backend version, method, hostname, HTTP status, received byte count and
curl code. It does not record full URLs, query strings, authentication headers,
account codes or save bodies. Early validation/initialization errors may only
appear in the UI. A new crash also needs its matching rebuilt `src/love` ELF.

## Transport behavior and limits

The native `love.system` module exposes GET, streamed download, generic request
and cancellation functions in every Lua state. Its `_vitaHttp` marker selects
the bridge even in workers without `POKEPORT_VITA`. Desktop shell probing and
self-updating remain disabled on Vita. Existing sync and mod UI paths use
their normal Fetch workers. Native transfers are serialized to bound TLS
memory, while the UI thread continues rendering.

Only HTTPS is accepted, with CA and hostname verification and TLS 1.2 or newer.
Public GET/download requests follow HTTPS redirects for GitHub assets.
Generic authenticated sync requests do not follow redirects, so custom sync
headers cannot be forwarded to a different host. GET/POST/PUT/DELETE, binary
bodies, and HTTP conflict responses are supported.

Default buffered replies are limited to 4 MiB; request bodies to 8 MiB, and
streamed downloads to 256 MiB. Large Box Sync payloads may exceed these Vita
limits and fail with a transfer-limit message. Mod extraction and compression
still use the engine's existing paths and require separate memory validation.
Timeouts are bounded at the curl transfer level. The SDK recipe uses a blocking
DNS resolver, so cancellation/timeout responsiveness during DNS still needs
device testing. A temporary sibling file is removed on failed native downloads
and renamed on success; the upstream fetch worker removes its destination
before starting, so this does not preserve an old cached destination end to end.

## CA bundle provenance

`native/cacert.pem` is the unmodified certifi/Mozilla bundle from
[python-certifi commit b60466c9f2882d9cf088943c650b0faac06c080c](https://github.com/certifi/python-certifi/blob/b60466c9f2882d9cf088943c650b0faac06c080c/certifi/cacert.pem)
(2026.10.23). SHA-256:

```text
2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b
```

The VPK includes `cacert.pem`, `CA-LICENSE` and `NETWORK-LICENSES.txt` at its
root. Future CA refreshes should use the upstream bundle and update this pin.

## Verification

Twenty packager/native host tests pass. They compile the production transport
and Lua wrappers against host libcurl and real LuaJIT, with Vita API shims and
a local TLS server. Coverage includes certificate/hostname rejection, signed
binary requests, conflicts, redirects, streaming, truncation, limits, timeouts,
cancellation, retry, native build preflight and packaging. The HTTP patch also
applies and reverse-checks against the real LOVE base after the full Vita and
raw-exit patches, with a local source change retained.

The engine's new Vita integration test passes 24 checks, and existing host
HTTP, platform and sync suites pass. The broader engine group retains three
baseline/environment failures: missing `javac`, an NX quit fixture missing its
VitaShutdown stub, and an NX worker fixture missing `love.data`. The latter two
were reproduced with the unchanged engine sources. The subsequent Windows
build and successful Vita mod-download/save-sync tests are recorded above.
