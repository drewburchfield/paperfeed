[![paperfeed](https://ghrb.waren.build/banner?header=paperfeed&subheader=Scan+paper+from+your+printer+to+PDF&bg=1A1A1A-4A4A4A&color=FFFFFF&headerfont=Inter&subheaderfont=Inter&support=false)](https://github.com/drewburchfield/paperfeed)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/drewburchfield/paperfeed)

Scan paper from an AirScan/eSCL printer on your LAN to a PDF. The command is `paperfeed`. A localhost page is `paperfeed ui`. Python 3 standard library only.

Built by someone who wanted the document feeder without installing Epson ScanSmart. If you have an AirScan printer on the network and want a PDF, this is for you.

This project is not affiliated with Seiko Epson Corporation.

## What You Can Do

- **Scan from the feeder or the glass** to a multi-page PDF
- **Choose sides** on the page: Single-sided (default) or Double-sided
- **Set the file name and folder** before you hit Scan
- **Pick color, gray, or black and white**, plus dpi and page size
- **Check printer and feeder state** with `paperfeed --status`
- **Open the PDF** when the job finishes, or show it in Finder from the page

Tested on an **Epson ET-3950**. Other eSCL/AirScan printers work when you pass `--host`.

## Quick Start

```bash
git clone https://github.com/drewburchfield/paperfeed.git
cd paperfeed
./install.sh
```

That copies the program to `~/.local/lib/paperfeed` and symlinks `~/.local/bin/paperfeed`. Put `~/.local/bin` on your `PATH` if it is not already.

Point it at your printer once:

```bash
paperfeed --host PRINTER.local --status
mkdir -p ~/.config/paperfeed
echo PRINTER.local > ~/.config/paperfeed/host
```

`PRINTER.local` is the AirScan hostname from the printer (Bonjour / mDNS). You can also set `PAPERFEED_HOST`. `--host` wins when you pass it.

Load pages **face-up, top edge first** in the feeder (max 25 on the ET-3950).

```bash
paperfeed --status
paperfeed
```

The PDF lands in `~/Downloads/scan-YYYY-MM-DD-HHMMSS.pdf`.

Browser UI:

```bash
paperfeed ui
```

Opens `http://127.0.0.1:8787`. Set the file name on that page. Sides default to Single-sided.

From a checkout, without installing:

```bash
python3 bin/paperfeed --status
```

Remove it:

```bash
./install.sh uninstall
```

## Command Line

```bash
paperfeed                      # feeder, single-sided, color, 300 dpi, letter
paperfeed --status             # printer and feeder state
paperfeed --duplex             # double-sided
paperfeed --glass              # flatbed
paperfeed --color gray
paperfeed --dpi 200
paperfeed --size legal
paperfeed -o ~/Desktop/form.pdf
paperfeed --host PRINTER.local
paperfeed --open               # open the PDF when it finishes
paperfeed ui
paperfeed ui --port 9000
paperfeed ui --no-browser
```

`--simplex` is accepted and does nothing. Single-sided is already the default.

## Defaults

| Setting | Default |
|---|---|
| Source | Feeder |
| Sides | Single-sided |
| Color | color |
| DPI | 300 |
| Size | letter |
| File name | `scan-YYYY-MM-DD-HHMMSS.pdf` |
| Folder | `~/Downloads` |
| Open when done | Off |
| Host | `--host`, else `PAPERFEED_HOST`, else `~/.config/paperfeed/host` |

If the output path already exists, `paperfeed` refuses and you pick another name.

## How It Works

The printer advertises AirScan/eSCL. `paperfeed` POSTs a ScanJobs document to `https://<printer>/eSCL`, reads every returned document, and hangs up. Most AirScan printers send one multi-page PDF. If the printer sends one PDF per page, extra files are written as `name-p2.pdf`, `name-p3.pdf`, and so on. Device TLS certificates are not verified, which is normal for these printers.

`paperfeed ui` binds `127.0.0.1` only.

## Compatibility

- macOS (Apple Silicon and Intel). `open` and Show in Finder are macOS.
- Python 3
- eSCL/AirScan printers. Tested: Epson ET-3950

Linux and Windows are untested. The eSCL client itself is plain Python. The UI's Open / Show in Finder buttons call macOS `open`.

## Troubleshooting

| Message | What to do |
|---|---|
| No scanner host | Pass `--host PRINTER.local`, set `PAPERFEED_HOST`, or write the hostname to `~/.config/paperfeed/host`. |
| Feeder is empty | Load pages face-up, top edge first, then run `paperfeed` again. |
| feeder jam / cover open / too many pages | Clear the ADF, then `paperfeed --status`. |
| Could not reach the scanner | Printer off, or this Mac is on another Wi-Fi. Check `--host`. |
| 1200 dpi is only available on the glass | Use `--glass` or a lower `--dpi`. |
| That file already exists | Change `-o` or the file name on the page. |
| Port 8787 is in use | `paperfeed ui --port 9000` |

The UI does not switch to the glass when the feeder is empty.

## Agent skill

Harnesses load `skill/scan/SKILL.md`. Install it with [skills.sh](https://skills.sh):

```bash
npx skills add git@github.com:drewburchfield/paperfeed.git --skill scan -g \
  -a claude-code -a codex -a opencode -a antigravity -y
```

## Development

```bash
git clone https://github.com/drewburchfield/paperfeed.git
cd paperfeed
python3 -m unittest discover -s tests -v
```

Tests use canned ScannerStatus XML. They do not need a printer.

Contributions welcome. Please keep the test suite green before opening a PR.

## Support

- [GitHub Issues](https://github.com/drewburchfield/paperfeed/issues)

## License

MIT License - see [LICENSE](LICENSE) for details.
