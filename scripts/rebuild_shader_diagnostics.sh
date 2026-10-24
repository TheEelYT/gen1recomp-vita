#!/usr/bin/env bash
# Run in MSYS2 bash. Reuse the existing configured runtime and local fixes.
set -euo pipefail

port_dir=$(cd "$(dirname "$0")/.." && pwd)
vitagl_dir=${1:-/b/vitagl-test}
runtime_dir=${2:-/b/gen1recomp-vita/vendor/love-vita}
patch_file="$port_dir/patches/vitagl-shader-link-guard.patch"
jobs=${G1R_BUILD_JOBS:-12}
export VITASDK=${VITASDK:-/c/vitasdk}
if command -v cygpath >/dev/null 2>&1; then
  VITASDK=$(cygpath -u "$VITASDK")
fi
export PATH="$VITASDK/bin:$PATH"
export PKG_CONFIG_PATH="$VITASDK/arm-vita-eabi/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"

[[ -f "$vitagl_dir/source/custom_shaders.c" && -f "$vitagl_dir/Makefile" ]] || {
  echo "No vitaGL source/Makefile at $vitagl_dir" >&2; exit 1;
}
[[ -f "$runtime_dir/Makefile" && -f "$runtime_dir/src/modules/graphics/opengl/Shader.cpp" ]] || {
  echo "No configured LOVE runtime at $runtime_dir" >&2; exit 1;
}
for tool in git make arm-vita-eabi-gcc vita-elf-create vita-make-fself; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done

# Keep the old device binary and symbol file once, without overwriting a backup.
backup_dir="$port_dir/baselines/before-shader-diagnostics"
mkdir -p "$backup_dir"
for name in love.self src/love; do
  if [[ -f "$runtime_dir/$name" && ! -e "$backup_dir/$(basename "$name")" ]]; then
    cp "$runtime_dir/$name" "$backup_dir/$(basename "$name")"
  fi
done

if git -C "$vitagl_dir" apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Shader diagnostics patch already applied."
else
  # Both checks complete before modifying any source. Never reset/pull this tree.
  git -C "$vitagl_dir" apply --check "$patch_file"
  git -C "$vitagl_dir" apply "$patch_file"
fi

# Make does not track flag changes: clean objects so the logger is compiled in.
make -C "$vitagl_dir" clean
make -C "$vitagl_dir" -j"$jobs" install \
  SAFE_DRAW=1 NO_SPLASHSCREEN=1 HAVE_SHARK_LOG=1 LOG_ERRORS=1

# Force a relink with the new static library; retain configure flags/heap size.
touch "$runtime_dir/src/modules/graphics/opengl/Shader.cpp"
make -C "$runtime_dir" -j"$jobs"
(
  cd "$runtime_dir"
  vita-elf-create -s ./src/love ./love.velf
  vita-make-fself ./love.velf ./love.self
)
echo "Native runtime rebuilt: $runtime_dir/love.self"
echo "Now repackage with build_game_vpk.py using that --eboot."
