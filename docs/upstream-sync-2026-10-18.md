# Vita upstream sync — October 18, 2026

Engine branches `dev`, `gba-import-work`, and `vita-audio-higher-rate` now share
merge commit `7f31bca51bb2d9bdd32428a00ee378588ef0170d`. Both parents are retained:
our previous `a85f21a1431b7d533dfe8e35557ea35de506def1` and upstream development
`041e05585059cc9f9af443ca28e7684ebdb420cb` (the engine code in v0.3.90).
`vita-gen3-checkpoint` remains at `d3f8052a` as a historical checkpoint.

The runtime fork already includes Code-Grub upstream `b1d1932`. Its local
patch is checked against isage/love `6633ca5ba9294cd735c62ca519a9ea3a9870e0bb`.

## Integration

Nine engine files conflicted. Resolution retains the Vita audio optimizations,
compact script buffers and packed grid cells, low-memory FRLG tileset loading,
sequential Gen 3 import, virtual filesystem browsing and native pad navigation.
Upstream bulk PCM rendering, SFX prewarming, movement translation, script labels
and precomputed atlas inventories remain available. The compact Vita encoder
now writes the middle atlas layer as well as the under/over layers.

The new upstream restart abstraction needed an explicit Vita gate: the runtime
reports Linux, but returning to the launcher must rebuild inside the same
process. Import GC also recognizes Vita without enabling handheld frame pacing.
The cached stereo pan is refreshed when the underlying track mask changes;
noise-rate calculations invalidate when the sample rate changes.

Runtime packaging now requires the patched LuaJIT 2.1 executable, enables
extended memory by default, includes Emerald/Ruby/Sapphire manifests and skips
PSD source art. `--love-only` validates the payload without native dependencies.
The native patch saves the rear-touch disable, 196 MB heap and zero-first-vertex
binding-offset workaround, including its required forward declaration.

## Validation

- Engine runner: 1,106 of 1,107 suites passed on the first run. The remaining
  CI-group test passed all 298 checks when LuaJIT was put on PATH for its child
  processes. No engine suite remains failing.
- Gen 2 and Gen 3 ROM-free test groups: passed. ROM/cache-dependent suites
  self-skip where their inputs are absent.
- New Vita import equivalence suite: 453/453 checks passed, including identical
  serialized desktop/Vita atlas layers, packed map collisions/elevations,
  precomputed full metatile inventories, and cache readiness.
- Bulk PCM suite: 35/35 checks passed. Audio queue, sample-rate and stereo
  tests also passed in the engine run.
- Packaging tests: 3/3 passed. The real payload built with 2,177 files, all
  eleven manifests, no generated ROM data, and a clean ZIP CRC check.
- Updated native patch applies to pristine pinned LÖVE sources and passes
  reverse application and source whitespace checks.
- Quick runner: 932/946 passed. All fourteen failures are identical on unchanged
  upstream and on the merge (ROM-dependent parity/save-editor fixture tests).
- The top-level Android copy test could not run: this environment has no javac.
  Lua lint was unavailable because luacheck is not installed.

## Hardware follow-up

This environment has no VitaSDK or attached Vita. No new native binary or VPK
has been compiled or tested on hardware. Rebuild LÖVE and package locally using
`TOOLCHAIN.md`, then check boot, controller navigation, Gen 1/2 music at 22050 Hz,
Gen 3 import, returning to the launcher and standard engine rendering.

Scope update: Battle Art and all other voxel mods have been dropped. Their
Sky/Water fallbacks, voxel mesh splitting and cache work are no longer follow-up
tasks or prerequisites for validating the Vita port. Previous voxel experiments
remain historical notes. Native fixes useful to the base engine are retained.

`baselines/` and downloaded/vendor trees remain ignored. Upstream remotes are
fetch-only in the working checkouts; all branch updates target TheEelYT's forks.
