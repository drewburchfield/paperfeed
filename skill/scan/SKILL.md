---
name: scan
description: Use when the user asks to scan paper, digitize a document, use an ADF or document feeder, or mentions Epson Scan, ScanSmart, Image Capture scanning, eSCL, AirScan, or paperfeed. Runs the paperfeed CLI to make a PDF from an AirScan printer. Do not use for port scans, virus scans, secret scans, or repository scans.
license: MIT
metadata:
  requires:
    bins:
      - paperfeed
---

# Scan

`paperfeed` talks eSCL/AirScan on the LAN and writes a PDF. Run that command. Do not install Epson software, SANE, or NAPS2, and do not write a new ScanJobs / curl / Python eSCL client.

Project: [drewburchfield/paperfeed](https://github.com/drewburchfield/paperfeed). README is the full flag list.

## Do this

```bash
paperfeed --status
paperfeed
```

`--status` first. Default is feeder, single-sided, color, 300 dpi, letter. Output is `~/Downloads/scan-TIMESTAMP.pdf`.

Host comes from `--host`, else `PAPERFEED_HOST`, else `~/.config/paperfeed/host`. Do not hardcode a LAN address.

If the feeder is empty, ask the user to load pages face-up, top edge first (max 25 on the ET-3950), then rerun `paperfeed`. Do not switch to `--glass` unless they asked for the flatbed.

If they want the page instead of the CLI: `paperfeed ui` (http://127.0.0.1:8787).

If `paperfeed` is missing from PATH:

```bash
git clone https://github.com/drewburchfield/paperfeed.git
cd paperfeed && ./install.sh
```

Common flags: `--duplex`, `--glass`, `--color gray`, `--color bw`, `--size legal`, `--open`, `-o FILE.pdf`. `paperfeed --help` is complete.

## Failures

| Output | Action |
| Feeder is empty | Load paper, rerun. Do not invent another scanner path. |
| No scanner host | Pass `--host PRINTER.local` or write it to `~/.config/paperfeed/host`. |
| Could not reach the scanner | Printer off or on another Wi-Fi. Check `--host`. |
| jam / hatch open / overloaded | Clear the ADF, then `--status`. |
| 1200 dpi is only available on the glass | `--glass` or a lower `--dpi`. |
| That file already exists | Change `-o` or the file name. |
| extra page `name-p2.pdf` | Printer sent one PDF per page. Those files are the rest of the job. |

## Not this skill

Port scans, virus scans, repo scans, Family Fax.
