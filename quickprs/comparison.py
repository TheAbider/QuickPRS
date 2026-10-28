"""PRS file comparison — diff two personality files at a semantic level.

Compares systems, group sets, trunk sets, IDEN sets, conv sets and P25
conv sets between two parsed PRS files, item by item, then compares the
two archive trees so that a difference in anything else (system settings,
radio options, personality fields) is reported too.  Produces a
structured list of differences.
"""

import dataclasses
import logging

from .prs_parser import parse_prs

logger = logging.getLogger("quickprs")

from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_p25_conv_channel_section,
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
    diffs.extend(_compare_p25_conv_sets(prs_a, prs_b))
    diffs.extend(_compare_iden_sets(prs_a, prs_b))
    diffs.extend(_compare_sections(prs_a, prs_b))
    diffs.extend(_compare_documents(prs_a, prs_b, diffs))
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


# Set fields that hold archive bookkeeping (class tags, and bytes that
# belong to the section rather than to the set), not settings
_BOOKKEEPING = frozenset({"separator", "set_marker", "trailing_bytes",
                          "trailing_uint16", "gap_bytes"})

# How many names a change line lists before "and N more"
_SHOW = 3


def _changed_fields(a, b, skip=frozenset()):
    """Names of the dataclass fields that differ between a and b; private
    fields (undecoded flag bytes) are reported as "other flags"."""
    names = [f.name for f in dataclasses.fields(a)
             if f.name not in skip and getattr(a, f.name) != getattr(b, f.name)]
    shown = [n for n in names if not n.startswith("_")]
    if len(shown) < len(names):
        shown.append("other flags")
    return shown


def _listed(names):
    names = list(names)
    text = ", ".join(names[:_SHOW])
    if len(names) > _SHOW:
        text += f" and {len(names) - _SHOW} more"
    return text


def _diff_items(items_a, items_b, key, label, noun):
    """Describe how two item lists differ, or None when they are equal.

    Items are matched by key (a talkgroup ID, a channel name ...); a
    matched item whose fields differ is a change, listed with the fields
    that changed.
    """
    if items_a == items_b:
        return None
    map_a, map_b = {}, {}
    for item in items_a:
        map_a.setdefault(key(item), item)
    for item in items_b:
        map_b.setdefault(key(item), item)
    added = [label(map_b[k]) for k in map_b if k not in map_a]
    removed = [label(map_a[k]) for k in map_a if k not in map_b]
    changed = [f"{label(map_b[k])} ({', '.join(_changed_fields(map_a[k], map_b[k]))})"
               for k in map_a if k in map_b and map_a[k] != map_b[k]]
    parts = []
    if len(items_a) != len(items_b):
        parts.append(f"{len(items_a)}->{len(items_b)} {noun}")
    if added:
        parts.append(f"+{len(added)}: {_listed(added)}")
    if removed:
        parts.append(f"-{len(removed)}: {_listed(removed)}")
    if changed:
        parts.append(f"changed {len(changed)}: {_listed(changed)}")
    if not parts:
        parts.append(f"{noun} reordered" if len(map_a) == len(items_a)
                     else f"{noun} changed")
    return "; ".join(parts)


def _diff_sets(items_attr, key, label, noun):
    """A diff_fn for _compare_set_type: the set's own fields, then its
    items."""
    def diff(set_a, set_b):
        parts = []
        fields = _changed_fields(set_a, set_b,
                                 skip=_BOOKKEEPING | {items_attr})
        if fields:
            parts.append("set fields: " + ", ".join(fields))
        items = _diff_items(getattr(set_a, items_attr),
                            getattr(set_b, items_attr), key, label, noun)
        if items:
            parts.append(items)
        return "; ".join(parts) or None
    return diff


_diff_groups = _diff_sets(
    "groups", lambda g: g.group_id,
    lambda g: f"{g.group_id} {g.group_name.strip()}", "talkgroups")

_diff_trunks = _diff_sets(
    "channels", lambda c: (round(c.tx_freq, 5), round(c.rx_freq, 5)),
    lambda c: f"{c.tx_freq:.5f}/{c.rx_freq:.5f}", "freqs")

_diff_convs = _diff_sets(
    "channels", lambda c: c.short_name,
    lambda c: c.short_name.strip() or "(unnamed)", "channels")


def _diff_idens(is_a, is_b):
    """Detail diff for IDEN sets — elements compared slot by slot."""
    parts = []
    fields = _changed_fields(is_a, is_b, skip=_BOOKKEEPING | {"elements"})
    if fields:
        parts.append("set fields: " + ", ".join(fields))
    active_a = sum(1 for e in is_a.elements if not e.is_empty())
    active_b = sum(1 for e in is_b.elements if not e.is_empty())
    if active_a != active_b:
        parts.append(f"{active_a}->{active_b} active elements")
    changed = [f"#{i} ({', '.join(_changed_fields(a, b))})"
               for i, (a, b) in enumerate(zip(is_a.elements, is_b.elements))
               if a != b]
    if changed:
        parts.append(f"changed {len(changed)}: {_listed(changed)}")
    elif len(is_a.elements) != len(is_b.elements):
        parts.append(f"{len(is_a.elements)}->{len(is_b.elements)} elements")
    return "; ".join(parts) or None


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
                             lambda s: len(s.channels), "channels",
                             _diff_convs)


def _compare_p25_conv_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "P25 Conv Set",
                             "CP25ConvChannel", "CP25ConvSet",
                             parse_p25_conv_channel_section,
                             lambda s: len(s.channels), "channels",
                             _diff_convs)


def _compare_iden_sets(prs_a, prs_b):
    return _compare_set_type(prs_a, prs_b, "IDEN Set",
                             "CDefaultIdenElem", "CIdenDataSet",
                             parse_iden_section,
                             lambda s: sum(1 for e in s.elements
                                           if not e.is_empty()),
                             "active elements", _diff_idens)


# Parts of the archive's root object, in order (see archive.Document), and
# the category a difference in each is reported under.  Lists compared item
# by item above only get a line here when that comparison found nothing.
_ROOT_PARTS = [
    ("Personality", "header fields"),
    ("System", None),
    ("Trunk Set", "set data"),
    ("Personality", "fields after the trunk sets"),
    ("Conv Set", "set data"),
    ("Options", None),
    ("Personality", "name, user and band limits"),
    ("Group Set", "set data"),
    ("P25 Conv Set", "set data"),
    ("Personality", "list after the P25 conv sets"),
    ("IDEN Set", "set data"),
    ("Radio Options", "options XML and file tail"),
]


def _system_name(obj):
    """A system object's short name (its data starts with it)."""
    data = obj.data()
    return data[1:1 + data[0]].decode("latin-1") if data else "?"


def _compare_documents(prs_a, prs_b, found):
    """Differences the item comparisons above did not report.

    The archive tree holds every object's data without class tags or
    list counts, so two files whose trees are equal hold the same
    personality; anything else that differs is reported here.
    """
    from . import archive
    reported = {cat for kind, cat, _, _ in found if kind != SAME}
    try:
        doc_a = archive.document_from_prs(prs_a)
        doc_b = archive.document_from_prs(prs_b)
    except archive.WalkError:
        if prs_a.to_bytes() != prs_b.to_bytes() and not reported:
            return [(CHANGED, "File", "Content",
                     "the files differ (layout QuickPRS cannot itemize)")]
        return []

    parts_a, parts_b = doc_a.root.parts, doc_b.root.parts
    if len(parts_a) != len(parts_b) or len(parts_a) != len(_ROOT_PARTS):
        return ([] if parts_a == parts_b else
                [(CHANGED, "File", "Content", "the files differ")])
    diffs = []
    for (cat, what), a, b in zip(_ROOT_PARTS, parts_a, parts_b):
        if a == b:
            continue
        if cat == "System":
            diffs.extend(_compare_system_objects(a.items, b.items))
        elif cat == "Options":
            # options only one file has are reported as sections
            for cls in sorted({o.cls for o in a.items if o} &
                              {o.cls for o in b.items if o}):
                oa = [o for o in a.items if o and o.cls == cls]
                ob = [o for o in b.items if o and o.cls == cls]
                if oa != ob:
                    diffs.append((CHANGED, "Options", cls, "settings differ"))
        elif what == "header fields":
            diffs.extend(_compare_personality_headers(prs_a, prs_b))
        elif what == "name, user and band limits":
            diffs.extend(_compare_doc_fields(a, b))
        elif cat in ("Personality", "Radio Options") or cat not in reported:
            diffs.append((CHANGED, cat, what, "differs"))
    return diffs


def _compare_personality_headers(prs_a, prs_b):
    """The CPersonality fields that differ (file name, saved by, save
    time ...)."""
    from .record_types import parse_personality_section
    try:
        pa = parse_personality_section(
            prs_a.get_section_by_class("CPersonality").raw)
        pb = parse_personality_section(
            prs_b.get_section_by_class("CPersonality").raw)
    except Exception:
        return [(CHANGED, "Personality", "header fields", "differs")]
    diffs = [(CHANGED, "Personality", f.name,
              f"{getattr(pa, f.name)!r} -> {getattr(pb, f.name)!r}")
             for f in dataclasses.fields(pa)
             if getattr(pa, f.name) != getattr(pb, f.name)]
    return diffs or [(CHANGED, "Personality", "header fields", "differ")]


def _compare_doc_fields(a, b):
    """Personality name, user name and band limits (the document fields
    after the options list)."""
    from . import archive
    try:
        name_a, pos_a = archive.read_cstring(a, 0)
        name_b, pos_b = archive.read_cstring(b, 0)
        user_a, end_a = archive.read_cstring(a, pos_a + 2)
        user_b, end_b = archive.read_cstring(b, pos_b + 2)
    except (IndexError, ValueError):
        return [(CHANGED, "Personality", "name, user and band limits",
                 "differ")]
    diffs = []
    if name_a != name_b:
        diffs.append((CHANGED, "Personality", "personality name",
                      f"{name_a!r} -> {name_b!r}"))
    if user_a != user_b:
        diffs.append((CHANGED, "Personality", "user name",
                      f"{user_a!r} -> {user_b!r}"))
    if (a[pos_a:pos_a + 2] != b[pos_b:pos_b + 2]
            or a[end_a:] != b[end_b:]):
        diffs.append((CHANGED, "Personality", "band limits and flags",
                      "differ"))
    return diffs


def _compare_system_objects(items_a, items_b):
    """Systems present in both files whose settings differ (systems added
    or removed are reported by _compare_systems)."""
    by_name_a, by_name_b = {}, {}
    for o in items_a:
        by_name_a.setdefault((o.cls, _system_name(o)), o)
    for o in items_b:
        by_name_b.setdefault((o.cls, _system_name(o)), o)
    labels = {"CP25TrkSystem": "P25 Trunked", "CConvSystem": "Conventional",
              "CP25ConvSystem": "P25 Conv"}
    diffs = [(CHANGED, labels.get(cls, cls), name, "system settings differ")
             for (cls, name), o in by_name_a.items()
             if (cls, name) in by_name_b and by_name_b[(cls, name)] != o]
    if not diffs and [o for o in items_a] != [o for o in items_b] and \
            set(by_name_a) == set(by_name_b):
        diffs.append((CHANGED, "System", "order", "systems reordered"))
    return diffs


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
    if not (added or removed or changed):
        lines.append("Files are identical.")

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
