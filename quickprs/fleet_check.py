"""Fleet consistency checker and configuration snapshot tools.

Compare multiple PRS files for consistent configurations across a fleet
of radios. Save lightweight JSON snapshots for tracking changes over time.

Usage:
    from quickprs.fleet_check import check_fleet_consistency, format_fleet_report
    results = check_fleet_consistency(["radio1.PRS", "radio2.PRS"])
    print(format_fleet_report(results))

    from quickprs.fleet_check import save_snapshot, compare_to_snapshot
    save_snapshot(prs, "radio.PRS", "snapshot.json")
    diffs = compare_to_snapshot(prs, "snapshot.json")
"""

import json
import logging
from pathlib import Path

from .prs_parser import parse_prs
from .record_types import (
    parse_personality_section,
    parse_group_section,
    parse_conv_channel_section,
    parse_p25_conv_channel_section,
    parse_system_short_name,
    parse_system_long_name,
    parse_system_set_refs,
    is_system_config_data,
    parse_sets_from_sections,
)
from .option_maps import extract_platform_config

logger = logging.getLogger("quickprs")


# ── Fleet Consistency ─────────────────────────────────────────────────


def check_fleet_consistency(prs_files):
    """Compare multiple PRS files for consistency.

    Args:
        prs_files: list of file paths (str or Path)

    Returns dict with:
        'files': [basename list],
        'systems': {
            'all_have': [system_names present in ALL files],
            'some_missing': {system_name: [files_missing_it]},
        },
        'talkgroups': {
            'consistent': [set_names where all files have same TGs],
            'inconsistent': {set_name: {file: [tg_ids]}},
        },
        'channels': {
            'consistent': [set_names where all files match],
            'inconsistent': {set_name: {file: [(short_name, tx_freq)]}},
        },
        'options': {
            'consistent': [option_names],
            'inconsistent': {option: {file: value}},
        },
        'unit_ids': {file: unit_id},
        'versions': {file: personality_name},
    """
    if len(prs_files) < 2:
        raise ValueError("Fleet check requires at least 2 PRS files")

    parsed = {}
    for fp in prs_files:
        fp = Path(fp)
        if not fp.exists():
            raise FileNotFoundError(f"PRS file not found: {fp}")
        parsed[fp.name] = parse_prs(str(fp))

    filenames = list(parsed.keys())
    result = {'files': filenames}

    # ── Systems ───────────────────────────────────────────────────────
    file_systems = {}
    for fname, prs in parsed.items():
        file_systems[fname] = _get_system_long_names(prs)

    all_systems = set()
    for systems in file_systems.values():
        all_systems.update(systems)

    all_have = []
    some_missing = {}
    for sys_name in sorted(all_systems):
        missing = [f for f in filenames if sys_name not in file_systems[f]]
        if not missing:
            all_have.append(sys_name)
        else:
            some_missing[sys_name] = missing

    result['systems'] = {
        'all_have': all_have,
        'some_missing': some_missing,
    }

    # ── Talkgroups ────────────────────────────────────────────────────
    file_talkgroups = {}
    for fname, prs in parsed.items():
        file_talkgroups[fname] = _get_talkgroup_sets(prs)

    all_tg_sets = set()
    for tgs in file_talkgroups.values():
        all_tg_sets.update(tgs.keys())

    tg_consistent = []
    tg_inconsistent = {}
    for set_name in sorted(all_tg_sets):
        # Collect the talkgroup IDs per file for this set
        per_file = {}
        for fname in filenames:
            tg_ids = file_talkgroups[fname].get(set_name, [])
            per_file[fname] = sorted(tg_ids)

        # Check if all files that have this set have the same TGs
        values = [tuple(v) for v in per_file.values() if v]
        if values and len(set(values)) == 1 and len(values) == len(filenames):
            tg_consistent.append(set_name)
        else:
            tg_inconsistent[set_name] = per_file

    result['talkgroups'] = {
        'consistent': tg_consistent,
        'inconsistent': tg_inconsistent,
    }

    # ── Channels ──────────────────────────────────────────────────────
    file_channels = {}
    for fname, prs in parsed.items():
        file_channels[fname] = _get_conv_channel_sets(prs)

    all_ch_sets = set()
    for chs in file_channels.values():
        all_ch_sets.update(chs.keys())

    ch_consistent = []
    ch_inconsistent = {}
    for set_name in sorted(all_ch_sets):
        per_file = {}
        for fname in filenames:
            ch_list = file_channels[fname].get(set_name, [])
            per_file[fname] = sorted(ch_list)

        values = [tuple(v) for v in per_file.values() if v]
        if values and len(set(values)) == 1 and len(values) == len(filenames):
            ch_consistent.append(set_name)
        else:
            ch_inconsistent[set_name] = per_file

    result['channels'] = {
        'consistent': ch_consistent,
        'inconsistent': ch_inconsistent,
    }

    # ── Options ───────────────────────────────────────────────────────
    file_options = {}
    for fname, prs in parsed.items():
        file_options[fname] = _get_flat_options(prs)

    all_option_keys = set()
    for opts in file_options.values():
        all_option_keys.update(opts.keys())

    opt_consistent = []
    opt_inconsistent = {}
    for opt_key in sorted(all_option_keys):
        per_file = {}
        for fname in filenames:
            per_file[fname] = file_options[fname].get(opt_key, "(not set)")

        values = list(per_file.values())
        if len(set(values)) == 1:
            opt_consistent.append(opt_key)
        else:
            opt_inconsistent[opt_key] = per_file

    result['options'] = {
        'consistent': opt_consistent,
        'inconsistent': opt_inconsistent,
    }

    # ── Unit IDs ──────────────────────────────────────────────────────
    unit_ids = {}
    for fname, prs in parsed.items():
        uid = _get_home_unit_id(prs)
        unit_ids[fname] = uid

    result['unit_ids'] = unit_ids

    # ── Personality names ─────────────────────────────────────────────
    versions = {}
    for fname, prs in parsed.items():
        pers_sec = prs.get_section_by_class("CPersonality")
        if pers_sec:
            p = parse_personality_section(pers_sec.raw)
            versions[fname] = p.filename
        else:
            versions[fname] = "(unknown)"

    result['versions'] = versions

    return result


def format_fleet_report(results):
    """Format fleet consistency results as readable text.

    Args:
        results: dict from check_fleet_consistency()

    Returns:
        str: formatted report text
    """
    lines = []
    filenames = results['files']
    lines.append(f"Fleet Consistency Report ({len(filenames)} radios)")
    lines.append("")

    # ── Systems ───────────────────────────────────────────────────────
    systems = results['systems']
    lines.append("  Systems:")
    if systems['all_have']:
        lines.append(
            f"    + All radios have: {', '.join(systems['all_have'])}")
    if systems['some_missing']:
        for sys_name, missing in systems['some_missing'].items():
            lines.append(
                f"    - {sys_name}: missing from {', '.join(missing)}")
    if not systems['all_have'] and not systems['some_missing']:
        lines.append("    (no systems found)")
    lines.append("")

    # ── Talkgroups ────────────────────────────────────────────────────
    talkgroups = results['talkgroups']
    if talkgroups['consistent'] or talkgroups['inconsistent']:
        lines.append("  Talkgroups:")
        for set_name in talkgroups['consistent']:
            # Find count from any file
            for per_file in [talkgroups]:
                pass
            count = 0
            for fname in filenames:
                per = talkgroups.get('inconsistent', {}).get(set_name, {})
                if not per:
                    # It's consistent, peek at the data from results context
                    break
            # For consistent sets we just report them as matching
            lines.append(
                f"    + {set_name}: identical across all radios")
        for set_name, per_file in talkgroups['inconsistent'].items():
            details = []
            for fname, tg_ids in per_file.items():
                details.append(f"{fname}={len(tg_ids)} TGs")
            lines.append(
                f"    - {set_name}: {', '.join(details)}")
        lines.append("")

    # ── Channels ──────────────────────────────────────────────────────
    channels = results['channels']
    if channels['consistent'] or channels['inconsistent']:
        lines.append("  Channels:")
        for set_name in channels['consistent']:
            lines.append(
                f"    + {set_name}: identical across all radios")
        for set_name, per_file in channels['inconsistent'].items():
            details = []
            for fname, ch_list in per_file.items():
                details.append(f"{fname}={len(ch_list)} ch")
            lines.append(
                f"    - {set_name}: {', '.join(details)}")
        lines.append("")

    # ── Options ───────────────────────────────────────────────────────
    options = results['options']
    if options['inconsistent']:
        lines.append("  Options:")
        for opt_key in sorted(options['consistent'][:5]):
            lines.append(f"    + {opt_key}: all match")
        if len(options['consistent']) > 5:
            lines.append(
                f"    + ... and {len(options['consistent']) - 5} more "
                f"consistent options")
        for opt_key, per_file in options['inconsistent'].items():
            details = []
            for fname, val in per_file.items():
                details.append(f"{fname}={val}")
            lines.append(
                f"    - {opt_key}: {', '.join(details)}")
        lines.append("")

    # ── Unit IDs ──────────────────────────────────────────────────────
    unit_ids = results['unit_ids']
    if any(uid is not None for uid in unit_ids.values()):
        lines.append("  Unit IDs:")
        for fname, uid in unit_ids.items():
            uid_str = str(uid) if uid is not None else "(none)"
            lines.append(f"    {fname}: {uid_str}")
        # Check uniqueness
        non_none = [uid for uid in unit_ids.values() if uid is not None]
        if non_none and len(set(non_none)) == len(non_none):
            lines.append("    (all unique)")
        elif non_none and len(set(non_none)) < len(non_none):
            lines.append("    WARNING: duplicate unit IDs detected")
        lines.append("")

    return "\n".join(lines)


# ── Snapshot ──────────────────────────────────────────────────────────


def save_snapshot(prs, filepath, snapshot_path=None):
    """Save a configuration snapshot (JSON summary) for later comparison.

    The snapshot captures the logical configuration: system names,
    talkgroup IDs, channel frequencies, and option values. It is NOT
    a copy of the binary — just the decoded config state.

    Args:
        prs: PRSFile object
        filepath: path of the original .PRS file (for metadata)
        snapshot_path: output path for the JSON snapshot file.
            If None, defaults to <filepath>.snapshot.json

    Returns:
        str: path to the saved snapshot file
    """
    filepath = Path(filepath)
    if snapshot_path is None:
        snapshot_path = filepath.with_suffix('.snapshot.json')
    else:
        snapshot_path = Path(snapshot_path)

    snap = _build_snapshot(prs, str(filepath))

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(snap, indent=2, ensure_ascii=False),
        encoding='utf-8')

    return str(snapshot_path)


def compare_to_snapshot(prs, snapshot_path):
    """Compare current personality against a saved snapshot.

    Args:
        prs: PRSFile object (current state)
        snapshot_path: path to a previously saved snapshot JSON

    Returns dict with:
        'source_file': original filename from snapshot,
        'systems': {
            'added': [names in current but not snapshot],
            'removed': [names in snapshot but not current],
            'unchanged': [names in both],
        },
        'talkgroups': {
            set_name: {
                'added': [(id, short_name)],
                'removed': [(id, short_name)],
            }
        },
        'channels': {
            set_name: {
                'added': [(short_name, tx_freq)],
                'removed': [(short_name, tx_freq)],
            }
        },
        'options': {
            'added': {key: new_value},
            'removed': {key: old_value},
            'changed': {key: (old, new)},
        },
    """
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    snap = json.loads(snapshot_path.read_text(encoding='utf-8'))

    current_snap = _build_snapshot(prs, "")

    result = {'source_file': snap.get('source_file', '')}

    # ── Systems ───────────────────────────────────────────────────────
    old_systems = set(snap.get('systems', []))
    new_systems = set(current_snap.get('systems', []))
    result['systems'] = {
        'added': sorted(new_systems - old_systems),
        'removed': sorted(old_systems - new_systems),
        'unchanged': sorted(old_systems & new_systems),
    }

    # ── Talkgroups ────────────────────────────────────────────────────
    old_tgs = snap.get('talkgroups', {})
    new_tgs = current_snap.get('talkgroups', {})
    tg_diffs = {}
    all_tg_sets = set(old_tgs.keys()) | set(new_tgs.keys())
    for set_name in sorted(all_tg_sets):
        old_items = {(t['id'], t['short_name'])
                     for t in old_tgs.get(set_name, [])}
        new_items = {(t['id'], t['short_name'])
                     for t in new_tgs.get(set_name, [])}
        added = sorted(new_items - old_items)
        removed = sorted(old_items - new_items)
        if added or removed:
            tg_diffs[set_name] = {'added': added, 'removed': removed}
    result['talkgroups'] = tg_diffs

    # ── Channels ──────────────────────────────────────────────────────
    old_chs = snap.get('channels', {})
    new_chs = current_snap.get('channels', {})
    ch_diffs = {}
    all_ch_sets = set(old_chs.keys()) | set(new_chs.keys())
    for set_name in sorted(all_ch_sets):
        old_items = {(c['short_name'], c['tx_freq'])
                     for c in old_chs.get(set_name, [])}
        new_items = {(c['short_name'], c['tx_freq'])
                     for c in new_chs.get(set_name, [])}
        added = sorted(new_items - old_items)
        removed = sorted(old_items - new_items)
        if added or removed:
            ch_diffs[set_name] = {'added': added, 'removed': removed}
    result['channels'] = ch_diffs

    # ── Options ───────────────────────────────────────────────────────
    old_opts = snap.get('options', {})
    new_opts = current_snap.get('options', {})
    opt_added = {}
    opt_removed = {}
    opt_changed = {}
    for key in sorted(set(old_opts.keys()) | set(new_opts.keys())):
        old_val = old_opts.get(key)
        new_val = new_opts.get(key)
        if old_val is None and new_val is not None:
            opt_added[key] = new_val
        elif old_val is not None and new_val is None:
            opt_removed[key] = old_val
        elif old_val != new_val:
            opt_changed[key] = (old_val, new_val)
    result['options'] = {
        'added': opt_added,
        'removed': opt_removed,
        'changed': opt_changed,
    }

    return result


def format_snapshot_comparison(diff):
    """Format snapshot comparison results as readable text.

    Args:
        diff: dict from compare_to_snapshot()

    Returns:
        str: formatted comparison text
    """
    lines = []
    if diff.get('source_file'):
        lines.append(f"Comparing against snapshot of: {diff['source_file']}")
        lines.append("")

    # Systems
    sys_diff = diff['systems']
    if sys_diff['added'] or sys_diff['removed']:
        lines.append("  Systems:")
        for name in sys_diff['added']:
            lines.append(f"    + {name}")
        for name in sys_diff['removed']:
            lines.append(f"    - {name}")
        lines.append("")

    # Talkgroups
    if diff['talkgroups']:
        lines.append("  Talkgroups:")
        for set_name, d in diff['talkgroups'].items():
            lines.append(f"    {set_name}:")
            for tg_id, short in d.get('added', []):
                lines.append(f"      + {tg_id} {short}")
            for tg_id, short in d.get('removed', []):
                lines.append(f"      - {tg_id} {short}")
        lines.append("")

    # Channels
    if diff['channels']:
        lines.append("  Channels:")
        for set_name, d in diff['channels'].items():
            lines.append(f"    {set_name}:")
            for short, freq in d.get('added', []):
                lines.append(f"      + {short} {freq:.4f} MHz")
            for short, freq in d.get('removed', []):
                lines.append(f"      - {short} {freq:.4f} MHz")
        lines.append("")

    # Options
    opts = diff['options']
    if opts['added'] or opts['removed'] or opts['changed']:
        lines.append("  Options:")
        for key, val in opts['added'].items():
            lines.append(f"    + {key}: {val}")
        for key, val in opts['removed'].items():
            lines.append(f"    - {key}: {val}")
        for key, (old, new) in opts['changed'].items():
            lines.append(f"    ~ {key}: {old} -> {new}")
        lines.append("")

    if not lines:
        lines.append("  No changes detected.")

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────


def _get_system_long_names(prs):
    """Get all system long names from a PRS."""
    names = set()
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            if long_name:
                names.add(long_name)
    return names


def _get_talkgroup_sets(prs):
    """Get talkgroup IDs by group set name.

    Returns: {set_name: [talkgroup_ids]}
    """
    data_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not data_sec or not set_sec:
        return {}

    sets = parse_sets_from_sections(
        set_sec.raw, data_sec.raw, parse_group_section)

    result = {}
    for gs in sets:
        result[gs.name] = [g.group_id for g in gs.groups]
    return result


def _get_conv_channel_sets(prs):
    """Get conventional channels by set name.

    Returns: {set_name: [(short_name, tx_freq)]}
    """
    result = {}

    # Standard conv channels
    data_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if data_sec and set_sec:
        sets = parse_sets_from_sections(
            set_sec.raw, data_sec.raw, parse_conv_channel_section)
        for cs in sets:
            result[cs.name] = [
                (ch.short_name, round(ch.tx_freq, 4)) for ch in cs.channels
            ]

    # P25 conv channels
    data_sec = prs.get_section_by_class("CP25ConvChannel")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    if data_sec and set_sec:
        sets = parse_sets_from_sections(
            set_sec.raw, data_sec.raw, parse_p25_conv_channel_section)
        for cs in sets:
            result[cs.name] = [
                (ch.short_name, round(ch.tx_freq, 4)) for ch in cs.channels
            ]

    return result


def _get_flat_options(prs):
    """Get flattened option values as {dotted_key: value}.

    E.g. 'gpsConfig.gpsMode' -> 'ON'
    """
    config = extract_platform_config(prs)
    if not config:
        return {}

    flat = {}
    _flatten_dict(config, '', flat)
    return flat


def _flatten_dict(d, prefix, result):
    """Recursively flatten a nested dict to dotted keys."""
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten_dict(value, full_key, result)
        elif isinstance(value, list):
            # Skip lists (progButtons, etc.) for option comparison
            pass
        else:
            result[full_key] = str(value)


def _get_home_unit_id(prs):
    """Extract the first Home Unit ID from P25 trunked configs.

    Returns the unit_id (int) or None if no P25 trunked systems.
    """
    import struct
    from .binary_io import read_lps
    from .fleet import _is_p25_trunk_config

    for sec in prs.sections:
        if sec.class_name:
            continue
        if not is_system_config_data(sec.raw):
            continue
        if not _is_p25_trunk_config(sec.raw):
            continue

        try:
            pos = 44  # SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
            _, pos = read_lps(sec.raw, pos)  # long_name
            pos += 15  # sys_flags
            _, pos = read_lps(sec.raw, pos)  # trunk_set
            _, pos = read_lps(sec.raw, pos)  # group_set
            pos += 12  # 12 zeros
            uid = struct.unpack_from('<I', sec.raw, pos)[0]
            return uid
        except (IndexError, ValueError, struct.error):
            continue

    return None


def _build_snapshot(prs, source_file):
    """Build a snapshot dict from a parsed PRS.

    Returns a JSON-serializable dict capturing the logical config.
    """
    snap = {'source_file': source_file}

    # Systems
    snap['systems'] = sorted(_get_system_long_names(prs))

    # Talkgroups
    tg_sets = _get_talkgroup_sets(prs)
    talkgroups = {}
    for set_name, tg_ids in tg_sets.items():
        # Get full talkgroup info
        data_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if data_sec and set_sec:
            sets = parse_sets_from_sections(
                set_sec.raw, data_sec.raw, parse_group_section)
            for gs in sets:
                if gs.name == set_name:
                    talkgroups[set_name] = [
                        {'id': g.group_id, 'short_name': g.group_name}
                        for g in gs.groups
                    ]
                    break
    snap['talkgroups'] = talkgroups

    # Channels
    ch_sets = _get_conv_channel_sets(prs)
    channels = {}
    for set_name, ch_list in ch_sets.items():
        channels[set_name] = [
            {'short_name': short, 'tx_freq': freq}
            for short, freq in ch_list
        ]
    snap['channels'] = channels

    # Options
    snap['options'] = _get_flat_options(prs)

    # Unit ID
    snap['unit_id'] = _get_home_unit_id(prs)

    # Personality name
    pers_sec = prs.get_section_by_class("CPersonality")
    if pers_sec:
        p = parse_personality_section(pers_sec.raw)
        snap['personality_name'] = p.filename
    else:
        snap['personality_name'] = ''

    return snap
