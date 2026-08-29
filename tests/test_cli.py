from __future__ import annotations

import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from paperfeed.cli import build_parser, main
from paperfeed.escl import ScanError


class ParserTests(unittest.TestCase):
    def test_defaults_are_single_sided_color_feeder(self) -> None:
        args = build_parser().parse_args([])
        self.assertFalse(args.duplex)
        self.assertFalse(args.glass)
        self.assertEqual(args.color, "color")
        self.assertEqual(args.dpi, 300)
        self.assertEqual(args.size, "letter")
        self.assertFalse(args.open)

    def test_duplex_flag(self) -> None:
        args = build_parser().parse_args(["--duplex"])
        self.assertTrue(args.duplex)

    def test_simplex_accepted(self) -> None:
        args = build_parser().parse_args(["--simplex"])
        self.assertFalse(args.duplex)


class MainTests(unittest.TestCase):
    def test_ui_dispatch(self) -> None:
        with patch("paperfeed.cli.run_ui", return_value=0) as ui:
            self.assertEqual(main(["ui"]), 0)
            ui.assert_called_once()
            self.assertEqual(ui.call_args.args[0], [])

    def test_ui_forwards_port(self) -> None:
        with patch("paperfeed.cli.run_ui", return_value=0) as ui:
            self.assertEqual(main(["ui", "--port", "9000", "--no-browser"]), 0)
            self.assertEqual(ui.call_args.args[0], ["--port", "9000", "--no-browser"])

    def test_1200_on_feeder_exits_2(self) -> None:
        with patch("paperfeed.cli.scan_to_pdf") as scan:
            code = main(["--dpi", "1200"])
        self.assertEqual(code, 2)
        scan.assert_not_called()

    def test_scan_passes_single_sided(self) -> None:
        with patch("paperfeed.cli.scan_to_pdf", autospec=True, return_value=Path("/tmp/scan.pdf")) as scan:
            self.assertEqual(main([]), 0)
        kwargs = scan.call_args.kwargs
        self.assertEqual(kwargs["source"], "Feeder")
        self.assertFalse(kwargs["duplex"])
        self.assertEqual(kwargs["color"], "color")
        self.assertEqual(kwargs["dpi"], 300)
        self.assertEqual(kwargs["size"], "letter")
        self.assertFalse(kwargs["open_when_done"])

    def test_scan_passes_duplex(self) -> None:
        with patch("paperfeed.cli.scan_to_pdf", autospec=True, return_value=Path("/tmp/scan.pdf")) as scan:
            self.assertEqual(main(["--duplex"]), 0)
        self.assertTrue(scan.call_args.kwargs["duplex"])

    def test_scan_passes_non_default_settings(self) -> None:
        with patch("paperfeed.cli.scan_to_pdf", autospec=True, return_value=Path("/tmp/scan.pdf")) as scan:
            self.assertEqual(main(["--color", "gray", "--dpi", "200", "--size", "legal", "--open"]), 0)
        kwargs = scan.call_args.kwargs
        self.assertEqual(kwargs["color"], "gray")
        self.assertEqual(kwargs["dpi"], 200)
        self.assertEqual(kwargs["size"], "legal")
        self.assertTrue(kwargs["open_when_done"])

    def test_status_transport_error(self) -> None:
        with patch("paperfeed.cli.resolve_base", return_value="https://printer/eSCL"):
            with patch("paperfeed.escl.request", side_effect=urllib.error.URLError("down")):
                self.assertEqual(main(["--status"]), 2)

    def test_status(self) -> None:
        with patch("paperfeed.cli.resolve_base", return_value="https://printer/eSCL"):
            with patch("paperfeed.cli.print_status", return_value=0) as status:
                self.assertEqual(main(["--status"]), 0)
                status.assert_called_once()

    def test_scan_error_is_exit_2(self) -> None:
        with patch("paperfeed.cli.scan_to_pdf", side_effect=ScanError("Feeder is empty. Load pages face-up in the ADF, then run paperfeed again.")):
            code = main([])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
