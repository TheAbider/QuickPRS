"""Shared CSV export functions for PRS personality data.

Used by both CLI (cmd_export_csv) and GUI (app.export_csv) to avoid
duplicating the export logic in two places.
"""

import csv
import logging

logger = logging.getLogger("quickprs")
from .option_maps import (
    extract_platform_config, extract_blob_preamble,
    XML_FIELD_INDEX, OOR_ALERT_VALUES,
)
from .record_types import (
    parse_system_short_name, parse_system_long_name,
    parse_system_wan_name, is_system_config_data,
    parse_ecc_entries, parse_preferred_section,
)


def export_group_sets(path, sets):
    """Write GROUP_SET.csv from a list of P25GroupSet objects.

    Returns description string like 'GROUP_SET.csv (241 groups)'.
    """
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Set", "GroupID", "ShortName", "LongName",
                     "TX", "RX", "Scan"])
        for gset in sets:
            for g in gset.groups:
                w.writerow([gset.name, g.group_id, g.group_name,
                            g.long_name,
                            "Y" if g.tx else "N",
                            "Y" if g.rx else "N",
                            "Y" if g.scan else "N"])
    total = sum(len(s.groups) for s in sets)
    return f"GROUP_SET.csv ({total} groups)"


def export_trunk_sets(path, sets):
    """Write TRK_SET.csv from a list of TrunkSet objects."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Set", "TxFreq", "RxFreq", "TxMin", "TxMax"])
        for tset in sets:
            for ch in tset.channels:
                w.writerow([tset.name, f"{ch.tx_freq:.5f}",
                            f"{ch.rx_freq:.5f}",
                            f"{tset.tx_min:.1f}", f"{tset.tx_max:.1f}"])
    total = sum(len(s.channels) for s in sets)
    return f"TRK_SET.csv ({total} channels)"


def export_conv_sets(path, sets):
    """Write CONV_SET.csv from a list of ConvSet objects."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Set", "ShortName", "TxFreq", "RxFreq",
                     "TxTone", "RxTone", "LongName"])
        for cset in sets:
            for ch in cset.channels:
                w.writerow([cset.name, ch.short_name,
                            f"{ch.tx_freq:.5f}", f"{ch.rx_freq:.5f}",
                            ch.tx_tone, ch.rx_tone, ch.long_name])
    total = sum(len(s.channels) for s in sets)
    return f"CONV_SET.csv ({total} channels)"


def export_iden_sets(path, sets):
    """Write IDEN_SET.csv from a list of IdenDataSet objects."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Set", "Slot", "BaseFreqMHz", "Spacing", "BW",
                     "TxOffset", "Type"])
        for iset in sets:
            for i, e in enumerate(iset.elements):
                if e.is_empty():
                    continue
                w.writerow([iset.name, i,
                            f"{e.base_freq_hz / 1e6:.5f}",
                            e.chan_spacing_hz, e.bandwidth_hz,
                            f"{e.tx_offset_mhz:.4f}",
                            "TDMA" if e.iden_type else "FDMA"])
    return f"IDEN_SET.csv ({len(sets)} sets)"


def export_options(path, prs):
    """Write OPTIONS.csv from a PRSFile's platformConfig XML + blob metadata.

    Returns description string or None if no platformConfig found.
    """
    config = extract_platform_config(prs)
    if not config:
        return None

    rows = flatten_config(config)

    # Add blob preamble fields (OOR Alert, filename, author)
    bp = extract_blob_preamble(prs)
    if bp:
        rows.append(("File Metadata", "Repeated OOR Alert Interval",
                      OOR_ALERT_VALUES.get(bp.oor_alert_interval,
                                           str(bp.oor_alert_interval))))
        if bp.filename:
            rows.append(("File Metadata", "RPM Filename", bp.filename))
        if bp.username:
            rows.append(("File Metadata", "Author", bp.username))

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Category", "Field", "Value"])
        for cat, field, val in rows:
            w.writerow([cat, field, val])
    return f"OPTIONS.csv ({len(rows)} fields)"


def export_systems(path, prs):
    """Write SYSTEMS.csv from a PRSFile's system sections.

    Returns description string or None if no systems found.
    """
    rows = collect_system_info(prs)
    if not rows:
        return None

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["ShortName", "Type", "LongName", "WACN"])
        for row in rows:
            w.writerow(row)
    return f"SYSTEMS.csv ({len(rows)} systems)"


def export_ecc(path, prs):
    """Write ECC.csv from a PRSFile's system config sections.

    Returns description string or None if no ECC entries found.
    """
    rows = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            sname = parse_system_long_name(sec.raw) or "Unknown"
            ecc_count, entries, iden_name = parse_ecc_entries(sec.raw)
            for entry in entries:
                rows.append((sname, entry.entry_type, entry.system_id,
                             entry.channel_ref1, entry.channel_ref2,
                             iden_name or ""))

    if not rows:
        return None

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["System", "Type", "SysID", "ChRef1", "ChRef2",
                     "IdenSet"])
        for row in rows:
            w.writerow(row)
    return f"ECC.csv ({len(rows)} entries)"


def export_preferred(path, prs):
    """Write PREFERRED.csv from CPreferredSystemTableEntry sections.

    Returns description string or None if no preferred entries found.
    """
    rows = []
    pref_secs = prs.get_sections_by_class("CPreferredSystemTableEntry")
    for sec in pref_secs:
        try:
            entries, iden_name, _, chain_name, chain_type = \
                parse_preferred_section(sec.raw)
            for entry in entries:
                rows.append((entry.entry_type, entry.system_id,
                             entry.field1, entry.field2,
                             iden_name or "", chain_name or ""))
        except Exception as e:
            logger.debug("Could not parse preferred section: %s", e)

    if not rows:
        return None

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Type", "SysID", "Priority", "Sequence",
                     "IdenSet", "ChainTo"])
        for row in rows:
            w.writerow(row)
    return f"PREFERRED.csv ({len(rows)} entries)"


def flatten_config(config, prefix="", category=""):
    """Flatten nested platform config dict into (category, field, value) tuples."""
    _CAT_MAP = {
        "audioConfig": "Audio Settings",
        "miscConfig": "Misc Settings",
        "gpsConfig": "GPS Settings",
        "bluetoothConfig": "Bluetooth Settings",
        "accessoryConfig": "Accessory Options",
        "manDownConfig": "Accessory Options",
        "progButtons": "Programmable Buttons",
        "accessoryButtons": "Accessory Buttons",
        "shortMenu": "Short Menu",
        "TimeDateCfg": "Clock Settings",
    }
    rows = []

    for key, val in config.items():
        if isinstance(val, dict):
            sub_cat = _CAT_MAP.get(key, category or "Platform Config")
            rows.extend(flatten_config(val, f"{prefix}{key}.", sub_cat))
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    sub_cat = _CAT_MAP.get(key, category or "Platform Config")
                    rows.extend(
                        flatten_config(item, f"{prefix}{key}[{i}].",
                                       sub_cat))
        else:
            cat = category or "Platform Config"
            field_name = f"{prefix}{key}"
            display_val = str(val)

            # Look up friendly name from field catalog
            tag = prefix.rstrip(".")
            if "[" in tag:
                tag = tag[:tag.index("[")]
            field_def = XML_FIELD_INDEX.get((tag, key))
            if field_def:
                field_name = field_def.display_name
                cat = field_def.category
                if field_def.display_map:
                    display_val = field_def.display_map.get(
                        display_val, display_val)
                elif field_def.field_type == "onoff":
                    display_val = ("Enabled" if display_val == "ON"
                                   else "Disabled" if display_val == "OFF"
                                   else display_val)

            rows.append((cat, field_name, display_val))
    return rows


def collect_system_info(prs):
    """Collect system metadata for CSV export.

    Returns list of (short_name, type, long_name, wacn) tuples.
    """
    rows = []
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    for cls, label in system_types:
        secs = prs.get_sections_by_class(cls)
        for sec in secs:
            short = parse_system_short_name(sec.raw) or ""
            rows.append((short, label, "", ""))

    # Add system config data rows (long names, WACN)
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            ln = parse_system_long_name(sec.raw) or ""
            try:
                wan = parse_system_wan_name(sec.raw) or ""
            except Exception as e:
                logger.debug("Could not parse WACN from config section: %s", e)
                wan = ""
            if ln:
                rows.append(("", "Config", ln, wan))

    return rows
