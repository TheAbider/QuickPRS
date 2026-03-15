# Changelog

All notable changes to QuickPRS will be documented in this file.

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
