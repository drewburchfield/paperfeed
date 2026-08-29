#!/usr/bin/env python3
"""Talk to an eSCL/AirScan scanner on the LAN."""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

NS = {
    "scan": "http://schemas.hp.com/imaging/escl/2011/05/03",
    "pwg": "http://www.pwg.org/schemas/2010/12/sm",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

BASE_PATH = "/eSCL"
NO_HOST_MESSAGE = (
    "No scanner host. Pass --host PRINTER.local, set PAPERFEED_HOST, "
    "or put the hostname in ~/.config/paperfeed/host."
)
SIZES = {
    "letter": (2550, 3300),
    "legal": (2550, 4200),
    "a4": (2480, 3508),
}
COLOR_MODES = {
    "color": "RGB24",
    "gray": "Grayscale8",
    "bw": "BlackAndWhite1",
}
ADF_BLOCKED = {
    "ScannerAdfJam",
    "ScannerAdfMispick",
    "ScannerAdfHatchOpen",
    "ScannerAdfInputTrayOverloaded",
    "ScannerAdfMultipickDetected",
}


class ScanError(RuntimeError):
    pass


def ssl_context() -> ssl.SSLContext:
    # eSCL printers present a self-signed device certificate on HTTPS.
    ctx = ssl._create_unverified_context()
    ctx.check_hostname = False
    return ctx


def request(
    url: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 15,
) -> Tuple[int, Dict[str, str], bytes]:
    hdrs = {
        "User-Agent": "paperfeed/1.0",
        "Accept": "*/*",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            body = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        if 400 <= exc.code < 600:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body
        raise


def find_text(root: ET.Element, path: str) -> Optional[str]:
    node = root.find(path, NS)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def parse_xml(body: bytes) -> ET.Element:
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise ScanError(f"Scanner returned unreadable XML: {exc}") from exc


def parse_status(body: bytes) -> Tuple[str, Optional[str]]:
    root = parse_xml(body)
    state = find_text(root, "pwg:State") or "Unknown"
    adf = find_text(root, "scan:AdfState")
    return state, adf


def probe_host(host: str) -> Optional[str]:
    url = f"https://{host}{BASE_PATH}/ScannerStatus"
    try:
        status, _, body = request(url, timeout=4)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if status != 200 or not body:
        return None
    return url.rsplit("/", 1)[0]


def host_config_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / ".config" / "paperfeed" / "host"


def configured_host(
    preferred: Optional[str] = None,
    *,
    environ: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Optional[str]:
    if preferred and preferred.strip():
        return preferred.strip()
    envmap = os.environ if environ is None else environ
    env = str(envmap.get("PAPERFEED_HOST", "")).strip()
    if env:
        return env
    path = host_config_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def resolve_base(preferred: Optional[str] = None) -> str:
    host = configured_host(preferred)
    if not host:
        raise ScanError(NO_HOST_MESSAGE)
    base = probe_host(host)
    if base:
        return base
    raise ScanError(
        f"Could not reach the scanner at {host}. Check that it is on and on this Wi-Fi."
    )


def scanner_status(base: str) -> Tuple[str, Optional[str]]:
    status, _, body = request(f"{base}/ScannerStatus", timeout=6)
    if status != 200:
        raise ScanError(f"ScannerStatus failed ({status}): {body[:300]!r}")
    return parse_status(body)


def describe_adf(adf: Optional[str]) -> str:
    labels = {
        "ScannerAdfEmpty": "feeder is empty",
        "ScannerAdfLoaded": "paper in the feeder",
        "ScannerAdfProcessing": "feeder is working",
        "ScannerAdfJam": "feeder jam",
        "ScannerAdfMispick": "feeder mispick",
        "ScannerAdfHatchOpen": "feeder cover open",
        "ScannerAdfInputTrayOverloaded": "too many pages in the feeder (max 25)",
        "ScannerAdfMultipickDetected": "feeder picked more than one page",
    }
    if adf is None:
        return "feeder state unknown"
    return labels.get(adf, adf)


def check_dpi(source: str, dpi: int) -> None:
    if dpi == 1200 and source != "Platen":
        raise ScanError("1200 dpi is only available on the glass. Use --glass or a lower --dpi.")


def build_settings(
    *,
    source: str,
    duplex: bool,
    color: str,
    dpi: int,
    size: str,
) -> bytes:
    width, height = SIZES[size]
    if source == "Platen":
        height = min(height, 3510)
    elif duplex:
        height = min(height, 3510)
    else:
        height = min(height, 4200)

    scan = NS["scan"]
    pwg = NS["pwg"]
    root = ET.Element(f"{{{scan}}}ScanSettings")
    ET.SubElement(root, f"{{{pwg}}}Version").text = "2.9"
    ET.SubElement(root, f"{{{pwg}}}Intent").text = "Document"
    regions = ET.SubElement(root, f"{{{pwg}}}ScanRegions")
    region = ET.SubElement(regions, f"{{{pwg}}}ScanRegion")
    ET.SubElement(region, f"{{{pwg}}}ContentRegionUnits").text = "escl:ThreeHundredthsOfInches"
    ET.SubElement(region, f"{{{pwg}}}XOffset").text = "0"
    ET.SubElement(region, f"{{{pwg}}}YOffset").text = "0"
    ET.SubElement(region, f"{{{pwg}}}Width").text = str(width)
    ET.SubElement(region, f"{{{pwg}}}Height").text = str(height)
    ET.SubElement(root, f"{{{pwg}}}InputSource").text = source
    ET.SubElement(root, f"{{{scan}}}ColorMode").text = COLOR_MODES[color]
    ET.SubElement(root, f"{{{scan}}}XResolution").text = str(dpi)
    ET.SubElement(root, f"{{{scan}}}YResolution").text = str(dpi)
    ET.SubElement(root, f"{{{pwg}}}DocumentFormat").text = "application/pdf"
    ET.SubElement(root, f"{{{scan}}}DocumentFormatExt").text = "application/pdf"
    if source == "Feeder":
        ET.SubElement(root, f"{{{scan}}}Duplex").text = "true" if duplex else "false"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def job_url_from_location(base: str, location: str) -> str:
    if not location:
        raise ScanError("Scanner accepted the job but sent no Location header.")
    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        path = parsed.path
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{base.rsplit('/eSCL', 1)[0]}{path}{query}" if path.startswith("/") else urljoin(base + "/", location)
    return urljoin(base + "/", location)


def create_job(base: str, settings: bytes) -> str:
    status, headers, body = request(
        f"{base}/ScanJobs",
        method="POST",
        data=settings,
        headers={"Content-Type": "text/xml; charset=utf-8", "Accept": "application/xml, text/xml, */*"},
        timeout=20,
    )
    if status not in (200, 201, 202):
        detail = body.decode("utf-8", "replace")[:500] or f"HTTP {status}"
        raise ScanError(f"Scanner refused the job: {detail}")
    location = headers.get("location") or headers.get("content-location")
    if not location and body:
        try:
            root = parse_xml(body)
            location = find_text(root, "pwg:JobUri") or find_text(root, "scan:JobUri")
        except ScanError:
            location = None
    return job_url_from_location(base, location or "")


def next_document(job_url: str, timeout: float = 180) -> Optional[bytes]:
    url = job_url.rstrip("/") + "/NextDocument"
    deadline = time.time() + 600
    last = ""
    while time.time() < deadline:
        remaining = max(5, min(timeout, deadline - time.time()))
        try:
            status, headers, body = request(
                url,
                headers={"Accept": "application/pdf, image/jpeg, */*"},
                timeout=remaining,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            time.sleep(2)
            last = str(exc)
            continue
        if status == 200 and body:
            return body
        if status in (404, 410):
            return None
        if status in (503, 409):
            retry = headers.get("retry-after")
            try:
                wait = min(5.0, max(1.0, float(retry))) if retry else 1.5
            except ValueError:
                wait = 1.5
            time.sleep(wait)
            continue
        if status >= 400:
            detail = body.decode("utf-8", "replace")[:400]
            raise ScanError(f"NextDocument failed ({status}): {detail or 'no body'}")
        time.sleep(1)
    extra = f" ({last})" if last else ""
    raise ScanError(f"Timed out waiting for the scanner to finish.{extra}")


def delete_job(job_url: str) -> None:
    try:
        request(job_url, method="DELETE", timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, ScanError):
        pass


def expand_user(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    return Path(value)


def output_path(
    *,
    output: Optional[str] = None,
    folder: Optional[str] = None,
    filename: Optional[str] = None,
    now: Optional[datetime] = None,
    exists: Optional[Callable[[Path], bool]] = None,
    home: Optional[Path] = None,
) -> Path:
    home = home or Path.home()
    exists_fn = exists or (lambda p: p.exists())
    stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M%S")

    if output:
        path = expand_user(output, home)
    else:
        folder_path = expand_user(folder, home) if folder else home / "Downloads"
        name = filename or f"scan-{stamp}.pdf"
        path = folder_path / name

    if not path.name.lower().endswith(".pdf"):
        path = path.with_name(path.name + ".pdf")
    if exists_fn(path):
        raise ScanError("That file already exists. Choose another name.")
    return path


def write_pdf(path: Path, chunks: list[bytes]) -> None:
    if not chunks:
        raise ScanError("Scanner returned no pages.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(chunks) == 1 and chunks[0][:5] == b"%PDF-":
        path.write_bytes(chunks[0])
        return
    if all(c[:5] == b"%PDF-" for c in chunks):
        path.write_bytes(chunks[0])
        for index, chunk in enumerate(chunks[1:], start=2):
            extra = path.with_name(f"{path.stem}-p{index}{path.suffix}")
            extra.write_bytes(chunk)
        return
    raise ScanError("Scanner returned something other than a PDF. Try again or use --glass.")


def open_pdf(path: Path) -> None:
    os.spawnlp(os.P_NOWAIT, "open", "open", str(path))


def reveal_pdf(path: Path) -> None:
    os.spawnlp(os.P_NOWAIT, "open", "open", "-R", str(path))


def assert_home_pdf(path: Path, home: Optional[Path] = None) -> Path:
    home = (home or Path.home()).resolve()
    resolved = path.expanduser().resolve()
    if resolved.suffix.lower() != ".pdf":
        raise ScanError("Only PDF files can be opened.")
    try:
        resolved.relative_to(home)
    except ValueError as exc:
        raise ScanError("That PDF is outside your home directory.") from exc
    if not resolved.is_file():
        raise ScanError("That PDF does not exist.")
    return resolved


def print_status(base: str) -> int:
    state, adf = scanner_status(base)
    print(f"Scanner: {base}")
    print(f"State:   {state}")
    print(f"Feeder:  {describe_adf(adf)}")
    return 0 if state == "Idle" else 1


def scan_to_pdf(
    *,
    source: str,
    duplex: bool,
    color: str,
    dpi: int,
    size: str,
    host: Optional[str] = None,
    output: Optional[str] = None,
    folder: Optional[str] = None,
    filename: Optional[str] = None,
    open_when_done: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    check_dpi(source, dpi)
    out = output_path(output=output, folder=folder, filename=filename)
    base = resolve_base(host)
    state, adf = scanner_status(base)
    if state not in ("Idle", "Processing"):
        raise ScanError(f"Scanner is {state}. {describe_adf(adf)}.")

    if source == "Feeder":
        if adf == "ScannerAdfEmpty":
            raise ScanError("Feeder is empty. Load pages face-up in the ADF, then run scan again.")
        if adf in ADF_BLOCKED:
            raise ScanError(f"Cannot scan: {describe_adf(adf)}.")

    duplex = source == "Feeder" and duplex
    settings = build_settings(
        source=source,
        duplex=duplex,
        color=color,
        dpi=dpi,
        size=size,
    )

    source_label = "glass" if source == "Platen" else ("ADF double-sided" if duplex else "ADF single-sided")
    log(f"Scanning {source_label}, {color}, {dpi} dpi, {size} → {out}")

    job_url = create_job(base, settings)
    chunks: list[bytes] = []
    try:
        while True:
            page = next_document(job_url)
            if page is None:
                break
            chunks.append(page)
            log(f"  received {len(page):,} bytes")
            if page[:5] == b"%PDF-":
                break
    finally:
        delete_job(job_url)

    write_pdf(out, chunks)
    log(str(out))
    if open_when_done:
        open_pdf(out)
    return out
