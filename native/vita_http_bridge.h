// Gen1Recomp Vita HTTPS bridge. Included once by wrap_System.cpp.
// Transport code is also compiled against host libcurl by the integration tests.
#ifndef G1R_VITA_HTTP_BRIDGE_H
#define G1R_VITA_HTTP_BRIDGE_H
#include <curl/curl.h>
#include <atomic>
#include <mutex>
#include <string>
#include <vector>
#include <cstdio>
#include <cstdlib>
#include <algorithm>
#include <limits>
#ifndef G1R_HTTP_HOST_TEST
#include <psp2/sysmodule.h>
#include <psp2/net/net.h>
#include <psp2/net/netctl.h>
#endif

namespace g1rhttp {
static std::mutex transferMutex;
static std::atomic<unsigned> cancelGeneration(0), tempSequence(0);
static std::atomic<bool> stopRequested(false);
static const size_t MEMORY_LIMIT = 8 * 1024 * 1024;
static const size_t DOWNLOAD_LIMIT = 256 * 1024 * 1024;
struct Request {
  std::string url, method = "GET", body, destination, caFile = "app0:/cacert.pem";
  std::string userAgent = "gen1recomp-vita";
  std::vector<std::string> headers;
  long seconds = 25;
  size_t limit = 4 * 1024 * 1024;
  bool redirects = false;
};
struct Reply {
  bool ok = false;
  long status = 0;
  size_t bytes = 0;
  std::string body, error;
};
static bool cancelled(unsigned generation) { return stopRequested.load() || cancelGeneration.load() != generation; }
static void cancelAll() { stopRequested.store(true); ++cancelGeneration; }
static void resetCancel() { stopRequested.store(false); }

static bool initialize(std::string &error) {
  static bool curlReady = false;
#ifndef G1R_HTTP_HOST_TEST
  static bool netReady = false;
  static void *netPool = nullptr;
  int state = -1;
  if (!netReady) {
    if (sceSysmoduleIsLoaded(SCE_SYSMODULE_NET) < 0 &&
        sceSysmoduleLoadModule(SCE_SYSMODULE_NET) < 0) {
      error = "could not load Vita networking"; return false;
    }
    // Reuse a stack initialized by another runtime component when available.
    if (sceNetCtlInetGetState(&state) < 0) {
      if (!netPool) {
        netPool = std::malloc(512 * 1024);
        if (!netPool) { error = "not enough memory for networking"; return false; }
        SceNetInitParam params = {};
        params.memory = netPool; params.size = 512 * 1024;
        int rc = sceNetInit(&params);
        if (rc < 0) { std::free(netPool); netPool = nullptr; }
      }
      sceNetCtlInit();
      if (sceNetCtlInetGetState(&state) < 0) {
        error = "could not initialize Vita networking"; return false;
      }
    }
    netReady = true;
  }
  if (sceNetCtlInetGetState(&state) < 0 || state != SCE_NETCTL_STATE_CONNECTED) {
    error = "Wi-Fi is not connected; connect in Vita Settings and retry"; return false;
  }
#endif
  if (!curlReady) {
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
      error = "could not initialize HTTPS"; return false;
    }
    curlReady = true;
  }
  if (!(curl_version_info(CURLVERSION_NOW)->features & CURL_VERSION_SSL)) {
    error = "this libcurl build has no TLS support"; return false;
  }
  return true;
}

static bool validHeader(const std::string &line) {
  size_t colon = line.find(':');
  if (!colon || colon == std::string::npos || line.size() > 8192 ||
      line.find_first_of("\r\n") != std::string::npos ||
      line.find('\0') != std::string::npos) return false;
  const std::string token = "!#$%&'*+-.^_`|~";
  for (size_t i = 0; i < colon; ++i) {
    unsigned char c = line[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
          (c >= '0' && c <= '9') || token.find(c) != std::string::npos)) return false;
  }
  return true;
}
struct Transfer {
  Reply *reply;
  FILE *file;
  size_t limit;
  unsigned generation;
  bool tooLarge = false, writeFailed = false;
};
static size_t receive(char *ptr, size_t size, size_t n, void *opaque) {
  Transfer &t = *static_cast<Transfer *>(opaque);
  if (size && n > std::numeric_limits<size_t>::max() / size) return 0;
  size_t bytes = size * n;
  if (cancelled(t.generation)) return 0;
  if (bytes > t.limit - t.reply->bytes) { t.tooLarge = true; return 0; }
  if (t.file) {
    if (std::fwrite(ptr, 1, bytes, t.file) != bytes) { t.writeFailed = true; return 0; }
  } else {
    try { t.reply->body.append(ptr, bytes); }
    catch (...) { t.tooLarge = true; return 0; }
  }
  t.reply->bytes += bytes;
  return bytes;
}
static int progress(void *opaque, curl_off_t, curl_off_t, curl_off_t, curl_off_t) {
  return cancelled(static_cast<Transfer *>(opaque)->generation) ? 1 : 0;
}
static void diagnostic(const Request &req, const Reply &reply, CURLcode code) {
#ifndef G1R_HTTP_HOST_TEST
  static unsigned entries = 0;
  if (entries >= 128) return;
  FILE *f = std::fopen("ux0:/data/g1r-network.txt", entries == 0 ? "w" : "a");
  if (!f) return;
  // Never record request bodies, headers, full URLs, or query parameters.
  size_t begin = req.url.find("://");
  std::string host = begin == std::string::npos ? "invalid" :
    req.url.substr(begin + 3, req.url.find_first_of("/?#", begin + 3) - (begin + 3));
  std::fprintf(f, "backend=%s method=%s host=%.160s status=%ld bytes=%lu curl=%d ok=%d\n",
    curl_version(), req.method.c_str(), host.c_str(), reply.status,
    static_cast<unsigned long>(reply.bytes), static_cast<int>(code), reply.ok ? 1 : 0);
  std::fclose(f); ++entries;
#else
  (void)req; (void)reply; (void)code;
#endif
}
struct Session {
  CURL *curl = nullptr;
  curl_slist *headers = nullptr;
  FILE *file = nullptr;
  std::string temporary;
  bool installed = false;
  ~Session() {
    if (file) std::fclose(file);
    curl_slist_free_all(headers);
    if (curl) curl_easy_cleanup(curl);
    if (!installed && !temporary.empty()) std::remove(temporary.c_str());
  }
};
static Reply perform(const Request &req) {
  Reply reply;
  const unsigned generation = cancelGeneration.load();
  std::unique_lock<std::mutex> lock(transferMutex);
  if (cancelled(generation)) { reply.error = "request cancelled"; return reply; }
  bool https = req.url.compare(0, 8, "https://") == 0;
#ifdef G1R_HTTP_HOST_TEST
  bool allowed = https || req.url.compare(0, 7, "http://") == 0;
#else
  bool allowed = https;
#endif
  size_t authorityEnd = req.url.find_first_of("/?#", req.url.find("://") + 3);
  if (!allowed || req.url.empty() || req.url.size() > 8192 ||
      req.url.find_first_of("\r\n") != std::string::npos || req.url.find('\0') != std::string::npos ||
      req.url.substr(0, authorityEnd).find('@') != std::string::npos) {
    reply.error = "an HTTPS URL without embedded credentials is required"; return reply;
  }
  if (req.method != "GET" && req.method != "POST" && req.method != "PUT" && req.method != "DELETE") {
    reply.error = "unsupported HTTP method"; return reply;
  }
  size_t headerBytes = 0;
  for (const auto &h : req.headers) {
    headerBytes += h.size();
    if (!validHeader(h) || headerBytes > 64 * 1024) { reply.error = "bad request header"; return reply; }
  }
  if (req.userAgent.find_first_of("\r\n") != std::string::npos ||
      req.userAgent.find('\0') != std::string::npos || req.userAgent.size() > 512) {
    reply.error = "bad user agent"; return reply;
  }
  if (req.body.size() > MEMORY_LIMIT) { reply.error = "request body exceeds Vita's 8 MiB limit"; return reply; }
  if (!initialize(reply.error)) return reply;
  Session session;
  CURL *curl = session.curl = curl_easy_init();
  if (!curl) { reply.error = "not enough memory for HTTPS"; return reply; }
  curl_slist *&headers = session.headers;
  for (const auto &h : req.headers) {
    auto *next = curl_slist_append(headers, h.c_str());
    if (!next) { reply.error = "not enough memory for headers"; return reply; }
    headers = next;
  }
  std::string &temporary = session.temporary;
  FILE *file = nullptr;
  if (!req.destination.empty()) {
    temporary = req.destination + ".g1r-part-" + std::to_string(++tempSequence);
    file = session.file = std::fopen(temporary.c_str(), "wb");
    if (!file) { reply.error = "could not create download file"; return reply; }
  }
  Transfer transfer; transfer.reply = &reply; transfer.file = file;
  transfer.limit = std::min(req.limit, file ? DOWNLOAD_LIMIT : MEMORY_LIMIT);
  transfer.generation = generation;
  long timeout = std::max(1L, std::min(req.seconds, 120L));
  curl_easy_setopt(curl, CURLOPT_URL, req.url.c_str());
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, std::min(10L, timeout));
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);
  curl_easy_setopt(curl, CURLOPT_LOW_SPEED_LIMIT, 64L);
  curl_easy_setopt(curl, CURLOPT_LOW_SPEED_TIME, std::min(15L, timeout));
  curl_easy_setopt(curl, CURLOPT_USERAGENT, req.userAgent.c_str());
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
  curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
  curl_easy_setopt(curl, CURLOPT_SSLVERSION, CURL_SSLVERSION_TLSv1_2);
  curl_easy_setopt(curl, CURLOPT_CAINFO, req.caFile.c_str());
  curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, req.redirects ? 1L : 0L);
  curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 8L);
  // Generic requests carry save-sync headers: never redirect those to another host.
#if LIBCURL_VERSION_NUM >= 0x075500
#ifdef G1R_HTTP_HOST_TEST
  curl_easy_setopt(curl, CURLOPT_PROTOCOLS_STR, "http,https");
  curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");
#else
  curl_easy_setopt(curl, CURLOPT_PROTOCOLS_STR, "https");
  curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, "https");
#endif
#else
  curl_easy_setopt(curl, CURLOPT_PROTOCOLS, CURLPROTO_HTTPS);
  curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS, CURLPROTO_HTTPS);
#endif
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, receive);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &transfer);
  curl_easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, progress);
  curl_easy_setopt(curl, CURLOPT_XFERINFODATA, &transfer);
  curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
  if (!req.body.empty() || req.method == "POST" || req.method == "PUT") {
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, req.body.data());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(req.body.size()));
  }
  curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, req.method.c_str());
  CURLcode code = curl_easy_perform(curl);
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &reply.status);
  if (file && std::fclose(file) != 0) transfer.writeFailed = true;
  session.file = nullptr;
  if (cancelled(generation) || code == CURLE_ABORTED_BY_CALLBACK) reply.error = "request cancelled";
  else if (transfer.tooLarge) reply.error = "reply exceeds the Vita transfer limit";
  else if (transfer.writeFailed) reply.error = "could not write download; check free storage";
  else if (code != CURLE_OK) reply.error = curl_easy_strerror(code);
  else if (file && (reply.status < 200 || reply.status >= 300)) reply.error = "HTTP " + std::to_string(reply.status);
  else if (file && std::rename(temporary.c_str(), req.destination.c_str()) != 0) reply.error = "could not install downloaded file";
  else reply.ok = true;
  session.installed = reply.ok;
  if (!reply.ok) { reply.body.clear(); if (file) std::remove(temporary.c_str()); }
  diagnostic(req, reply, code);
  return reply;
}
} // namespace g1rhttp

#ifndef G1R_HTTP_NO_LUA
namespace love { namespace system {
static int w_vitaHttpCancelAll(lua_State *) { g1rhttp::cancelAll(); return 0; }
static int w_vitaHttpResetCancel(lua_State *) { g1rhttp::resetCancel(); return 0; }
static int vitaHttpReply(lua_State *L, const g1rhttp::Reply &r, bool envelope) {
  if (envelope) {
    std::string message = r.ok ? "STATUS " + std::to_string(r.status) + "\n" + r.body : "ERROR " + r.error + "\n";
    lua_pushlstring(L, message.data(), message.size()); return 1;
  }
  if (r.ok) lua_pushlstring(L, r.body.data(), r.body.size()); else lua_pushnil(L);
  if (r.ok) lua_pushnil(L); else lua_pushlstring(L, r.error.data(), r.error.size());
  lua_pushinteger(L, r.status); return 3;
}
static int vitaHttpGetImpl(lua_State *L) {
  const char *url = luaL_checkstring(L, 1);
  const char *agent = luaL_optstring(L, 2, "gen1recomp-vita");
  const char *accept = luaL_optstring(L, 3, "*/*");
  long seconds = luaL_optinteger(L, 4, 25);
  g1rhttp::Request req; req.url = url; req.userAgent = agent; req.seconds = seconds;
  req.headers.push_back(std::string("Accept: ") + accept); req.redirects = true;
  return vitaHttpReply(L, g1rhttp::perform(req), false);
}
static int vitaHttpDownloadImpl(lua_State *L) {
  const char *url = luaL_checkstring(L, 1);
  const char *path = luaL_checkstring(L, 2);
  const char *agent = luaL_optstring(L, 3, "gen1recomp-vita");
  const char *accept = luaL_optstring(L, 4, "*/*");
  long seconds = luaL_optinteger(L, 5, 90);
  g1rhttp::Request req; req.url = url; req.destination = path; req.userAgent = agent;
  req.headers.push_back(std::string("Accept: ") + accept); req.seconds = seconds;
  req.limit = g1rhttp::DOWNLOAD_LIMIT; req.redirects = true;
  if (req.destination.compare(0, 10, "ux0:/data/") != 0 && req.destination.compare(0, 9, "ux0:data/") != 0) {
    lua_pushnil(L); lua_pushliteral(L, "download destination must be in ux0:data"); return 2;
  }
  auto r = g1rhttp::perform(req);
  if (r.ok) lua_pushboolean(L, 1); else lua_pushnil(L);
  if (r.ok) lua_pushnil(L); else lua_pushlstring(L, r.error.data(), r.error.size());
  return 2;
}
static int vitaHttpRequestImpl(lua_State *L) {
  const char *url = luaL_checkstring(L, 1);
  const char *method = luaL_optstring(L, 2, "GET");
  luaL_checktype(L, 3, LUA_TTABLE);
  size_t bodySize = 0;
  const char *body = luaL_optlstring(L, 4, "", &bodySize);
  const char *agent = luaL_optstring(L, 5, "gen1recomp-vita");
  long seconds = luaL_optinteger(L, 6, 25);
  g1rhttp::Request req; req.url = url; req.method = method; req.userAgent = agent;
  req.body.assign(body, bodySize); req.seconds = seconds;
  size_t count = lua_objlen(L, 3);
  if (count % 2 || count > 128) { lua_pushliteral(L, "ERROR bad request headers\n"); return 1; }
  for (size_t i = 1; i <= count; i += 2) {
    lua_rawgeti(L, 3, i); lua_rawgeti(L, 3, i + 1);
    if (lua_type(L, -2) != LUA_TSTRING || lua_type(L, -1) != LUA_TSTRING) {
      lua_pop(L, 2); lua_pushliteral(L, "ERROR bad request headers\n"); return 1;
    }
    size_t nk, nv; const char *k = lua_tolstring(L, -2, &nk); const char *v = lua_tolstring(L, -1, &nv);
    req.headers.push_back(std::string(k, nk) + ": " + std::string(v, nv)); lua_pop(L, 2);
  }
  return vitaHttpReply(L, g1rhttp::perform(req), true);
}
static int w_vitaHttpGet(lua_State *L) {
  int n = 0; luax_catchexcept(L, [&]() { n = vitaHttpGetImpl(L); }); return n;
}
static int w_vitaHttpDownload(lua_State *L) {
  int n = 0; luax_catchexcept(L, [&]() { n = vitaHttpDownloadImpl(L); }); return n;
}
static int w_vitaHttpRequest(lua_State *L) {
  int n = 0; luax_catchexcept(L, [&]() { n = vitaHttpRequestImpl(L); }); return n;
}
}} // namespace love::system
#endif
#endif
