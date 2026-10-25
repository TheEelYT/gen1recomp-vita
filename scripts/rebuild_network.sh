#!/usr/bin/env bash
# Add native HTTPS to the existing, working Vita runtime without reconfiguring it.
set -euo pipefail
port_dir=$(cd "$(dirname "$0")/.." && pwd)
vitagl_dir=${1:-/b/vitagl-test}
runtime_dir=${2:-/b/gen1recomp-vita/vendor/love-vita}
export VITASDK=${VITASDK:-/c/vitasdk}
if command -v cygpath >/dev/null 2>&1; then VITASDK=$(cygpath -u "$VITASDK"); fi
export PATH="$VITASDK/bin:$PATH"
export PKG_CONFIG_PATH="$VITASDK/arm-vita-eabi/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"
export G1R_CUSTOM_HEAP=${G1R_CUSTOM_HEAP:-1}
export G1R_HTTP_BUILD=1
for tool in git pkg-config arm-vita-eabi-g++; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
[[ -f "$runtime_dir/src/Makefile" ]] || { echo "No configured LOVE runtime at $runtime_dir" >&2; exit 1; }
if ! pkg-config --exists libcurl; then
  echo "Install the SDK curl package first: vdpm install curl" >&2
  exit 1
fi
curl_features=$(pkg-config --variable=supported_features libcurl)
if [[ " $curl_features " != *" SSL "* ]]; then
  echo "The SDK libcurl package does not advertise SSL. Install a TLS-enabled package: vdpm install curl" >&2
  exit 1
fi
# SDK packages may carry a CI prefix. Override prefix locally, without editing .pc files.
curl_libs=$(pkg-config --define-variable=prefix="$VITASDK/arm-vita-eabi" --static --libs libcurl)
curl_cflags=$(pkg-config --define-variable=prefix="$VITASDK/arm-vita-eabi" --cflags libcurl)
# Keep one spelling of pthread in the imported flags; LOVE already links pthread.
curl_libs=$(printf '%s\n' "$curl_libs" | awk '{for(i=1;i<=NF;i++) if($i!="-pthread" && $i!="-lpthread") printf "%s ",$i}')
mkdir -p "$port_dir/build"
probe_dir=$(mktemp -d "$port_dir/build/network-link.XXXXXX")
trap 'rm -rf "$probe_dir"' EXIT
cat > "$probe_dir/probe.cpp" <<'CPP'
#include <curl/curl.h>
int main() {
  curl_global_init(CURL_GLOBAL_DEFAULT);
  CURL *c = curl_easy_init();
  curl_easy_cleanup(c);
  return curl_version_info(CURLVERSION_NOW)->features & CURL_VERSION_SSL ? 0 : 1;
}
CPP
# Intentional word splitting for pkg-config's compiler/linker flags.
arm-vita-eabi-g++ -Wl,-q $curl_cflags "$probe_dir/probe.cpp" \
  -Wl,--start-group $curl_libs -lSceNet_stub -lpthread -Wl,--end-group -o "$probe_dir/probe.elf"

http_patch="$port_dir/patches/love-vita-http.patch"
apply_http=0
if ! git -C "$runtime_dir" apply --reverse --check "$http_patch" 2>/dev/null; then
  git -C "$runtime_dir" apply --check "$http_patch"
  apply_http=1
fi
backup="$port_dir/baselines/before-network"
mkdir -p "$backup"
for name in love.self src/love src/modules/system/wrap_System.cpp; do
  [[ ! -f "$runtime_dir/$name" || -e "$backup/$(basename "$name")" ]] || cp "$runtime_dir/$name" "$backup/$(basename "$name")"
done
if [[ "$apply_http" == 1 ]]; then git -C "$runtime_dir" apply "$http_patch"; fi
cp "$port_dir/native/vita_http_bridge.h" "$runtime_dir/src/modules/system/vita_http_bridge.h"
# A separate generated fragment allows refreshed package flags on each rebuild.
printf 'override CPPFLAGS += %s\noverride LIBS := $(filter-out -pthread -lpthread,$(LIBS)) -Wl,--start-group %s -lSceNet_stub -lSceNetCtl_stub -lSceSysmodule_stub -lpthread -Wl,--end-group\n' \
  "$curl_cflags" "$curl_libs" > "$runtime_dir/src/g1r-http-libs.mk"
if ! grep -Fxq 'include g1r-http-libs.mk' "$runtime_dir/src/Makefile"; then
  printf '\n# G1R_HTTP_LIBS\ninclude g1r-http-libs.mk\n' >> "$runtime_dir/src/Makefile"
fi
touch "$runtime_dir/src/modules/system/wrap_System.cpp"
bash "$port_dir/scripts/rebuild_shader_diagnostics.sh" "$vitagl_dir" "$runtime_dir"
echo "HTTPS runtime rebuilt. Repackage the VPK to include its CA certificate bundle."
