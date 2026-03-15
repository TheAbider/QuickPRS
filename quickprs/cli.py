"""Command-line interface for QuickPRS.

Non-GUI operations for scripting and batch processing:
    quickprs info file.PRS [--detail]
    quickprs validate file.PRS
    quickprs export-csv file.PRS output_dir/
    quickprs compare file_a.PRS file_b.PRS [--detail]
    quickprs dump file.PRS [-s N] [-x BYTES]
    quickprs inject file.PRS p25 --name PSERN --sysid 892 ...
    quickprs inject file.PRS conv --name MURS --channels-csv ch.csv
    quickprs inject file.PRS conv --name MURS --template murs
    quickprs inject file.PRS talkgroups --set "PSERN PD" --tgs-csv tgs.csv
    quickprs merge target.PRS source.PRS [--systems] [--channels] [--all]
    quickprs clone target.PRS source.PRS "PSERN SEATTLE" [-o output.PRS]
    quickprs import-rr file.PRS --sid 8155 --username USER --apikey KEY
    quickprs import-paste file.PRS --name PSERN --sysid 892 --tgs-file tgs.txt
    quickprs export-json file.PRS [-o output.json]
    quickprs import-json file.json [-o output.PRS]
    quickprs remove file.PRS system "PSERN SEATTLE"
    quickprs remove file.PRS trunk-set "PSERN"
    quickprs remove file.PRS group-set "PSERN PD"
    quickprs remove file.PRS conv-set "MURS"
    quickprs edit file.PRS --name "NEW NAME.PRS"
    quickprs edit file.PRS --author "New Author"
    quickprs edit file.PRS --rename-set trunk PSERN NEWNAME
    quickprs set-option file.PRS gps.gpsMode ON
    quickprs set-option file.PRS misc.password 1234
    quickprs set-option file.PRS --list
    quickprs repair file.PRS [-o repaired.PRS]
    quickprs repair file.PRS --salvage
    quickprs capacity file.PRS
    quickprs build config.ini [-o output.PRS]
    quickprs fleet config.ini --units units.csv [-o output_dir/]
    quickprs list file.PRS systems|talkgroups|channels|frequencies|sets|options
    quickprs bulk-edit file.PRS talkgroups --set "PSERN PD" --enable-scan
    quickprs bulk-edit file.PRS talkgroups --set "PSERN PD" --disable-tx
    quickprs bulk-edit file.PRS talkgroups --set "PSERN PD" --prefix "PD "
    quickprs bulk-edit file.PRS channels --set "MURS" --set-tone "100.0"
    quickprs bulk-edit file.PRS channels --set "MURS" --clear-tones
    quickprs freq-tools offset 146.94
    quickprs freq-tools channel 462.5625
    quickprs freq-tools tones
    quickprs freq-tools dcs
    quickprs freq-tools nearest 100.5
    quickprs auto-setup file.PRS --sid 8155 --username X --apikey Y
    quickprs systems list
    quickprs systems search "seattle"
    quickprs systems info PSERN
    quickprs systems add file.PRS PSERN
    quickprs export file.PRS chirp [-o channels.csv] [--sets "MURS,GMRS"]
    quickprs export file.PRS uniden [-o channels.csv]
    quickprs export file.PRS sdrtrunk [-o talkgroups.csv]
    quickprs export file.PRS dsd [-o freqs.txt]
    quickprs export file.PRS markdown [-o config.md]
    quickprs zones file.PRS
    quickprs zones file.PRS --strategy by_set
    quickprs zones file.PRS --export zones.csv
    quickprs stats file.PRS
    quickprs card file.PRS [-o card.html]
    quickprs clone-personality file.PRS -o variant.PRS --name "DET" --remove-set FIRE
    quickprs renumber file.PRS --set "MURS" --start 1
    quickprs auto-name file.PRS --set "PSERN PD" --style compact
    quickprs cleanup file.PRS --check
    quickprs cleanup file.PRS --fix
    quickprs cleanup file.PRS --remove-unused
    quickprs search *.PRS --freq 851.0125
    quickprs search *.PRS --tg 1000
    quickprs search *.PRS --name "PSERN"
    quickprs rename file.PRS --set "PSERN PD" --pattern "^PD " --replace ""
    quickprs sort file.PRS --set "MURS" --key frequency
    quickprs diff-report before.PRS after.PRS [-o report.txt]
    quickprs export-config file.PRS [-o config.ini]
    quickprs profiles list
    quickprs profiles build scanner_basic [-o scanner.PRS]
"""

import csv
import logging
import sys
from pathlib import Path

logger = logging.getLogger("quickprs")

from . import __version__
from .prs_parser import parse_prs
from .record_types import (
    parse_class_header, parse_group_section,
    parse_trunk_channel_section, parse_conv_channel_section,
    parse_iden_section, parse_system_short_name,
    parse_system_long_name, parse_system_wan_name,
    is_system_config_data, parse_ecc_entries,
    parse_sets_from_sections,
)
from .validation import validate_prs, ERROR, WARNING, INFO
from .comparison import (
    compare_prs_files, format_comparison,
    detailed_comparison, format_detailed_comparison,
)
from .option_maps import (
    extract_platform_config, extract_blob_preamble,
    format_button_function, format_button_name,
    format_switch_function, format_short_menu_name,
    set_platform_option, list_platform_options,
    SECTION_MAP,
)
from .csv_export import (
    export_group_sets, export_trunk_sets, export_conv_sets,
    export_iden_sets, export_options, export_systems,
    export_ecc, export_preferred,
)


def cmd_info(filepath, detail=False):
    """Print personality summary to stdout.

    Args:
        filepath: PRS file path
        detail: if True, show verbose output with WAN entries, IDEN details,
                conv channel frequencies, preferred entries, option section
                listing, and file size breakdown by section type.
    """
    prs = parse_prs(filepath)
    print(f"File: {filepath}")
    print(f"Size: {prs.file_size:,} bytes")
    print(f"Sections: {len(prs.sections)}")
    print()

    # Systems
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        if not secs:
            continue
        names = [parse_system_short_name(s.raw) or "?" for s in secs]
        print(f"{label} ({len(secs)}): {', '.join(names)}")

    # Config names
    config_names = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            ln = parse_system_long_name(sec.raw)
            if ln:
                config_names.append(ln)
    if config_names:
        print(f"System configs: {', '.join(config_names)}")

    # ECC (Enhanced Control Channel) entries per system
    ecc_info = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            sname = parse_system_long_name(sec.raw) or "Unknown"
            ecc_count, _, iden_name = parse_ecc_entries(sec.raw)
            if ecc_count > 0:
                wacn = ""
                try:
                    wacn = parse_system_wan_name(sec.raw) or ""
                except Exception:
                    pass
                iden_str = f" IDEN: {iden_name}" if iden_name else ""
                wacn_str = f" WACN: {wacn}" if wacn else ""
                ecc_info.append(
                    f"  {sname}: {ecc_count} ECC entries"
                    f"{iden_str}{wacn_str}")
    if ecc_info:
        print(f"\nEnhanced Control Channels:")
        for line in ecc_info:
            print(line)
    print()

    # Group sets
    sets = _parse_group_sets(prs)
    if sets:
        total = sum(len(s.groups) for s in sets)
        print(f"Group Sets ({len(sets)}):")
        for gs in sets:
            scan_ct = sum(1 for g in gs.groups if g.scan)
            print(f"  {gs.name}: {len(gs.groups)} TGs ({scan_ct} scan)")
        print(f"  Total: {total} talkgroups")
        print()

    # Trunk sets
    sets = _parse_trunk_sets(prs)
    if sets:
        total = sum(len(s.channels) for s in sets)
        print(f"Trunk Sets ({len(sets)}):")
        for ts in sets:
            print(f"  {ts.name}: {len(ts.channels)} freqs "
                  f"({ts.tx_min:.0f}-{ts.tx_max:.0f} MHz)")
        print(f"  Total: {total} frequencies")
        print()

    # Conv sets
    conv_sets = _parse_conv_sets(prs)
    if conv_sets:
        total = sum(len(s.channels) for s in conv_sets)
        print(f"Conv Sets ({len(conv_sets)}):")
        for cs in conv_sets:
            print(f"  {cs.name}: {len(cs.channels)} channels")
        print(f"  Total: {total} channels")
        print()

    # IDEN sets
    iden_sets = _parse_iden_sets(prs)
    if iden_sets:
        print(f"IDEN Sets ({len(iden_sets)}):")
        for iset in iden_sets:
            active = [e for e in iset.elements if not e.is_empty()]
            fdma = sum(1 for e in active if not e.iden_type)
            tdma = sum(1 for e in active if e.iden_type)
            if fdma and tdma:
                mode = "mixed FDMA+TDMA"
            elif tdma:
                mode = "TDMA"
            else:
                mode = "FDMA"
            if detail:
                base_freqs = [f"{e.base_freq_hz / 1_000_000:.5f}"
                              for e in active]
                base_str = ", ".join(base_freqs)
                print(f"  {iset.name}: {len(active)}/16 active ({mode})"
                      f" [{base_str} MHz]")
            else:
                print(f"  {iset.name}: {len(active)}/16 active ({mode})")
        print()

    # WAN entries (detail mode)
    if detail:
        from .record_types import parse_wan_section
        wan_sec = prs.get_section_by_class("CP25TrkWan")
        if wan_sec:
            try:
                wan_entries = parse_wan_section(wan_sec.raw)
                if wan_entries:
                    print(f"WAN Entries ({len(wan_entries)}):")
                    for entry in wan_entries:
                        print(f"  {entry.wan_name.strip()}: "
                              f"WACN={entry.wacn} "
                              f"SysID={entry.system_id}")
                    print()
            except Exception:
                pass

    # Preferred system table (detail mode)
    if detail:
        from .injector import get_preferred_entries
        pref_entries, pref_iden, pref_chain = get_preferred_entries(prs)
        if pref_entries:
            print(f"Preferred System Table ({len(pref_entries)} entries):")
            for entry in pref_entries:
                parts = [f"  [{entry.field2}]"]
                if hasattr(entry, 'wan_name') and entry.wan_name:
                    parts.append(entry.wan_name.strip())
                if hasattr(entry, 'system_id') and entry.system_id:
                    parts.append(f"SysID={entry.system_id}")
                print(" ".join(parts))
            if pref_iden:
                print(f"  IDEN: {pref_iden}")
            if pref_chain:
                print(f"  Chain: {pref_chain}")
            print()

    # Conv channel details (detail mode)
    if detail and conv_sets:
        print("Conv Channel Details:")
        for cs in conv_sets:
            print(f"  {cs.name}:")
            for ch in cs.channels:
                tone_info = ""
                if ch.tx_tone:
                    tone_info += f" TX:{ch.tx_tone}"
                if ch.rx_tone:
                    tone_info += f" RX:{ch.rx_tone}"
                print(f"    {ch.short_name:<8s} "
                      f"{ch.tx_freq:>10.4f}/{ch.rx_freq:>10.4f} MHz"
                      f"{tone_info}")
        print()

    # Radio options from platformConfig XML
    config = extract_platform_config(prs)
    if config:
        _print_radio_options(config)

    # Blob preamble (file metadata, OOR alert)
    bp = extract_blob_preamble(prs)
    if bp:
        parts = []
        if bp.oor_alert_interval > 0:
            parts.append(f"Repeated OOR Alert: {bp.oor_display}")
        if bp.filename:
            parts.append(f"RPM Filename: {bp.filename}")
        if bp.username:
            parts.append(f"Author: {bp.username}")
        if parts:
            print("File Metadata:")
            for p in parts:
                print(f"  {p}")
            print()

    # Binary option sections (mapped fields)
    from .option_maps import OPTION_MAPS, extract_section_data, read_field
    mapped_sections = []
    for cls_name, opt_map in OPTION_MAPS.items():
        sec = prs.get_section_by_class(cls_name)
        if sec is None:
            continue
        data = extract_section_data(sec)
        if data is None or not opt_map.fields:
            continue
        mapped_sections.append((opt_map, data))

    if mapped_sections:
        print("Binary Options:")
        for opt_map, data in mapped_sections:
            values = []
            for fd in opt_map.fields:
                val = read_field(data, fd)
                if val is not None:
                    values.append(f"{fd.display_name}: {val}")
            if values:
                print(f"  {opt_map.display_name} ({opt_map.coverage:.0%} mapped):")
                for v in values:
                    print(f"    {v}")
        print()

    # Option sections present (detail mode)
    if detail:
        option_classes = []
        for cls_name in OPTION_MAPS:
            sec = prs.get_section_by_class(cls_name)
            if sec is not None:
                option_classes.append(cls_name)
        if option_classes:
            print(f"Option Sections ({len(option_classes)}):")
            for cls in option_classes:
                print(f"  {cls}")
            print()

    # Named sections
    named = [s for s in prs.sections if s.class_name]
    print(f"Named records ({len(named)}):")
    for s in named:
        print(f"  {s.class_name} ({len(s.raw):,} bytes)")

    # File size breakdown by section type (detail mode)
    if detail:
        print()
        _print_size_breakdown(prs)

    return 0


def _print_size_breakdown(prs):
    """Print file size breakdown by section type."""
    type_sizes = {}
    for sec in prs.sections:
        key = sec.class_name if sec.class_name else "(data)"
        if key not in type_sizes:
            type_sizes[key] = {'count': 0, 'bytes': 0}
        type_sizes[key]['count'] += 1
        type_sizes[key]['bytes'] += len(sec.raw)

    total = sum(v['bytes'] for v in type_sizes.values())
    # Sort by size descending
    sorted_types = sorted(type_sizes.items(),
                          key=lambda x: x[1]['bytes'], reverse=True)

    print("Size Breakdown:")
    for name, info in sorted_types:
        pct = (info['bytes'] / total * 100) if total else 0
        print(f"  {name:<30s} {info['count']:>3d} section(s) "
              f"{info['bytes']:>8,d} bytes ({pct:4.1f}%)")
    print(f"  {'Total':<30s} {len(prs.sections):>3d} section(s) "
          f"{total:>8,d} bytes")


def _print_radio_options(config):
    """Print radio option summary from parsed platformConfig dict."""

    # Key settings
    print("Radio Options:")
    misc = config.get("miscConfig", {})
    audio = config.get("audioConfig", {})
    gps = config.get("gpsConfig", {})
    bt = config.get("bluetoothConfig", {})
    time_cfg = config.get("TimeDateCfg", {})

    # Battery
    batt = misc.get("batteryType", "")
    if batt:
        batt_map = {"LITHIUM_ION_POLY": "Lithium Ion Poly", "NIMH": "NiMH",
                     "ALKALINE": "Alkaline", "PRIMARY_LITHIUM": "Primary Lithium"}
        print(f"  Battery: {batt_map.get(batt, batt)}")

    # Audio highlights
    parts = []
    speaker = audio.get("speakerMode", "")
    if speaker:
        parts.append(f"Speaker={'On' if speaker == 'ON' else 'Off'}")
    nc = audio.get("noiseCancellation", "")
    if nc:
        parts.append(f"NoiseCan={'On' if nc == 'ON' else 'Off'}")
    tones = audio.get("tones", "")
    if tones:
        parts.append(f"Tones={'On' if tones == 'ON' else 'Off'}")
    if parts:
        print(f"  Audio: {', '.join(parts)}")

    # GPS
    gps_mode = gps.get("gpsMode", "")
    if gps_mode:
        gps_type = gps.get("type", "")
        type_map = {"INTERNAL_GPS": "Internal", "EXTERNAL_GPS": "External"}
        label = "On" if gps_mode == "ON" else "Off"
        if gps_mode == "ON" and gps_type:
            label += f" ({type_map.get(gps_type, gps_type)})"
        print(f"  GPS: {label}")

    # Bluetooth
    bt_admin = bt.get("btAdminMode", "")
    if bt_admin:
        bt_enable = bt.get("btMode", "")
        if bt_admin == "OFF":
            print("  Bluetooth: Not Allowed")
        elif bt_enable == "ON":
            name = bt.get("friendlyName", "")
            label = "Enabled"
            if name:
                label += f" ({name})"
            print(f"  Bluetooth: {label}")
        else:
            print("  Bluetooth: Allowed (Off)")

    # Time zone
    tz = time_cfg.get("zone", "")
    if tz:
        tz_map = {"BIT": "UTC-12", "SST": "UTC-11", "HST": "UTC-10",
                   "AKST": "UTC-9", "PST": "UTC-8", "MST": "UTC-7",
                   "CST": "UTC-6", "EST": "UTC-5", "AST": "UTC-4",
                   "ART": "UTC-3", "BRST": "UTC-2", "AZOT": "UTC-1",
                   "GMT": "UTC+0", "CET": "UTC+1", "EET": "UTC+2",
                   "MSK": "UTC+3", "GST": "UTC+4", "PKT": "UTC+5",
                   "BST": "UTC+6", "ICT": "UTC+7", "HKT": "UTC+8",
                   "JST": "UTC+9", "AEST": "UTC+10", "SBT": "UTC+11",
                   "NZST": "UTC+12", "PHOT": "UTC+13", "LINT": "UTC+14"}
        print(f"  Time Zone: {tz_map.get(tz, tz)}")
    print()

    # Programmable Buttons
    prog = config.get("progButtons", {})
    if prog:
        print("Programmable Buttons:")
        # Switches
        fn2 = prog.get("_2PosFunction", "")
        if fn2:
            print(f"  2-Pos Switch: {format_switch_function(fn2)}")
        fn3 = prog.get("_3PosFunction", "")
        if fn3:
            print(f"  3-Pos Switch: {format_switch_function(fn3)}")

        # Side buttons
        buttons = prog.get("progButton", [])
        if isinstance(buttons, dict):
            buttons = [buttons]
        for btn in buttons:
            name = btn.get("buttonName", "")
            func = btn.get("function", "")
            if name and func:
                print(f"  {format_button_name(name)}: "
                      f"{format_button_function(func)}")
        print()

    # Accessory buttons
    acc_btns_container = config.get("accessoryButtons", {})
    if acc_btns_container:
        acc_btns = acc_btns_container.get("accessoryButton", [])
        if isinstance(acc_btns, dict):
            acc_btns = [acc_btns]
        if acc_btns:
            print("Accessory Buttons:")
            for btn in acc_btns:
                name = btn.get("buttonName", "")
                func = btn.get("function", "")
                if name and func:
                    print(f"  {format_button_name(name)}: "
                          f"{format_button_function(func)}")
            print()

    # Short Menu
    menu = config.get("shortMenu", {})
    if menu:
        items = menu.get("shortMenuItem", [])
        if isinstance(items, dict):
            items = [items]
        filled = [it for it in items
                  if it.get("name", "empty") != "empty"]
        if items:
            print(f"Short Menu ({len(filled)}/{len(items)} slots):")
            for it in items:
                pos = it.get("position", "?")
                name = it.get("name", "empty")
                friendly = format_short_menu_name(name)
                if name != "empty":
                    print(f"  [{pos}] {friendly}")
            print()


def cmd_validate(filepath):
    """Validate a PRS file, print issues. Exit code 1 if errors found."""
    prs = parse_prs(filepath)
    issues = validate_prs(prs)

    errors = [(s, m) for s, m in issues if s == ERROR]
    warnings = [(s, m) for s, m in issues if s == WARNING]
    infos = [(s, m) for s, m in issues if s == INFO]

    print(f"Validating: {filepath}")
    print(f"Size: {prs.file_size:,} bytes | "
          f"Sections: {len(prs.sections)}")
    print()

    if not issues:
        print("PASS: No issues found.")
        return 0

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for _, msg in errors:
            print(f"  [ERROR] {msg}")
        print()

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for _, msg in warnings:
            print(f"  [WARN]  {msg}")
        print()

    if infos:
        print(f"INFO ({len(infos)}):")
        for _, msg in infos:
            print(f"  [INFO]  {msg}")
        print()

    print(f"Summary: {len(errors)} errors, {len(warnings)} warnings, "
          f"{len(infos)} info")
    return 1 if errors else 0


def cmd_export_csv(filepath, output_dir):
    """Export personality data to CSV files."""
    prs = parse_prs(filepath)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    exported = []

    sets = _parse_group_sets(prs)
    if sets:
        exported.append(export_group_sets(out / "GROUP_SET.csv", sets))

    sets = _parse_trunk_sets(prs)
    if sets:
        exported.append(export_trunk_sets(out / "TRK_SET.csv", sets))

    sets = _parse_conv_sets(prs)
    if sets:
        exported.append(export_conv_sets(out / "CONV_SET.csv", sets))

    sets = _parse_iden_sets(prs)
    if sets:
        exported.append(export_iden_sets(out / "IDEN_SET.csv", sets))

    result = export_options(out / "OPTIONS.csv", prs)
    if result:
        exported.append(result)

    result = export_systems(out / "SYSTEMS.csv", prs)
    if result:
        exported.append(result)

    result = export_ecc(out / "ECC.csv", prs)
    if result:
        exported.append(result)

    result = export_preferred(out / "PREFERRED.csv", prs)
    if result:
        exported.append(result)

    if exported:
        print(f"Exported to {output_dir}:")
        for e in exported:
            print(f"  {e}")
    else:
        print("No data to export.")
    return 0


def cmd_export(filepath, fmt, output=None, sets=None):
    """Export PRS data to third-party radio tool formats.

    Args:
        filepath: PRS file path
        fmt: export format ('chirp', 'uniden', 'sdrtrunk', 'dsd', 'markdown')
        output: output file path (auto-named if None)
        sets: list of set names to export (None = all)

    Returns:
        0 on success, 1 on error.
    """
    from .export_formats import (
        export_chirp_csv, export_uniden_csv, export_sdrtrunk_csv,
        export_dsd_freqs, export_markdown,
    )

    prs = parse_prs(filepath)
    stem = Path(filepath).stem

    if fmt == "chirp":
        out_path = output or f"{stem}_chirp.csv"
        count = export_chirp_csv(prs, out_path, sets=sets)
        print(f"Exported {count} channels to CHIRP CSV: {out_path}")
    elif fmt == "uniden":
        out_path = output or f"{stem}_uniden.csv"
        count = export_uniden_csv(prs, out_path, sets=sets)
        print(f"Exported {count} channels to Uniden CSV: {out_path}")
    elif fmt == "sdrtrunk":
        out_path = output or f"{stem}_talkgroups.csv"
        count = export_sdrtrunk_csv(prs, out_path, sets=sets)
        print(f"Exported {count} talkgroups to SDRTrunk CSV: {out_path}")
    elif fmt == "dsd":
        out_path = output or f"{stem}_freqs.txt"
        count = export_dsd_freqs(prs, out_path, sets=sets)
        print(f"Exported {count} frequencies to DSD+ format: {out_path}")
    elif fmt == "markdown":
        out_path = output or f"{stem}.md"
        export_markdown(prs, out_path)
        print(f"Exported Markdown report: {out_path}")
    else:
        print(f"Unknown export format: {fmt}", file=sys.stderr)
        return 1

    return 0


def cmd_compare(filepath_a, filepath_b, detail=False):
    """Compare two PRS files and show differences.

    Args:
        filepath_a: first PRS file path
        filepath_b: second PRS file path
        detail: if True, show detailed side-by-side comparison with
                individual talkgroups, frequencies, channels, and options.
    """
    diffs = compare_prs_files(filepath_a, filepath_b)
    lines = format_comparison(diffs, filepath_a, filepath_b)
    print("\n".join(lines))

    if detail:
        prs_a = parse_prs(filepath_a)
        prs_b = parse_prs(filepath_b)
        detail_data = detailed_comparison(prs_a, prs_b)
        detail_lines = format_detailed_comparison(
            detail_data, filepath_a, filepath_b)
        print()
        print("\n".join(detail_lines))

    errors = sum(1 for d in diffs if d[0] in ("ADDED", "REMOVED", "CHANGED"))
    return 1 if errors else 0


def cmd_dump(filepath, section_idx=None, hex_bytes=0):
    """Dump raw section information from a PRS file.

    If section_idx is given, dump details for that section.
    hex_bytes controls how many bytes of hex to show (0=none).
    """
    prs = parse_prs(filepath)

    if section_idx is not None:
        # Validate index before printing anything
        if section_idx < 0 or section_idx >= len(prs.sections):
            print(f"Error: section index {section_idx} out of range "
                  f"(0-{len(prs.sections) - 1})", file=sys.stderr)
            return 1

    print(f"File: {filepath}")
    print(f"Size: {prs.file_size:,} bytes")
    print(f"Sections: {len(prs.sections)}")
    print()

    if section_idx is not None:
        sec = prs.sections[section_idx]
        print(f"Section [{section_idx}]:")
        print(f"  Class: {sec.class_name or '(unnamed)'}")
        print(f"  Offset: {sec.offset}")
        print(f"  Size: {len(sec.raw):,} bytes")
        if sec.class_name:
            try:
                name, b1, b2, ds = parse_class_header(sec.raw, 0)
                print(f"  Header: class={name}, byte1=0x{b1:02x}, "
                      f"byte2=0x{b2:02x}, data_start={ds}")
            except Exception as e:
                logger.debug("Could not parse header for section %d: %s", section_idx, e)
        if hex_bytes > 0:
            show = min(hex_bytes, len(sec.raw))
            print(f"  Hex ({show}/{len(sec.raw)} bytes):")
            for row_start in range(0, show, 16):
                chunk = sec.raw[row_start:row_start + 16]
                hex_str = " ".join(f"{b:02x}" for b in chunk)
                ascii_str = "".join(
                    chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"    {row_start:06x}  {hex_str:<48s}  {ascii_str}")
        return 0

    # List all sections
    print(f"{'#':>3}  {'Class':<30s}  {'Offset':>8s}  {'Size':>8s}")
    print(f"{'---':>3}  {'-' * 30}  {'--------':>8s}  {'--------':>8s}")
    for i, sec in enumerate(prs.sections):
        name = sec.class_name or "(data)"
        print(f"{i:3d}  {name:<30s}  {sec.offset:>8,d}  {len(sec.raw):>8,d}")

    return 0


# ─── Set parsing helpers ─────────────────────────────────────────────

def _parse_sets(prs, data_cls, set_cls, parser_func):
    """Parse a set type from PRS using the shared helper."""
    data_sec = prs.get_section_by_class(data_cls)
    set_sec = prs.get_section_by_class(set_cls)
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw, parser_func)


def _parse_group_sets(prs):
    return _parse_sets(prs, "CP25Group", "CP25GroupSet", parse_group_section)


def _parse_trunk_sets(prs):
    return _parse_sets(prs, "CTrunkChannel", "CTrunkSet",
                       parse_trunk_channel_section)


def _parse_conv_sets(prs):
    return _parse_sets(prs, "CConvChannel", "CConvSet",
                       parse_conv_channel_section)


def _parse_iden_sets(prs):
    return _parse_sets(prs, "CDefaultIdenElem", "CIdenDataSet",
                       parse_iden_section)


def cmd_diff_options(filepath_a, filepath_b, raw=False):
    """Diff radio options between two PRS files.

    Shows semantic differences in both XML platformConfig and binary
    option sections. With --raw, also shows byte-level diffs.
    """
    from .option_differ import (
        diff_options_from_files, format_option_diff,
        diff_section_bytes,
    )
    from .option_maps import OPTION_MAPS

    prs_a = parse_prs(filepath_a)
    prs_b = parse_prs(filepath_b)

    from .option_differ import diff_options
    diffs = diff_options(prs_a, prs_b)
    lines = format_option_diff(diffs, filepath_a, filepath_b)
    print("\n".join(lines))

    if raw:
        print("\n=== Raw Byte Diffs ===\n")
        for class_name, opt_map in OPTION_MAPS.items():
            byte_diffs = diff_section_bytes(prs_a, prs_b, class_name)
            if byte_diffs:
                print(f"--- {class_name} ({opt_map.display_name}) ---")
                for bd in byte_diffs:
                    print(f"  data[{bd.offset:3d}]: "
                          f"0x{bd.old_byte:02x} -> 0x{bd.new_byte:02x}")
                print()

    return 0


def cmd_iden_templates(detail=False):
    """List available standard IDEN templates."""
    from .iden_library import STANDARD_IDEN_TEMPLATES, get_template_keys

    keys = get_template_keys()
    print(f"Standard IDEN Templates ({len(keys)}):\n")

    for key in keys:
        tmpl = STANDARD_IDEN_TEMPLATES[key]
        active = sum(1 for e in tmpl.entries if e.get('base_freq_hz', 0) > 0)
        print(f"  {key:<12s}  {tmpl.label}")
        print(f"  {'':12s}  {tmpl.description}")
        print(f"  {'':12s}  {active}/16 active entries")
        if detail:
            for i, e in enumerate(tmpl.entries):
                if e.get('base_freq_hz', 0) == 0:
                    continue
                mode = "TDMA" if e.get('iden_type', 0) else "FDMA"
                base_mhz = e['base_freq_hz'] / 1_000_000
                spacing_khz = e.get('chan_spacing_hz', 0) / 1000
                offset = e.get('tx_offset_mhz', 0)
                print(f"  {'':12s}    [{i:2d}] {base_mhz:.5f} MHz "
                      f"{mode} sp:{spacing_khz:.2f}kHz "
                      f"off:{offset:+.1f}MHz")
        print()

    return 0


# ─── Inject commands ──────────────────────────────────────────────────

def _read_csv_file(filepath):
    """Read a CSV file and return rows as list of dicts via DictReader."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return list(reader)


def _parse_freq_csv(filepath):
    """Parse a frequencies CSV (tx_freq, rx_freq) into (tx, rx) tuples."""
    rows = _read_csv_file(filepath)
    freqs = []
    for i, row in enumerate(rows, 1):
        # Normalize keys to lowercase
        row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
        tx_str = row_lower.get('tx_freq', '') or row_lower.get('tx', '') or row_lower.get('frequency', '')
        rx_str = row_lower.get('rx_freq', '') or row_lower.get('rx', '')
        if not tx_str:
            raise ValueError(f"Row {i}: missing tx_freq")
        tx = float(tx_str)
        rx = float(rx_str) if rx_str else tx
        freqs.append((tx, rx))
    return freqs


def _parse_tgs_csv(filepath):
    """Parse a talkgroups CSV (id, short_name, long_name, tx, scan)."""
    rows = _read_csv_file(filepath)
    tgs = []
    for i, row in enumerate(rows, 1):
        row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
        id_str = (row_lower.get('id', '') or row_lower.get('tgid', '') or
                  row_lower.get('group_id', '') or row_lower.get('dec', ''))
        if not id_str:
            raise ValueError(f"Row {i}: missing talkgroup id")
        gid = int(id_str)
        short = (row_lower.get('short_name', '') or
                 row_lower.get('name', '') or f"TG{gid}")[:8]
        long_name = (row_lower.get('long_name', '') or
                     row_lower.get('description', '') or short)[:16]
        tx = row_lower.get('tx', 'N').upper() in ('Y', 'YES', 'TRUE', '1')
        scan = row_lower.get('scan', 'Y').upper() in ('Y', 'YES', 'TRUE', '1')
        tgs.append((gid, short, long_name, tx, scan))
    return tgs


def _parse_conv_csv(filepath):
    """Parse a conventional channels CSV."""
    rows = _read_csv_file(filepath)
    channels = []
    for i, row in enumerate(rows, 1):
        row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
        short = (row_lower.get('short_name', '') or
                 row_lower.get('name', '') or row_lower.get('channel', ''))
        if not short:
            raise ValueError(f"Row {i}: missing short_name")
        short = short[:8]
        tx_str = (row_lower.get('tx_freq', '') or row_lower.get('tx', '') or
                  row_lower.get('frequency', ''))
        if not tx_str:
            raise ValueError(f"Row {i}: missing tx_freq")
        tx = float(tx_str)
        rx_str = row_lower.get('rx_freq', '') or row_lower.get('rx', '')
        rx = float(rx_str) if rx_str else tx
        tx_tone = row_lower.get('tx_tone', '') or row_lower.get('tone', '')
        rx_tone = row_lower.get('rx_tone', '')
        long_name = (row_lower.get('long_name', '') or
                     row_lower.get('description', '') or short)[:16]
        channels.append({
            'short_name': short,
            'tx_freq': tx,
            'rx_freq': rx,
            'tx_tone': tx_tone,
            'rx_tone': rx_tone,
            'long_name': long_name,
        })
    return channels


def cmd_inject_p25(filepath, name, sysid, long_name=None, wacn=0,
                   freqs_csv=None, tgs_csv=None,
                   iden_base=None, iden_spacing=None,
                   output=None):
    """Inject a P25 trunked system into a PRS file.

    Args:
        filepath: input PRS file
        name: system short name (8 chars max)
        sysid: P25 System ID
        long_name: long display name (16 chars max)
        wacn: WACN (default 0)
        freqs_csv: CSV file with trunk frequencies
        tgs_csv: CSV file with talkgroups
        iden_base: IDEN base frequency in Hz (None = auto-detect)
        iden_spacing: channel spacing in Hz (None = auto-detect)
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import (
        add_p25_trunked_system,
        make_trunk_set, make_group_set, make_iden_set,
        make_p25_group, auto_iden_from_frequencies,
    )
    from .record_types import P25TrkSystemConfig
    from .prs_writer import write_prs

    name = name[:8]
    if not long_name:
        long_name = name
    long_name = long_name[:16]

    prs = parse_prs(filepath)

    # Parse CSV data
    trunk_set = None
    freqs = None
    if freqs_csv:
        freqs = _parse_freq_csv(freqs_csv)
        if not freqs:
            print("Error: frequencies CSV is empty", file=sys.stderr)
            return 1
        trunk_set = make_trunk_set(name, freqs)
        print(f"  Frequencies: {len(freqs)} from {freqs_csv}")

    group_set = None
    if tgs_csv:
        tgs = _parse_tgs_csv(tgs_csv)
        if not tgs:
            print("Error: talkgroups CSV is empty", file=sys.stderr)
            return 1
        groups = [make_p25_group(gid, sn, ln, tx=tx, scan=scan)
                  for gid, sn, ln, tx, scan in tgs]
        from .record_types import P25GroupSet
        group_set = P25GroupSet(name=name[:8], groups=groups)
        print(f"  Talkgroups: {len(tgs)} from {tgs_csv}")

    # Build IDEN set — auto-detect from frequencies or use explicit params
    iden_set = None
    if iden_base is not None:
        # Explicit IDEN parameters provided
        if iden_spacing is None:
            iden_spacing = 12500
        iden_set = make_iden_set(name[:5], [{
            'base_freq_hz': iden_base,
            'chan_spacing_hz': iden_spacing,
            'bandwidth_hz': iden_spacing // 2,
            'iden_type': 0,
        }])
    elif freqs:
        # Auto-detect IDEN from frequencies
        iden_set, descriptions = auto_iden_from_frequencies(
            freqs, set_name=name[:5])
        if iden_set:
            print("  IDEN auto-detected:")
            for desc in descriptions:
                print(f"    {desc}")
        else:
            print("  Warning: could not auto-detect IDEN from frequencies, "
                  "using 800 MHz FDMA default", file=sys.stderr)
            iden_base = 851012500
            iden_spacing = 12500
            iden_set = make_iden_set(name[:5], [{
                'base_freq_hz': iden_base,
                'chan_spacing_hz': iden_spacing,
                'bandwidth_hz': iden_spacing // 2,
                'iden_type': 0,
            }])
    else:
        # No frequencies and no explicit IDEN — use default
        iden_base = 851012500
        iden_spacing = 12500
        iden_set = make_iden_set(name[:5], [{
            'base_freq_hz': iden_base,
            'chan_spacing_hz': iden_spacing,
            'bandwidth_hz': iden_spacing // 2,
            'iden_type': 0,
        }])

    # Determine WAN parameters from IDEN set for system config
    if iden_base is None:
        # Get from the first active IDEN element
        for elem in iden_set.elements:
            if elem.base_freq_hz > 0:
                iden_base = elem.base_freq_hz
                iden_spacing = elem.chan_spacing_hz
                break
        if iden_base is None:
            iden_base = 851012500
            iden_spacing = 12500
    if iden_spacing is None:
        iden_spacing = 12500

    # Build system config
    config = P25TrkSystemConfig(
        system_name=name,
        long_name=long_name,
        trunk_set_name=name if trunk_set else "",
        group_set_name=name if group_set else "",
        wan_name=name,
        system_id=sysid,
        wacn=wacn,
        iden_set_name=name[:5] if iden_set else "",
        wan_base_freq_hz=iden_base,
        wan_chan_spacing_hz=iden_spacing,
    )

    add_p25_trunked_system(prs, config,
                           trunk_set=trunk_set,
                           group_set=group_set,
                           iden_set=iden_set)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Injected P25 system '{name}' (SysID {sysid}) into {out_path}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_inject_conv(filepath, name, channels_csv=None, template=None,
                    output=None):
    """Inject conventional channels into a PRS file.

    Channels can come from a CSV file (--channels-csv) or a built-in
    template (--template). Exactly one source must be specified.

    Args:
        filepath: input PRS file
        name: set name (8 chars max)
        channels_csv: CSV file with channel data
        template: template name (e.g., 'murs', 'gmrs', 'frs', 'marine', 'noaa')
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import (
        add_conv_system, make_conv_set,
    )
    from .record_types import ConvSystemConfig
    from .prs_writer import write_prs

    # Default name from template if not specified
    if not name and template:
        name = template.upper()
    elif not name:
        print("Error: --name is required (or use --template)", file=sys.stderr)
        return 1
    name = name[:8]
    prs = parse_prs(filepath)

    # Get channel data from CSV or template
    if template:
        from .templates import get_template_channels
        try:
            channels_data = get_template_channels(template)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    elif channels_csv:
        channels_data = _parse_conv_csv(channels_csv)
    else:
        print("Error: specify --channels-csv or --template", file=sys.stderr)
        return 1

    if not channels_data:
        print("Error: no channel data provided", file=sys.stderr)
        return 1

    conv_set = make_conv_set(name, channels_data)
    config = ConvSystemConfig(
        system_name=name,
        long_name=name,
        conv_set_name=name,
    )

    add_conv_system(prs, config, conv_set=conv_set)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    source = f"template '{template}'" if template else channels_csv
    print(f"Injected conv system '{name}' ({len(channels_data)} channels "
          f"from {source}) into {out_path}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_import_scanner(filepath, csv_file, scanner_fmt='auto',
                       name=None, output=None):
    """Import channels from a scanner CSV into a PRS file.

    Supports Uniden Sentinel, CHIRP, and SDRTrunk CSV formats.
    Auto-detects format by examining CSV headers.

    Args:
        filepath: input PRS file
        csv_file: scanner CSV file to import
        scanner_fmt: 'uniden', 'chirp', 'sdrtrunk', or 'auto'
        name: conv set name (defaults to CSV filename stem)
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .scanner_import import import_scanner_csv, detect_scanner_format
    from .injector import add_conv_system, make_conv_set
    from .record_types import ConvSystemConfig
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    # Auto-detect or use specified format
    fmt = scanner_fmt if scanner_fmt != 'auto' else None
    if fmt is None:
        fmt = detect_scanner_format(csv_file)
        if fmt == 'unknown':
            print(f"Error: cannot auto-detect scanner format for "
                  f"{csv_file}. Use --format to specify.",
                  file=sys.stderr)
            return 1
        print(f"Auto-detected format: {fmt}")

    try:
        channels = import_scanner_csv(csv_file, fmt=fmt)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not channels:
        print("Error: no channels found in scanner CSV", file=sys.stderr)
        return 1

    # Set name from argument or CSV filename
    if not name:
        name = Path(csv_file).stem[:8].upper()
    name = name[:8]

    conv_set = make_conv_set(name, channels)
    config = ConvSystemConfig(
        system_name=name,
        long_name=name,
        conv_set_name=name,
    )

    add_conv_system(prs, config, conv_set=conv_set)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Imported {len(channels)} channels from {csv_file} "
          f"(format: {fmt}) as conv system '{name}' into {out_path}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_inject_talkgroups(filepath, set_name, tgs_csv, output=None):
    """Add talkgroups to an existing group set in a PRS file.

    Args:
        filepath: input PRS file
        set_name: target group set name
        tgs_csv: CSV file with talkgroup data
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import add_talkgroups, make_p25_group
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    # Parse CSV
    tgs = _parse_tgs_csv(tgs_csv)
    if not tgs:
        print("Error: talkgroups CSV is empty", file=sys.stderr)
        return 1

    groups = [make_p25_group(gid, sn, ln, tx=tx, scan=scan)
              for gid, sn, ln, tx, scan in tgs]

    add_talkgroups(prs, set_name, groups)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Added {len(tgs)} talkgroups to set '{set_name}' in {out_path}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_merge(target_path, source_path, include_systems=True,
              include_channels=True, output=None):
    """Merge systems and channels from source PRS into target PRS.

    Copies P25 trunked systems (with their trunk sets, group sets, IDEN sets)
    and conventional systems (with their conv sets) from source into target.
    Skips systems that already exist in target (by short name).

    Args:
        target_path: target PRS file path
        source_path: source PRS file path
        include_systems: if True, merge P25 trunked systems
        include_channels: if True, merge conventional systems
        output: output file path (default: overwrite target)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import merge_prs
    from .prs_writer import write_prs

    target = parse_prs(target_path)
    source = parse_prs(source_path)

    stats = merge_prs(target, source,
                      include_systems=include_systems,
                      include_channels=include_channels)

    # Validate
    issues = validate_prs(target)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or target_path
    write_prs(target, out_path, backup=(out_path == target_path))

    # Print summary
    total_added = stats['p25_added'] + stats['conv_added']
    total_skipped = stats['p25_skipped'] + stats['conv_skipped']

    print(f"Merged {source_path} into {out_path}")
    if stats['p25_added'] or stats['p25_skipped']:
        print(f"  P25 systems: {stats['p25_added']} added, "
              f"{stats['p25_skipped']} skipped")
    if stats['conv_added'] or stats['conv_skipped']:
        print(f"  Conv systems: {stats['conv_added']} added, "
              f"{stats['conv_skipped']} skipped")
    if total_added == 0 and total_skipped == 0:
        print("  No systems found in source to merge.")

    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_clone(target_path, source_path, system_name, output=None):
    """Clone a specific system from source PRS into target PRS.

    Copies exactly one system by its long name (from parse_system_long_name),
    including its associated trunk set, group set, IDEN set, and conv set.

    Args:
        target_path: target PRS file path (receives data)
        source_path: source PRS file path (provides data)
        system_name: the system's long display name
        output: output file path (default: overwrite target)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import clone_system
    from .prs_writer import write_prs

    target = parse_prs(target_path)
    source = parse_prs(source_path)

    try:
        result = clone_system(target, source, system_name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if result['system'] is None:
        print(f"System '{system_name}' already exists in target "
              f"or was not cloned.")
        return 0

    # Validate
    issues = validate_prs(target)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or target_path
    write_prs(target, out_path, backup=(out_path == target_path))

    # Print summary
    print(f"Cloned '{system_name}' from {source_path} into {out_path}")
    parts = []
    if result['trunk_set']:
        parts.append(f"trunk set '{result['trunk_set']}'")
    if result['group_set']:
        parts.append(f"group set '{result['group_set']}'")
    if result['iden_set']:
        parts.append(f"IDEN set '{result['iden_set']}'")
    if result['conv_set']:
        parts.append(f"conv set '{result['conv_set']}'")
    if parts:
        print(f"  Copied: {', '.join(parts)}")
    else:
        print("  Sets already existed in target (system config only)")

    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_clone_personality(filepath, output, name=None, remove_sets=None,
                          remove_systems=None, enable_tx=None,
                          disable_tx=None, unit_id=None, password=None):
    """Create a modified clone of a PRS personality.

    Args:
        filepath: source PRS file
        output: output file path (required)
        name: new personality name
        remove_sets: list of set names to remove
        remove_systems: list of system long names to remove
        enable_tx: list of set names to enable TX on
        disable_tx: list of set names to disable TX on
        unit_id: new unit ID
        password: new radio password

    Returns:
        0 on success, 1 on error.
    """
    from .cloner import clone_personality
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    mods = {}
    if name:
        mods['name'] = name
    if remove_sets:
        mods['remove_sets'] = remove_sets
    if remove_systems:
        mods['remove_systems'] = remove_systems
    if enable_tx:
        mods['enable_tx_sets'] = enable_tx
    if disable_tx:
        mods['disable_tx_sets'] = disable_tx
    if unit_id is not None:
        mods['unit_id'] = unit_id
    if password is not None:
        mods['password'] = password

    cloned = clone_personality(prs, mods if mods else None)

    # Validate
    issues = validate_prs(cloned)
    errors = [(s, m) for s, m in issues if s == ERROR]

    write_prs(cloned, output)

    mod_summary = []
    if name:
        mod_summary.append(f"name='{name}'")
    if remove_sets:
        mod_summary.append(f"removed {len(remove_sets)} set(s)")
    if remove_systems:
        mod_summary.append(f"removed {len(remove_systems)} system(s)")
    if enable_tx:
        mod_summary.append(f"TX enabled on {len(enable_tx)} set(s)")
    if disable_tx:
        mod_summary.append(f"TX disabled on {len(disable_tx)} set(s)")
    if unit_id is not None:
        mod_summary.append(f"unit_id={unit_id}")
    if password is not None:
        mod_summary.append("password set")

    desc = ", ".join(mod_summary) if mod_summary else "exact copy"
    print(f"Cloned {filepath} -> {output} ({desc})")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_renumber(filepath, set_name=None, start=1, set_type="conv",
                 output=None):
    """Renumber channels sequentially in a PRS file.

    Args:
        filepath: PRS file path
        set_name: set to renumber (None = all)
        start: starting number
        set_type: "conv" or "group"
        output: output file (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import renumber_channels
    from .prs_writer import write_prs

    prs = parse_prs(filepath)
    count = renumber_channels(prs, set_name=set_name, start=start,
                               set_type=set_type)

    if count == 0:
        target = f"set '{set_name}'" if set_name else "any sets"
        print(f"No channels found in {target}")
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))
    target = f"set '{set_name}'" if set_name else "all sets"
    print(f"Renumbered {count} channels in {target} "
          f"(starting at {start}) in {out_path}")
    return 0


def cmd_auto_name(filepath, set_name, style="compact", output=None):
    """Auto-generate talkgroup short names from long names.

    Args:
        filepath: PRS file path
        set_name: group set name to rename
        style: "compact", "numbered", or "department"
        output: output file (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import auto_name_talkgroups
    from .prs_writer import write_prs

    prs = parse_prs(filepath)
    count = auto_name_talkgroups(prs, set_name, style=style)

    if count == 0:
        print(f"No talkgroups found in set '{set_name}' or set not found")
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))
    print(f"Auto-named {count} talkgroups in set '{set_name}' "
          f"(style: {style}) in {out_path}")
    return 0


def cmd_export_json(filepath, output=None, compact=False):
    """Export a PRS file to structured JSON.

    Args:
        filepath: input PRS file path
        output: output JSON file path (default: same name with .json)
        compact: if True, write compact single-line JSON

    Returns:
        0 on success, 1 on error.
    """
    from .json_io import prs_to_dict, dict_to_json

    prs = parse_prs(filepath)
    d = prs_to_dict(prs)
    text = dict_to_json(d, compact=compact)

    if output is None:
        output = Path(filepath).with_suffix('.json')

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding='utf-8')

    # Summary
    n_sys = len(d.get("systems", []))
    n_trk = sum(len(ts.get("channels", []))
                for ts in d.get("trunk_sets", []))
    n_grp = sum(len(gs.get("groups", []))
                for gs in d.get("group_sets", []))
    n_conv = sum(len(cs.get("channels", []))
                 for cs in d.get("conv_sets", []))
    n_iden = len(d.get("iden_sets", []))

    print(f"Exported: {out}")
    print(f"  Systems: {n_sys}")
    parts = []
    if n_trk:
        parts.append(f"{n_trk} trunk freqs")
    if n_grp:
        parts.append(f"{n_grp} talkgroups")
    if n_conv:
        parts.append(f"{n_conv} conv channels")
    if n_iden:
        parts.append(f"{n_iden} IDEN sets")
    if parts:
        print(f"  Data: {', '.join(parts)}")
    return 0


def cmd_import_json(filepath, output=None):
    """Import a JSON file and create a PRS file.

    Args:
        filepath: input JSON file path
        output: output PRS file path (default: same name with .PRS)

    Returns:
        0 on success, 1 on error.
    """
    from .json_io import json_to_dict, dict_to_prs

    d = json_to_dict(filepath)
    prs = dict_to_prs(d)

    if output is None:
        output = Path(filepath).with_suffix('.PRS')

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = prs.to_bytes()
    out.write_bytes(raw)

    print(f"Created: {out}")
    print(f"  Size: {len(raw):,} bytes")
    print(f"  Sections: {len(prs.sections)}")

    # Validate
    from .validation import validate_prs, ERROR
    issues = validate_prs(prs)
    errors = [m for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors")
        for msg in errors[:5]:
            print(f"    [ERROR] {msg}")
    else:
        warnings = [m for s, m in issues if s not in (ERROR,)]
        print(f"  Validation: OK ({len(warnings)} warnings)")

    return 0


def cmd_build(config_path, output=None):
    """Build a complete PRS file from an INI config file.

    Args:
        config_path: path to the .ini config file
        output: output PRS file path (default: same name with .PRS)

    Returns:
        0 on success, 1 on error.
    """
    from .config_builder import build_from_config, ConfigError

    config_path = Path(config_path)
    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        return 1

    if output is None:
        output = config_path.with_suffix('.PRS')

    try:
        prs = build_from_config(str(config_path))
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = prs.to_bytes()
    out.write_bytes(raw)

    print(f"Built: {out}")
    print(f"  Size: {len(raw):,} bytes")
    print(f"  Sections: {len(prs.sections)}")

    # Validate
    from .validation import validate_prs as _validate_prs
    issues = _validate_prs(prs)
    errors = [m for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for msg in errors[:5]:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [m for s, m in issues if s not in (ERROR,)]
        print(f"  Validation: OK ({len(warnings)} warnings)")

    return 0


def cmd_export_config(filepath, output=None):
    """Export a PRS file as an INI config file.

    The exported config can be edited and rebuilt with ``quickprs build``.

    Args:
        filepath: path to the PRS file
        output: output .ini file path (default: same name with .ini)

    Returns:
        0 on success, 1 on error.
    """
    from .config_builder import export_config

    filepath = Path(filepath)
    if not filepath.exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        return 1

    if output is None:
        output = filepath.with_suffix('.ini')

    try:
        prs = parse_prs(str(filepath))
        result_path = export_config(prs, str(output),
                                    source_path=str(filepath))
        print(f"Exported config: {result_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_profiles(subcmd, profile_name=None, output=None):
    """List or build from profile templates.

    Args:
        subcmd: 'list' or 'build'
        profile_name: profile name (for 'build')
        output: output PRS path (for 'build')

    Returns:
        0 on success, 1 on error.
    """
    from .profile_templates import (
        list_profile_templates, build_from_profile,
    )

    if subcmd == "list":
        profiles = list_profile_templates()
        if not profiles:
            print("No profile templates available.")
            return 0
        print("Available profile templates:\n")
        for name, desc in profiles:
            print(f"  {name:20s}  {desc}")
        print(f"\nUse 'quickprs profiles build <name>' to create a PRS.")
        return 0

    elif subcmd == "build":
        if not profile_name:
            print("Error: profile name required", file=sys.stderr)
            return 1

        try:
            prs = build_from_profile(profile_name)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if output is None:
            output = f"{profile_name.upper()}.PRS"

        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = prs.to_bytes()
        out.write_bytes(raw)

        print(f"Built: {out}")
        print(f"  Profile: {profile_name}")
        print(f"  Size: {len(raw):,} bytes")
        print(f"  Sections: {len(prs.sections)}")

        # Validate
        from .validation import validate_prs as _validate_prs
        issues = _validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        if errors:
            print(f"  Validation: {len(errors)} errors", file=sys.stderr)
            for msg in errors[:5]:
                print(f"    [ERROR] {msg}", file=sys.stderr)
            return 1
        else:
            warnings = [m for s, m in issues if s not in (ERROR,)]
            print(f"  Validation: OK ({len(warnings)} warnings)")

        return 0

    print(f"Error: unknown profiles subcommand: {subcmd}", file=sys.stderr)
    return 1


def cmd_fleet(config_path, units_csv, output_dir=None):
    """Build PRS files for a fleet of radios from a single config.

    Creates one PRS per row in the units CSV, each with a unique Home Unit ID
    and optional per-radio name and password.

    Args:
        config_path: path to the .ini config file
        units_csv: path to the units CSV (columns: unit_id, name, password)
        output_dir: output directory (default: fleet_output/)

    Returns:
        0 on success, 1 on error.
    """
    from .fleet import build_fleet

    config_path = Path(config_path)
    units_csv = Path(units_csv)

    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        return 1
    if not units_csv.exists():
        print(f"Error: units CSV not found: {units_csv}", file=sys.stderr)
        return 1

    if output_dir is None:
        output_dir = "fleet_output"
    output_dir = Path(output_dir)

    try:
        results = build_fleet(str(config_path), str(units_csv),
                              str(output_dir))
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Report results
    success = sum(1 for _, _, ok, _ in results if ok)
    failed = sum(1 for _, _, ok, _ in results if not ok)

    print(f"Fleet build: {success} succeeded, {failed} failed "
          f"({len(results)} total)")
    print(f"Output: {output_dir}/")

    for filepath, unit_id, ok, err in results:
        if ok:
            size = Path(filepath).stat().st_size
            print(f"  [{unit_id}] {Path(filepath).name} ({size:,} bytes)")
        else:
            print(f"  [{unit_id}] FAILED: {err}", file=sys.stderr)

    return 1 if failed > 0 else 0


def cmd_create(output_path, name=None, author=""):
    """Create a new blank PRS file.

    Args:
        output_path: path for the output .PRS file
        name: personality name (defaults to output filename)
        author: saved-by field (default empty)

    Returns:
        0 on success, 1 on error.
    """
    from .builder import create_blank_prs

    out = Path(output_path)
    filename = name if name else out.name
    prs = create_blank_prs(filename=filename, saved_by=author)
    raw = prs.to_bytes()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)

    print(f"Created: {out}")
    print(f"Size: {len(raw):,} bytes")
    print(f"Sections: {len(prs.sections)}")
    return 0


def cmd_remove(filepath, remove_type, name, output=None):
    """Remove a system or data set from a PRS file.

    Args:
        filepath: input PRS file
        remove_type: one of "system", "trunk-set", "group-set", "conv-set"
        name: the name of the item to remove
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import (
        remove_system_config, remove_trunk_set, remove_group_set,
        remove_conv_set, remove_wan_entry,
    )
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    if remove_type == "system":
        removed = remove_system_config(prs, name)
        if removed:
            # Also try to clean up WAN entry for this system
            remove_wan_entry(prs, name)
        label = f"system '{name}'"
    elif remove_type == "trunk-set":
        removed = remove_trunk_set(prs, name)
        label = f"trunk set '{name}'"
    elif remove_type == "group-set":
        removed = remove_group_set(prs, name)
        label = f"group set '{name}'"
    elif remove_type == "conv-set":
        removed = remove_conv_set(prs, name)
        label = f"conv set '{name}'"
    else:
        print(f"Error: unknown remove type '{remove_type}'", file=sys.stderr)
        return 1

    if not removed:
        print(f"Error: {label} not found in {filepath}", file=sys.stderr)
        return 1

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Removed {label} from {out_path}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_edit(filepath, name=None, author=None,
             rename_set_type=None, rename_old=None, rename_new=None,
             output=None):
    """Edit personality metadata or rename a data set.

    Args:
        filepath: input PRS file
        name: new personality filename (None = don't change)
        author: new saved-by field (None = don't change)
        rename_set_type: set type to rename ("trunk", "group", "conv")
        rename_old: current set name
        rename_new: new set name
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .injector import (
        edit_personality, rename_trunk_set, rename_group_set, rename_conv_set,
    )
    from .prs_writer import write_prs

    prs = parse_prs(filepath)
    changes = []

    # Edit personality fields
    if name is not None or author is not None:
        changed = edit_personality(prs, filename=name, saved_by=author)
        if changed:
            if name is not None:
                changes.append(f"name='{name}'")
            if author is not None:
                changes.append(f"author='{author}'")

    # Rename set
    if rename_set_type and rename_old and rename_new:
        rename_new = rename_new[:8]
        if rename_set_type == "trunk":
            renamed = rename_trunk_set(prs, rename_old, rename_new)
        elif rename_set_type == "group":
            renamed = rename_group_set(prs, rename_old, rename_new)
        elif rename_set_type == "conv":
            renamed = rename_conv_set(prs, rename_old, rename_new)
        else:
            print(f"Error: unknown set type '{rename_set_type}'",
                  file=sys.stderr)
            return 1

        if not renamed:
            print(f"Error: {rename_set_type} set '{rename_old}' not found",
                  file=sys.stderr)
            return 1
        changes.append(
            f"renamed {rename_set_type} set '{rename_old}' -> '{rename_new}'")

    if not changes:
        print("No changes specified.", file=sys.stderr)
        return 1

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Edited {out_path}: {', '.join(changes)}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_set_option(filepath, option_path=None, value=None, list_opts=False,
                   output=None):
    """Get or set a platformConfig XML option in a PRS file.

    Args:
        filepath: input PRS file
        option_path: "section.attribute" (e.g. "gps.gpsMode")
        value: new value to set (None = show current value)
        list_opts: if True, list all available options
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    if list_opts:
        options = list_platform_options(prs)
        if not options:
            print("No platformConfig found in this file.", file=sys.stderr)
            return 1

        current_section = None
        for friendly, element, attr, val in options:
            section_label = friendly
            if section_label != current_section:
                if current_section is not None:
                    print()
                print(f"[{section_label}]")
                current_section = section_label
            print(f"  {friendly}.{attr} = {val}")
        return 0

    if not option_path:
        print("Error: specify section.attribute or use --list",
              file=sys.stderr)
        return 1

    # Parse option path
    parts = option_path.split('.', 1)
    if len(parts) != 2:
        print(f"Error: option path must be section.attribute, "
              f"got '{option_path}'", file=sys.stderr)
        print(f"Available sections: {', '.join(sorted(SECTION_MAP.keys()))}",
              file=sys.stderr)
        return 1

    section, attr = parts

    if value is None:
        # Read-only mode: show current value
        config = extract_platform_config(prs)
        if config is None:
            print("No platformConfig found in this file.", file=sys.stderr)
            return 1
        xml_element = SECTION_MAP.get(section, section)
        elem_config = config.get(xml_element)
        if elem_config is None:
            print(f"Error: section '{xml_element}' not found",
                  file=sys.stderr)
            return 1
        cur_val = elem_config.get(attr)
        if cur_val is None:
            print(f"Error: attribute '{attr}' not found in {xml_element}",
                  file=sys.stderr)
            return 1
        print(f"{section}.{attr} = {cur_val}")
        return 0

    # Set mode
    try:
        set_platform_option(prs, section, attr, value)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Set {section}.{attr} = {value} in {out_path}")
    return 0


def cmd_import_rr(filepath, sid=None, url=None, username=None, apikey=None,
                   categories=None, tags=None, output=None):
    """Import a P25 trunked system from RadioReference and inject into PRS.

    Args:
        filepath: input PRS file
        sid: RadioReference system ID (int)
        url: RadioReference system URL (alternative to sid)
        username: RadioReference username
        apikey: RadioReference API key
        categories: comma-separated category IDs to include (None = all)
        tags: comma-separated service tags to include (None = all)
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .radioreference import (
        HAS_ZEEP, parse_rr_url, RadioReferenceAPI,
        build_injection_data, build_standard_iden_entries,
        make_set_name,
    )
    from .injector import (
        add_p25_trunked_system,
        make_trunk_set, make_group_set, make_iden_set,
    )
    from .record_types import P25TrkSystemConfig
    from .prs_writer import write_prs

    # Check zeep availability
    if not HAS_ZEEP:
        print("Error: zeep library required for RadioReference API.\n"
              "Install with: pip install zeep", file=sys.stderr)
        return 1

    # Resolve system ID
    if sid is None and url is not None:
        sid = parse_rr_url(url)
        if sid is None:
            print(f"Error: cannot parse system ID from URL: {url}",
                  file=sys.stderr)
            return 1
    if sid is None:
        print("Error: --sid or --url is required", file=sys.stderr)
        return 1

    # Fetch system from API
    print(f"Fetching system {sid} from RadioReference...")
    try:
        api = RadioReferenceAPI(username, apikey, apikey)
        rr_system = api.get_system(sid)
    except (ImportError, ConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not rr_system.name:
        print(f"Error: no system found for SID {sid}", file=sys.stderr)
        return 1

    # Parse filter options
    selected_cats = None
    if categories:
        selected_cats = set()
        for c in categories.split(','):
            c = c.strip()
            if c:
                try:
                    selected_cats.add(int(c))
                except ValueError:
                    print(f"Warning: ignoring non-integer category: {c}",
                          file=sys.stderr)

    selected_tags = None
    if tags:
        selected_tags = {t.strip() for t in tags.split(',') if t.strip()}

    # Build injection data
    data = build_injection_data(rr_system, selected_cats, selected_tags)
    set_name = data['system_name']
    if not set_name:
        set_name = f"SID{sid}"[:8]

    prs = parse_prs(filepath)

    # Build trunk set from frequencies
    trunk_set = None
    if data['frequencies']:
        trunk_set = make_trunk_set(set_name, data['frequencies'])

    # Build group set from talkgroups
    group_set = None
    if data['talkgroups']:
        group_set = make_group_set(set_name, data['talkgroups'])

    # Build IDEN set from auto-detected entries
    iden_set = None
    if data.get('iden_entries'):
        iden_set = make_iden_set(set_name[:5], data['iden_entries'])

    # Convert hex sysid/wacn to int
    sysid_int = 0
    if data['sysid']:
        try:
            sysid_int = int(data['sysid'], 16)
        except ValueError:
            sysid_int = 0

    wacn_int = 0
    if data['wacn']:
        try:
            wacn_int = int(data['wacn'], 16)
        except ValueError:
            wacn_int = 0

    # Detect IDEN params for WAN config
    wan_base = 851_006_250
    wan_spacing = 6250
    if data.get('iden_entries'):
        first_iden = data['iden_entries'][0]
        wan_base = first_iden.get('base_freq_hz', wan_base)
        wan_spacing = first_iden.get('chan_spacing_hz', wan_spacing)

    # Build system config
    long_name = (data.get('full_name') or set_name)[:16].upper()
    config = P25TrkSystemConfig(
        system_name=set_name,
        long_name=long_name,
        trunk_set_name=set_name if trunk_set else "",
        group_set_name=set_name if group_set else "",
        wan_name=set_name,
        system_id=sysid_int,
        wacn=wacn_int,
        iden_set_name=set_name[:5] if iden_set else "",
        wan_base_freq_hz=wan_base,
        wan_chan_spacing_hz=wan_spacing,
    )

    add_p25_trunked_system(prs, config,
                           trunk_set=trunk_set,
                           group_set=group_set,
                           iden_set=iden_set)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    # Print summary
    n_tgs = len(data['talkgroups'])
    n_freqs = len(data['frequencies'])
    n_sites = len(data.get('sites', []))
    print(f"Imported '{rr_system.name}' (SID {sid}) into {out_path}")
    print(f"  System ID: {data['sysid']}  WACN: {data['wacn']}")
    print(f"  Talkgroups: {n_tgs}  Frequencies: {n_freqs}  Sites: {n_sites}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_import_paste(filepath, name, sysid, wacn=0, long_name=None,
                     tgs_file=None, freqs_file=None, output=None):
    """Import a P25 system from pasted RadioReference text files.

    Args:
        filepath: input PRS file
        name: system short name (8 chars max)
        sysid: P25 System ID (decimal int)
        wacn: WACN (decimal int, default 0)
        long_name: long display name (16 chars max)
        tgs_file: text file with pasted talkgroup table
        freqs_file: text file with pasted frequency/site table
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .radioreference import (
        parse_pasted_talkgroups, parse_pasted_frequencies,
        make_short_name, make_long_name,
        build_standard_iden_entries,
    )
    from .injector import (
        add_p25_trunked_system,
        make_trunk_set, make_group_set, make_iden_set,
        make_p25_group,
    )
    from .record_types import P25TrkSystemConfig
    from .prs_writer import write_prs

    name = name[:8]
    if not long_name:
        long_name = name
    long_name = long_name[:16]

    if not tgs_file and not freqs_file:
        print("Error: at least one of --tgs-file or --freqs-file is required",
              file=sys.stderr)
        return 1

    prs = parse_prs(filepath)

    # Parse talkgroups from pasted text
    group_set = None
    tg_count = 0
    if tgs_file:
        tgs_path = Path(tgs_file)
        if not tgs_path.exists():
            print(f"Error: talkgroups file not found: {tgs_file}",
                  file=sys.stderr)
            return 1
        tgs_text = tgs_path.read_text(encoding='utf-8')
        rr_tgs = parse_pasted_talkgroups(tgs_text)
        if not rr_tgs:
            print("Error: no talkgroups found in pasted text",
                  file=sys.stderr)
            return 1

        # Convert RRTalkgroup objects to injection tuples
        talkgroups = []
        for tg in rr_tgs:
            if tg.dec_id <= 0 or tg.dec_id > 65535:
                continue
            short = make_short_name(tg.alpha_tag)
            long = make_long_name(tg.description, tg.alpha_tag)
            talkgroups.append((tg.dec_id, short, long))

        if talkgroups:
            group_set = make_group_set(name, talkgroups)
            tg_count = len(talkgroups)
            print(f"  Talkgroups: {tg_count} from {tgs_file}")

    # Parse frequencies from pasted text
    trunk_set = None
    freq_count = 0
    all_rx_freqs = []
    if freqs_file:
        freqs_path = Path(freqs_file)
        if not freqs_path.exists():
            print(f"Error: frequencies file not found: {freqs_file}",
                  file=sys.stderr)
            return 1
        freqs_text = freqs_path.read_text(encoding='utf-8')
        freqs = parse_pasted_frequencies(freqs_text)
        if not freqs:
            print("Error: no frequencies found in pasted text",
                  file=sys.stderr)
            return 1

        trunk_set = make_trunk_set(name, freqs)
        freq_count = len(freqs)
        all_rx_freqs = [rx for _, rx in freqs]
        print(f"  Frequencies: {freq_count} from {freqs_file}")

    # Build IDEN set
    iden_set = None
    wan_base = 851_006_250
    wan_spacing = 6250
    if all_rx_freqs:
        iden_entries = build_standard_iden_entries(sorted(all_rx_freqs))
        if iden_entries:
            iden_set = make_iden_set(name[:5], iden_entries)
            wan_base = iden_entries[0].get('base_freq_hz', wan_base)
            wan_spacing = iden_entries[0].get('chan_spacing_hz', wan_spacing)

    # Build system config
    config = P25TrkSystemConfig(
        system_name=name,
        long_name=long_name,
        trunk_set_name=name if trunk_set else "",
        group_set_name=name if group_set else "",
        wan_name=name,
        system_id=sysid,
        wacn=wacn,
        iden_set_name=name[:5] if iden_set else "",
        wan_base_freq_hz=wan_base,
        wan_chan_spacing_hz=wan_spacing,
    )

    add_p25_trunked_system(prs, config,
                           trunk_set=trunk_set,
                           group_set=group_set,
                           iden_set=iden_set)

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Injected P25 system '{name}' (SysID {sysid}) into {out_path}")
    print(f"  Talkgroups: {tg_count}  Frequencies: {freq_count}")
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_repair(filepath, output=None, salvage=False):
    """Repair a damaged PRS file or extract salvageable data.

    Args:
        filepath: path to the damaged PRS file
        output: output path (default: overwrite input)
        salvage: if True, extract data from badly damaged files
                 instead of attempting repair
    """
    from .prs_writer import write_prs
    from .repair import repair_prs, extract_salvageable_data
    from .validation import validate_structure

    if salvage:
        print(f"Salvaging data from: {filepath}")
        result = extract_salvageable_data(filepath)

        if result['personality']:
            p = result['personality']
            print(f"\nPersonality: {p.get('filename', '?')}")
            if p.get('saved_by'):
                print(f"  Author: {p['saved_by']}")

        if result['systems']:
            print(f"\nSystems ({len(result['systems'])}):")
            for sys_info in result['systems']:
                print(f"  {sys_info.get('long_name', '?')}")

        if result['group_sets']:
            total = sum(len(gs.groups) for gs in result['group_sets'])
            print(f"\nGroup Sets ({len(result['group_sets'])}): "
                  f"{total} talkgroups")
            for gs in result['group_sets']:
                print(f"  {gs.name}: {len(gs.groups)} TGs")

        if result['trunk_sets']:
            total = sum(len(ts.channels) for ts in result['trunk_sets'])
            print(f"\nTrunk Sets ({len(result['trunk_sets'])}): "
                  f"{total} frequencies")
            for ts in result['trunk_sets']:
                print(f"  {ts.name}: {len(ts.channels)} freqs")

        if result['conv_sets']:
            total = sum(len(cs.channels) for cs in result['conv_sets'])
            print(f"\nConv Sets ({len(result['conv_sets'])}): "
                  f"{total} channels")
            for cs in result['conv_sets']:
                print(f"  {cs.name}: {len(cs.channels)} channels")

        if result['iden_sets']:
            print(f"\nIDEN Sets ({len(result['iden_sets'])}):")
            for iset in result['iden_sets']:
                active = sum(1 for e in iset.elements
                             if not e.is_empty())
                print(f"  {iset.name}: {active}/16 active")

        print(f"\nSections found: {len(result['sections'])}")

        if result['errors']:
            print(f"\nRecovery errors ({len(result['errors'])}):")
            for err in result['errors']:
                print(f"  {err}")

        return 0

    # Normal repair mode
    print(f"Repairing: {filepath}")
    try:
        prs = parse_prs(filepath)
    except ValueError as e:
        print(f"Cannot parse file: {e}", file=sys.stderr)
        print("Try --salvage to extract what data is readable.",
              file=sys.stderr)
        return 1

    # Check structural issues first
    issues = validate_structure(prs)
    if not issues:
        print("No structural issues found — file is already valid.")
        return 0

    print(f"Found {len(issues)} structural issues:")
    for sev, msg in issues:
        print(f"  [{sev}] {msg}")
    print()

    # Attempt repair
    prs, repairs = repair_prs(prs)

    if not repairs:
        print("No automatic repairs were possible.")
        return 1

    print(f"Repairs applied ({len(repairs)}):")
    for r in repairs:
        print(f"  {r}")

    # Validate after repair
    post_issues = validate_structure(prs)
    if post_issues:
        print(f"\nRemaining issues after repair ({len(post_issues)}):")
        for sev, msg in post_issues:
            print(f"  [{sev}] {msg}")
    else:
        print("\nStructural validation: PASS")

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))
    print(f"\nRepaired file written to: {out_path}")
    return 0


def cmd_capacity(filepath):
    """Show capacity report for a PRS file."""
    from .validation import estimate_capacity, format_capacity

    prs = parse_prs(filepath)
    cap = estimate_capacity(prs)
    lines = format_capacity(cap, filename=Path(filepath).name)
    print("\n".join(lines))
    return 0


def cmd_report(filepath, output=None):
    """Generate an HTML report of the radio configuration.

    Args:
        filepath: PRS file path
        output: output HTML path (default: same name with .html extension)

    Returns:
        0 on success, 1 on error.
    """
    from .reports import generate_html_report

    prs = parse_prs(filepath)
    if output is None:
        output = str(Path(filepath).with_suffix('.html'))

    generate_html_report(prs, filepath=output, source_path=filepath)
    print(f"Report written to: {output}")
    return 0


def cmd_zones(filepath, strategy="auto", export=None):
    """Generate a zone plan for a PRS file.

    Args:
        filepath: PRS file path
        strategy: zone planning strategy (auto, by_set, combined, manual)
        export: if given, export zone plan to this CSV path

    Returns:
        0 on success, 1 on error.
    """
    from .zones import (
        plan_zones, format_zone_plan, validate_zone_plan,
        export_zone_plan_csv,
    )

    prs = parse_prs(filepath)
    zones = plan_zones(prs, strategy=strategy)
    issues = validate_zone_plan(zones)

    # Print the zone plan
    lines = format_zone_plan(zones)
    for line in lines:
        print(line)

    # Print any validation issues
    if issues:
        print("")
        for severity, msg in issues:
            tag = severity.upper()
            print(f"  [{tag}] {msg}")

    # Export to CSV if requested
    if export:
        export_zone_plan_csv(zones, export)
        print(f"\nZone plan exported to: {export}")

    return 0


def cmd_stats(filepath):
    """Show personality statistics.

    Args:
        filepath: PRS file path

    Returns:
        0 on success, 1 on error.
    """
    from .validation import compute_statistics, format_statistics

    prs = parse_prs(filepath)
    stats = compute_statistics(prs)
    lines = format_statistics(stats, filename=Path(filepath).name)
    print("\n".join(lines))
    return 0


def cmd_card(filepath, output=None):
    """Generate a compact summary card for a PRS file.

    Args:
        filepath: PRS file path
        output: output HTML path (default: same name with _card.html)

    Returns:
        0 on success, 1 on error.
    """
    from .reports import generate_summary_card

    prs = parse_prs(filepath)
    if output is None:
        stem = Path(filepath).stem
        output = str(Path(filepath).parent / f"{stem}_card.html")

    generate_summary_card(prs, filepath=output, source_path=filepath)
    print(f"Summary card written to: {output}")
    return 0


def cmd_list(filepath, list_type):
    """List specific data types from a PRS file in machine-parseable format.

    Each list type prints one item per line with tab-separated fields.

    Args:
        filepath: PRS file path
        list_type: one of 'systems', 'talkgroups', 'channels',
                   'frequencies', 'sets', 'options'

    Returns:
        0 on success, 1 on error.
    """
    prs = parse_prs(filepath)

    if list_type == "systems":
        system_types = [
            ('CP25TrkSystem', 'P25 Trunked'),
            ('CConvSystem', 'Conventional'),
            ('CP25ConvSystem', 'P25 Conv'),
        ]
        for cls, label in system_types:
            secs = prs.get_sections_by_class(cls)
            for sec in secs:
                short = parse_system_short_name(sec.raw) or "?"
                print(f"{short}\t{label}")

    elif list_type == "talkgroups":
        sets = _parse_group_sets(prs)
        for gs in sets:
            for grp in gs.groups:
                scan = "Y" if grp.scan else "N"
                tx = "Y" if grp.tx else "N"
                print(f"{gs.name}\t{grp.group_id}\t{grp.group_name}\t"
                      f"{grp.long_name}\tscan={scan}\ttx={tx}")

    elif list_type == "channels":
        conv_sets = _parse_conv_sets(prs)
        for cs in conv_sets:
            for ch in cs.channels:
                tone = ""
                if ch.tx_tone:
                    tone = f"tone={ch.tx_tone}"
                print(f"{cs.name}\t{ch.short_name}\t"
                      f"{ch.tx_freq:.4f}\t{ch.rx_freq:.4f}\t{tone}")

    elif list_type == "frequencies":
        sets = _parse_trunk_sets(prs)
        for ts in sets:
            for ch in ts.channels:
                print(f"{ts.name}\t{ch.tx_freq:.4f}\t{ch.rx_freq:.4f}")

    elif list_type == "sets":
        for kind, parser_fn in [("group", _parse_group_sets),
                                ("trunk", _parse_trunk_sets),
                                ("conv", _parse_conv_sets),
                                ("iden", _parse_iden_sets)]:
            for s in parser_fn(prs):
                items = len(s.groups) if kind == "group" else (
                    len(s.channels) if kind in ("trunk", "conv") else
                    len([e for e in s.elements if not e.is_empty()]))
                print(f"{kind}\t{s.name}\t{items}")

    elif list_type == "options":
        opts = list_platform_options(prs)
        for entry in opts:
            # (section_friendly, element_name, attr_name, value)
            friendly, elem, attr, val = entry
            print(f"{friendly}.{attr}\t{val}")

    else:
        print(f"Unknown list type: {list_type}", file=sys.stderr)
        return 1

    return 0


def cmd_bulk_edit_talkgroups(filepath, set_name, enable_scan=None,
                              disable_scan=None, enable_tx=None,
                              disable_tx=None, prefix=None, suffix=None,
                              output=None):
    """Bulk-edit talkgroups in a group set.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import bulk_edit_talkgroups
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    # Resolve scan flag
    scan_flag = None
    if enable_scan:
        scan_flag = True
    elif disable_scan:
        scan_flag = False

    # Resolve TX flag
    tx_flag = None
    if enable_tx:
        tx_flag = True
    elif disable_tx:
        tx_flag = False

    try:
        count = bulk_edit_talkgroups(prs, set_name,
                                      enable_scan=scan_flag,
                                      enable_tx=tx_flag,
                                      prefix=prefix,
                                      suffix=suffix)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Bulk-edited {count} talkgroups in set '{set_name}' "
          f"-> {out_path}")

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_bulk_edit_channels(filepath, set_name, set_tone=None,
                            clear_tones=False, set_power=None,
                            output=None):
    """Bulk-edit conventional channels in a conv set.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import bulk_edit_channels
    from .prs_writer import write_prs

    prs = parse_prs(filepath)

    try:
        count = bulk_edit_channels(prs, set_name,
                                    set_tone=set_tone,
                                    clear_tones=clear_tones,
                                    set_power=set_power)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Bulk-edited {count} channels in set '{set_name}' "
          f"-> {out_path}")

    # Validate
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_encrypt(filepath, set_name, tg_id=None, encrypt_all=False,
                key_id=0, decrypt=False, output=None):
    """Set encryption on P25 talkgroups.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import set_talkgroup_encryption
    from .prs_writer import write_prs

    if tg_id is None and not encrypt_all:
        print("Error: specify --tg ID or --all", file=sys.stderr)
        return 1

    prs = parse_prs(filepath)

    encrypted = not decrypt
    group_id = tg_id  # None means all

    try:
        count = set_talkgroup_encryption(prs, set_name,
                                          group_id=group_id,
                                          encrypted=encrypted,
                                          key_id=key_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    action = "Encrypted" if encrypted else "Decrypted"
    target = f"TG {tg_id}" if tg_id else f"{count} TGs"
    print(f"{action} {target} in set '{set_name}' "
          f"(key_id={key_id}) -> {out_path}")

    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_set_nac(filepath, set_name, channel=0, nac="293", nac_rx=None,
                output=None):
    """Set NAC on a P25 conventional channel.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import set_p25_conv_nac
    from .prs_writer import write_prs

    try:
        nac_tx_val = int(nac, 16)
    except ValueError:
        print(f"Error: invalid NAC value '{nac}' (must be hex)", file=sys.stderr)
        return 1

    nac_rx_val = None
    if nac_rx is not None:
        try:
            nac_rx_val = int(nac_rx, 16)
        except ValueError:
            print(f"Error: invalid NAC RX value '{nac_rx}'", file=sys.stderr)
            return 1
    else:
        nac_rx_val = nac_tx_val  # Same TX and RX by default

    prs = parse_prs(filepath)

    try:
        set_p25_conv_nac(prs, set_name, channel,
                          nac_tx=nac_tx_val, nac_rx=nac_rx_val)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Set NAC on channel {channel} in '{set_name}' "
          f"(TX:{nac_tx_val:03X} RX:{nac_rx_val:03X}) -> {out_path}")

    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_rename(filepath, set_name, pattern, replace,
               set_type="group", field="short_name", output=None):
    """Batch rename items in a set using regex substitution.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import batch_rename
    from .prs_writer import write_prs

    find_pattern = pattern
    replace_str = replace
    prs = parse_prs(filepath)

    try:
        count = batch_rename(prs, set_name, find_pattern, replace_str,
                              set_type=set_type, field=field)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if count == 0:
        print(f"No matches found for pattern '{find_pattern}' "
              f"in set '{set_name}'")
        return 0

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    print(f"Renamed {count} items in set '{set_name}' -> {out_path}")

    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_sort(filepath, set_name, key="frequency", set_type="conv",
             reverse=False, output=None):
    """Sort channels or talkgroups within a set.

    Returns:
        0 on success, 1 on error.
    """
    from .injector import sort_channels
    from .prs_writer import write_prs

    sort_by = key
    prs = parse_prs(filepath)

    try:
        found = sort_channels(prs, set_name, set_type=set_type,
                               key=sort_by, reverse=reverse)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not found:
        print(f"Error: set '{set_name}' not found", file=sys.stderr)
        return 1

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    order = "descending" if reverse else "ascending"
    print(f"Sorted set '{set_name}' by {sort_by} ({order}) -> {out_path}")

    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    if errors:
        print(f"  Validation: {len(errors)} errors", file=sys.stderr)
        for _, msg in errors:
            print(f"    [ERROR] {msg}", file=sys.stderr)
        return 1
    else:
        warnings = [(s, m) for s, m in issues if s == WARNING]
        print(f"  Validation: OK ({len(warnings)} warnings)")
    return 0


def cmd_freq_tools(subcmd, freq=None, freq_list=None):
    """Frequency/tone reference tool.

    Args:
        subcmd: 'offset', 'channel', 'tones', 'dcs', 'nearest',
                'identify', 'all-offsets', or 'conflicts'
        freq: frequency value (MHz) for offset/channel/nearest/identify
        freq_list: list of frequencies for conflicts check

    Returns:
        0 on success, 1 on error.
    """
    from .freq_tools import (
        format_repeater_offset, format_channel_id,
        format_ctcss_table, format_dcs_table,
        nearest_ctcss,
        format_service_id, format_all_offsets, format_conflict_check,
    )

    if subcmd == "tones":
        for line in format_ctcss_table():
            print(line)
        return 0
    elif subcmd == "dcs":
        for line in format_dcs_table():
            print(line)
        return 0
    elif subcmd == "offset":
        if freq is None:
            print("Error: frequency required for 'offset'", file=sys.stderr)
            return 1
        for line in format_repeater_offset(freq):
            print(line)
        return 0
    elif subcmd == "channel":
        if freq is None:
            print("Error: frequency required for 'channel'", file=sys.stderr)
            return 1
        for line in format_channel_id(freq):
            print(line)
        return 0
    elif subcmd == "nearest":
        if freq is None:
            print("Error: frequency required for 'nearest'", file=sys.stderr)
            return 1
        tone, diff = nearest_ctcss(freq)
        print(f"Input:   {freq:.1f} Hz")
        print(f"Nearest: {tone:.1f} Hz (diff: {diff:+.1f} Hz)")
        return 0
    elif subcmd == "identify":
        if freq is None:
            print("Error: frequency required for 'identify'",
                  file=sys.stderr)
            return 1
        for line in format_service_id(freq):
            print(line)
        return 0
    elif subcmd == "all-offsets":
        if freq is None:
            print("Error: frequency required for 'all-offsets'",
                  file=sys.stderr)
            return 1
        for line in format_all_offsets(freq):
            print(line)
        return 0
    elif subcmd == "conflicts":
        if not freq_list:
            print("Error: frequency list required for 'conflicts'",
                  file=sys.stderr)
            return 1
        for line in format_conflict_check(freq_list):
            print(line)
        return 0
    else:
        print(f"Error: unknown freq-tools subcommand: {subcmd}",
              file=sys.stderr)
        return 1


def cmd_auto_setup(filepath, sid=None, url=None, username=None, apikey=None,
                   categories=None, tags=None, output=None):
    """One-click RadioReference system setup with ECC and IDEN.

    Like import-rr but also auto-configures ECC entries and IDEN
    parameters from site control channel data.

    Args:
        filepath: input PRS file
        sid: RadioReference system ID (int)
        url: RadioReference system URL (alternative to sid)
        username: RadioReference username
        apikey: RadioReference API key
        categories: comma-separated category IDs to include (None = all)
        tags: comma-separated service tags to include (None = all)
        output: output file path (default: overwrite input)

    Returns:
        0 on success, 1 on error.
    """
    from .radioreference import HAS_ZEEP, parse_rr_url, RadioReferenceAPI
    from .auto_setup import auto_setup_from_rr
    from .prs_writer import write_prs

    # Check zeep availability
    if not HAS_ZEEP:
        print("Error: zeep library required for RadioReference API.\n"
              "Install with: pip install zeep", file=sys.stderr)
        return 1

    # Resolve system ID
    if sid is None and url is not None:
        sid = parse_rr_url(url)
        if sid is None:
            print(f"Error: cannot parse system ID from URL: {url}",
                  file=sys.stderr)
            return 1
    if sid is None:
        print("Error: --sid or --url is required", file=sys.stderr)
        return 1

    # Fetch system from API
    print(f"Fetching system {sid} from RadioReference...")
    try:
        api = RadioReferenceAPI(username, apikey, apikey)
        rr_system = api.get_system(sid)
    except (ImportError, ConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not rr_system.name:
        print(f"Error: no system found for SID {sid}", file=sys.stderr)
        return 1

    # Parse filter options
    selected_cats = None
    if categories:
        selected_cats = set()
        for c in categories.split(','):
            c = c.strip()
            if c:
                try:
                    selected_cats.add(int(c))
                except ValueError:
                    print(f"Warning: ignoring non-integer category: {c}",
                          file=sys.stderr)

    selected_tags = None
    if tags:
        selected_tags = {t.strip() for t in tags.split(',') if t.strip()}

    prs = parse_prs(filepath)

    # Run auto-setup
    summary = auto_setup_from_rr(prs, rr_system, selected_cats,
                                 selected_tags)

    out_path = output or filepath
    write_prs(prs, out_path, backup=(out_path == filepath))

    # Print summary
    print(f"Auto-setup complete: '{summary['full_name']}' (SID {sid})")
    print(f"  System ID: {summary['sysid']}  WACN: {summary['wacn']}")
    print(f"  Talkgroups:  {summary['talkgroups']}")
    print(f"  Frequencies: {summary['frequencies']}")
    print(f"  Sites:       {summary['sites']}")
    print(f"  ECC entries: {summary['ecc_entries']}")
    print(f"  IDEN entries: {summary['iden_entries']}")
    print(f"  Saved to: {out_path}")

    if summary['warnings']:
        for w in summary['warnings']:
            print(f"  Warning: {w}", file=sys.stderr)

    if summary['validation_errors'] > 0:
        print(f"  Validation: {summary['validation_errors']} errors",
              file=sys.stderr)
        return 1
    else:
        print(f"  Validation: OK "
              f"({summary['validation_warnings']} warnings)")
    return 0


def cmd_systems(subcmd, query=None, filepath=None, system_name=None,
                output=None):
    """P25 system database commands.

    Subcommands:
        list: show all known systems
        search <query>: search by name/location
        info <name>: show system details
        add <file> <name>: add system to PRS file

    Returns 0 on success, 1 on error.
    """
    from .system_database import (
        list_all_systems, search_systems, get_system_by_name,
        get_iden_template_key, get_default_iden_name,
    )

    if subcmd == "list":
        systems = list_all_systems()
        if not systems:
            print("No systems in database.")
            return 0
        print(f"{'Name':<10} {'Location':<25} {'Band':<10} "
              f"{'Type':<10} {'SysID':>6}  {'WACN':>8}")
        print("-" * 75)
        for s in systems:
            print(f"{s.name:<10} {s.location:<25} {s.band:<10} "
                  f"{s.system_type:<10} {s.system_id:>6}  {s.wacn:>8}")
        print(f"\n{len(systems)} systems in database")
        return 0

    elif subcmd == "search":
        if not query:
            print("Error: search requires a query", file=sys.stderr)
            return 1
        results = search_systems(query)
        if not results:
            print(f"No systems matching '{query}'")
            return 0
        print(f"{'Name':<10} {'Location':<25} {'Band':<10} "
              f"{'Type':<10} {'SysID':>6}")
        print("-" * 65)
        for s in results:
            print(f"{s.name:<10} {s.location:<25} {s.band:<10} "
                  f"{s.system_type:<10} {s.system_id:>6}")
        print(f"\n{len(results)} matching systems")
        return 0

    elif subcmd == "info":
        if not system_name:
            print("Error: info requires a system name", file=sys.stderr)
            return 1
        sys_obj = get_system_by_name(system_name)
        if not sys_obj:
            # Try searching
            results = search_systems(system_name)
            if len(results) == 1:
                sys_obj = results[0]
            elif results:
                print(f"Multiple matches for '{system_name}':")
                for s in results:
                    print(f"  {s.name}: {s.long_name}")
                return 1
            else:
                print(f"System '{system_name}' not found.", file=sys.stderr)
                return 1
        iden_key = get_iden_template_key(sys_obj)
        iden_name = get_default_iden_name(sys_obj)
        print(f"Name:        {sys_obj.name}")
        print(f"Full Name:   {sys_obj.long_name}")
        print(f"Location:    {sys_obj.location}")
        print(f"State:       {sys_obj.state}")
        print(f"System ID:   {sys_obj.system_id}")
        print(f"WACN:        {sys_obj.wacn}")
        print(f"Band:        {sys_obj.band}")
        print(f"Type:        {sys_obj.system_type}")
        print(f"IDEN Key:    {iden_key}")
        print(f"IDEN Name:   {iden_name}")
        if sys_obj.description:
            print(f"Description: {sys_obj.description}")
        return 0

    elif subcmd == "add":
        if not filepath:
            print("Error: add requires a PRS file path", file=sys.stderr)
            return 1
        if not system_name:
            print("Error: add requires a system name", file=sys.stderr)
            return 1

        sys_obj = get_system_by_name(system_name)
        if not sys_obj:
            results = search_systems(system_name)
            if len(results) == 1:
                sys_obj = results[0]
            elif results:
                print(f"Multiple matches for '{system_name}':")
                for s in results:
                    print(f"  {s.name}: {s.long_name}")
                return 1
            else:
                print(f"System '{system_name}' not found.", file=sys.stderr)
                return 1

        from .prs_writer import write_prs
        from .injector import (
            add_p25_trunked_system, make_iden_set,
        )
        from .record_types import P25TrkSystemConfig
        from .iden_library import get_template

        prs = parse_prs(filepath)

        name = sys_obj.name[:8]
        long_name = sys_obj.long_name[:16]
        iden_key = get_iden_template_key(sys_obj)
        iden_name = get_default_iden_name(sys_obj)

        # Build IDEN from standard template
        template = get_template(iden_key)
        iden_set = None
        wan_base = 851_006_250
        wan_spacing = 12500
        if template:
            iden_set = make_iden_set(iden_name, template.entries)
            if template.entries:
                wan_base = template.entries[0].get(
                    'base_freq_hz', wan_base)
                wan_spacing = template.entries[0].get(
                    'chan_spacing_hz', wan_spacing)

        config = P25TrkSystemConfig(
            system_name=name,
            long_name=long_name,
            trunk_set_name="",
            group_set_name="",
            wan_name=name,
            system_id=sys_obj.system_id,
            wacn=sys_obj.wacn,
            iden_set_name=iden_name if iden_set else "",
            wan_base_freq_hz=wan_base,
            wan_chan_spacing_hz=wan_spacing,
        )

        add_p25_trunked_system(prs, config, iden_set=iden_set)

        # Validate
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]

        out_path = output or filepath
        write_prs(prs, out_path, backup=(out_path == filepath))

        print(f"Added P25 system '{name}' (SysID {sys_obj.system_id}, "
              f"WACN {sys_obj.wacn}) to {out_path}")
        print(f"  IDEN: {iden_name} ({iden_key})")
        print(f"  Trunk set: empty (add frequencies later)")
        print(f"  Group set: empty (add talkgroups later)")
        if errors:
            print(f"  Validation: {len(errors)} errors", file=sys.stderr)
            for _, msg in errors:
                print(f"    [ERROR] {msg}", file=sys.stderr)
            return 1
        else:
            warnings = [(s, m) for s, m in issues if s == WARNING]
            print(f"  Validation: OK ({len(warnings)} warnings)")
        return 0

    else:
        print(f"Unknown systems subcommand: {subcmd}", file=sys.stderr)
        return 1


def cmd_cleanup(filepath, check=False, fix=False, remove_unused=False):
    """Find and fix duplicates and unused sets in a PRS file.

    Args:
        filepath: PRS file path
        check: if True, report duplicates and unused sets
        fix: if True, report what would be removed (duplicates)
        remove_unused: if True, report unused sets
    """
    from .cleanup import (
        find_duplicates, remove_duplicates,
        find_unused_sets, cleanup_report,
        format_duplicates_report, format_unused_report,
    )

    prs = parse_prs(filepath)
    print(f"File: {filepath}")
    print()

    if check or (not fix and not remove_unused):
        lines = cleanup_report(prs)
        for line in lines:
            print(line)
        return 0

    if fix:
        dupes = find_duplicates(prs)
        lines = format_duplicates_report(dupes)
        for line in lines:
            print(line)
        counts = remove_duplicates(prs)
        total = sum(counts.values())
        if total == 0:
            print("\nNo duplicates to remove.")
        else:
            print(f"\nWould remove: {counts['tgs_removed']} TGs, "
                  f"{counts['freqs_removed']} freqs, "
                  f"{counts['channels_removed']} channels")
            print("(Binary modification not yet supported — "
                  "use GUI Cleanup dialog to fix interactively)")
        return 0

    if remove_unused:
        unused = find_unused_sets(prs)
        lines = format_unused_report(unused)
        for line in lines:
            print(line)
        total = sum(len(v) for v in unused.values())
        if total == 0:
            print("\nNo unused sets to remove.")
        else:
            print(f"\n{total} unused set(s) found.")
            print("Use 'quickprs remove' to remove individual sets.")
        return 0

    return 0


def cmd_search(filepaths, freq=None, tg=None, name=None):
    """Search across multiple PRS files for data.

    Args:
        filepaths: list of PRS file paths (may include glob patterns)
        freq: frequency to search for (MHz)
        tg: talkgroup ID to search for
        name: name/string to search for
    """
    import glob as globmod

    # Expand glob patterns
    expanded = []
    for pattern in filepaths:
        matches = globmod.glob(pattern)
        if matches:
            expanded.extend(matches)
        else:
            expanded.append(pattern)

    # Filter to PRS files only
    prs_files = [f for f in expanded
                 if f.lower().endswith('.prs')]

    if not prs_files:
        print("No PRS files found.", file=sys.stderr)
        return 1

    print(f"Searching {len(prs_files)} file(s)...")
    print()

    from .search import (
        search_freq, search_talkgroup, search_name,
        format_search_results,
    )

    if freq is not None:
        results = search_freq(prs_files, freq)
        lines = format_search_results(results, 'freq')
    elif tg is not None:
        results = search_talkgroup(prs_files, tg)
        lines = format_search_results(results, 'tg')
    elif name is not None:
        results = search_name(prs_files, name)
        lines = format_search_results(results, 'name')
    else:
        print("Specify --freq, --tg, or --name", file=sys.stderr)
        return 1

    for line in lines:
        print(line)

    return 0


def cmd_template_csv(template_type, output=None):
    """Generate a blank CSV template file for user data entry.

    Produces a CSV with headers and commented example rows for the
    given data type: frequencies, talkgroups, channels, units, or config.

    Args:
        template_type: one of 'frequencies', 'talkgroups', 'channels',
                       'units', 'config'
        output: output file path (default: auto-named)

    Returns:
        0 on success, 1 on error.
    """
    templates = {
        'frequencies': {
            'default_name': 'freqs.csv',
            'content': (
                "tx_freq,rx_freq\n"
                "# Example: 851.0125,806.0125\n"
                "# One frequency pair per line\n"
            ),
        },
        'talkgroups': {
            'default_name': 'tgs.csv',
            'content': (
                "id,short_name,long_name,tx,scan\n"
                "# Example: 1000,PD DISP,Police Dispatch,false,true\n"
            ),
        },
        'channels': {
            'default_name': 'channels.csv',
            'content': (
                "short_name,tx_freq,rx_freq,tx_tone,rx_tone,long_name\n"
                "# Example: RPT IN,147.000,147.600,100.0,100.0,"
                "Repeater Input\n"
            ),
        },
        'units': {
            'default_name': 'units.csv',
            'content': (
                "unit_id,name,password\n"
                "# Example: 1001,UNIT-1001,1234\n"
            ),
        },
        'config': {
            'default_name': 'config.ini',
            'content': (
                "# QuickPRS Config Template\n"
                "# Build a PRS file: quickprs build config.ini\n"
                "\n"
                "[personality]\n"
                "name = My Radio.PRS\n"
                "author = QuickPRS\n"
                "\n"
                "# --- P25 Trunked System ---\n"
                "# Uncomment and fill in to add a P25 system\n"
                "#[system.MYSYS]\n"
                "#type = p25_trunked\n"
                "#long_name = MY SYSTEM\n"
                "#system_id = 100\n"
                "#wacn = 0\n"
                "\n"
                "#[system.MYSYS.frequencies]\n"
                "#1 = 851.0125,806.0125\n"
                "#2 = 851.0375,806.0375\n"
                "\n"
                "#[system.MYSYS.talkgroups]\n"
                "#1 = 1,DISP,Dispatch\n"
                "#2 = 2,TAC 1,Tactical 1\n"
                "\n"
                "# --- Conventional Channels ---\n"
                "# Use a built-in template:\n"
                "#[channels.MURS]\n"
                "#template = murs\n"
                "\n"
                "#[channels.NOAA]\n"
                "#template = noaa\n"
                "\n"
                "# Or define inline channels:\n"
                "#[channels.CUSTOM]\n"
                "#1 = CH 1,462.5625,462.5625,100.0,100.0,Custom 1\n"
                "\n"
                "# --- Radio Options ---\n"
                "#[options]\n"
                "#gps.gpsMode = ON\n"
                "#misc.password = 1234\n"
            ),
        },
    }

    if template_type not in templates:
        print(f"Error: unknown template type '{template_type}'. "
              f"Available: {', '.join(sorted(templates.keys()))}",
              file=sys.stderr)
        return 1

    tmpl = templates[template_type]
    out_path = Path(output) if output else Path(tmpl['default_name'])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tmpl['content'], encoding='utf-8')

    print(f"Created template: {out_path}")
    return 0


def cmd_wizard(modify_file=None):
    """Launch the interactive wizard.

    Args:
        modify_file: optional path to an existing PRS file to modify.

    Returns:
        0 on success, 1 on error.
    """
    from .wizard import run_wizard
    return run_wizard(modify_file=modify_file)


def cmd_backup(filepath, list_backups=False, restore=False,
               restore_index=None):
    """Manage timestamped backups of a PRS file.

    Args:
        filepath: PRS file path
        list_backups: if True, list available backups
        restore: if True, restore from most recent (or restore_index)
        restore_index: specific backup number to restore (1 = newest)
    """
    from .backup import (
        create_backup as do_create,
        list_backups as do_list,
        restore_backup as do_restore,
    )

    path = Path(filepath)

    if list_backups:
        entries = do_list(filepath)
        if not entries:
            print(f"No backups found for {path.name}")
            return 0
        print(f"Backups for {path.name}:")
        for idx, bp, mtime in entries:
            size = bp.stat().st_size
            ts = mtime.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {idx:>2}. {ts}  ({size:,} bytes)  {bp.name}")
        return 0

    if restore:
        if not path.exists():
            print(f"Error: {path} not found", file=sys.stderr)
            return 1
        idx = restore_index if restore_index else None
        try:
            restored = do_restore(filepath, index=idx)
            print(f"Restored {path.name} from {Path(restored).name}")
            return 0
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Default: create a backup
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1
    backup_path = do_create(filepath)
    print(f"Backup created: {Path(backup_path).name}")
    return 0


def cmd_rename(filepath, set_name, pattern, replacement,
               set_type="group", field="short_name", output=None):
    """Batch rename items in a set using regex substitution.

    Args:
        filepath: PRS file path
        set_name: name of the target set
        pattern: regex pattern to match in names
        replacement: replacement string (supports backreferences)
        set_type: "group" or "conv"
        field: "short_name" or "long_name"
        output: output file path (default: overwrite input)
    """
    from .injector import batch_rename
    from .prs_writer import write_prs

    prs = parse_prs(filepath)
    count = batch_rename(prs, set_name, pattern, replacement,
                         set_type=set_type, field=field)

    if count == 0:
        print("No items matched the pattern.")
        return 0

    out = Path(output) if output else Path(filepath)
    write_prs(prs, out)
    print(f"Renamed {count} item(s) in {set_type} set '{set_name}'")
    print(f"Written to {out}")
    return 0


def cmd_sort(filepath, set_name, set_type="conv", key="name",
             reverse=False, output=None):
    """Sort channels or talkgroups within a set.

    Args:
        filepath: PRS file path
        set_name: name of the target set
        set_type: "conv" or "group"
        key: sort key — "frequency", "name", "id", "tone"
        reverse: if True, reverse sort order
        output: output file path (default: overwrite input)
    """
    from .injector import sort_channels
    from .prs_writer import write_prs

    prs = parse_prs(filepath)
    result = sort_channels(prs, set_name, set_type=set_type,
                           key=key, reverse=reverse)

    if not result:
        print(f"Error: {set_type} set '{set_name}' not found",
              file=sys.stderr)
        return 1

    out = Path(output) if output else Path(filepath)
    write_prs(prs, out)
    order = "descending" if reverse else "ascending"
    print(f"Sorted {set_type} set '{set_name}' by {key} ({order})")
    print(f"Written to {out}")
    return 0


def cmd_diff_report(filepath_a, filepath_b, output=None):
    """Generate a personality change report between two PRS files.

    Args:
        filepath_a: original PRS file (before)
        filepath_b: modified PRS file (after)
        output: output file path (default: print to stdout)
    """
    from .diff_report import generate_diff_report_from_files

    report = generate_diff_report_from_files(filepath_a, filepath_b,
                                             output=output)
    if not output:
        print(report)
    else:
        print(f"Change report written to {output}")
    return 0


def run_cli(args=None):
    """Parse CLI arguments and dispatch to the appropriate command.

    Returns exit code (0=success, 1=error/validation failure).
    Returns None if no CLI flags found (caller should launch GUI).
    """
    import argparse

    fmt = argparse.RawDescriptionHelpFormatter

    categorized_help = (
        "QuickPRS v" + __version__ + " - XG-100P Personality File Tool\n"
        "\n"
        "Create & Build:\n"
        "  create            Create a new blank PRS file\n"
        "  build             Build from INI config file\n"
        "  profiles          Build from pre-built profile templates\n"
        "  wizard            Interactive guided setup\n"
        "  fleet             Batch-build for radio fleet\n"
        "\n"
        "Modify:\n"
        "  inject            Add systems/channels/talkgroups\n"
        "  remove            Remove systems or sets\n"
        "  edit              Edit metadata or rename sets\n"
        "  merge             Merge from another PRS file\n"
        "  clone             Clone a system between files\n"
        "  clone-personality  Create modified personality copy\n"
        "  rename            Batch rename with regex patterns\n"
        "  sort              Sort channels or talkgroups in a set\n"
        "  renumber          Auto-number channels sequentially\n"
        "  auto-name         Auto-generate short names from long names\n"
        "  bulk-edit         Batch-modify talkgroup or channel settings\n"
        "\n"
        "Import:\n"
        "  import-rr         Import P25 system from RadioReference API\n"
        "  import-paste      Import from pasted RadioReference text\n"
        "  import-scanner    Import from CHIRP, Uniden, or SDRTrunk CSV\n"
        "  import-json       Create PRS from a JSON file\n"
        "  auto-setup        One-click P25 system setup from RadioReference\n"
        "  systems           Browse/search/add from built-in P25 database\n"
        "  template-csv      Generate blank CSV/INI templates for data entry\n"
        "\n"
        "Export:\n"
        "  export            Export to CHIRP, Uniden, SDRTrunk, DSD+, Markdown\n"
        "  export-csv        Export all data to CSV files\n"
        "  export-json       Export PRS to structured JSON\n"
        "  export-config     Export PRS as editable INI config file\n"
        "  report            Generate full HTML report\n"
        "  card              Generate printable summary reference card\n"
        "\n"
        "Inspect & Validate:\n"
        "  info              Print personality summary\n"
        "  validate          Validate against XG-100P hardware limits\n"
        "  compare           Compare two PRS files\n"
        "  diff-report       Generate personality change report\n"
        "  diff-options      Compare radio options between two files\n"
        "  stats             Show channel statistics and frequency analysis\n"
        "  capacity          Show memory usage and remaining capacity\n"
        "  list              Quick-list systems, talkgroups, channels, etc.\n"
        "  dump              Dump raw section structure and hex data\n"
        "\n"
        "Radio Options:\n"
        "  set-option        Get/set radio options (GPS, audio, bluetooth, etc.)\n"
        "  encrypt           Set/clear P25 encryption on talkgroups\n"
        "  set-nac           Set Network Access Code on P25 conv channels\n"
        "\n"
        "Planning & Tools:\n"
        "  zones             Generate and export zone plans\n"
        "  freq-tools        Frequency reference (offsets, tones, channel lookup)\n"
        "  iden-templates    List standard IDEN frequency templates\n"
        "\n"
        "Maintenance:\n"
        "  repair            Fix corrupted PRS files or salvage data\n"
        "  cleanup           Find and fix duplicates and unused sets\n"
        "  search            Search across PRS files for freqs/TGs/names\n"
        "  backup            Create, list, or restore timestamped backups\n"
        "\n"
        "Use 'quickprs <command> --help' for details on any command."
    )

    parser = argparse.ArgumentParser(
        prog="QuickPRS",
        description=categorized_help,
        formatter_class=fmt,
        usage="quickprs [-h] [--version] <command> [options]",
    )
    parser.add_argument("--version", action="version",
                        version=f"QuickPRS v{__version__}")
    parser.add_argument("--completion", choices=["bash", "powershell"],
                        default=None, metavar="SHELL",
                        help="Output shell completion script "
                             "(bash or powershell)")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # info
    p_info = sub.add_parser("info", help="Print personality summary",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs info radio.PRS\n"
               "  quickprs info radio.PRS --detail\n"
               "  quickprs info *.PRS")
    p_info.add_argument("file", nargs='+', help="PRS file path(s)")
    p_info.add_argument("-d", "--detail", action="store_true",
                        help="Show verbose output with WAN, IDEN freqs, "
                             "conv details, size breakdown")

    # validate
    p_val = sub.add_parser("validate",
                            help="Validate one or more PRS files",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs validate radio.PRS\n"
               "  quickprs validate *.PRS")
    p_val.add_argument("file", nargs='+', help="PRS file path(s)")

    # set-option
    p_setopt = sub.add_parser("set-option",
                               help="Get/set radio options in "
                                    "platformConfig XML",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs set-option radio.PRS --list\n"
               "  quickprs set-option radio.PRS gps.gpsMode\n"
               "  quickprs set-option radio.PRS gps.gpsMode ON\n"
               "  quickprs set-option radio.PRS misc.password 1234\n"
               "  quickprs set-option radio.PRS bluetooth.btMode OFF")
    p_setopt.add_argument("file", help="PRS file path")
    p_setopt.add_argument("option", nargs='?', default=None,
                           help="section.attribute (e.g. gps.gpsMode)")
    p_setopt.add_argument("value", nargs='?', default=None,
                           help="New value (omit to show current)")
    p_setopt.add_argument("--list", action="store_true", dest="list_opts",
                           help="List all available options")
    p_setopt.add_argument("-o", "--output", default=None,
                           help="Output file (default: overwrite input)")

    # export-csv
    p_csv = sub.add_parser("export-csv", help="Export to CSV files",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs export-csv radio.PRS output/")
    p_csv.add_argument("file", help="PRS file path")
    p_csv.add_argument("output_dir", help="Output directory")

    # export-json
    p_json_out = sub.add_parser("export-json",
                                 help="Export PRS to structured JSON",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs export-json radio.PRS\n"
               "  quickprs export-json radio.PRS -o config.json\n"
               "  quickprs export-json radio.PRS --compact")
    p_json_out.add_argument("file", help="PRS file path")
    p_json_out.add_argument("-o", "--output", default=None,
                             help="Output JSON path (default: same name .json)")
    p_json_out.add_argument("--compact", action="store_true",
                             help="Write compact single-line JSON")

    # import-json
    p_json_in = sub.add_parser("import-json",
                                help="Create PRS from a JSON file",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs import-json config.json -o radio.PRS")
    p_json_in.add_argument("file", help="JSON file path")
    p_json_in.add_argument("-o", "--output", default=None,
                            help="Output PRS path (default: same name .PRS)")

    # compare
    p_cmp = sub.add_parser("compare",
                            help="Compare systems, channels, and data sets",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs compare old.PRS new.PRS\n"
               "  quickprs compare old.PRS new.PRS --detail")
    p_cmp.add_argument("file_a", help="First PRS file")
    p_cmp.add_argument("file_b", help="Second PRS file")
    p_cmp.add_argument("--detail", action="store_true", default=False,
                        help="Show detailed per-item comparison "
                             "(talkgroups, frequencies, channels, options)")

    # dump
    p_dump = sub.add_parser("dump", help="Dump raw section info",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs dump radio.PRS\n"
               "  quickprs dump radio.PRS -s 5\n"
               "  quickprs dump radio.PRS -s 5 -x 128")
    p_dump.add_argument("file", help="PRS file path")
    p_dump.add_argument("-s", "--section", type=int, default=None,
                        help="Section index to inspect in detail")
    p_dump.add_argument("-x", "--hex", type=int, default=0, metavar="BYTES",
                        help="Show N bytes of hex dump (use with -s)")

    # diff-options
    p_dopt = sub.add_parser("diff-options",
                              help="Compare radio options (audio, buttons, "
                                   "menu, display, etc.)",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs diff-options baseline.PRS modified.PRS\n"
               "  quickprs diff-options baseline.PRS modified.PRS --raw")
    p_dopt.add_argument("file_a", help="First PRS file (baseline)")
    p_dopt.add_argument("file_b", help="Second PRS file (modified)")
    p_dopt.add_argument("--raw", action="store_true",
                        help="Also show raw byte diffs for named sections")

    # create
    p_create = sub.add_parser("create",
                               help="Create a new blank PRS file",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs create radio.PRS\n"
               "  quickprs create radio.PRS --name PATROL --author Dispatch")
    p_create.add_argument("output", help="Output PRS file path")
    p_create.add_argument("--name", default=None,
                           help="Personality name (default: output filename)")
    p_create.add_argument("--author", default="",
                           help="Saved-by field")

    # build
    p_build = sub.add_parser("build",
                              help="Build a PRS from an INI config file",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs build patrol.ini\n"
               "  quickprs build patrol.ini -o patrol.PRS")
    p_build.add_argument("config", help="INI config file path")
    p_build.add_argument("-o", "--output", default=None,
                          help="Output PRS path (default: same name .PRS)")

    # export-config
    p_exp_cfg = sub.add_parser("export-config",
                                help="Export PRS as editable INI config",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs export-config radio.PRS\n"
               "  quickprs export-config radio.PRS -o config.ini")
    p_exp_cfg.add_argument("file", help="PRS file path")
    p_exp_cfg.add_argument("-o", "--output", default=None,
                            help="Output INI path (default: same name .ini)")

    # profiles
    p_prof = sub.add_parser("profiles",
                             help="Build from pre-built profile templates",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs profiles list\n"
               "  quickprs profiles build scanner_basic\n"
               "  quickprs profiles build ham_portable -o ham.PRS")
    p_prof_sub = p_prof.add_subparsers(dest="prof_cmd",
                                        metavar="<subcommand>")
    p_prof_list = p_prof_sub.add_parser("list",
                                         help="List available profiles")
    p_prof_build = p_prof_sub.add_parser("build",
                                          help="Build from a profile")
    p_prof_build.add_argument("profile", help="Profile template name")
    p_prof_build.add_argument("-o", "--output", default=None,
                               help="Output PRS path")

    # fleet
    p_fleet = sub.add_parser("fleet",
                              help="Build PRS files for a fleet of radios",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs fleet patrol.ini --units units.csv -o fleet_output/")
    p_fleet.add_argument("config", help="INI config file path")
    p_fleet.add_argument("--units", required=True,
                          help="CSV file with unit_id,name,password columns")
    p_fleet.add_argument("-o", "--output", default=None,
                          help="Output directory (default: fleet_output/)")

    # remove
    p_remove = sub.add_parser("remove",
                               help="Remove a system or data set",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs remove radio.PRS system \"PSERN SEATTLE\"\n"
               "  quickprs remove radio.PRS trunk-set PSERN\n"
               "  quickprs remove radio.PRS group-set \"PSERN PD\"\n"
               "  quickprs remove radio.PRS conv-set MURS")
    p_remove.add_argument("file", help="PRS file path")
    p_remove.add_argument("type",
                           choices=["system", "trunk-set",
                                    "group-set", "conv-set"],
                           help="What to remove")
    p_remove.add_argument("name", help="Name of the item to remove")
    p_remove.add_argument("-o", "--output", default=None,
                           help="Output file (default: overwrite input)")

    # edit
    p_edit = sub.add_parser("edit",
                             help="Edit personality metadata or rename sets",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs edit radio.PRS --name \"PATROL.PRS\"\n"
               "  quickprs edit radio.PRS --author \"Dispatch\"\n"
               "  quickprs edit radio.PRS --rename-set trunk PSERN NEWNAME")
    p_edit.add_argument("file", help="PRS file path")
    p_edit.add_argument("--name", default=None,
                         help="New personality filename")
    p_edit.add_argument("--author", default=None,
                         help="New saved-by field")
    p_edit.add_argument("--rename-set", nargs=3,
                         metavar=("TYPE", "OLD", "NEW"),
                         help="Rename a set: TYPE OLD NEW "
                              "(TYPE: trunk, group, conv)")
    p_edit.add_argument("-o", "--output", default=None,
                         help="Output file (default: overwrite input)")

    # iden-templates
    p_iden = sub.add_parser("iden-templates",
                             help="List standard IDEN templates",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs iden-templates\n"
               "  quickprs iden-templates --detail")
    p_iden.add_argument("-d", "--detail", action="store_true",
                        help="Show individual entries per template")

    # import-rr
    p_rr = sub.add_parser("import-rr",
                           help="Import P25 system from RadioReference API",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs import-rr radio.PRS --sid 8155 "
               "--username USER --apikey KEY\n"
               "  quickprs import-rr radio.PRS "
               "--url https://www.radioreference.com/db/sid/8155 "
               "--username USER --apikey KEY\n"
               "  quickprs import-rr radio.PRS --sid 8155 "
               "--username USER --apikey KEY --categories 1,3,5")
    p_rr.add_argument("file", help="PRS file to inject into")
    p_rr.add_argument("--sid", type=int, default=None,
                      help="RadioReference system ID (from URL: /db/sid/XXXX)")
    p_rr.add_argument("--url", default=None,
                      help="RadioReference system URL (alternative to --sid)")
    p_rr.add_argument("--username", required=True,
                      help="RadioReference username")
    p_rr.add_argument("--apikey", required=True,
                      help="RadioReference API key")
    p_rr.add_argument("--categories", default=None,
                      help="Comma-separated category IDs to include "
                           "(default: all)")
    p_rr.add_argument("--tags", default=None,
                      help="Comma-separated service tags to include "
                           "(default: all)")
    p_rr.add_argument("-o", "--output", default=None,
                      help="Output file (default: overwrite input)")

    # import-paste
    p_paste = sub.add_parser("import-paste",
                              help="Import P25 system from pasted "
                                   "RadioReference text",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs import-paste radio.PRS --name PSERN "
               "--sysid 892 --wacn 781824 "
               "--tgs-file tgs.txt --freqs-file freqs.txt")
    p_paste.add_argument("file", help="PRS file to inject into")
    p_paste.add_argument("--name", required=True,
                         help="System short name (8 chars max)")
    p_paste.add_argument("--sysid", type=int, required=True,
                         help="P25 System ID (decimal)")
    p_paste.add_argument("--wacn", type=int, default=0,
                         help="WACN (decimal, default 0)")
    p_paste.add_argument("--long-name", default=None,
                         help="Long display name (16 chars max)")
    p_paste.add_argument("--tgs-file", default=None,
                         help="Text file with pasted talkgroup table")
    p_paste.add_argument("--freqs-file", default=None,
                         help="Text file with pasted frequency/site table")
    p_paste.add_argument("-o", "--output", default=None,
                         help="Output file (default: overwrite input)")

    # merge
    p_merge = sub.add_parser("merge",
                              help="Merge systems/channels from one PRS "
                                   "into another",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs merge target.PRS source.PRS --all\n"
               "  quickprs merge target.PRS source.PRS --systems\n"
               "  quickprs merge target.PRS source.PRS --channels "
               "-o merged.PRS")
    p_merge.add_argument("target", help="Target PRS file (receives data)")
    p_merge.add_argument("source", help="Source PRS file (provides data)")
    p_merge.add_argument("--systems", action="store_true", default=False,
                          help="Merge P25 trunked systems only")
    p_merge.add_argument("--channels", action="store_true", default=False,
                          help="Merge conventional systems only")
    p_merge.add_argument("--all", action="store_true", default=False,
                          dest="merge_all",
                          help="Merge both systems and channels (default)")
    p_merge.add_argument("-o", "--output", default=None,
                          help="Output file (default: overwrite target)")

    # clone
    p_clone = sub.add_parser("clone",
                              help="Clone a specific system from one PRS "
                                   "into another",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs clone target.PRS source.PRS "
               "\"PSERN SEATTLE\" -o output.PRS")
    p_clone.add_argument("target", help="Target PRS file (receives data)")
    p_clone.add_argument("source", help="Source PRS file (provides data)")
    p_clone.add_argument("system", help="System long name to clone "
                                        "(e.g., 'PSERN SEATTLE')")
    p_clone.add_argument("-o", "--output", default=None,
                          help="Output file (default: overwrite target)")

    # clone-personality
    p_clonep = sub.add_parser("clone-personality",
                               help="Create a modified clone of a "
                                    "personality file",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs clone-personality radio.PRS -o det.PRS "
               "--name DET --remove-set FIRE\n"
               "  quickprs clone-personality radio.PRS -o rx_only.PRS "
               "--disable-tx \"PSERN PD\"\n"
               "  quickprs clone-personality radio.PRS -o unit5.PRS "
               "--unit-id 12345 --password 5678")
    p_clonep.add_argument("file", help="Source PRS file path")
    p_clonep.add_argument("-o", "--output", required=True,
                           help="Output file path (required)")
    p_clonep.add_argument("--name", default=None,
                           help="New personality name")
    p_clonep.add_argument("--remove-set", action="append", default=None,
                           dest="remove_sets",
                           help="Set name to remove (repeatable)")
    p_clonep.add_argument("--remove-system", action="append", default=None,
                           dest="remove_systems",
                           help="System long name to remove (repeatable)")
    p_clonep.add_argument("--enable-tx", action="append", default=None,
                           help="Set name to enable TX on (repeatable)")
    p_clonep.add_argument("--disable-tx", action="append", default=None,
                           help="Set name to disable TX on (repeatable)")
    p_clonep.add_argument("--unit-id", type=int, default=None,
                           help="New HomeUnitID")
    p_clonep.add_argument("--password", default=None,
                           help="New radio password")

    # renumber
    p_renum = sub.add_parser("renumber",
                              help="Renumber channels sequentially",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs renumber radio.PRS --set MURS --start 1\n"
               "  quickprs renumber radio.PRS --type group "
               "--set \"PSERN PD\" --start 100")
    p_renum.add_argument("file", help="PRS file path")
    p_renum.add_argument("--set", default=None, dest="set_name",
                          help="Set name to renumber (default: all)")
    p_renum.add_argument("--start", type=int, default=1,
                          help="Starting number (default: 1)")
    p_renum.add_argument("--type", choices=["conv", "group"],
                          default="conv", dest="set_type",
                          help="Set type: conv or group (default: conv)")
    p_renum.add_argument("-o", "--output", default=None,
                          help="Output file (default: overwrite input)")

    # auto-name
    p_autoname = sub.add_parser("auto-name",
                                 help="Auto-generate talkgroup short "
                                      "names from long names",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs auto-name radio.PRS --set \"PSERN PD\"\n"
               "  quickprs auto-name radio.PRS --set \"PSERN PD\" "
               "--style numbered")
    p_autoname.add_argument("file", help="PRS file path")
    p_autoname.add_argument("--set", required=True, dest="set_name",
                             help="Group set name")
    p_autoname.add_argument("--style",
                             choices=["compact", "numbered", "department"],
                             default="compact",
                             help="Naming style (default: compact)")
    p_autoname.add_argument("-o", "--output", default=None,
                             help="Output file (default: overwrite input)")

    # repair
    p_repair = sub.add_parser("repair",
                               help="Repair a damaged PRS file",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs repair damaged.PRS -o fixed.PRS\n"
               "  quickprs repair damaged.PRS --salvage")
    p_repair.add_argument("file", help="PRS file path")
    p_repair.add_argument("-o", "--output", default=None,
                           help="Output file (default: overwrite input)")
    p_repair.add_argument("--salvage", action="store_true",
                           help="Extract readable data from badly "
                                "damaged files")

    # capacity
    p_cap = sub.add_parser("capacity",
                            help="Show memory usage and remaining "
                                 "capacity",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs capacity radio.PRS\n"
               "  quickprs capacity *.PRS")
    p_cap.add_argument("file", nargs='+', help="PRS file path(s)")

    # report
    p_report = sub.add_parser("report",
                               help="Generate HTML report of radio "
                                    "configuration",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs report radio.PRS\n"
               "  quickprs report radio.PRS -o report.html")
    p_report.add_argument("file", help="PRS file path")
    p_report.add_argument("-o", "--output", default=None,
                           help="Output HTML path (default: same name .html)")

    # inject -- subcommand with its own sub-subparsers
    p_inject = sub.add_parser("inject",
                               help="Inject data into a PRS file",
        formatter_class=fmt,
        epilog="Subcommands: p25, conv, talkgroups\n\n"
               "Examples:\n"
               "  quickprs inject radio.PRS p25 --name PSERN "
               "--sysid 892 --freqs-csv freqs.csv --tgs-csv tgs.csv\n"
               "  quickprs inject radio.PRS conv --template murs\n"
               "  quickprs inject radio.PRS talkgroups "
               "--set \"PSERN PD\" --tgs-csv more_tgs.csv")
    p_inject.add_argument("file", help="PRS file path")
    inject_sub = p_inject.add_subparsers(dest="inject_cmd")

    # inject p25
    p_inj_p25 = inject_sub.add_parser("p25",
                                        help="Add a P25 trunked system",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs inject radio.PRS p25 --name PSERN "
               "--sysid 892 --wacn 781824 "
               "--freqs-csv freqs.csv --tgs-csv tgs.csv")
    p_inj_p25.add_argument("--name", required=True,
                            help="System short name (8 chars max)")
    p_inj_p25.add_argument("--long-name", default=None,
                            help="Long display name (16 chars max)")
    p_inj_p25.add_argument("--sysid", type=int, required=True,
                            help="P25 System ID")
    p_inj_p25.add_argument("--wacn", type=int, default=0,
                            help="WACN (default 0)")
    p_inj_p25.add_argument("--freqs-csv", default=None,
                            help="CSV with columns: tx_freq,rx_freq (MHz)")
    p_inj_p25.add_argument("--tgs-csv", default=None,
                            help="CSV with columns: id,short_name,long_name")
    p_inj_p25.add_argument("--iden-base", type=int, default=None,
                            help="IDEN base frequency Hz (auto-detect if omitted)")
    p_inj_p25.add_argument("--iden-spacing", type=int, default=None,
                            help="Channel spacing Hz (auto-detect if omitted)")
    p_inj_p25.add_argument("-o", "--output", default=None,
                            help="Output file (default: overwrite input)")

    # inject conv
    p_inj_conv = inject_sub.add_parser("conv",
                                        help="Add conventional channels",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs inject radio.PRS conv --template murs\n"
               "  quickprs inject radio.PRS conv --template noaa\n"
               "  quickprs inject radio.PRS conv --name LOCAL "
               "--channels-csv channels.csv")
    p_inj_conv.add_argument("--name", default=None,
                             help="Set name (8 chars max, defaults to "
                                  "template name if using --template)")
    conv_source = p_inj_conv.add_mutually_exclusive_group(required=True)
    conv_source.add_argument("--channels-csv", default=None,
                             help="CSV: short_name,tx_freq,rx_freq,"
                                  "tx_tone,rx_tone,long_name")
    conv_source.add_argument("--template", default=None,
                             help="Built-in template: murs, gmrs, frs, "
                                  "marine, noaa, weather, interop, "
                                  "public_safety")
    p_inj_conv.add_argument("-o", "--output", default=None,
                             help="Output file (default: overwrite input)")

    # inject talkgroups
    p_inj_tg = inject_sub.add_parser("talkgroups",
                                      help="Add talkgroups to existing set",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs inject radio.PRS talkgroups "
               "--set \"PSERN PD\" --tgs-csv new_tgs.csv")
    p_inj_tg.add_argument("--set", required=True, dest="set_name",
                           help="Target group set name")
    p_inj_tg.add_argument("--tgs-csv", required=True,
                           help="CSV: id,short_name,long_name")
    p_inj_tg.add_argument("-o", "--output", default=None,
                           help="Output file (default: overwrite input)")

    # import-scanner
    p_scanner = sub.add_parser("import-scanner",
                                help="Import channels from scanner CSV "
                                     "(Uniden, CHIRP, SDRTrunk)",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs import-scanner radio.PRS --csv chirp.csv\n"
               "  quickprs import-scanner radio.PRS --csv uniden.csv "
               "--format uniden --name SCANNER")
    p_scanner.add_argument("file", help="PRS file to inject into")
    p_scanner.add_argument("--csv", required=True, dest="csv_file",
                            help="Scanner CSV file to import")
    p_scanner.add_argument("--format",
                            choices=["uniden", "chirp", "sdrtrunk", "auto"],
                            default="auto", dest="scanner_fmt",
                            help="Scanner format (default: auto-detect)")
    p_scanner.add_argument("--name", default=None,
                            help="Conv set name (8 chars max, "
                                 "default: CSV filename)")
    p_scanner.add_argument("-o", "--output", default=None,
                            help="Output file (default: overwrite input)")

    # list -- quick data dump
    p_list = sub.add_parser("list",
                             help="List specific data types "
                                  "(systems, talkgroups, channels, "
                                  "frequencies, sets, options)",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs list radio.PRS systems\n"
               "  quickprs list radio.PRS talkgroups\n"
               "  quickprs list radio.PRS channels\n"
               "  quickprs list radio.PRS frequencies\n"
               "  quickprs list radio.PRS options")
    p_list.add_argument("file", help="PRS file path")
    p_list.add_argument("type",
                         choices=["systems", "talkgroups", "channels",
                                  "frequencies", "sets", "options"],
                         help="Data type to list")

    # bulk-edit -- subcommand with talkgroups/channels sub-subcommands
    p_bulk = sub.add_parser("bulk-edit",
                             help="Bulk-modify talkgroups or channels",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs bulk-edit radio.PRS talkgroups "
               "--set \"PSERN PD\" --enable-scan\n"
               "  quickprs bulk-edit radio.PRS talkgroups "
               "--set \"PSERN PD\" --disable-tx\n"
               "  quickprs bulk-edit radio.PRS channels "
               "--set MURS --set-tone 100.0\n"
               "  quickprs bulk-edit radio.PRS channels "
               "--set MURS --clear-tones")
    p_bulk.add_argument("file", help="PRS file path")
    bulk_sub = p_bulk.add_subparsers(dest="bulk_cmd")

    # bulk-edit talkgroups
    p_bulk_tg = bulk_sub.add_parser("talkgroups",
                                     help="Bulk-edit talkgroups in a set",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs bulk-edit radio.PRS talkgroups "
               "--set \"PSERN PD\" --enable-scan\n"
               "  quickprs bulk-edit radio.PRS talkgroups "
               "--set \"PSERN PD\" --disable-tx\n"
               "  quickprs bulk-edit radio.PRS talkgroups "
               "--set \"PSERN PD\" --prefix \"PD \"")
    p_bulk_tg.add_argument("--set", required=True, dest="set_name",
                            help="Target group set name")
    p_bulk_tg.add_argument("--enable-scan", action="store_true",
                            default=False,
                            help="Enable scan on all TGs")
    p_bulk_tg.add_argument("--disable-scan", action="store_true",
                            default=False,
                            help="Disable scan on all TGs")
    p_bulk_tg.add_argument("--enable-tx", action="store_true",
                            default=False,
                            help="Enable TX on all TGs")
    p_bulk_tg.add_argument("--disable-tx", action="store_true",
                            default=False,
                            help="Disable TX on all TGs")
    p_bulk_tg.add_argument("--prefix", default=None,
                            help="Add prefix to all short names")
    p_bulk_tg.add_argument("--suffix", default=None,
                            help="Add suffix to all short names")
    p_bulk_tg.add_argument("-o", "--output", default=None,
                            help="Output file (default: overwrite input)")

    # bulk-edit channels
    p_bulk_ch = bulk_sub.add_parser("channels",
                                     help="Bulk-edit conv channels in a set",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs bulk-edit radio.PRS channels "
               "--set MURS --set-tone 100.0\n"
               "  quickprs bulk-edit radio.PRS channels "
               "--set MURS --clear-tones\n"
               "  quickprs bulk-edit radio.PRS channels "
               "--set MURS --set-power 2")
    p_bulk_ch.add_argument("--set", required=True, dest="set_name",
                            help="Target conv set name")
    p_bulk_ch.add_argument("--set-tone", default=None,
                            help="Set CTCSS tone on all channels "
                                 "(e.g., '100.0')")
    p_bulk_ch.add_argument("--clear-tones", action="store_true",
                            default=False,
                            help="Clear all tones from all channels")
    p_bulk_ch.add_argument("--set-power", type=int, default=None,
                            choices=[0, 1, 2],
                            help="Set power level (0=low, 1=med, 2=high)")
    p_bulk_ch.add_argument("-o", "--output", default=None,
                            help="Output file (default: overwrite input)")

    # freq-tools -- frequency/tone reference
    p_freq = sub.add_parser("freq-tools",
                             help="Frequency and tone reference tools",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs freq-tools offset 146.94\n"
               "  quickprs freq-tools channel 462.5625\n"
               "  quickprs freq-tools tones\n"
               "  quickprs freq-tools dcs\n"
               "  quickprs freq-tools nearest 100.5\n"
               "  quickprs freq-tools identify 462.5625\n"
               "  quickprs freq-tools all-offsets 146.94\n"
               "  quickprs freq-tools conflicts "
               "462.5625,462.5875,462.6125")
    freq_sub = p_freq.add_subparsers(dest="freq_cmd")

    p_freq_offset = freq_sub.add_parser("offset",
                                         help="Calculate repeater offset")
    p_freq_offset.add_argument("freq", type=float,
                                help="Frequency in MHz")

    p_freq_channel = freq_sub.add_parser("channel",
                                          help="Identify service channel")
    p_freq_channel.add_argument("freq", type=float,
                                 help="Frequency in MHz")

    freq_sub.add_parser("tones", help="List all CTCSS tones")
    freq_sub.add_parser("dcs", help="List all DCS codes")

    p_freq_nearest = freq_sub.add_parser("nearest",
                                          help="Find nearest CTCSS tone")
    p_freq_nearest.add_argument("freq", type=float,
                                 help="Tone frequency in Hz")

    p_freq_identify = freq_sub.add_parser("identify",
                                           help="Identify frequency service")
    p_freq_identify.add_argument("freq", type=float,
                                  help="Frequency in MHz")

    p_freq_all = freq_sub.add_parser("all-offsets",
                                      help="Show all possible repeater "
                                           "offsets")
    p_freq_all.add_argument("freq", type=float,
                             help="Output frequency in MHz")

    p_freq_conflicts = freq_sub.add_parser("conflicts",
                                            help="Check frequencies for "
                                                 "interference")
    p_freq_conflicts.add_argument("freqs", type=str,
                                   help="Comma-separated frequencies in MHz")

    # systems -- built-in P25 system database
    p_sys = sub.add_parser("systems",
                            help="Built-in P25 system database "
                                 "(list, search, info, add)",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs systems list\n"
               "  quickprs systems search seattle\n"
               "  quickprs systems info PSERN\n"
               "  quickprs systems add radio.PRS PSERN")
    sys_sub = p_sys.add_subparsers(dest="sys_cmd")

    sys_sub.add_parser("list", help="List all known P25 systems")

    p_sys_search = sys_sub.add_parser("search",
                                       help="Search systems by name/location")
    p_sys_search.add_argument("query", help="Search query")

    p_sys_info = sys_sub.add_parser("info",
                                     help="Show details for a system")
    p_sys_info.add_argument("name", help="System short name (e.g., PSERN)")

    p_sys_add = sys_sub.add_parser("add",
                                    help="Add a known system to a PRS file")
    p_sys_add.add_argument("file", help="PRS file to inject into")
    p_sys_add.add_argument("name",
                            help="System name from database (e.g., PSERN)")
    p_sys_add.add_argument("-o", "--output", default=None,
                            help="Output file (default: overwrite input)")

    # auto-setup -- one-click RadioReference system setup
    p_auto = sub.add_parser("auto-setup",
                             help="One-click P25 system setup from "
                                  "RadioReference (with ECC + IDEN)",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs auto-setup radio.PRS --sid 8155 "
               "--username USER --apikey KEY")
    p_auto.add_argument("file", help="PRS file to inject into")
    p_auto.add_argument("--sid", type=int, default=None,
                        help="RadioReference system ID")
    p_auto.add_argument("--url", default=None,
                        help="RadioReference system URL (alternative "
                             "to --sid)")
    p_auto.add_argument("--username", required=True,
                        help="RadioReference username")
    p_auto.add_argument("--apikey", required=True,
                        help="RadioReference API key")
    p_auto.add_argument("--categories", default=None,
                        help="Comma-separated category IDs to include")
    p_auto.add_argument("--tags", default=None,
                        help="Comma-separated service tags to include")
    p_auto.add_argument("-o", "--output", default=None,
                        help="Output file (default: overwrite input)")

    # encrypt -- set encryption on talkgroups
    p_enc = sub.add_parser("encrypt",
                            help="Set encryption on P25 talkgroups",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs encrypt radio.PRS --set \"PSERN PD\" "
               "--tg 1000 --key-id 1\n"
               "  quickprs encrypt radio.PRS --set \"PSERN PD\" "
               "--all --key-id 1\n"
               "  quickprs encrypt radio.PRS --set \"PSERN PD\" "
               "--all --decrypt")
    p_enc.add_argument("file", help="PRS file path")
    p_enc.add_argument("--set", required=True, dest="set_name",
                        help="Target group set name")
    p_enc.add_argument("--tg", type=int, default=None,
                        help="Specific talkgroup ID (default: all)")
    p_enc.add_argument("--all", action="store_true", dest="encrypt_all",
                        help="Apply to all talkgroups in set")
    p_enc.add_argument("--key-id", type=int, default=0,
                        help="Encryption key ID (default: 0)")
    p_enc.add_argument("--decrypt", action="store_true",
                        help="Remove encryption instead of setting it")
    p_enc.add_argument("-o", "--output", default=None,
                        help="Output file (default: overwrite input)")

    # set-nac -- set NAC on P25 conventional channel
    p_nac = sub.add_parser("set-nac",
                            help="Set NAC on P25 conventional channel",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs set-nac radio.PRS --set P25CONV "
               "--channel 0 --nac 293\n"
               "  quickprs set-nac radio.PRS --set P25CONV "
               "--channel 0 --nac 293 --nac-rx F7E")
    p_nac.add_argument("file", help="PRS file path")
    p_nac.add_argument("--set", required=True, dest="set_name",
                        help="P25 conv set name")
    p_nac.add_argument("--channel", type=int, required=True,
                        help="Channel index (0-based)")
    p_nac.add_argument("--nac", required=True,
                        help="NAC value in hex (e.g., 293, F7E, F7F)")
    p_nac.add_argument("--nac-rx", default=None,
                        help="RX NAC if different from TX (hex)")
    p_nac.add_argument("-o", "--output", default=None,
                        help="Output file (default: overwrite input)")

    # export -- export to third-party formats
    p_export = sub.add_parser("export",
                               help="Export to third-party radio tool "
                                    "formats (CHIRP, Uniden, SDRTrunk, "
                                    "DSD+, Markdown)",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs export radio.PRS chirp -o channels.csv\n"
               "  quickprs export radio.PRS uniden\n"
               "  quickprs export radio.PRS sdrtrunk\n"
               "  quickprs export radio.PRS markdown\n"
               "  quickprs export radio.PRS chirp "
               "--sets \"MURS,GMRS\"")
    p_export.add_argument("file", help="PRS file path")
    p_export.add_argument("format",
                           choices=["chirp", "uniden", "sdrtrunk",
                                    "dsd", "markdown"],
                           help="Export format")
    p_export.add_argument("-o", "--output", default=None,
                           help="Output file path (default: auto-named)")
    p_export.add_argument("--sets", default=None,
                           help="Comma-separated set names to export "
                                "(default: all)")

    # zones -- zone planning
    p_zones = sub.add_parser("zones",
                              help="Generate zone plan for channel "
                                   "organization",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs zones radio.PRS\n"
               "  quickprs zones radio.PRS --strategy by_set\n"
               "  quickprs zones radio.PRS --export zones.csv")
    p_zones.add_argument("file", help="PRS file path")
    p_zones.add_argument("--strategy",
                          choices=["auto", "by_set", "combined", "manual"],
                          default="auto",
                          help="Zone planning strategy (default: auto)")
    p_zones.add_argument("--export", default=None, metavar="CSV",
                          help="Export zone plan to CSV file")

    # stats -- personality statistics
    p_stats = sub.add_parser("stats",
                              help="Show radio personality statistics",
        formatter_class=fmt,
        epilog="Example:\n"
               "  quickprs stats radio.PRS")
    p_stats.add_argument("file", help="PRS file path")

    # card -- summary card
    p_card = sub.add_parser("card",
                             help="Generate compact summary reference card",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs card radio.PRS\n"
               "  quickprs card radio.PRS -o card.html")
    p_card.add_argument("file", help="PRS file path")
    p_card.add_argument("-o", "--output", default=None,
                         help="Output HTML path (default: <name>_card.html)")

    # cleanup -- duplicate detection and removal
    p_cleanup = sub.add_parser("cleanup",
                                help="Find and fix duplicates and "
                                     "unused sets",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs cleanup radio.PRS --check\n"
               "  quickprs cleanup radio.PRS --fix\n"
               "  quickprs cleanup radio.PRS --remove-unused")
    p_cleanup.add_argument("file", help="PRS file path")
    p_cleanup.add_argument("--check", action="store_true",
                            default=False,
                            help="Report duplicates and unused sets "
                                 "(default action)")
    p_cleanup.add_argument("--fix", action="store_true",
                            default=False,
                            help="Show what duplicates would be removed")
    p_cleanup.add_argument("--remove-unused", action="store_true",
                            default=False, dest="remove_unused",
                            help="Report unreferenced data sets")

    # search -- cross-file search
    p_search = sub.add_parser("search",
                               help="Search across PRS files for "
                                    "frequencies, talkgroups, or names",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs search *.PRS --freq 851.0125\n"
               "  quickprs search *.PRS --tg 1000\n"
               "  quickprs search *.PRS --name PSERN")
    p_search.add_argument("file", nargs='+',
                           help="PRS file path(s) or glob pattern(s)")
    search_type = p_search.add_mutually_exclusive_group(required=True)
    search_type.add_argument("--freq", type=float, default=None,
                              help="Frequency to search for (MHz)")
    search_type.add_argument("--tg", type=int, default=None,
                              help="Talkgroup ID to search for")
    search_type.add_argument("--name", default=None,
                              dest="search_name",
                              help="Name/string to search for "
                                   "(case-insensitive)")

    # wizard -- interactive personality builder
    p_wizard = sub.add_parser("wizard",
                               help="Interactive wizard for building a "
                                    "radio personality",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs wizard\n"
               "  quickprs wizard --modify radio.PRS")
    p_wizard.add_argument("--modify", default=None, metavar="FILE",
                           help="Existing PRS file to use as base "
                                "(optional)")

    # template-csv -- generate blank CSV/INI templates
    p_tmpl = sub.add_parser("template-csv",
                              help="Generate blank CSV/INI templates "
                                   "for data entry",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs template-csv frequencies -o freqs.csv\n"
               "  quickprs template-csv talkgroups -o tgs.csv\n"
               "  quickprs template-csv channels -o channels.csv\n"
               "  quickprs template-csv units -o units.csv\n"
               "  quickprs template-csv config -o config.ini")
    p_tmpl.add_argument("type",
                         choices=["frequencies", "talkgroups", "channels",
                                  "units", "config"],
                         help="Template type to generate")
    p_tmpl.add_argument("-o", "--output", default=None,
                         help="Output file path (default: auto-named)")

    # backup -- manage timestamped backups
    p_backup = sub.add_parser("backup",
                               help="Create, list, or restore "
                                    "timestamped backups",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs backup radio.PRS\n"
               "  quickprs backup radio.PRS --list\n"
               "  quickprs backup radio.PRS --restore\n"
               "  quickprs backup radio.PRS --restore 2")
    p_backup.add_argument("file", help="PRS file path")
    p_backup.add_argument("--list", action="store_true",
                           dest="list_backups",
                           help="List available backups")
    p_backup.add_argument("--restore", nargs='?', const=True,
                           default=False, metavar="N",
                           help="Restore from backup (optionally "
                                "specify backup number, 1=newest)")

    # rename -- batch rename with regex
    p_rename = sub.add_parser("rename",
                               help="Batch rename channels or talkgroups "
                                    "using regex",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs rename radio.PRS --set \"PSERN PD\" "
               "--pattern \"^PD \" --replace \"\"\n"
               "  quickprs rename radio.PRS --set MURS --type conv "
               "--pattern \"CH(\\d)\" --replace \"MURS \\1\"\n"
               "  quickprs rename radio.PRS --set \"PSERN PD\" "
               "--field long_name --pattern DISP --replace DSP")
    p_rename.add_argument("file", help="PRS file path")
    p_rename.add_argument("--set", required=True, dest="set_name",
                           help="Set name to rename items in")
    p_rename.add_argument("--pattern", required=True,
                           help="Regex pattern to match")
    p_rename.add_argument("--replace", required=True,
                           help="Replacement string (supports \\1 backrefs)")
    p_rename.add_argument("--type", choices=["group", "conv"],
                           default="group", dest="set_type",
                           help="Set type (default: group)")
    p_rename.add_argument("--field", choices=["short_name", "long_name"],
                           default="short_name",
                           help="Name field to modify (default: short_name)")
    p_rename.add_argument("-o", "--output", default=None,
                           help="Output file (default: overwrite input)")

    # sort -- sort channels/talkgroups in a set
    p_sort = sub.add_parser("sort",
                              help="Sort channels or talkgroups within "
                                   "a set",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs sort radio.PRS --set MURS --key frequency\n"
               "  quickprs sort radio.PRS --set \"PSERN PD\" --type group "
               "--key id\n"
               "  quickprs sort radio.PRS --set MURS --key name --reverse")
    p_sort.add_argument("file", help="PRS file path")
    p_sort.add_argument("--set", required=True, dest="set_name",
                         help="Set name to sort")
    p_sort.add_argument("--key",
                         choices=["frequency", "name", "id", "tone"],
                         default="name",
                         help="Sort key (default: name)")
    p_sort.add_argument("--type", choices=["conv", "group"],
                         default="conv", dest="set_type",
                         help="Set type (default: conv)")
    p_sort.add_argument("--reverse", action="store_true",
                         default=False,
                         help="Reverse sort order")
    p_sort.add_argument("-o", "--output", default=None,
                         help="Output file (default: overwrite input)")

    # diff-report -- personality change report
    p_diffrpt = sub.add_parser("diff-report",
                                help="Generate personality change report "
                                     "between two PRS files",
        formatter_class=fmt,
        epilog="Examples:\n"
               "  quickprs diff-report before.PRS after.PRS\n"
               "  quickprs diff-report original.PRS modified.PRS "
               "-o changes.txt")
    p_diffrpt.add_argument("file_a", help="Original PRS file (before)")
    p_diffrpt.add_argument("file_b", help="Modified PRS file (after)")
    p_diffrpt.add_argument("-o", "--output", default=None,
                            help="Output file path (default: print to stdout)")

    # Suppress the auto-generated subparser listing since we have a
    # curated categorized listing in the description above
    for action_group in parser._action_groups:
        if action_group.title == "positional arguments":
            action_group._group_actions = []
            action_group._actions = []
            break

    parsed = parser.parse_args(args)

    # Shell completion script output
    if parsed.completion:
        from .completions import (
            generate_bash_completion, generate_powershell_completion,
        )
        if parsed.completion == "bash":
            print(generate_bash_completion())
        elif parsed.completion == "powershell":
            print(generate_powershell_completion())
        return 0

    if parsed.command is None:
        return None  # No subcommand — caller should launch GUI

    try:
        if parsed.command == "info":
            files = parsed.file
            if len(files) == 1:
                return cmd_info(files[0], detail=parsed.detail)
            # Multi-file batch mode
            worst = 0
            for i, f in enumerate(files):
                if i > 0:
                    print("=" * 60)
                try:
                    rc = cmd_info(f, detail=parsed.detail)
                    worst = max(worst, rc)
                except (FileNotFoundError, ValueError) as e:
                    print(f"Error: {e}", file=sys.stderr)
                    worst = 1
            if len(files) > 1:
                print("=" * 60)
                print(f"Processed {len(files)} files")
            return worst
        elif parsed.command == "validate":
            files = parsed.file
            if len(files) == 1:
                return cmd_validate(files[0])
            # Multi-file batch mode
            pass_count = 0
            fail_count = 0
            error_count = 0
            for i, f in enumerate(files):
                if i > 0:
                    print("=" * 60)
                try:
                    rc = cmd_validate(f)
                    if rc == 0:
                        pass_count += 1
                    else:
                        fail_count += 1
                except (FileNotFoundError, ValueError) as e:
                    print(f"Error: {f}: {e}", file=sys.stderr)
                    error_count += 1
            print("=" * 60)
            print(f"Batch validate: {pass_count} passed, "
                  f"{fail_count} failed, {error_count} errors "
                  f"({len(files)} files)")
            return 1 if (fail_count + error_count) > 0 else 0
        elif parsed.command == "set-option":
            return cmd_set_option(
                parsed.file,
                option_path=parsed.option,
                value=parsed.value,
                list_opts=parsed.list_opts,
                output=parsed.output,
            )
        elif parsed.command == "export-csv":
            return cmd_export_csv(parsed.file, parsed.output_dir)
        elif parsed.command == "export-json":
            return cmd_export_json(parsed.file, output=parsed.output,
                                   compact=parsed.compact)
        elif parsed.command == "import-json":
            return cmd_import_json(parsed.file, output=parsed.output)
        elif parsed.command == "compare":
            return cmd_compare(parsed.file_a, parsed.file_b,
                               detail=parsed.detail)
        elif parsed.command == "dump":
            return cmd_dump(parsed.file, parsed.section, parsed.hex)
        elif parsed.command == "diff-options":
            return cmd_diff_options(parsed.file_a, parsed.file_b,
                                    raw=parsed.raw)
        elif parsed.command == "create":
            return cmd_create(parsed.output, name=parsed.name,
                              author=parsed.author)
        elif parsed.command == "build":
            return cmd_build(parsed.config, output=parsed.output)
        elif parsed.command == "export-config":
            return cmd_export_config(parsed.file, output=parsed.output)
        elif parsed.command == "profiles":
            if parsed.prof_cmd is None:
                p_prof.print_help()
                return 1
            elif parsed.prof_cmd == "list":
                return cmd_profiles("list")
            elif parsed.prof_cmd == "build":
                return cmd_profiles("build", parsed.profile,
                                    output=parsed.output)
        elif parsed.command == "fleet":
            return cmd_fleet(parsed.config, parsed.units,
                             output_dir=parsed.output)
        elif parsed.command == "remove":
            return cmd_remove(parsed.file, parsed.type, parsed.name,
                              output=parsed.output)
        elif parsed.command == "edit":
            rename_args = (None, None, None)
            if parsed.rename_set:
                rename_args = tuple(parsed.rename_set)
            return cmd_edit(
                parsed.file,
                name=parsed.name,
                author=parsed.author,
                rename_set_type=rename_args[0],
                rename_old=rename_args[1],
                rename_new=rename_args[2],
                output=parsed.output,
            )
        elif parsed.command == "iden-templates":
            return cmd_iden_templates(parsed.detail)
        elif parsed.command == "import-rr":
            return cmd_import_rr(
                parsed.file,
                sid=parsed.sid,
                url=parsed.url,
                username=parsed.username,
                apikey=parsed.apikey,
                categories=parsed.categories,
                tags=parsed.tags,
                output=parsed.output,
            )
        elif parsed.command == "import-paste":
            return cmd_import_paste(
                parsed.file,
                parsed.name,
                parsed.sysid,
                wacn=parsed.wacn,
                long_name=parsed.long_name,
                tgs_file=parsed.tgs_file,
                freqs_file=parsed.freqs_file,
                output=parsed.output,
            )
        elif parsed.command == "merge":
            # Determine what to merge based on flags
            if parsed.merge_all or (not parsed.systems
                                    and not parsed.channels):
                inc_sys, inc_ch = True, True
            else:
                inc_sys = parsed.systems
                inc_ch = parsed.channels
            return cmd_merge(
                parsed.target, parsed.source,
                include_systems=inc_sys,
                include_channels=inc_ch,
                output=parsed.output,
            )
        elif parsed.command == "clone":
            return cmd_clone(
                parsed.target, parsed.source,
                parsed.system,
                output=parsed.output,
            )
        elif parsed.command == "clone-personality":
            return cmd_clone_personality(
                parsed.file,
                output=parsed.output,
                name=parsed.name,
                remove_sets=parsed.remove_sets,
                remove_systems=parsed.remove_systems,
                enable_tx=parsed.enable_tx,
                disable_tx=parsed.disable_tx,
                unit_id=parsed.unit_id,
                password=parsed.password,
            )
        elif parsed.command == "renumber":
            return cmd_renumber(
                parsed.file,
                set_name=parsed.set_name,
                start=parsed.start,
                set_type=parsed.set_type,
                output=parsed.output,
            )
        elif parsed.command == "auto-name":
            return cmd_auto_name(
                parsed.file,
                parsed.set_name,
                style=parsed.style,
                output=parsed.output,
            )
        elif parsed.command == "repair":
            return cmd_repair(
                parsed.file,
                output=parsed.output,
                salvage=parsed.salvage,
            )
        elif parsed.command == "capacity":
            files = parsed.file
            if len(files) == 1:
                return cmd_capacity(files[0])
            worst = 0
            for i, f in enumerate(files):
                if i > 0:
                    print("=" * 60)
                try:
                    rc = cmd_capacity(f)
                    worst = max(worst, rc)
                except (FileNotFoundError, ValueError) as e:
                    print(f"Error: {e}", file=sys.stderr)
                    worst = 1
            return worst
        elif parsed.command == "report":
            return cmd_report(parsed.file, output=parsed.output)
        elif parsed.command == "inject":
            if parsed.inject_cmd is None:
                p_inject.print_help()
                return 1
            elif parsed.inject_cmd == "p25":
                return cmd_inject_p25(
                    parsed.file, parsed.name, parsed.sysid,
                    long_name=parsed.long_name,
                    wacn=parsed.wacn,
                    freqs_csv=parsed.freqs_csv,
                    tgs_csv=parsed.tgs_csv,
                    iden_base=parsed.iden_base,
                    iden_spacing=parsed.iden_spacing,
                    output=parsed.output,
                )
            elif parsed.inject_cmd == "conv":
                return cmd_inject_conv(
                    parsed.file, parsed.name,
                    channels_csv=parsed.channels_csv,
                    template=parsed.template,
                    output=parsed.output,
                )
            elif parsed.inject_cmd == "talkgroups":
                return cmd_inject_talkgroups(
                    parsed.file, parsed.set_name,
                    parsed.tgs_csv,
                    output=parsed.output,
                )
        elif parsed.command == "import-scanner":
            return cmd_import_scanner(
                parsed.file,
                csv_file=parsed.csv_file,
                scanner_fmt=parsed.scanner_fmt,
                name=parsed.name,
                output=parsed.output,
            )
        elif parsed.command == "list":
            return cmd_list(parsed.file, parsed.type)
        elif parsed.command == "bulk-edit":
            if parsed.bulk_cmd is None:
                p_bulk.print_help()
                return 1
            elif parsed.bulk_cmd == "talkgroups":
                return cmd_bulk_edit_talkgroups(
                    parsed.file, parsed.set_name,
                    enable_scan=parsed.enable_scan,
                    disable_scan=parsed.disable_scan,
                    enable_tx=parsed.enable_tx,
                    disable_tx=parsed.disable_tx,
                    prefix=parsed.prefix,
                    suffix=parsed.suffix,
                    output=parsed.output,
                )
            elif parsed.bulk_cmd == "channels":
                return cmd_bulk_edit_channels(
                    parsed.file, parsed.set_name,
                    set_tone=parsed.set_tone,
                    clear_tones=parsed.clear_tones,
                    set_power=parsed.set_power,
                    output=parsed.output,
                )
        elif parsed.command == "freq-tools":
            if parsed.freq_cmd is None:
                p_freq.print_help()
                return 1
            freq_val = getattr(parsed, 'freq', None)
            freq_list = None
            if parsed.freq_cmd == "conflicts":
                raw = getattr(parsed, 'freqs', '')
                freq_list = [float(f.strip()) for f in raw.split(',')
                             if f.strip()]
            return cmd_freq_tools(parsed.freq_cmd, freq=freq_val,
                                   freq_list=freq_list)
        elif parsed.command == "systems":
            if parsed.sys_cmd is None:
                p_sys.print_help()
                return 1
            elif parsed.sys_cmd == "list":
                return cmd_systems("list")
            elif parsed.sys_cmd == "search":
                return cmd_systems("search", query=parsed.query)
            elif parsed.sys_cmd == "info":
                return cmd_systems("info", system_name=parsed.name)
            elif parsed.sys_cmd == "add":
                return cmd_systems("add", filepath=parsed.file,
                                   system_name=parsed.name,
                                   output=parsed.output)
        elif parsed.command == "auto-setup":
            return cmd_auto_setup(
                parsed.file,
                sid=parsed.sid,
                url=parsed.url,
                username=parsed.username,
                apikey=parsed.apikey,
                categories=parsed.categories,
                tags=parsed.tags,
                output=parsed.output,
            )
        elif parsed.command == "encrypt":
            return cmd_encrypt(
                parsed.file, parsed.set_name,
                tg_id=parsed.tg,
                encrypt_all=parsed.encrypt_all,
                key_id=parsed.key_id,
                decrypt=parsed.decrypt,
                output=parsed.output,
            )
        elif parsed.command == "set-nac":
            return cmd_set_nac(
                parsed.file, parsed.set_name,
                channel=parsed.channel,
                nac=parsed.nac,
                nac_rx=parsed.nac_rx,
                output=parsed.output,
            )
        elif parsed.command == "export":
            sets_list = None
            if parsed.sets:
                sets_list = [s.strip() for s in parsed.sets.split(',')]
            return cmd_export(parsed.file, parsed.format,
                              output=parsed.output, sets=sets_list)
        elif parsed.command == "zones":
            return cmd_zones(
                parsed.file,
                strategy=parsed.strategy,
                export=parsed.export,
            )
        elif parsed.command == "stats":
            return cmd_stats(parsed.file)
        elif parsed.command == "card":
            return cmd_card(parsed.file, output=parsed.output)
        elif parsed.command == "cleanup":
            return cmd_cleanup(
                parsed.file,
                check=parsed.check,
                fix=parsed.fix,
                remove_unused=parsed.remove_unused,
            )
        elif parsed.command == "search":
            return cmd_search(
                parsed.file,
                freq=parsed.freq,
                tg=parsed.tg,
                name=parsed.search_name,
            )
        elif parsed.command == "wizard":
            return cmd_wizard(modify_file=parsed.modify)
        elif parsed.command == "template-csv":
            return cmd_template_csv(
                parsed.type,
                output=parsed.output,
            )
        elif parsed.command == "backup":
            restore_idx = None
            if parsed.restore and parsed.restore is not True:
                restore_idx = int(parsed.restore)
            return cmd_backup(
                parsed.file,
                list_backups=parsed.list_backups,
                restore=bool(parsed.restore),
                restore_index=restore_idx,
            )
        elif parsed.command == "rename":
            return cmd_rename(
                parsed.file,
                parsed.set_name,
                parsed.pattern,
                parsed.replace,
                set_type=parsed.set_type,
                field=parsed.field,
                output=parsed.output,
            )
        elif parsed.command == "sort":
            return cmd_sort(
                parsed.file,
                parsed.set_name,
                set_type=parsed.set_type,
                key=parsed.key,
                reverse=parsed.reverse,
                output=parsed.output,
            )
        elif parsed.command == "diff-report":
            return cmd_diff_report(
                parsed.file_a,
                parsed.file_b,
                output=parsed.output,
            )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0
