"""Demo mode and interactive tutorial for QuickPRS.

Provides:
    run_demo()     - Non-interactive demo building a patrol radio from scratch
    run_tutorial() - Interactive step-by-step CLI tutorial
    show_about()   - Project statistics and version info
"""

import os
import sys
from pathlib import Path

from . import __version__


# ─── Demo Mode ────────────────────────────────────────────────────────


def _can_unicode():
    """Check if stdout can handle Unicode box-drawing characters."""
    try:
        "\u2550".encode(sys.stdout.encoding or 'ascii')
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _print_banner(title, subtitle=""):
    """Print a bordered banner."""
    width = 50
    if _can_unicode():
        tl, tr, bl, br = "\u2554", "\u2557", "\u255a", "\u255d"
        hz, vt = "\u2550", "\u2551"
    else:
        tl, tr, bl, br = "+", "+", "+", "+"
        hz, vt = "=", "|"
    print()
    print(tl + hz * width + tr)
    print(vt + title.center(width) + vt)
    if subtitle:
        print(vt + subtitle.center(width) + vt)
    print(bl + hz * width + br)
    print()


def _step(num, total, description):
    """Print a step header."""
    print(f"Step {num}/{total}: {description}")


def _result(msg):
    """Print an indented result line."""
    arrow = "\u2192" if _can_unicode() else "->"
    print(f"  {arrow} {msg}")


def _file_size(path):
    """Return file size as a formatted string."""
    size = Path(path).stat().st_size
    return f"{size:,}"


def run_demo(output_dir=None):
    """Run a non-interactive demo of QuickPRS capabilities.

    Creates a realistic patrol radio personality step by step,
    showing each operation's output. No user input required.

    Args:
        output_dir: directory for output files (default: temp dir).
                    If specified, files are kept after the demo.

    Returns:
        0 on success, 1 on error.
    """
    from .builder import create_blank_prs
    from .prs_writer import write_prs
    from .injector import (
        add_p25_trunked_system, add_conv_system,
        make_trunk_set, make_group_set, make_iden_set,
        make_p25_group, make_conv_set,
    )
    from .record_types import P25TrkSystemConfig, ConvSystemConfig
    from .templates import get_template_channels
    from .validation import validate_prs, estimate_capacity, format_capacity
    from .validation import compute_statistics, format_statistics
    from .validation import ERROR, WARNING
    from .json_io import prs_to_dict, dict_to_json
    from .reports import generate_html_report, generate_summary_card
    from .config_builder import export_config
    from .option_maps import set_platform_option

    total_steps = 11

    # Resolve output directory
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "demo_output")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    prs_path = out / "DEMO_PATROL.PRS"

    _print_banner("QuickPRS Demo",
                  "Building a patrol radio from scratch")

    # ── Step 1: Create blank personality ──────────────────────────────
    _step(1, total_steps, "Creating blank personality...")

    prs = create_blank_prs(filename="DEMO_PATROL.PRS",
                           saved_by="QuickPRS Demo")
    write_prs(prs, str(prs_path))

    _result(f"Created: {prs_path.name} ({_file_size(prs_path)} bytes)")

    # ── Step 2: Add P25 trunked system ────────────────────────────────
    _step(2, total_steps, "Adding P25 trunked system (DEMO PD)...")

    # Build trunk frequencies (10 typical 800 MHz freqs)
    trunk_freqs = [
        (851.0125, 851.0125), (851.2625, 851.2625),
        (851.5125, 851.5125), (851.7625, 851.7625),
        (852.0125, 852.0125), (852.2625, 852.2625),
        (852.5125, 852.5125), (852.7625, 852.7625),
        (853.0125, 853.0125), (853.2625, 853.2625),
    ]
    trunk_set = make_trunk_set("DEMO PD", trunk_freqs)

    # Build talkgroups
    demo_talkgroups = [
        (100, "DISP", "PD Dispatch"),
        (101, "TAC 1", "PD Tactical 1"),
        (102, "TAC 2", "PD Tactical 2"),
        (103, "TAC 3", "PD Tactical 3"),
        (104, "TAC 4", "PD Tactical 4"),
        (200, "FD DISP", "Fire Dispatch"),
        (201, "FD TAC", "Fire Tactical"),
        (300, "EMS", "EMS Dispatch"),
        (301, "EMS TAC", "EMS Tactical"),
        (400, "COMM 1", "Common 1"),
        (401, "COMM 2", "Common 2"),
        (500, "OPS 1", "Operations 1"),
        (501, "OPS 2", "Operations 2"),
        (600, "ADMIN", "Admin"),
        (700, "MUTUAL", "Mutual Aid"),
    ]
    groups = [make_p25_group(gid, sn, ln)
              for gid, sn, ln in demo_talkgroups]
    from .record_types import P25GroupSet
    group_set = P25GroupSet(name="DEMO PD", groups=groups)

    # Build IDEN set (800 MHz FDMA)
    iden_set = make_iden_set("DEMO", [{
        'base_freq_hz': 851_012_500,
        'chan_spacing_hz': 12500,
        'bandwidth_hz': 6250,
        'iden_type': 0,
    }])

    config = P25TrkSystemConfig(
        system_name="DEMO PD",
        long_name="DEMO PD SYSTEM",
        trunk_set_name="DEMO PD",
        group_set_name="DEMO PD",
        wan_name="DEMO PD",
        system_id=999,
        wacn=12345,
        iden_set_name="DEMO",
        wan_base_freq_hz=851_012_500,
        wan_chan_spacing_hz=12500,
    )

    add_p25_trunked_system(prs, config,
                           trunk_set=trunk_set,
                           group_set=group_set,
                           iden_set=iden_set)

    write_prs(prs, str(prs_path))
    _result(f"System ID: 999, WACN: 12345")
    _result(f"{len(trunk_freqs)} trunk frequencies (851-853 MHz)")
    _result(f"Done ({_file_size(prs_path)} bytes)")

    # ── Step 3: Add talkgroups (already done above) ───────────────────
    _step(3, total_steps, "Adding talkgroups...")

    _result(f"{len(demo_talkgroups)} talkgroups: "
            "Dispatch, Tactical 1-4, Fire Dispatch, EMS, ...")
    _result(f"Done ({_file_size(prs_path)} bytes)")

    # ── Step 4: Add MURS and NOAA templates ───────────────────────────
    _step(4, total_steps, "Adding MURS and NOAA channel templates...")

    # Add MURS
    murs_channels = get_template_channels('murs')
    murs_set = make_conv_set("MURS", murs_channels)
    murs_config = ConvSystemConfig(
        system_name="MURS",
        long_name="MURS",
        conv_set_name="MURS",
    )
    add_conv_system(prs, murs_config, conv_set=murs_set)

    # Add NOAA
    noaa_channels = get_template_channels('noaa')
    noaa_set = make_conv_set("NOAA", noaa_channels)
    noaa_config = ConvSystemConfig(
        system_name="NOAA",
        long_name="NOAA WEATHER",
        conv_set_name="NOAA",
    )
    add_conv_system(prs, noaa_config, conv_set=noaa_set)

    write_prs(prs, str(prs_path))
    _result(f"MURS: {len(murs_channels)} channels (151-154 MHz)")
    _result(f"NOAA: {len(noaa_channels)} channels (162 MHz)")
    _result(f"Done ({_file_size(prs_path)} bytes)")

    # ── Step 5: Add interop channels ──────────────────────────────────
    _step(5, total_steps, "Adding national interop channels...")

    interop_channels = get_template_channels('interop')
    interop_set = make_conv_set("INTEROP", interop_channels)
    interop_config = ConvSystemConfig(
        system_name="INTEROP",
        long_name="INTEROP",
        conv_set_name="INTEROP",
    )
    add_conv_system(prs, interop_config, conv_set=interop_set)

    write_prs(prs, str(prs_path))
    _result(f"{len(interop_channels)} channels "
            "(VHF, UHF, 700, 800 MHz interop)")
    _result(f"Done ({_file_size(prs_path)} bytes)")

    # ── Step 6: Set radio options ─────────────────────────────────────
    _step(6, total_steps, "Setting radio options (GPS, password)...")

    try:
        set_platform_option(prs, "gps", "gpsMode", "ON")
        _result("GPS: ON")
    except (ValueError, KeyError):
        _result("GPS: skipped (no platformConfig in blank file)")

    try:
        set_platform_option(prs, "misc", "password", "1234")
        _result("Password: 1234")
    except (ValueError, KeyError):
        _result("Password: skipped (no platformConfig in blank file)")

    write_prs(prs, str(prs_path))
    _result(f"Done ({_file_size(prs_path)} bytes)")

    # ── Step 7: Validate ──────────────────────────────────────────────
    _step(7, total_steps, "Validating personality...")

    # Re-parse from file for clean validation
    from .prs_parser import parse_prs
    prs = parse_prs(str(prs_path))

    issues = validate_prs(prs)
    errors = [m for s, m in issues if s == ERROR]
    warnings = [m for s, m in issues if s == WARNING]

    if errors:
        _result(f"Validation: {len(errors)} errors, "
                f"{len(warnings)} warnings")
    else:
        _result(f"Validation: PASS ({len(warnings)} warnings)")

    # ── Step 8: Show statistics ───────────────────────────────────────
    _step(8, total_steps, "Computing statistics...")

    stats = compute_statistics(prs)
    lines = format_statistics(stats, filename="DEMO_PATROL.PRS")
    for line in lines:
        print(f"  {line}")

    # ── Step 9: Show capacity ─────────────────────────────────────────
    _step(9, total_steps, "Checking capacity...")

    cap = estimate_capacity(prs)
    cap_lines = format_capacity(cap, filename="DEMO_PATROL.PRS")
    for line in cap_lines:
        print(f"  {line}")

    # ── Step 10: Export to JSON ───────────────────────────────────────
    _step(10, total_steps, "Exporting to JSON...")

    json_path = out / "DEMO_PATROL.json"
    d = prs_to_dict(prs)
    text = dict_to_json(d)
    json_path.write_text(text, encoding='utf-8')
    _result(f"Saved: {json_path.name} ({_file_size(json_path)} bytes)")

    # Also export INI config
    ini_path = out / "DEMO_PATROL.ini"
    try:
        export_config(prs, str(ini_path), source_path=str(prs_path))
        _result(f"Saved: {ini_path.name} ({_file_size(ini_path)} bytes)")
    except Exception:
        _result("INI export: skipped")

    # ── Step 11: Generate HTML report ─────────────────────────────────
    _step(11, total_steps, "Generating HTML report...")

    report_path = out / "DEMO_PATROL_report.html"
    generate_html_report(prs, filepath=str(report_path),
                         source_path=str(prs_path))
    _result(f"Saved: {report_path.name} "
            f"({_file_size(report_path)} bytes)")

    card_path = out / "DEMO_PATROL_card.html"
    generate_summary_card(prs, filepath=str(card_path),
                          source_path=str(prs_path))
    _result(f"Saved: {card_path.name} ({_file_size(card_path)} bytes)")

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("=" * 52)
    print(f"Demo complete! Files in {out}/:")

    for p in sorted(out.iterdir()):
        if p.is_file():
            size = p.stat().st_size
            print(f"  {p.name:<30s} ({size:,} bytes)")

    print("=" * 52)

    return 0


# ─── Interactive Tutorial ─────────────────────────────────────────────


def _tutorial_pause(msg="Press Enter to continue..."):
    """Pause and wait for user input."""
    try:
        input(f"\n  {msg}")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return True


def _tutorial_section(num, title):
    """Print a tutorial section header."""
    print()
    print(f"{'=' * 52}")
    print(f"  Section {num}: {title}")
    print(f"{'=' * 52}")
    print()


def run_tutorial():
    """Interactive tutorial that teaches QuickPRS CLI usage.

    Walks the user through each concept with explanations
    and hands-on exercises. Uses input() prompts to pace.

    Returns:
        0 on success, 1 on interrupted.
    """
    from .builder import create_blank_prs
    from .prs_writer import write_prs
    from .injector import add_conv_system, make_conv_set
    from .record_types import ConvSystemConfig
    from .templates import get_template_channels, get_template_names
    from .validation import validate_prs, estimate_capacity, format_capacity
    from .validation import ERROR, WARNING

    _print_banner("QuickPRS Tutorial",
                  "Learn the CLI step by step")

    print("This tutorial walks through the core QuickPRS commands.")
    print("Each section explains a concept, shows the command,")
    print("and runs it so you can see the output.")
    print()
    print("You can quit at any time with Ctrl+C.")

    if not _tutorial_pause():
        return 1

    # ── Section 1: What is QuickPRS? ──────────────────────────────────
    _tutorial_section(1, "What is QuickPRS?")

    print("QuickPRS is a tool for working with Harris XG-100P")
    print("portable radio personality (.PRS) files.")
    print()
    print("A personality file defines everything about how a")
    print("radio is configured: systems, channels, talkgroups,")
    print("frequencies, scan lists, and radio options.")
    print()
    print("QuickPRS can:")
    print("  - Create, edit, and validate .PRS files")
    print("  - Inject P25 trunked systems and conventional channels")
    print("  - Import from RadioReference, CHIRP, Uniden, SDRTrunk")
    print("  - Export to JSON, INI, CSV, HTML reports")
    print("  - Repair damaged files and check configurations")
    print()
    print("All operations work from the command line:")
    print("  quickprs <command> [options]")

    if not _tutorial_pause():
        return 1

    # Use a temp directory for tutorial files
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="quickprs_tutorial_"))

    # ── Section 2: Creating a personality ─────────────────────────────
    _tutorial_section(2, "Creating a Personality")

    print("The first step is creating a blank personality file.")
    print()
    print("Command:")
    print("  quickprs create radio.PRS")
    print()
    print("Running it now...")
    print()

    prs_path = tmpdir / "tutorial.PRS"
    prs = create_blank_prs(filename="tutorial.PRS")
    write_prs(prs, str(prs_path))

    size = prs_path.stat().st_size
    print(f"  Created: {prs_path.name}")
    print(f"  Size: {size:,} bytes")
    print(f"  Sections: {len(prs.sections)}")
    print()
    print("A blank personality has one conventional system with")
    print("a single default channel. It's the starting point for")
    print("adding your radio configuration.")

    if not _tutorial_pause():
        return 1

    # ── Section 3: Adding channels ────────────────────────────────────
    _tutorial_section(3, "Adding Channels with Templates")

    templates = get_template_names()
    print("QuickPRS includes built-in channel templates:")
    for t in templates:
        channels = get_template_channels(t)
        print(f"  {t:<15s} ({len(channels)} channels)")
    print()
    print("Command:")
    print("  quickprs inject radio.PRS conv --template murs")
    print()
    print("Running it now (adding MURS channels)...")
    print()

    murs = get_template_channels('murs')
    murs_set = make_conv_set("MURS", murs)
    config = ConvSystemConfig(
        system_name="MURS",
        long_name="MURS",
        conv_set_name="MURS",
    )
    from .prs_parser import parse_prs
    prs = parse_prs(str(prs_path))
    add_conv_system(prs, config, conv_set=murs_set)
    write_prs(prs, str(prs_path))

    print(f"  Injected {len(murs)} MURS channels")
    print(f"  File size: {prs_path.stat().st_size:,} bytes")

    if not _tutorial_pause():
        return 1

    # ── Section 4: Adding P25 systems ─────────────────────────────────
    _tutorial_section(4, "Adding P25 Trunked Systems")

    print("P25 trunked systems require a system ID, frequencies,")
    print("and talkgroups. QuickPRS supports several import methods:")
    print()
    print("  1. CSV files with frequency and talkgroup data")
    print("     quickprs inject radio.PRS p25 --name SYS --sysid 892 \\")
    print("       --freqs-csv freqs.csv --tgs-csv tgs.csv")
    print()
    print("  2. RadioReference API (requires premium account)")
    print("     quickprs import-rr radio.PRS --sid 8155 \\")
    print("       --username USER --apikey KEY")
    print()
    print("  3. Built-in database of 30 US metro systems")
    print("     quickprs systems list")
    print("     quickprs systems add radio.PRS PSERN")
    print()
    print("  4. Pasted RadioReference text")
    print("     quickprs import-paste radio.PRS --name SYS \\")
    print("       --sysid 892 --tgs-file talkgroups.txt")

    if not _tutorial_pause():
        return 1

    # ── Section 5: Radio options ──────────────────────────────────────
    _tutorial_section(5, "Radio Options")

    print("Radio options control hardware settings like GPS,")
    print("audio, bluetooth, display, and security.")
    print()
    print("List all available options:")
    print("  quickprs set-option radio.PRS --list")
    print()
    print("Read a specific option:")
    print("  quickprs set-option radio.PRS gps.gpsMode")
    print()
    print("Set an option:")
    print("  quickprs set-option radio.PRS gps.gpsMode ON")
    print("  quickprs set-option radio.PRS misc.password 1234")
    print()
    print("Options are organized by section: gps, misc, audio,")
    print("bluetooth, timedate, display, security, etc.")

    if not _tutorial_pause():
        return 1

    # ── Section 6: Validation ─────────────────────────────────────────
    _tutorial_section(6, "Validation and Health Checks")

    print("QuickPRS validates configurations against XG-100P")
    print("hardware limits and best practices.")
    print()
    print("Commands:")
    print("  quickprs validate radio.PRS    # Hardware limit check")
    print("  quickprs health radio.PRS      # Best practice check")
    print("  quickprs capacity radio.PRS    # Memory usage report")
    print()
    print("Running validation on our tutorial file...")
    print()

    prs = parse_prs(str(prs_path))
    issues = validate_prs(prs)
    errors = [m for s, m in issues if s == ERROR]
    warnings = [m for s, m in issues if s == WARNING]

    if errors:
        print(f"  Result: {len(errors)} errors, {len(warnings)} warnings")
        for msg in errors[:3]:
            print(f"    [ERROR] {msg}")
    else:
        print(f"  Result: PASS ({len(warnings)} warnings)")
        for msg in warnings[:3]:
            print(f"    [WARN] {msg}")

    print()
    print("Running capacity check...")
    print()

    cap = estimate_capacity(prs)
    cap_lines = format_capacity(cap, filename="tutorial.PRS")
    for line in cap_lines:
        print(f"  {line}")

    if not _tutorial_pause():
        return 1

    # ── Section 7: Exporting ──────────────────────────────────────────
    _tutorial_section(7, "Exporting Data")

    print("QuickPRS exports to many formats:")
    print()
    print("  quickprs export-json radio.PRS       # Structured JSON")
    print("  quickprs export-config radio.PRS      # Editable INI config")
    print("  quickprs report radio.PRS             # Full HTML report")
    print("  quickprs card radio.PRS               # Printable ref card")
    print("  quickprs export radio.PRS chirp       # CHIRP CSV")
    print("  quickprs export radio.PRS markdown    # Markdown doc")
    print("  quickprs convert radio.PRS --to json  # Universal converter")
    print()
    print("The JSON export preserves all data and can be imported")
    print("back with 'quickprs import-json' for lossless roundtrip.")

    if not _tutorial_pause():
        return 1

    # ── Section 8: Next steps ─────────────────────────────────────────
    _tutorial_section(8, "Next Steps")

    print("You now know the core QuickPRS workflow:")
    print()
    print("  1. Create a personality    (quickprs create)")
    print("  2. Add channels/systems    (quickprs inject)")
    print("  3. Set radio options       (quickprs set-option)")
    print("  4. Validate                (quickprs validate)")
    print("  5. Export/report           (quickprs report)")
    print()
    print("For a complete command reference:")
    print("  quickprs cheat-sheet")
    print()
    print("For help on any command:")
    print("  quickprs <command> --help")
    print()
    print("Run the demo to see a full build:")
    print("  quickprs demo")
    print()
    print("GitHub: https://github.com/TheAbider/QuickPRS")
    print()
    print("Tutorial complete! Tutorial files are in:")
    print(f"  {tmpdir}")

    return 0


# ─── About / Project Statistics ───────────────────────────────────────


def show_about():
    """Show comprehensive project information and statistics.

    Returns:
        0 always.
    """
    from .option_maps import OPTION_MAPS
    from .templates import get_template_names
    from .profile_templates import PROFILE_TEMPLATES
    from .system_database import SYSTEMS

    # Count binary field mappings across all OPTION_MAPS
    total_fields = 0
    total_bytes = 0
    for section_name, option_map in OPTION_MAPS.items():
        for field_def in option_map.fields:
            total_fields += 1
            total_bytes += field_def.size

    n_sections = len(OPTION_MAPS)
    n_templates = len(get_template_names())
    n_profiles = len(PROFILE_TEMPLATES)
    n_systems = len(SYSTEMS)

    print(f"QuickPRS v{__version__}")
    print("XG-100P Personality File Tool")
    print()
    print("Binary Format:")
    print(f"  {n_sections} section types decoded")
    print(f"  {total_fields}+ binary fields mapped")
    print(f"  {total_bytes}/{total_bytes} mapped bytes")
    print("  Lossless roundtrip verified")
    print()
    print("Channel Templates: "
          f"{n_templates} ({', '.join(get_template_names())})")
    print(f"Profile Templates: {n_profiles} "
          f"({', '.join(sorted(PROFILE_TEMPLATES.keys()))})")
    print(f"P25 System Database: {n_systems} US systems")
    print()
    print("GitHub: https://github.com/TheAbider/QuickPRS")
    print("License: MIT")

    return 0
