# Changelog

All notable changes to QuickPRS will be documented in this file.

## [1.2.0] - 2026-10-28

### Fixed
- Templates: FRS, GMRS 8-14, MURS 1-3 and the public safety simplex channels were 25 kHz channels where the FCC allows 12.5 kHz or less (47 CFR 95.573, 95.1773, 95.2773, 90.209(b)(5)); they are narrowband now. Marine channel 70 carries DSC only (no voice) and is no longer in the marine template
- CHIRP export lost the TX tone of a channel whose TX and RX tones differ, turned an RX-only tone into TX and RX, ignored the RX side of DCS, always wrote FM and dropped scan-off and TX-off. It now uses CHIRP's Cross mode, NFM, Skip and Duplex off, and CHIRP import reads them all back
- The Uniden export gave the scanner the tone the radio transmits; it now gives the one the radio expects on the receive frequency
- RadioReference conventional channels: DPL codes and P25 NACs were read as CTCSS tones, and every channel went into an analog set as wide FM. FMN channels are now narrowband, P25 channels go to a P25 conventional set with their NAC, and DMR, NXDN, AM and other modes are left out and counted
- `compare` said "Files are identical" (exit code 0) when a channel's frequency, tone, name or flags, a talkgroup, a trunk TX frequency, an IDEN element, a P25 conventional channel, a system setting or a radio option had changed. It now names the changed items and their fields, and reports anything else that differs
- JSON import duplicated the default conventional set, lost P25 conventional sets and systems, the radio options, system IDs and every field without a readable key, and moved IDEN elements to other slots. An unedited export now imports to the same bytes (all 36 RPM-saved test files do)
- `merge` named every system after the first one of its class, rebuilt P25 systems from defaults (system ID 0, no home unit ID, a guessed IDEN set), left P25 conventional systems out and could add a second set under a name already in use. It now copies systems and the sets they use exactly and reports name clashes
- Adding a set under a name already used by a set of the same type is refused: systems find their sets by name
- `wizard --modify FILE` ignored FILE and built a new personality; it now adds to FILE. The wizard replaced an existing output file without asking or keeping a backup
- Renaming a set (`edit --rename-set`, the GUI) left the systems that use it naming a set that no longer existed; their references now follow the rename, as does a P25 conventional set's talkgroup set reference. A name already in use is refused
- The personality name and user name are stored twice in a file (RPM writes both copies the same); `edit --name/--author`, `fleet` and `clone-personality --name` changed only one
- `export-config` dropped narrowband, TX-off and scan-off from conventional channels (PAWSOVERMAWS's FURRY NB set came back from `build` as 25 kHz channels) and wrote `template = X` for any set with a template's frequencies, so a MURS set programmed wide would build narrowband
- The CSV files `template-csv` writes did not work: inject and fleet read their `#` comment lines as data
- The RadioReference cache dropped conventional channels, categories (the GUI's category filter) and color codes
- Validation checked frequencies against 30-960 MHz, so 220 or 900 MHz passed; it now checks the XG-100P's bands (136-174, 380-520, 762-870 MHz). It no longer warns about a trunk set and talkgroup set sharing a name, or about PTCT, RPM's default 2-position switch function: RPM writes both
- New analog channels get the values RPM writes in every channel it creates (85 in both tone address fields, the tone mode flag set); QuickPRS wrote 0, 0 and off
- GUI: with the search filtering rows, editing or moving a trunk channel changed another channel; Export to CSV on a P25 conventional set wrote an empty file; the NAC editor and IDEN set delete spliced raw sections (IDEN delete left a stale count); the RadioReference fetch thread called Tk; deleting a set now names the systems that use it

### Added
- `edit --rename-set` takes `iden` and `p25conv` sets
- Config file channel lines take an optional seventh field of flags: `nb`, `rxonly`, `noscan`
- `merge` merges P25 conventional systems

### Changed
- JSON exports carry every field of each set, channel and talkgroup (bytes as hex) and an `archive` block with the rest of the file; IDEN elements carry their slot (`index`)
- `compare` matches items by key and names the fields that changed

## [1.1.0] - 2026-10-28

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
- The standalone EXE is a windowed program, so its commands printed nothing in a console; releases now include `QuickPRS-cli.exe`, a console build for the command line
- Classic Windows console windows showed color codes as text (`←[1m`); QuickPRS now turns on their handling, leaves colors out where it cannot, and honors `NO_COLOR`

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
