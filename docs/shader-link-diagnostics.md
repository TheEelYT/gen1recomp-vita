# World entry shader failure

The October 24 build with engine `e3b3d5aa` reached Emerald's title screen and
completed the Birch new-game sequence on hardware. The next dump is a CPU data
abort, with a null argument inside SceGxm, called from native `glLinkProgram`.
The graphics log ends at program 9's link. Captured compiler structures contain
`amask`, `dlut` and `mode`, identifying the RSE field-weather sprite shader.
The compiler's actual error message is absent. This does not establish whether
its failure came from source translation, compiler limits or memory pressure.

`patches/vitagl-shader-link-guard.patch` checks both compiled stage pointers
after deferred GLSL compilation, before uniform reflection. Failed compilation
leaves `GL_LINK_STATUS` false so LOVE can raise a catchable shader error rather
than passing null into SceGxm. The field-weather module already handles that
error with `pcall`; weather color effects may be unavailable until the shader's
underlying compiler error is fixed.

With `HAVE_SHARK_LOG=1 LOG_ERRORS=1`, the patch writes compiler messages to
`ux0:/data/g1r-shaders.txt` and saves each failed stage's translated source as
`g1r-shader-failed-vertex.cg` or `g1r-shader-failed-fragment.cg` in that directory.
The log appends across launches; each stage source replaces its preceding
failure. These are diagnostics, and a successful boot is not proof that all
weather effects work.

The patch was applied to vitaGL `76f43e6fbe1513cee44118da7ff2c16728c4fed2` for
host validation. It uses small context hunks to support an existing older local
tree. The helper stops if those hunks do not apply; it never fetches, checks out
or resets vitaGL or LOVE. Keep their existing local changes. The helper retains
the runtime's existing configure flags, including its heap size and LuaJIT build.
Its vitaGL flags match our prior SAFE_DRAW/no-splash build plus compiler logging.

## Rebuild on the existing Windows setup

Update the packager checkout in PowerShell:

```powershell
git -C B:\gen1recomp-vita-standard fetch origin main
git -C B:\gen1recomp-vita-standard merge --ff-only origin/main
```

In an **MSYS2 terminal**, run:

```sh
bash /b/gen1recomp-vita-standard/scripts/rebuild_shader_diagnostics.sh
```

The default source paths are `/b/vitagl-test` (from the uploaded runtime's debug
information) and `/b/gen1recomp-vita/vendor/love-vita`. To use different existing
folders, pass the vitaGL and LOVE paths as the first and second arguments.
If it reports missing folders or a patch conflict, retain the message and stop.
It backs up the previous `love.self` and `src/love` under the ignored
`baselines/before-shader-diagnostics/` directory once.

Then repackage in PowerShell, keeping the current engine:

```powershell
Set-Location B:\gen1recomp-vita-standard
python build_game_vpk.py `
  --engine B:/gen1recomp-standard `
  --eboot B:/gen1recomp-vita/vendor/love-vita/love.self
```

Install `build\gen1recomp-vita.vpk` and retry entering the world. Keep the marker
on `trace`. No Emerald re-import is needed. Copy `g1r-shaders.txt`, any
`g1r-shader-failed-*.cg`, and `g1r-gfx.txt` after the attempt, plus any new dump.

Host checks exercise the guard's C control flow with absent and failed stages,
logging enabled/disabled and failed-source capture. They do not compile the
complete native library or test Vita execution; VitaSDK is unavailable here.

The current helper also applies the [application-close workaround](process-exit.md)
and keeps a new backup under `baselines/before-process-exit/`. Follow that page
for the latest close-test instructions. The original shader guard remains applied.
