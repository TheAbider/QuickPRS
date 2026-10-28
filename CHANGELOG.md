# Changelog

All notable changes to QuickPRS will be documented in this file.

## [1.1.0] - 2026-10-27

### Fixed
- **Edits broke the file structure RPM reads.** A .PRS file is an MFC archive: every class and object is numbered as it is written, and every list starts with its count. Adding or removing a talkgroup, channel, set or system left every later class tag and the list counts stale, and MFC's loader, which RPM uses, rejects tags that name the wrong class. QuickPRS now reads a personality into a tree that keeps every byte and writes it back with tags and counts recomputed. All 36 RPM-saved test files re-serialize byte for byte. See [docs/prs-format.md](docs/prs-format.md).
- Saving refuses an edit that breaks a file's archive structure, and `validate` reports stale tags and counts; `repair` fixes files saved by QuickPRS 1.0.x
- `create` built a file whose system count, list counts and WAN object did not match its contents
- Conventional sets after a padded gap were missing from the GUI, CSV export and rebuilds (#1)
- A talkgroup ID of 65535 cut its talkgroup list short
- 800 MHz IDEN tables started at 851.00625 MHz in 12.5 kHz steps, which never lands on an 800 MHz channel; they now start at 851.0125 MHz, and TDMA templates use 12.5 kHz as RPM-saved files do
- Trunk channel TX and RX were reversed in the README, example INIs and CSV templates (RPM stores TX on the uplink, 806 MHz, and RX on the downlink, 851 MHz); validation now warns when a trunk set looks swapped
- `import-paste` paired every pasted frequency with itself
- `import-rr` and `auto-setup` sent the API key as the account password, so they could not log in
- 2 m repeater offsets were reversed (146.61-146.97 MHz outputs take -600 kHz, 147.00-147.39 MHz take +600 kHz)
- Interop template: VTAC11-14 were on the wrong frequencies, UTAC44 does not exist, the 800 MHz channels were on their pre-rebanding frequencies, repeater channels were simplex, and the 700 MHz P25 channels were analog. It now follows the NIFOG: 23 channels with repeater pairs and direct channels, all 800 MHz channels wide (20 kHz, 47 CFR 90.209), 700 MHz left to a P25 conventional set
- The built-in P25 system list's IDs were never verified (the FCC does not publish System IDs or WACNs). PSERN is corrected to 939 and marked verified; the CLI and GUI warn before an unverified system is added
- `create` silently replaced an existing file (it now needs `--force` and keeps a `.bak`), and `import-json` overwrote the .PRS its JSON came from
- `cleanup` reported every trunk and talkgroup set as unused
- Backups of `radio_v2.PRS` were listed, restored and pruned as backups of `radio.PRS`
- `fleet`: unit names could write outside the output folder, duplicate names overwrote each other, short CSV rows crashed, and unit IDs were not checked against 24 bits
- `build` ignored the `[options]` section. Options are now checked like `set-option` (an unknown attribute or a value the radio does not allow is an error), and the lists `export-config` writes for programmable buttons, microphones and the short menu build back into those elements
- The wizard saved the time zone to an attribute the radio does not have; it now sets the radio's time zone and asks again for one RPM does not list
- `clone-personality --name/--unit-id` changed nothing the radio uses
- `set-option` accepted misspelt attributes and values a field does not allow, and wrote nested settings on the parent element; the default options XML is now RPM's own; presets and profiles no longer set attributes the XG-100P does not have
- GUI: crashed on start; the Import Wizard failed every non-talkgroup import; the System Wizard reported failure on success and could add a system twice; undo history carried over to the next file; opening a recent file did not ask about unsaved changes; Delete, F2 and undo acted on the tree while typing; multi-select edits touched talkgroups that were not selected; Health Check crashed; dropped paths were not read as Unicode
- `search` skipped unreadable files without saying so; listings print 6.25 kHz channels with 5 decimals

### Added
- `quickprs radio`: groundwork for reading the radio over Bluetooth. The XG-100P uses Bluetooth Classic (serial port profile), which RPM programs over like the USB cable. `scan` finds paired radios and their COM ports, `probe` listens, `relay` sits between RPM and the radio and logs both directions, and `analyze` summarises a capture and extracts any personality in it. None of them sends bytes of its own to the radio. See [docs/bluetooth.md](docs/bluetooth.md).
- P25 conventional sets: CSV export, CSV import and creation
- `quickprs import-csv`, which detects each CSV's type, so `export-csv` output imports directly
- RadioReference login from `--password` or the `QUICKPRS_RR_*` environment variables, with a hidden password prompt
- `radio` optional dependencies (pyserial, bleak); the standalone EXE includes pyserial

### Changed
- CLI writes back up an existing output file, not only the input
- The EXE build collects every quickprs module instead of a hand-kept list

### Also in this release (prepared as 1.0.3, never released)

#### Added
- README: Dedicated RadioReference integration section with auto-setup, paste import, and GUI wizard documentation
- README: Updated Quick Start to lead with RadioReference one-command workflow

#### Fixed
- Section replacement functions now validate section indices before writing, preventing silent data corruption if expected sections are missing
- Added empty set guards to prevent IndexError when trunk, group, or conv sets are unexpectedly empty
- NOAA weather channels now correctly set as receive-only (TX disabled)
- Interop template docstring corrected to document 156.7 Hz PL tone usage and accurate frequency ranges
- `make_conv_channel()` and `make_conv_set()` now support `tx` and `scan` flags from template data
- Updated test count to 5,300+ in README

## [1.0.2] - 2026-03-15

### Added
- Configuration health check with 15+ best practice checks (`quickprs health`)
- Smart improvement suggestions with CLI commands (`quickprs suggest`)
- Frequency spectrum map visualization (`quickprs freq-map`)
- Fleet consistency checker for comparing radio configs (`quickprs fleet-check`)
- Configuration snapshots for change tracking (`quickprs snapshot`)
- Department-specific profiles: fire, law enforcement, EMS, search & rescue
- Export PRS to editable INI config (`quickprs export-config`)
- File watcher with auto-validation (`quickprs watch`)
- CLI cheat sheet (`quickprs cheat-sheet`)
- 4,000+ automated tests

### Fixed
- Duplicate cmd_rename/cmd_sort definitions causing backup skips
- Unicode crash in write_lps and build_personality_section
- run.py only routing 10 of 45 CLI commands
- 8 missing hidden imports in build.py

### Improved
- Test suite optimized with session-scoped PRS parsing cache

## [1.0.1] - 2026-03-15

### Added
- Interactive CLI wizard (`quickprs wizard`)
- CSV template generator (`quickprs template-csv`)
- Auto-backup system with timestamped copies (`quickprs backup`)
- Duplicate detection and cleanup (`quickprs cleanup`)
- Frequency/talkgroup search across files (`quickprs search`)
- Import wizard in GUI (File > Import Wizard)
- Batch rename with regex (`quickprs rename`)
- Channel sorting (`quickprs sort`)
- Personality change report (`quickprs diff-report`)
- GitHub issue/PR templates

### Improved
- All validation messages now include actionable guidance
- CLI help text includes usage examples for all commands
- CLI help organized into categories for easier navigation
- Tests skip gracefully when PRS test data not available (CI fix)

## [1.0.0] - 2026-03-14

### Added
- Complete PRS binary format reverse engineering (49 section types, 100% byte coverage)
- CLI with 35+ commands for full radio programming workflow
- GUI with interactive tree view, inline editing, drag-and-drop reordering
- Create PRS files from scratch via `create` command or INI config files
- Import from RadioReference (SOAP API and paste), CHIRP, Uniden, SDRTrunk formats
- Export to CHIRP, Uniden, SDRTrunk, DSD+, Markdown, JSON, CSV formats
- Built-in channel templates: MURS, GMRS, FRS, Marine VHF, NOAA Weather, Interop, Public Safety
- Built-in P25 system database with 30 major US metro systems
- Fleet batch processing for generating radio-specific personalities
- Radio option editor (GPS, display, audio, bluetooth, programmable buttons)
- P25 encryption key management and NAC editing
- File comparison with visual side-by-side diff viewer
- Hex viewer for raw section inspection
- Zone planner with auto and manual strategies
- Capacity estimator and statistics dashboard
- HTML report and printable summary card generation
- File repair and data salvage for damaged PRS files
- Frequency reference tools (CTCSS tones, DCS codes, repeater offsets)
- Tab completion for bash and PowerShell
- Multi-level undo/redo (20 levels)
- Comprehensive validation against XG-100P hardware limits
- 3,265+ automated tests
