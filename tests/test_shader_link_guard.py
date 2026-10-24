"""Host C checks for the exact guard added by the vitaGL patch (no VitaSDK)."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cc"), "requires a host C compiler")
class ShaderLinkGuardTests(unittest.TestCase):
    def test_failed_stages_never_reach_native_reflection(self):
        patch = (ROOT / "patches/vitagl-shader-link-guard.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        start = added.index("static void g1r_shader_diagnostic(")
        helper = added[start:added.index("\n#endif", start)]
        start = added.index("// G1R_LINK_GUARD_BEGIN")
        guard = added[start:added.index("// G1R_LINK_GUARD_END", start)]
        harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef int shark_log_level;
enum { SHARK_LOG_ERROR = 2, PROG_UNLINKED = 1, PROG_LINKED = 2 };
typedef struct { void *prog; char *source; } shader;
typedef struct { shader *vshader, *fshader; int status; } program;
int failed_io, native_calls;
FILE *test_fopen(const char *path, const char *mode) {
    assert(strncmp(path, "ux0:data/", 9) == 0);
    return failed_io ? NULL : fopen(path + 9, mode);
}
#define fopen test_fopen
#define vgl_log(...) ((void)0)
@HELPER@
void link_program(program *p) {
#if defined(HAVE_SHARK_LOG) || defined(LOG_ERRORS)
    unsigned progr = 9;
#endif
@GUARD@
    native_calls++;
    p->status = PROG_LINKED;
}
int main(void) {
    shader ready = { (void *)1, NULL }, failed = { NULL, "bad translated source\n" };
    program cases[] = {
        { NULL, &ready, 0 }, { &ready, NULL, 0 },
        { &failed, &ready, 0 }, { &ready, &failed, 0 },
        { &failed, &failed, 0 }
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        link_program(&cases[i]);
        assert(cases[i].status == PROG_UNLINKED && native_calls == 0);
    }
    program valid = { &ready, &ready, 0 };
    link_program(&valid);
    assert(valid.status == PROG_LINKED && native_calls == 1);
#if defined(HAVE_SHARK_LOG) || defined(LOG_ERRORS)
    char text[128] = {0};
    FILE *file = test_fopen("ux0:data/g1r-shader-failed-fragment.cg", "r");
    assert(file); assert(fgets(text, sizeof(text), file)); fclose(file);
    assert(strcmp(text, failed.source) == 0);
    file = test_fopen("ux0:data/g1r-shaders.txt", "r");
    assert(file); assert(fgets(text, sizeof(text), file)); fclose(file);
    assert(strstr(text, "program=9 link aborted"));
#endif
    failed_io = 1;
    program no_disk = { &ready, &failed, 0 };
    link_program(&no_disk);
    assert(no_disk.status == PROG_UNLINKED && native_calls == 1);
    return 0;
}
'''
        helper = "#if defined(HAVE_SHARK_LOG) || defined(LOG_ERRORS)\n" + helper + "\n#endif"
        source = harness.replace("@HELPER@", helper).replace("@GUARD@", guard)
        for flags in ([], ["-DLOG_ERRORS"], ["-DHAVE_SHARK_LOG"],
                      ["-DLOG_ERRORS", "-DHAVE_SHARK_LOG"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp:
                work = pathlib.Path(tmp)
                (work / "guard.c").write_text(source)
                subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                                *flags, "guard.c", "-o", "guard"], cwd=work, check=True)
                subprocess.run([str(work / "guard")], cwd=work, check=True)

    @unittest.skipUnless(shutil.which("bash"), "requires bash")
    def test_rebuild_script_syntax(self):
        subprocess.run(["bash", "-n", str(ROOT / "scripts/rebuild_shader_diagnostics.sh")],
                       check=True)


if __name__ == "__main__":
    unittest.main()
