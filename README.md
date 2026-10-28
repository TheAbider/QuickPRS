# QuickPRS

Generate and edit Harris XG-100P personality (.PRS) files without Harris RPM software.

> **WARNING: USE AT YOUR OWN RISK.** This software modifies radio personality files. Incorrectly configured personality files **may brick your radio** or cause it to malfunction. The authors are not responsible for any damage to radios, equipment, or property. Always validate files before loading onto a radio. Keep backups of working personalities. **This tool is not affiliated with or endorsed by L3Harris Technologies.**

> **STATUS: In Development.** This tool is under active development. While the binary format has been extensively reverse-engineered and tested against known-good RPM files, it has NOT been exhaustively tested on all XG-100P hardware revisions and firmware versions. Test on non-critical equipment first.

> **IMPORTANT: This tool does NOT load mission plans onto radios.** QuickPRS generates and edits .PRS personality files. To actually load a personality onto an XG-100P radio, you still need Harris RPM software (for now). The `quickprs radio` commands are groundwork for reading radios directly over Bluetooth: they find the radio and record RPM's sessions with it, and never send bytes of their own (see [docs/bluetooth.md](docs/bluetooth.md)).

## RadioReference Integration

QuickPRS can pull P25 trunked system data directly from [RadioReference.com](https://www.radioreference.com/) and automatically build a complete radio personality — talkgroups, frequencies, IDEN tables, control channels, and WAN config — in a single command.

### One-Click Auto Setup (API)

With a RadioReference premium account and API key:

```bash
# Fetch a P25 system and build the entire personality automatically
quickprs create radio.PRS --name "PATROL"
quickprs auto-setup radio.PRS --sid 8155 --username YOUR_USER --apikey YOUR_KEY
quickprs validate radio.PRS
```

`auto-setup` and `import-rr` log in with your RadioReference username and password plus the API key. The password is asked for when you run them (or comes from `--password` or `QUICKPRS_RR_PASSWORD`; `QUICKPRS_RR_USER` and `QUICKPRS_RR_APIKEY` work for the other two).

This single `auto-setup` command:
1. Fetches the full system from RadioReference (talkgroups, sites, frequencies)
2. Creates the trunk frequency set with all site frequencies
3. Creates the talkgroup set with smart short name generation
4. Auto-detects and creates IDEN frequency parameters (base freq, spacing, bandwidth, FDMA/TDMA)
5. Builds Enhanced Control Channel (ECC) entries from site control channels
6. Configures the P25 trunked system with WACN, SysID, and WAN settings
7. Runs validation to catch any hardware limit issues

### Import by Pasting from the Website

No API key? Just copy talkgroup/frequency tables from RadioReference and paste them in:

```bash
# Paste the talkgroup table, the site/frequency table, or both
quickprs import-paste radio.PRS --name PSERN --sysid 939 --wacn 781824 \
    --tgs-file tgs.txt --freqs-file freqs.txt
```

### GUI Import Wizard

The GUI includes a dedicated RadioReference import wizard (File > Import Wizard) that walks you through system selection, talkgroup filtering by category and service tag, and previews everything before injection.

### What Gets Imported

| Data | Source | Details |
|------|--------|---------|
| Talkgroups | Categories + service tags | ID, short name, description, mode, encryption status |
| Frequencies | All sites | TX/RX pairs with LCN mapping |
| IDEN Parameters | Channel identifiers | Base freq, spacing, bandwidth, FDMA/TDMA auto-detected |
| Control Channels | Site details | Enhanced CC entries with NAC and RFSS |
| System Config | System metadata | WACN, SysID, system type, WAN configuration |

## Features

- Writes personalities the way RPM does: the .PRS is an MFC archive, and every save rebuilds its class tags and list counts ([format notes](docs/prs-format.md))
- Refuses to save an edit that breaks the archive structure; `repair` fixes files saved by QuickPRS 1.0.x
- Create PRS files from scratch or INI config files
- **RadioReference integration** — auto-setup P25 systems via SOAP API, web scraping, or paste
- Import from scanner formats (CHIRP, Uniden Sentinel, SDRTrunk)
- P25 conventional channel sets (CSV export and import)
- 60+ CLI commands for scripting and batch processing
- Full GUI with tree view, inline editing, drag-and-drop, and RadioReference import wizard
- Built-in channel templates (MURS, GMRS, FRS, Marine, NOAA, Interop, Public Safety)
- Built-in list of 28 US P25 systems as a starting point (IDs unverified except where marked: confirm them before programming)
- Bluetooth groundwork: find a paired radio and record RPM's sessions with it (`quickprs radio`)
- JSON export/import for human-editable radio configs
- Export to CHIRP CSV, Uniden CSV, SDRTrunk, DSD+, Markdown, INI
- Merge, clone, and compare PRS files
- Radio option editing (GPS, display, audio, bluetooth, buttons, etc.)
- P25 encryption key management and NAC editing
- Fleet batch processing (same config to multiple radios with unique unit IDs)
- Fleet consistency checking across multiple radios
- Zone planning, capacity estimation, and statistics
- Configuration health check with best practice suggestions
- Department-specific profiles (fire, law enforcement, EMS, search & rescue)
- Frequency spectrum map visualization
- Configuration snapshots for change tracking
- File watcher with auto-validation
- Comprehensive validation against XG-100P hardware limits
- File repair and data salvage for damaged PRS files
- Lossless binary roundtrip (parse and rewrite produces byte-identical output)
- 5,400+ automated tests

## Quick Start

### One-command P25 setup from RadioReference:

```bash
quickprs create radio.PRS --name "PATROL"
quickprs auto-setup radio.PRS --sid 8155 --username USER --apikey KEY
quickprs inject radio.PRS conv --template interop
quickprs validate radio.PRS
```

### Build from an INI config file:

```bash
quickprs build patrol.ini -o radio.PRS
quickprs set-option radio.PRS gps.gpsMode ON
quickprs validate radio.PRS
```

### Build step by step:

```bash
quickprs create radio.PRS --name "PATROL"
quickprs inject radio.PRS p25 --name PSERN --sysid 939 --wacn 781824 --freqs-csv freqs.csv --tgs-csv tgs.csv
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
- `pyserial` — serial and Bluetooth ports for `quickprs radio`
- `bleak` — BLE device scan (`quickprs radio scan --ble`)

## CLI Commands

| Command | Description |
|---------|-------------|
| `create` | Create a new blank PRS file |
| `build` | Build a complete PRS from an INI config file |
| `wizard` | Interactive guided personality setup |
| `fleet` | Batch-build for a fleet of radios with unique unit IDs |
| `inject p25` | Add a P25 trunked system with frequencies and talkgroups |
| `inject conv` | Add conventional channels (from CSV or built-in template) |
| `inject talkgroups` | Add talkgroups to an existing group set |
| `clone` | Clone a specific system from one PRS file to another |
| `clone-personality` | Create a modified copy of a personality |
| `merge` | Merge systems and channels from one PRS into another |
| `remove` | Remove a system, trunk set, group set, or conv set |
| `edit` | Edit personality metadata or rename sets |
| `rename` | Batch rename channels/talkgroups with regex patterns |
| `sort` | Sort channels or talkgroups by name, frequency, or ID |
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
| `import-csv` | Import talkgroup, trunk, conventional and P25 conventional sets from CSV (the `export-csv` format) |
| `convert` | Convert between PRS, JSON, INI, CSV, CHIRP and Markdown |
| `preset` | Apply named option presets (GPS, covert, quiet, etc.) |
| `favorites` | Bookmark systems, talkgroups, channels and templates |
| `systems` | Browse/search/add from built-in P25 system database |
| `template-csv` | Generate blank CSV/INI templates for data entry |
| `validate` | Validate PRS file against XG-100P hardware limits |
| `capacity` | Show memory usage and remaining capacity |
| `repair` | Fix corrupted PRS files or salvage data |
| `info` | Print personality summary (`--detail` for full breakdown) |
| `stats` | Show channel statistics and frequency band analysis |
| `compare` | Compare two PRS files (`--detail` for semantic diff) |
| `diff-report` | Generate personality change report between two files |
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
| `cleanup` | Find and fix duplicates and unused sets |
| `search` | Search across PRS files for frequencies, talkgroups, or names |
| `backup` | Create, list, or restore timestamped backups |
| `health` | Configuration health check with best practice suggestions |
| `suggest` | Smart improvement suggestions with ready-to-run commands |
| `freq-map` | Frequency spectrum map visualization |
| `fleet-check` | Compare configs across multiple radios for consistency |
| `snapshot` | Save/compare configuration snapshots for change tracking |
| `profiles` | Department-specific profiles (fire, law, EMS, SAR) |
| `export-config` | Export PRS to editable INI config file |
| `watch` | File watcher with auto-validation on change |
| `cheat-sheet` | Quick reference of common CLI workflows |
| `radio` | Find a paired radio, listen to it, or log RPM talking to it ([docs](docs/bluetooth.md)) |
| `tutorial` | Interactive step-by-step CLI tutorial |
| `demo` | Build an example patrol radio from scratch, non-interactively |
| `about` | Project info and statistics |

## Config File Format

INI-style config files let you define an entire radio personality in one place:

```ini
[personality]
name = PATROL.PRS
author = Dispatch

; Example values: use your system's real IDs and frequencies.
[system.COUNTY]
type = p25_trunked
long_name = COUNTY P25
system_id = 100
wacn = 781824

[system.COUNTY.frequencies]
; tx_freq (radio transmit = site uplink), rx_freq (site downlink)
1 = 806.0125,851.0125
2 = 806.5125,851.5125
3 = 807.0125,852.0125

[system.COUNTY.talkgroups]
; id, short_name, long_name
1 = 1000,PD DISP,Police Dispatch
2 = 1001,PD TAC1,Police Tactical 1
3 = 2000,FD DISP,Fire Dispatch

[channels.MURS]
template = murs

[channels.NOAA]
template = noaa

[channels.INTEROP]
template = interop

[channels.LOCAL]
; short_name, tx_freq, rx_freq, tx_tone, rx_tone, long_name
1 = RPT 147,147.600,147.000,100.0,100.0,147.00+ Repeater
2 = SIMPLEX,146.520,146.520,,,2m Calling

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
| `interop` | 23 | National interoperability (NIFOG): VHF, UHF and 800 MHz calling and tactical channels |
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
- The built-in P25 system list is a starting point only: its System IDs and WACNs are unverified unless marked, and a wrong one keeps a radio off the system

## License

MIT
