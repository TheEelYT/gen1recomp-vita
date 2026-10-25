#!/usr/bin/env bash
# Run in MSYS2 bash. Reuse the existing configured runtime and local fixes.
set -euo pipefail

port_dir=$(cd "$(dirname "$0")/.." && pwd)
vitagl_dir=${1:-/b/vitagl-test}
runtime_dir=${2:-/b/gen1recomp-vita/vendor/love-vita}
patch_file="$port_dir/patches/vitagl-shader-link-guard.patch"
exit_patch="$port_dir/patches/love-vita-process-exit.patch"
jobs=${G1R_BUILD_JOBS:-12}
custom_heap=${G1R_CUSTOM_HEAP:-0}
case "$custom_heap" in
  0|1) ;;
  *) echo "G1R_CUSTOM_HEAP must be 0 or 1" >&2; exit 1 ;;
esac
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
for tool in git make arm-vita-eabi-gcc arm-vita-eabi-nm vita-elf-create vita-make-fself; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
if [[ "$custom_heap" == 1 ]]; then
  git -C "$vitagl_dir" grep -q 'HAVE_CUSTOM_HEAP' -- Makefile || {
    echo "This vitaGL tree does not advertise HAVE_CUSTOM_HEAP; retain the existing runtime." >&2
    exit 1
  }
fi

# Keep the old device binary and symbol file once, without overwriting a backup.
backup_dir="$port_dir/baselines/before-process-exit"
if [[ "$custom_heap" == 1 ]]; then
  backup_dir="$port_dir/baselines/before-graphics-heap"
fi
mkdir -p "$backup_dir"
for name in love.self src/love; do
  if [[ -f "$runtime_dir/$name" && ! -e "$backup_dir/$(basename "$name")" ]]; then
    cp "$runtime_dir/$name" "$backup_dir/$(basename "$name")"
  fi
done

# Check both trees before modifying either one. Never reset/pull either tree.
apply_shader=0
apply_exit=0
if ! git -C "$vitagl_dir" apply --reverse --check "$patch_file" 2>/dev/null; then
  git -C "$vitagl_dir" apply --check "$patch_file"
  apply_shader=1
fi
if ! git -C "$runtime_dir" apply --reverse --check "$exit_patch" 2>/dev/null; then
  git -C "$runtime_dir" apply --check "$exit_patch"
  apply_exit=1
fi
if [[ "$apply_shader" == 1 ]]; then
  git -C "$vitagl_dir" apply "$patch_file"
fi
if [[ "$apply_exit" == 1 ]]; then
  git -C "$runtime_dir" apply "$exit_patch"
fi
echo "Shader diagnostics and process-exit patches are applied."

# Verify the actual library and linked ELF, not just the requested make flag.
mkdir -p "$port_dir/build"
allocator_report="$port_dir/build/graphics-heap-symbols.txt"
echo "G1R_CUSTOM_HEAP=$custom_heap" > "$allocator_report"
verify_allocator() {
  local binary=$1 symbols
  symbols=$(arm-vita-eabi-nm --defined-only "$binary" |
    awk '$NF == "tm_alloclist" || $NF == "mempool_mspace" { print }')
  printf '%s\n%s\n' "$binary" "$symbols" >> "$allocator_report"
  if [[ "$custom_heap" == 1 ]]; then
    if ! awk '$NF == "tm_alloclist" { found=1 } END { exit !found }' <<< "$symbols"; then
      echo "Custom heap missing from $binary; stopping before packaging a runtime." >&2
      exit 1
    fi
    if awk '$NF == "mempool_mspace" { found=1 } END { exit !found }' <<< "$symbols"; then
      echo "Mixed graphics allocators in $binary; stopping." >&2
      exit 1
    fi
  else
    if ! awk '$NF == "mempool_mspace" { found=1 } END { exit !found }' <<< "$symbols"; then
      echo "Expected sceClibMspace allocator missing from $binary; stopping." >&2
      exit 1
    fi
  fi
}

# Make does not track flag changes: clean objects so the logger is compiled in.
make -C "$vitagl_dir" clean
make -C "$vitagl_dir" -j"$jobs" install \
  SAFE_DRAW=1 NO_SPLASHSCREEN=1 HAVE_SHARK_LOG=1 LOG_ERRORS=1 \
  NO_DEBUG=0 HAVE_CUSTOM_HEAP="$custom_heap"
verify_allocator "$vitagl_dir/libvitaGL.a"

# Force a relink with the new static library; retain configure flags/heap size.
touch "$runtime_dir/src/modules/graphics/opengl/Shader.cpp"
make -C "$runtime_dir" -j"$jobs"
verify_allocator "$runtime_dir/src/love"
(
  cd "$runtime_dir"
  vita-elf-create -s ./src/love ./love.velf
  vita-make-fself ./love.velf ./love.self
)
echo "Native runtime rebuilt: $runtime_dir/love.self"
echo "Graphics allocator verification: $allocator_report"
echo "Now repackage with build_game_vpk.py using that --eboot."
