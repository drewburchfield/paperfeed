from __future__ import annotations

import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from paperfeed.escl import ScanError
from paperfeed.server import WEB_DIR, make_handler, serve


def _get(port: int, path: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
        return resp.status, resp.read()


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body)


class HtmlTests(unittest.TestCase):
    def test_page_copy(self) -> None:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("Single-sided", html)
        self.assertIn("Double-sided", html)
        self.assertIn("File name", html)
        self.assertIn("Folder", html)
        self.assertNotIn("Duplex", html)
        self.assertNotIn("duplex", html)


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        def status_fn(host=None):
            return {
                "scanner": "https://printer.local/eSCL",
                "state": "Idle",
                "feeder": "paper in the feeder",
                "adf": "ScannerAdfLoaded",
                "host": host,
            }

        def scan_fn(payload):
            if payload.get("filename") == "taken.pdf":
                raise ScanError("That file already exists. Choose another name.")
            return {"ok": True, "path": "/tmp/lease.pdf", "log": ["Scanning ADF single-sided"]}

        handler = make_handler(status_fn=status_fn, scan_fn=scan_fn)
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
        self.assertNotIn("Duplex", text)

    def test_status_json(self) -> None:
        status, body = _get(self.port, "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["state"], "Idle")
        self.assertEqual(data["feeder"], "paper in the feeder")
        self.assertIn("scanner", data)

    def test_scan_ok(self) -> None:
        code, data = _post(self.port, "/api/scan", {"filename": "lease.pdf", "sides": "single"})
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["path"], "/tmp/lease.pdf")

    def test_scan_existing_file(self) -> None:
        code, data = _post(self.port, "/api/scan", {"filename": "taken.pdf"})
        self.assertEqual(code, 400)
        self.assertFalse(data["ok"])
        self.assertIn("already exists", data["error"])


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
            self.assertIn("--port", str(ctx.exception))
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
