"""CSV Import — read RPM CSV export format and convert to injection data.

Supports:
  - GROUP_SET.csv → P25GroupSet objects
  - TRK_SET.csv → TrunkSet objects
  - CONV_SET.csv → ConvSet objects
  - Generic CSV with flexible column matching

RPM CSV format uses header rows with known column names. This module
auto-detects the format from the header row.
"""

import csv
from pathlib import Path

from .record_types import (
    P25Group, P25GroupSet, TrunkChannel, TrunkSet,
    ConvChannel, ConvSet,
)


def import_csv(filepath):
    """Auto-detect CSV format and import to structured data.

    Returns:
        tuple of (data_type, objects) where:
          data_type: "groups" | "trunk" | "conv" | "unknown"
          objects: list of P25GroupSet | TrunkSet | ConvSet
    """
    filepath = Path(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return "unknown", []
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
        raise ValueError(f"Cannot read CSV file: {e}") from e

    header_lower = [h.strip().lower() for h in header]

    if _is_group_csv(header_lower):
        return "groups", import_group_csv(filepath)
    elif _is_conv_csv(header_lower):
        return "conv", import_conv_csv(filepath)
    elif _is_trunk_csv(header_lower):
        return "trunk", import_trunk_csv(filepath)
    else:
        return "unknown", []


def _is_group_csv(header):
    """Check if header matches GROUP_SET format."""
    return ('groupid' in header or 'group_id' in header or
            'talkgroup' in header or 'tgid' in header or 'dec' in header)


def _is_trunk_csv(header):
    """Check if header matches TRK_SET format."""
    return (('txfreq' in header or 'tx_freq' in header or
             'frequency' in header or 'freq' in header) and
            'groupid' not in header and 'talkgroup' not in header)


def _is_conv_csv(header):
    """Check if header matches CONV_SET format."""
    return ('shortname' in header or 'short_name' in header or
            'channel' in header or 'name' in header)


def import_group_csv(filepath):
    """Import GROUP_SET.csv → list of P25GroupSet.

    Expected columns (flexible matching):
      Set, GroupID, ShortName, LongName, TX, RX, Scan

    If 'Set' column exists, groups are organized into multiple sets.
    Otherwise, all groups go into a single set named from the filename.
    """
    filepath = Path(filepath)
    rows = _read_csv(filepath)
    if not rows:
        return []

    header = rows[0]
    col_map = _map_columns(header, {
        'set': ['set', 'setname', 'set_name', 'group_set'],
        'group_id': ['groupid', 'group_id', 'tgid', 'dec', 'id',
                      'talkgroup', 'tg_id'],
        'short_name': ['shortname', 'short_name', 'name', 'short'],
        'long_name': ['longname', 'long_name', 'long', 'description',
                       'alpha_tag', 'alpha tag', 'tag'],
        'tx': ['tx', 'transmit'],
        'rx': ['rx', 'receive'],
        'scan': ['scan'],
    })

    # Group by set name
    sets_dict = {}
    default_set = filepath.stem[:8].upper()

    for row in rows[1:]:
        if len(row) <= max(col_map.values(), default=-1):
            continue

        set_name = _get_field(row, col_map, 'set', default_set)[:8]

        try:
            gid = int(_get_field(row, col_map, 'group_id', '0'))
        except ValueError:
            continue

        short = _get_field(row, col_map, 'short_name', '')[:8]
        if not short:
            short = f"TG{gid}"[:8]
        long_name = _get_field(row, col_map, 'long_name', short)[:16]

        tx = _parse_bool(_get_field(row, col_map, 'tx', 'N'))
        rx = _parse_bool(_get_field(row, col_map, 'rx', 'Y'))
        scan = _parse_bool(_get_field(row, col_map, 'scan', 'Y'))

        if set_name not in sets_dict:
            sets_dict[set_name] = []

        sets_dict[set_name].append(P25Group(
            group_name=short, group_id=gid, long_name=long_name,
            tx=tx, rx=rx, scan=scan,
            calls=True, alert=True,
            scan_list_member=True, backlight=True,
        ))

    return [P25GroupSet(name=name, groups=groups)
            for name, groups in sets_dict.items()]


def import_trunk_csv(filepath):
    """Import TRK_SET.csv → list of TrunkSet.

    Expected columns (flexible matching):
      Set, TxFreq, RxFreq, TxMin, TxMax
    """
    filepath = Path(filepath)
    rows = _read_csv(filepath)
    if not rows:
        return []

    header = rows[0]
    col_map = _map_columns(header, {
        'set': ['set', 'setname', 'set_name'],
        'tx_freq': ['txfreq', 'tx_freq', 'tx', 'frequency', 'freq'],
        'rx_freq': ['rxfreq', 'rx_freq', 'rx'],
        'tx_min': ['txmin', 'tx_min'],
        'tx_max': ['txmax', 'tx_max'],
    })

    sets_dict = {}
    default_set = filepath.stem[:8].upper()

    for row in rows[1:]:
        if len(row) <= max(col_map.values(), default=-1):
            continue

        set_name = _get_field(row, col_map, 'set', default_set)[:8]

        try:
            tx = float(_get_field(row, col_map, 'tx_freq', '0'))
        except ValueError:
            continue

        try:
            rx = float(_get_field(row, col_map, 'rx_freq', str(tx)))
        except ValueError:
            rx = tx

        if set_name not in sets_dict:
            tx_min = _safe_float(_get_field(row, col_map, 'tx_min', '136.0'))
            tx_max = _safe_float(_get_field(row, col_map, 'tx_max', '870.0'))
            sets_dict[set_name] = {
                'channels': [],
                'tx_min': tx_min, 'tx_max': tx_max,
                'rx_min': tx_min, 'rx_max': tx_max,
            }

        sets_dict[set_name]['channels'].append(
            TrunkChannel(tx_freq=tx, rx_freq=rx))

    return [TrunkSet(
        name=name, channels=d['channels'],
        tx_min=d['tx_min'], tx_max=d['tx_max'],
        rx_min=d['rx_min'], rx_max=d['rx_max'],
    ) for name, d in sets_dict.items()]


def import_conv_csv(filepath):
    """Import CONV_SET.csv → list of ConvSet.

    Expected columns (flexible matching):
      Set, ShortName, TxFreq, RxFreq, TxTone, RxTone, LongName
    """
    filepath = Path(filepath)
    rows = _read_csv(filepath)
    if not rows:
        return []

    header = rows[0]
    col_map = _map_columns(header, {
        'set': ['set', 'setname', 'set_name', 'zone'],
        'short_name': ['shortname', 'short_name', 'name', 'channel', 'short'],
        'tx_freq': ['txfreq', 'tx_freq', 'tx', 'frequency', 'freq'],
        'rx_freq': ['rxfreq', 'rx_freq', 'rx'],
        'tx_tone': ['txtone', 'tx_tone', 'tone'],
        'rx_tone': ['rxtone', 'rx_tone'],
        'long_name': ['longname', 'long_name', 'long', 'description'],
    })

    sets_dict = {}
    default_set = filepath.stem[:8].upper()

    for row in rows[1:]:
        if len(row) <= max(col_map.values(), default=-1):
            continue

        set_name = _get_field(row, col_map, 'set', default_set)[:8]
        short = _get_field(row, col_map, 'short_name', '')[:8]
        if not short:
            continue

        try:
            tx = float(_get_field(row, col_map, 'tx_freq', '0'))
        except ValueError:
            continue

        try:
            rx = float(_get_field(row, col_map, 'rx_freq', str(tx)))
        except ValueError:
            rx = tx

        tx_tone = _get_field(row, col_map, 'tx_tone', '')
        rx_tone = _get_field(row, col_map, 'rx_tone', '')
        long_name = _get_field(row, col_map, 'long_name', short)[:16]

        if set_name not in sets_dict:
            sets_dict[set_name] = []

        sets_dict[set_name].append(ConvChannel(
            short_name=short, tx_freq=tx, rx_freq=rx,
            tx_tone=tx_tone, rx_tone=rx_tone, long_name=long_name,
        ))

    return [ConvSet(name=name, channels=channels)
            for name, channels in sets_dict.items()]


# ─── Helpers ────────────────────────────────────────────────────────

def _read_csv(filepath):
    """Read CSV file, return list of rows (each a list of strings)."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        return list(csv.reader(f))


def _map_columns(header, mappings):
    """Map logical field names to column indices.

    Args:
        header: list of header strings
        mappings: dict of {field_name: [possible_header_names]}

    Returns:
        dict of {field_name: column_index} (-1 if not found)
    """
    header_lower = [h.strip().lower().replace(' ', '_') for h in header]
    result = {}
    for field, alternatives in mappings.items():
        result[field] = -1
        for alt in alternatives:
            alt_clean = alt.strip().lower().replace(' ', '_')
            if alt_clean in header_lower:
                result[field] = header_lower.index(alt_clean)
                break
    return result


def _get_field(row, col_map, field, default=''):
    """Get a field value from a row using the column map."""
    idx = col_map.get(field, -1)
    if idx < 0 or idx >= len(row):
        return default
    val = row[idx].strip()
    return val if val else default


def _parse_bool(val):
    """Parse Y/N/True/False/1/0 to boolean."""
    return val.upper() in ('Y', 'YES', 'TRUE', '1', 'ON')


def _safe_float(val):
    """Parse float, returning 0.0 on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
