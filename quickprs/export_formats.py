"""Export to third-party radio tool formats.

Supported formats:
  - CHIRP CSV (conventional channels for Baofeng, Kenwood, Yaesu, etc.)
  - Uniden Sentinel CSV (conventional channels for Uniden scanners)
  - SDRTrunk CSV (P25 talkgroups for SDRTrunk SDR software)
  - DSD+ frequency list (trunk frequencies for DSD+/SDR#)
  - Markdown (human-readable documentation of radio configuration)

Each exporter accepts a parsed PRSFile and writes to the given filepath.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from .prs_parser import PRSFile
from .record_types import (
    parse_class_header, parse_trunk_channel_section,
    parse_conv_channel_section, parse_group_section, parse_iden_section,
    parse_system_short_name, parse_system_long_name, parse_system_wan_name,
    is_system_config_data, parse_ecc_entries, parse_sets_from_sections,
)
from .option_maps import extract_platform_config, extract_blob_preamble

logger = logging.getLogger("quickprs")


# ─── Internal helpers ─────────────────────────────────────────────────

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


def _filter_sets(sets, names):
    """Filter sets by name list (case-insensitive). None = all."""
    if names is None:
        return sets
    name_set = {n.strip().upper() for n in names}
    return [s for s in sets if s.name.upper() in name_set]


# ─── CHIRP CSV Export ─────────────────────────────────────────────────

_CHIRP_COLUMNS = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode",
    "TStep", "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL",
]


def _tone_to_chirp(tx_tone, rx_tone):
    """Convert PRS tone strings to CHIRP Tone/rToneFreq/cToneFreq/DtcsCode.

    Returns: (tone_mode, rtonefreq, ctonefreq, dtcscode)
    """
    if not tx_tone and not rx_tone:
        return ("", "88.5", "88.5", "023")

    # DCS tones start with "D"
    if tx_tone and tx_tone.startswith("D"):
        code = tx_tone[1:]
        return ("DTCS", "88.5", "88.5", code)

    if tx_tone and rx_tone:
        # Both set = TSQL (carrier squelch with tone)
        return ("TSQL", tx_tone, rx_tone, "023")

    if tx_tone:
        # TX only = Tone (encode only)
        return ("Tone", tx_tone, "88.5", "023")

    # RX only (uncommon but possible)
    return ("TSQL", rx_tone, rx_tone, "023")


def export_chirp_csv(prs, filepath, sets=None):
    """Export conventional channels to CHIRP-compatible CSV format.

    CHIRP CSV columns:
    Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,
    DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL

    Args:
        prs: parsed PRSFile
        filepath: output CSV path
        sets: list of set names to export (None = all conv sets)

    Returns:
        Number of channels exported.
    """
    conv_sets = _parse_conv_sets(prs)
    conv_sets = _filter_sets(conv_sets, sets)

    filepath = Path(filepath)
    location = 0
    rows = []

    for cset in conv_sets:
        for ch in cset.channels:
            # Calculate duplex and offset from TX/RX
            tx = ch.tx_freq
            rx = ch.rx_freq
            diff = round(tx - rx, 6)

            if abs(diff) < 0.0001:
                duplex = ""
                offset = "0.000000"
            elif diff > 0:
                duplex = "+"
                offset = f"{abs(diff):.6f}"
            else:
                duplex = "-"
                offset = f"{abs(diff):.6f}"

            tone_mode, rtone, ctone, dtcs = _tone_to_chirp(
                ch.tx_tone, ch.rx_tone)

            rows.append({
                "Location": str(location),
                "Name": ch.short_name,
                "Frequency": f"{rx:.6f}",
                "Duplex": duplex,
                "Offset": offset,
                "Tone": tone_mode,
                "rToneFreq": rtone,
                "cToneFreq": ctone,
                "DtcsCode": dtcs,
                "DtcsPolarity": "NN",
                "Mode": "FM",
                "TStep": "5.00",
                "Skip": "",
                "Comment": ch.long_name or f"{cset.name} {ch.short_name}",
                "URCALL": "",
                "RPT1CALL": "",
                "RPT2CALL": "",
            })
            location += 1

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_CHIRP_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    return len(rows)


# ─── Uniden Sentinel CSV Export ───────────────────────────────────────

_UNIDEN_COLUMNS = [
    "System", "Department", "Channel", "Frequency", "Modulation",
    "Tone", "Code", "Lockout", "Priority",
]


def export_uniden_csv(prs, filepath, sets=None):
    """Export conventional channels to Uniden Sentinel-compatible CSV format.

    Uniden CSV columns:
    System,Department,Channel,Frequency,Modulation,Tone,Code,Lockout,Priority

    Args:
        prs: parsed PRSFile
        filepath: output CSV path
        sets: list of set names to export (None = all conv sets)

    Returns:
        Number of channels exported.
    """
    conv_sets = _parse_conv_sets(prs)
    conv_sets = _filter_sets(conv_sets, sets)

    filepath = Path(filepath)
    rows = []

    for cset in conv_sets:
        for ch in cset.channels:
            tone_str = ""
            code_str = ""
            if ch.tx_tone:
                if ch.tx_tone.startswith("D"):
                    code_str = ch.tx_tone[1:]
                else:
                    tone_str = ch.tx_tone

            rows.append({
                "System": cset.name,
                "Department": cset.name,
                "Channel": ch.short_name,
                "Frequency": f"{ch.rx_freq:.4f}",
                "Modulation": "NFM",
                "Tone": tone_str,
                "Code": code_str,
                "Lockout": "Unlocked",
                "Priority": "",
            })

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_UNIDEN_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    return len(rows)


# ─── SDRTrunk Talkgroup CSV Export ────────────────────────────────────

_SDRTRUNK_COLUMNS = [
    "Decimal", "Hex", "Alpha Tag", "Mode", "Description", "Tag",
    "Category",
]


def export_sdrtrunk_csv(prs, filepath, sets=None):
    """Export P25 talkgroups to SDRTrunk-compatible talkgroup CSV format.

    SDRTrunk talkgroup CSV:
    Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category

    Args:
        prs: parsed PRSFile
        filepath: output CSV path
        sets: list of set names to export (None = all group sets)

    Returns:
        Number of talkgroups exported.
    """
    group_sets = _parse_group_sets(prs)
    group_sets = _filter_sets(group_sets, sets)

    filepath = Path(filepath)
    rows = []

    for gset in group_sets:
        for grp in gset.groups:
            rows.append({
                "Decimal": str(grp.group_id),
                "Hex": f"{grp.group_id:04X}",
                "Alpha Tag": grp.group_name,
                "Mode": "D",
                "Description": grp.long_name or grp.group_name,
                "Tag": "Public Safety" if grp.tx else "Other",
                "Category": gset.name,
            })

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_SDRTRUNK_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    return len(rows)


# ─── DSD+ Frequency Export ────────────────────────────────────────────

def export_dsd_freqs(prs, filepath, sets=None):
    """Export trunk frequencies to DSD+/SDR# compatible format.

    Simple text file with one frequency per line in Hz.

    Args:
        prs: parsed PRSFile
        filepath: output file path
        sets: list of set names to export (None = all trunk sets)

    Returns:
        Number of frequencies exported.
    """
    trunk_sets = _parse_trunk_sets(prs)
    trunk_sets = _filter_sets(trunk_sets, sets)

    filepath = Path(filepath)
    freqs = []

    for tset in trunk_sets:
        for ch in tset.channels:
            # DSD+ expects frequency in Hz
            freq_hz = int(round(ch.rx_freq * 1e6))
            freqs.append(freq_hz)

    # Remove duplicates and sort
    freqs = sorted(set(freqs))

    with open(filepath, 'w', encoding='utf-8') as f:
        for freq in freqs:
            f.write(f"{freq}\n")

    return len(freqs)


# ─── Markdown Export ──────────────────────────────────────────────────

def export_markdown(prs, filepath=None):
    """Export radio personality as a formatted Markdown document.

    Includes tables for systems, talkgroups, channels, frequencies,
    and radio options/metadata.

    Args:
        prs: parsed PRSFile
        filepath: output path (if None, just return the string)

    Returns:
        The markdown string.
    """
    lines = []

    # Title
    bp = extract_blob_preamble(prs)
    title = "Radio Configuration"
    if bp and bp.filename:
        title = bp.filename
    lines.append(f"# {title}")
    lines.append("")

    # Metadata
    lines.append("## File Information")
    lines.append("")
    lines.append(f"- **File**: {Path(prs.filepath).name}")
    lines.append(f"- **Size**: {prs.file_size:,} bytes")
    lines.append(f"- **Sections**: {len(prs.sections)}")
    if bp:
        if bp.filename:
            lines.append(f"- **Personality Name**: {bp.filename}")
        if bp.username:
            lines.append(f"- **Author**: {bp.username}")
        lines.append(f"- **OOR Alert**: {bp.oor_display}")
    lines.append(f"- **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Systems
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    sys_rows = []
    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        for sec in secs:
            short = parse_system_short_name(sec.raw) or "?"
            sys_rows.append((short, label))

    if sys_rows:
        lines.append("## Systems")
        lines.append("")
        lines.append("| Name | Type |")
        lines.append("|------|------|")
        for short, label in sys_rows:
            lines.append(f"| {short} | {label} |")
        lines.append("")

    # Talkgroups
    group_sets = _parse_group_sets(prs)
    if group_sets:
        lines.append("## Talkgroups")
        lines.append("")
        for gset in group_sets:
            lines.append(f"### {gset.name}")
            lines.append("")
            lines.append("| ID | Short Name | Long Name | Scan | TX |")
            lines.append("|---:|------------|-----------|:----:|:--:|")
            for grp in gset.groups:
                scan = "Y" if grp.scan else "N"
                tx = "Y" if grp.tx else "N"
                lines.append(
                    f"| {grp.group_id} | {grp.group_name} "
                    f"| {grp.long_name} | {scan} | {tx} |")
            lines.append("")

    # Trunk Frequencies
    trunk_sets = _parse_trunk_sets(prs)
    if trunk_sets:
        lines.append("## Trunk Frequencies")
        lines.append("")
        for tset in trunk_sets:
            lines.append(f"### {tset.name}")
            lines.append("")
            lines.append("| TX (MHz) | RX (MHz) |")
            lines.append("|---------:|---------:|")
            for ch in tset.channels:
                lines.append(f"| {ch.tx_freq:.4f} | {ch.rx_freq:.4f} |")
            lines.append("")

    # Conventional Channels
    conv_sets = _parse_conv_sets(prs)
    if conv_sets:
        lines.append("## Conventional Channels")
        lines.append("")
        for cset in conv_sets:
            lines.append(f"### {cset.name}")
            lines.append("")
            lines.append("| Name | TX (MHz) | RX (MHz) | TX Tone | RX Tone "
                         "| Long Name |")
            lines.append("|------|--------:|---------:|---------|---------|"
                         "-----------|")
            for ch in cset.channels:
                tx_t = ch.tx_tone or "-"
                rx_t = ch.rx_tone or "-"
                ln = ch.long_name or "-"
                lines.append(
                    f"| {ch.short_name} | {ch.tx_freq:.4f} "
                    f"| {ch.rx_freq:.4f} | {tx_t} | {rx_t} | {ln} |")
            lines.append("")

    # IDEN Sets
    iden_sets = _parse_iden_sets(prs)
    if iden_sets:
        lines.append("## IDEN Sets")
        lines.append("")
        for iset in iden_sets:
            lines.append(f"### {iset.name}")
            lines.append("")
            lines.append("| Slot | Base Freq (MHz) | Spacing | BW | "
                         "TX Offset | Type |")
            lines.append("|-----:|----------------:|--------:|---:|"
                         "---------:|------|")
            for i, e in enumerate(iset.elements):
                if e.is_empty():
                    continue
                freq_mhz = e.base_freq_hz / 1e6
                iden_type = "TDMA" if e.iden_type else "FDMA"
                lines.append(
                    f"| {i} | {freq_mhz:.5f} | {e.chan_spacing_hz} "
                    f"| {e.bandwidth_hz} | {e.tx_offset_mhz:.4f} "
                    f"| {iden_type} |")
            lines.append("")

    md = "\n".join(lines)

    if filepath is not None:
        filepath = Path(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md)

    return md
