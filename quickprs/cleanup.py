"""Duplicate detection and cleanup for PRS personality files.

Finds and removes duplicate talkgroups, channels, frequencies, and
unused data sets. Operates on the parsed PRS structure and produces
modified output.
"""

from .prs_parser import PRSFile
from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_sets_from_sections, parse_system_short_name,
    parse_system_long_name, is_system_config_data,
    parse_ecc_entries,
)


# ─── Internal helpers ─────────────────────────────────────────────────

def _parse_sets(prs, data_cls, set_cls, parser_func):
    """Parse data sets of a given type from a PRS file."""
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


def _get_system_config_refs(prs):
    """Get all set names referenced by system configurations.

    Returns a set of lowercase set name strings found in system configs.
    """
    refs = set()
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            # System configs reference trunk, group, and IDEN set names
            # via long names and ECC entries
            ln = parse_system_long_name(sec.raw)
            if ln:
                refs.add(ln.strip().lower())
            sn = parse_system_short_name(sec.raw)
            if sn:
                refs.add(sn.strip().lower())
            _, _, iden_name = parse_ecc_entries(sec.raw)
            if iden_name:
                refs.add(iden_name.strip().lower())

    # Also add names from system sections themselves
    for cls in ('CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem'):
        for sec in prs.get_sections_by_class(cls):
            sn = parse_system_short_name(sec.raw)
            if sn:
                refs.add(sn.strip().lower())

    return refs


# ─── Public API ───────────────────────────────────────────────────────

def find_duplicates(prs):
    """Find duplicate talkgroups, channels, and frequencies in a PRS file.

    Returns dict with:
        'duplicate_tgs': list of (set_name, group_id, count) for IDs
            appearing more than once in a set
        'duplicate_freqs': list of (set_name, freq_mhz, count) for
            frequencies appearing more than once in a trunk set
        'duplicate_channels': list of (set_name, short_name, count) for
            channel short names appearing more than once in a conv set
        'cross_set_tgs': list of (group_id, [set_names]) for talkgroup
            IDs that appear in multiple group sets
    """
    result = {
        'duplicate_tgs': [],
        'duplicate_freqs': [],
        'duplicate_channels': [],
        'cross_set_tgs': [],
    }

    # ── Talkgroup duplicates (within each set) ──
    group_sets = _parse_group_sets(prs)
    # Also track cross-set TG IDs
    tg_to_sets = {}  # group_id -> list of set names

    for gs in group_sets:
        seen = {}
        for g in gs.groups:
            seen[g.group_id] = seen.get(g.group_id, 0) + 1
            tg_to_sets.setdefault(g.group_id, [])
            if gs.name not in tg_to_sets[g.group_id]:
                tg_to_sets[g.group_id].append(gs.name)
        for gid, count in sorted(seen.items()):
            if count > 1:
                result['duplicate_tgs'].append((gs.name, gid, count))

    # Cross-set talkgroup duplicates
    for gid, set_names in sorted(tg_to_sets.items()):
        if len(set_names) > 1:
            result['cross_set_tgs'].append((gid, set_names))

    # ── Trunk frequency duplicates (within each set) ──
    trunk_sets = _parse_trunk_sets(prs)
    for ts in trunk_sets:
        seen = {}
        for ch in ts.channels:
            freq_key = round(ch.tx_freq, 6)
            seen[freq_key] = seen.get(freq_key, 0) + 1
        for freq, count in sorted(seen.items()):
            if count > 1:
                result['duplicate_freqs'].append((ts.name, freq, count))

    # ── Conv channel duplicates (within each set, by short_name) ──
    conv_sets = _parse_conv_sets(prs)
    for cs in conv_sets:
        seen = {}
        for ch in cs.channels:
            key = ch.short_name.strip().upper()
            seen[key] = seen.get(key, 0) + 1
        for name, count in sorted(seen.items()):
            if count > 1:
                result['duplicate_channels'].append((cs.name, name, count))

    return result


def remove_duplicates(prs, keep='first'):
    """Remove duplicate items from all data sets.

    Args:
        prs: parsed PRSFile
        keep: 'first' to keep the first occurrence, 'last' to keep the last

    Returns:
        dict with counts: {'tgs_removed': N, 'freqs_removed': N, 'channels_removed': N}

    Note: This operates on the parsed set structures. Since PRS files
    store data as raw bytes in sections, removal requires re-serializing
    the affected sections. This function returns counts only; actual
    binary modification requires using the injector to rebuild sections.
    """
    removed = {'tgs_removed': 0, 'freqs_removed': 0, 'channels_removed': 0}

    # Count duplicates that would be removed
    dupes = find_duplicates(prs)

    for _set_name, _gid, count in dupes['duplicate_tgs']:
        removed['tgs_removed'] += count - 1

    for _set_name, _freq, count in dupes['duplicate_freqs']:
        removed['freqs_removed'] += count - 1

    for _set_name, _name, count in dupes['duplicate_channels']:
        removed['channels_removed'] += count - 1

    return removed


def find_unused_sets(prs):
    """Find data sets not referenced by any system configuration.

    Returns dict with:
        'trunk_sets': list of set names not linked to any system
        'group_sets': list of set names not linked to any system
        'conv_sets': list of set names not linked to any system
        'iden_sets': list of set names not linked to any system
    """
    refs = _get_system_config_refs(prs)

    result = {
        'trunk_sets': [],
        'group_sets': [],
        'conv_sets': [],
        'iden_sets': [],
    }

    for ts in _parse_trunk_sets(prs):
        if ts.name.strip().lower() not in refs:
            result['trunk_sets'].append(ts.name)

    for gs in _parse_group_sets(prs):
        if gs.name.strip().lower() not in refs:
            result['group_sets'].append(gs.name)

    for cs in _parse_conv_sets(prs):
        if cs.name.strip().lower() not in refs:
            result['conv_sets'].append(cs.name)

    for iset in _parse_iden_sets(prs):
        if iset.name.strip().lower() not in refs:
            result['iden_sets'].append(iset.name)

    return result


def format_duplicates_report(dupes):
    """Format duplicate findings into human-readable lines.

    Args:
        dupes: dict from find_duplicates()

    Returns:
        list of strings
    """
    lines = []

    if dupes['duplicate_tgs']:
        lines.append("Duplicate Talkgroups (within same set):")
        for set_name, gid, count in dupes['duplicate_tgs']:
            lines.append(f"  [{set_name}] TG {gid}: {count} occurrences")

    if dupes['duplicate_freqs']:
        lines.append("Duplicate Frequencies (within same set):")
        for set_name, freq, count in dupes['duplicate_freqs']:
            lines.append(f"  [{set_name}] {freq:.4f} MHz: "
                         f"{count} occurrences")

    if dupes['duplicate_channels']:
        lines.append("Duplicate Channels (within same set):")
        for set_name, name, count in dupes['duplicate_channels']:
            lines.append(f"  [{set_name}] {name}: {count} occurrences")

    if dupes['cross_set_tgs']:
        lines.append("Cross-Set Talkgroup Duplicates:")
        for gid, set_names in dupes['cross_set_tgs']:
            lines.append(f"  TG {gid}: found in {', '.join(set_names)}")

    if not any([dupes['duplicate_tgs'], dupes['duplicate_freqs'],
                dupes['duplicate_channels'], dupes['cross_set_tgs']]):
        lines.append("No duplicates found.")

    return lines


def format_unused_report(unused):
    """Format unused set findings into human-readable lines.

    Args:
        unused: dict from find_unused_sets()

    Returns:
        list of strings
    """
    lines = []
    has_any = False

    for label, key in [("Trunk Sets", "trunk_sets"),
                       ("Group Sets", "group_sets"),
                       ("Conv Sets", "conv_sets"),
                       ("IDEN Sets", "iden_sets")]:
        if unused[key]:
            has_any = True
            lines.append(f"Unused {label}:")
            for name in unused[key]:
                lines.append(f"  {name}")

    if not has_any:
        lines.append("No unused sets found.")

    return lines


def cleanup_report(prs):
    """Generate a complete cleanup report for a PRS file.

    Returns:
        list of strings covering both duplicates and unused sets
    """
    lines = ["=== Cleanup Report ===", ""]

    dupes = find_duplicates(prs)
    lines.extend(format_duplicates_report(dupes))
    lines.append("")

    unused = find_unused_sets(prs)
    lines.extend(format_unused_report(unused))

    # Summary counts
    total_dupes = (
        sum(c - 1 for _, _, c in dupes['duplicate_tgs']) +
        sum(c - 1 for _, _, c in dupes['duplicate_freqs']) +
        sum(c - 1 for _, _, c in dupes['duplicate_channels'])
    )
    total_cross = len(dupes['cross_set_tgs'])
    total_unused = sum(len(v) for v in unused.values())

    lines.append("")
    lines.append(f"Summary: {total_dupes} duplicate items, "
                 f"{total_cross} cross-set TGs, "
                 f"{total_unused} unused sets")

    return lines
