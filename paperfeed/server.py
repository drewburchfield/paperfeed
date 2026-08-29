"""Localhost UI for paperfeed."""

from __future__ import annotations

import errno
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from paperfeed.escl import (
    COLOR_MODES,
    SIZES,
    ScanError,
    assert_home_pdf,
    describe_adf,
    open_pdf,
    reveal_pdf,
    resolve_base,
    scan_to_pdf,
    scanner_status,
)

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8787
TOKEN_PLACEHOLDER = "__PAPERFEED_TOKEN__"
ALLOWED_DPI = {100, 200, 300, 600, 1200}
ALLOWED_SOURCES = {"feeder", "glass"}
ALLOWED_SIDES = {"single", "double"}


def parse_scan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source_raw = payload.get("source") or "feeder"
    if source_raw not in ALLOWED_SOURCES:
        raise ScanError("Invalid source.")
    sides = payload.get("sides") or "single"
    if sides not in ALLOWED_SIDES:
        raise ScanError("Invalid sides.")
    color = payload.get("color") or "color"
    if color not in COLOR_MODES:
        raise ScanError("Invalid color.")
    try:
        dpi = int(payload.get("dpi") or 300)
    except (TypeError, ValueError) as exc:
        raise ScanError("Invalid dpi.") from exc
    if dpi not in ALLOWED_DPI:
        raise ScanError("Invalid dpi.")
    size = payload.get("size") or "letter"
    if size not in SIZES:
        raise ScanError("Invalid size.")
    open_flag = payload.get("open")
    if open_flag not in (True, False, None):
        raise ScanError("Invalid open flag.")
    host = payload.get("host") or None
    if host is not None:
        host = str(host).strip() or None
    folder = payload.get("folder") or None
    if folder is not None:
        folder = str(folder).strip() or None
    filename = payload.get("filename") or None
    if filename is not None:
        filename = str(filename).strip() or None
    return {
        "source": "Platen" if source_raw == "glass" else "Feeder",
        "duplex": source_raw == "feeder" and sides == "double",
        "color": color,
        "dpi": dpi,
        "size": size,
        "host": host,
        "folder": folder,
        "filename": filename,
        "open_when_done": bool(open_flag),
    }


def default_status(host: Optional[str] = None) -> dict[str, Any]:
    base = resolve_base(host)
    state, adf = scanner_status(base)
    return {
        "scanner": base,
        "state": state,
        "feeder": describe_adf(adf),
        "adf": adf,
    }


def default_scan(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_scan_payload(payload)
    log_lines: list[str] = []

    def log(message: str) -> None:
        log_lines.append(message)

    path = scan_to_pdf(log=log, **parsed)
    return {"ok": True, "path": str(path), "log": log_lines}


def origin_allowed(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def make_handler(
    *,
    status_fn: Callable[..., dict[str, Any]] = default_status,
    scan_fn: Callable[[dict[str, Any]], dict[str, Any]] = default_scan,
    open_fn: Callable[[Path], None] = open_pdf,
    reveal_fn: Callable[[Path], None] = reveal_pdf,
    html: Optional[bytes] = None,
    token: str = "test-token",
) -> type[BaseHTTPRequestHandler]:
    raw = html if html is not None else (WEB_DIR / "index.html").read_bytes()
    page = raw.replace(TOKEN_PLACEHOLDER.encode("utf-8"), token.encode("utf-8"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")

        def _token_ok(self) -> bool:
            sent = self.headers.get("X-Paperfeed-Token") or ""
            if len(sent) != len(token):
                return False
            return secrets.compare_digest(sent, token)

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return origin_allowed(origin)

        def _require_api(self) -> bool:
            if not self._token_ok():
                self._json(403, {"ok": False, "error": "Missing or invalid token."})
                return False
            if not self._origin_ok():
                self._json(403, {"ok": False, "error": "Invalid origin."})
                return False
            return True

        def _read_json(self) -> dict[str, Any]:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                raise ScanError("Content-Type must be application/json.")
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length) if length else b"{}"
            if not raw_body:
                return {}
            data = json.loads(raw_body.decode("utf-8"))
            if not isinstance(data, dict):
                raise ScanError("Expected a JSON object.")
            return data

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                if not self._require_api():
                    return
                host = (parse_qs(parsed.query).get("host") or [None])[0] or None
                try:
                    self._json(200, status_fn(host))
                except ScanError as exc:
                    self._json(503, {"error": str(exc)})
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._require_api():
                return
            try:
                payload = self._read_json()
            except (json.JSONDecodeError, ScanError) as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            try:
                if parsed.path == "/api/scan":
                    self._json(200, scan_fn(payload))
                    return
                if parsed.path == "/api/open":
                    open_fn(assert_home_pdf(Path(str(payload.get("path") or ""))))
                    self._json(200, {"ok": True})
                    return
                if parsed.path == "/api/reveal":
                    reveal_fn(assert_home_pdf(Path(str(payload.get("path") or ""))))
                    self._json(200, {"ok": True})
                    return
            except ScanError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

    return Handler


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    handler: Optional[type[BaseHTTPRequestHandler]] = None,
) -> int:
    token = secrets.token_urlsafe(32)
    Handler = handler or make_handler(token=token)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        httpd = Server((host, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise ScanError(f"Port {port} is in use. Try paperfeed ui --port PORT.") from exc
        raise

    url = f"http://{host}:{httpd.server_address[1]}"
    print(f"paperfeed ui: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\npaperfeed: cancelled")
    finally:
        httpd.server_close()
    return 0
