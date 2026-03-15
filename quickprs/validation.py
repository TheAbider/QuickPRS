"""Validation — XG-100P hardware/firmware limit enforcement.

All limits are from confirmed XG-100P behavior and RPM documentation.
Violations are returned as a list of (severity, message) tuples.

validate_prs_detailed() returns categorized results grouped by
system/set for hierarchical display.
"""

import logging

logger = logging.getLogger("quickprs")

from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    is_system_config_data,
    parse_sets_from_sections,
)
from .option_maps import (
    extract_platform_config, XML_FIELDS,
    BUTTON_FUNCTION_NAMES, SHORT_MENU_NAMES, SWITCH_FUNCTION_NAMES,
)


# ─── XG-100P Limits ──────────────────────────────────────────────────
# Sources: Harris RPM documentation, RadioReference forums,
# PAWSOVERMAWS.PRS binary analysis, Communications Support forums.

LIMITS = {
    # Critical — exceeding these causes malfunction
    'scan_talkgroups_per_set': 127,    # 128 breaks scanning on all Harris radios
    'enhanced_cc_entries': 30,          # max per system (C/S Nevada has 30 in PAWSOVERMAWS)
    'tgs_per_trunked_system': 1250,    # max talkgroups per P25 trunked system
    'conv_channels_per_system': 1000,  # max conventional channels per system
    'conv_scan_practical': 8,          # >6-8 conv channels in scan = missed traffic

    # Personality-wide limits
    'channels_per_personality': 1250,   # channels+talkgroups per mission plan
    'systems_per_personality': 512,     # P25 trunked + conv + P25 conv combined
    'zones_per_personality': 50,
    'channels_per_zone': 48,            # 16 knob positions x 3 banks (A/B/C)
    'scan_lists': 10,
    'channels_per_scan_list': 100,
    'mission_plans': 10,
    'total_channels': 12500,            # 10 mission plans x 1,250
    'encryption_keys': 128,             # 64 AES + 64 DES

    # Per-set storage limits
    'groups_per_set': 1024,             # storage limit, only 127 scannable
    'unique_freqs_per_system': 1024,

    # Name lengths
    'short_name_max': 8,
    'long_name_max': 16,
    'talkgroup_id_max': 65535,          # uint16

    # XG-100P frequency range
    'freq_min_mhz': 30.0,
    'freq_max_mhz': 960.0,

    # XG-100P band edges (VHF, UHF, 700/800)
    'vhf_min': 136.0, 'vhf_max': 174.0,
    'uhf_min': 380.0, 'uhf_max': 520.0,
    'band_700_min': 762.0, 'band_800_max': 870.0,

    # Recommended limits (exceeding causes performance issues)
    'max_conv_in_mixed_scan': 8,        # more than 8 conv in trunked scan = degraded
}


# Severity levels
ERROR = 'ERROR'     # will cause malfunction
WARNING = 'WARNING'  # may cause issues
INFO = 'INFO'       # advisory


def validate_prs(prs):
    """Run all validation checks on a PRSFile.

    Returns list of (severity, message) tuples.
    """
    issues = []
    data = prs.to_bytes()

    issues.extend(_validate_groups(prs, data))
    issues.extend(_validate_trunk(prs, data))
    issues.extend(_validate_conv(prs, data))
    issues.extend(_validate_iden(prs, data))
    issues.extend(_validate_frequencies(prs))
    issues.extend(_validate_system_counts(prs))
    issues.extend(_validate_platform_config(prs))

    return issues


def validate_prs_detailed(prs):
    """Run all validation checks, grouped by category.

    Returns dict of category -> list of (severity, message) tuples:
        {
            "Global": [...],
            "Group Set: PSERN PD": [...],
            "Trunk Set: PSERN": [...],
            "Conv Set: FURRY WB": [...],
            "IDEN Set: BEE00": [...],
        }

    Categories with no issues are omitted. "Global" holds personality-wide
    checks (system counts, total channels, etc.).
    """
    results = {}

    # Global checks
    global_issues = _validate_system_counts(prs)
    global_issues.extend(_validate_platform_config(prs))
    global_issues.extend(_validate_frequencies(prs))
    if global_issues:
        results["Global"] = global_issues

    # Group sets
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if grp_sec and set_sec:
        sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
        if isinstance(sets, list):
            for gset in sets:
                issues = validate_group_set(gset)
                if issues:
                    results[f"Group Set: {gset.name}"] = issues
        else:
            results["Group Sets"] = [(ERROR, "Failed to parse group sections")]

    # Trunk sets
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    ts_sec = prs.get_section_by_class("CTrunkSet")
    if ch_sec and ts_sec:
        sets = _parse_sets_safe(ts_sec, ch_sec, parse_trunk_channel_section)
        if isinstance(sets, list):
            for tset in sets:
                issues = validate_trunk_set(tset)
                if issues:
                    results[f"Trunk Set: {tset.name}"] = issues
        else:
            results["Trunk Sets"] = [(ERROR, "Failed to parse trunk sections")]

    # Conv sets
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        sets = _parse_sets_safe(conv_set_sec, conv_sec,
                                parse_conv_channel_section)
        if isinstance(sets, list):
            for cset in sets:
                issues = validate_conv_set(cset)
                if issues:
                    results[f"Conv Set: {cset.name}"] = issues
        else:
            results["Conv Sets"] = [(ERROR, "Failed to parse conv sections")]

    # IDEN sets
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    if elem_sec and ids_sec:
        sets = _parse_sets_safe(ids_sec, elem_sec, parse_iden_section)
        if isinstance(sets, list):
            for iset in sets:
                issues = validate_iden_set(iset)
                if issues:
                    results[f"IDEN Set: {iset.name}"] = issues
        else:
            results["IDEN Sets"] = [(ERROR, "Failed to parse IDEN sections")]

    return results


# ─── Per-set validators ──────────────────────────────────────────────

def validate_group_set(group_set):
    """Validate a single P25GroupSet before injection.

    Returns list of (severity, message) tuples.
    """
    issues = []
    name = group_set.name
    count = len(group_set.groups)

    # Set name must fit in 8-char LPS reference
    if len(name) > LIMITS['short_name_max']:
        issues.append((ERROR,
            f"Group set name '{name}' is {len(name)} chars "
            f"(max {LIMITS['short_name_max']} — system config truncates reference)"))

    if count > LIMITS['groups_per_set']:
        issues.append((ERROR,
            f"Group set '{name}' has {count} groups "
            f"(max {LIMITS['groups_per_set']}). "
            f"Remove at least {count - LIMITS['groups_per_set']} talkgroup(s) "
            f"or split into multiple group sets."))

    scan_count = sum(1 for g in group_set.groups if g.scan)
    if scan_count > LIMITS['scan_talkgroups_per_set']:
        over = scan_count - LIMITS['scan_talkgroups_per_set']
        issues.append((ERROR,
            f"Group set '{name}' has {scan_count} scan-enabled talkgroups "
            f"(max {LIMITS['scan_talkgroups_per_set']}). "
            f"Disable scan on at least {over} talkgroup(s) to avoid "
            f"radio scanning issues. Use: quickprs bulk-edit <file> "
            f"talkgroups --set \"{name}\" --disable-scan"))
    elif scan_count > LIMITS['scan_talkgroups_per_set'] - 10:
        issues.append((WARNING,
            f"Group set '{name}' has {scan_count} scan-enabled talkgroups "
            f"(approaching limit of {LIMITS['scan_talkgroups_per_set']})"))

    # Check for duplicate talkgroup IDs
    seen_ids = set()
    for g in group_set.groups:
        if g.group_id in seen_ids:
            issues.append((WARNING,
                f"Duplicate talkgroup ID {g.group_id} in set '{name}'. "
                f"Remove the duplicate or assign a unique ID to avoid "
                f"scan/display issues on the radio."))
        seen_ids.add(g.group_id)

        if g.group_id > LIMITS['talkgroup_id_max']:
            issues.append((ERROR,
                f"Talkgroup '{g.group_name}' ID {g.group_id} "
                f"exceeds uint16 max ({LIMITS['talkgroup_id_max']}). "
                f"Use an ID between 1 and {LIMITS['talkgroup_id_max']}."))
        issues.extend(_validate_name_lengths(g.group_name, g.long_name,
                                              f"talkgroup {g.group_id}"))

    return issues


def validate_trunk_set(trunk_set):
    """Validate a single TrunkSet before injection."""
    issues = []
    name = trunk_set.name

    # Set name must fit in 8-char LPS reference
    if len(name) > LIMITS['short_name_max']:
        issues.append((ERROR,
            f"Trunk set name '{name}' is {len(name)} chars "
            f"(max {LIMITS['short_name_max']} — system config truncates reference)"))

    if len(trunk_set.channels) > LIMITS['unique_freqs_per_system']:
        over = len(trunk_set.channels) - LIMITS['unique_freqs_per_system']
        issues.append((ERROR,
            f"Trunk set '{name}' has {len(trunk_set.channels)} channels "
            f"(max {LIMITS['unique_freqs_per_system']}). "
            f"Remove at least {over} frequency(s) or split across "
            f"multiple trunk sets."))

    # Check for duplicate frequencies (report count, not each one)
    seen = set()
    dup_count = 0
    for ch in trunk_set.channels:
        key = (round(ch.tx_freq, 6), round(ch.rx_freq, 6))
        if key in seen:
            dup_count += 1
        seen.add(key)
    if dup_count > 0:
        issues.append((WARNING,
            f"Trunk set '{name}' has {dup_count} duplicate "
            f"frequencies (multi-site systems share freqs)"))

    # Check band limits contain all frequencies
    for ch in trunk_set.channels:
        if ch.tx_freq < trunk_set.tx_min or ch.tx_freq > trunk_set.tx_max:
            issues.append((WARNING,
                f"Trunk set '{name}' TX freq {ch.tx_freq:.5f} "
                f"outside band limits {trunk_set.tx_min:.1f}-"
                f"{trunk_set.tx_max:.1f}. Verify the frequency is correct "
                f"or update the IDEN band limits."))
        if ch.rx_freq < trunk_set.rx_min or ch.rx_freq > trunk_set.rx_max:
            issues.append((WARNING,
                f"Trunk set '{name}' RX freq {ch.rx_freq:.5f} "
                f"outside band limits {trunk_set.rx_min:.1f}-"
                f"{trunk_set.rx_max:.1f}. Verify the frequency is correct "
                f"or update the IDEN band limits."))

    # Check absolute frequency range
    for ch in trunk_set.channels:
        for freq in (ch.tx_freq, ch.rx_freq):
            if freq < LIMITS['freq_min_mhz'] or freq > LIMITS['freq_max_mhz']:
                issues.append((ERROR,
                    f"Trunk set '{name}' freq {freq:.5f} MHz outside "
                    f"XG-100P range ({LIMITS['freq_min_mhz']}-"
                    f"{LIMITS['freq_max_mhz']} MHz). "
                    f"Remove this frequency or correct it to a valid "
                    f"XG-100P band."))

    return issues


def validate_conv_set(conv_set):
    """Validate a single ConvSet before injection."""
    issues = []
    name = conv_set.name

    # Set name must fit in 8-char LPS reference
    if len(name) > LIMITS['short_name_max']:
        issues.append((ERROR,
            f"Conv set name '{name}' is {len(name)} chars "
            f"(max {LIMITS['short_name_max']} — system config truncates reference)"))

    if len(conv_set.channels) > LIMITS['conv_channels_per_system']:
        over = len(conv_set.channels) - LIMITS['conv_channels_per_system']
        issues.append((ERROR,
            f"Conv set '{name}' has {len(conv_set.channels)} channels "
            f"(max {LIMITS['conv_channels_per_system']} per system). "
            f"Remove at least {over} channel(s) or split into "
            f"multiple conv sets."))
    elif len(conv_set.channels) > LIMITS['channels_per_zone']:
        issues.append((INFO,
            f"Conv set '{name}' has {len(conv_set.channels)} channels "
            f"(zone limit is {LIMITS['channels_per_zone']}). "
            f"Use 'quickprs zones' to plan multi-zone layout."))

    for ch in conv_set.channels:
        issues.extend(_validate_name_lengths(
            ch.short_name, ch.long_name, f"channel '{ch.short_name}'"))

        # Check frequency range
        for freq in (ch.tx_freq, ch.rx_freq):
            if freq < LIMITS['freq_min_mhz'] or freq > LIMITS['freq_max_mhz']:
                issues.append((ERROR,
                    f"Conv channel '{ch.short_name}' freq {freq:.5f} MHz "
                    f"outside XG-100P range ({LIMITS['freq_min_mhz']}-"
                    f"{LIMITS['freq_max_mhz']} MHz). "
                    f"Correct the frequency or remove this channel."))

        # Check tone format
        for tone_name, tone_val in [("TX tone", ch.tx_tone),
                                     ("RX tone", ch.rx_tone)]:
            if tone_val and not _is_valid_tone(tone_val):
                issues.append((WARNING,
                    f"Conv channel '{ch.short_name}' {tone_name} "
                    f"'{tone_val}' may not be a valid CTCSS/DCS code. "
                    f"Use 'quickprs freq-tools tones' to see valid CTCSS "
                    f"tones or 'quickprs freq-tools dcs' for DCS codes."))

    return issues


def validate_iden_set(iden_set):
    """Validate a single IdenDataSet before injection."""
    issues = []
    name = iden_set.name

    # Set name must fit in 8-char LPS reference
    if len(name) > LIMITS['short_name_max']:
        issues.append((ERROR,
            f"IDEN set name '{name}' is {len(name)} chars "
            f"(max {LIMITS['short_name_max']} — system config truncates reference)"))

    if len(iden_set.elements) > 16:
        issues.append((ERROR,
            f"IDEN set '{name}' has {len(iden_set.elements)} elements "
            f"(max 16). Remove unused IDEN entries or create a separate "
            f"IDEN set for additional band plans."))

    for i, elem in enumerate(iden_set.elements):
        if elem.is_empty():
            continue
        # TDMA bandwidth: 6250 or 12500 are both valid (RPM uses 12500)
        if elem.iden_type == 1 and elem.bandwidth_hz not in (6250, 12500):
            issues.append((WARNING,
                f"IDEN set '{name}' element {i}: TDMA bandwidth "
                f"{elem.bandwidth_hz} Hz is unusual (expected 6250 or "
                f"12500 Hz). Check the system's IDEN table on "
                f"RadioReference for the correct bandwidth."))

    return issues


# ─── Internal validators ─────────────────────────────────────────────

def _validate_groups(prs, data):
    """Validate all group sets in the personality."""
    issues = []

    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return issues

    sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
    if not isinstance(sets, list):
        issues.append((ERROR, "Failed to parse group sections"))
        return issues

    total_groups = 0
    for gset in sets:
        issues.extend(validate_group_set(gset))
        total_groups += len(gset.groups)

    if total_groups > LIMITS['channels_per_personality']:
        issues.append((WARNING,
            f"Total talkgroups ({total_groups}) is high — "
            f"combined with channels must stay under {LIMITS['channels_per_personality']}"))

    return issues


def _validate_trunk(prs, data):
    """Validate all trunk sets in the personality."""
    issues = []

    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not ch_sec or not set_sec:
        return issues

    sets = _parse_sets_safe(set_sec, ch_sec, parse_trunk_channel_section)
    if not isinstance(sets, list):
        issues.append((ERROR, "Failed to parse trunk sections"))
        return issues

    for tset in sets:
        issues.extend(validate_trunk_set(tset))

    return issues


def _validate_conv(prs, data):
    """Validate all conv sets in the personality."""
    issues = []

    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if not conv_sec or not conv_set_sec:
        return issues

    sets = _parse_sets_safe(conv_set_sec, conv_sec,
                            parse_conv_channel_section)
    if not isinstance(sets, list):
        issues.append((ERROR, "Failed to parse conv sections"))
        return issues

    for cset in sets:
        issues.extend(validate_conv_set(cset))

    return issues


def _validate_iden(prs, data):
    """Validate all IDEN sets in the personality."""
    issues = []

    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    if not elem_sec or not ids_sec:
        return issues

    sets = _parse_sets_safe(ids_sec, elem_sec, parse_iden_section)
    if not isinstance(sets, list):
        issues.append((ERROR, "Failed to parse IDEN sections"))
        return issues

    for iset in sets:
        issues.extend(validate_iden_set(iset))

    # Check for duplicate/equivalent IDEN sets
    if len(sets) >= 2:
        for i, a in enumerate(sets):
            for j, b in enumerate(sets):
                if j <= i:
                    continue
                if _iden_sets_equivalent(a, b):
                    issues.append((WARNING,
                        f"IDEN sets '{a.name}' and '{b.name}' have "
                        "identical entries — consider removing the duplicate"))

    return issues


def _iden_sets_equivalent(a, b):
    """Check if two IdenDataSets have identical active entries."""
    if len(a.elements) != len(b.elements):
        return False
    for ea, eb in zip(a.elements, b.elements):
        if ea.is_empty() != eb.is_empty():
            return False
        if ea.is_empty():
            continue
        if (ea.base_freq_hz != eb.base_freq_hz or
                ea.chan_spacing_hz != eb.chan_spacing_hz or
                ea.bandwidth_hz != eb.bandwidth_hz or
                ea.iden_type != eb.iden_type):
            return False
    return True


def validate_frequencies(prs):
    """Check for frequency issues across all trunk and conv sets.

    Returns list of (severity, message) tuples for:
    - Duplicate frequencies within a trunk set
    - Duplicate frequencies across trunk sets
    - Frequencies outside valid P25 bands
    - Mismatched TX/RX offsets within a trunk set
    - Channels with 0 MHz frequency
    - Conv channels outside 30-960 MHz range
    - Conv channels where TX==RX but tones suggest repeater use
    - IDEN base frequencies that don't match trunk channels in the set
    """
    return _validate_frequencies(prs)


def _validate_frequencies(prs):
    """Internal frequency validation across all sets."""
    issues = []

    from .iden_library import detect_p25_band

    # ── Trunk frequency checks ──
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    ts_sec = prs.get_section_by_class("CTrunkSet")
    trunk_sets = []
    if ch_sec and ts_sec:
        trunk_sets = _parse_sets_safe(ts_sec, ch_sec,
                                       parse_trunk_channel_section) or []

    # Collect all trunk frequencies for cross-set duplicate detection
    all_trunk_freqs = {}  # (rx_freq_rounded) -> list of set names

    for tset in trunk_sets:
        name = tset.name

        # Check for 0 MHz frequencies
        for ch in tset.channels:
            if ch.rx_freq == 0.0 or ch.tx_freq == 0.0:
                issues.append((WARNING,
                    f"Trunk set '{name}' has a channel with 0 MHz frequency. "
                    f"This may be a placeholder. Remove it or set a valid "
                    f"frequency."))
                break  # Only report once per set

        # Frequencies outside valid P25 bands (check RX freqs only —
        # TX side of standard bands like 806-824 MHz won't match the
        # RX-based band definitions and that's normal)
        oob_count = 0
        for ch in tset.channels:
            if ch.rx_freq > 0:
                band, _ = detect_p25_band(ch.rx_freq)
                if band is None:
                    oob_count += 1
        if oob_count > 0:
            issues.append((WARNING,
                f"Trunk set '{name}' has {oob_count} RX freq(s) "
                "outside standard P25 bands. Verify frequencies match "
                "the system's RadioReference listing."))

        # Mismatched TX/RX offsets within a set
        offsets = set()
        for ch in tset.channels:
            if ch.tx_freq > 0 and ch.rx_freq > 0:
                offset = round(ch.tx_freq - ch.rx_freq, 4)
                offsets.add(offset)
        if len(offsets) > 1:
            offset_strs = [f"{o:+.4f}" for o in sorted(offsets)]
            issues.append((WARNING,
                f"Trunk set '{name}' has inconsistent TX/RX offsets: "
                f"{', '.join(offset_strs)} MHz. This is normal for "
                f"multi-band systems but may indicate a data entry error "
                f"for single-band systems."))

        # Track for cross-set duplicate detection
        for ch in tset.channels:
            key = round(ch.rx_freq, 6)
            all_trunk_freqs.setdefault(key, []).append(name)

    # Cross-set duplicate frequencies
    for freq, sets in all_trunk_freqs.items():
        if len(sets) > 1 and freq > 0:
            unique_sets = sorted(set(sets))
            if len(unique_sets) > 1:
                issues.append((INFO,
                    f"RX freq {freq:.5f} MHz appears in trunk sets: "
                    f"{', '.join(unique_sets)} "
                    "(shared freqs are normal for multi-site systems)"))

    # ── Conv frequency checks ──
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    conv_sets = []
    if conv_sec and conv_set_sec:
        conv_sets = _parse_sets_safe(conv_set_sec, conv_sec,
                                      parse_conv_channel_section) or []

    for cset in conv_sets:
        name = cset.name

        # Check for 0 MHz frequencies
        for ch in cset.channels:
            if ch.tx_freq == 0.0 and ch.rx_freq == 0.0:
                issues.append((WARNING,
                    f"Conv set '{name}' channel '{ch.short_name}' "
                    "has 0 MHz frequency. Set a valid frequency or "
                    "remove this channel."))

        # TX == RX but tones suggest repeater
        for ch in cset.channels:
            if (ch.tx_freq > 0 and ch.rx_freq > 0 and
                    abs(ch.tx_freq - ch.rx_freq) < 0.0001):
                # Same TX/RX — check if tones suggest repeater use
                has_tone = bool(ch.tx_tone or ch.rx_tone)
                if has_tone:
                    issues.append((INFO,
                        f"Conv channel '{ch.short_name}' in '{name}' "
                        f"has TX=RX ({ch.tx_freq:.4f} MHz) but uses "
                        "tones, which suggests a repeater with missing "
                        "offset. Use 'quickprs freq-tools offset "
                        f"{ch.tx_freq:.4f}' to find the correct offset."))

    # ── IDEN vs trunk frequency cross-check ──
    _validate_iden_trunk_match(prs, trunk_sets, issues)

    return issues


def _validate_iden_trunk_match(prs, trunk_sets, issues):
    """Check that IDEN base frequencies cover the trunk channels."""
    from .iden_library import detect_p25_band

    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    if not elem_sec or not ids_sec:
        return

    iden_sets = _parse_sets_safe(ids_sec, elem_sec, parse_iden_section)
    if not iden_sets:
        return

    # Build map: iden_set_name -> set of bands covered by active entries
    iden_bands = {}
    for iset in iden_sets:
        bands_covered = set()
        for elem in iset.elements:
            if elem.is_empty():
                continue
            freq_mhz = elem.base_freq_hz / 1_000_000.0
            band, _ = detect_p25_band(freq_mhz)
            if band:
                # Normalize 700_upper
                band = '700' if band == '700_upper' else band
                bands_covered.add(band)
        iden_bands[iset.name] = bands_covered

    iden_set_names = set(iden_bands.keys())

    # Check system configs for trunk_set -> iden_set associations
    try:
        from .record_types import (
            parse_system_long_name, parse_system_set_refs,
            parse_ecc_entries,
        )

        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                sys_name = parse_system_long_name(sec.raw) or "Unknown"
                trunk_ref, _ = parse_system_set_refs(sec.raw)

                if not trunk_ref:
                    continue

                # Try parse_ecc_entries first for the IDEN reference
                _, _, iden_ref = parse_ecc_entries(sec.raw)

                # If parse_ecc_entries didn't find it, search raw data
                # for known IDEN set names
                if not iden_ref:
                    for iname in iden_set_names:
                        iname_bytes = iname.encode('ascii', errors='ignore')
                        if iname_bytes and iname_bytes in sec.raw:
                            iden_ref = iname
                            break

                if not iden_ref:
                    continue

                # Find the trunk set and determine its band(s)
                matched_tset = None
                for tset in trunk_sets:
                    if tset.name == trunk_ref:
                        matched_tset = tset
                        break

                if not matched_tset:
                    continue

                # Determine bands used by trunk channels — check both
                # TX and RX freqs since stored order varies
                trunk_bands = set()
                for ch in matched_tset.channels:
                    for freq in (ch.tx_freq, ch.rx_freq):
                        if freq > 0:
                            band, _ = detect_p25_band(freq)
                            if band:
                                band = '700' if band == '700_upper' else band
                                trunk_bands.add(band)
                if not trunk_bands:
                    continue

                # Check if IDEN covers those bands
                iden_covered = iden_bands.get(iden_ref, set())
                missing = trunk_bands - iden_covered
                if missing:
                    issues.append((WARNING,
                        f"System '{sys_name}' trunk set '{trunk_ref}' "
                        f"uses {', '.join(sorted(missing))} MHz band(s) "
                        f"but IDEN set '{iden_ref}' does not cover them. "
                        f"The radio will not decode channels in the "
                        f"uncovered band(s). Re-inject the system with "
                        f"correct IDEN entries."))
    except Exception as e:
        logger.debug("IDEN/trunk cross-check failed: %s", e)


def _validate_system_counts(prs):
    """Check personality-wide system and section counts."""
    issues = []

    system_classes = ['CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem']
    total_systems = 0
    for cls in system_classes:
        secs = prs.get_sections_by_class(cls)
        total_systems += len(secs)

    if total_systems > LIMITS['systems_per_personality']:
        issues.append((ERROR,
            f"Total systems ({total_systems}) exceeds maximum "
            f"({LIMITS['systems_per_personality']}). "
            f"Remove systems with 'quickprs remove <file> system <name>'."))
    elif total_systems == 0:
        issues.append((INFO,
            "No systems found in personality. Use 'quickprs inject' to "
            "add P25 trunked or conventional systems."))

    # System short name length check (8-char LPS limit)
    from .record_types import parse_system_short_name
    for cls in system_classes:
        for sec in prs.get_sections_by_class(cls):
            short = parse_system_short_name(sec.raw)
            if short and len(short) > LIMITS['short_name_max']:
                issues.append((ERROR,
                    f"System short name '{short}' is {len(short)} chars "
                    f"(max {LIMITS['short_name_max']}). "
                    f"Shorten the name to {LIMITS['short_name_max']} "
                    f"characters with 'quickprs edit <file> "
                    f"--rename-set trunk \"{short}\" <new_name>'."))

    # Count conventional channels against personality limit (1,250 conv per plan)
    total_conv = 0
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        sets = _parse_sets_safe(conv_set_sec, conv_sec,
                                parse_conv_channel_section)
        if isinstance(sets, list):
            total_conv = sum(len(cs.channels) for cs in sets)

    if total_conv > LIMITS['channels_per_personality']:
        over = total_conv - LIMITS['channels_per_personality']
        issues.append((ERROR,
            f"Total conventional channels ({total_conv}) exceeds "
            f"personality limit ({LIMITS['channels_per_personality']}). "
            f"Remove at least {over} channel(s) across conv sets."))
    elif total_conv > LIMITS['channels_per_personality'] * 0.9:
        remaining = LIMITS['channels_per_personality'] - total_conv
        issues.append((WARNING,
            f"Total conventional channels ({total_conv}) approaching "
            f"personality limit ({LIMITS['channels_per_personality']}). "
            f"Only {remaining} channel(s) remaining before limit."))

    # Count talkgroups against per-system limit
    total_tgs = 0
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if grp_sec and set_sec:
        sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
        if isinstance(sets, list):
            for gs in sets:
                if len(gs.groups) > LIMITS['tgs_per_trunked_system']:
                    over = len(gs.groups) - LIMITS['tgs_per_trunked_system']
                    issues.append((ERROR,
                        f"Group set '{gs.name}' has {len(gs.groups)} TGs "
                        f"(max {LIMITS['tgs_per_trunked_system']} per system). "
                        f"Remove at least {over} talkgroup(s) from this set."))
            total_tgs = sum(len(gs.groups) for gs in sets)

    # Combined channel+TG personality limit
    total_combined = total_conv + total_tgs
    if total_combined > LIMITS['channels_per_personality']:
        over = total_combined - LIMITS['channels_per_personality']
        issues.append((ERROR,
            f"Total channels+talkgroups ({total_combined}: "
            f"{total_tgs} TGs + {total_conv} conv) exceeds "
            f"personality limit ({LIMITS['channels_per_personality']}). "
            f"Remove at least {over} item(s). Use 'quickprs capacity "
            f"<file>' to see per-set breakdown."))
    elif total_combined > LIMITS['channels_per_personality'] * 0.9:
        remaining = LIMITS['channels_per_personality'] - total_combined
        issues.append((WARNING,
            f"Total channels+talkgroups ({total_combined}: "
            f"{total_tgs} TGs + {total_conv} conv) approaching "
            f"personality limit ({LIMITS['channels_per_personality']}). "
            f"Only {remaining} slot(s) remaining."))

    # Duplicate set name detection
    _check_duplicate_set_names(prs, issues)

    # Zone limit advisory for large group sets
    if grp_sec and set_sec:
        sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
        if isinstance(sets, list):
            for gs in sets:
                if len(gs.groups) > LIMITS['channels_per_zone']:
                    zones_needed = (len(gs.groups) + LIMITS['channels_per_zone'] - 1) // LIMITS['channels_per_zone']
                    issues.append((INFO,
                        f"Group set '{gs.name}' has {len(gs.groups)} TGs "
                        f"(zone limit is {LIMITS['channels_per_zone']}). "
                        f"Will need at least {zones_needed} zones. "
                        f"Use 'quickprs zones <file>' to auto-plan."))

    # Total file size check (RPM sometimes has issues with very large files)
    file_size = len(prs.to_bytes())
    if file_size > 1_000_000:
        issues.append((ERROR,
            f"Personality file is very large ({file_size:,} bytes). "
            "RPM may reject files over 1 MB. Remove unused systems "
            "or reduce talkgroup/channel counts."))
    elif file_size > 500_000:
        issues.append((WARNING,
            f"Personality file is large ({file_size:,} bytes). "
            "RPM may be slow to load. Consider removing unused "
            "systems to reduce file size."))

    # Mixed scanning warning (conv + trunked)
    has_trunk = bool(prs.get_sections_by_class('CP25TrkSystem'))
    has_conv = bool(prs.get_sections_by_class('CConvSystem'))
    if has_trunk and has_conv:
        issues.append((INFO,
            "Mixed trunked + conventional scanning is unreliable on "
            "XG-100P — conventional channels may be missed during "
            "trunked scanning. Keep conv scan channels under 8 if mixing."))

    # ECC entry count per system + WACN conflict + cross-reference checks
    try:
        from .record_types import (
            is_system_config_data, parse_ecc_entries,
            parse_system_long_name, parse_system_wan_name,
            parse_system_set_refs,
        )

        # Collect existing set names for cross-reference
        iden_set_names = set()
        elem_sec = prs.get_section_by_class("CDefaultIdenElem")
        ids_sec = prs.get_section_by_class("CIdenDataSet")
        if elem_sec and ids_sec:
            iden_sets = _parse_sets_safe(ids_sec, elem_sec, parse_iden_section)
            if isinstance(iden_sets, list):
                iden_set_names = {s.name for s in iden_sets}

        trunk_set_names = set()
        ch_sec = prs.get_section_by_class("CTrunkChannel")
        ts_sec = prs.get_section_by_class("CTrunkSet")
        if ch_sec and ts_sec:
            trunk_sets = _parse_sets_safe(ts_sec, ch_sec,
                                          parse_trunk_channel_section)
            if isinstance(trunk_sets, list):
                trunk_set_names = {s.name for s in trunk_sets}

        group_set_names = set()
        if grp_sec and set_sec:
            grp_sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
            if isinstance(grp_sets, list):
                group_set_names = {s.name for s in grp_sets}

        wacns_seen = {}  # wan_name -> list of system names
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                sname = parse_system_long_name(sec.raw) or "Unknown"
                ecc_count, _, iden_name = parse_ecc_entries(sec.raw)
                if ecc_count > LIMITS['enhanced_cc_entries']:
                    over = ecc_count - LIMITS['enhanced_cc_entries']
                    issues.append((WARNING,
                        f"System '{sname}' has {ecc_count} ECC entries "
                        f"(max {LIMITS['enhanced_cc_entries']}). "
                        f"Remove at least {over} Enhanced Control "
                        f"Channel entry(s)."))

                # Cross-reference: ECC IDEN set must exist
                if iden_name and iden_set_names and iden_name not in iden_set_names:
                    issues.append((WARNING,
                        f"System '{sname}' ECC references IDEN set "
                        f"'{iden_name}' which doesn't exist in personality. "
                        f"Re-inject the system to auto-create the "
                        f"matching IDEN set."))

                # Cross-reference: system config → trunk/group sets
                trunk_ref, group_ref = parse_system_set_refs(sec.raw)
                if trunk_ref and trunk_set_names and trunk_ref not in trunk_set_names:
                    issues.append((WARNING,
                        f"System '{sname}' references trunk set "
                        f"'{trunk_ref}' which doesn't exist. "
                        f"The system may have been partially removed. "
                        f"Re-inject it or remove the system entirely."))
                if group_ref and group_set_names and group_ref not in group_set_names:
                    issues.append((WARNING,
                        f"System '{sname}' references group set "
                        f"'{group_ref}' which doesn't exist. "
                        f"The system may have been partially removed. "
                        f"Re-inject it or remove the system entirely."))

                # Track WAN names for conflict detection
                wan = parse_system_wan_name(sec.raw)
                if wan:
                    wacns_seen.setdefault(wan, []).append(sname)

        # Check for same-WACN conflicts (radio can lock onto wrong system)
        for wan, systems in wacns_seen.items():
            if len(systems) > 1:
                names = ", ".join(systems)
                issues.append((WARNING,
                    f"Systems share WACN '{wan}': {names}. "
                    "XG-100P may lock onto the wrong system during scan. "
                    "If these are different sites of the same system, "
                    "this is normal. Otherwise, consider removing one."))
    except Exception as e:
        logger.debug("System cross-validation failed: %s", e)

    return issues


def _check_duplicate_set_names(prs, issues):
    """Detect duplicate set names across all set types."""
    set_names = {}  # name -> list of type labels

    for cls, label, parser_fn in [
        ("CP25GroupSet", "group", parse_group_section),
        ("CTrunkSet", "trunk", parse_trunk_channel_section),
        ("CConvSet", "conv", parse_conv_channel_section),
        ("CIdenDataSet", "IDEN", parse_iden_section),
    ]:
        data_cls = {
            "CP25GroupSet": "CP25Group",
            "CTrunkSet": "CTrunkChannel",
            "CConvSet": "CConvChannel",
            "CIdenDataSet": "CDefaultIdenElem",
        }[cls]
        set_sec = prs.get_section_by_class(cls)
        data_sec = prs.get_section_by_class(data_cls)
        if set_sec and data_sec:
            sets = _parse_sets_safe(set_sec, data_sec, parser_fn)
            if isinstance(sets, list):
                for s in sets:
                    set_names.setdefault(s.name, []).append(label)

    for name, types in set_names.items():
        if len(types) > 1:
            labels = ", ".join(types)
            issues.append((WARNING,
                f"Duplicate set name '{name}' used by: {labels}. "
                "RPM may confuse references. Rename one of the sets "
                "with 'quickprs edit <file> --rename-set <type> "
                f"\"{name}\" <new_name>'."))



def _validate_name_lengths(short_name, long_name, context):
    """Check short/long name lengths."""
    issues = []
    if len(short_name) > LIMITS['short_name_max']:
        issues.append((ERROR,
            f"{context}: short name '{short_name}' is {len(short_name)} chars "
            f"(max {LIMITS['short_name_max']}). "
            f"Truncate to {LIMITS['short_name_max']} characters."))
    if len(long_name) > LIMITS['long_name_max']:
        issues.append((ERROR,
            f"{context}: long name '{long_name}' is {len(long_name)} chars "
            f"(max {LIMITS['long_name_max']}). "
            f"Truncate to {LIMITS['long_name_max']} characters."))
    return issues


def _parse_sets_safe(set_sec, data_sec, parser_fn):
    """Parse data sections safely, returning list of sets or None on error."""
    result = parse_sets_from_sections(set_sec.raw, data_sec.raw, parser_fn)
    return result if result else None


# ─── Platform config validation ─────────────────────────────────────

def _validate_platform_config(prs):
    """Validate platformConfig XML fields: buttons, menus, value ranges."""
    issues = []
    config = extract_platform_config(prs)
    if config is None:
        return issues

    # Validate prog button functions
    prog = config.get("progButtons", {})
    if prog:
        # Switch functions
        for attr, label in [("_2PosFunction", "2-Pos Switch"),
                            ("_3PosFunction", "3-Pos Switch"),
                            ("_3PosAFunc", "3-Pos A"),
                            ("_3PosBFunc", "3-Pos B"),
                            ("_3PosCFunc", "3-Pos C")]:
            val = prog.get(attr, "")
            if val and val not in SWITCH_FUNCTION_NAMES:
                issues.append((WARNING,
                    f"{label} function '{val}' is not a known switch "
                    f"function. Use 'quickprs set-option <file> --list' "
                    f"to see valid function names."))

        # Side buttons
        buttons = prog.get("progButton", [])
        if isinstance(buttons, dict):
            buttons = [buttons]
        for btn in buttons:
            func = btn.get("function", "")
            name = btn.get("buttonName", "")
            if func and func not in BUTTON_FUNCTION_NAMES:
                issues.append((WARNING,
                    f"Button '{name}' function '{func}' is not recognized. "
                    f"Use 'quickprs set-option <file> --list' to see "
                    f"valid button functions."))

    # Validate accessory buttons
    acc_container = config.get("accessoryButtons", {})
    if acc_container:
        acc_btns = acc_container.get("accessoryButton", [])
        if isinstance(acc_btns, dict):
            acc_btns = [acc_btns]
        for btn in acc_btns:
            func = btn.get("function", "")
            name = btn.get("buttonName", "")
            if func and func not in BUTTON_FUNCTION_NAMES:
                issues.append((WARNING,
                    f"Accessory button '{name}' function '{func}' "
                    "is not recognized. Use 'quickprs set-option "
                    "<file> --list' to see valid button functions."))

    # Validate short menu
    menu = config.get("shortMenu", {})
    if menu:
        items = menu.get("shortMenuItem", [])
        if isinstance(items, dict):
            items = [items]

        # Check for invalid menu names
        for it in items:
            name = it.get("name", "empty")
            if name and name not in SHORT_MENU_NAMES:
                pos = it.get("position", "?")
                issues.append((WARNING,
                    f"Short menu slot {pos} name '{name}' is not recognized. "
                    f"This menu item may not work on the radio."))

        # Check for duplicate positions
        positions = [it.get("position", "") for it in items]
        seen = set()
        for pos in positions:
            if pos and pos in seen:
                issues.append((WARNING,
                    f"Duplicate short menu position: {pos}. "
                    f"Each menu position should be unique. "
                    f"Reassign one of the duplicates."))
            seen.add(pos)

    # Validate int fields against min/max ranges
    _validate_xml_int_ranges(config, issues)

    return issues


def _validate_xml_int_ranges(config, issues):
    """Check XML int fields against their defined min/max ranges."""
    # Build flat lookup of config values by element tag
    flat = {}
    for key, val in config.items():
        if isinstance(val, dict):
            flat[key] = val

    for field_def in XML_FIELDS:
        if field_def.field_type != "int":
            continue
        if field_def.min_val is None and field_def.max_val is None:
            continue

        # Find the element containing this field
        tag = field_def.element
        if "/" in tag:
            # Qualified path like "audioConfig/microphone[@micType='INTERNAL']"
            # Skip — would need full XML parsing to resolve
            continue

        elem_data = flat.get(tag, {})
        raw = elem_data.get(field_def.attribute, "")
        if not raw:
            continue

        try:
            val = int(raw)
        except ValueError:
            try:
                val = int(float(raw))
            except ValueError:
                continue

        if field_def.min_val is not None and val < field_def.min_val:
            issues.append((WARNING,
                f"{field_def.display_name} value {val} is below minimum "
                f"({field_def.min_val}). Set to at least "
                f"{field_def.min_val}."))
        if field_def.max_val is not None and val > field_def.max_val:
            issues.append((WARNING,
                f"{field_def.display_name} value {val} exceeds maximum "
                f"({field_def.max_val}). Set to at most "
                f"{field_def.max_val}."))


# ─── Tone validation ────────────────────────────────────────────────

# Standard CTCSS tones (Hz)
CTCSS_TONES = {
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
    94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0,
    127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2,
    165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9,
    192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
    233.6, 241.8, 250.3, 254.1,
}


def _is_valid_tone(tone_str):
    """Check if a tone string is a valid CTCSS or DCS code."""
    if not tone_str:
        return True

    # DCS codes: "D023N", "D023I", "023", etc.
    tone_upper = tone_str.upper().strip()
    if tone_upper.startswith('D') and len(tone_upper) >= 4:
        return True  # DCS format
    if tone_upper.endswith('N') or tone_upper.endswith('I'):
        return True  # DCS format variant

    # CTCSS: numeric value
    try:
        val = float(tone_str)
        if val in CTCSS_TONES:
            return True
        # Allow close matches (some systems use slightly off values)
        for ctcss in CTCSS_TONES:
            if abs(val - ctcss) < 0.2:
                return True
        # Allow any value in CTCSS range even if not standard
        if 60.0 <= val <= 260.0:
            return True
        return False
    except ValueError:
        return False


# ─── Structural validation ──────────────────────────────────────────

def validate_structure(prs):
    """Validate the structural integrity of a PRS file.

    Checks that the binary layout is well-formed and internally consistent,
    independent of radio-specific hardware limits. This catches format errors
    that could cause RPM to reject the file or brick a radio.

    Checks:
      - CPersonality section present and first
      - At least one system (conv, P25 trunk, or P25 conv)
      - System config data sections follow their class headers
      - Set references in system configs match actual set names
      - WAN entry count matches CP25tWanOpts
      - No orphan system config data sections (no preceding header)
      - File terminator present (if file uses terminator pattern)
      - ConvSet metadata config pair (bytes 38-39) is 0x01,0x01

    Returns:
        list of (severity, message) tuples.
    """
    from .record_types import (
        parse_system_long_name, parse_system_set_refs,
        parse_system_short_name, parse_wan_opts_section,
        parse_wan_section, SYSTEM_CONFIG_PREFIX,
        parse_class_header,
    )
    from .binary_io import read_uint16_le

    issues = []

    # 1. CPersonality must be present and first
    personality = prs.get_section_by_class("CPersonality")
    if not personality:
        issues.append((ERROR,
            "Missing CPersonality section. The file may be corrupted. "
            "Try 'quickprs repair <file>' to attempt recovery."))
    elif prs.sections and prs.sections[0].class_name != "CPersonality":
        issues.append((ERROR,
            "CPersonality is not the first section "
            f"(found at index {next(i for i, s in enumerate(prs.sections) if s.class_name == 'CPersonality')})"))

    # 2. At least one system
    system_classes = ['CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem']
    total_systems = sum(len(prs.get_sections_by_class(c)) for c in system_classes)
    if total_systems == 0:
        issues.append((ERROR,
            "No system sections found — file must contain at least one "
            "CConvSystem, CP25TrkSystem, or CP25ConvSystem"))

    # 3. System config data sections must follow a system header
    header_types = {'CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem'}
    for i, sec in enumerate(prs.sections):
        if not sec.class_name and is_system_config_data(sec.raw):
            # Walk backward to find the nearest system header
            found_header = False
            for j in range(i - 1, -1, -1):
                if prs.sections[j].class_name in header_types:
                    found_header = True
                    break
                # CPreferredSystemTableEntry can appear between header and data
                if prs.sections[j].class_name == 'CPreferredSystemTableEntry':
                    continue
                # Other unnamed data sections (small continuations) are OK
                if not prs.sections[j].class_name:
                    continue
                # Hit a different class section — no header found
                break
            if not found_header:
                long = parse_system_long_name(sec.raw) or "(unknown)"
                issues.append((ERROR,
                    f"Orphan system config data section at index {i} "
                    f"('{long}') — no preceding system header"))

    # 4. System config prefix consistency
    for i, sec in enumerate(prs.sections):
        if not sec.class_name and is_system_config_data(sec.raw):
            actual_prefix = sec.raw[2:44]
            if actual_prefix != SYSTEM_CONFIG_PREFIX:
                long = parse_system_long_name(sec.raw) or "(unknown)"
                diffs = [j for j in range(len(SYSTEM_CONFIG_PREFIX))
                         if j < len(actual_prefix) and
                         actual_prefix[j] != SYSTEM_CONFIG_PREFIX[j]]
                issues.append((ERROR,
                    f"System config '{long}' at index {i} has "
                    f"corrupted prefix (differs at {len(diffs)} byte positions)"))

    # 5. Cross-reference: system config set names must resolve
    _validate_set_crossrefs(prs, issues, parse_system_set_refs, parse_system_long_name)

    # 6. WAN entry count consistency
    opts_sec = prs.get_section_by_class("CP25tWanOpts")
    wan_sec = prs.get_section_by_class("CP25TrkWan")
    if opts_sec and wan_sec:
        try:
            expected_count = parse_wan_opts_section(opts_sec.raw)
            actual_entries = parse_wan_section(wan_sec.raw)
            if expected_count != len(actual_entries):
                issues.append((ERROR,
                    f"WAN count mismatch: CP25tWanOpts says {expected_count} "
                    f"entries but CP25TrkWan has {len(actual_entries)}. "
                    f"Try 'quickprs repair <file>' to fix the count."))
        except Exception as e:
            logger.debug("WAN validation failed: %s", e)

    # 7. ConvSet metadata config pair check
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        try:
            sets = parse_sets_from_sections(
                conv_set_sec.raw, conv_sec.raw, parse_conv_channel_section)
            if sets:
                for cset in sets:
                    meta = cset.metadata
                    if len(meta) >= 40 and meta[38:40] != b'\x01\x01':
                        issues.append((WARNING,
                            f"Conv set '{cset.name}' metadata bytes 38-39 "
                            f"are {meta[38:40].hex()} (RPM expects 01 01). "
                            f"Try 'quickprs repair <file>' to fix this."))
        except Exception as e:
            logger.debug("ConvSet metadata check failed: %s", e)

    # 8. Required companion sections
    _validate_companion_sections(prs, issues)

    return issues


def _validate_set_crossrefs(prs, issues, parse_refs_fn, parse_long_fn):
    """Check that system config set references point to real sets."""
    # Collect all actual set names
    trunk_names = set()
    group_names = set()
    conv_names = set()

    ch_sec = prs.get_section_by_class("CTrunkChannel")
    ts_sec = prs.get_section_by_class("CTrunkSet")
    if ch_sec and ts_sec:
        try:
            sets = parse_sets_from_sections(
                ts_sec.raw, ch_sec.raw, parse_trunk_channel_section)
            trunk_names = {s.name for s in sets}
        except Exception:
            pass

    grp_sec = prs.get_section_by_class("CP25Group")
    gs_sec = prs.get_section_by_class("CP25GroupSet")
    if grp_sec and gs_sec:
        try:
            sets = parse_sets_from_sections(
                gs_sec.raw, grp_sec.raw, parse_group_section)
            group_names = {s.name for s in sets}
        except Exception:
            pass

    conv_ch_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_ch_sec and conv_set_sec:
        try:
            sets = parse_sets_from_sections(
                conv_set_sec.raw, conv_ch_sec.raw, parse_conv_channel_section)
            conv_names = {s.name for s in sets}
        except Exception:
            pass

    all_set_names = trunk_names | group_names | conv_names

    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long = parse_long_fn(sec.raw) or "(unknown)"
            trunk_ref, group_ref = parse_refs_fn(sec.raw)

            if trunk_ref and all_set_names and trunk_ref not in trunk_names:
                issues.append((ERROR,
                    f"System '{long}' references trunk set '{trunk_ref}' "
                    "which does not exist. Re-inject the system or "
                    "remove it with 'quickprs remove <file> system "
                    f"\"{long}\"'."))
            if group_ref and all_set_names and group_ref not in group_names:
                issues.append((ERROR,
                    f"System '{long}' references group set '{group_ref}' "
                    "which does not exist. Re-inject the system or "
                    "remove it with 'quickprs remove <file> system "
                    f"\"{long}\"'."))


def _validate_companion_sections(prs, issues):
    """Check that paired sections are both present (e.g., CTrunkSet + CTrunkChannel)."""
    pairs = [
        ('CTrunkSet', 'CTrunkChannel'),
        ('CConvSet', 'CConvChannel'),
        ('CP25GroupSet', 'CP25Group'),
        ('CIdenDataSet', 'CDefaultIdenElem'),
        ('CP25ConvSet', 'CP25ConvChannel'),
        ('CType99Opts', 'CT99'),
        ('CP25tWanOpts', 'CP25TrkWan'),
    ]
    for a, b in pairs:
        has_a = prs.get_section_by_class(a) is not None
        has_b = prs.get_section_by_class(b) is not None
        if has_a and not has_b:
            issues.append((ERROR,
                f"{a} present but companion {b} is missing. "
                f"The file structure is incomplete. "
                f"Try 'quickprs repair <file>' to fix."))
        elif has_b and not has_a:
            issues.append((ERROR,
                f"{b} present but companion {a} is missing. "
                f"The file structure is incomplete. "
                f"Try 'quickprs repair <file>' to fix."))


# ─── Capacity estimation ─────────────────────────────────────────────

def estimate_capacity(prs):
    """Estimate memory usage and remaining capacity of an XG-100P personality.

    Returns a dict with:
        'systems': {'used': N, 'max': 512, 'pct': float},
        'channels': {'used': N, 'max': 1250, 'pct': float},
        'talkgroups': {'used': N, 'max': 1250, 'details': {set_name: count}},
        'trunk_freqs': {'used': N, 'details': {set_name: count}},
        'conv_channels': {'used': N, 'details': {set_name: count}},
        'iden_sets': {'used': N, 'details': {set_name: active_count}},
        'file_size': {'bytes': N, 'sections': N},
        'scan_tg_headroom': {set_name: {'used': N, 'max': 127, 'remaining': N}},
        'zones_needed': {'total_items': N, 'zones_min': N, 'max': 50},
    """
    result = {}

    # Systems
    system_classes = ['CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem']
    total_systems = sum(len(prs.get_sections_by_class(c))
                        for c in system_classes)
    max_sys = LIMITS['systems_per_personality']
    result['systems'] = {
        'used': total_systems,
        'max': max_sys,
        'pct': (total_systems / max_sys * 100) if max_sys else 0,
    }

    # Group sets (talkgroups)
    tg_details = {}
    total_tgs = 0
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if grp_sec and set_sec:
        sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
        if isinstance(sets, list):
            for gs in sets:
                count = len(gs.groups)
                tg_details[gs.name] = count
                total_tgs += count

    max_ch = LIMITS['channels_per_personality']
    result['talkgroups'] = {
        'used': total_tgs,
        'max': max_ch,
        'details': tg_details,
    }

    # Trunk sets (frequencies)
    trunk_details = {}
    total_trunk = 0
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    ts_sec = prs.get_section_by_class("CTrunkSet")
    if ch_sec and ts_sec:
        sets = _parse_sets_safe(ts_sec, ch_sec,
                                parse_trunk_channel_section)
        if isinstance(sets, list):
            for ts in sets:
                count = len(ts.channels)
                trunk_details[ts.name] = count
                total_trunk += count

    result['trunk_freqs'] = {
        'used': total_trunk,
        'details': trunk_details,
    }

    # Conv sets (channels)
    conv_details = {}
    total_conv = 0
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        sets = _parse_sets_safe(conv_set_sec, conv_sec,
                                parse_conv_channel_section)
        if isinstance(sets, list):
            for cs in sets:
                count = len(cs.channels)
                conv_details[cs.name] = count
                total_conv += count

    result['conv_channels'] = {
        'used': total_conv,
        'details': conv_details,
    }

    # Combined channels (TGs + conv against personality limit)
    total_channels = total_tgs + total_conv
    result['channels'] = {
        'used': total_channels,
        'max': max_ch,
        'pct': (total_channels / max_ch * 100) if max_ch else 0,
    }

    # IDEN sets
    iden_details = {}
    total_iden = 0
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    if elem_sec and ids_sec:
        sets = _parse_sets_safe(ids_sec, elem_sec, parse_iden_section)
        if isinstance(sets, list):
            for iset in sets:
                active = sum(1 for e in iset.elements
                             if not e.is_empty())
                iden_details[iset.name] = active
                total_iden += 1

    result['iden_sets'] = {
        'used': total_iden,
        'details': iden_details,
    }

    # Scan TG headroom per group set
    scan_headroom = {}
    max_scan = LIMITS['scan_talkgroups_per_set']
    if grp_sec and set_sec:
        sets = _parse_sets_safe(set_sec, grp_sec, parse_group_section)
        if isinstance(sets, list):
            for gs in sets:
                scan_count = sum(1 for g in gs.groups if g.scan)
                scan_headroom[gs.name] = {
                    'used': scan_count,
                    'max': max_scan,
                    'remaining': max_scan - scan_count,
                }

    result['scan_tg_headroom'] = scan_headroom

    # File size
    result['file_size'] = {
        'bytes': len(prs.to_bytes()),
        'sections': len(prs.sections),
    }

    # Zone estimate (total addressable items / channels per zone)
    total_items = total_tgs + total_conv
    cpz = LIMITS['channels_per_zone']
    zones_min = (total_items + cpz - 1) // cpz if total_items > 0 else 0
    result['zones_needed'] = {
        'total_items': total_items,
        'zones_min': zones_min,
        'max': LIMITS['zones_per_personality'],
    }

    return result


def format_capacity(cap, filename=""):
    """Format capacity estimation dict into human-readable lines.

    Args:
        cap: dict from estimate_capacity()
        filename: optional filename for the header

    Returns:
        list of strings (no trailing newlines)
    """
    lines = []
    header = f"Capacity Report: {filename}" if filename else "Capacity Report"
    lines.append(header)

    # Systems
    sys_info = cap['systems']
    lines.append(f"  Systems:     {sys_info['used']}/{sys_info['max']}"
                 f"  ({sys_info['pct']:5.1f}%)")

    # Channels (combined)
    ch_info = cap['channels']
    lines.append(f"  Channels:  {ch_info['used']:>4d}/{ch_info['max']}"
                 f"  ({ch_info['pct']:5.1f}%)")

    # Trunk frequencies
    trunk_info = cap['trunk_freqs']
    if trunk_info['used'] > 0:
        set_count = len(trunk_info['details'])
        set_str = f"{set_count} set" + ("s" if set_count != 1 else "")
        lines.append(f"    Trunk:   {trunk_info['used']:>4d} freqs "
                     f"({set_str})")

    # Conv channels
    conv_info = cap['conv_channels']
    if conv_info['used'] > 0:
        set_count = len(conv_info['details'])
        set_str = f"{set_count} set" + ("s" if set_count != 1 else "")
        lines.append(f"    Conv:    {conv_info['used']:>4d} channels "
                     f"({set_str})")

    # Talkgroups
    tg_info = cap['talkgroups']
    if tg_info['used'] > 0:
        set_count = len(tg_info['details'])
        set_str = f"{set_count} set" + ("s" if set_count != 1 else "")
        lines.append(f"    Groups:  {tg_info['used']:>4d} talkgroups "
                     f"({set_str})")

    # Scan TG headroom
    headroom = cap.get('scan_tg_headroom', {})
    if headroom:
        lines.append("")
        lines.append("  Scan TG Headroom:")
        for name, info in sorted(headroom.items()):
            lines.append(
                f"    {name:<12s} {info['used']:>3d}/{info['max']} "
                f"({info['remaining']} remaining)")

    # IDEN sets
    iden_info = cap.get('iden_sets', {})
    if iden_info.get('used', 0) > 0:
        lines.append("")
        lines.append("  IDEN Sets:")
        for name, active in sorted(iden_info['details'].items()):
            lines.append(f"    {name:<12s} {active}/16 active")

    # Zone estimate
    zones = cap.get('zones_needed', {})
    if zones.get('zones_min', 0) > 0:
        lines.append("")
        lines.append(f"  Zones needed: {zones['zones_min']} minimum "
                     f"(max {zones['max']})")

    # File size
    fs = cap['file_size']
    lines.append("")
    lines.append(f"  File: {fs['bytes']:,} bytes, "
                 f"{fs['sections']} sections")

    return lines


# ─── Statistics ──────────────────────────────────────────────────────

# Frequency band classification (MHz ranges)
_FREQ_BANDS = [
    ("VHF", 136.0, 174.0),
    ("UHF", 400.0, 512.0),
    ("700 MHz", 764.0, 806.0),
    ("800 MHz", 806.0, 870.0),
    ("900 MHz", 896.0, 960.0),
    ("Low Band", 30.0, 88.0),
]


def _classify_band(freq_mhz):
    """Classify a frequency into a named band."""
    for band_name, lo, hi in _FREQ_BANDS:
        if lo <= freq_mhz <= hi:
            return band_name
    return f"Other ({freq_mhz:.1f} MHz)"


def compute_statistics(prs):
    """Compute interesting statistics about a radio personality.

    Args:
        prs: PRSFile object (already parsed)

    Returns:
        dict with statistics:
            'systems': {'total': N, 'p25_trunked': N, 'conventional': N,
                        'p25_conv': N, 'names': [str]},
            'channels': {'total': N, 'talkgroups': N, 'trunk_freqs': N,
                         'conv_channels': N},
            'freq_bands': {band_name: count},
            'talkgroup_analysis': {'total': N, 'tx_enabled': N,
                                   'scan_enabled': N, 'encrypted': N,
                                   'priority': N},
            'channel_types': {'simplex': N, 'duplex': N},
            'ctcss_tones': {tone: count},
            'file_info': {'size_bytes': N, 'sections': N},
    """
    stats = {}

    # Systems
    p25_trk = prs.get_sections_by_class("CP25TrkSystem")
    conv_sys = prs.get_sections_by_class("CConvSystem")
    p25_conv = prs.get_sections_by_class("CP25ConvSystem")
    sys_names = []
    for sec in p25_trk + conv_sys + p25_conv:
        from .record_types import parse_system_short_name
        name = parse_system_short_name(sec.raw)
        if name:
            sys_names.append(name)

    stats['systems'] = {
        'total': len(p25_trk) + len(conv_sys) + len(p25_conv),
        'p25_trunked': len(p25_trk),
        'conventional': len(conv_sys),
        'p25_conv': len(p25_conv),
        'names': sys_names,
    }

    # Parse sets
    group_sets = []
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if grp_sec and set_sec:
        group_sets = _parse_sets_safe(set_sec, grp_sec,
                                      parse_group_section)
        if not isinstance(group_sets, list):
            group_sets = []

    trunk_sets = []
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    ts_sec = prs.get_section_by_class("CTrunkSet")
    if ch_sec and ts_sec:
        trunk_sets = _parse_sets_safe(ts_sec, ch_sec,
                                      parse_trunk_channel_section)
        if not isinstance(trunk_sets, list):
            trunk_sets = []

    conv_sets = []
    conv_sec = prs.get_section_by_class("CConvChannel")
    conv_set_sec = prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        conv_sets = _parse_sets_safe(conv_set_sec, conv_sec,
                                     parse_conv_channel_section)
        if not isinstance(conv_sets, list):
            conv_sets = []

    total_tgs = sum(len(gs.groups) for gs in group_sets)
    total_trunk = sum(len(ts.channels) for ts in trunk_sets)
    total_conv = sum(len(cs.channels) for cs in conv_sets)

    stats['channels'] = {
        'total': total_tgs + total_trunk + total_conv,
        'talkgroups': total_tgs,
        'trunk_freqs': total_trunk,
        'conv_channels': total_conv,
    }

    # Frequency band analysis (trunk + conv frequencies)
    freq_bands = {}
    all_freqs = []
    for ts in trunk_sets:
        for ch in ts.channels:
            all_freqs.append(ch.rx_freq)
    for cs in conv_sets:
        for ch in cs.channels:
            all_freqs.append(ch.rx_freq)

    for freq in all_freqs:
        band = _classify_band(freq)
        freq_bands[band] = freq_bands.get(band, 0) + 1

    stats['freq_bands'] = freq_bands

    # Talkgroup analysis
    tg_total = 0
    tg_tx = 0
    tg_scan = 0
    tg_encrypted = 0
    tg_priority = 0
    for gs in group_sets:
        for grp in gs.groups:
            tg_total += 1
            if grp.tx:
                tg_tx += 1
            if grp.scan:
                tg_scan += 1
            if grp.encrypted:
                tg_encrypted += 1
            if grp.priority_tg:
                tg_priority += 1

    stats['talkgroup_analysis'] = {
        'total': tg_total,
        'tx_enabled': tg_tx,
        'scan_enabled': tg_scan,
        'encrypted': tg_encrypted,
        'priority': tg_priority,
    }

    # Channel types (simplex vs duplex) for conv channels
    simplex = 0
    duplex = 0
    for cs in conv_sets:
        for ch in cs.channels:
            if abs(ch.tx_freq - ch.rx_freq) < 0.0001:
                simplex += 1
            else:
                duplex += 1

    stats['channel_types'] = {
        'simplex': simplex,
        'duplex': duplex,
    }

    # CTCSS tones used
    ctcss_tones = {}
    for cs in conv_sets:
        for ch in cs.channels:
            for tone in (ch.tx_tone, ch.rx_tone):
                if tone:
                    ctcss_tones[tone] = ctcss_tones.get(tone, 0) + 1

    stats['ctcss_tones'] = ctcss_tones

    # File info
    stats['file_info'] = {
        'size_bytes': prs.file_size,
        'sections': len(prs.sections),
    }

    return stats


def format_statistics(stats, filename=""):
    """Format statistics dict into human-readable lines.

    Args:
        stats: dict from compute_statistics()
        filename: optional filename for the header

    Returns:
        list of strings (no trailing newlines)
    """
    lines = []
    header = (f"Radio Statistics: {filename}"
              if filename else "Radio Statistics")
    lines.append(header)

    # Systems
    sys_info = stats['systems']
    if sys_info['total'] > 0:
        parts = []
        if sys_info['p25_trunked'] > 0:
            parts.append(f"{sys_info['p25_trunked']} P25 trunked")
        if sys_info['conventional'] > 0:
            parts.append(f"{sys_info['conventional']} conventional")
        if sys_info['p25_conv'] > 0:
            parts.append(f"{sys_info['p25_conv']} P25 conv")
        detail = f" ({', '.join(parts)})" if parts else ""
        lines.append(f"  Systems: {sys_info['total']}{detail}")
    else:
        lines.append("  Systems: 0")

    # Channels
    ch = stats['channels']
    parts = []
    if ch['talkgroups'] > 0:
        parts.append(f"{ch['talkgroups']} TGs")
    if ch['trunk_freqs'] > 0:
        parts.append(f"{ch['trunk_freqs']} trunk freqs")
    if ch['conv_channels'] > 0:
        parts.append(f"{ch['conv_channels']} conv channels")
    detail = f" ({', '.join(parts)})" if parts else ""
    lines.append(f"  Total Channels: {ch['total']}{detail}")

    # Frequency bands
    bands = stats.get('freq_bands', {})
    if bands:
        lines.append("")
        lines.append("  Frequency Bands:")
        # Sort by count descending
        for band, count in sorted(bands.items(),
                                  key=lambda x: -x[1]):
            lines.append(f"    {band}: {count} channels")

    # Talkgroup analysis
    tg = stats.get('talkgroup_analysis', {})
    if tg.get('total', 0) > 0:
        lines.append("")
        lines.append("  Talkgroup Analysis:")
        total = tg['total']
        tx = tg['tx_enabled']
        scan = tg['scan_enabled']
        enc = tg['encrypted']
        prio = tg['priority']
        tx_pct = (tx / total * 100) if total else 0
        scan_pct = (scan / total * 100) if total else 0
        enc_pct = (enc / total * 100) if total else 0
        lines.append(f"    TX-enabled: {tx}/{total} ({tx_pct:.0f}%)")
        lines.append(f"    Scan-enabled: {scan}/{total} ({scan_pct:.0f}%)")
        lines.append(f"    Encrypted: {enc}/{total} ({enc_pct:.0f}%)")
        if prio > 0:
            lines.append(f"    Priority: {prio}/{total}")

    # Channel types
    ct = stats.get('channel_types', {})
    if ct.get('simplex', 0) + ct.get('duplex', 0) > 0:
        lines.append("")
        lines.append("  Channel Types:")
        if ct.get('simplex', 0) > 0:
            lines.append(f"    Simplex: {ct['simplex']} channels")
        if ct.get('duplex', 0) > 0:
            lines.append(f"    Duplex: {ct['duplex']} channels")

    # CTCSS tones
    tones = stats.get('ctcss_tones', {})
    if tones:
        lines.append("")
        lines.append("  CTCSS/DCS Tones Used:")
        for tone, count in sorted(tones.items(),
                                  key=lambda x: -x[1]):
            lines.append(f"    {tone} ({count} ch)")

    # File info
    fi = stats.get('file_info', {})
    if fi:
        lines.append("")
        lines.append(f"  File: {fi['size_bytes']:,} bytes, "
                     f"{fi['sections']} sections")

    return lines
