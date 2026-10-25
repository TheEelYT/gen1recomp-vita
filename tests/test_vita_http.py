"""Exercise the production bridge with host curl, a local TLS server and Vita API shims."""
import http.server
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT.parent / "gen1recomp"
LUA = ENGINE / "mobile/android/love/src/jni/LuaJIT-2.1/src"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body=b"", extra=None):
        self.send_response(status)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/ok":
                self.reply(200, b"hello")
            elif self.path == "/redirect":
                self.reply(302, extra={"Location": "/ok"})
            elif self.path == "/conflict":
                self.reply(409, b'{"error":"conflict"}')
            elif self.path == "/large":
                self.reply(200, b"x" * (12 * 1024 * 1024))
            elif self.path == "/truncated":
                self.send_response(200)
                self.send_header("Content-Length", "10000")
                self.end_headers()
                self.wfile.write(b"partial")
                self.close_connection = True
            elif self.path == "/slow":
                self.send_response(200)
                self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(3)
                self.wfile.write(b"x" * 999)
            else:
                self.reply(404, b"missing")
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.headers.get("x-sync-token") != "fake-token":
            self.reply(403, b"missing auth")
        else:
            self.reply(200, body)

    do_POST = do_PUT

    def do_DELETE(self):
        self.reply(204)


SHIMS = {
    "psp2/sysmodule.h": """
#define SCE_SYSMODULE_NET 1
inline int sceSysmoduleIsLoaded(int) { return 0; }
inline int sceSysmoduleLoadModule(int) { return 0; }
""",
    "psp2/net/net.h": """
struct SceNetInitParam { void *memory; int size; int flags; };
inline int sceNetInit(SceNetInitParam *p) {
  assert(p->memory && p->size == 512*1024 && !p->flags); ++netInits; return 0;
}
""",
    "psp2/net/netctl.h": """
#define SCE_NETCTL_STATE_CONNECTED 3
inline int sceNetCtlInit() { uninitialized=false; return 0; }
inline int sceNetCtlInetGetState(int *state) {
  if (uninitialized) return -1;
  *state=offline ? 0 : 3; return 0;
}
""",
}
PRELUDE = r'''
#include <cassert>
#include <fstream>
#include <thread>
#include <chrono>
#include <iterator>
bool uninitialized=true, offline=false;
int netInits=0;
'''
CORE = r'''
#define G1R_HTTP_NO_LUA
#include "vita_http_bridge.h"
std::string read(const std::string &p) {
  std::ifstream f(p, std::ios::binary); return {std::istreambuf_iterator<char>(f), {}};
}
int main(int argc, char **argv) {
  assert(argc==4);
  std::string base=argv[1], ca=argv[2], dest=argv[3];
  g1rhttp::Request q; q.caFile=ca; q.url=base+"/ok";
  auto r=g1rhttp::perform(q); assert(r.ok && r.status==200 && r.body=="hello");
  assert(netInits==1);
  offline=true; r=g1rhttp::perform(q); assert(!r.ok && r.error.find("Wi-Fi")!=std::string::npos);
  offline=false; assert(g1rhttp::perform(q).ok && netInits==1);
  q.method="PUT"; q.headers={"x-sync-token: fake-token", "Content-Type: application/octet-stream"};
  q.body=std::string("A\0B",3); r=g1rhttp::perform(q); assert(r.ok && r.body==q.body);
  q.method="POST"; r=g1rhttp::perform(q); assert(r.ok && r.body==q.body);
  q.method="DELETE"; q.body.clear(); r=g1rhttp::perform(q); assert(r.ok && r.status==204);
  q.method="GET"; q.url=base+"/conflict"; r=g1rhttp::perform(q);
  assert(r.ok && r.status==409 && r.body.find("conflict")!=std::string::npos);
  q.url=base+"/redirect"; r=g1rhttp::perform(q); assert(r.ok && r.status==302);
  q.headers.clear(); q.redirects=true; r=g1rhttp::perform(q); assert(r.ok && r.body=="hello");
  q.url=base+"/large"; q.limit=32; r=g1rhttp::perform(q); assert(!r.ok && r.body.empty());
  q.destination=dest; q.limit=32*1024*1024; r=g1rhttp::perform(q);
  assert(r.ok && r.body.empty() && r.bytes==12*1024*1024 && read(dest).size()==r.bytes);
  {std::ofstream f(dest); f<<"keep";}
  for (auto path : {"/truncated", "/missing"}) {
    q.url=base+path; r=g1rhttp::perform(q); assert(!r.ok && read(dest)=="keep");
  }
  q.url=base+"/large"; q.limit=32; r=g1rhttp::perform(q); assert(!r.ok && read(dest)=="keep");
  q.destination.clear(); q.limit=4096; q.url="file:///etc/passwd";
  r=g1rhttp::perform(q); assert(!r.ok);
  q.url="http://localhost/"; assert(!g1rhttp::perform(q).ok);
  q.url=base+"/ok"; q.headers={"x-sync-token: fake\r\ninjected: value"}; assert(!g1rhttp::perform(q).ok);
  q.headers.clear(); q.userAgent="bad\nagent"; assert(!g1rhttp::perform(q).ok); q.userAgent="test";
  q.caFile="missing-ca.pem"; assert(!g1rhttp::perform(q).ok); q.caFile=ca;
  q.url=base; q.url.replace(q.url.find("localhost"),9,"127.0.0.1"); assert(!g1rhttp::perform(q).ok);
  q.url=base+"/slow"; q.seconds=1;
  auto start=std::chrono::steady_clock::now(); r=g1rhttp::perform(q); assert(!r.ok);
  assert(std::chrono::steady_clock::now()-start<std::chrono::seconds(4));
  q.seconds=20; std::thread worker([&](){r=g1rhttp::perform(q);});
  std::this_thread::sleep_for(std::chrono::milliseconds(150)); g1rhttp::cancelAll(); worker.join();
  assert(!r.ok && r.error=="request cancelled");
  q.url=base+"/ok"; assert(!g1rhttp::perform(q).ok); // late call during shutdown
  g1rhttp::resetCancel(); assert(g1rhttp::perform(q).ok);
  return 0;
}
'''
BINDINGS = r'''
extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}
namespace love {
template<class F> void luax_catchexcept(lua_State *L, F f) {
  try { f(); } catch (...) { luaL_error(L,"native exception"); }
}
}
#include "vita_http_bridge.h"
int main(int argc, char **argv) {
  assert(argc==2); lua_State *L=luaL_newstate(); luaL_openlibs(L);
  lua_pushstring(L,argv[1]); lua_setglobal(L,"base");
  lua_register(L,"get",love::system::w_vitaHttpGet);
  lua_register(L,"request",love::system::w_vitaHttpRequest);
  lua_register(L,"download",love::system::w_vitaHttpDownload);
  lua_register(L,"cancel",love::system::w_vitaHttpCancelAll);
  lua_register(L,"reset",love::system::w_vitaHttpResetCancel);
  const char *test=R"LUA(
    local b,e,code=get(base..'/ok'); assert(b=='hello' and e==nil and code==200)
    assert(request(base..'/ok','PUT',{'x-sync-token','fake-token'},'A\0B')=='STATUS 200\nA\0B')
    assert(request(base..'/conflict','GET',{},nil):find('STATUS 409\n',1,true)==1)
    assert(request(base..'/redirect','GET',{'x-sync-token','fake-token'},nil)=='STATUS 302\n')
    assert(request(base..'/ok','GET',{'odd'},nil)=='ERROR bad request headers\n')
    assert(download(base..'/ok','ux0:/data/test.bin'))
    local f=assert(io.open('ux0:/data/test.bin','rb')); assert(f:read('*a')=='hello'); f:close()
    assert(not download(base..'/ok','app0:/readonly'))
    cancel(); assert(not get(base..'/ok')); reset(); assert(get(base..'/ok')=='hello')
  )LUA";
  int rc=luaL_dostring(L,test);
  if(rc) std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
  lua_close(L); return rc;
}
'''


@unittest.skipUnless(shutil.which("g++") and shutil.which("openssl"), "requires host C++/curl and openssl")
class VitaHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.work = Path(cls.tmp.name)
        for name, source in SHIMS.items():
            p = cls.work / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(source)
        cls.cert = cls.work / "cert.pem"
        key = cls.work / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cls.cert), "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in ("app0:", "ux0:/data"):
            (cls.work / name).mkdir(parents=True)
        shutil.copyfile(cls.cert, cls.work / "app0:/cacert.pem")
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cls.cert, key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.base = f"https://localhost:{cls.server.server_port}"

    def compile(self, name, source, lua=False):
        cpp, binary = self.work / f"{name}.cpp", self.work / name
        cpp.write_text(PRELUDE + source)
        cmd = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(self.work),
               "-I", str(ROOT / "native"), str(cpp), "-lcurl", "-pthread", "-o", str(binary)]
        if lua:
            cmd.extend(["-I", str(LUA), str(LUA / "libluajit.a"), "-ldl", "-lm"])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return binary

    def test_transport_tls_auth_streaming_failure_limits_and_shutdown(self):
        binary = self.compile("transport", CORE)
        subprocess.run([str(binary), self.base, str(self.cert), str(self.work / "download.bin")],
                       cwd=self.work, check=True, timeout=20)
        self.assertFalse(list(self.work.glob("*.g1r-part-*")))

    @unittest.skipUnless((LUA / "libluajit.a").exists(), "requires host LuaJIT build for native binding check")
    def test_real_luajit_native_bindings(self):
        binary = self.compile("bindings", BINDINGS, lua=True)
        subprocess.run([str(binary), self.base], cwd=self.work, check=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
