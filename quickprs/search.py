"""Cross-file search for frequencies, talkgroups, and names.

Search across multiple PRS files for specific data, useful when
managing a fleet of radios or comparing personality files.
"""

from pathlib import Path

from .prs_parser import parse_prs
from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_sets_from_sections,
    parse_system_short_name, parse_system_long_name,
    is_system_config_data,
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


# ─── Public API ───────────────────────────────────────────────────────

def search_freq(filepaths, target_freq, tolerance=0.001):
    """Search for a frequency across multiple PRS files.

    Args:
        filepaths: iterable of PRS file paths (str or Path)
        target_freq: frequency in MHz to search for
        tolerance: match tolerance in MHz (default 0.001 = 1 kHz)

    Returns:
        list of dicts with keys:
            file: filename
            filepath: full path
            set_type: 'trunk' or 'conv'
            set_name: data set name
            freq: matched frequency (MHz)
            channel_name: short name (conv only, '' for trunk)
    """
    results = []

    for fp in filepaths:
        fp = Path(fp)
        try:
            prs = parse_prs(fp)
        except (FileNotFoundError, ValueError, Exception):
            continue

        filename = fp.name

        # Search trunk sets (TX frequencies)
        for ts in _parse_trunk_sets(prs):
            for ch in ts.channels:
                if abs(ch.tx_freq - target_freq) <= tolerance:
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'set_type': 'trunk',
                        'set_name': ts.name,
                        'freq': ch.tx_freq,
                        'channel_name': '',
                    })
                if abs(ch.rx_freq - target_freq) <= tolerance:
                    if abs(ch.rx_freq - ch.tx_freq) > tolerance:
                        results.append({
                            'file': filename,
                            'filepath': str(fp),
                            'set_type': 'trunk',
                            'set_name': ts.name,
                            'freq': ch.rx_freq,
                            'channel_name': '',
                        })

        # Search conv sets (TX and RX frequencies)
        for cs in _parse_conv_sets(prs):
            for ch in cs.channels:
                matched = False
                if abs(ch.tx_freq - target_freq) <= tolerance:
                    matched = True
                if abs(ch.rx_freq - target_freq) <= tolerance:
                    matched = True
                if matched:
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'set_type': 'conv',
                        'set_name': cs.name,
                        'freq': ch.tx_freq,
                        'channel_name': ch.short_name,
                    })

    return results


def search_talkgroup(filepaths, target_tg):
    """Search for a talkgroup ID across multiple PRS files.

    Args:
        filepaths: iterable of PRS file paths
        target_tg: talkgroup ID (integer) to search for

    Returns:
        list of dicts with keys:
            file: filename
            filepath: full path
            set_name: group set name
            group_id: matched talkgroup ID
            short_name: talkgroup short name
            long_name: talkgroup long name
    """
    results = []

    for fp in filepaths:
        fp = Path(fp)
        try:
            prs = parse_prs(fp)
        except (FileNotFoundError, ValueError, Exception):
            continue

        filename = fp.name

        for gs in _parse_group_sets(prs):
            for g in gs.groups:
                if g.group_id == target_tg:
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'set_name': gs.name,
                        'group_id': g.group_id,
                        'short_name': g.group_name,
                        'long_name': g.long_name,
                    })

    return results


def search_name(filepaths, query):
    """Search for a name/string across multiple PRS files.

    Searches system names, set names, channel names, and talkgroup
    names. Case-insensitive substring match.

    Args:
        filepaths: iterable of PRS file paths
        query: search string (case-insensitive)

    Returns:
        list of dicts with keys:
            file: filename
            filepath: full path
            match_type: 'system', 'trunk_set', 'group_set', 'conv_set',
                        'talkgroup', 'channel'
            set_name: parent set name (if applicable)
            name: the matched name
            detail: additional context string
    """
    results = []
    query_lower = query.lower()

    for fp in filepaths:
        fp = Path(fp)
        try:
            prs = parse_prs(fp)
        except (FileNotFoundError, ValueError, Exception):
            continue

        filename = fp.name

        # Search system names
        for cls, label in [('CP25TrkSystem', 'P25 Trunked'),
                           ('CConvSystem', 'Conventional'),
                           ('CP25ConvSystem', 'P25 Conv')]:
            for sec in prs.get_sections_by_class(cls):
                sn = parse_system_short_name(sec.raw)
                if sn and query_lower in sn.lower():
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'match_type': 'system',
                        'set_name': '',
                        'name': sn,
                        'detail': label,
                    })

        # Search system config long names
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                ln = parse_system_long_name(sec.raw)
                if ln and query_lower in ln.lower():
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'match_type': 'system',
                        'set_name': '',
                        'name': ln,
                        'detail': 'System Config',
                    })

        # Search trunk set names
        for ts in _parse_trunk_sets(prs):
            if query_lower in ts.name.lower():
                results.append({
                    'file': filename,
                    'filepath': str(fp),
                    'match_type': 'trunk_set',
                    'set_name': ts.name,
                    'name': ts.name,
                    'detail': f'{len(ts.channels)} freqs',
                })

        # Search group sets and talkgroups
        for gs in _parse_group_sets(prs):
            if query_lower in gs.name.lower():
                results.append({
                    'file': filename,
                    'filepath': str(fp),
                    'match_type': 'group_set',
                    'set_name': gs.name,
                    'name': gs.name,
                    'detail': f'{len(gs.groups)} TGs',
                })
            for g in gs.groups:
                if (query_lower in g.group_name.lower() or
                        query_lower in g.long_name.lower()):
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'match_type': 'talkgroup',
                        'set_name': gs.name,
                        'name': g.group_name,
                        'detail': f'TG {g.group_id} / {g.long_name}',
                    })

        # Search conv sets and channels
        for cs in _parse_conv_sets(prs):
            if query_lower in cs.name.lower():
                results.append({
                    'file': filename,
                    'filepath': str(fp),
                    'match_type': 'conv_set',
                    'set_name': cs.name,
                    'name': cs.name,
                    'detail': f'{len(cs.channels)} channels',
                })
            for ch in cs.channels:
                if (query_lower in ch.short_name.lower() or
                        query_lower in ch.long_name.lower()):
                    results.append({
                        'file': filename,
                        'filepath': str(fp),
                        'match_type': 'channel',
                        'set_name': cs.name,
                        'name': ch.short_name,
                        'detail': (f'{ch.tx_freq:.4f} MHz / '
                                   f'{ch.long_name}'),
                    })

    return results


def format_search_results(results, search_type='freq'):
    """Format search results into human-readable lines.

    Args:
        results: list of result dicts from search_freq/search_talkgroup/search_name
        search_type: 'freq', 'tg', or 'name'

    Returns:
        list of strings
    """
    if not results:
        return ["No matches found."]

    lines = []

    if search_type == 'freq':
        lines.append(f"Found {len(results)} match(es):")
        for r in results:
            ch = f" ({r['channel_name']})" if r['channel_name'] else ""
            lines.append(
                f"  {r['file']}: [{r['set_name']}] "
                f"{r['freq']:.4f} MHz{ch} ({r['set_type']})")

    elif search_type == 'tg':
        lines.append(f"Found {len(results)} match(es):")
        for r in results:
            lines.append(
                f"  {r['file']}: [{r['set_name']}] "
                f"TG {r['group_id']} - {r['short_name']} "
                f"({r['long_name']})")

    elif search_type == 'name':
        lines.append(f"Found {len(results)} match(es):")
        for r in results:
            set_str = f"[{r['set_name']}] " if r['set_name'] else ""
            lines.append(
                f"  {r['file']}: {set_str}{r['name']} "
                f"({r['match_type']}: {r['detail']})")

    return lines
