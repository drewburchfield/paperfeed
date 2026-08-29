from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from paperfeed.escl import (
    NO_HOST_MESSAGE,
    ScanError,
    build_settings,
    check_dpi,
    configured_host,
    describe_adf,
    job_url_from_location,
    output_path,
    parse_status,
    resolve_base,
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
    def test_single_sided_omits_true_duplex(self) -> None:
        xml = build_settings(
            source="Feeder",
            duplex=False,
            color="color",
            dpi=300,
            size="letter",
        ).decode("utf-8")
        self.assertIn("Feeder", xml)
        self.assertIn(">false<", xml)
        self.assertNotIn(">true<", xml)

    def test_double_sided_sets_duplex_true(self) -> None:
        xml = build_settings(
            source="Feeder",
            duplex=True,
            color="color",
            dpi=300,
            size="letter",
        ).decode("utf-8")
        self.assertIn(">true<", xml)

    def test_glass_has_no_duplex_element(self) -> None:
        xml = build_settings(
            source="Platen",
            duplex=True,
            color="gray",
            dpi=300,
            size="letter",
        ).decode("utf-8")
        self.assertIn("Platen", xml)
        self.assertNotIn("Duplex", xml)
        self.assertIn("Grayscale8", xml)


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
        self.assertIsNone(configured_host(None, environ={}, home=Path("/tmp/paperfeed-no-config")))

    def test_resolve_requires_host(self) -> None:
        with patch("paperfeed.escl.configured_host", return_value=None):
            with self.assertRaises(ScanError) as ctx:
                resolve_base()
        self.assertEqual(str(ctx.exception), NO_HOST_MESSAGE)
        self.assertNotIn("Epson", str(ctx.exception))

    def test_unreachable_is_generic(self) -> None:
        with patch("paperfeed.escl.configured_host", return_value="gone.local"):
            with patch("paperfeed.escl.probe_host", return_value=None):
                with self.assertRaises(ScanError) as ctx:
                    resolve_base()
        self.assertIn("gone.local", str(ctx.exception))
        self.assertNotIn("Epson", str(ctx.exception))


class JobUrlTests(unittest.TestCase):
    def test_absolute_path_location(self) -> None:
        url = job_url_from_location("https://printer.local/eSCL", "/eSCL/ScanJobs/1")
        self.assertEqual(url, "https://printer.local/eSCL/ScanJobs/1")

    def test_empty_location_errors(self) -> None:
        with self.assertRaises(ScanError):
            job_url_from_location("https://printer.local/eSCL", "")


if __name__ == "__main__":
    unittest.main()
