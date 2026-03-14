"""PRS file comparison — diff two personality files at a semantic level.

Compares systems, group sets, trunk sets, IDEN sets, and conv sets between
two parsed PRS files. Produces a structured list of differences.
"""

import logging

from .prs_parser import parse_prs

logger = logging.getLogger("quickprs")

from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_system_short_name, parse_system_long_name,
    parse_system_set_refs,
    is_system_config_data,
    parse_sets_from_sections,
)


# Diff entry types
ADDED = "ADDED"
REMOVED = "REMOVED"
CHANGED = "CHANGED"
SAME = "SAME"


def compare_prs(prs_a, prs_b):
    """Compare two PRSFile objects.

    Returns list of (type, category, name, detail) tuples.
    """
    diffs = []
    diffs.extend(_compare_systems(prs_a, prs_b))
    diffs.extend(_compare_group_sets(prs_a, prs_b))
    diffs.extend(_compare_trunk_sets(prs_a, prs_b))
    diffs.extend(_compare_conv_sets(prs_a, prs_b))
    diffs.extend(_compare_iden_sets(prs_a, prs_b))
    diffs.extend(_compare_sections(prs_a, prs_b))
    diffs.extend(_compare_size(prs_a, prs_b))
    return diffs


def compare_prs_files(path_a, path_b):
    """Compare two PRS files by path.

    Returns list of (type, category, name, detail) tuples.
    """
    prs_a = parse_prs(path_a)
    prs_b = parse_prs(path_b)
    return compare_prs(prs_a, prs_b)


# ─── Internal comparators ────────────────────────────────────────────


def _compare_size(prs_a, prs_b):
    """Compare file sizes."""
    diffs = []
    size_a = len(prs_a.to_bytes())
    size_b = len(prs_b.to_bytes())
    if size_a != size_b:
        diffs.append((CHANGED, "File", "Size",
                       f"{size_a:,} -> {size_b:,} bytes "
                       f"({size_b - size_a:+,})"))
    diffs.append((SAME if len(prs_a.sections) == len(prs_b.sections) else CHANGED,
                  "File", "Sections",
                  f"{len(prs_a.sections)} -> {len(prs_b.sections)}"))
    return diffs


def _compare_sections(prs_a, prs_b):
    """Compare named sections between files."""
    diffs = []

    classes_a = set(s.class_name for s in prs_a.sections if s.class_name)
    classes_b = set(s.class_name for s in prs_b.sections if s.class_name)

    for cls in sorted(classes_a - classes_b):
        diffs.append((REMOVED, "Section", cls, "removed"))
    for cls in sorted(classes_b - classes_a):
        diffs.append((ADDED, "Section", cls, "added"))

    return diffs


def _get_system_names(prs, class_name):
    """Extract system short names from header sections."""
    names = []
    for sec in prs.get_sections_by_class(class_name):
        name = parse_system_short_name(sec.raw)
        if name:
            names.append(name)
    return names


def _get_config_names(prs):
    """Extract all system config long names from data sections."""
    names = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            if long_name:
                names.append(long_name)
    return names


def _compare_systems(prs_a, prs_b):
    """Compare systems between two files."""
    diffs = []

    system_types = [
        ("P25 Trunked", "CP25TrkSystem"),
        ("Conventional", "CConvSystem"),
        ("P25 Conv", "CP25ConvSystem"),
    ]

    for label, class_name in system_types:
        names_a = set(_get_system_names(prs_a, class_name))
        names_b = set(_get_system_names(prs_b, class_name))

        for name in sorted(names_a - names_b):
            diffs.append((REMOVED, label, name, "system removed"))
        for name in sorted(names_b - names_a):
            diffs.append((ADDED, label, name, "system added"))

    # Also compare config section long names
    configs_a = set(_get_config_names(prs_a))
    configs_b = set(_get_config_names(prs_b))
    for name in sorted(configs_a - configs_b):
        diffs.append((REMOVED, "System Config", name, "config removed"))
    for name in sorted(configs_b - configs_a):
        diffs.append((ADDED, "System Config", name, "config added"))

    return diffs


def _parse_sets_safe(prs, class_sec_name, set_sec_name, parser_func):
    """Safely parse sets from a PRS file. Returns [] on failure."""
    sec = prs.get_section_by_class(class_sec_name)
    set_sec = prs.get_section_by_class(set_sec_name)
    if not sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, sec.raw, parser_func)


def _compare_set_type(prs_a, prs_b, label, data_cls, set_cls,
                      parser_fn, count_fn, item_label, diff_fn=None):
    """Generic comparison for a set type.

    Args:
        label: display label (e.g. "Group Set")
        data_cls/set_cls: section class names for parsing
        parser_fn: parser function (e.g. parse_group_section)
        count_fn: callable(set) -> int, counts items in a set
        item_label: plural noun for items (e.g. "talkgroups")
        diff_fn: optional callable(set_a, set_b) -> str or None
    """
    diffs = []
    sets_a = _parse_sets_safe(prs_a, data_cls, set_cls, parser_fn)
    sets_b = _parse_sets_safe(prs_b, data_cls, set_cls, parser_fn)

    map_a = {s.name: s for s in sets_a}
    map_b = {s.name: s for s in sets_b}

    for name in sorted(set(map_a) - set(map_b)):
        diffs.append((REMOVED, label, name,
                       f"{count_fn(map_a[name])} {item_label}"))
    for name in sorted(set(map_b) - set(map_a)):
        diffs.append((ADDED, label, name,
                       f"{count_fn(map_b[name])} {item_label}"))
    for name in sorted(set(map_a) & set(map_b)):
        if diff_fn:
            change = diff_fn(map_a[name], map_b[name])
            if change:
                diffs.append((CHANGED, label, name, change))
        else:
            ca, cb = count_fn(map_a[name]), count_fn(map_b[name])
            if ca != cb:
                diffs.append((CHANGED, label, name,
                               f"{ca}->{cb} {item_label}"))

    return diffs


def _diff_groups(gs_a, gs_b):
    """Detail diff for group sets — compares talkgroup IDs."""
    ids_a = {g.group_id for g in gs_a.groups}
    ids_b = {g.group_id for g in gs_b.groups}
    added, removed = ids_b - ids_a, ids_a - ids_b
    if added or removed:
        parts = []
        if added:
            parts.append(f"+{len(added)} TGs")
        if removed:
            parts.append(f"-{len(removed)} TGs")
        return (f"{len(gs_a.groups)}->{len(gs_b.groups)} "
                f"({', '.join(parts)})")
    return None


def _diff_trunks(ts_a, ts_b):
    """Detail diff for trunk sets — compares frequencies."""
    freqs_a = {(round(c.rx_freq, 5),) for c in ts_a.channels}
    freqs_b = {(round(c.rx_freq, 5),) for c in ts_b.channels}
    added, removed = freqs_b - freqs_a, freqs_a - freqs_b
    if added or removed:
        parts = []
        if added:
            parts.append(f"+{len(added)} freqs")
        if removed:
            parts.append(f"-{len(removed)} freqs")
        return (f"{len(ts_a.channels)}->{len(ts_b.channels)} "
                f"({', '.join(parts)})")
    return None


def _diff_idens(is_a, is_b):
    """Detail diff for IDEN sets — compares active element counts."""
    active_a = sum(1 for e in is_a.elements if not e.is_empty())
    active_b = sum(1 for e in is_b.elements if not e.is_empty())
    if active_a != active_b:
        return f"{active_a}->{active_b} active elements"
    return None


def _compare_group_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "Group Set",
                             "CP25Group", "CP25GroupSet",
                             parse_group_section,
                             lambda s: len(s.groups), "talkgroups",
                             _diff_groups)


def _compare_trunk_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "Trunk Set",
                             "CTrunkChannel", "CTrunkSet",
                             parse_trunk_channel_section,
                             lambda s: len(s.channels), "freqs",
                             _diff_trunks)


def _compare_conv_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "Conv Set",
                             "CConvChannel", "CConvSet",
                             parse_conv_channel_section,
                             lambda s: len(s.channels), "channels")


def _compare_iden_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "IDEN Set",
                             "CDefaultIdenElem", "CIdenDataSet",
                             parse_iden_section,
                             lambda s: sum(1 for e in s.elements
                                           if not e.is_empty()),
                             "active elements", _diff_idens)


def format_comparison(diffs, filepath_a="", filepath_b=""):
    """Format comparison results as human-readable text.

    Returns a list of lines.
    """
    lines = []
    if filepath_a or filepath_b:
        lines.append(f"A: {filepath_a}")
        lines.append(f"B: {filepath_b}")
        lines.append("")

    if not diffs:
        lines.append("Files are identical.")
        return lines

    # Group by category
    categories = {}
    for dtype, cat, name, detail in diffs:
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((dtype, name, detail))

    for cat, entries in categories.items():
        lines.append(f"--- {cat} ---")
        for dtype, name, detail in entries:
            prefix = {
                ADDED: "+",
                REMOVED: "-",
                CHANGED: "~",
                SAME: "=",
            }.get(dtype, "?")
            lines.append(f"  {prefix} {name}: {detail}")
        lines.append("")

    # Summary
    added = sum(1 for d in diffs if d[0] == ADDED)
    removed = sum(1 for d in diffs if d[0] == REMOVED)
    changed = sum(1 for d in diffs if d[0] == CHANGED)
    lines.append(f"Summary: {added} added, {removed} removed, {changed} changed")

    return lines


# ─── Detailed comparison ─────────────────────────────────────────────


def detailed_comparison(prs_a, prs_b):
    """Produce a detailed semantic comparison between two PRS files.

    Goes deeper than compare_prs() by enumerating individual talkgroups,
    frequencies, conventional channels, and option differences for
    systems that exist in both files.

    Returns a dict with keys:
        'systems_a_only': [long_names...],
        'systems_b_only': [long_names...],
        'systems_both': [long_names...],
        'talkgroup_diffs': {system_name: {'added': [...], 'removed': [...]}},
        'freq_diffs': {set_name: {'added': [...], 'removed': [...]}},
        'conv_diffs': {set_name: {'added': [...], 'removed': [...]}},
        'option_diffs': [(field_name, val_a, val_b), ...],
    """
    result = {
        'systems_a_only': [],
        'systems_b_only': [],
        'systems_both': [],
        'talkgroup_diffs': {},
        'freq_diffs': {},
        'conv_diffs': {},
        'option_diffs': [],
    }

    # ── Systems ──────────────────────────────────────────────────────
    configs_a = _get_system_configs(prs_a)
    configs_b = _get_system_configs(prs_b)
    names_a = set(configs_a.keys())
    names_b = set(configs_b.keys())

    result['systems_a_only'] = sorted(names_a - names_b)
    result['systems_b_only'] = sorted(names_b - names_a)
    result['systems_both'] = sorted(names_a & names_b)

    # ── Talkgroup diffs (for systems in both) ────────────────────────
    group_sets_a = _parse_sets_safe_map(
        prs_a, "CP25Group", "CP25GroupSet", parse_group_section)
    group_sets_b = _parse_sets_safe_map(
        prs_b, "CP25Group", "CP25GroupSet", parse_group_section)

    for sys_name in result['systems_both']:
        raw_a = configs_a[sys_name]
        raw_b = configs_b[sys_name]
        _, group_ref_a = parse_system_set_refs(raw_a)
        _, group_ref_b = parse_system_set_refs(raw_b)

        gs_a = group_sets_a.get(group_ref_a)
        gs_b = group_sets_b.get(group_ref_b)
        if gs_a and gs_b:
            tg_map_a = {g.group_id: g for g in gs_a.groups}
            tg_map_b = {g.group_id: g for g in gs_b.groups}
            ids_a = set(tg_map_a.keys())
            ids_b = set(tg_map_b.keys())
            added_ids = sorted(ids_b - ids_a)
            removed_ids = sorted(ids_a - ids_b)
            if added_ids or removed_ids:
                added_tgs = [
                    (gid, tg_map_b[gid].group_name, tg_map_b[gid].long_name)
                    for gid in added_ids
                ]
                removed_tgs = [
                    (gid, tg_map_a[gid].group_name, tg_map_a[gid].long_name)
                    for gid in removed_ids
                ]
                result['talkgroup_diffs'][sys_name] = {
                    'added': added_tgs,
                    'removed': removed_tgs,
                }

    # ── Trunk frequency diffs ────────────────────────────────────────
    trunk_sets_a = _parse_sets_safe_map(
        prs_a, "CTrunkChannel", "CTrunkSet", parse_trunk_channel_section)
    trunk_sets_b = _parse_sets_safe_map(
        prs_b, "CTrunkChannel", "CTrunkSet", parse_trunk_channel_section)

    for set_name in sorted(set(trunk_sets_a.keys()) &
                           set(trunk_sets_b.keys())):
        ts_a = trunk_sets_a[set_name]
        ts_b = trunk_sets_b[set_name]
        freqs_a = {round(c.rx_freq, 5) for c in ts_a.channels}
        freqs_b = {round(c.rx_freq, 5) for c in ts_b.channels}
        added_freqs = sorted(freqs_b - freqs_a)
        removed_freqs = sorted(freqs_a - freqs_b)
        if added_freqs or removed_freqs:
            result['freq_diffs'][set_name] = {
                'added': added_freqs,
                'removed': removed_freqs,
            }

    # ── Conv channel diffs ───────────────────────────────────────────
    conv_sets_a = _parse_sets_safe_map(
        prs_a, "CConvChannel", "CConvSet", parse_conv_channel_section)
    conv_sets_b = _parse_sets_safe_map(
        prs_b, "CConvChannel", "CConvSet", parse_conv_channel_section)

    for set_name in sorted(set(conv_sets_a.keys()) &
                           set(conv_sets_b.keys())):
        cs_a = conv_sets_a[set_name]
        cs_b = conv_sets_b[set_name]
        ch_a = {(c.short_name, round(c.tx_freq, 5), round(c.rx_freq, 5))
                for c in cs_a.channels}
        ch_b = {(c.short_name, round(c.tx_freq, 5), round(c.rx_freq, 5))
                for c in cs_b.channels}
        added = sorted(ch_b - ch_a)
        removed = sorted(ch_a - ch_b)
        if added or removed:
            result['conv_diffs'][set_name] = {
                'added': added,
                'removed': removed,
            }

    # ── Option diffs ─────────────────────────────────────────────────
    try:
        from .option_differ import diff_options
        opt_diffs = diff_options(prs_a, prs_b)
        result['option_diffs'] = [
            (d.field_name, d.old_value, d.new_value)
            for d in opt_diffs
        ]
    except Exception:
        pass  # options comparison is best-effort

    return result


def _get_system_configs(prs):
    """Build a map of long_name -> raw bytes for all system configs."""
    configs = {}
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            if long_name:
                configs[long_name] = sec.raw
    return configs


def _parse_sets_safe_map(prs, data_cls, set_cls, parser_func):
    """Parse sets into a {name: set_obj} dict. Returns {} on failure."""
    sets = _parse_sets_safe(prs, data_cls, set_cls, parser_func)
    return {s.name: s for s in sets}


def format_detailed_comparison(detail, filepath_a="", filepath_b=""):
    """Format detailed comparison results as human-readable text.

    Args:
        detail: dict from detailed_comparison()
        filepath_a: path label for file A
        filepath_b: path label for file B

    Returns a list of lines.
    """
    lines = []
    if filepath_a or filepath_b:
        lines.append(f"A: {filepath_a}")
        lines.append(f"B: {filepath_b}")
        lines.append("")

    # ── Systems ──────────────────────────────────────────────────────
    lines.append("=== Systems ===")
    if detail['systems_a_only']:
        lines.append("  Only in A:")
        for name in detail['systems_a_only']:
            lines.append(f"    - {name}")
    if detail['systems_b_only']:
        lines.append("  Only in B:")
        for name in detail['systems_b_only']:
            lines.append(f"    + {name}")
    if detail['systems_both']:
        lines.append(f"  In both: {', '.join(detail['systems_both'])}")
    if (not detail['systems_a_only'] and not detail['systems_b_only']
            and not detail['systems_both']):
        lines.append("  (no systems)")
    lines.append("")

    # ── Talkgroup diffs ──────────────────────────────────────────────
    if detail['talkgroup_diffs']:
        lines.append("=== Talkgroup Differences ===")
        for sys_name, diffs in sorted(detail['talkgroup_diffs'].items()):
            lines.append(f"  {sys_name}:")
            for gid, short, long in diffs.get('added', []):
                lines.append(f"    + {gid} {short} ({long})")
            for gid, short, long in diffs.get('removed', []):
                lines.append(f"    - {gid} {short} ({long})")
        lines.append("")

    # ── Trunk frequency diffs ────────────────────────────────────────
    if detail['freq_diffs']:
        lines.append("=== Trunk Frequency Differences ===")
        for set_name, diffs in sorted(detail['freq_diffs'].items()):
            lines.append(f"  {set_name}:")
            for freq in diffs.get('added', []):
                lines.append(f"    + {freq:.5f} MHz")
            for freq in diffs.get('removed', []):
                lines.append(f"    - {freq:.5f} MHz")
        lines.append("")

    # ── Conv channel diffs ───────────────────────────────────────────
    if detail['conv_diffs']:
        lines.append("=== Conv Channel Differences ===")
        for set_name, diffs in sorted(detail['conv_diffs'].items()):
            lines.append(f"  {set_name}:")
            for short, tx, rx in diffs.get('added', []):
                lines.append(f"    + {short} TX:{tx:.5f} RX:{rx:.5f}")
            for short, tx, rx in diffs.get('removed', []):
                lines.append(f"    - {short} TX:{tx:.5f} RX:{rx:.5f}")
        lines.append("")

    # ── Option diffs ─────────────────────────────────────────────────
    if detail['option_diffs']:
        lines.append("=== Option Differences ===")
        for field, val_a, val_b in detail['option_diffs']:
            lines.append(f"  ~ {field}: {val_a} -> {val_b}")
        lines.append("")

    # ── Summary ──────────────────────────────────────────────────────
    n_sys_a = len(detail['systems_a_only'])
    n_sys_b = len(detail['systems_b_only'])
    n_tg = sum(
        len(d.get('added', [])) + len(d.get('removed', []))
        for d in detail['talkgroup_diffs'].values()
    )
    n_freq = sum(
        len(d.get('added', [])) + len(d.get('removed', []))
        for d in detail['freq_diffs'].values()
    )
    n_conv = sum(
        len(d.get('added', [])) + len(d.get('removed', []))
        for d in detail['conv_diffs'].values()
    )
    n_opts = len(detail['option_diffs'])
    has_diffs = any([n_sys_a, n_sys_b, n_tg, n_freq, n_conv, n_opts])

    if not has_diffs:
        lines.append("No differences found.")
    else:
        parts = []
        if n_sys_a:
            parts.append(f"{n_sys_a} system(s) only in A")
        if n_sys_b:
            parts.append(f"{n_sys_b} system(s) only in B")
        if n_tg:
            parts.append(f"{n_tg} talkgroup change(s)")
        if n_freq:
            parts.append(f"{n_freq} frequency change(s)")
        if n_conv:
            parts.append(f"{n_conv} conv channel change(s)")
        if n_opts:
            parts.append(f"{n_opts} option change(s)")
        lines.append(f"Summary: {', '.join(parts)}")

    return lines
