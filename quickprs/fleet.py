"""Fleet batch processing — generate multiple PRS files from a single config.

Build one PRS file per row in a units CSV, each with a unique Home Unit ID
and optional per-radio personality name and password.

Usage:
    from quickprs.fleet import build_fleet
    results = build_fleet("config.ini", "units.csv", "output_dir/")

CSV format (header row required):
    unit_id,name,password
    1001,UNIT-1001,1234
    1002,UNIT-1002,1234
"""

import csv
import logging
import struct
from pathlib import Path

logger = logging.getLogger("quickprs")


def build_fleet(config_path, units_csv_path, output_dir):
    """Build PRS files for a fleet of radios.

    Creates one PRS per row in the units CSV. Each file gets:
    - The same systems/channels/options from the config file
    - A unique Home Unit ID (for P25 systems)
    - Optional unique personality name and password

    Args:
        config_path: INI config file (same format as config_builder)
        units_csv_path: CSV with columns: unit_id, name (optional),
            password (optional)
        output_dir: directory for output files (named: {name}.PRS
            or unit_{id}.PRS)

    Returns:
        list of (filepath, unit_id, success, error_msg) tuples

    Raises:
        FileNotFoundError: if config or CSV file doesn't exist
        ValueError: if CSV has no unit_id column or no data rows
    """
    config_path = Path(config_path)
    units_csv_path = Path(units_csv_path)
    output_dir = Path(output_dir)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not units_csv_path.exists():
        raise FileNotFoundError(f"Units CSV not found: {units_csv_path}")

    # Parse units CSV
    units = _parse_units_csv(units_csv_path)
    if not units:
        raise ValueError("Units CSV has no data rows")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for unit in units:
        unit_id = unit['unit_id']
        name = unit.get('name', '').strip()
        password = unit.get('password', '').strip()

        # Determine output filename
        if name:
            filename = f"{name}.PRS"
        else:
            filename = f"unit_{unit_id}.PRS"

        out_path = output_dir / filename

        try:
            prs = _build_unit_prs(config_path, unit_id, name, password)

            raw = prs.to_bytes()
            out_path.write_bytes(raw)

            results.append((str(out_path), unit_id, True, None))
            logger.info("Built %s (unit_id=%d)", out_path.name, unit_id)

        except Exception as e:
            results.append((str(out_path), unit_id, False, str(e)))
            logger.error("Failed unit_id=%d: %s", unit_id, e)

    return results


def _parse_units_csv(csv_path):
    """Parse the units CSV file.

    Required column: unit_id
    Optional columns: name, password

    Returns:
        list of dicts with keys: unit_id (int), name (str), password (str)
    """
    units = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError("Units CSV is empty (no header row)")

        # Normalize field names (strip whitespace, lowercase for matching)
        normalized = {fn.strip().lower(): fn for fn in reader.fieldnames}
        if 'unit_id' not in normalized:
            raise ValueError(
                f"Units CSV missing required 'unit_id' column. "
                f"Found columns: {list(reader.fieldnames)}")

        uid_col = normalized['unit_id']
        name_col = normalized.get('name')
        pw_col = normalized.get('password')

        for row_num, row in enumerate(reader, start=2):
            uid_str = row.get(uid_col, '').strip()
            if not uid_str:
                continue  # skip blank rows

            try:
                uid = int(uid_str)
            except ValueError:
                raise ValueError(
                    f"Units CSV row {row_num}: invalid unit_id '{uid_str}'")

            entry = {'unit_id': uid}
            if name_col is not None:
                entry['name'] = row.get(name_col, '').strip()
            else:
                entry['name'] = ''
            if pw_col is not None:
                entry['password'] = row.get(pw_col, '').strip()
            else:
                entry['password'] = ''

            units.append(entry)

    return units


def _build_unit_prs(config_path, unit_id, name, password):
    """Build a single PRS for one unit in the fleet.

    Args:
        config_path: Path to INI config file
        unit_id: Home Unit ID for P25 systems
        name: personality name (or empty to keep config default)
        password: radio password (or empty to skip)

    Returns:
        PRSFile object
    """
    from .config_builder import build_from_config
    from .injector import edit_personality

    prs = build_from_config(str(config_path))

    # Set Home Unit ID on all P25 trunked system configs
    set_home_unit_id(prs, unit_id)

    # Set personality name if specified
    if name:
        filename = f"{name}.PRS"
        edit_personality(prs, filename=filename)

    # Set radio password if specified
    if password:
        from .option_maps import set_platform_option
        try:
            set_platform_option(prs, 'misc', 'password', password)
        except ValueError:
            # Blank PRS may not have platformConfig — not a fatal error
            logger.debug("Could not set password (no platformConfig)")

    return prs


def set_home_unit_id(prs, unit_id, system_name=None):
    """Set the Home Unit ID for P25 trunked systems in a PRS.

    The HomeUnitID appears at 3 positions in each P25 trunked system
    config data section (verified from P25TrkSystemConfig.build_data_section):

    1. After SYSTEM_CONFIG_PREFIX(42) + LPS(long_name) + sys_flags(15)
       + LPS(trunk_set) + LPS(group_set) + 12 zeros
    2. After WAN_CONFIG(44) + LPS(wan_name_2)
    3. 5 zeros after position 2

    If system_name is None, sets it for ALL P25 trunked systems.

    Args:
        prs: PRSFile object
        unit_id: uint32 Home Unit ID value
        system_name: optional system long name to filter (None = all)

    Returns:
        int: number of systems modified
    """
    from .record_types import (
        is_system_config_data, parse_system_long_name,
    )
    from .binary_io import read_lps

    modified = 0

    for i, sec in enumerate(prs.sections):
        # Only modify P25 trunked system config data sections
        if sec.class_name:
            continue  # skip named header sections
        if not is_system_config_data(sec.raw):
            continue

        # Check if this is a P25 trunked config (has sys_flags + trunk_set)
        # Conv systems have a different layout after long_name
        if not _is_p25_trunk_config(sec.raw):
            continue

        # Filter by system name if specified
        if system_name is not None:
            long_name = parse_system_long_name(sec.raw)
            if long_name != system_name:
                continue

        # Patch the HomeUnitID at all 3 positions
        new_raw = _patch_home_unit_id(sec.raw, unit_id)
        if new_raw is not None:
            from .prs_parser import Section
            prs.sections[i] = Section(
                offset=sec.offset, raw=new_raw, class_name=sec.class_name)
            modified += 1

    return modified


def _is_p25_trunk_config(raw):
    """Check if a system config data section is P25 trunked (not conv).

    P25 trunked configs have sys_flags(15) after LPS(long_name),
    then LPS(trunk_set) + LPS(group_set).
    Conv configs have 12 zeros then LPS(conv_set) instead.

    We detect by checking the layout: after the long_name, P25 trunk has
    15 bytes of flags that typically contain 0xb6/0xb7 pattern bytes.
    """
    from .binary_io import read_lps

    try:
        pos = 44  # after SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
        _, pos = read_lps(raw, pos)  # skip long_name

        # P25 trunk: sys_flags has identifiable pattern
        # The sys_flags are 15 bytes; check for the trunk_set LPS after them
        flags_end = pos + 15
        if flags_end >= len(raw):
            return False

        # After flags, there should be an LPS(trunk_set) — check if the
        # byte at flags_end is a reasonable LPS length (0-8 for set names)
        trunk_name_len = raw[flags_end]
        if trunk_name_len > 16:
            return False

        # After trunk_set LPS, there should be LPS(group_set)
        next_pos = flags_end + 1 + trunk_name_len
        if next_pos >= len(raw):
            return False
        group_name_len = raw[next_pos]
        if group_name_len > 16:
            return False

        # After group_set LPS + 12 zeros, there should be HomeUnitID(4)
        # followed by SYSTEM_BLOCK4 starting with 0x03 0x04
        uid_pos = next_pos + 1 + group_name_len + 12
        block4_pos = uid_pos + 4
        if block4_pos + 2 > len(raw):
            return False

        return raw[block4_pos] == 0x03 and raw[block4_pos + 1] == 0x04

    except (IndexError, ValueError):
        return False


def _patch_home_unit_id(raw, unit_id):
    """Patch all 3 HomeUnitID positions in a P25 trunked system config section.

    Navigates the variable-length field layout to find the 3 positions
    where HomeUnitID is stored.

    Returns:
        patched bytes, or None if navigation fails
    """
    from .binary_io import read_lps

    uid_bytes = struct.pack('<I', unit_id)

    try:
        data = bytearray(raw)

        # Position 1: after LPS(long_name) + sys_flags(15) + LPS(trunk_set)
        #             + LPS(group_set) + 12 zeros
        pos = 44  # SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
        _, pos = read_lps(raw, pos)   # long_name
        pos += 15                      # sys_flags
        _, pos = read_lps(raw, pos)   # trunk_set
        _, pos = read_lps(raw, pos)   # group_set
        pos += 12                      # 12 zeros

        uid1_pos = pos
        data[uid1_pos:uid1_pos + 4] = uid_bytes

        # Navigate past: HomeUnitID(4) + SYSTEM_BLOCK4(12) + 6 zeros
        #                + uint16(15) + system_id(4) + LPS(wan_name_1)
        #                + WAN_CONFIG(44) + LPS(wan_name_2)
        pos += 4    # HomeUnitID
        pos += 12   # SYSTEM_BLOCK4
        pos += 6    # 6 zeros
        pos += 2    # uint16(15)
        pos += 4    # system_id
        _, pos = read_lps(raw, pos)   # wan_name_1
        pos += 44                      # WAN_CONFIG
        _, pos = read_lps(raw, pos)   # wan_name_2

        # Position 2: right after wan_name_2
        uid2_pos = pos
        data[uid2_pos:uid2_pos + 4] = uid_bytes

        # Position 3: 5 zeros after position 2
        uid3_pos = uid2_pos + 4 + 5
        data[uid3_pos:uid3_pos + 4] = uid_bytes

        return bytes(data)

    except (IndexError, ValueError) as e:
        logger.warning("Failed to patch HomeUnitID: %s", e)
        return None
