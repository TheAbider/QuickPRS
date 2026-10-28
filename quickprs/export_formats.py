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
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "RxDtcsCode",
    "CrossMode", "Mode", "TStep", "Skip", "Comment", "URCALL",
    "RPT1CALL", "RPT2CALL",
]


def dcs_parts(tone):
    """(code, polarity) of a DCS tone string such as 'D023', 'D023N' or
    'D023I' (inverted): ('023', 'N') or ('023', 'R'). None if not DCS."""
    if not tone or not tone.upper().startswith("D"):
        return None
    body = tone[1:].upper()
    polarity = "N"
    if body[-1:] in ("N", "I", "R"):
        polarity = "N" if body[-1] == "N" else "R"
        body = body[:-1]
    if not body.isdigit():
        return None
    return body.zfill(3), polarity


def _tone_to_chirp(tx_tone, rx_tone):
    """CHIRP's tone columns for a channel's TX and RX tones.

    CHIRP's TSQL mode sends and expects cToneFreq, and its DTCS mode uses
    DtcsCode both ways, so they only fit a channel whose two tones are
    the same. Anything else is Cross mode: CrossMode names the TX and RX
    halves, TX uses rToneFreq or DtcsCode, RX cToneFreq or RxDtcsCode.
    """
    tx_dcs, rx_dcs = dcs_parts(tx_tone), dcs_parts(rx_tone)
    tx_kind = "DTCS" if tx_dcs else ("Tone" if tx_tone else "")
    rx_kind = "DTCS" if rx_dcs else ("Tone" if rx_tone else "")
    fields = {
        "rToneFreq": tx_tone if tx_kind == "Tone" else "88.5",
        "cToneFreq": rx_tone if rx_kind == "Tone" else "88.5",
        "DtcsCode": tx_dcs[0] if tx_dcs else "023",
        "RxDtcsCode": rx_dcs[0] if rx_dcs else "023",
        "DtcsPolarity": ((tx_dcs[1] if tx_dcs else "N")
                         + (rx_dcs[1] if rx_dcs else "N")),
        "CrossMode": "Tone->Tone",
    }
    if not tx_kind and not rx_kind:
        fields["Tone"] = ""
    elif tx_kind == "Tone" and not rx_kind:
        fields["Tone"] = "Tone"
    elif tx_kind == rx_kind == "Tone" and tx_tone == rx_tone:
        fields["Tone"] = "TSQL"
    elif tx_kind == rx_kind == "DTCS" and tx_dcs[0] == rx_dcs[0]:
        fields["Tone"] = "DTCS"
    else:
        fields["Tone"] = "Cross"
        fields["CrossMode"] = f"{tx_kind}->{rx_kind}"
    return fields


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

            if not ch.tx:
                duplex = "off"       # CHIRP: transmit inhibited
                offset = "0.000000"
            elif abs(diff) < 0.0001:
                duplex = ""
                offset = "0.000000"
            elif diff > 0:
                duplex = "+"
                offset = f"{abs(diff):.6f}"
            else:
                duplex = "-"
                offset = f"{abs(diff):.6f}"

            rows.append({
                "Location": str(location),
                "Name": ch.short_name,
                "Frequency": f"{rx:.6f}",
                "Duplex": duplex,
                "Offset": offset,
                **_tone_to_chirp(ch.tx_tone, ch.rx_tone),
                "Mode": "NFM" if ch.narrowband else "FM",
                "TStep": "5.00",
                "Skip": "" if ch.scan else "S",
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
            # The scanner listens on the receive frequency, so it takes the
            # tone the radio expects there, not the one it transmits
            tone_str = ""
            code_str = ""
            dcs = dcs_parts(ch.rx_tone)
            if dcs:
                code_str = dcs[0]
            elif ch.rx_tone:
                tone_str = ch.rx_tone

            rows.append({
                "System": cset.name,
                "Department": cset.name,
                "Channel": ch.short_name,
                "Frequency": f"{ch.rx_freq:.4f}",
                "Modulation": "NFM" if ch.narrowband else "FM",
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
