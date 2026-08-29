---
name: scan
description: Use when the user asks to scan paper, scan a document, scan from an Epson printer, use the ADF or document feeder, digitize pages, or turn a stack of pages into a PDF. Also when they mention Epson Scan, ScanSmart, Image Capture scanning, eSCL, AirScan, or paperfeed. Do not use for port scans, virus scans, secret scans, or repository scans.
metadata:
  requires:
    bins:
      - paperfeed
---

# Scan

Paper on the LAN becomes a PDF through `paperfeed`. The printer already speaks eSCL. Run that command. Do not install Epson software, SANE, or NAPS2, and do not write a new ScanJobs / curl / Python eSCL client.

Project: [drewburchfield/paperfeed](https://github.com/drewburchfield/paperfeed).

## Do this

```bash
paperfeed --status
paperfeed
```

`--status` first. Default is the document feeder, single-sided, color, 300 dpi, letter. Output is `~/Downloads/scan-TIMESTAMP.pdf`.

Host comes from `--host`, `PAPERFEED_HOST`, or `~/.config/paperfeed/host`. Do not hardcode a LAN address.

If the feeder is empty, ask the user to load pages face-up, top edge first (max 25 on the ET-3950), then rerun `paperfeed`. Do not switch to `--glass` unless they asked for the flatbed.

If `paperfeed` is missing from PATH:

```bash
git clone https://github.com/drewburchfield/paperfeed.git
cd paperfeed && ./install.sh
```

`paperfeed --help` is the flag list. Common ones: `--duplex`, `--glass`, `--color gray`, `--color bw`, `--size legal`, `--open`, `-o FILE.pdf`. UI: `paperfeed ui`.

## Failures

| Output | Action |
| Feeder is empty | Load paper, rerun. Do not invent another scanner path. |
| No scanner host | Check `~/.config/paperfeed/host` or pass `--host`. |
| Could not reach the scanner | Printer off or on another network. |
| jam / hatch open / overloaded | Clear the ADF, then `--status`. |

## Not this skill

Port scans, virus scans, repo scans, Family Fax.
