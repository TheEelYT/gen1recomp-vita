"""Network helper preflight, preservation and repeat-build checks without VitaSDK."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("bash"), "requires bash")
class NetworkRebuildTests(unittest.TestCase):
    def setup_build(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        port, runtime, sdk = (root / p for p in ("port", "love", "sdk"))
        for p in (port / "scripts", port / "patches", port / "native", sdk / "bin",
                  runtime / "src/modules/system"):
            p.mkdir(parents=True)
        shutil.copy(ROOT / "scripts/rebuild_network.sh", port / "scripts")
        shutil.copy(ROOT / "patches/love-vita-http.patch", port / "patches")
        shutil.copy(ROOT / "native/vita_http_bridge.h", port / "native")
        (runtime / "src/Makefile").write_text("LIBS = -llocal_fix -lpthread\n")
        (runtime / "src/modules/system/wrap_System.cpp").write_text("local runtime fix\n")
        (runtime / "love.self").write_text("working SELF")
        (runtime / "src/love").write_text("working ELF")
        (port / "scripts/rebuild_shader_diagnostics.sh").write_text(
            'set -eu\n[[ "$G1R_CUSTOM_HEAP" == 1 && "$G1R_HTTP_BUILD" == 1 ]]\n'
            'printf "rebuilt SELF" > "$2/love.self"\n')

        def tool(name, source):
            path = sdk / "bin" / name
            path.write_text("#!/usr/bin/env bash\nset -eu\n" + source)
            path.chmod(0o755)

        tool("pkg-config", r'''
case "$*" in
  *--exists*) [[ "${TEST_FAIL:-}" != package ]] ;;
  *--variable*) [[ "${TEST_FAIL:-}" == ssl ]] || echo 'SSL IPv6' ;;
  *--libs*) echo '-lcurl -lssl -lcrypto -pthread -lpthread' ;;
  *--cflags*) echo '-DCURL_STATICLIB' ;;
esac
''')
        tool("arm-vita-eabi-g++", '[[ "${TEST_FAIL:-}" != link ]]\n')
        tool("git", r'''
if [[ "$*" == *--reverse* ]]; then
  [[ -f "$TEST_RUNTIME/http-patched" ]]; exit
fi
if [[ "$*" == *--check* ]]; then [[ "${TEST_FAIL:-}" != conflict ]]; exit; fi
touch "$TEST_RUNTIME/http-patched"
''')
        env = {**os.environ, "VITASDK": str(sdk), "TEST_RUNTIME": str(runtime)}
        env.pop("G1R_CUSTOM_HEAP", None)
        def run(fail=""):
            return subprocess.run(["bash", str(port / "scripts/rebuild_network.sh"),
                                   str(root / "vitaGL"), str(runtime)],
                                  env={**env, "TEST_FAIL": fail}, capture_output=True, text=True)
        return run, port, runtime

    def test_missing_package_link_failure_or_patch_conflict_preserves_working_runtime(self):
        for failure in ("package", "ssl", "link", "conflict"):
            with self.subTest(failure=failure):
                run, _, runtime = self.setup_build()
                result = run(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((runtime / "love.self").read_text(), "working SELF")
                self.assertEqual((runtime / "src/Makefile").read_text(),
                                 "LIBS = -llocal_fix -lpthread\n")
                self.assertFalse((runtime / "http-patched").exists())

    def test_rebuild_preserves_local_sources_backup_and_repeatable_link_settings(self):
        run, port, runtime = self.setup_build()
        for _ in range(2):
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((runtime / "love.self").read_text(), "rebuilt SELF")
        self.assertEqual((port / "baselines/before-network/love.self").read_text(), "working SELF")
        self.assertEqual((port / "baselines/before-network/love").read_text(), "working ELF")
        self.assertEqual((runtime / "src/modules/system/wrap_System.cpp").read_text(),
                         "local runtime fix\n")
        self.assertEqual((runtime / "src/Makefile").read_text().count("include g1r-http-libs.mk"), 1)
        fragment = (runtime / "src/g1r-http-libs.mk").read_text()
        self.assertIn("$(filter-out -pthread -lpthread,$(LIBS))", fragment)
        self.assertIn("-lcurl -lssl -lcrypto", fragment)
        self.assertEqual(fragment.count("-lpthread"), 2)  # filter + final link group
        self.assertEqual((runtime / "src/modules/system/vita_http_bridge.h").read_bytes(),
                         (ROOT / "native/vita_http_bridge.h").read_bytes())


if __name__ == "__main__":
    unittest.main()
