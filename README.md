# QuickPRS

Generate and edit Harris XG-100P personality (.PRS) files without Harris RPM software.

> **WARNING: USE AT YOUR OWN RISK.** This software modifies radio personality files. Incorrectly configured personality files **may brick your radio** or cause it to malfunction. The authors are not responsible for any damage to radios, equipment, or property. Always validate files before loading onto a radio. Keep backups of working personalities. **This tool is not affiliated with or endorsed by L3Harris Technologies.**

> **STATUS: In Development.** This tool is under active development. While the binary format has been extensively reverse-engineered and tested against known-good RPM files, it has NOT been exhaustively tested on all XG-100P hardware revisions and firmware versions. Test on non-critical equipment first.

> **IMPORTANT: This tool does NOT load mission plans onto radios.** QuickPRS generates and edits .PRS personality files. To actually load a personality onto an XG-100P radio, you still need Harris RPM software (for now). QuickPRS replaces the personality *creation and editing* workflow, not the radio flashing process.

## Features

- 100% binary format decoded (49 section types, 27 option sections, 514+ fields)
- Create PRS files from scratch or INI config files
- Import from RadioReference (SOAP API or paste from website)
- Import from scanner formats (CHIRP, Uniden Sentinel, SDRTrunk)
- 30+ CLI commands for scripting and batch processing
- Full GUI with tree view, inline editing, drag-and-drop, RadioReference import
- Built-in channel templates (MURS, GMRS, FRS, Marine, NOAA, Interop, Public Safety)
- Built-in P25 system database (30 major US systems)
- JSON export/import for human-editable radio configs
- Export to CHIRP CSV, Uniden CSV, SDRTrunk, DSD+, Markdown
- Merge, clone, and compare PRS files
- Radio option editing (GPS, display, audio, bluetooth, buttons, etc.)
- P25 encryption key management and NAC editing
- Fleet batch processing (same config to multiple radios with unique unit IDs)
- Zone planning, capacity estimation, and statistics
- Comprehensive validation against XG-100P hardware limits
- File repair and data salvage for damaged PRS files
- Lossless binary roundtrip (parse and rewrite produces byte-identical output)

## Quick Start

### Build a radio config from an INI file:

```bash
quickprs build patrol.ini -o radio.PRS
quickprs set-option radio.PRS gps.gpsMode ON
quickprs validate radio.PRS
```

### Or use individual commands:

```bash
quickprs create radio.PRS --name "PATROL"
quickprs inject radio.PRS p25 --name PSERN --sysid 892 --freqs-csv freqs.csv --tgs-csv tgs.csv
quickprs inject radio.PRS conv --template murs
quickprs inject radio.PRS conv --template noaa
quickprs inject radio.PRS conv --template interop
quickprs validate radio.PRS
```

### Launch the GUI:

```bash
python -m quickprs
```

## Installation

```bash
pip install -r requirements.txt
python -m quickprs          # Launch GUI
python -m quickprs --help   # CLI help
```

Or use the standalone EXE from [Releases](../../releases) (no Python required).

### Optional dependencies:

- `sv-ttk` — Modern theme for the GUI
- `darkdetect` — Auto dark mode detection
- `windnd` — Drag-and-drop file support (Windows)
- `zeep` — RadioReference SOAP API access (requires premium subscription)

## CLI Commands

| Command | Description |
|---------|-------------|
| `create` | Create a new blank PRS file |
| `build` | Build a complete PRS from an INI config file |
| `fleet` | Batch-build for a fleet of radios with unique unit IDs |
| `inject p25` | Add a P25 trunked system with frequencies and talkgroups |
| `inject conv` | Add conventional channels (from CSV or built-in template) |
| `inject talkgroups` | Add talkgroups to an existing group set |
| `clone` | Clone a specific system from one PRS file to another |
| `clone-personality` | Create a modified copy of a personality |
| `merge` | Merge systems and channels from one PRS into another |
| `remove` | Remove a system, trunk set, group set, or conv set |
| `edit` | Edit personality metadata or rename sets |
| `set-option` | Get/set radio options (GPS, audio, bluetooth, display, etc.) |
| `encrypt` | Set/clear P25 encryption on talkgroups |
| `set-nac` | Set Network Access Code on P25 conv channels |
| `bulk-edit` | Batch-modify talkgroup or channel settings |
| `renumber` | Auto-number channels sequentially |
| `auto-name` | Auto-generate talkgroup short names from long names |
| `auto-setup` | One-click P25 system setup from RadioReference |
| `import-rr` | Import a P25 system from RadioReference API |
| `import-paste` | Import from pasted RadioReference text |
| `import-scanner` | Import from CHIRP, Uniden, or SDRTrunk CSV |
| `import-json` | Create a PRS from a JSON file |
| `systems` | Browse/search/add from built-in P25 system database |
| `validate` | Validate PRS file against XG-100P hardware limits |
| `capacity` | Show memory usage and remaining capacity |
| `repair` | Fix corrupted PRS files or salvage data |
| `info` | Print personality summary (`--detail` for full breakdown) |
| `stats` | Show channel statistics and frequency band analysis |
| `compare` | Compare two PRS files (`--detail` for semantic diff) |
| `export` | Export to CHIRP, Uniden, SDRTrunk, DSD+, or Markdown format |
| `export-csv` | Export all data to CSV files |
| `export-json` | Export PRS to structured JSON |
| `report` | Generate full HTML report of radio configuration |
| `card` | Generate printable summary reference card |
| `zones` | Generate and export zone plans |
| `freq-tools` | Frequency reference (repeater offsets, CTCSS tones, channel lookup) |
| `list` | Quick-list systems, talkgroups, channels, frequencies, or options |
| `dump` | Dump raw section structure and hex data |
| `diff-options` | Compare radio options between two PRS files |
| `iden-templates` | List standard IDEN frequency templates |

## Config File Format

INI-style config files let you define an entire radio personality in one place:

```ini
[personality]
name = PATROL.PRS
author = Dispatch

[system.PSERN]
type = p25_trunked
long_name = PSERN SEATTLE
system_id = 892
wacn = 781824

[system.PSERN.frequencies]
851.0125,806.0125
851.5125,806.5125
852.0125,807.0125

[system.PSERN.talkgroups]
1000,PD DISP,Police Dispatch
1001,PD TAC1,Police Tactical 1
2000,FD DISP,Fire Dispatch

[channels.MURS]
template = murs

[channels.NOAA]
template = noaa

[channels.INTEROP]
template = interop

[channels.LOCAL]
; short_name, tx_freq, rx_freq, tx_tone, rx_tone, long_name
RPT IN,147.000,147.600,100.0,100.0,Repeater Input
RPT OUT,147.600,147.600,,,Repeater Output
SIMPLEX,146.520,146.520,,,2m Calling

[options]
gps.gpsMode = ON
bluetooth.btMode = OFF
misc.password = 1234
```

Build with: `quickprs build patrol.ini -o patrol.PRS`

## Built-in Templates

| Template | Channels | Description |
|----------|----------|-------------|
| `murs` | 5 | Multi-Use Radio Service (151-154 MHz) |
| `gmrs` | 22 | General Mobile Radio Service (462-467 MHz) |
| `frs` | 22 | Family Radio Service (462-467 MHz) |
| `marine` | 15 | Marine VHF (156-157 MHz) |
| `noaa` / `weather` | 7 | NOAA Weather Radio (162 MHz) |
| `interop` | 20 | National Interoperability (NPSPAC) |
| `public_safety` | 10 | Public Safety simplex frequencies |

Usage: `quickprs inject file.PRS conv --template murs`

## Testing

```bash
python -m pytest tests/ -q
```

Note: Test PRS data files are not included in this repository. Tests that require `.PRS` files will skip gracefully if the test data directory is empty.

## Disclaimer

- This software is provided AS-IS with NO WARRANTY of any kind
- Incorrectly configured personality files may damage or disable your radio
- Always test on non-critical equipment before deploying to field radios
- Always keep backups of known-working personality files
- This tool is an independent project and is NOT affiliated with, endorsed by, or supported by L3Harris Technologies, Harris Corporation, or any radio manufacturer
- XG-100P, RPM, and related trademarks belong to their respective owners
- Users are responsible for ensuring their radio configurations comply with all applicable FCC regulations and local laws
- The P25 system database contains publicly available information from FCC records

## License

MIT
