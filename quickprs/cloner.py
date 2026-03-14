"""Personality cloner — create modified copies of PRS personalities.

Useful for creating radio variants (e.g., patrol vs detective radios
that share most config but differ in talkgroups or TX permissions).
"""

import logging
from copy import deepcopy

from .prs_parser import parse_prs
from .prs_writer import write_prs
from .record_types import (
    parse_class_header, parse_group_section,
    parse_trunk_channel_section, parse_conv_channel_section,
    parse_iden_section, is_system_config_data,
    parse_system_long_name, parse_system_short_name,
)
from .binary_io import read_uint16_le
from .injector import (
    add_talkgroups, remove_group_set, remove_conv_set,
    remove_trunk_set, make_p25_group, make_conv_channel,
    _find_section_index, _get_first_count, _get_header_bytes,
    _parse_section_data, _replace_group_sections,
    _replace_conv_sections,
    bulk_edit_talkgroups,
)
from .option_maps import set_platform_option

logger = logging.getLogger("quickprs")


def clone_personality(source_prs, modifications=None):
    """Create a modified copy of a personality.

    Deep-copies the entire PRSFile and then applies modifications.

    Args:
        source_prs: PRSFile to clone
        modifications: dict with optional keys:
            'name': new personality name (stored in options)
            'remove_sets': list of set names to remove (trunk/group/conv)
            'remove_systems': list of system long names to remove
            'add_talkgroups': {set_name: [(id, short_name, long_name), ...]}
            'remove_talkgroups': {set_name: [group_id, ...]}
            'enable_tx_sets': [set_names where TX should be enabled]
            'disable_tx_sets': [set_names where TX should be disabled]
            'unit_id': int for HomeUnitID
            'password': str for radio password

    Returns:
        new PRSFile with modifications applied
    """
    clone = deepcopy(source_prs)

    if not modifications:
        return clone

    mods = modifications

    # 1. Remove systems by long name
    if 'remove_systems' in mods:
        for sys_name in mods['remove_systems']:
            _remove_system_by_long_name(clone, sys_name)

    # 2. Remove sets (trunk, group, or conv — tries all types)
    if 'remove_sets' in mods:
        for set_name in mods['remove_sets']:
            removed = remove_trunk_set(clone, set_name)
            if not removed:
                removed = remove_group_set(clone, set_name)
            if not removed:
                remove_conv_set(clone, set_name)

    # 3. Remove specific talkgroups from group sets
    if 'remove_talkgroups' in mods:
        for set_name, group_ids in mods['remove_talkgroups'].items():
            _remove_talkgroups_by_id(clone, set_name, group_ids)

    # 4. Add talkgroups to existing group sets
    if 'add_talkgroups' in mods:
        for set_name, tg_list in mods['add_talkgroups'].items():
            groups = [make_p25_group(gid, sn, ln)
                      for gid, sn, ln in tg_list]
            try:
                add_talkgroups(clone, set_name, groups)
            except (ValueError, KeyError) as e:
                logger.warning("Could not add talkgroups to '%s': %s",
                               set_name, e)

    # 5. Enable TX on sets
    if 'enable_tx_sets' in mods:
        for set_name in mods['enable_tx_sets']:
            _set_tx_on_set(clone, set_name, enable=True)

    # 6. Disable TX on sets
    if 'disable_tx_sets' in mods:
        for set_name in mods['disable_tx_sets']:
            _set_tx_on_set(clone, set_name, enable=False)

    # 7. Set personality name
    if 'name' in mods:
        _set_personality_name(clone, mods['name'])

    # 8. Set unit ID via option_maps
    if 'unit_id' in mods:
        try:
            set_platform_option(clone, 'misc', 'homeUnitID',
                                str(mods['unit_id']))
        except (ValueError, KeyError) as e:
            logger.warning("Could not set unit_id: %s", e)

    # 9. Set password via option_maps
    if 'password' in mods:
        try:
            set_platform_option(clone, 'misc', 'password',
                                mods['password'])
        except (ValueError, KeyError) as e:
            logger.warning("Could not set password: %s", e)

    return clone


def _remove_system_by_long_name(prs, long_name):
    """Remove a system config section by its long name."""
    from .injector import remove_system_config
    try:
        remove_system_config(prs, long_name)
    except (ValueError, KeyError) as e:
        logger.warning("Could not remove system '%s': %s", long_name, e)


def _remove_talkgroups_by_id(prs, set_name, group_ids):
    """Remove specific talkgroups from a group set by group ID."""
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")

    existing_sets = _parse_section_data(grp_sec, parse_group_section,
                                         first_count)

    target_set = None
    for gs in existing_sets:
        if gs.name == set_name:
            target_set = gs
            break

    if not target_set:
        logger.warning("Group set '%s' not found", set_name)
        return

    id_set = set(group_ids)
    original_count = len(target_set.groups)
    target_set.groups = [g for g in target_set.groups
                         if g.group_id not in id_set]

    if len(target_set.groups) == original_count:
        return  # nothing removed

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)


def _set_tx_on_set(prs, set_name, enable=True):
    """Enable or disable TX on all talkgroups/channels in a set.

    Tries group sets first, then conv sets.
    """
    # Try group sets
    try:
        bulk_edit_talkgroups(prs, set_name, enable_tx=enable)
        return
    except (ValueError, KeyError):
        pass

    # Try conv sets
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        return

    byte1, byte2 = _get_header_bytes(ch_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CConvSet")

    existing_sets = _parse_section_data(ch_sec, parse_conv_channel_section,
                                         first_count)

    for cs in existing_sets:
        if cs.name == set_name:
            for ch in cs.channels:
                ch.tx = enable
            _replace_conv_sections(prs, existing_sets, byte1, byte2,
                                    set_byte1, set_byte2)
            return


def _set_personality_name(prs, name):
    """Set the personality file name stored in the PRS header."""
    # The personality name is stored in the first section's raw bytes.
    # Try setting it via option maps first.
    try:
        set_platform_option(prs, 'misc', 'personalityName', name)
    except (ValueError, KeyError, TypeError):
        # Not all files have this option — log and continue
        logger.debug("Could not set personality name via option_maps")
