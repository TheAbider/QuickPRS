"""JSON export and import for PRS personality files.

Export: converts a parsed PRSFile into a structured JSON document with all
decoded data (personality, systems, trunk/group/conv/IDEN sets, WAN entries,
platform config).

Every channel, talkgroup and set carries all of its fields (bytes as hex)
after the readable ones, and an "archive" block carries the rest of the
file (systems, option objects, personality fields, options XML) as data,
so importing an unedited export gives back the same personality.

Import: reads a JSON document and creates a valid PRS file from its
contents (see dict_to_prs).
"""

import dataclasses
import json
import logging
from pathlib import Path

from . import archive

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
    parse_sets_from_sections, list_system_configs,
)
from .option_maps import extract_platform_config, extract_platform_xml

logger = logging.getLogger("quickprs")


# ─── Export: PRS → dict → JSON ──────────────────────────────────────

# Each channel, talkgroup and set is exported with its readable keys and,
# after them, every other field of its record (bytes as hex), so an import
# rebuilds it exactly.  Class tags are left out: they are recomputed on
# every save.
_TAGS = ("separator", "set_marker")

_CONV_HIDDEN = ("_flags_reserved", "pre_long_name", "trailer")
_P25_CONV_HIDDEN = ("_flags_reserved", "trailer")
_GROUP_HIDDEN = ("_middle_reserved_9_10", "audio_profile", "key_id")
_GROUP_RENAME = {"id": "group_id", "short_name": "group_name"}


def _hidden(obj, shown):
    """The fields of a record not among its readable keys, bytes as hex."""
    out = {}
    for f in dataclasses.fields(obj):
        if f.name in shown or f.name in _TAGS:
            continue
        value = getattr(obj, f.name)
        if isinstance(value, list):
            continue
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).hex()
        out[f.name] = value
    return out


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
        d = {"tx_freq": ch.tx_freq, "rx_freq": ch.rx_freq}
        d.update(_hidden(ch, d))
        channels.append(d)
    result = {
        "name": tset.name,
        "channels": channels,
        "tx_min": tset.tx_min,
        "tx_max": tset.tx_max,
        "rx_min": tset.rx_min,
        "rx_max": tset.rx_max,
    }
    result.update(_hidden(tset, result))
    return result


def _group_set_to_dict(gset):
    """Convert a P25GroupSet to a JSON-friendly dict."""
    groups = []
    for g in gset.groups:
        d = {
            "id": g.group_id,
            "short_name": g.group_name,
            "long_name": g.long_name,
            "tx": g.tx,
            "scan": g.scan,
            "rx": g.rx,
        }
        d.update(_hidden(g, {_GROUP_RENAME.get(k, k) for k in d}))
        groups.append(d)
    result = {
        "name": gset.name,
        "scan_list_size": gset.scan_list_size,
        "system_id": gset.system_id,
        "groups": groups,
    }
    result.update(_hidden(gset, result))
    return result


def _conv_set_to_dict(cset):
    """Convert a ConvSet to a JSON-friendly dict."""
    channels = []
    readable = ("short_name", "tx_freq", "rx_freq", "long_name", "tx", "rx",
                "scan", "tx_tone", "rx_tone", "narrowband")
    for ch in cset.channels:
        d = {
            "short_name": ch.short_name,
            "tx_freq": ch.tx_freq,
            "rx_freq": ch.rx_freq,
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
        d.update(_hidden(ch, readable))
        channels.append(d)
    result = {
        "name": cset.name,
        "channels": channels,
        "tx_min": cset.tx_min,
        "tx_max": cset.tx_max,
        "rx_min": cset.rx_min,
        "rx_max": cset.rx_max,
    }
    result.update(_hidden(cset, result))
    return result


def _p25_conv_set_to_dict(cset):
    """Convert a P25ConvSet to a JSON-friendly dict."""
    channels = []
    for ch in cset.channels:
        d = {
            "short_name": ch.short_name,
            "tx_freq": ch.tx_freq,
            "rx_freq": ch.rx_freq,
            "long_name": ch.long_name,
            "tx": ch.tx,
            "rx": ch.rx,
            "scan": ch.scan,
            "nac_tx": ch.nac_tx,
            "nac_rx": ch.nac_rx,
        }
        d.update(_hidden(ch, d))
        channels.append(d)
    result = {
        "name": cset.name,
        "channels": channels,
        "tx_min": cset.tx_min,
        "tx_max": cset.tx_max,
        "rx_min": cset.rx_min,
        "rx_max": cset.rx_max,
        "group_set_ref": cset.group_set_ref,
    }
    result.update(_hidden(cset, result))
    return result


def _iden_set_to_dict(iset):
    """Convert an IdenDataSet to a JSON-friendly dict.

    Only elements that are set are listed, each with its slot ("index",
    0-15): the control channel names an IDEN by its slot, so slots must
    not move."""
    from .record_types import IdenElement
    elements = []
    for index, elem in enumerate(iset.elements):
        if elem == IdenElement():
            continue
        d = {
            "index": index,
            "chan_spacing_hz": elem.chan_spacing_hz,
            "bandwidth_hz": elem.bandwidth_hz,
            "base_freq_hz": elem.base_freq_hz,
            "tx_offset_mhz": round(elem.tx_offset_mhz, 1),
            "iden_type": "TDMA" if elem.iden_type else "FDMA",
        }
        d.update(_hidden(elem, set(d) | {"iden_type"}))
        elements.append(d)
    result = {
        "name": iset.name,
        "elements": elements,
    }
    result.update(_hidden(iset, result))
    return result


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


def _system_extras(obj):
    """Set references and IDs read from a system object of an
    archive.Document (the readable systems list shows them)."""
    data = obj.parts[0]
    _, pos = archive.read_cstring(data, 0)
    pos += 1 + 2 + 42                       # type byte, FFFF, prefix
    _, pos = archive.read_cstring(data, pos)  # long name
    if obj.cls == "CP25TrkSystem":
        pos += 15
        _, pos = archive.read_cstring(data, pos)  # trunk set
        _, pos = archive.read_cstring(data, pos)  # group set
        pos += 12
        home = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4 + 12 + 6 + 2
        sysid = int.from_bytes(data[pos:pos + 4], "little")
        iden, _ = archive.read_cstring(obj.parts[2], 4)
        extras = {"system_id": sysid, "home_unit_id": home}
        if iden:
            extras["iden_set"] = iden
        return extras
    if obj.cls == "CConvSystem":
        return {"conv_set": archive.read_cstring(data, pos + 12)[0]}
    return {"conv_set": archive.read_cstring(data, pos + 5 + 4)[0]}


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
    for ref in list_system_configs(prs):
        sys_dict = _config_to_sys_dict(ref.section.raw,
                                       system_class_map[ref.class_name])
        sys_dict["name"] = ref.short_name
        systems.append(sys_dict)
    try:
        objs = [o for o in archive.document_from_prs(prs).list(
            "systems").items if o is not None]
    except archive.WalkError:
        objs = []
    if len(objs) == len(systems):
        for sys_dict, obj in zip(systems, objs):
            try:
                sys_dict.update(_system_extras(obj))
            except (IndexError, ValueError):
                pass
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

    # Platform config (XML options): readable, and the XML itself, which
    # an import without the archive block applies
    config = extract_platform_config(prs)
    if config:
        result["options"] = {"platform_config": config,
                             "platform_xml": extract_platform_xml(prs)}

    # Everything that is not a set (systems, option objects, personality
    # fields, the options XML) as archive data; dict_to_prs rebuilds the
    # personality from it and the readable sets
    try:
        doc = archive.document_from_prs(prs)
    except archive.WalkError:
        doc = None
    if doc is not None:
        result["archive"] = {
            "schemas": dict(doc.schemas),
            "root": _obj_to_json(doc.root, skip=_SET_LIST_NAMES),
        }

    return result


# The archive's set lists: exported as readable sets, not as data
_SET_LIST_NAMES = ("trunk sets", "conv sets", "group sets", "P25 conv sets",
                   "IDEN sets")


def _obj_to_json(obj, skip=()):
    """An archive object as JSON: its class and its parts (bytes as hex,
    nested lists as {list, counted, items}); lists named in ``skip`` are
    written empty."""
    if obj is None:
        return None
    parts = []
    for p in obj.parts:
        if isinstance(p, (bytes, bytearray)):
            parts.append(bytes(p).hex())
        else:
            parts.append({"list": p.name, "counted": p.counted,
                          "items": [] if p.name in skip else
                          [_obj_to_json(i) for i in p.items]})
    return {"class": obj.cls, "parts": parts}


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


def _is_bytes_field(f):
    return isinstance(f.default, (bytes, bytearray)) or f.type in (
        bytes, 'bytes')


def _from_fields(cls, d, rename=None, **fixed):
    """Build a dataclass from exported keys: readable keys (renamed via
    ``rename``, JSON key -> field) and hidden ones, hex strings back to
    bytes.  Keys the class does not have are ignored; fields the dict
    leaves out keep their defaults."""
    rename = rename or {}
    data = {rename.get(k, k): v for k, v in d.items()}
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in fixed:
            kwargs[f.name] = fixed[f.name]
        elif f.name in data and not isinstance(data[f.name], (list, dict)):
            value = data[f.name]
            if _is_bytes_field(f) and isinstance(value, str):
                value = bytes.fromhex(value)
            kwargs[f.name] = value
    return cls(**kwargs)


def _trunk_set_from_dict(ts_d):
    from .record_types import TrunkChannel, TrunkSet
    channels = [_from_fields(TrunkChannel, ch)
                for ch in ts_d.get("channels", [])]
    return _from_fields(TrunkSet, ts_d, channels=channels,
                        name=ts_d["name"][:8])


def _group_set_from_dict(gs_d):
    from .injector import make_p25_group
    from .record_types import P25Group, P25GroupSet
    groups = []
    for g in gs_d.get("groups", []):
        if any(k in g for k in _GROUP_HIDDEN):
            groups.append(_from_fields(P25Group, g, _GROUP_RENAME))
        else:
            # hand-written: the injector's defaults for a new talkgroup
            grp = make_p25_group(g["id"],
                                 g.get("short_name", f"TG{g['id']}")[:8],
                                 g.get("long_name", "")[:16],
                                 tx=g.get("tx", False),
                                 scan=g.get("scan", True))
            if "rx" in g:
                grp.rx = g["rx"]
            groups.append(grp)
    return _from_fields(P25GroupSet, gs_d, groups=groups,
                        name=gs_d["name"][:8])


def _conv_set_from_dict(cs_d):
    from .injector import make_conv_channel
    from .record_types import ConvChannel, ConvSet
    channels = []
    for ch in cs_d.get("channels", []):
        if any(k in ch for k in _CONV_HIDDEN):
            channels.append(_from_fields(ConvChannel, ch))
        else:
            channels.append(make_conv_channel(
                ch.get("short_name", "CH")[:8], ch["tx_freq"],
                ch.get("rx_freq", ch["tx_freq"]),
                tx_tone=ch.get("tx_tone", ""), rx_tone=ch.get("rx_tone", ""),
                long_name=ch.get("long_name", "")[:16],
                tx=ch.get("tx", True), scan=ch.get("scan", True),
                narrowband=ch.get("narrowband", False)))
            if "rx" in ch:
                channels[-1].rx = ch["rx"]
    return _from_fields(ConvSet, cs_d, channels=channels,
                        name=cs_d["name"][:8])


def _p25_conv_set_from_dict(cs_d):
    from .injector import make_p25_conv_channel
    from .record_types import P25ConvChannel, P25ConvSet
    channels = []
    for ch in cs_d.get("channels", []):
        if any(k in ch for k in _P25_CONV_HIDDEN):
            channels.append(_from_fields(P25ConvChannel, ch))
        else:
            channels.append(make_p25_conv_channel(
                ch.get("short_name", "CH")[:8], ch["tx_freq"],
                ch.get("rx_freq", ch["tx_freq"]),
                nac_tx=ch.get("nac_tx", 0x293), nac_rx=ch.get("nac_rx"),
                long_name=ch.get("long_name", "")[:16],
                tx=ch.get("tx", True), rx=ch.get("rx", True),
                scan=ch.get("scan", True)))
    return _from_fields(P25ConvSet, cs_d, channels=channels,
                        name=cs_d["name"][:8])


def _iden_set_from_dict(is_d):
    from .record_types import IdenElement, IdenDataSet
    elements = [IdenElement() for _ in range(IdenDataSet.SLOTS)]
    for pos, e in enumerate(is_d.get("elements", [])):
        index = e.get("index", pos)
        fields = dict(e)
        kind = fields.pop("iden_type", 0)
        elem = _from_fields(IdenElement, fields)
        elem.iden_type = 1 if kind in ("TDMA", 1) else 0
        raw = fields.get("tx_offset")
        mhz = fields.get("tx_offset_mhz")
        if mhz is not None and (raw is None or round(elem.tx_offset_mhz, 1)
                                != round(mhz, 1)):
            elem.tx_offset_mhz = mhz      # edited (or hand-written)
        if not 0 <= index < IdenDataSet.SLOTS:
            raise ValueError(f"IDEN set {is_d['name']}: element index "
                             f"{index} is not 0-{IdenDataSet.SLOTS - 1}")
        elements[index] = elem
    return _from_fields(IdenDataSet, is_d, elements=elements,
                        name=is_d["name"][:8])


# (JSON key, archive list, set reader)
_SET_LISTS = [
    ("trunk_sets", "trunk sets", _trunk_set_from_dict),
    ("conv_sets", "conv sets", _conv_set_from_dict),
    ("group_sets", "group sets", _group_set_from_dict),
    ("p25_conv_sets", "P25 conv sets", _p25_conv_set_from_dict),
    ("iden_sets", "IDEN sets", _iden_set_from_dict),
]


def _obj_from_json(j):
    from .archive import Obj, ObjList
    if j is None:
        return None
    parts = []
    for p in j["parts"]:
        if isinstance(p, str):
            parts.append(bytes.fromhex(p))
        else:
            parts.append(ObjList(p["list"],
                                 [_obj_from_json(i) for i in p.get("items", [])],
                                 p.get("counted", True)))
    return Obj(j["class"], parts)


def _set_objects(list_name, sets):
    from .injector import _SET_OBJ_BUILDERS
    build = _SET_OBJ_BUILDERS[list_name]
    if list_name == "conv sets":
        return [build(s, None) for s in sets]
    return [build(s) for s in sets]


def dict_to_prs(d):
    """Convert a JSON-derived dict into a PRSFile.

    A dict from prs_to_dict carries an "archive" block (systems, option
    objects, personality fields and the options XML, as data) next to the
    readable sets: the personality is rebuilt from both, so an unedited
    export imports to the same personality, and edits to the sets, their
    channels and talkgroups are applied.  Systems and options come from
    the archive block; to rebuild them from the readable "systems" list
    instead, delete the "archive" key.

    Without an archive block (a hand-written file, or one from QuickPRS
    1.1 or older) the personality is built from a blank one: each set list
    and the systems list the dict has replaces the blank's.

    Args:
        d: dict (from json_to_dict or prs_to_dict)

    Returns:
        PRSFile object
    """
    from .prs_parser import parse_prs_bytes
    from . import archive

    if "archive" in d:
        arch = d["archive"]
        doc = archive.Document(_obj_from_json(arch["root"]),
                               dict(arch.get("schemas", {})))
        for key, list_name, read in _SET_LISTS:
            doc.list(list_name).items = _set_objects(
                list_name, [read(x) for x in d.get(key, [])])
        return parse_prs_bytes(archive.serialize(doc))

    return _dict_to_prs_readable(d)


def _dict_to_prs_readable(d):
    from .builder import create_blank_prs
    from . import archive
    from .injector import (add_p25_trunked_system, add_conv_system,
                           add_p25_conv_system)
    from .record_types import (P25TrkSystemConfig, ConvSystemConfig,
                               P25ConvSystemConfig)
    from .prs_parser import parse_prs_bytes

    pers = d.get("personality", {})
    prs = create_blank_prs(filename=pers.get("filename", "Imported.PRS"),
                           saved_by=pers.get("saved_by", ""))

    doc = archive.document_from_prs(prs)
    for key, list_name, read in _SET_LISTS:
        if key in d:
            doc.list(list_name).items = _set_objects(
                list_name, [read(x) for x in d[key]])
    if "systems" in d:
        doc.list("systems").items = []
    prs = parse_prs_bytes(archive.serialize(doc))

    wan_entries = d.get("wan_entries", [])
    for sys_d in d.get("systems", []):
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
                home_unit_id=sys_d.get("home_unit_id", 0),
                iden_set_name=sys_d.get("iden_set", "")[:8],
            )
            for we in wan_entries:
                if we.get("wan_name", "").strip() == config.wan_name.strip():
                    config.wacn = we.get("wacn", 0)
                    config.system_id = we.get("system_id", config.system_id)
                    break
            add_p25_trunked_system(prs, config)
        elif sys_type == "Conventional":
            add_conv_system(prs, ConvSystemConfig(
                system_name=sys_name, long_name=long_name,
                conv_set_name=sys_d.get("conv_set", sys_name)[:8]))
        elif sys_type == "P25Conv":
            add_p25_conv_system(prs, P25ConvSystemConfig(
                system_name=sys_name, long_name=long_name,
                conv_set_name=sys_d.get("conv_set", sys_name)[:8]))

    xml = d.get("options", {}).get("platform_xml")
    if xml:
        from .option_maps import (extract_platform_xml, write_platform_config,
                                  _inject_platform_xml)
        if extract_platform_xml(prs) is None:
            written = _inject_platform_xml(prs, xml)
        else:
            written = write_platform_config(prs, xml)
        if not written:
            logger.warning("The JSON's radio options could not be written")
    elif d.get("options", {}).get("platform_config"):
        logger.warning("JSON options without platform_xml are not imported")
    return prs


def import_json(filepath, output_path=None):
    """Import a JSON file and create a PRS file.

    Args:
        filepath: input JSON file path
        output_path: output PRS file path (default: same name with .PRS)

    Returns:
        (PRSFile, str): the PRS object and the output path written to
    """
    from .prs_writer import write_prs
    d = json_to_dict(filepath)
    prs = dict_to_prs(d)

    if output_path is None:
        output_path = Path(filepath).with_suffix('.PRS')

    write_prs(prs, output_path, backup=True)
    return prs, str(output_path)
