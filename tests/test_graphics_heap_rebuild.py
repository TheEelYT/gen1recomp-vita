"""Run the rebuild helper with fake toolchain commands in isolated directories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("bash"), "requires bash")
class GraphicsHeapRebuildTests(unittest.TestCase):
    def run_build(self, mode="1", bad_stage="", conflict=False, exit_state="patched"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        port, vita, runtime, sdk = (root / name for name in ("port", "vitaGL", "love", "sdk"))
        (port / "scripts").mkdir(parents=True)
        (port / "patches").mkdir()
        script = port / "scripts/rebuild_shader_diagnostics.sh"
        shutil.copyfile(ROOT / "scripts/rebuild_shader_diagnostics.sh", script)
        for name in ("vitagl-shader-link-guard.patch", "love-vita-process-exit.patch",
                     "love-vita-process-exit-raw-upgrade.patch"):
            (port / "patches" / name).write_text("fixture patch")
        (vita / "source").mkdir(parents=True)
        (vita / "Makefile").write_text("HAVE_CUSTOM_HEAP")
        (vita / "source/custom_shaders.c").write_text("local shader fix")
        (runtime / "src/modules/graphics/opengl").mkdir(parents=True)
        (runtime / "Makefile").write_text("local configure flags")
        (runtime / "src/Makefile").write_text("LIBS = -llocal_fix\n")
        (runtime / "src/modules/graphics/opengl/Shader.cpp").write_text("local runtime fix")
        (runtime / "src/love").write_text("original ELF")
        (runtime / "love.self").write_text("original SELF")
        (sdk / "bin").mkdir(parents=True)
        (sdk / "arm-vita-eabi/lib").mkdir(parents=True)
        (sdk / "arm-vita-eabi/lib/libSceProcessmgr_stub.a").touch()
        log = root / "commands.txt"

        def tool(name, body):
            p = sdk / "bin" / name
            p.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
            p.chmod(0o755)

        tool("git", r'''
printf 'git %s\n' "$*" >> "$TEST_LOG"
if [[ "$*" == *" grep "* ]]; then exit 0; fi
if [[ "$TEST_CONFLICT" == 1 && "$*" == *"apply"* ]]; then exit 1; fi
if [[ "$*" == *"love-vita-process-exit.patch" && "$*" == *"--reverse"* ]]; then
  [[ "$TEST_EXIT_STATE" == patched ]]; exit
fi
if [[ "$*" == *"love-vita-process-exit-raw-upgrade.patch" && "$*" == *"--check"* ]]; then
  [[ "$TEST_EXIT_STATE" == legacy ]]; exit
fi
exit 0
''')
        tool("make", r'''
printf 'make %s\n' "$*" >> "$TEST_LOG"
if [[ "$*" == *" install "* ]]; then
  printf 'library\n' > "$2/libvitaGL.a"
elif [[ "$2" == "$TEST_RUNTIME" ]]; then
  printf 'rebuilt ELF\n' > "$2/src/love"
fi
''')
        tool("arm-vita-eabi-gcc", "exit 0\n")
        tool("arm-vita-eabi-nm", r'''
printf 'nm %s\n' "$*" >> "$TEST_LOG"
if [[ "$*" == *"libSceProcessmgr_stub.a" ]]; then
  [[ "$TEST_BAD_STAGE" == sdk-raw ]] || echo '00000000 T _sceKernelExitProcessForUser'
  exit 0
fi
stage=runtime
[[ "$*" != *".a" ]] || stage=library
if [[ "$stage" == runtime && "$TEST_BAD_STAGE" != raw-runtime ]]; then
  echo '00005678 T _sceKernelExitProcessForUser'
fi
if [[ "$TEST_BAD_STAGE" == "mixed-$stage" ]]; then
  echo '00001234 b tm_alloclist'
  echo '00005678 b mempool_mspace'
  exit 0
fi
if [[ "$TEST_BAD_STAGE" == "$stage" || "$G1R_CUSTOM_HEAP" == 0 ]]; then
  echo '00001234 b mempool_mspace'
else
  echo '00001234 b tm_alloclist'
fi
''')
        tool("vita-elf-create", r'''
printf 'elf-create\n' >> "$TEST_LOG"
printf 'rebuilt VELF\n' > "${@: -1}"
''')
        tool("vita-make-fself", r'''
printf 'make-fself\n' >> "$TEST_LOG"
printf 'rebuilt SELF\n' > "${@: -1}"
''')
        env = {**os.environ, "VITASDK": str(sdk), "G1R_CUSTOM_HEAP": mode,
               "TEST_LOG": str(log), "TEST_BAD_STAGE": bad_stage,
               "TEST_RUNTIME": str(runtime), "TEST_CONFLICT": str(int(conflict)),
               "TEST_EXIT_STATE": exit_state}
        result = subprocess.run(["bash", str(script), str(vita), str(runtime)],
                                env=env, text=True, capture_output=True)
        commands = log.read_text() if log.exists() else ""
        return result, commands, port, vita, runtime

    def test_custom_heap_verified_before_creating_self(self):
        result, calls, port, vita, runtime = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HAVE_CUSTOM_HEAP=1", calls)
        self.assertIn("NO_DEBUG=0", calls)
        self.assertLess(calls.index(" clean"), calls.index(" install"))
        self.assertEqual(calls.count("nm --defined-only"), 4)
        self.assertLess(calls.rindex("nm --defined-only"), calls.index("elf-create"))
        self.assertEqual((runtime / "love.self").read_text(), "rebuilt SELF\n")
        backup = port / "baselines/before-raw-process-exit"
        self.assertEqual((backup / "love.self").read_text(), "original SELF")
        self.assertEqual((backup / "love").read_text(), "original ELF")
        self.assertEqual((vita / "source/custom_shaders.c").read_text(), "local shader fix")
        self.assertEqual((runtime / "src/modules/graphics/opengl/Shader.cpp").read_text(),
                         "local runtime fix")
        self.assertIn("tm_alloclist", (port / "build/graphics-heap-symbols.txt").read_text())
        self.assertEqual((runtime / "src/Makefile").read_text(),
                         "LIBS = -llocal_fix\n\n# G1R_RAW_EXIT_LIBS\n"
                         "override LIBS += -lSceProcessmgr_stub\n")

    def test_wrong_library_or_linked_runtime_preserves_existing_self(self):
        for stage in ("library", "runtime"):
            with self.subTest(stage=stage):
                result, calls, _, _, runtime = self.run_build(bad_stage=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Custom heap missing", result.stderr)
                self.assertNotIn("elf-create", calls)
                self.assertEqual((runtime / "love.self").read_text(), "original SELF")
                if stage == "library":
                    self.assertEqual((runtime / "src/love").read_text(), "original ELF")

    def test_patch_conflict_stops_before_building(self):
        result, calls, _, _, runtime = self.run_build(conflict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("make -C", calls)
        self.assertEqual((runtime / "love.self").read_text(), "original SELF")

    def test_mixed_allocator_build_is_rejected(self):
        result, calls, _, _, runtime = self.run_build(bad_stage="mixed-runtime")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Mixed graphics allocators", result.stderr)
        self.assertNotIn("elf-create", calls)
        self.assertEqual((runtime / "love.self").read_text(), "original SELF")

    def test_previous_allocator_remains_explicitly_available(self):
        result, calls, port, _, _ = self.run_build(mode="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HAVE_CUSTOM_HEAP=0", calls)
        self.assertIn("mempool_mspace", (port / "build/graphics-heap-symbols.txt").read_text())

    def test_invalid_mode_stops_before_mutating_runtime(self):
        result, calls, _, _, runtime = self.run_build(mode="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be 0 or 1", result.stderr)
        self.assertEqual(calls, "")
        self.assertEqual((runtime / "love.self").read_text(), "original SELF")

    def test_missing_raw_sdk_stub_or_linked_import_preserves_self(self):
        for stage in ("sdk-raw", "raw-runtime"):
            with self.subTest(stage=stage):
                result, calls, _, _, runtime = self.run_build(bad_stage=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing", result.stderr)
                self.assertNotIn("elf-create", calls)
                self.assertEqual((runtime / "love.self").read_text(), "original SELF")
                if stage == "sdk-raw":
                    self.assertNotIn("make -C", calls)
                    self.assertEqual((runtime / "src/Makefile").read_text(), "LIBS = -llocal_fix\n")

    def test_fresh_and_legacy_exit_patches_choose_the_right_update(self):
        for state, patch in (("fresh", "love-vita-process-exit.patch"),
                             ("legacy", "love-vita-process-exit-raw-upgrade.patch")):
            with self.subTest(state=state):
                result, calls, port, _, runtime = self.run_build(exit_state=state)
                self.assertEqual(result.returncode, 0, result.stderr)
                apply = f"git -C {runtime} apply {port / 'patches' / patch}"
                self.assertIn(apply + "\n", calls)


if __name__ == "__main__":
    unittest.main()
