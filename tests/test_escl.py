from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import urllib.error
import xml.etree.ElementTree as ET

from paperfeed.escl import (
    NO_HOST_MESSAGE,
    NS,
    ScanError,
    build_settings,
    check_dpi,
    configured_host,
    describe_adf,
    exclusive_write,
    job_url_from_location,
    output_path,
    parse_status,
    resolve_base,
    scan_to_pdf,
    scanner_status,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _xml(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class ParseStatusTests(unittest.TestCase):
    def test_idle_empty(self) -> None:
        state, adf = parse_status(_xml("status-idle-empty.xml"))
        self.assertEqual(state, "Idle")
        self.assertEqual(adf, "ScannerAdfEmpty")
        self.assertEqual(describe_adf(adf), "feeder is empty")

    def test_idle_loaded(self) -> None:
        state, adf = parse_status(_xml("status-idle-loaded.xml"))
        self.assertEqual(state, "Idle")
        self.assertEqual(adf, "ScannerAdfLoaded")
        self.assertEqual(describe_adf(adf), "paper in the feeder")

    def test_jam(self) -> None:
        state, adf = parse_status(_xml("status-jam.xml"))
        self.assertEqual(state, "Idle")
        self.assertEqual(adf, "ScannerAdfJam")
        self.assertEqual(describe_adf(adf), "feeder jam")

    def test_unknown_adf_passthrough(self) -> None:
        self.assertEqual(describe_adf("SomethingNew"), "SomethingNew")

    def test_missing_adf(self) -> None:
        self.assertEqual(describe_adf(None), "feeder state unknown")


class SettingsTests(unittest.TestCase):
    def _root(self, **kwargs):
        return ET.fromstring(build_settings(**kwargs))

    def test_single_sided_omits_true_duplex(self) -> None:
        root = self._root(source="Feeder", duplex=False, color="color", dpi=300, size="letter")
        self.assertEqual(root.find("pwg:InputSource", NS).text, "Feeder")
        self.assertEqual(root.find("scan:Duplex", NS).text, "false")
        self.assertEqual(root.find("scan:ColorMode", NS).text, "RGB24")

    def test_double_sided_sets_duplex_true(self) -> None:
        root = self._root(source="Feeder", duplex=True, color="color", dpi=300, size="letter")
        self.assertEqual(root.find("scan:Duplex", NS).text, "true")

    def test_glass_has_no_duplex_element(self) -> None:
        root = self._root(source="Platen", duplex=True, color="gray", dpi=300, size="letter")
        self.assertEqual(root.find("pwg:InputSource", NS).text, "Platen")
        self.assertIsNone(root.find("scan:Duplex", NS))
        self.assertEqual(root.find("scan:ColorMode", NS).text, "Grayscale8")


class DpiTests(unittest.TestCase):
    def test_1200_feeder_rejected(self) -> None:
        with self.assertRaises(ScanError) as ctx:
            check_dpi("Feeder", 1200)
        self.assertIn("glass", str(ctx.exception).lower())

    def test_1200_glass_ok(self) -> None:
        check_dpi("Platen", 1200)

    def test_300_feeder_ok(self) -> None:
        check_dpi("Feeder", 300)


class OutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path("/tmp/paperfeed-home")
        self.now = datetime(2026, 8, 29, 15, 4, 5)
        self.existing: set[Path] = set()

    def _exists(self, path: Path) -> bool:
        return path in self.existing

    def test_default_downloads_timestamp(self) -> None:
        path = output_path(now=self.now, exists=self._exists, home=self.home)
        self.assertEqual(path, self.home / "Downloads" / "scan-2026-08-29-150405.pdf")

    def test_custom_name_in_folder(self) -> None:
        path = output_path(
            folder=str(self.home / "Inbox"),
            filename="lease",
            now=self.now,
            exists=self._exists,
            home=self.home,
        )
        self.assertEqual(path, self.home / "Inbox" / "lease.pdf")

    def test_tilde_folder_uses_home(self) -> None:
        path = output_path(
            folder="~/Inbox",
            filename="lease.pdf",
            now=self.now,
            exists=self._exists,
            home=self.home,
        )
        self.assertEqual(path, self.home / "Inbox" / "lease.pdf")

    def test_full_output_path(self) -> None:
        path = output_path(
            output=str(self.home / "Desktop" / "form.pdf"),
            now=self.now,
            exists=self._exists,
            home=self.home,
        )
        self.assertEqual(path, self.home / "Desktop" / "form.pdf")

    def test_refuses_existing(self) -> None:
        target = self.home / "Downloads" / "scan-2026-08-29-150405.pdf"
        self.existing.add(target)
        with self.assertRaises(ScanError) as ctx:
            output_path(now=self.now, exists=self._exists, home=self.home)
        self.assertIn("already exists", str(ctx.exception))


class HostConfigTests(unittest.TestCase):
    def test_flag_wins_over_env(self) -> None:
        self.assertEqual(
            configured_host("flag.local", environ={"PAPERFEED_HOST": "env.local"}, home=Path("/tmp/none")),
            "flag.local",
        )

    def test_env(self) -> None:
        self.assertEqual(
            configured_host(None, environ={"PAPERFEED_HOST": "env.local"}, home=Path("/tmp/none")),
            "env.local",
        )

    def test_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            path = home / ".config" / "paperfeed" / "host"
            path.parent.mkdir(parents=True)
            path.write_text("# comment\nfile.local\n", encoding="utf-8")
            self.assertEqual(configured_host(None, environ={}, home=home), "file.local")

    def test_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(configured_host(None, environ={}, home=Path(raw)))

    def test_resolve_requires_host(self) -> None:
        with patch("paperfeed.escl.configured_host", return_value=None):
            with self.assertRaises(ScanError) as ctx:
                resolve_base()
        self.assertEqual(str(ctx.exception), NO_HOST_MESSAGE)
        self.assertNotIn("Epson", str(ctx.exception))

    def test_unreachable_is_generic(self) -> None:
        with patch("paperfeed.escl.configured_host", return_value="gone.local"):
            with patch("paperfeed.escl.probe_host", return_value=None):
                with patch("paperfeed.escl.host_lookup_failed", return_value=None):
                    with self.assertRaises(ScanError) as ctx:
                        resolve_base()
        self.assertIn("gone.local", str(ctx.exception))
        self.assertIn("Wi-Fi", str(ctx.exception))
        self.assertNotIn("Epson", str(ctx.exception))

    def test_falls_back_to_last_ip_when_hostname_misses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            cfg = home / ".config" / "paperfeed"
            cfg.mkdir(parents=True)
            (cfg / "last-ip").write_text("192.168.68.69\n", encoding="utf-8")

            def probe(host: str, timeout: float = 4) -> str | None:
                if host == "192.168.68.69":
                    return "https://192.168.68.69/eSCL"
                return None

            with patch("paperfeed.escl.configured_host", return_value="printer.local"):
                with patch("paperfeed.escl.probe_host", side_effect=probe):
                    base = resolve_base(home=home)
            self.assertEqual(base, "https://192.168.68.69/eSCL")

    def test_dns_failure_says_resolve_not_wifi(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            with patch("paperfeed.escl.configured_host", return_value="printer.local"):
                with patch("paperfeed.escl.probe_host", return_value=None):
                    with patch("paperfeed.escl.host_lookup_failed", return_value="nodename nor servname"):
                        with self.assertRaises(ScanError) as ctx:
                            resolve_base(home=home)
        self.assertIn("Could not resolve printer.local", str(ctx.exception))
        self.assertNotIn("Wi-Fi", str(ctx.exception))

    def test_successful_probe_remembers_ipv4(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            with patch("paperfeed.escl.configured_host", return_value="192.0.2.10"):
                with patch("paperfeed.escl.probe_host", return_value="https://192.0.2.10/eSCL"):
                    resolve_base(home=home)
            saved = (home / ".config" / "paperfeed" / "last-ip").read_text(encoding="utf-8").strip()
            self.assertEqual(saved, "192.0.2.10")


class ExclusiveWriteTests(unittest.TestCase):
    def test_refuses_to_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "out.pdf"
            exclusive_write(path, b"%PDF-one")
            with self.assertRaises(ScanError) as ctx:
                exclusive_write(path, b"%PDF-two")
            self.assertIn("already exists", str(ctx.exception))
            self.assertEqual(path.read_bytes(), b"%PDF-one")


class ScanLoopTests(unittest.TestCase):
    def test_keeps_every_pdf_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "out.pdf"
            with patch("paperfeed.escl.resolve_base", return_value="https://p/eSCL"):
                with patch("paperfeed.escl.scanner_status", return_value=("Idle", "ScannerAdfLoaded")):
                    with patch("paperfeed.escl.create_job", return_value="https://p/eSCL/ScanJobs/1"):
                        with patch(
                            "paperfeed.escl.next_document",
                            side_effect=[b"%PDF-one", b"%PDF-two", None],
                        ):
                            with patch("paperfeed.escl.delete_job"):
                                path = scan_to_pdf(
                                    source="Feeder",
                                    duplex=False,
                                    color="color",
                                    dpi=300,
                                    size="letter",
                                    output=str(out),
                                    log=lambda _m: None,
                                )
            self.assertEqual(path, out)
            self.assertEqual(out.read_bytes(), b"%PDF-one")
            extra = out.with_name("out-p2.pdf")
            self.assertEqual(extra.read_bytes(), b"%PDF-two")


class TransportTests(unittest.TestCase):
    def test_scanner_status_wraps_urlerror(self) -> None:
        with patch("paperfeed.escl.request", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(ScanError) as ctx:
                scanner_status("https://p/eSCL")
        self.assertIn("Could not reach the scanner", str(ctx.exception))


class JobUrlTests(unittest.TestCase):
    def test_absolute_path_location(self) -> None:
        url = job_url_from_location("https://printer.local/eSCL", "/eSCL/ScanJobs/1")
        self.assertEqual(url, "https://printer.local/eSCL/ScanJobs/1")

    def test_empty_location_errors(self) -> None:
        with self.assertRaises(ScanError):
            job_url_from_location("https://printer.local/eSCL", "")


if __name__ == "__main__":
    unittest.main()
