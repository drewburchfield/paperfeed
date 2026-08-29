"""Localhost UI for scan."""

from __future__ import annotations

import errno
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from paperfeed.escl import (
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
    source = "Platen" if payload.get("source") == "glass" else "Feeder"
    duplex = source == "Feeder" and payload.get("sides") == "double"
    log_lines: list[str] = []

    def log(message: str) -> None:
        log_lines.append(message)

    path = scan_to_pdf(
        source=source,
        duplex=duplex,
        color=str(payload.get("color") or "color"),
        dpi=int(payload.get("dpi") or 300),
        size=str(payload.get("size") or "letter"),
        host=payload.get("host") or None,
        folder=payload.get("folder") or None,
        filename=payload.get("filename") or None,
        open_when_done=bool(payload.get("open")),
        log=log,
    )
    return {"ok": True, "path": str(path), "log": log_lines}


def make_handler(
    *,
    status_fn: Callable[..., dict[str, Any]] = default_status,
    scan_fn: Callable[[dict[str, Any]], dict[str, Any]] = default_scan,
    open_fn: Callable[[Path], None] = open_pdf,
    reveal_fn: Callable[[Path], None] = reveal_pdf,
    html: Optional[bytes] = None,
) -> type[BaseHTTPRequestHandler]:
    page = html if html is not None else (WEB_DIR / "index.html").read_bytes()

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

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ScanError("Expected a JSON object.")
            return data

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                host = (parse_qs(parsed.query).get("host") or [None])[0] or None
                try:
                    self._json(200, status_fn(host))
                except ScanError as exc:
                    self._json(503, {"error": str(exc)})
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
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
    Handler = handler or make_handler()

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        httpd = Server((host, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise ScanError(f"Port {port} is in use. Try scan ui --port PORT.") from exc
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
