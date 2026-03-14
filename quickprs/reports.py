"""HTML report generation for PRS personality files.

Generates a printer-friendly HTML report of the radio configuration
including systems, talkgroups, frequencies, channels, IDEN sets, and
radio options.
"""

import html
from datetime import datetime
from pathlib import Path

from .prs_parser import PRSFile, parse_prs
from .record_types import (
    parse_class_header, parse_trunk_channel_section,
    parse_conv_channel_section, parse_group_section, parse_iden_section,
    parse_system_short_name, parse_system_long_name, parse_system_wan_name,
    is_system_config_data, parse_ecc_entries, parse_sets_from_sections,
)
from .binary_io import read_uint16_le
from .option_maps import (
    extract_platform_config, extract_blob_preamble,
    OPTION_MAPS, extract_section_data, read_field,
)


def _esc(text):
    """HTML-escape a string, handling None."""
    if text is None:
        return ""
    return html.escape(str(text))


def _parse_sets(prs, data_cls, set_cls, parser_func):
    """Parse data sets from a PRS file (shared helper)."""
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


_CSS = """\
body {
    font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    margin: 20px 40px;
    color: #222;
    background: #fff;
    line-height: 1.4;
}
h1 { font-size: 22px; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 17px; color: #444; margin-top: 28px; border-bottom: 1px solid #ccc;
     padding-bottom: 3px; }
h3 { font-size: 14px; color: #555; margin-top: 16px; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0 16px 0;
    font-size: 13px;
}
th, td {
    border: 1px solid #ccc;
    padding: 4px 8px;
    text-align: left;
}
th { background: #f0f0f0; font-weight: 600; }
tr:nth-child(even) { background: #f9f9f9; }
.summary-table { width: auto; min-width: 400px; }
.summary-table td:first-child { font-weight: 600; width: 160px; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 3px;
         font-size: 11px; font-weight: 600; }
.badge-tx { background: #d4edda; color: #155724; }
.badge-rx { background: #f8d7da; color: #721c24; }
.badge-scan { background: #cce5ff; color: #004085; }
.meta { color: #888; font-size: 12px; }
.capacity-bar {
    height: 14px; background: #e9ecef; border-radius: 3px;
    display: inline-block; width: 120px; vertical-align: middle;
}
.capacity-fill {
    height: 100%; border-radius: 3px; background: #28a745;
}
.capacity-fill.warn { background: #ffc107; }
.capacity-fill.danger { background: #dc3545; }
@media print {
    body { margin: 10px; font-size: 11px; }
    h1 { font-size: 18px; }
    h2 { font-size: 14px; }
    table { font-size: 11px; }
    .no-print { display: none; }
}
"""


def generate_html_report(prs, filepath=None, source_path=None):
    """Generate an HTML report of the radio personality.

    Args:
        prs: PRSFile object (already parsed)
        filepath: if given, write HTML to this file path
        source_path: original .PRS file path for display

    Returns:
        HTML string
    """
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append("<html lang='en'>")
    parts.append("<head>")
    parts.append("<meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")

    # Title from blob preamble or file path
    bp = extract_blob_preamble(prs)
    personality_name = ""
    if bp and bp.filename:
        personality_name = bp.filename
    elif source_path:
        personality_name = Path(source_path).stem
    else:
        personality_name = "Radio Personality"

    parts.append(f"<title>{_esc(personality_name)} - QuickPRS Report</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head>")
    parts.append("<body>")

    # Header
    parts.append(f"<h1>{_esc(personality_name)}</h1>")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_parts = [f"Generated: {now}"]
    if source_path:
        meta_parts.append(f"Source: {_esc(str(source_path))}")
    parts.append(f"<p class='meta'>{' | '.join(meta_parts)}</p>")

    # File summary
    _add_summary(parts, prs, bp)

    # Systems
    _add_systems(parts, prs)

    # Group sets (talkgroups)
    _add_group_sets(parts, prs)

    # Trunk sets (frequencies)
    _add_trunk_sets(parts, prs)

    # Conv sets (conventional channels)
    _add_conv_sets(parts, prs)

    # IDEN sets
    _add_iden_sets(parts, prs)

    # Radio options from platformConfig
    _add_radio_options(parts, prs)

    # Binary options
    _add_binary_options(parts, prs)

    # Capacity
    _add_capacity(parts, prs)

    parts.append("</body>")
    parts.append("</html>")

    html_str = "\n".join(parts)

    if filepath:
        Path(filepath).write_text(html_str, encoding="utf-8")

    return html_str


def _add_summary(parts, prs, bp):
    """Add file summary table."""
    parts.append("<h2>Summary</h2>")
    parts.append("<table class='summary-table'>")

    parts.append(f"<tr><td>File Size</td><td>{prs.file_size:,} bytes</td></tr>")
    parts.append(f"<tr><td>Sections</td><td>{len(prs.sections)}</td></tr>")

    if bp:
        if bp.filename:
            parts.append(f"<tr><td>Personality Name</td>"
                         f"<td>{_esc(bp.filename)}</td></tr>")
        if bp.username:
            parts.append(f"<tr><td>Author</td>"
                         f"<td>{_esc(bp.username)}</td></tr>")

    # System counts
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked Systems'),
        ('CConvSystem', 'Conventional Systems'),
        ('CP25ConvSystem', 'P25 Conv Systems'),
    ]
    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        if secs:
            names = [parse_system_short_name(s.raw) or "?" for s in secs]
            parts.append(f"<tr><td>{_esc(label)}</td>"
                         f"<td>{len(secs)}: {_esc(', '.join(names))}</td></tr>")

    # Set counts
    group_sets = _parse_group_sets(prs)
    trunk_sets = _parse_trunk_sets(prs)
    conv_sets = _parse_conv_sets(prs)
    iden_sets = _parse_iden_sets(prs)

    if group_sets:
        total_tgs = sum(len(gs.groups) for gs in group_sets)
        parts.append(f"<tr><td>Group Sets</td>"
                     f"<td>{len(group_sets)} sets, {total_tgs} talkgroups</td></tr>")
    if trunk_sets:
        total_freqs = sum(len(ts.channels) for ts in trunk_sets)
        parts.append(f"<tr><td>Trunk Sets</td>"
                     f"<td>{len(trunk_sets)} sets, {total_freqs} frequencies</td></tr>")
    if conv_sets:
        total_ch = sum(len(cs.channels) for cs in conv_sets)
        parts.append(f"<tr><td>Conv Sets</td>"
                     f"<td>{len(conv_sets)} sets, {total_ch} channels</td></tr>")
    if iden_sets:
        parts.append(f"<tr><td>IDEN Sets</td>"
                     f"<td>{len(iden_sets)} sets</td></tr>")

    parts.append("</table>")


def _add_systems(parts, prs):
    """Add systems section."""
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    any_systems = False
    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        if secs:
            any_systems = True
            break

    if not any_systems:
        return

    parts.append("<h2>Systems</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Name</th><th>Type</th>"
                 "<th>Long Name</th><th>Size</th></tr>")

    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        if not secs:
            continue
        for sec in secs:
            short = parse_system_short_name(sec.raw) or "(unnamed)"
            parts.append(f"<tr><td>{_esc(short)}</td><td>{_esc(label)}</td>"
                         f"<td></td><td>{len(sec.raw):,} bytes</td></tr>")

        # Config data sections
        current_type = None
        for sec_obj in prs.sections:
            if sec_obj.class_name == cls:
                current_type = cls
                continue
            if (not sec_obj.class_name and current_type == cls
                    and is_system_config_data(sec_obj.raw)):
                long_name = parse_system_long_name(sec_obj.raw) or ""
                wan_name = ""
                try:
                    wan_name = parse_system_wan_name(sec_obj.raw) or ""
                except Exception:
                    pass
                detail = long_name
                if wan_name:
                    detail += f" (WACN: {wan_name})"
                parts.append(
                    f"<tr><td></td><td>{_esc(label)} Config</td>"
                    f"<td>{_esc(detail)}</td>"
                    f"<td>{len(sec_obj.raw):,} bytes</td></tr>")

    parts.append("</table>")


def _add_group_sets(parts, prs):
    """Add talkgroup tables."""
    sets = _parse_group_sets(prs)
    if not sets:
        return

    total = sum(len(gs.groups) for gs in sets)
    parts.append(f"<h2>Group Sets ({len(sets)} sets, {total} talkgroups)</h2>")

    for gs in sets:
        n_scan = sum(1 for g in gs.groups if g.scan)
        n_tx = sum(1 for g in gs.groups if g.tx)
        parts.append(f"<h3>{_esc(gs.name)} "
                     f"({len(gs.groups)} TGs, {n_scan} scan, {n_tx} TX)</h3>")
        parts.append("<table>")
        parts.append("<tr><th>#</th><th>ID</th><th>Short Name</th>"
                     "<th>Long Name</th><th>TX</th><th>Scan</th></tr>")

        for i, grp in enumerate(gs.groups, 1):
            tx_badge = ("<span class='badge badge-tx'>TX</span>"
                        if grp.tx
                        else "<span class='badge badge-rx'>RX</span>")
            scan_badge = ("<span class='badge badge-scan'>Scan</span>"
                          if grp.scan else "")
            parts.append(
                f"<tr><td>{i}</td><td>{grp.group_id}</td>"
                f"<td>{_esc(grp.group_name)}</td>"
                f"<td>{_esc(grp.long_name)}</td>"
                f"<td>{tx_badge}</td><td>{scan_badge}</td></tr>")

        parts.append("</table>")


def _add_trunk_sets(parts, prs):
    """Add trunk frequency tables."""
    sets = _parse_trunk_sets(prs)
    if not sets:
        return

    total = sum(len(ts.channels) for ts in sets)
    parts.append(f"<h2>Trunk Sets ({len(sets)} sets, {total} frequencies)</h2>")

    for ts in sets:
        parts.append(f"<h3>{_esc(ts.name)} ({len(ts.channels)} frequencies, "
                     f"{ts.tx_min:.0f}-{ts.tx_max:.0f} MHz)</h3>")
        parts.append("<table>")
        parts.append("<tr><th>#</th><th>TX Freq (MHz)</th>"
                     "<th>RX Freq (MHz)</th><th>Mode</th></tr>")

        for i, ch in enumerate(ts.channels, 1):
            mode = "Simplex" if ch.tx_freq == ch.rx_freq else "Duplex"
            parts.append(
                f"<tr><td>{i}</td>"
                f"<td>{ch.tx_freq:.5f}</td>"
                f"<td>{ch.rx_freq:.5f}</td>"
                f"<td>{mode}</td></tr>")

        parts.append("</table>")


def _add_conv_sets(parts, prs):
    """Add conventional channel tables."""
    sets = _parse_conv_sets(prs)
    if not sets:
        return

    total = sum(len(cs.channels) for cs in sets)
    parts.append(f"<h2>Conv Sets ({len(sets)} sets, {total} channels)</h2>")

    for cs in sets:
        parts.append(f"<h3>{_esc(cs.name)} ({len(cs.channels)} channels)</h3>")
        parts.append("<table>")
        parts.append("<tr><th>#</th><th>Short Name</th><th>Long Name</th>"
                     "<th>TX Freq</th><th>RX Freq</th>"
                     "<th>TX Tone</th><th>RX Tone</th></tr>")

        for i, ch in enumerate(cs.channels, 1):
            parts.append(
                f"<tr><td>{i}</td>"
                f"<td>{_esc(ch.short_name)}</td>"
                f"<td>{_esc(ch.long_name)}</td>"
                f"<td>{ch.tx_freq:.5f}</td>"
                f"<td>{ch.rx_freq:.5f}</td>"
                f"<td>{_esc(ch.tx_tone)}</td>"
                f"<td>{_esc(ch.rx_tone)}</td></tr>")

        parts.append("</table>")


def _add_iden_sets(parts, prs):
    """Add IDEN set summary."""
    sets = _parse_iden_sets(prs)
    if not sets:
        return

    parts.append(f"<h2>IDEN Sets ({len(sets)} sets)</h2>")

    for iset in sets:
        active = [e for e in iset.elements if not e.is_empty()]
        fdma = sum(1 for e in active if not e.iden_type)
        tdma = sum(1 for e in active if e.iden_type)
        if fdma and tdma:
            mode = "mixed FDMA+TDMA"
        elif tdma:
            mode = "TDMA"
        else:
            mode = "FDMA"

        parts.append(f"<h3>{_esc(iset.name)} "
                     f"({len(active)}/16 active, {mode})</h3>")
        parts.append("<table>")
        parts.append("<tr><th>IDEN</th><th>Base Freq (MHz)</th>"
                     "<th>Mode</th><th>Spacing (kHz)</th>"
                     "<th>TX Offset (MHz)</th></tr>")

        for i, elem in enumerate(iset.elements):
            if elem.is_empty():
                continue
            e_mode = "TDMA" if elem.iden_type else "FDMA"
            base_mhz = elem.base_freq_hz / 1_000_000
            spacing_khz = elem.chan_spacing_hz / 1000
            offset = elem.tx_offset_mhz
            parts.append(
                f"<tr><td>{i}</td>"
                f"<td>{base_mhz:.5f}</td>"
                f"<td>{e_mode}</td>"
                f"<td>{spacing_khz:.2f}</td>"
                f"<td>{offset:+.1f}</td></tr>")

        parts.append("</table>")


def _add_radio_options(parts, prs):
    """Add radio options from platformConfig XML."""
    config = extract_platform_config(prs)
    if not config:
        return

    parts.append("<h2>Radio Options (platformConfig)</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Setting</th><th>Value</th></tr>")

    misc = config.get("miscConfig", {})
    audio = config.get("audioConfig", {})
    gps = config.get("gpsConfig", {})
    bt = config.get("bluetoothConfig", {})

    # Battery
    batt = misc.get("batteryType", "")
    if batt:
        batt_map = {"LITHIUM_ION_POLY": "Lithium Ion Poly", "NIMH": "NiMH",
                     "ALKALINE": "Alkaline", "PRIMARY_LITHIUM": "Primary Lithium"}
        parts.append(f"<tr><td>Battery Type</td>"
                     f"<td>{_esc(batt_map.get(batt, batt))}</td></tr>")

    # Audio
    speaker = audio.get("speakerMode", "")
    if speaker:
        parts.append(f"<tr><td>Speaker</td>"
                     f"<td>{'On' if speaker == 'ON' else 'Off'}</td></tr>")
    nc = audio.get("noiseCancellation", "")
    if nc:
        parts.append(f"<tr><td>Noise Cancellation</td>"
                     f"<td>{'On' if nc == 'ON' else 'Off'}</td></tr>")
    tones = audio.get("tones", "")
    if tones:
        parts.append(f"<tr><td>Tones</td>"
                     f"<td>{'On' if tones == 'ON' else 'Off'}</td></tr>")

    # GPS
    gps_mode = gps.get("gpsMode", "")
    if gps_mode:
        gps_type = gps.get("type", "")
        type_map = {"INTERNAL_GPS": "Internal", "EXTERNAL_GPS": "External"}
        label = "On" if gps_mode == "ON" else "Off"
        if gps_mode == "ON" and gps_type:
            label += f" ({type_map.get(gps_type, gps_type)})"
        parts.append(f"<tr><td>GPS</td><td>{_esc(label)}</td></tr>")

    # Bluetooth
    bt_admin = bt.get("btAdminMode", "")
    if bt_admin:
        bt_enable = bt.get("btMode", "")
        if bt_admin == "OFF":
            label = "Not Allowed"
        elif bt_enable == "ON":
            name = bt.get("friendlyName", "")
            label = "Enabled"
            if name:
                label += f" ({name})"
        else:
            label = "Allowed, Disabled"
        parts.append(f"<tr><td>Bluetooth</td><td>{_esc(label)}</td></tr>")

    parts.append("</table>")


def _add_binary_options(parts, prs):
    """Add binary option section summary."""
    mapped = []
    for cls_name, opt_map in OPTION_MAPS.items():
        sec = prs.get_section_by_class(cls_name)
        if sec is None:
            continue
        data = extract_section_data(sec)
        if data is None or not opt_map.fields:
            continue
        values = []
        for fd in opt_map.fields:
            val = read_field(data, fd)
            if val is not None:
                values.append((fd.display_name, str(val)))
        if values:
            mapped.append((opt_map.display_name, values))

    if not mapped:
        return

    parts.append("<h2>Binary Options</h2>")
    for section_name, values in mapped:
        parts.append(f"<h3>{_esc(section_name)}</h3>")
        parts.append("<table>")
        parts.append("<tr><th>Setting</th><th>Value</th></tr>")
        for name, val in values:
            parts.append(f"<tr><td>{_esc(name)}</td>"
                         f"<td>{_esc(val)}</td></tr>")
        parts.append("</table>")


def _add_capacity(parts, prs):
    """Add capacity summary with visual bars."""
    group_sets = _parse_group_sets(prs)
    trunk_sets = _parse_trunk_sets(prs)
    conv_sets = _parse_conv_sets(prs)

    total_tgs = sum(len(gs.groups) for gs in group_sets)
    total_freqs = sum(len(ts.channels) for ts in trunk_sets)
    total_convch = sum(len(cs.channels) for cs in conv_sets)

    if not (total_tgs or total_freqs or total_convch):
        return

    parts.append("<h2>Capacity Summary</h2>")
    parts.append("<table class='summary-table'>")

    # Typical XG-100P limits (approximate)
    limits = [
        ("Talkgroups", total_tgs, 2000),
        ("Trunk Frequencies", total_freqs, 500),
        ("Conv Channels", total_convch, 512),
        ("Group Sets", len(group_sets), 32),
        ("Trunk Sets", len(trunk_sets), 32),
        ("Conv Sets", len(conv_sets), 32),
    ]

    for label, used, limit in limits:
        if used == 0 and limit > 100:
            continue
        pct = min(used / limit * 100, 100) if limit > 0 else 0
        css_class = ""
        if pct > 90:
            css_class = " danger"
        elif pct > 70:
            css_class = " warn"
        bar = (f"<div class='capacity-bar'>"
               f"<div class='capacity-fill{css_class}' "
               f"style='width:{pct:.0f}%'></div></div>")
        parts.append(f"<tr><td>{label}</td>"
                     f"<td>{used} / {limit} {bar}</td></tr>")

    parts.append("</table>")


# ─── Summary Card ────────────────────────────────────────────────────

_CARD_CSS = """\
@page { size: letter; margin: 0.5in; }
body {
    font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    margin: 0; padding: 16px;
    color: #222; background: #fff;
    line-height: 1.3; font-size: 11px;
}
h1 { font-size: 16px; margin: 0 0 4px 0; border-bottom: 2px solid #333;
     padding-bottom: 4px; }
h2 { font-size: 12px; color: #444; margin: 10px 0 2px 0;
     border-bottom: 1px solid #ccc; padding-bottom: 2px; }
.meta { color: #888; font-size: 10px; margin-bottom: 8px; }
.card-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.card-section { flex: 1 1 45%; min-width: 280px; }
table {
    border-collapse: collapse; width: 100%;
    margin: 2px 0 6px 0; font-size: 10px;
}
th, td { border: 1px solid #ccc; padding: 2px 6px; text-align: left; }
th { background: #f0f0f0; font-weight: 600; }
tr:nth-child(even) { background: #f9f9f9; }
.badge { display: inline-block; padding: 0 4px; border-radius: 2px;
         font-size: 9px; font-weight: 600; }
.badge-tx { background: #d4edda; color: #155724; }
.summary-item { margin: 1px 0; }
.summary-label { font-weight: 600; display: inline-block; width: 100px; }
@media print {
    body { padding: 0; font-size: 10px; }
    .card-section { page-break-inside: avoid; }
}
"""


def generate_summary_card(prs, filepath=None, source_path=None):
    """Generate a compact HTML summary card for printing.

    Fits on one page. Shows:
    - Radio name and date
    - System names and IDs
    - Key frequencies
    - Important talkgroups (TX-enabled ones)
    - Zone/channel quick reference
    - CTCSS tones in use

    Args:
        prs: PRSFile object (already parsed)
        filepath: if given, write HTML to this file path
        source_path: original .PRS file path for display

    Returns:
        HTML string
    """
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append("<html lang='en'>")
    parts.append("<head>")
    parts.append("<meta charset='utf-8'>")

    # Title from blob preamble or file path
    bp = extract_blob_preamble(prs)
    personality_name = ""
    if bp and bp.filename:
        personality_name = bp.filename
    elif source_path:
        personality_name = Path(source_path).stem
    else:
        personality_name = "Radio"

    parts.append(f"<title>{_esc(personality_name)} - Reference Card</title>")
    parts.append(f"<style>{_CARD_CSS}</style>")
    parts.append("</head>")
    parts.append("<body>")

    # Header
    parts.append(f"<h1>{_esc(personality_name)} - Quick Reference</h1>")
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d")
    meta_parts = [f"Generated: {now}"]
    if source_path:
        meta_parts.append(f"Source: {_esc(Path(source_path).name)}")
    parts.append(f"<p class='meta'>{' | '.join(meta_parts)}</p>")

    parts.append("<div class='card-grid'>")

    # Left column: Systems + Talkgroups
    parts.append("<div class='card-section'>")
    _card_add_systems(parts, prs)
    _card_add_talkgroups(parts, prs)
    parts.append("</div>")

    # Right column: Channels + Frequencies + Tones
    parts.append("<div class='card-section'>")
    _card_add_channels(parts, prs)
    _card_add_summary_stats(parts, prs)
    parts.append("</div>")

    parts.append("</div>")
    parts.append("</body>")
    parts.append("</html>")

    html_str = "\n".join(parts)

    if filepath:
        Path(filepath).write_text(html_str, encoding="utf-8")

    return html_str


def _card_add_systems(parts, prs):
    """Add systems summary to card."""
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    any_systems = False
    for cls, label in system_types:
        if prs.get_sections_by_class(cls):
            any_systems = True
            break

    if not any_systems:
        return

    parts.append("<h2>Systems</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Name</th><th>Type</th></tr>")
    for cls, label in system_types:
        for sec in prs.get_sections_by_class(cls):
            name = parse_system_short_name(sec.raw) or "(unnamed)"
            parts.append(f"<tr><td>{_esc(name)}</td>"
                         f"<td>{_esc(label)}</td></tr>")
    parts.append("</table>")


def _card_add_talkgroups(parts, prs):
    """Add TX-enabled talkgroups to card (the ones you can talk on)."""
    group_sets = _parse_group_sets(prs)
    if not group_sets:
        return

    tx_groups = []
    for gs in group_sets:
        for grp in gs.groups:
            if grp.tx:
                tx_groups.append((gs.name, grp))

    if not tx_groups:
        return

    total_tgs = sum(len(gs.groups) for gs in group_sets)
    parts.append(f"<h2>TX Talkgroups ({len(tx_groups)}/{total_tgs})</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Set</th><th>ID</th><th>Name</th></tr>")
    for set_name, grp in tx_groups:
        parts.append(
            f"<tr><td>{_esc(set_name)}</td>"
            f"<td>{grp.group_id}</td>"
            f"<td>{_esc(grp.group_name)}</td></tr>")
    parts.append("</table>")


def _card_add_channels(parts, prs):
    """Add conventional channel table to card."""
    conv_sets = _parse_conv_sets(prs)
    if not conv_sets:
        return

    total = sum(len(cs.channels) for cs in conv_sets)
    parts.append(f"<h2>Conventional Channels ({total})</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Set</th><th>Name</th><th>TX</th>"
                 "<th>RX</th><th>Tone</th></tr>")
    for cs in conv_sets:
        for ch in cs.channels:
            tone = ch.tx_tone or ""
            tx_badge = ""
            if ch.tx:
                tx_badge = " <span class='badge badge-tx'>TX</span>"
            parts.append(
                f"<tr><td>{_esc(cs.name)}</td>"
                f"<td>{_esc(ch.short_name)}{tx_badge}</td>"
                f"<td>{ch.tx_freq:.4f}</td>"
                f"<td>{ch.rx_freq:.4f}</td>"
                f"<td>{_esc(tone)}</td></tr>")
    parts.append("</table>")


def _card_add_summary_stats(parts, prs):
    """Add compact stats summary to card."""
    from .validation import compute_statistics
    stats = compute_statistics(prs)

    parts.append("<h2>Summary</h2>")

    ch = stats['channels']
    parts.append(f"<p class='summary-item'>"
                 f"<span class='summary-label'>Channels:</span>"
                 f"{ch['total']}</p>")

    bands = stats.get('freq_bands', {})
    if bands:
        band_strs = [f"{band}: {count}"
                     for band, count in sorted(bands.items(),
                                               key=lambda x: -x[1])]
        parts.append(f"<p class='summary-item'>"
                     f"<span class='summary-label'>Bands:</span>"
                     f"{', '.join(band_strs)}</p>")

    tg = stats.get('talkgroup_analysis', {})
    if tg.get('total', 0) > 0:
        parts.append(f"<p class='summary-item'>"
                     f"<span class='summary-label'>TG TX/Scan:</span>"
                     f"{tg['tx_enabled']}/{tg['total']} TX, "
                     f"{tg['scan_enabled']}/{tg['total']} scan</p>")

    tones = stats.get('ctcss_tones', {})
    if tones:
        tone_strs = [f"{t} ({c})" for t, c
                     in sorted(tones.items(), key=lambda x: -x[1])]
        parts.append(f"<p class='summary-item'>"
                     f"<span class='summary-label'>Tones:</span>"
                     f"{', '.join(tone_strs)}</p>")
