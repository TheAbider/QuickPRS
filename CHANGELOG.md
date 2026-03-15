# Changelog

All notable changes to QuickPRS will be documented in this file.

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
