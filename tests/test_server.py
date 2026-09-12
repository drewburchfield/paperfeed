from __future__ import annotations

import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from paperfeed.escl import ScanError
from paperfeed.server import WEB_DIR, make_handler, parse_scan_payload, serve

TOKEN = "test-token"


def _get(port: int, path: str, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(
    port: int,
    path: str,
    payload: dict | bytes,
    headers: dict | None = None,
) -> tuple[int, dict | bytes]:
    if isinstance(payload, bytes):
        data = payload
    else:
        data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "X-Paperfeed-Token": TOKEN}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=hdrs,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read()
            if "json" in resp.headers.get("Content-Type", ""):
                return resp.status, json.loads(body.decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return exc.code, body


class HtmlTests(unittest.TestCase):
    def test_page_copy(self) -> None:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("Single-sided", html)
        self.assertIn("Double-sided", html)
        self.assertIn("File name", html)
        self.assertIn("Folder", html)
        self.assertIn("__PAPERFEED_TOKEN__", html)
        self.assertIn("statusInFlight", html)
        self.assertIn('id="scan" type="button"', html)
        self.assertNotIn("Duplex", html)
        self.assertNotIn("duplex", html)


class PayloadTests(unittest.TestCase):
    def test_defaults(self) -> None:
        parsed = parse_scan_payload({})
        self.assertEqual(parsed["source"], "Feeder")
        self.assertFalse(parsed["duplex"])
        self.assertEqual(parsed["color"], "color")
        self.assertEqual(parsed["dpi"], 300)
        self.assertEqual(parsed["size"], "letter")

    def test_invalid_dpi(self) -> None:
        with self.assertRaises(ScanError):
            parse_scan_payload({"dpi": "abc"})

    def test_invalid_color(self) -> None:
        with self.assertRaises(ScanError):
            parse_scan_payload({"color": "sepia"})

    def test_invalid_size(self) -> None:
        with self.assertRaises(ScanError):
            parse_scan_payload({"size": "tabloid"})


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payloads: list[dict] = []

        def status_fn(host=None):
            return {
                "scanner": "https://printer.local/eSCL",
                "state": "Idle",
                "feeder": "paper in the feeder",
                "adf": "ScannerAdfLoaded",
                "host": host,
            }

        def scan_fn(payload):
            self.payloads.append(payload)
            if payload.get("filename") == "taken.pdf":
                raise ScanError("That file already exists. Choose another name.")
            return {"ok": True, "path": "/tmp/lease.pdf", "log": ["Scanning ADF single-sided"]}

        handler = make_handler(status_fn=status_fn, scan_fn=scan_fn, token=TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_index_contains_sides_copy(self) -> None:
        status, body = _get(self.port, "/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("Single-sided", text)
        self.assertIn("File name", text)
        self.assertIn(TOKEN, text)
        self.assertNotIn("__PAPERFEED_TOKEN__", text)
        self.assertNotIn("Duplex", text)

    def test_status_json(self) -> None:
        status, body = _get(self.port, "/api/status", headers={"X-Paperfeed-Token": TOKEN})
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["state"], "Idle")
        self.assertEqual(data["feeder"], "paper in the feeder")
        self.assertIn("scanner", data)

    def test_status_requires_token(self) -> None:
        status, _body = _get(self.port, "/api/status")
        self.assertEqual(status, 403)

    def test_scan_ok(self) -> None:
        code, data = _post(
            self.port,
            "/api/scan",
            {"filename": "lease.pdf", "sides": "single", "color": "gray", "dpi": 200, "size": "legal"},
        )
        self.assertEqual(code, 200)
        assert isinstance(data, dict)
        self.assertTrue(data["ok"])
        self.assertEqual(data["path"], "/tmp/lease.pdf")
        self.assertEqual(self.payloads[0]["color"], "gray")
        self.assertEqual(self.payloads[0]["dpi"], 200)
        self.assertEqual(self.payloads[0]["size"], "legal")
        self.assertEqual(self.payloads[0]["sides"], "single")

    def test_scan_existing_file(self) -> None:
        code, data = _post(self.port, "/api/scan", {"filename": "taken.pdf"})
        self.assertEqual(code, 400)
        assert isinstance(data, dict)
        self.assertFalse(data["ok"])
        self.assertIn("already exists", data["error"])

    def test_scan_rejects_missing_token(self) -> None:
        code, data = _post(self.port, "/api/scan", {"filename": "x.pdf"}, headers={"X-Paperfeed-Token": "nope"})
        self.assertEqual(code, 403)
        assert isinstance(data, dict)
        self.assertIn("token", data["error"])

    def test_scan_rejects_foreign_origin(self) -> None:
        code, data = _post(
            self.port,
            "/api/scan",
            {"filename": "x.pdf"},
            headers={"Origin": "http://evil.example"},
        )
        self.assertEqual(code, 403)
        assert isinstance(data, dict)
        self.assertIn("origin", data["error"].lower())
        self.assertEqual(self.payloads, [])

    def test_scan_rejects_plain_text(self) -> None:
        code, data = _post(
            self.port,
            "/api/scan",
            b'{"filename":"x.pdf"}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(code, 400)
        assert isinstance(data, dict)
        self.assertIn("application/json", data["error"])
        self.assertEqual(self.payloads, [])


class DefaultScanHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        handler = make_handler(token=TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_invalid_dpi_json_error(self) -> None:
        with patch("paperfeed.server.scan_to_pdf") as scan:
            code, data = _post(self.port, "/api/scan", {"dpi": "abc"})
        self.assertEqual(code, 400)
        assert isinstance(data, dict)
        self.assertFalse(data["ok"])
        self.assertIn("dpi", data["error"].lower())
        scan.assert_not_called()

    def test_valid_payload_reaches_scan_to_pdf(self) -> None:
        with patch("paperfeed.server.scan_to_pdf", return_value=Path("/tmp/out.pdf")) as scan:
            code, data = _post(
                self.port,
                "/api/scan",
                {"source": "feeder", "sides": "double", "color": "gray", "dpi": 200, "size": "legal"},
            )
        self.assertEqual(code, 200)
        assert isinstance(data, dict)
        self.assertTrue(data["ok"])
        kwargs = scan.call_args.kwargs
        self.assertEqual(kwargs["source"], "Feeder")
        self.assertTrue(kwargs["duplex"])
        self.assertEqual(kwargs["color"], "gray")
        self.assertEqual(kwargs["dpi"], 200)
        self.assertEqual(kwargs["size"], "legal")


class BindTests(unittest.TestCase):
    def test_port_in_use(self) -> None:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            with self.assertRaises(ScanError) as ctx:
                serve(port=port, open_browser=False)
            self.assertIn("in use", str(ctx.exception))
            self.assertIn("paperfeed ui --port", str(ctx.exception))
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
