"""JSON export and import for PRS personality files.

Export: converts a parsed PRSFile into a structured JSON document with all
decoded data (personality, systems, trunk/group/conv/IDEN sets, WAN entries,
platform config).

Import: reads a JSON document and creates a valid PRS file from its contents,
using the injector pipeline to build the binary structure.
"""

import json
import logging
from pathlib import Path

from .prs_parser import parse_prs
from .record_types import (
    parse_personality_section,
    parse_trunk_channel_section,
    parse_group_section,
    parse_conv_channel_section,
    parse_p25_conv_channel_section,
    parse_iden_section,
    parse_wan_section, parse_wan_opts_section,
    parse_system_short_name, parse_system_long_name,
    parse_system_wan_name, parse_system_set_refs,
    is_system_config_data, parse_ecc_entries,
    parse_sets_from_sections,
)
from .option_maps import extract_platform_config

logger = logging.getLogger("quickprs")


# ─── Export: PRS → dict → JSON ──────────────────────────────────────


def _parse_sets(prs, data_cls, set_cls, parser_func):
    """Parse a set type from PRS sections. Returns list or []."""
    data_sec = prs.get_section_by_class(data_cls)
    set_sec = prs.get_section_by_class(set_cls)
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw, parser_func)


def _trunk_set_to_dict(tset):
    """Convert a TrunkSet to a JSON-friendly dict."""
    channels = []
    for ch in tset.channels:
        channels.append({
            "tx_freq": round(ch.tx_freq, 6),
            "rx_freq": round(ch.rx_freq, 6),
        })
    return {
        "name": tset.name,
        "channels": channels,
        "tx_min": tset.tx_min,
        "tx_max": tset.tx_max,
        "rx_min": tset.rx_min,
        "rx_max": tset.rx_max,
    }


def _group_set_to_dict(gset):
    """Convert a P25GroupSet to a JSON-friendly dict."""
    groups = []
    for g in gset.groups:
        groups.append({
            "id": g.group_id,
            "short_name": g.group_name,
            "long_name": g.long_name,
            "tx": g.tx,
            "scan": g.scan,
            "rx": g.rx,
        })
    return {
        "name": gset.name,
        "scan_list_size": gset.scan_list_size,
        "system_id": gset.system_id,
        "groups": groups,
    }


def _conv_set_to_dict(cset):
    """Convert a ConvSet to a JSON-friendly dict."""
    channels = []
    for ch in cset.channels:
        d = {
            "short_name": ch.short_name,
            "tx_freq": round(ch.tx_freq, 6),
            "rx_freq": round(ch.rx_freq, 6),
            "long_name": ch.long_name,
            "tx": ch.tx,
            "rx": ch.rx,
            "scan": ch.scan,
        }
        if ch.tx_tone:
            d["tx_tone"] = ch.tx_tone
        if ch.rx_tone:
            d["rx_tone"] = ch.rx_tone
        if ch.narrowband:
            d["narrowband"] = True
        channels.append(d)
    result = {
        "name": cset.name,
        "channels": channels,
    }
    if cset.tx_min != 0.0:
        result["tx_min"] = cset.tx_min
        result["tx_max"] = cset.tx_max
        result["rx_min"] = cset.rx_min
        result["rx_max"] = cset.rx_max
    return result


def _p25_conv_set_to_dict(cset):
    """Convert a P25ConvSet to a JSON-friendly dict."""
    channels = []
    for ch in cset.channels:
        d = {
            "short_name": ch.short_name,
            "tx_freq": round(ch.tx_freq, 6),
            "rx_freq": round(ch.rx_freq, 6),
            "long_name": ch.long_name,
            "tx": ch.tx,
            "rx": ch.rx,
            "scan": ch.scan,
        }
        if ch.nac_tx:
            d["nac_tx"] = ch.nac_tx
        if ch.nac_rx:
            d["nac_rx"] = ch.nac_rx
        channels.append(d)
    return {
        "name": cset.name,
        "channels": channels,
        "tx_min": cset.tx_min,
        "tx_max": cset.tx_max,
        "rx_min": cset.rx_min,
        "rx_max": cset.rx_max,
        "group_set_ref": cset.group_set_ref,
    }


def _iden_set_to_dict(iset):
    """Convert an IdenDataSet to a JSON-friendly dict."""
    elements = []
    for elem in iset.elements:
        if elem.is_empty():
            continue
        elements.append({
            "chan_spacing_hz": elem.chan_spacing_hz,
            "bandwidth_hz": elem.bandwidth_hz,
            "base_freq_hz": elem.base_freq_hz,
            "tx_offset_mhz": round(elem.tx_offset_mhz, 1),
            "iden_type": "TDMA" if elem.iden_type else "FDMA",
        })
    return {
        "name": iset.name,
        "elements": elements,
    }


def _wan_entry_to_dict(entry):
    """Convert a P25TrkWanEntry to a JSON-friendly dict."""
    return {
        "wan_name": entry.wan_name.strip(),
        "wacn": entry.wacn,
        "system_id": entry.system_id,
    }


def _config_to_sys_dict(cfg_raw, sys_type):
    """Extract system info from a single config data section."""
    sys_dict = {"type": sys_type}

    long_name = parse_system_long_name(cfg_raw)
    if long_name:
        sys_dict["long_name"] = long_name

    trunk_set, group_set = parse_system_set_refs(cfg_raw)
    if trunk_set:
        sys_dict["trunk_set"] = trunk_set
    if group_set:
        sys_dict["group_set"] = group_set

    try:
        wan_name = parse_system_wan_name(cfg_raw)
        if wan_name:
            sys_dict["wan_name"] = wan_name.strip()
    except Exception:
        pass

    ecc_count, ecc_entries, iden_name = parse_ecc_entries(cfg_raw)
    if ecc_count > 0:
        sys_dict["ecc_count"] = ecc_count
    if iden_name:
        sys_dict["iden_set"] = iden_name

    return sys_dict


def _collect_systems(prs):
    """Collect all system information into a list of dicts.

    Walks sections in file order. Each system header (CP25TrkSystem,
    CConvSystem, CP25ConvSystem) is followed by one or more config data
    sections. The first config is the primary system; subsequent configs
    are chained inline systems (until the next header or non-config section).
    """
    systems = []
    system_class_map = {
        'CP25TrkSystem': 'P25Trunked',
        'CConvSystem': 'Conventional',
        'CP25ConvSystem': 'P25Conv',
    }

    current_type = None
    current_name = None

    for sec in prs.sections:
        if sec.class_name in system_class_map:
            current_type = system_class_map[sec.class_name]
            current_name = parse_system_short_name(sec.raw) or ""
        elif (not sec.class_name and is_system_config_data(sec.raw)
              and current_type is not None):
            sys_dict = _config_to_sys_dict(sec.raw, current_type)
            # Use the header short name for the first config after a header
            if current_name is not None:
                sys_dict["name"] = current_name
                current_name = None  # consumed
            else:
                # Chained inline system — derive name from long_name
                ln = sys_dict.get("long_name", "")
                sys_dict["name"] = ln[:8] if ln else ""
            systems.append(sys_dict)
        elif sec.class_name and sec.class_name not in (
            'CPreferredSystemTableEntry',
        ):
            # Non-config named section breaks the chain
            current_type = None
            current_name = None

    return systems


def prs_to_dict(prs):
    """Convert a parsed PRSFile to a nested dict suitable for JSON export.

    Args:
        prs: PRSFile object (from parse_prs)

    Returns:
        dict with keys: personality, systems, trunk_sets, group_sets,
        conv_sets, p25_conv_sets, iden_sets, wan_entries, options
    """
    result = {}

    # Personality metadata
    pers_sec = prs.get_section_by_class("CPersonality")
    if pers_sec:
        p = parse_personality_section(pers_sec.raw)
        result["personality"] = {
            "filename": p.filename,
            "saved_by": p.saved_by,
            "version_str": p.version_str,
            "guid": p.guid,
            "platform": p.platform,
            "save_date": p.save_date,
            "save_time": p.save_time,
        }

    # Systems
    systems = _collect_systems(prs)
    if systems:
        result["systems"] = systems

    # Trunk sets
    trunk_sets = _parse_sets(prs, "CTrunkChannel", "CTrunkSet",
                             parse_trunk_channel_section)
    if trunk_sets:
        result["trunk_sets"] = [_trunk_set_to_dict(ts) for ts in trunk_sets]

    # Group sets
    group_sets = _parse_sets(prs, "CP25Group", "CP25GroupSet",
                             parse_group_section)
    if group_sets:
        result["group_sets"] = [_group_set_to_dict(gs) for gs in group_sets]

    # Conventional sets
    conv_sets = _parse_sets(prs, "CConvChannel", "CConvSet",
                            parse_conv_channel_section)
    if conv_sets:
        result["conv_sets"] = [_conv_set_to_dict(cs) for cs in conv_sets]

    # P25 conventional sets
    p25_conv_sets = _parse_sets(prs, "CP25ConvChannel", "CP25ConvSet",
                                parse_p25_conv_channel_section)
    if p25_conv_sets:
        result["p25_conv_sets"] = [
            _p25_conv_set_to_dict(cs) for cs in p25_conv_sets
        ]

    # IDEN sets
    iden_sets = _parse_sets(prs, "CDefaultIdenElem", "CIdenDataSet",
                            parse_iden_section)
    if iden_sets:
        result["iden_sets"] = [_iden_set_to_dict(iset) for iset in iden_sets]

    # WAN entries
    wan_sec = prs.get_section_by_class("CP25TrkWan")
    wan_opts = prs.get_section_by_class("CP25tWanOpts")
    if wan_sec and wan_opts:
        wan_count = parse_wan_opts_section(wan_opts.raw)
        if wan_count > 0:
            entries = parse_wan_section(wan_sec.raw)
            if entries:
                result["wan_entries"] = [
                    _wan_entry_to_dict(e) for e in entries
                ]

    # Platform config (XML options)
    config = extract_platform_config(prs)
    if config:
        result["options"] = {"platform_config": config}

    return result


def dict_to_json(d, compact=False):
    """Serialize a dict to a formatted JSON string.

    Args:
        d: dict (from prs_to_dict)
        compact: if True, produce compact single-line JSON

    Returns:
        str: JSON string
    """
    if compact:
        return json.dumps(d, separators=(',', ':'), ensure_ascii=False)
    return json.dumps(d, indent=2, ensure_ascii=False)


def export_json(prs, filepath, compact=False):
    """Export a PRSFile to a JSON file.

    Args:
        prs: PRSFile object
        filepath: output JSON file path
        compact: if True, write compact JSON

    Returns:
        str: path written to
    """
    d = prs_to_dict(prs)
    text = dict_to_json(d, compact=compact)
    path = Path(filepath)
    path.write_text(text, encoding='utf-8')
    return str(path)


# ─── Import: JSON → dict → PRS ──────────────────────────────────────


def json_to_dict(filepath):
    """Read a JSON file and return the parsed dict.

    Args:
        filepath: path to JSON file

    Returns:
        dict
    """
    path = Path(filepath)
    text = path.read_text(encoding='utf-8')
    return json.loads(text)


def dict_to_prs(d):
    """Convert a JSON-derived dict into a PRSFile.

    Creates a blank PRS and injects systems, sets, and WAN entries
    from the dict structure.

    Args:
        d: dict (from json_to_dict or prs_to_dict)

    Returns:
        PRSFile object
    """
    from .builder import create_blank_prs
    from .injector import (
        add_p25_trunked_system, add_conv_system,
        make_trunk_set, make_group_set, make_p25_group,
        make_trunk_channel, make_conv_set, make_conv_channel,
        make_iden_set,
    )
    from .record_types import (
        P25TrkSystemConfig, ConvSystemConfig,
        TrunkChannel, TrunkSet, P25Group, P25GroupSet,
        ConvChannel, ConvSet, IdenElement, IdenDataSet,
        P25TrkWanEntry, EnhancedCCEntry,
    )

    # Personality metadata
    pers = d.get("personality", {})
    filename = pers.get("filename", "Imported.PRS")
    saved_by = pers.get("saved_by", "")

    prs = create_blank_prs(filename=filename, saved_by=saved_by)

    # Track what sets need to be created
    trunk_sets_data = d.get("trunk_sets", [])
    group_sets_data = d.get("group_sets", [])
    conv_sets_data = d.get("conv_sets", [])
    iden_sets_data = d.get("iden_sets", [])
    wan_entries_data = d.get("wan_entries", [])
    systems_data = d.get("systems", [])

    # Create trunk sets
    for ts_d in trunk_sets_data:
        channels = ts_d.get("channels", [])
        freqs = [(ch["tx_freq"], ch["rx_freq"]) for ch in channels]
        tset = make_trunk_set(
            ts_d["name"], freqs,
            tx_min=ts_d.get("tx_min", 136.0),
            tx_max=ts_d.get("tx_max", 870.0),
            rx_min=ts_d.get("rx_min", 136.0),
            rx_max=ts_d.get("rx_max", 870.0),
        )
        from .injector import _safe_add_trunk_set
        _safe_add_trunk_set(prs, tset)

    # Create group sets
    for gs_d in group_sets_data:
        groups_data = gs_d.get("groups", [])
        groups = []
        for g in groups_data:
            groups.append(make_p25_group(
                g["id"],
                g.get("short_name", f"TG{g['id']}")[:8],
                g.get("long_name", "")[:16],
                tx=g.get("tx", False),
                scan=g.get("scan", True),
            ))
        from .record_types import P25GroupSet
        gset = P25GroupSet(name=gs_d["name"][:8], groups=groups)
        from .injector import _safe_add_group_set
        _safe_add_group_set(prs, gset)

    # Create IDEN sets
    for is_d in iden_sets_data:
        elements_data = is_d.get("elements", [])
        entries = []
        for elem in elements_data:
            iden_type = 1 if elem.get("iden_type", "FDMA") == "TDMA" else 0
            entries.append({
                "chan_spacing_hz": elem.get("chan_spacing_hz", 12500),
                "bandwidth_hz": elem.get("bandwidth_hz", 6250),
                "base_freq_hz": elem.get("base_freq_hz", 0),
                "tx_offset_mhz": elem.get("tx_offset_mhz", 0.0),
                "iden_type": iden_type,
            })
        iset = make_iden_set(is_d["name"], entries)
        from .injector import _safe_add_iden_set
        _safe_add_iden_set(prs, iset)

    # Create conventional sets
    for cs_d in conv_sets_data:
        channels_data = cs_d.get("channels", [])
        ch_list = []
        for ch in channels_data:
            ch_list.append({
                "short_name": ch.get("short_name", "CH")[:8],
                "tx_freq": ch["tx_freq"],
                "rx_freq": ch.get("rx_freq", ch["tx_freq"]),
                "tx_tone": ch.get("tx_tone", ""),
                "rx_tone": ch.get("rx_tone", ""),
                "long_name": ch.get("long_name", "")[:16],
            })
        cset = make_conv_set(cs_d["name"], ch_list)
        from .injector import _safe_add_conv_set
        _safe_add_conv_set(prs, cset)

    # Create systems
    for sys_d in systems_data:
        sys_type = sys_d.get("type", "")
        sys_name = sys_d.get("name", "SYS")[:8]
        long_name = sys_d.get("long_name", sys_name)[:16]

        if sys_type == "P25Trunked":
            config = P25TrkSystemConfig(
                system_name=sys_name,
                long_name=long_name,
                trunk_set_name=sys_d.get("trunk_set", sys_name)[:8],
                group_set_name=sys_d.get("group_set", sys_name)[:8],
                wan_name=sys_d.get("wan_name", sys_name)[:8],
                system_id=sys_d.get("system_id", 0),
            )
            # Look up WACN from wan_entries if available
            wan_name_stripped = config.wan_name.strip()
            for we in wan_entries_data:
                if we.get("wan_name", "").strip() == wan_name_stripped:
                    config.wacn = we.get("wacn", 0)
                    config.system_id = we.get("system_id",
                                              config.system_id)
                    break
            add_p25_trunked_system(prs, config)

        elif sys_type == "Conventional":
            config = ConvSystemConfig(
                system_name=sys_name,
                long_name=long_name,
                conv_set_name=sys_d.get("group_set",
                                        sys_d.get("conv_set", sys_name))[:8],
            )
            add_conv_system(prs, config)

    return prs


def import_json(filepath, output_path=None):
    """Import a JSON file and create a PRS file.

    Args:
        filepath: input JSON file path
        output_path: output PRS file path (default: same name with .PRS)

    Returns:
        (PRSFile, str): the PRS object and the output path written to
    """
    d = json_to_dict(filepath)
    prs = dict_to_prs(d)

    if output_path is None:
        output_path = Path(filepath).with_suffix('.PRS')

    raw = prs.to_bytes()
    Path(output_path).write_bytes(raw)
    return prs, str(output_path)
