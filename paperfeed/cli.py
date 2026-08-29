"""Command-line entry for paperfeed."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from paperfeed.escl import (
    COLOR_MODES,
    SIZES,
    ScanError,
    check_dpi,
    print_status as escl_print_status,
    resolve_base,
    scan_to_pdf,
)


def print_status(base: str) -> int:
    return escl_print_status(base)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperfeed",
        description=(
            "Scan from an eSCL/AirScan printer on the LAN to PDF. "
            "Default is the document feeder, single-sided, color. "
            "Tested on the Epson ET-3950."
        ),
    )
    parser.add_argument("--status", action="store_true", help="Show scanner and feeder state, then exit")
    parser.add_argument("--glass", action="store_true", help="Scan the flatbed instead of the feeder")
    parser.add_argument(
        "--duplex",
        action="store_true",
        help="Double-sided (ADF)",
    )
    parser.add_argument(
        "--simplex",
        action="store_true",
        help="Single-sided (default; accepted for compatibility)",
    )
    parser.add_argument(
        "--color",
        choices=sorted(COLOR_MODES),
        default="color",
        help="color (default), gray, or bw",
    )
    parser.add_argument("--dpi", type=int, choices=(100, 200, 300, 600, 1200), default=300)
    parser.add_argument("--size", choices=sorted(SIZES), default="letter")
    parser.add_argument("-o", "--output", help="Output PDF path (default: ~/Downloads/scan-TIMESTAMP.pdf)")
    parser.add_argument(
        "--host",
        help="Scanner hostname or IP (or PAPERFEED_HOST, or ~/.config/paperfeed/host)",
    )
    parser.add_argument("--open", action="store_true", help="Open the PDF when done")
    return parser


def run_scan(args: argparse.Namespace) -> int:
    source = "Platen" if args.glass else "Feeder"
    check_dpi(source, args.dpi)
    scan_to_pdf(
        source=source,
        duplex=bool(args.duplex),
        color=args.color,
        dpi=args.dpi,
        size=args.size,
        host=args.host,
        output=args.output,
        open_when_done=args.open,
    )
    return 0


def run_ui(argv: list[str]) -> int:
    from paperfeed.server import serve

    parser = argparse.ArgumentParser(prog="paperfeed ui", description="Open the localhost scan page.")
    parser.add_argument("--port", type=int, default=8787, help="Port (default 8787)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = parser.parse_args(argv)
    return serve(port=args.port, open_browser=not args.no_browser)


def main(argv: Optional[list[str]] = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list[:1] == ["ui"]:
        try:
            return run_ui(argv_list[1:])
        except ScanError as exc:
            print(f"paperfeed: {exc}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("paperfeed: cancelled", file=sys.stderr)
            return 130
    args = build_parser().parse_args(argv_list)
    try:
        if args.status:
            return print_status(resolve_base(args.host))
        return run_scan(args)
    except ScanError as exc:
        print(f"paperfeed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("paperfeed: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
