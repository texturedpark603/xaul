from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs
from api import XboxAPI, extract_scid_from_achievements
from achievements import AchievementManager
DEFAULT_PORT = 1337
def _json_response(handler: BaseHTTPRequestHandler, data: object, status: int = 200) -> None:
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
def _html_response(handler: BaseHTTPRequestHandler, html: str, status: int = 200) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b""
    return json.loads(raw) if raw else {}
_INDEX_HTML = """\
<!DOCTYPE html>
<html>
<head><title>XAU-py API</title>
<style>
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 2em; }
  h1   { color: #00d4ff; }
  h2   { color: #a0c4ff; margin-top: 1.5em; }
  code { background: #2a2a4a; padding: 2px 6px; border-radius: 3px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 12px; border-bottom: 1px solid #333; }
  th { color: #00d4ff; }
  .get  { color: #69ff94; }
  .post { color: #ffd166; }
</style>
</head>
<body>
<h1>XAU-py Local API</h1>
<table>
  <tr><th>Method</th><th>Path</th><th>Description</th></tr>
  <tr><td class="get">GET</td><td><code>/api/xauth</code></td><td>Current XAUTH token (add <code>?format=json</code> for JSON)</td></tr>
  <tr><td class="get">GET</td><td><code>/api/profile/me</code></td><td>Authenticated user full profile</td></tr>
  <tr><td class="get">GET</td><td><code>/api/profile/xuid/{xuid}</code></td><td>Profile by XUID</td></tr>
  <tr><td class="get">GET</td><td><code>/api/profile/gt/{gamertag}</code></td><td>Profile by gamertag</td></tr>
  <tr><td class="get">GET</td><td><code>/api/games/me</code></td><td>Games list for authenticated user</td></tr>
  <tr><td class="get">GET</td><td><code>/api/games/xuid/{xuid}</code></td><td>Games list by XUID</td></tr>
  <tr><td class="get">GET</td><td><code>/api/games/gt/{gamertag}</code></td><td>Games list by gamertag</td></tr>
  <tr><td class="get">GET</td><td><code>/api/games/search/titleid/{titleId}</code></td><td>Title info by Title ID</td></tr>
  <tr><td class="get">GET</td><td><code>/api/games/search/productid/{productId}</code></td><td>GamePass product info</td></tr>
  <tr><td class="get">GET</td><td><code>/api/achievements/{titleId}</code></td><td>Achievement list for a title</td></tr>
  <tr><td class="post">POST</td><td><code>/api/achievements/unlock</code></td><td>Unlock one achievement <code>{"TitleId":"..","AchievementId":".."}</code></td></tr>
  <tr><td class="post">POST</td><td><code>/api/achievements/unlockall</code></td><td>Unlock all achievements <code>{"TitleId":".."}</code></td></tr>
  <tr><td class="get">GET</td><td><code>/api/spoof/{titleId}</code></td><td>Send one presence heartbeat</td></tr>
</table>
</body>
</html>
"""
class _Handler(BaseHTTPRequestHandler):
    api: XboxAPI = None
    ach_manager: AchievementManager = None
    xuid: str = ""
    xauth: str = ""
    _scid_cache: dict[str, str] = {}
    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} - {fmt % args}")
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        qs = parse_qs(urlparse(self.path).query)
        try:
            if path in ("", "/", "/api", "/api/"):
                _html_response(self, _INDEX_HTML)
            elif path == "/api/xauth":
                if qs.get("format", [""])[0] == "json":
                    _json_response(self, {"token": self.xauth})
                else:
                    _text_response(self, self.xauth)
            elif path == "/api/profile/me":
                data = self.api.get_profile_by_xuid(self.xuid)
                _json_response(self, data)
            elif path.startswith("/api/profile/xuid/"):
                target_xuid = path.split("/api/profile/xuid/", 1)[1]
                data = self.api.get_profile_by_xuid(target_xuid)
                _json_response(self, data)
            elif path.startswith("/api/profile/gt/"):
                gamertag = path.split("/api/profile/gt/", 1)[1]
                xuid = self.api.get_xuid_for_gamertag(gamertag)
                if not xuid:
                    _json_response(self, {"error": f"Gamertag '{gamertag}' not found"}, 404)
                    return
                data = self.api.get_profile_by_xuid(xuid)
                _json_response(self, data)
            elif path == "/api/games/me":
                data = self.api.get_games_list(self.xuid)
                _json_response(self, data)
            elif path.startswith("/api/games/xuid/"):
                target_xuid = path.split("/api/games/xuid/", 1)[1]
                data = self.api.get_games_list(target_xuid)
                _json_response(self, data)
            elif path.startswith("/api/games/gt/"):
                gamertag = path.split("/api/games/gt/", 1)[1]
                xuid = self.api.get_xuid_for_gamertag(gamertag)
                if not xuid:
                    _json_response(self, {"error": f"Gamertag '{gamertag}' not found"}, 404)
                    return
                data = self.api.get_games_list(xuid)
                _json_response(self, data)
            elif path.startswith("/api/games/search/titleid/"):
                title_id = path.split("/api/games/search/titleid/", 1)[1]
                data = self.api.get_title_info(self.xuid, title_id)
                _json_response(self, data)
            elif path.startswith("/api/games/search/productid/"):
                product_id = path.split("/api/games/search/productid/", 1)[1]
                data = self.api.get_gamepass_catalog(product_id)
                _json_response(self, data)
            elif path.startswith("/api/achievements/"):
                title_id = path.split("/api/achievements/", 1)[1]
                if not title_id:
                    _json_response(self, {"error": "No TitleId provided"}, 400)
                    return
                try:
                    data = self.api.get_achievements(self.xuid, title_id)
                    if not data.get("achievements"):
                        raise ValueError("empty")
                    _json_response(self, data)
                except Exception:
                    try:
                        data = self.api.get_achievements_360(self.xuid, title_id)
                        _json_response(self, data)
                    except Exception as exc:
                        _json_response(self, {"error": str(exc)}, 500)
            elif path.startswith("/api/spoof/"):
                title_id = path.split("/api/spoof/", 1)[1]
                if not title_id:
                    _json_response(self, {"error": "No TitleId provided"}, 400)
                    return
                self.api.send_heartbeat(self.xuid, title_id)
                _json_response(self, {"message": f"Heartbeat sent for TitleId {title_id}"})
            else:
                _json_response(self, {"error": "Not found"}, 404)
        except Exception as exc:
            _json_response(self, {"error": str(exc)}, 500)
    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = _read_body(self)
            if path == "/api/achievements/unlock":
                title_id = body.get("TitleId", "").strip()
                ach_id = body.get("AchievementId", "").strip()
                if not title_id or not ach_id:
                    _json_response(self, {"error": "Provide TitleId and AchievementId"}, 400)
                    return
                scid = self._resolve_scid(title_id)
                self.api.unlock_achievements(self.xuid, scid, title_id, [ach_id])
                _json_response(self, {
                    "message": "Achievement unlocked successfully",
                    "achievementId": ach_id,
                    "titleId": title_id,
                })
            elif path == "/api/achievements/unlockall":
                title_id = body.get("TitleId", "").strip()
                if not title_id:
                    _json_response(self, {"error": "Provide TitleId"}, 400)
                    return
                data = self.api.get_achievements(self.xuid, title_id)
                scid = extract_scid_from_achievements(data)
                if not scid:
                    _json_response(self, {"error": "Could not resolve SCID for title"}, 500)
                    return
                locked_ids = [
                    a["id"] for a in data.get("achievements", [])
                    if a.get("progressState") != "Achieved"
                ]
                if not locked_ids:
                    _json_response(self, {"message": "All achievements already unlocked", "titleId": title_id})
                    return
                self.api.unlock_achievements(self.xuid, scid, title_id, locked_ids)
                _json_response(self, {
                    "message": "All achievements unlocked successfully",
                    "titleId": title_id,
                    "totalAchievements": len(locked_ids),
                })
            else:
                _json_response(self, {"error": "Not found"}, 404)
        except Exception as exc:
            _json_response(self, {"error": str(exc)}, 500)
    def _resolve_scid(self, title_id: str) -> str:
        if title_id in _Handler._scid_cache:
            return _Handler._scid_cache[title_id]
        data = self.api.get_achievements(self.xuid, title_id)
        scid = extract_scid_from_achievements(data)
        if not scid:
            raise RuntimeError(f"Could not resolve SCID for title {title_id}")
        _Handler._scid_cache[title_id] = scid
        return scid
class XAUServer:
    def __init__(
        self,
        api: XboxAPI,
        ach_manager: AchievementManager,
        xuid: str,
        xauth: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        _Handler.api = api
        _Handler.ach_manager = ach_manager
        _Handler.xuid = xuid
        _Handler.xauth = xauth
        _Handler._scid_cache = {}
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
    def start(self) -> None:
        if self.is_running:
            print(f"[server] Already running on port {self._port}.")
            return
        try:
            self._server = HTTPServer(("127.0.0.1", self._port), _Handler)
        except OSError as exc:
            print(f"[server] Could not bind to port {self._port}: {exc}")
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="xau-http-server",
            daemon=True,
        )
        self._thread.start()
        print(f"[server] Listening on http://127.0.0.1:{self._port}/")
    def stop(self) -> None:
        if not self.is_running:
            return
        self._server.shutdown()
        self._thread.join(timeout=5)
        print("[server] HTTP server stopped.")
    def set_port(self, port: int) -> None:
        if self.is_running:
            self.stop()
        self._port = port