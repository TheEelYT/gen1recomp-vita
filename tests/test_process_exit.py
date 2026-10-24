"""Exercise the exact exit gate without VitaSDK or graphics hardware."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cc"), "requires a host C compiler")
class ProcessExitTests(unittest.TestCase):
    def test_only_completed_real_quit_bypasses_finalizers(self):
        patch = (ROOT / "patches/love-vita-process-exit.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        start = added.index("// G1R_PROCESS_EXIT_BEGIN")
        guard = added[start:added.index("// G1R_PROCESS_EXIT_END", start)]
        source = r'''
#include <assert.h>
#include <stdio.h>
#include <stdbool.h>
#include <setjmp.h>
#include <string.h>
enum { DONE_QUIT, DONE_RESTART };
int ready, finishes, finalized, exit_status, pops;
jmp_buf exited;
void lua_getglobal(void *L, const char *name) {
    (void)L; assert(strcmp(name, "G1R_VITA_SHUTDOWN_READY") == 0);
}
int lua_toboolean(void *L, int index) { (void)L; assert(index == -1); return ready; }
void lua_pop(void *L, int n) { (void)L; assert(n == 1); pops++; }
void glFinish(void) { finishes++; }
void sceKernelExitProcess(int status) { exit_status = status; longjmp(exited, 1); }
FILE *test_fopen(const char *path, const char *mode) {
    assert(strcmp(path, "ux0:data/g1r-shutdown.txt") == 0);
    assert(strcmp(mode, "a") == 0);
    return NULL; // An unavailable log must not prevent quitting.
}
#define fopen test_fopen
void teardown(int done, int retval) {
    void *L = NULL;
@GUARD@
    finalized++;
}
int main(void) {
    ready = 0; teardown(DONE_QUIT, 0);
    assert(finalized == 1 && finishes == 0);
    ready = 1; teardown(DONE_RESTART, 0);
    assert(finalized == 2 && finishes == 0);
    if (!setjmp(exited)) { teardown(DONE_QUIT, 7); assert(0); }
    assert(exit_status == 7 && finishes == 1 && finalized == 2 && pops == 3);
    return 0;
}
'''.replace("@GUARD@", guard)
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / "exit.c").write_text(source)
            subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                            "exit.c", "-o", "exit"], cwd=work, check=True)
            subprocess.run([str(work / "exit")], cwd=work, check=True)


if __name__ == "__main__":
    unittest.main()
