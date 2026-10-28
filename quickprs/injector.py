"""Injector — high-level functions to add/modify personality data.

Operations modify the in-memory PRSFile object. After injection, call
write_prs() to save. Always verify roundtrip on the modified file.

Strategy:
  - Data set modifications (add groups, channels, IDEN elements) rebuild
    the relevant section's raw bytes from structured data.
  - System creation builds CP25TrkSystem header + config data sections
    and inserts them at the correct position in the section list.
  - All operations preserve unknown bytes and section ordering.
  - All parsing uses section.raw directly (not full file + offset) so it
    works correctly after sections have been rebuilt.
"""

import logging
import struct

from . import archive
from .archive import Obj, ObjList
from .prs_parser import Section
from .binary_io import (
    read_uint16_le, write_uint16_le, write_lps, write_uint8, write_double_le,
)
from .record_types import (
    TrunkChannel, TrunkSet, ConvChannel, ConvSet,
    IdenElement, IdenDataSet, P25Group, P25GroupSet,
    is_system_config_data,
    TRUNK_CHANNEL_SEP, CONV_CHANNEL_SEP, IDEN_ELEMENT_SEP, GROUP_SEP,
    TRUNK_SET_MARKER, GROUP_SET_MARKER, CONV_SET_MARKER, IDEN_SET_MARKER,
    parse_class_header, build_class_header,
    parse_trunk_channel_section, parse_group_section, parse_iden_section,
    parse_conv_channel_section,
    extract_iden_trailing_data,
    parse_wan_section, build_wan_section, build_wan_opts_section,
    P25TrkWanEntry,
    parse_system_short_name, parse_system_long_name,
    parse_system_set_refs,
    parse_sets_from_sections,
)

logger = logging.getLogger("quickprs")


# ─── Section helpers ──────────────────────────────────────────────────

def _find_section_index(prs, class_name):
    """Find index of section with given class name."""
    for i, s in enumerate(prs.sections):
        if s.class_name == class_name:
            return i
    return -1


def _get_first_count(prs, set_class_name):
    """Read the first-set element count from a Set section's raw bytes."""
    sec = prs.get_section_by_class(set_class_name)
    if not sec:
        return 0
    _, _, _, data_start = parse_class_header(sec.raw, 0)
    count, _ = read_uint16_le(sec.raw, data_start)
    return count


def _get_header_bytes(section):
    """Extract the class header byte1 and byte2 from a section."""
    if len(section.raw) < 6:
        return 0x64, 0x00
    return section.raw[2], section.raw[3]


def _rebuild_set_section(class_name, first_count, byte1, byte2):
    """Rebuild a Set section (CTrunkSet, CP25GroupSet, CIdenDataSet)."""
    header = build_class_header(class_name, byte1, byte2)
    return header + write_uint16_le(first_count)


def _parse_section_data(section, parser_fn, first_count):
    """Parse a section's raw bytes into structured data.

    Uses section.raw directly, so works even after sections have been rebuilt.
    """
    _, _, _, data_start = parse_class_header(section.raw, 0)
    return parser_fn(section.raw, data_start, len(section.raw), first_count)


# ─── Archive-backed writes ────────────────────────────────────────────
#
# Everything that adds, removes or reorders objects goes through
# archive.Document, which writes the class tags, the WORD count in front
# of each list and each class's schema the way RPM does (see archive.py).
# Copying "separators" from the old file is what used to make edited files
# unreadable to RPM.

def _trunk_set_obj(tset):
    channels = [Obj("CTrunkChannel", [ch.to_bytes()]) for ch in tset.channels]
    trailing = bytes(tset.trailing_bytes or b"")
    if len(trailing) >= 13:
        tail = trailing[:13]   # parsed last set: its own 13 bytes come first
    else:
        tail = bytes(tset.gap_bytes or b"")[:12].ljust(12, b"\x00") + b"\x01"
    return Obj("CTrunkSet", [ObjList("items", channels),
                             tset.metadata_to_bytes() + tail])


def _conv_set_obj(cset, old=None):
    channels = [Obj("CConvChannel", [ch.to_bytes()]) for ch in cset.channels]
    meta = write_lps(cset.name) + cset.metadata
    if old is not None:
        # The walker knows where the set really ends; bytes after the
        # 60-byte block (issue #1) are kept from there, not guessed.
        old_meta = old.parts[1]
        _, at = archive.read_cstring(old_meta, 0)
        meta += old_meta[at + ConvSet.METADATA_SIZE:]
    else:
        meta += bytes(getattr(cset, "padding", b""))
    return Obj("CConvSet", [ObjList("items", channels), meta])


def _group_set_obj(gset):
    groups = [Obj("CP25Group", [g.to_bytes()]) for g in gset.groups]
    return Obj("CP25GroupSet", [ObjList("items", groups),
                                gset.metadata_to_bytes()])


def _iden_set_obj(iset):
    elements = list(iset.elements[:IdenDataSet.SLOTS])
    while len(elements) < IdenDataSet.SLOTS:
        elements.append(IdenElement())
    items = [Obj("CDefaultIdenElem", [e.to_bytes()]) for e in elements]
    meta = write_lps(iset.name) + bytes(iset.metadata)[:2].ljust(2, b"\x00")
    return Obj("CIdenDataSet", [ObjList("items", items), meta])


def _p25_conv_set_obj(pset):
    channels = [Obj("CP25ConvChannel", [ch.to_bytes()])
                for ch in pset.channels]
    # The old parser's 17-byte "trailing" ends with the next two list
    # counts; only the first 13 bytes belong to the set.
    meta = (write_lps(pset.name) + write_uint8(pset.scan_list_size) +
            write_uint8(pset.config_byte2) + write_double_le(pset.tx_min) +
            write_double_le(pset.rx_min) + write_double_le(pset.tx_max) +
            write_double_le(pset.rx_max) + write_lps(pset.group_set_ref) +
            bytes(pset.trailing)[:13].ljust(13, b"\x00"))
    return Obj("CP25ConvSet", [ObjList("items", channels), meta])


_SET_OBJ_BUILDERS = {
    "trunk sets": _trunk_set_obj,
    "conv sets": _conv_set_obj,
    "group sets": _group_set_obj,
    "IDEN sets": _iden_set_obj,
    "P25 conv sets": _p25_conv_set_obj,
}


def _set_obj_name(obj):
    return archive.read_cstring(obj.parts[1], 0)[0]


def _write_set_list(prs, list_name, sets):
    """Replace one whole set list (may be empty) and rewrite the file."""
    doc = archive.document_from_prs(prs)
    lst = doc.list(list_name)
    build = _SET_OBJ_BUILDERS[list_name]
    if list_name == "conv sets":
        # Match the file's own set objects by name (or by position when a
        # rename kept the list the same length) to keep their extra bytes.
        old_items = [o for o in lst.items if o is not None]
        by_name = {_set_obj_name(o): o for o in old_items}
        same_len = len(old_items) == len(sets)
        lst.items = [
            build(s, by_name.get(s.name,
                                 old_items[i] if same_len else None))
            for i, s in enumerate(sets)]
    else:
        lst.items = [build(s) for s in sets]
    archive.write_document(prs, doc)


def _system_obj_names(obj):
    """(short name, long name) of a system object in an archive.Document."""
    data = obj.parts[0]
    short, pos = archive.read_cstring(data, 0)
    pos += 1 + 2 + 42          # type byte, FFFF, config prefix
    long_name, _ = archive.read_cstring(data, pos)
    return short, long_name


def _system_ref_sites(obj):
    """Where a system object of an archive.Document names its sets:
    (archive list name, part index, start, end) of each name's CString,
    trunk, talkgroup and IDEN sets for a P25 trunked system, the channel
    set for the others."""
    data = obj.parts[0]
    _, pos = archive.read_cstring(data, 0)
    pos += 1 + 2 + 42                       # type byte, FFFF, prefix
    _, pos = archive.read_cstring(data, pos)  # long name
    if obj.cls == "CP25TrkSystem":
        pos += 15
        _, trunk_end = archive.read_cstring(data, pos)
        _, group_end = archive.read_cstring(data, trunk_end)
        _, iden_end = archive.read_cstring(obj.parts[2], 4)
        return [("trunk sets", 0, pos, trunk_end),
                ("group sets", 0, trunk_end, group_end),
                ("IDEN sets", 2, 4, iden_end)]
    start = pos + (12 if obj.cls == "CConvSystem" else 5 + 4)
    _, end = archive.read_cstring(data, start)
    return [("conv sets" if obj.cls == "CConvSystem" else "P25 conv sets",
             0, start, end)]


def _system_obj_refs(obj):
    """The sets a system object names, as (archive list name, set name)."""
    return [(list_name,
             archive.read_cstring(obj.parts[part], start)[0])
            for list_name, part, start, _ in _system_ref_sites(obj)]


def _replace_cstring(data, start, end, text):
    return data[:start] + archive.write_cstring(text) + data[end:]


# The archive set list each rename_* function works on, and its label
_SET_LISTS = {
    "trunk": ("trunk sets", "Trunk set"),
    "group": ("group sets", "Group set"),
    "conv": ("conv sets", "Conv set"),
    "iden": ("IDEN sets", "IDEN set"),
    "p25conv": ("P25 conv sets", "P25 conv set"),
}


def systems_using_set(prs, set_type, name):
    """Short names of the systems that name this set (set_type as for
    rename_set).  Empty when the archive cannot be read."""
    list_name = _SET_LISTS[set_type][0]
    try:
        doc = archive.document_from_prs(prs)
    except archive.WalkError:
        return []
    return [_system_obj_names(o)[0] for o in doc.list("systems").items
            if o is not None and (list_name, name) in _system_obj_refs(o)]


def rename_set(prs, set_type, old_name, new_name):
    """Rename a set and every reference to it.

    Systems find their sets by name, and a P25 conventional set may name a
    talkgroup set, so those names change with it.

    Args:
        set_type: "trunk", "group", "conv", "iden" or "p25conv"
        new_name: 8 characters at most (longer is cut)

    Returns:
        True if renamed, False if no set of that type has old_name.

    Raises:
        ValueError: another set of that type already has new_name.
    """
    list_name, label = _SET_LISTS[set_type]
    new_name = new_name[:8]
    if not prs.sections:
        return False
    doc = archive.document_from_prs(prs)
    sets = [o for o in doc.list(list_name).items if o is not None]
    target = next((o for o in sets if _set_obj_name(o) == old_name), None)
    if target is None:
        return False
    if new_name == old_name:
        return True
    if any(_set_obj_name(o) == new_name for o in sets):
        raise ValueError(f"{label} '{new_name}' already exists")

    meta = target.parts[1]
    _, end = archive.read_cstring(meta, 0)
    target.parts[1] = _replace_cstring(meta, 0, end, new_name)

    for obj in doc.list("systems").items:
        if obj is None:
            continue
        # back to front, so earlier positions stay valid
        for site_list, part, start, end in reversed(_system_ref_sites(obj)):
            if (site_list == list_name and
                    archive.read_cstring(obj.parts[part], start)[0]
                    == old_name):
                obj.parts[part] = _replace_cstring(
                    obj.parts[part], start, end, new_name)

    if list_name == "group sets":
        for obj in doc.list("P25 conv sets").items:
            if obj is None:
                continue
            meta = obj.parts[1]
            _, pos = archive.read_cstring(meta, 0)   # set name
            pos += 1 + 1 + 32                        # sizes, band limits
            ref, end = archive.read_cstring(meta, pos)
            if ref == old_name:
                obj.parts[1] = _replace_cstring(meta, pos, end, new_name)

    archive.write_document(prs, doc)
    return True


def _system_obj_wan_name(obj):
    """The WAN name a P25 trunked system object names."""
    data = obj.parts[0]
    _, pos = archive.read_cstring(data, 0)
    pos += 1 + 2 + 42
    _, pos = archive.read_cstring(data, pos)  # long name
    pos += 15
    _, pos = archive.read_cstring(data, pos)  # trunk set
    _, pos = archive.read_cstring(data, pos)  # group set
    pos += 12 + 4 + 12 + 6 + 2 + 4            # ... home unit ID, system ID
    return archive.read_cstring(data, pos)[0]


def system_set_references(prs):
    """Every set name the personality's systems refer to.

    P25 trunked systems name a trunk set, a talkgroup set and an IDEN set;
    conventional and P25 conventional systems name their channel set.
    Returns an empty set when the archive cannot be read.
    """
    try:
        doc = archive.document_from_prs(prs)
    except archive.WalkError:
        return set()
    refs = set()
    for obj in doc.list("systems").items:
        if obj is not None:
            refs.update(name for _, name in _system_obj_refs(obj))
    refs.discard("")
    return refs


def _append_system(prs, obj):
    doc = archive.document_from_prs(prs)
    doc.list("systems").items.append(obj)
    archive.write_document(prs, doc)


# ─── Trunk Set Operations ────────────────────────────────────────────

def _refuse_duplicate(existing_sets, new_set, label):
    """Systems refer to sets by name, so two sets of one type may not
    share a name (validation warns that RPM may confuse them)."""
    if any(s.name == new_set.name for s in existing_sets):
        raise ValueError(f"{label} '{new_set.name}' already exists")


def add_trunk_set(prs, trunk_set):
    """Add a new TrunkSet to the personality.

    Args:
        prs: PRSFile object
        trunk_set: TrunkSet object with channels and metadata

    Modifies prs in-place. Rebuilds CTrunkChannel and CTrunkSet sections.
    """
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")

    if not ch_sec or not set_sec:
        raise ValueError("No existing trunk sections found")

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CTrunkSet")

    existing_sets = _parse_section_data(ch_sec, parse_trunk_channel_section,
                                         first_count)
    _refuse_duplicate(existing_sets, trunk_set, "Trunk set")
    existing_sets.append(trunk_set)

    _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)


def add_trunk_channels(prs, set_name, channels):
    """Add channels to an existing TrunkSet.

    Args:
        prs: PRSFile object
        set_name: name of the set to add to (e.g., "PSERN")
        channels: list of TrunkChannel objects
    """
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CTrunkSet")

    existing_sets = _parse_section_data(ch_sec, parse_trunk_channel_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"Trunk set '{set_name}' not found")

    target.channels.extend(channels)

    _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)


def _replace_trunk_sections(prs, sets, byte1=None, byte2=None,
                            set_byte1=None, set_byte2=None):
    """Replace all trunk sets.  The header-byte arguments are ignored (kept
    for callers); schemas come from the file or RPM's defaults."""
    if not sets:
        raise ValueError("No trunk sets to write")
    _write_set_list(prs, "trunk sets", sets)


def _build_trunk_channel_raw(sets, byte1, byte2):
    """Build complete CTrunkChannel section from list of TrunkSets.

    Preserves the original inter-set gap structure:
      channels + set_metadata + (gap_bytes(12) + 01 + set_marker(2) + count + separator(2)) ...
      after last set: trailing_bytes (preserved from parse)
    """
    header = build_class_header('CTrunkChannel', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else TRUNK_SET_MARKER
    sep = sets[0].separator if sets else TRUNK_CHANNEL_SEP

    # Default trailing for new sections (matches observed pattern)
    _DEFAULT_TRAILING = (b'\x00' * 12 + b'\x01' +
                         b'\x00' * 5 + b'\x00' +
                         write_uint16_le(len(sets)))

    for i, tset in enumerate(sets):
        parts.append(tset.channels_to_bytes())
        parts.append(tset.metadata_to_bytes())

        if i < len(sets) - 1:
            next_count = len(sets[i + 1].channels)
            parts.append(tset.gap_bytes)
            parts.append(b'\x01')
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)
        else:
            # Use preserved trailing if available, otherwise default
            if tset.trailing_bytes:
                parts.append(tset.trailing_bytes)
            else:
                parts.append(_DEFAULT_TRAILING)

    return b''.join(parts)


# ─── Group Set Operations ────────────────────────────────────────────

def add_group_set(prs, group_set):
    """Add a new P25GroupSet to the personality.

    Args:
        prs: PRSFile object
        group_set: P25GroupSet object with groups and metadata
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")

    if not grp_sec or not set_sec:
        raise ValueError("No existing group sections found")

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section, first_count)
    _refuse_duplicate(existing_sets, group_set, "Group set")
    existing_sets.append(group_set)

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)


def add_talkgroups(prs, set_name, groups):
    """Add talkgroups to an existing P25GroupSet.

    Args:
        prs: PRSFile object
        set_name: name of the group set (e.g., "PSERN PD")
        groups: list of P25Group objects
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section, first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"Group set '{set_name}' not found")

    target.groups.extend(groups)

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)


def _replace_group_sections(prs, sets, byte1=None, byte2=None,
                            set_byte1=None, set_byte2=None):
    """Replace all talkgroup sets (header-byte arguments are ignored)."""
    if not sets:
        raise ValueError("No group sets to write")
    _write_set_list(prs, "group sets", sets)


def _build_group_raw(sets, byte1, byte2):
    """Build complete CP25Group section from list of P25GroupSets."""
    header = build_class_header('CP25Group', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else GROUP_SET_MARKER
    sep = sets[0].separator if sets else GROUP_SEP

    for i, gset in enumerate(sets):
        parts.append(gset.groups_to_bytes())
        parts.append(gset.metadata_to_bytes())

        if i < len(sets) - 1:
            next_count = len(sets[i + 1].groups)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)
        else:
            # Append preserved trailing bytes if available
            if gset.trailing_bytes:
                parts.append(gset.trailing_bytes)

    return b''.join(parts)


# ─── IDEN Set Operations ─────────────────────────────────────────────

def add_iden_set(prs, iden_set):
    """Add a new IdenDataSet to the personality.

    Args:
        prs: PRSFile object
        iden_set: IdenDataSet object with elements

    Preserves trailing data (platformConfig XML, passwords, GUID) that
    lives after the IDEN elements in the CDefaultIdenElem section.
    """
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    set_sec = prs.get_section_by_class("CIdenDataSet")

    if not elem_sec or not set_sec:
        raise ValueError("No existing IDEN sections found")

    byte1, byte2 = _get_header_bytes(elem_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CIdenDataSet")

    existing_sets = _parse_section_data(elem_sec, parse_iden_section, first_count)
    _refuse_duplicate(existing_sets, iden_set, "IDEN set")
    existing_sets.append(iden_set)
    # The document keeps everything after the IDEN sets (platformConfig XML,
    # passwords, GUID) on its own, so no trailing data needs carrying here.
    _replace_iden_sections(prs, existing_sets)


def _replace_iden_sections(prs, sets, *_args, **_kwargs):
    """Replace all IDEN sets (extra arguments are ignored)."""
    if not sets:
        raise ValueError("No IDEN sets to write")
    _write_set_list(prs, "IDEN sets", sets)


def _replace_p25_conv_sections(prs, sets, *_args, **_kwargs):
    """Replace all P25 conventional sets (extra arguments are ignored)."""
    if not sets:
        raise ValueError("No P25 conv sets to write")
    _write_set_list(prs, "P25 conv sets", sets)


def get_p25_conv_sets(prs):
    """The personality's P25 conventional sets ([] when there are none)."""
    from .record_types import parse_p25_conv_channel_section
    ch_sec = prs.get_section_by_class("CP25ConvChannel")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    if not ch_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, ch_sec.raw,
                                    parse_p25_conv_channel_section)


def add_p25_conv_set(prs, p25_conv_set):
    """Add a P25 conventional set, creating the first one if needed."""
    existing = get_p25_conv_sets(prs)
    _refuse_duplicate(existing, p25_conv_set, "P25 conv set")
    _write_set_list(prs, "P25 conv sets", existing + [p25_conv_set])


def _build_iden_raw(sets, byte1, byte2, trailing_data=None):
    """Build complete CDefaultIdenElem section from list of IdenDataSets.

    Args:
        sets: list of IdenDataSet objects
        byte1: class header byte1
        byte2: class header byte2
        trailing_data: optional bytes to append after the last set (preserves
            platformConfig XML, passwords, GUID from the original section)
    """
    header = build_class_header('CDefaultIdenElem', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else IDEN_SET_MARKER
    sep = sets[0].separator if sets else IDEN_ELEMENT_SEP

    for i, iset in enumerate(sets):
        parts.append(iset.elements_to_bytes())
        parts.append(write_lps(iset.name))
        parts.append(iset.metadata)

        if i < len(sets) - 1:
            next_count = len(sets[i + 1].elements)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)

    if trailing_data:
        parts.append(trailing_data)

    return b''.join(parts)


# ─── P25 Trunked System Creation ────────────────────────────────────

def add_p25_trunked_system(prs, config, trunk_set=None, group_set=None,
                           iden_set=None):
    """Add a complete P25 trunked system to the personality.

    Creates the CP25TrkSystem header (if needed), the system config data
    section, and optionally injects the associated trunk/group/IDEN sets.

    Args:
        prs: PRSFile object
        config: P25TrkSystemConfig with system parameters
        trunk_set: optional TrunkSet to inject
        group_set: optional P25GroupSet to inject
        iden_set: optional IdenDataSet to inject
    """
    # The system goes at the end of the systems list; its ECC entries are
    # CPreferredSystemTableEntry objects inside it.
    head, ecc, rest = config.object_parts()
    _append_system(prs, Obj("CP25TrkSystem", [
        head,
        ObjList("ECC entries",
                [Obj("CPreferredSystemTableEntry", [e]) for e in ecc]),
        rest,
    ]))

    # Inject associated data sets
    if trunk_set:
        _safe_add_trunk_set(prs, trunk_set)

    if group_set:
        _safe_add_group_set(prs, group_set)

    if iden_set:
        _safe_add_iden_set(prs, iden_set)

    # Update WAN sections with this system's WAN entry
    _update_wan_sections(prs, config)


def _update_wan_sections(prs, config):
    """Add a WAN entry for the system to CP25TrkWan and update CP25tWanOpts.

    Reads existing WAN entries, appends a new one for this system config
    (unless a duplicate wan_name already exists), then rebuilds both
    CP25TrkWan and CP25tWanOpts sections.

    Args:
        prs: PRSFile object
        config: P25TrkSystemConfig with wan_name, wacn, and system_id
    """
    wan_name = config.wan_name or config.system_name
    if len(wan_name) < 8:
        wan_name = wan_name + ' ' * (8 - len(wan_name))
    wan_name = wan_name[:8]

    doc = archive.document_from_prs(prs)
    wan_list = _wan_list(doc, create=True)
    for item in wan_list.items:
        if item is None:
            continue
        entry, _ = P25TrkWanEntry.parse(item.parts[0], 0)
        if entry.wan_name.strip() == wan_name.strip():
            return  # already there

    new_entry = P25TrkWanEntry(
        wan_name=wan_name,
        wacn=config.wacn,
        system_id=config.system_id,
    )
    wan_list.items.append(Obj("CP25TrkWan", [new_entry.to_bytes()]))
    archive.write_document(prs, doc)


def _wan_list(doc, create=False):
    """The WAN entry list inside the CP25tWanOpts option (None if absent).

    With ``create``, adds an empty CP25tWanOpts option when the
    personality has none, so P25 systems always get their WAN entry.
    """
    opts = doc.option("CP25tWanOpts")
    if opts is None:
        if not create:
            return None
        opts = Obj("CP25tWanOpts", [ObjList("WAN entries")])
        doc.list("options").items.insert(0, opts)
    return opts.lists()[0]


def add_preferred_entries(prs, new_entries):
    """Add preferred system table entries to an existing section.

    If no CPreferredSystemTableEntry section exists, this is a no-op
    (preferred entries are optional for injected systems).

    Args:
        prs: PRSFile object
        new_entries: list of PreferredSystemEntry to add
    """
    if not new_entries:
        return
    doc = archive.document_from_prs(prs)
    system = _first_ecc_system(doc)
    if system is None:
        return
    ecc = system.lists()[0]
    entries = _preferred_entries_of(system)

    # Compute next sequence index
    max_f2 = max((e.field2 for e in entries), default=0)
    for i, entry in enumerate(new_entries):
        if entry.field2 == 0:
            entry.field2 = max_f2 + 1 + i

    for entry in new_entries:
        ecc.items.append(Obj("CPreferredSystemTableEntry",
                             [entry.to_bytes()[:13]]))
    archive.write_document(prs, doc)


def _first_ecc_system(doc):
    """The first P25 trunked system: the "preferred system table" is its
    ECC list (the CPreferredSystemTableEntry objects inside it)."""
    for obj in doc.list("systems").items:
        if obj is not None and obj.cls == "CP25TrkSystem":
            return obj
    return None


def _preferred_entries_of(system):
    from .record_types import PreferredSystemEntry
    entries = []
    for item in system.lists()[0].items:
        if item is not None:
            entries.append(PreferredSystemEntry.from_bytes(
                item.parts[0] + b"\x00\x00", 0))
    return entries


def get_preferred_entries(prs):
    """Get parsed preferred system table entries.

    Returns:
        (entries, iden_name, chain_name) or ([], None, None)
    """
    try:
        doc = archive.document_from_prs(prs)
    except archive.WalkError:
        doc = None
    system = _first_ecc_system(doc) if doc else None
    if system is None:
        return [], None, None
    entries = _preferred_entries_of(system)
    rest = system.parts[2]
    iden, _ = archive.read_cstring(rest, 4)
    # the next system in the list, which the old section layout called
    # the "chain"
    # The next system in the list is the "chain" when it is another P25
    # trunked system (what the old section parser reported).
    systems = [o for o in doc.list("systems").items if o is not None]
    pos = systems.index(system)
    chain = None
    if pos + 1 < len(systems) and systems[pos + 1].cls == "CP25TrkSystem":
        chain = _system_obj_names(systems[pos + 1])[0]
    return entries, iden or None, chain


def _find_set_insertion_point(prs):
    """Find the index before which to insert new system sections.

    Returns the index of the first C*Set or C*Channel section, or
    the index of the first options section, or the end of sections.
    """
    set_classes = {'CTrunkSet', 'CTrunkChannel', 'CConvSet', 'CConvChannel',
                   'CP25GroupSet', 'CP25Group', 'CIdenDataSet',
                   'CDefaultIdenElem', 'CP25ConvSet', 'CP25ConvChannel'}
    opts_classes = {'CGenRadioOpts', 'CP25tWanOpts', 'CP25TrkWan',
                    'CTimerOpts', 'CDTMFOpts', 'CScanOpts'}

    for i, s in enumerate(prs.sections):
        if s.class_name in set_classes or s.class_name in opts_classes:
            return i
    return len(prs.sections)


def _find_system_data_end(prs, header_idx):
    """Find the end of system config data sections after a header.

    Scans forward from the header to find the last consecutive
    system config data section (or non-class section that could be
    system config data).
    """
    idx = header_idx + 1
    while idx < len(prs.sections):
        sec = prs.sections[idx]
        # System config data sections have no class name and start with
        # the universal prefix (01 01 00 00 ...)
        if not sec.class_name and is_system_config_data(sec.raw):
            idx += 1
            continue
        # Also skip unnamed data sections that might be continuation data
        if not sec.class_name and len(sec.raw) < 50:
            idx += 1
            continue
        break
    return idx


def _safe_add_trunk_set(prs, trunk_set):
    """Add a trunk set, creating the section structure if needed."""
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    if ch_sec:
        add_trunk_set(prs, trunk_set)
    else:
        # No existing trunk sections — create from scratch
        _create_trunk_sections(prs, [trunk_set])


def _safe_add_group_set(prs, group_set):
    """Add a group set, creating the section structure if needed."""
    grp_sec = prs.get_section_by_class("CP25Group")
    if grp_sec:
        add_group_set(prs, group_set)
    else:
        _create_group_sections(prs, [group_set])


def _safe_add_iden_set(prs, iden_set):
    """Add an IDEN set, creating the section structure if needed."""
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    if elem_sec:
        add_iden_set(prs, iden_set)
    else:
        _create_iden_sections(prs, [iden_set])


def _create_trunk_sections(prs, sets):
    """Write the first trunk sets of a personality that had none."""
    _write_set_list(prs, "trunk sets", sets)


def _create_group_sections(prs, sets):
    """Write the first talkgroup sets of a personality that had none."""
    _write_set_list(prs, "group sets", sets)


def _create_iden_sections(prs, sets):
    """Write the first IDEN sets of a personality that had none."""
    _write_set_list(prs, "IDEN sets", sets)


def _find_data_set_insert_point(prs):
    """Find where to insert new data set sections (before options/end)."""
    opts_classes = {'CGenRadioOpts', 'CP25tWanOpts', 'CP25TrkWan',
                    'CTimerOpts', 'CDTMFOpts', 'CScanOpts', 'CType99Opts'}
    for i, s in enumerate(prs.sections):
        if s.class_name in opts_classes:
            return i
    return len(prs.sections)


# ─── Conv Set Operations ────────────────────────────────────────────

def add_conv_set(prs, conv_set):
    """Add a new ConvSet to the personality.

    Args:
        prs: PRSFile object
        conv_set: ConvSet object with channels and metadata
    """
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")

    if not ch_sec or not set_sec:
        raise ValueError("No existing conv sections found")

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CConvSet")

    existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                         first_count)
    _refuse_duplicate(existing_sets, conv_set, "Conv set")
    existing_sets.append(conv_set)

    _replace_conv_sections(prs, existing_sets, byte1, byte2,
                            set_byte1, set_byte2)


def _replace_conv_sections(prs, sets, byte1=None, byte2=None,
                           set_byte1=None, set_byte2=None):
    """Replace all conventional sets (header-byte arguments are ignored)."""
    if not sets:
        raise ValueError("No conv sets to write")
    _write_set_list(prs, "conv sets", sets)


def _build_conv_channel_raw(sets, byte1, byte2):
    """Build complete CConvChannel section from list of ConvSets."""
    header = build_class_header('CConvChannel', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else CONV_SET_MARKER
    sep = sets[0].separator if sets else CONV_CHANNEL_SEP

    for i, cset in enumerate(sets):
        parts.append(cset.channels_to_bytes())
        parts.append(cset.metadata_to_bytes())

        if i < len(sets) - 1:
            next_count = len(sets[i + 1].channels)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)

    # Trailing 2 bytes — use stored value from last set
    trailing = sets[-1].trailing_uint16 if sets else len(sets)
    parts.append(write_uint16_le(trailing))

    return b''.join(parts)


def _safe_add_conv_set(prs, conv_set):
    """Add a conv set, creating the section structure if needed."""
    ch_sec = prs.get_section_by_class("CConvChannel")
    if ch_sec:
        add_conv_set(prs, conv_set)
    else:
        _create_conv_sections(prs, [conv_set])


def _create_conv_sections(prs, sets):
    """Write the first conventional sets of a personality that had none."""
    _write_set_list(prs, "conv sets", sets)


# ─── Conventional System Creation ──────────────────────────────────

def add_conv_system(prs, config, conv_set=None):
    """Add a conventional system (CConvSystem) to the personality.

    Creates the CConvSystem header (if needed), the system config data
    section, and optionally injects the associated conv channel set.

    Args:
        prs: PRSFile object
        config: ConvSystemConfig with system parameters
        conv_set: optional ConvSet to inject
    """
    _append_system(prs, Obj("CConvSystem", [config.object_data()]))

    if conv_set:
        _safe_add_conv_set(prs, conv_set)


# ─── P25 Conventional System Creation ──────────────────────────────

def add_p25_conv_system(prs, config):
    """Add a P25 conventional system (CP25ConvSystem) to the personality.

    Creates the CP25ConvSystem header, data section, and trailing section.

    Args:
        prs: PRSFile object
        config: P25ConvSystemConfig with system parameters
    """
    _append_system(prs, Obj("CP25ConvSystem", [config.object_data()]))


# ─── Set Removal ───────────────────────────────────────────────────

def remove_trunk_set(prs, set_name):
    """Remove a trunk set by name. Rebuilds CTrunkChannel section without it.

    If removing the last set, removes both CTrunkChannel and CTrunkSet sections.

    Args:
        prs: PRSFile object
        set_name: name of the trunk set to remove

    Returns:
        True if set was removed, False if not found.
    """
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not ch_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CTrunkSet")

    existing_sets = _parse_section_data(ch_sec, parse_trunk_channel_section,
                                         first_count)

    remaining = [s for s in existing_sets if s.name != set_name]
    if len(remaining) == len(existing_sets):
        return False  # not found

    # An empty list is fine: the archive then holds a count of 0.
    _write_set_list(prs, "trunk sets", remaining)
    return True


def remove_group_set(prs, set_name):
    """Remove a group set by name. Rebuilds CP25Group section without it.

    If removing the last set, removes both CP25Group and CP25GroupSet sections.

    Args:
        prs: PRSFile object
        set_name: name of the group set to remove

    Returns:
        True if set was removed, False if not found.
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    remaining = [s for s in existing_sets if s.name != set_name]
    if len(remaining) == len(existing_sets):
        return False  # not found

    _write_set_list(prs, "group sets", remaining)
    return True


def remove_conv_set(prs, set_name):
    """Remove a conv set by name. Rebuilds CConvChannel section without it.

    If removing the last set, removes both CConvChannel and CConvSet sections.

    Args:
        prs: PRSFile object
        set_name: name of the conv set to remove

    Returns:
        True if set was removed, False if not found.
    """
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CConvSet")

    existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                         first_count)

    remaining = [s for s in existing_sets if s.name != set_name]
    if len(remaining) == len(existing_sets):
        return False  # not found

    _write_set_list(prs, "conv sets", remaining)
    return True


def rename_trunk_set(prs, old_name, new_name):
    """Rename a trunk set and the references to it (see rename_set)."""
    return rename_set(prs, "trunk", old_name, new_name)


def rename_group_set(prs, old_name, new_name):
    """Rename a group set and the references to it (see rename_set)."""
    return rename_set(prs, "group", old_name, new_name)


def rename_iden_set(prs, old_name, new_name):
    """Rename an IDEN set and the references to it (see rename_set)."""
    return rename_set(prs, "iden", old_name, new_name)


def rename_p25_conv_set(prs, old_name, new_name):
    """Rename a P25 conventional set and the references to it (see
    rename_set)."""
    return rename_set(prs, "p25conv", old_name, new_name)


def rename_conv_set(prs, old_name, new_name):
    """Rename a conventional set and the references to it (see rename_set)."""
    return rename_set(prs, "conv", old_name, new_name)


def reorder_talkgroup(prs, set_name, old_index, new_index):
    """Move a talkgroup to a new position within its group set.

    Args:
        prs: PRSFile object
        set_name: name of the group set
        old_index: current 0-based index of the talkgroup
        new_index: target 0-based index

    Returns:
        True if moved, False if set not found.

    Raises:
        IndexError: if old_index or new_index is out of range.
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        return False

    n = len(target.groups)
    if old_index < 0 or old_index >= n:
        raise IndexError(f"old_index {old_index} out of range (0..{n-1})")
    if new_index < 0 or new_index >= n:
        raise IndexError(f"new_index {new_index} out of range (0..{n-1})")
    if old_index == new_index:
        return True  # no-op

    grp = target.groups.pop(old_index)
    target.groups.insert(new_index, grp)

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)
    return True


def reorder_conv_channel(prs, set_name, old_index, new_index):
    """Move a conv channel to a new position within its set.

    Args:
        prs: PRSFile object
        set_name: name of the conv set
        old_index: current 0-based index
        new_index: target 0-based index

    Returns:
        True if moved, False if set not found.

    Raises:
        IndexError: if old_index or new_index is out of range.
    """
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CConvSet")

    existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        return False

    n = len(target.channels)
    if old_index < 0 or old_index >= n:
        raise IndexError(f"old_index {old_index} out of range (0..{n-1})")
    if new_index < 0 or new_index >= n:
        raise IndexError(f"new_index {new_index} out of range (0..{n-1})")
    if old_index == new_index:
        return True  # no-op

    ch = target.channels.pop(old_index)
    target.channels.insert(new_index, ch)

    _replace_conv_sections(prs, existing_sets, byte1, byte2,
                            set_byte1, set_byte2)
    return True


def reorder_trunk_channel(prs, set_name, old_index, new_index):
    """Move a trunk channel to a new position within its set.

    Args:
        prs: PRSFile object
        set_name: name of the trunk set
        old_index: current 0-based index
        new_index: target 0-based index

    Returns:
        True if moved, False if set not found.

    Raises:
        IndexError: if old_index or new_index is out of range.
    """
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not ch_sec or not set_sec:
        return False

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CTrunkSet")

    existing_sets = _parse_section_data(ch_sec, parse_trunk_channel_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        return False

    n = len(target.channels)
    if old_index < 0 or old_index >= n:
        raise IndexError(f"old_index {old_index} out of range (0..{n-1})")
    if new_index < 0 or new_index >= n:
        raise IndexError(f"new_index {new_index} out of range (0..{n-1})")
    if old_index == new_index:
        return True  # no-op

    ch = target.channels.pop(old_index)
    target.channels.insert(new_index, ch)

    _replace_trunk_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)
    return True


def edit_personality(prs, filename=None, saved_by=None):
    """Edit CPersonality metadata fields.

    Args:
        prs: PRSFile object
        filename: new personality name (None = don't change)
        saved_by: new author/saved-by (None = don't change)

    Returns:
        True if changes were made, False otherwise.
    """
    from .record_types import parse_personality_section, build_personality_section

    sec = prs.get_section_by_class("CPersonality")
    if not sec:
        return False

    personality = parse_personality_section(sec.raw)

    changed = False
    if filename is not None and filename != personality.filename:
        personality.filename = filename
        changed = True
    if saved_by is not None and saved_by != personality.saved_by:
        personality.saved_by = saved_by
        changed = True

    if not changed:
        return False

    try:
        new_raw = build_personality_section(personality)
    except struct.error:
        # the header's name/value block has a one-byte length
        raise ValueError("the personality name and saved-by are too long "
                         "(the header holds 255 bytes for them and three "
                         "other fields)") from None
    idx = _find_section_index(prs, "CPersonality")
    if idx < 0:
        raise ValueError("CPersonality section not found")
    prs.sections[idx] = Section(offset=0, raw=new_raw,
                                 class_name="CPersonality")
    _set_document_names(prs, personality.filename, personality.saved_by)
    return True


def _set_document_names(prs, name, user):
    """The personality name and user name are stored twice: in the
    CPersonality header and among the document fields after the options
    (RPM writes the same values in both).  Set the second copy."""
    try:
        doc = archive.document_from_prs(prs)
    except archive.WalkError:
        return
    fields = doc.root.parts[6]
    _, pos = archive.read_cstring(fields, 0)
    flags = fields[pos:pos + 2]
    _, end = archive.read_cstring(fields, pos + 2)
    doc.root.parts[6] = (archive.write_cstring(name) + flags +
                         archive.write_cstring(user) + fields[end:])
    archive.write_document(prs, doc)


def remove_wan_entry(prs, wan_name):
    """Remove a WAN entry by name from CP25TrkWan and update CP25tWanOpts.

    Args:
        prs: PRSFile object
        wan_name: WAN name to remove (will strip/compare)

    Returns:
        True if entry was removed, False if not found.
    """
    doc = archive.document_from_prs(prs)
    wan_list = _wan_list(doc)
    if wan_list is None:
        return False

    def _name(item):
        return P25TrkWanEntry.parse(item.parts[0], 0)[0].wan_name.strip()

    remaining = [i for i in wan_list.items
                 if i is None or _name(i) != wan_name.strip()]
    if len(remaining) == len(wan_list.items):
        return False  # not found

    # An emptied WAN list stays as CP25tWanOpts with a count of 0.
    wan_list.items = remaining
    archive.write_document(prs, doc)
    return True


# ─── System Removal ─────────────────────────────────────────────────

def remove_system_config(prs, long_name):
    """Remove the system whose long display name is ``long_name``.

    Args:
        prs: PRSFile object
        long_name: the system's long display name (e.g., "PSERN SEATTLE")

    Returns:
        True if a system was removed, False if not found.
    """
    doc = archive.document_from_prs(prs)
    systems = doc.list("systems")
    for i, obj in enumerate(systems.items):
        if obj is not None and _system_obj_names(obj)[1] == long_name:
            del systems.items[i]
            archive.write_document(prs, doc)
            return True
    return False


def remove_system_by_class(prs, class_name, system_name=None):
    """Remove the systems of one class, or one of them by short name.

    Args:
        prs: PRSFile object
        class_name: "CP25TrkSystem", "CConvSystem", or "CP25ConvSystem"
        system_name: optional short name to target a specific system.
                     If None, removes ALL systems of this class.

    Returns:
        Number of systems removed.
    """
    doc = archive.document_from_prs(prs)
    systems = doc.list("systems")
    keep = []
    removed = 0
    for obj in systems.items:
        if (obj is not None and obj.cls == class_name and
                (system_name is None or
                 _system_obj_names(obj)[0] == system_name)):
            removed += 1
        else:
            keep.append(obj)
    if removed:
        systems.items = keep
        archive.write_document(prs, doc)
    return removed


# ─── Bulk Edit Operations ────────────────────────────────────────────

def bulk_edit_talkgroups(prs, set_name, enable_scan=None, enable_tx=None,
                          prefix=None, suffix=None):
    """Bulk-modify talkgroups in a group set.

    Args:
        prs: PRSFile object
        set_name: name of the group set (e.g., "PSERN PD")
        enable_scan: if True/False, set scan flag on all TGs
        enable_tx: if True/False, set TX flag on all TGs
        prefix: add prefix to all short names (truncated to 8 chars)
        suffix: add suffix to all short names (truncated to 8 chars)

    Returns:
        Number of talkgroups modified.

    Raises:
        ValueError: if set_name not found or no modifications specified.
    """
    if (enable_scan is None and enable_tx is None
            and prefix is None and suffix is None):
        raise ValueError("No modifications specified")

    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        raise ValueError("No existing group sections found")

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"Group set '{set_name}' not found")

    count = 0
    for grp in target.groups:
        modified = False
        if enable_scan is not None:
            grp.scan = enable_scan
            modified = True
        if enable_tx is not None:
            grp.tx = enable_tx
            modified = True
        if prefix is not None:
            new_name = (prefix + grp.group_name)[:8]
            grp.group_name = new_name
            modified = True
        if suffix is not None:
            new_name = (grp.group_name.rstrip() + suffix)[:8]
            grp.group_name = new_name
            modified = True
        if modified:
            count += 1

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)

    logger.info("Bulk-edited %d talkgroups in set '%s'", count, set_name)
    return count


def bulk_edit_channels(prs, set_name, set_tone=None, clear_tones=None,
                        set_power=None):
    """Bulk-modify conventional channels in a conv set.

    Args:
        prs: PRSFile object
        set_name: name of the conv set (e.g., "MURS")
        set_tone: CTCSS tone string to set on all channels (e.g., "100.0")
        clear_tones: if True, clear all tones from all channels
        set_power: power level to set (0=low, 1=med, 2=high)

    Returns:
        Number of channels modified.

    Raises:
        ValueError: if set_name not found or no modifications specified.
    """
    if set_tone is None and clear_tones is None and set_power is None:
        raise ValueError("No modifications specified")

    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        raise ValueError("No existing conv sections found")

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CConvSet")

    existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"Conv set '{set_name}' not found")

    count = 0
    for ch in target.channels:
        modified = False
        if set_tone is not None:
            ch.tx_tone = set_tone
            ch.rx_tone = set_tone
            ch.tone_mode = True
            modified = True
        if clear_tones:
            ch.tx_tone = ""
            ch.rx_tone = ""
            ch.tone_mode = False
            modified = True
        if set_power is not None:
            # Rebuild pre_long_name with new power level
            plnb = bytearray(ch.pre_long_name)
            plnb[1] = set_power
            ch.pre_long_name = bytes(plnb)
            # Also update trailer if it mirrors power level
            trail = bytearray(ch.trailer)
            trail[3] = set_power
            ch.trailer = bytes(trail)
            modified = True
        if modified:
            count += 1

    _replace_conv_sections(prs, existing_sets, byte1, byte2,
                            set_byte1, set_byte2)

    logger.info("Bulk-edited %d channels in set '%s'", count, set_name)
    return count


# ─── Encryption Operations ───────────────────────────────────────────

def set_talkgroup_encryption(prs, set_name, group_id=None, encrypted=True,
                              key_id=0):
    """Set encryption on a talkgroup or all talkgroups in a set.

    Args:
        prs: PRSFile object
        set_name: name of the group set (e.g., "PSERN PD")
        group_id: specific talkgroup ID to modify, or None for all
        encrypted: True to enable encryption, False to disable
        key_id: encryption key ID (uint32, 0=none)

    Returns:
        Number of talkgroups modified.

    Raises:
        ValueError: if set_name not found or group_id not found.
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        raise ValueError("No existing group sections found")

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"Group set '{set_name}' not found")

    count = 0
    for g in target.groups:
        if group_id is not None and g.group_id != group_id:
            continue
        g.encrypted = encrypted
        g.key_id = key_id if encrypted else 0
        count += 1

    if group_id is not None and count == 0:
        raise ValueError(f"Talkgroup {group_id} not found in '{set_name}'")

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)

    logger.info("Set encryption on %d TGs in '%s' (encrypted=%s, key_id=%d)",
                count, set_name, encrypted, key_id)
    return count


# ─── NAC Operations ──────────────────────────────────────────────────

def set_p25_conv_nac(prs, set_name, channel_index, nac_tx=None, nac_rx=None):
    """Set NAC (Network Access Code) on a P25 conventional channel.

    Args:
        prs: PRSFile object
        set_name: name of the P25 conv set
        channel_index: 0-based index of the channel in the set
        nac_tx: TX NAC value (uint16, 0-0xFFF), or None to leave unchanged
        nac_rx: RX NAC value (uint16, 0-0xFFF), or None to leave unchanged

    Returns:
        True if modified.

    Raises:
        ValueError: if set/channel not found or NAC values out of range.
    """
    from .record_types import (
        parse_p25_conv_channel_section, build_p25_conv_channel_section,
        build_p25_conv_set_section,
    )

    ch_sec = prs.get_section_by_class("CP25ConvChannel")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    if not ch_sec or not set_sec:
        raise ValueError("No existing P25 conv sections found")

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25ConvSet")

    existing_sets = _parse_section_data(ch_sec,
                                         parse_p25_conv_channel_section,
                                         first_count)

    target = None
    for s in existing_sets:
        if s.name == set_name:
            target = s
            break
    if not target:
        raise ValueError(f"P25 conv set '{set_name}' not found")

    if channel_index < 0 or channel_index >= len(target.channels):
        raise ValueError(
            f"Channel index {channel_index} out of range "
            f"(0..{len(target.channels) - 1})")

    ch = target.channels[channel_index]

    if nac_tx is not None:
        if nac_tx < 0 or nac_tx > 0xFFF:
            raise ValueError(f"NAC TX {nac_tx:#x} out of range (0-FFF)")
        ch.nac_tx = nac_tx
    if nac_rx is not None:
        if nac_rx < 0 or nac_rx > 0xFFF:
            raise ValueError(f"NAC RX {nac_rx:#x} out of range (0-FFF)")
        ch.nac_rx = nac_rx

    _replace_p25_conv_sections(prs, existing_sets)

    logger.info("Set NAC on channel %d in '%s' (tx=%s, rx=%s)",
                channel_index, set_name,
                f"{nac_tx:#x}" if nac_tx is not None else "unchanged",
                f"{nac_rx:#x}" if nac_rx is not None else "unchanged")
    return True


# ─── Scan Priority Operations ────────────────────────────────────────

def reorder_preferred_entries(prs, new_order):
    """Reorder preferred system table entries.

    Args:
        prs: PRSFile object
        new_order: list of system_id values in desired priority order

    Returns:
        True if reordered, False if no preferred section exists.

    Raises:
        ValueError: if new_order doesn't match existing entries.
    """
    doc = archive.document_from_prs(prs)
    system = _first_ecc_system(doc)
    if system is None:
        return False
    entries = _preferred_entries_of(system)

    if len(new_order) != len(entries):
        raise ValueError(
            f"new_order has {len(new_order)} items but there are "
            f"{len(entries)} entries")

    # Build a map of system_id -> entry
    entry_map = {}
    for e in entries:
        entry_map[e.system_id] = e

    # Validate all IDs exist
    for sid in new_order:
        if sid not in entry_map:
            raise ValueError(f"System ID {sid} not found in preferred entries")

    # Reorder and reassign sequence indices
    reordered = []
    for i, sid in enumerate(new_order):
        entry = entry_map[sid]
        entry.field2 = i
        reordered.append(entry)

    system.lists()[0].items = [
        Obj("CPreferredSystemTableEntry", [e.to_bytes()[:13]])
        for e in reordered]
    archive.write_document(prs, doc)

    logger.info("Reordered %d preferred entries", len(reordered))
    return True


# ─── Convenience Builders ────────────────────────────────────────────

def make_p25_group(group_id, short_name, long_name="",
                   tx=False, scan=True, rx=True):
    """Create a P25Group with NAS monitoring defaults.

    Args:
        group_id: decimal talkgroup ID
        short_name: 8-char max display name
        long_name: 16-char max long name (defaults to short_name if empty)
    """
    if len(short_name) > 8:
        short_name = short_name[:8]
    if not long_name:
        long_name = short_name
    if len(long_name) > 16:
        long_name = long_name[:16]

    return P25Group(
        group_name=short_name,
        group_id=group_id,
        long_name=long_name,
        tx=tx, rx=rx, scan=scan,
        calls=True, alert=True,
        scan_list_member=True, backlight=True,
    )


def make_trunk_channel(tx_freq, rx_freq=None):
    """Create a TrunkChannel with default flags.

    Args:
        tx_freq: transmit frequency in MHz
        rx_freq: receive frequency in MHz (defaults to tx_freq)
    """
    if rx_freq is None:
        rx_freq = tx_freq
    return TrunkChannel(tx_freq=tx_freq, rx_freq=rx_freq)


def make_trunk_set(name, freqs, tx_min=136.0, tx_max=870.0,
                   rx_min=136.0, rx_max=870.0):
    """Create a TrunkSet from a list of (tx, rx) frequency tuples.

    Args:
        name: set name (8-char max, e.g., "PSERN")
        freqs: list of (tx_freq, rx_freq) tuples in MHz
    """
    channels = [make_trunk_channel(tx, rx) for tx, rx in freqs]
    return TrunkSet(
        name=name[:8], channels=channels,
        tx_min=tx_min, tx_max=tx_max,
        rx_min=rx_min, rx_max=rx_max,
    )


def make_group_set(name, talkgroups, tx_default=False, scan_default=True):
    """Create a P25GroupSet from a list of (id, short_name, long_name) tuples.

    Args:
        name: set name (8-char max, e.g., "PSERN PD")
        talkgroups: list of (group_id, short_name, long_name) tuples
        tx_default: default TX enable for all groups
        scan_default: default scan enable for all groups
    """
    groups = [make_p25_group(gid, sn, ln, tx=tx_default, scan=scan_default)
              for gid, sn, ln in talkgroups]
    return P25GroupSet(name=name[:8], groups=groups)


def make_conv_channel(short_name, tx_freq, rx_freq=None,
                      tx_tone="", rx_tone="", long_name="",
                      tx=True, scan=True, narrowband=False):
    """Create a ConvChannel with default flags.

    Args:
        short_name: 8-char max display name
        tx_freq: transmit frequency in MHz
        rx_freq: receive frequency in MHz (defaults to tx_freq for simplex)
        tx_tone: CTCSS/DCS tone string (e.g., "250.3", "" for none)
        rx_tone: CTCSS/DCS tone string
        long_name: 16-char max long name (defaults to short_name)
        tx: transmit enable (False for receive-only channels like NOAA)
        scan: scan enable
        narrowband: 12.5 kHz channel (False = 25 kHz wideband)
    """
    if rx_freq is None:
        rx_freq = tx_freq
    if len(short_name) > 8:
        short_name = short_name[:8]
    if not long_name:
        long_name = short_name
    if len(long_name) > 16:
        long_name = long_name[:16]

    return ConvChannel(
        short_name=short_name, tx_freq=tx_freq, rx_freq=rx_freq,
        tx_tone=tx_tone, rx_tone=rx_tone, long_name=long_name,
        tx=tx, scan=scan, narrowband=narrowband,
    )


# Flag and trailer bytes of a P25 conventional channel as RPM 14 creates
# it (taken from an RPM-saved personality): RX, call and alert tones, scan
# list member, scan, backlight and TX on; tone mode and narrowband set.
_RPM_P25_CONV_FLAGS = bytes.fromhex(
    "00010101010001000000010100010100000000010001")
_RPM_P25_CONV_TRAILER = bytes.fromhex(
    "0000000000010001000000000000000000000000")


def make_p25_conv_channel(short_name, tx_freq, rx_freq=None, nac_tx=0x293,
                          nac_rx=None, long_name="", tx=True, rx=True,
                          scan=True):
    """Create a P25 conventional channel with RPM's default flags.

    NACs are 12-bit (0x000-0xFFF); 0x293 is the P25 default.
    """
    from .record_types import P25ConvChannel
    if rx_freq is None:
        rx_freq = tx_freq
    if nac_rx is None:
        nac_rx = nac_tx
    for label, nac in (("TX", nac_tx), ("RX", nac_rx)):
        if not 0 <= nac <= 0xFFF:
            raise ValueError(f"{label} NAC {nac:#x} out of range (0-FFF)")
    ch = P25ConvChannel(short_name=short_name[:8], tx_freq=tx_freq,
                        rx_freq=rx_freq, nac_tx=nac_tx, nac_rx=nac_rx,
                        long_name=(long_name or short_name)[:16],
                        trailer=_RPM_P25_CONV_TRAILER)
    ch.flags = _RPM_P25_CONV_FLAGS
    ch.tx = ch.tx_enable = tx
    ch.rx = rx
    ch.scan = scan
    return ch


def make_p25_conv_set(name, channels_data, group_set_ref=""):
    """Create a P25ConvSet from dicts with short_name, tx_freq, rx_freq,
    nac_tx, nac_rx, long_name, tx, rx and scan keys."""
    from .record_types import P25ConvSet
    channels = [make_p25_conv_channel(
        short_name=d['short_name'], tx_freq=d['tx_freq'],
        rx_freq=d.get('rx_freq'), nac_tx=d.get('nac_tx', 0x293),
        nac_rx=d.get('nac_rx'), long_name=d.get('long_name', ''),
        tx=d.get('tx', True), rx=d.get('rx', True), scan=d.get('scan', True))
        for d in channels_data]
    return P25ConvSet(name=name[:8], channels=channels,
                      group_set_ref=group_set_ref[:8])


def make_conv_set(name, channels_data):
    """Create a ConvSet from channel data.

    Args:
        name: set name (8-char max, e.g., "FURRY NB")
        channels_data: list of dicts with keys:
            short_name, tx_freq, rx_freq (optional), tx_tone, rx_tone,
            long_name (optional)
    """
    channels = []
    for ch in channels_data:
        channels.append(make_conv_channel(
            short_name=ch['short_name'],
            tx_freq=ch['tx_freq'],
            rx_freq=ch.get('rx_freq'),
            tx_tone=ch.get('tx_tone', ''),
            rx_tone=ch.get('rx_tone', ''),
            long_name=ch.get('long_name', ''),
            tx=ch.get('tx', True),
            scan=ch.get('scan', True),
            narrowband=ch.get('narrowband', False),
        ))
    return ConvSet(name=name[:8], channels=channels)


def make_iden_set(name, entries):
    """Create an IdenDataSet from channel identifier entries.

    Args:
        name: set name (8-char max, e.g., "BEE00")
        entries: list of dicts with keys:
            base_freq_hz, chan_spacing_hz, bandwidth_hz, tx_offset, iden_type
            (all optional, defaults to standard P25 FDMA values)
    """
    elements = []
    for entry in entries:
        elem = IdenElement(
            base_freq_hz=entry.get('base_freq_hz', 0),
            chan_spacing_hz=entry.get('chan_spacing_hz', 12500),
            bandwidth_hz=entry.get('bandwidth_hz', 6250),
            iden_type=entry.get('iden_type', 0),
        )
        # tx_offset is stored as float32 LE (MHz) in the binary.
        # Accept both 'tx_offset_mhz' (float MHz) and raw 'tx_offset' (uint32).
        if 'tx_offset_mhz' in entry:
            elem.tx_offset_mhz = entry['tx_offset_mhz']
        else:
            elem.tx_offset = entry.get('tx_offset', 0)
        elements.append(elem)
    # Pad to 16 slots
    while len(elements) < IdenDataSet.SLOTS:
        elements.append(IdenElement())
    return IdenDataSet(name=name[:8], elements=elements[:IdenDataSet.SLOTS])


def auto_iden_from_frequencies(frequencies_mhz, set_name=None):
    """Auto-detect IDEN parameters from a list of frequencies.

    Groups frequencies by P25 band and creates IdenDataSet entries with
    the correct base_freq, spacing, bandwidth, and FDMA/TDMA type for
    each detected band. Supports mixed-band systems.

    Args:
        frequencies_mhz: list of floats (RX freqs in MHz) or list of
            (tx, rx) tuples.
        set_name: optional IDEN set name (auto-generated if None).

    Returns:
        (IdenDataSet, list of str) — the IDEN set and a list of
        human-readable descriptions of what was detected. Returns
        (None, []) if no valid bands detected.
    """
    from .iden_library import (
        detect_p25_band, build_standard_iden_entries,
        _standard_700_iden, _standard_800_iden, _standard_900_iden,
        _derive_iden_from_freqs,
    )

    if not frequencies_mhz:
        return None, []

    # Normalize to individual frequencies for band detection.
    # When given (tx, rx) tuples, include both values — detect_p25_band
    # will match whichever falls in a known band.
    all_freqs = []
    for f in frequencies_mhz:
        if isinstance(f, (list, tuple)):
            for val in f:
                all_freqs.append(float(val))
        else:
            all_freqs.append(float(f))

    # Group by band — deduplicate within bands
    bands = {}  # band_name -> list of freqs
    for freq in all_freqs:
        band_name, tx_offset = detect_p25_band(freq)
        if band_name:
            # Normalize 700_upper to 700
            key = '700' if band_name == '700_upper' else band_name
            bands.setdefault(key, []).append(freq)

    if not bands:
        return None, []

    # Detect TDMA by checking if frequencies use 6.25 kHz spacing
    def _has_tdma_spacing(freqs):
        """Check if any pair of frequencies suggests 6.25 kHz spacing."""
        sorted_f = sorted(set(freqs))
        for i in range(len(sorted_f) - 1):
            diff_hz = round((sorted_f[i + 1] - sorted_f[i]) * 1_000_000)
            if diff_hz > 0 and diff_hz % 6250 == 0 and diff_hz % 12500 != 0:
                return True
        return False

    # Band parameters: (base_generator, tx_offset, max_entries)
    band_config = {
        '700': (_standard_700_iden, 30.0, 16),
        '800': (_standard_800_iden, -45.0, 16),
        '900': (_standard_900_iden, -39.0, 8),
        'VHF': (None, 0.0, 16),
        'UHF': (None, 0.0, 16),
    }

    # Collect entries per band, then allocate slots proportionally
    band_entries = {}  # band_name -> list of active entry dicts
    descriptions = []

    for band_name in ['700', '800', '900', 'VHF', 'UHF']:
        if band_name not in bands:
            continue

        freqs = bands[band_name]
        is_tdma = _has_tdma_spacing(freqs)
        spacing = 6250 if is_tdma else 12500
        bw = 6250 if is_tdma else 12500
        base_kw = {}
        if band_name == '800':
            # The table must reach every listed frequency in whole steps:
            # 12.5 kHz from 851.0125 covers the 800 MHz channel centres,
            # anything on a 6.25 kHz offset needs 6.25 kHz from 851.00625.
            if is_tdma:
                spacing = bw = 6250
                base_kw = {'base_hz': 851006250}
            else:
                spacing = bw = 12500
        iden_type = 1 if is_tdma else 0
        mode_str = "TDMA" if is_tdma else "FDMA"

        gen_fn, tx_offset, max_entries = band_config[band_name]

        if gen_fn is not None:
            entries = gen_fn(spacing, bw, tx_offset, iden_type, **base_kw)
        else:
            # VHF/UHF — derive from actual frequencies
            entries = _derive_iden_from_freqs(
                freqs, spacing, bw, tx_offset, iden_type)

        # Only keep active entries (non-zero base_freq)
        active = [e for e in entries if e.get('base_freq_hz', 0) > 0]
        band_entries[band_name] = active

        freq_min = min(freqs)
        freq_max = max(freqs)
        descriptions.append(
            f"{band_name} MHz band ({freq_min:.4f}-{freq_max:.4f} MHz, "
            f"{len(freqs)} freqs, {mode_str}, "
            f"spacing={spacing} Hz)")

    if not band_entries:
        return None, []

    # Allocate 16 slots proportionally across bands
    num_bands = len(band_entries)
    if num_bands == 1:
        # Single band gets all 16 slots
        only_band = list(band_entries.keys())[0]
        all_entries = band_entries[only_band][:16]
    else:
        # Distribute slots evenly, remainder goes to first bands
        slots_per_band = 16 // num_bands
        extra_slots = 16 % num_bands
        all_entries = []
        for i, band_name in enumerate(
                ['700', '800', '900', 'VHF', 'UHF']):
            if band_name not in band_entries:
                continue
            n = slots_per_band + (1 if i < extra_slots else 0)
            all_entries.extend(band_entries[band_name][:n])

    # Pad with empty entries to fill 16 slots
    while len(all_entries) < 16:
        all_entries.append({
            'base_freq_hz': 0, 'chan_spacing_hz': 0,
            'bandwidth_hz': 0, 'tx_offset': 0, 'iden_type': 0,
        })

    # Generate a name if not provided
    if not set_name:
        band_keys = sorted(bands.keys())
        if len(band_keys) == 1:
            b = band_keys[0]
            is_tdma = _has_tdma_spacing(bands[b])
            mode = "T" if is_tdma else "F"
            set_name = f"{b[0]}{mode}AUT"
        else:
            set_name = "MAUTO"
    set_name = set_name[:8]

    iden_set = make_iden_set(set_name, all_entries)
    return iden_set, descriptions


# ─── PRS File Merging ────────────────────────────────────────────────

def merge_prs(target, source, include_systems=True, include_channels=True):
    """Merge data from source PRS into target PRS.

    Copies P25 trunked systems (with their trunk, talkgroup and IDEN sets
    and their WAN entry) and conventional and P25 conventional systems
    (with their channel sets) from source to target, exactly as the
    source has them.  Skips systems whose short name the target already
    has, and systems naming a set that the target holds with other
    contents under the same name (systems find their sets by name, so the
    merged system would get the target's set).

    Args:
        target: PRSFile object (modified in-place)
        source: PRSFile object (read-only)
        include_systems: if True, merge P25 trunked systems
        include_channels: if True, merge conventional and P25
            conventional systems

    Returns:
        dict with merge statistics:
            p25_added: number of P25 systems added
            p25_skipped: number of P25 systems skipped
            conv_added: number of conventional systems added
            conv_skipped: number of conventional systems skipped
            conflicts: one line per system skipped over a set name clash
    """
    stats = {
        'p25_added': 0,
        'p25_skipped': 0,
        'conv_added': 0,
        'conv_skipped': 0,
        'conflicts': [],
    }
    t_doc = archive.document_from_prs(target)
    s_doc = archive.document_from_prs(source)
    t_systems = t_doc.list("systems").items
    t_names = {_system_obj_names(o)[0] for o in t_systems if o is not None}

    for obj in s_doc.list("systems").items:
        if obj is None:
            continue
        p25 = obj.cls == "CP25TrkSystem"
        if not (include_systems if p25 else include_channels):
            continue
        kind = 'p25' if p25 else 'conv'
        name = _system_obj_names(obj)[0]
        if name in t_names:
            logger.debug("Skipping system '%s' (already in target)", name)
            stats[f'{kind}_skipped'] += 1
            continue

        copies, clashes = [], []
        for list_name, set_name in _system_obj_refs(obj):
            if not set_name:
                continue
            src = _find_set_obj(s_doc, list_name, set_name)
            have = _find_set_obj(t_doc, list_name, set_name)
            if have is None:
                if src is not None:
                    copies.append((list_name, src))
            elif src is not None and have != src:
                clashes.append(set_name)
        if clashes:
            stats['conflicts'].append(
                f"{name}: the target has other sets named "
                f"{', '.join(repr(c) for c in clashes)}")
            stats[f'{kind}_skipped'] += 1
            continue

        for list_name, src in copies:
            t_doc.list(list_name).items.append(src)
        if p25:
            _merge_wan_entry(t_doc, s_doc, _system_obj_wan_name(obj))
        t_systems.append(obj)
        t_names.add(name)
        stats[f'{kind}_added'] += 1

    archive.write_document(target, t_doc)
    return stats


def _find_set_obj(doc, list_name, set_name):
    for o in doc.list(list_name).items:
        if o is not None and _set_obj_name(o) == set_name:
            return o
    return None


def _merge_wan_entry(t_doc, s_doc, wan_name):
    """Copy the source's WAN entry for wan_name unless the target has one."""
    def entries(doc):
        opts = doc.option("CP25tWanOpts")
        return opts.parts[0].items if opts is not None else None

    src, dst = entries(s_doc), entries(t_doc)
    if src is None or dst is None:
        return

    def wan(o):
        return archive.read_cstring(o.parts[0], 0)[0].strip()

    if any(o is not None and wan(o) == wan_name.strip() for o in dst):
        return
    for o in src:
        if o is not None and wan(o) == wan_name.strip():
            dst.append(o)
            return


def _parse_source_sets(prs, data_cls, set_cls, parser_func):
    """Parse data sets from a source PRS file."""
    data_sec = prs.get_section_by_class(data_cls)
    set_sec = prs.get_section_by_class(set_cls)
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw, parser_func)


def _parse_conv_set_ref(raw):
    """Extract the conv set name from a conventional system config data section.

    Layout: SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42) + LPS(long_name)
            + 12 zeros + LPS(conv_set_name)

    Returns:
        str or None
    """
    from .binary_io import read_lps
    try:
        pos = 44  # after SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
        _, pos = read_lps(raw, pos)   # skip long_name
        pos += 12                      # skip 12-byte gap
        conv_set, _ = read_lps(raw, pos)
        return conv_set if conv_set else None
    except (IndexError, ValueError):
        return None


def _populate_wan_from_source(source, config, short_name):
    """Try to populate system_id and wacn from source WAN entries."""
    wan_idx = _find_section_index(source, "CP25TrkWan")
    if wan_idx < 0:
        return
    try:
        entries = parse_wan_section(source.sections[wan_idx].raw)
        for entry in entries:
            if entry.wan_name.strip() == short_name.strip():
                config.system_id = entry.system_id
                config.wacn = entry.wacn
                return
    except Exception:
        pass


# ─── System Cloning ─────────────────────────────────────────────────


def clone_system(target, source, system_long_name):
    """Clone a specific system from source PRS into target PRS.

    Copies the system config, and finds + copies its referenced
    trunk set, group set, and IDEN set (if they don't already exist
    in the target).

    Works for P25 trunked systems and conventional systems.

    Args:
        target: PRSFile object (modified in-place)
        source: PRSFile object (read-only)
        system_long_name: the system's long display name
                          (from parse_system_long_name)

    Returns:
        dict with keys 'system', 'trunk_set', 'group_set', 'iden_set',
        'conv_set' indicating what was copied (name strings or None
        if skipped/not applicable).

    Raises:
        ValueError: if the system is not found in source.
    """
    from .record_types import P25TrkSystemConfig, ConvSystemConfig

    result = {
        'system': None,
        'trunk_set': None,
        'group_set': None,
        'iden_set': None,
        'conv_set': None,
    }

    # Find the system config data section in source by long name
    source_data_sec = None
    for sec in source.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == system_long_name:
                source_data_sec = sec
                break

    if source_data_sec is None:
        raise ValueError(
            f"System '{system_long_name}' not found in source file")

    # Check if target already has this system
    for sec in target.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == system_long_name:
                logger.info("System '%s' already exists in target, skipping",
                            system_long_name)
                return result

    # Determine system type by finding which header owns this data section
    system_type = _find_system_type(source, source_data_sec)

    # Extract set references
    trunk_ref, group_ref = parse_system_set_refs(source_data_sec.raw)
    conv_ref = _parse_conv_set_ref(source_data_sec.raw)

    # Find the header section for this system
    short_name = _find_system_short_name(source, source_data_sec)

    if system_type in ('CP25TrkSystem',):
        # P25 trunked system
        src_trunk_sets = _parse_source_sets(
            source, "CTrunkChannel", "CTrunkSet",
            parse_trunk_channel_section)
        src_group_sets = _parse_source_sets(
            source, "CP25Group", "CP25GroupSet", parse_group_section)
        src_iden_sets = _parse_source_sets(
            source, "CDefaultIdenElem", "CIdenDataSet", parse_iden_section)

        # Find matching sets
        trunk_set = None
        if trunk_ref:
            for ts in src_trunk_sets:
                if ts.name == trunk_ref:
                    trunk_set = ts
                    break

        group_set = None
        if group_ref:
            for gs in src_group_sets:
                if gs.name == group_ref:
                    group_set = gs
                    break

        iden_set = None
        for iset in src_iden_sets:
            if iset.name.strip():
                iden_set = iset
                if short_name and short_name[:5].upper() in iset.name.upper():
                    break

        # Check if target already has these sets — skip if so
        target_trunk_names = {s.name for s in _parse_source_sets(
            target, "CTrunkChannel", "CTrunkSet",
            parse_trunk_channel_section)}
        target_group_names = {s.name for s in _parse_source_sets(
            target, "CP25Group", "CP25GroupSet", parse_group_section)}
        target_iden_names = {s.name for s in _parse_source_sets(
            target, "CDefaultIdenElem", "CIdenDataSet", parse_iden_section)}

        if trunk_set and trunk_set.name in target_trunk_names:
            logger.debug("Trunk set '%s' already in target", trunk_set.name)
            trunk_set = None
        if group_set and group_set.name in target_group_names:
            logger.debug("Group set '%s' already in target", group_set.name)
            group_set = None
        if iden_set and iden_set.name in target_iden_names:
            logger.debug("IDEN set '%s' already in target", iden_set.name)
            iden_set = None

        config = P25TrkSystemConfig(
            system_name=short_name or system_long_name[:8],
            long_name=system_long_name,
            trunk_set_name=trunk_ref or "",
            group_set_name=group_ref or "",
            wan_name=short_name or system_long_name[:8],
            system_id=0,
            wacn=0,
        )
        _populate_wan_from_source(source, config, config.system_name)
        if iden_set:
            config.iden_set_name = iden_set.name

        add_p25_trunked_system(target, config,
                               trunk_set=trunk_set,
                               group_set=group_set,
                               iden_set=iden_set)

        result['system'] = system_long_name
        result['trunk_set'] = trunk_set.name if trunk_set else None
        result['group_set'] = group_set.name if group_set else None
        result['iden_set'] = iden_set.name if iden_set else None

    elif system_type in ('CConvSystem',):
        # Conventional system
        src_conv_sets = _parse_source_sets(
            source, "CConvChannel", "CConvSet",
            parse_conv_channel_section)

        conv_set = None
        if conv_ref:
            for cs in src_conv_sets:
                if cs.name == conv_ref:
                    conv_set = cs
                    break

        # Check if target already has this conv set
        target_conv_names = {s.name for s in _parse_source_sets(
            target, "CConvChannel", "CConvSet",
            parse_conv_channel_section)}
        if conv_set and conv_set.name in target_conv_names:
            logger.debug("Conv set '%s' already in target", conv_set.name)
            conv_set = None

        config = ConvSystemConfig(
            system_name=short_name or system_long_name[:8],
            long_name=system_long_name,
            conv_set_name=conv_ref or "",
        )

        add_conv_system(target, config, conv_set=conv_set)

        result['system'] = system_long_name
        result['conv_set'] = conv_set.name if conv_set else None

    else:
        raise ValueError(
            f"Unknown or unsupported system type for '{system_long_name}'")

    return result


def _system_ref_for(prs, data_sec):
    from .record_types import list_system_configs
    for ref in list_system_configs(prs):
        if ref.section is data_sec:
            return ref
    return None


def _find_system_type(prs, data_sec):
    """The system class (CP25TrkSystem, CConvSystem, CP25ConvSystem) that
    owns a config data section, from the type byte in front of it."""
    ref = _system_ref_for(prs, data_sec)
    return ref.class_name if ref else None


def _find_system_short_name(prs, data_sec):
    """The short name of the system that owns a config data section."""
    ref = _system_ref_for(prs, data_sec)
    return ref.short_name if ref else None


# ─── Channel Numbering & Auto-Naming ─────────────────────────────────


def renumber_channels(prs, set_name=None, start=1, set_type="conv"):
    """Renumber channels sequentially by prefixing short names.

    E.g., channels become "01 MURS1", "02 MURS2", etc.
    This helps users find channels quickly on the radio display.

    Args:
        prs: PRSFile object (modified in-place)
        set_name: name of set to renumber (None = all sets of type)
        start: starting number (default 1)
        set_type: "conv" for conventional, "group" for P25 talkgroups

    Returns:
        int: number of channels/groups renumbered
    """
    count = 0

    if set_type == "conv":
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not ch_sec or not set_sec:
            return 0

        byte1, byte2 = _get_header_bytes(ch_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CConvSet")

        existing_sets = _parse_section_data(ch_sec,
                                             parse_conv_channel_section,
                                             first_count)
        modified = False
        for cs in existing_sets:
            if set_name and cs.name != set_name:
                continue
            num = start
            for ch in cs.channels:
                prefix = f"{num:02d} "
                # Strip existing numeric prefix if present
                base = _strip_numeric_prefix(ch.short_name)
                new_name = (prefix + base)[:8]
                ch.short_name = new_name
                num += 1
                count += 1
            modified = True

        if modified:
            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)

    elif set_type == "group":
        grp_sec = prs.get_section_by_class("CP25Group")
        grp_set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not grp_set_sec:
            return 0

        byte1, byte2 = _get_header_bytes(grp_sec)
        set_byte1, set_byte2 = _get_header_bytes(grp_set_sec)
        first_count = _get_first_count(prs, "CP25GroupSet")

        existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                             first_count)
        modified = False
        for gs in existing_sets:
            if set_name and gs.name != set_name:
                continue
            num = start
            for g in gs.groups:
                prefix = f"{num:02d} "
                base = _strip_numeric_prefix(g.group_name)
                new_name = (prefix + base)[:8]
                g.group_name = new_name
                num += 1
                count += 1
            modified = True

        if modified:
            _replace_group_sections(prs, existing_sets, byte1, byte2,
                                     set_byte1, set_byte2)

    return count


def _strip_numeric_prefix(name):
    """Strip a leading 'NN ' numeric prefix from a name."""
    stripped = name.lstrip()
    if len(stripped) >= 3 and stripped[:2].isdigit() and stripped[2] == ' ':
        return stripped[3:]
    return name


# ─── Abbreviation tables for auto_name_talkgroups ────────────────────

_ABBREVIATIONS = {
    'dispatch': 'DISP',
    'tactical': 'TAC',
    'operations': 'OPS',
    'emergency': 'EMRG',
    'police': 'PD',
    'fire': 'FD',
    'sheriff': 'SO',
    'department': 'DEPT',
    'county': 'CO',
    'district': 'DIST',
    'hospital': 'HOSP',
    'medical': 'MED',
    'rescue': 'RESC',
    'administration': 'ADMIN',
    'command': 'CMD',
    'communications': 'COMM',
    'enforcement': 'ENF',
    'services': 'SVC',
    'service': 'SVC',
    'north': 'N',
    'south': 'S',
    'east': 'E',
    'west': 'W',
    'central': 'CTR',
    'highway': 'HWY',
    'patrol': 'PTL',
    'detective': 'DET',
    'investigation': 'INV',
    'investigations': 'INV',
    'channel': 'CH',
    'frequency': 'FREQ',
    'interoperability': 'IOPS',
    'mutual': 'MUT',
    'aid': 'AID',
    'public': 'PUB',
    'safety': 'SFTY',
    'works': 'WRK',
    'water': 'WTR',
    'transportation': 'TRAN',
    'school': 'SCH',
    'university': 'UNIV',
    'national': 'NATL',
    'federal': 'FED',
    'state': 'ST',
    'regional': 'RGN',
    'volunteer': 'VOL',
    'ambulance': 'AMB',
    'hazmat': 'HAZ',
    'corrections': 'CORR',
    'maintenance': 'MAINT',
    'security': 'SEC',
}

_DEPT_PREFIXES = {
    'police': 'PD',
    'fire': 'FD',
    'sheriff': 'SO',
    'ems': 'EMS',
    'rescue': 'RSC',
    'dispatch': 'DSP',
    'highway': 'HWY',
    'patrol': 'PTL',
}


def auto_name_talkgroups(prs, set_name, style="compact"):
    """Auto-generate talkgroup short names from long names.

    Styles:
    - "compact": "Seattle Police Dispatch" -> "SPD DISP" (smart abbreviation)
    - "numbered": "001 Dispatch", "002 Tactical", etc.
    - "department": "PD DISP", "FD TAC" (extract department prefix)

    Args:
        prs: PRSFile object (modified in-place)
        set_name: name of the group set to rename
        style: "compact", "numbered", or "department"

    Returns:
        int: number of talkgroups renamed
    """
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return 0

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    target = None
    for gs in existing_sets:
        if gs.name == set_name:
            target = gs
            break

    if not target:
        return 0

    count = 0
    for i, g in enumerate(target.groups):
        long = g.long_name.strip() if g.long_name else ""
        if not long:
            continue

        if style == "compact":
            g.group_name = _compact_name(long)[:8]
        elif style == "numbered":
            g.group_name = f"{i + 1:03d} {long}"[:8]
        elif style == "department":
            g.group_name = _department_name(long)[:8]
        else:
            continue
        count += 1

    if count > 0:
        _replace_group_sections(prs, existing_sets, byte1, byte2,
                                 set_byte1, set_byte2)

    return count


def _compact_name(long_name):
    """Generate a compact short name from a long name.

    "Seattle Police Dispatch" -> "SPD DISP"
    "Fire Tactical 2" -> "FD TAC 2"
    """
    words = long_name.split()
    if not words:
        return long_name[:8]

    parts = []
    for word in words:
        lower = word.lower()
        if lower in _ABBREVIATIONS:
            parts.append(_ABBREVIATIONS[lower])
        elif word.isdigit():
            parts.append(word)
        elif len(word) <= 3:
            parts.append(word.upper())
        else:
            parts.append(word[0].upper())

    result = ' '.join(parts)
    # If too long, try joining without spaces
    if len(result) > 8:
        result = ''.join(parts)
    return result[:8]


# ─── Batch Rename ────────────────────────────────────────────────

def batch_rename(prs, set_name, pattern, replacement, set_type="group",
                 field="short_name"):
    """Rename items in a set using regex substitution.

    Args:
        prs: PRSFile object
        set_name: name of the target set
        pattern: regex pattern to match in names
        replacement: replacement string (supports \\1, \\2 backreferences)
        set_type: "group" for talkgroups, "conv" for channels
        field: "short_name" or "long_name"

    Returns: number of items renamed

    Raises:
        ValueError: if set_name not found or invalid set_type/field

    Examples:
        # Remove "PD " prefix from all TG names
        batch_rename(prs, "PSERN PD", r"^PD ", "", set_type="group")

        # Add zone prefix
        batch_rename(prs, "PSERN PD", r"^(.+)$", r"Z1 \\1", set_type="group")

        # Replace "DISP" with "DSP"
        batch_rename(prs, "PSERN PD", "DISP", "DSP", set_type="group")
    """
    import re

    if field not in ("short_name", "long_name"):
        raise ValueError(f"Invalid field: {field} (must be 'short_name' or 'long_name')")

    regex = re.compile(pattern)

    if set_type == "group":
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            raise ValueError("No existing group sections found")

        byte1, byte2 = _get_header_bytes(grp_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CP25GroupSet")

        existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                             first_count)

        target = None
        for s in existing_sets:
            if s.name == set_name:
                target = s
                break
        if not target:
            raise ValueError(f"Group set '{set_name}' not found")

        count = 0
        max_len = 8 if field == "short_name" else 16
        for grp in target.groups:
            attr = "group_name" if field == "short_name" else "long_name"
            old_val = getattr(grp, attr)
            new_val = regex.sub(replacement, old_val)
            if new_val != old_val:
                setattr(grp, attr, new_val[:max_len])
                count += 1

        _replace_group_sections(prs, existing_sets, byte1, byte2,
                                 set_byte1, set_byte2)

    elif set_type == "conv":
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not ch_sec or not set_sec:
            raise ValueError("No existing conv sections found")

        byte1, byte2 = _get_header_bytes(ch_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CConvSet")

        existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                             first_count)

        target = None
        for s in existing_sets:
            if s.name == set_name:
                target = s
                break
        if not target:
            raise ValueError(f"Conv set '{set_name}' not found")

        count = 0
        max_len = 8 if field == "short_name" else 16
        for ch in target.channels:
            attr = field if field == "long_name" else "short_name"
            old_val = getattr(ch, attr)
            new_val = regex.sub(replacement, old_val)
            if new_val != old_val:
                setattr(ch, attr, new_val[:max_len])
                count += 1

        _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                set_byte1, set_byte2)

    else:
        raise ValueError(f"Invalid set_type: {set_type} "
                         f"(must be 'group' or 'conv')")

    logger.info("Batch-renamed %d items in set '%s'", count, set_name)
    return count


# ─── Channel Sorter ──────────────────────────────────────────────

def sort_channels(prs, set_name, set_type="conv", key="frequency",
                  reverse=False):
    """Sort channels/talkgroups within a set.

    Keys:
    - "frequency": by TX frequency (ascending) — conv sets only
    - "name": by short name (alphabetical)
    - "id": by talkgroup ID — group sets only
    - "tone": by CTCSS tone string — conv sets only

    Args:
        prs: PRSFile object
        set_name: name of the target set
        set_type: "conv" for conventional channels, "group" for talkgroups
        key: sort key — "frequency", "name", "id", "tone"
        reverse: if True, reverse sort order

    Returns: True if sorted, False if set not found

    Raises:
        ValueError: if invalid key for the given set_type
    """
    if set_type == "conv":
        if key not in ("frequency", "name", "tone"):
            raise ValueError(f"Invalid sort key '{key}' for conv sets "
                             f"(use 'frequency', 'name', or 'tone')")

        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if not ch_sec or not set_sec:
            return False

        byte1, byte2 = _get_header_bytes(ch_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CConvSet")

        existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                             first_count)

        target = None
        for s in existing_sets:
            if s.name == set_name:
                target = s
                break
        if not target:
            return False

        if key == "frequency":
            target.channels.sort(key=lambda c: c.tx_freq, reverse=reverse)
        elif key == "name":
            target.channels.sort(key=lambda c: c.short_name, reverse=reverse)
        elif key == "tone":
            target.channels.sort(key=lambda c: c.tx_tone, reverse=reverse)

        _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                set_byte1, set_byte2)
        return True

    elif set_type == "group":
        if key not in ("name", "id"):
            raise ValueError(f"Invalid sort key '{key}' for group sets "
                             f"(use 'name' or 'id')")

        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return False

        byte1, byte2 = _get_header_bytes(grp_sec)
        set_byte1, set_byte2 = _get_header_bytes(set_sec)
        first_count = _get_first_count(prs, "CP25GroupSet")

        existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                             first_count)

        target = None
        for s in existing_sets:
            if s.name == set_name:
                target = s
                break
        if not target:
            return False

        if key == "name":
            target.groups.sort(key=lambda g: g.group_name, reverse=reverse)
        elif key == "id":
            target.groups.sort(key=lambda g: g.group_id, reverse=reverse)

        _replace_group_sections(prs, existing_sets, byte1, byte2,
                                 set_byte1, set_byte2)
        return True

    else:
        raise ValueError(f"Invalid set_type: {set_type} "
                         f"(must be 'conv' or 'group')")


def _department_name(long_name):
    """Generate a department-style short name.

    "Police Dispatch" -> "PD DISP"
    "Fire Tactical" -> "FD TAC"
    """
    words = long_name.split()
    if not words:
        return long_name[:8]

    # Check if first word is a department prefix
    first_lower = words[0].lower()
    if first_lower in _DEPT_PREFIXES:
        prefix = _DEPT_PREFIXES[first_lower]
        rest_words = words[1:]
    else:
        prefix = words[0][:3].upper()
        rest_words = words[1:]

    rest_parts = []
    for word in rest_words:
        lower = word.lower()
        if lower in _ABBREVIATIONS:
            rest_parts.append(_ABBREVIATIONS[lower])
        elif word.isdigit():
            rest_parts.append(word)
        else:
            rest_parts.append(word[:3].upper())

    if rest_parts:
        return f"{prefix} {' '.join(rest_parts)}"[:8]
    return prefix[:8]
