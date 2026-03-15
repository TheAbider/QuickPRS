"""Configuration health check and smart suggestions for radio personalities.

Goes beyond hardware-limit validation to identify common configuration
mistakes, best practices, and suggest improvements based on the current
personality state.

Health check returns (severity, category, message, suggestion) tuples.
Suggestions return (category, suggestion, command) tuples with CLI commands.
"""

import logging
from collections import Counter
from difflib import SequenceMatcher

from .prs_parser import PRSFile
from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_system_short_name, parse_system_long_name,
    is_system_config_data, parse_ecc_entries,
    parse_sets_from_sections, parse_personality_section,
)
from .option_maps import extract_platform_config

logger = logging.getLogger("quickprs")

# Severity levels
CRITICAL = "CRITICAL"
WARN = "WARN"
INFO = "INFO"

# NOAA Weather Radio frequencies (MHz)
_NOAA_FREQS = {162.400, 162.425, 162.450, 162.475, 162.500, 162.525, 162.550}

# National interop frequencies (NPSPAC, MHz)
_INTEROP_FREQS = {
    # VHF
    155.7525, 156.7625, 158.7375, 159.4725,
    # UHF
    453.2125, 453.4625, 453.7125, 453.8625,
    # 800 MHz
    866.0125, 866.5125, 867.0125, 867.5125,
    # 700 MHz
    769.24375, 769.74375, 770.24375, 770.74375,
}

# Emergency talkgroup IDs (common P25 emergency TG ranges)
_EMERGENCY_TG_KEYWORDS = {"emerg", "911", "emer", "mayday", "distress"}


def _parse_group_sets(prs):
    """Parse P25 group (talkgroup) sets from a PRS file."""
    data_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                    parse_group_section)


def _parse_trunk_sets(prs):
    """Parse trunk frequency sets from a PRS file."""
    data_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                    parse_trunk_channel_section)


def _parse_conv_sets(prs):
    """Parse conventional channel sets from a PRS file."""
    data_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                    parse_conv_channel_section)


def _parse_iden_sets(prs):
    """Parse IDEN sets from a PRS file."""
    data_sec = prs.get_section_by_class("CDefaultIdenElem")
    set_sec = prs.get_section_by_class("CIdenDataSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                    parse_iden_section)


def _get_all_conv_freqs(conv_sets):
    """Collect all unique frequencies from conventional channel sets."""
    freqs = set()
    for cs in conv_sets:
        for ch in cs.channels:
            if ch.tx_freq > 0:
                freqs.add(round(ch.tx_freq, 4))
            if ch.rx_freq > 0:
                freqs.add(round(ch.rx_freq, 4))
    return freqs


def _get_personality_name(prs):
    """Extract the personality filename from CPersonality section."""
    sec = prs.get_section_by_class("CPersonality")
    if not sec:
        return ""
    try:
        pers = parse_personality_section(sec.raw)
        return pers.filename
    except Exception:
        return ""


def _has_noaa_channels(conv_sets):
    """Check if any conventional channels use NOAA frequencies."""
    conv_freqs = _get_all_conv_freqs(conv_sets)
    return bool(conv_freqs & _NOAA_FREQS)


def _has_interop_channels(conv_sets, trunk_sets):
    """Check if any channels use national interop frequencies."""
    conv_freqs = _get_all_conv_freqs(conv_sets)
    trunk_freqs = set()
    for ts in trunk_sets:
        for ch in ts.channels:
            if ch.rx_freq > 0:
                trunk_freqs.add(round(ch.rx_freq, 4))
    all_freqs = conv_freqs | trunk_freqs
    return bool(all_freqs & _INTEROP_FREQS)


def _has_emergency_tg(group_sets):
    """Check if any talkgroups appear to be emergency channels."""
    for gs in group_sets:
        for grp in gs.groups:
            name_lower = (grp.group_name + " " + grp.long_name).lower()
            for keyword in _EMERGENCY_TG_KEYWORDS:
                if keyword in name_lower:
                    return True
    return False


def _find_similar_names(names, threshold=0.85):
    """Find pairs of names that are very similar (easy to confuse)."""
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ratio = SequenceMatcher(None, names[i], names[j]).ratio()
            if ratio >= threshold and names[i] != names[j]:
                pairs.append((names[i], names[j], ratio))
    return pairs


def run_health_check(prs):
    """Run comprehensive health check on a radio personality.

    Returns list of (severity, category, message, suggestion) tuples.

    Checks for common configuration mistakes and best practices
    beyond what hardware-limit validation catches.
    """
    results = []

    # Parse all set types
    group_sets = _parse_group_sets(prs)
    trunk_sets = _parse_trunk_sets(prs)
    conv_sets = _parse_conv_sets(prs)
    iden_sets = _parse_iden_sets(prs)

    # Get personality name
    pers_name = _get_personality_name(prs)

    # Get platform config (XML options)
    try:
        xml_config = extract_platform_config(prs)
    except Exception:
        xml_config = {}

    # Count systems
    system_types = [
        ('CP25TrkSystem', 'P25 Trunked'),
        ('CConvSystem', 'Conventional'),
        ('CP25ConvSystem', 'P25 Conv'),
    ]
    systems = []
    for cls, label in system_types:
        for sec in prs.get_sections_by_class(cls):
            short = parse_system_short_name(sec.raw) or "?"
            systems.append((short, label))

    # ─── Personality-level checks ──────────────────────────────────

    # Very long personality name
    if pers_name and len(pers_name.replace('.PRS', '')) > 20:
        results.append((
            INFO, "Personality",
            f"Personality name '{pers_name}' is long ({len(pers_name)} chars)",
            "Long names may truncate on the radio display. "
            "Consider a shorter name."
        ))

    # Empty personality (no systems at all)
    if not systems:
        results.append((
            WARN, "Personality",
            "No systems configured",
            "This personality has no P25 trunked, conventional, or "
            "P25 conventional systems. Add at least one system."
        ))

    # Duplicate system names
    sys_names = [name for name, _ in systems]
    name_counts = Counter(sys_names)
    for name, count in name_counts.items():
        if count > 1:
            results.append((
                WARN, "Systems",
                f"Duplicate system name '{name}' appears {count} times",
                "Duplicate names can confuse operators switching between "
                "systems on the radio display."
            ))

    # ─── Emergency / safety checks ─────────────────────────────────

    # No emergency talkgroup
    if group_sets and not _has_emergency_tg(group_sets):
        results.append((
            WARN, "Safety",
            "No emergency talkgroup found",
            "Consider adding a dedicated emergency talkgroup for "
            "critical incident communications."
        ))

    # No NOAA weather channels
    if not _has_noaa_channels(conv_sets):
        results.append((
            INFO, "Missing Channels",
            "No NOAA weather monitoring channels",
            "Consider adding NOAA Weather Radio channels for "
            "weather alerts and emergency information."
        ))

    # No interop channels
    if not _has_interop_channels(conv_sets, trunk_sets):
        results.append((
            INFO, "Missing Channels",
            "No national interoperability channels",
            "Consider adding NPSPAC interop channels for "
            "mutual aid and cross-agency communications."
        ))

    # ─── Talkgroup checks ─────────────────────────────────────────

    for gs in group_sets:
        # All TGs have TX disabled
        if gs.groups and all(not grp.tx for grp in gs.groups):
            results.append((
                WARN, "Talkgroups",
                f"All talkgroups in '{gs.name}' have TX disabled",
                "No transmit capability on any talkgroup in this set. "
                "If this is intentional (monitor-only), this is fine."
            ))

        # System with no talkgroups
        if not gs.groups:
            results.append((
                WARN, "Talkgroups",
                f"Group set '{gs.name}' has no talkgroups",
                "Empty talkgroup set serves no purpose. "
                "Add talkgroups or remove the set."
            ))

        # Large number of scan-enabled TGs
        scan_count = sum(1 for grp in gs.groups if grp.scan)
        if scan_count > 100:
            results.append((
                WARN, "Scanning",
                f"Group set '{gs.name}' has {scan_count} scan-enabled "
                f"talkgroups",
                "Scanning more than 100 talkgroups may slow scan speed "
                "and increase time to catch transmissions. Consider "
                "disabling scan on less-used talkgroups."
            ))

        # Very similar talkgroup names (confusing on small display)
        tg_names = [grp.group_name for grp in gs.groups if grp.group_name]
        if len(tg_names) <= 200:  # skip similarity check for very large sets
            similar = _find_similar_names(tg_names)
            for name_a, name_b, ratio in similar[:5]:  # limit output
                results.append((
                    INFO, "Talkgroups",
                    f"Similar names in '{gs.name}': "
                    f"'{name_a}' vs '{name_b}' ({ratio:.0%} similar)",
                    "Very similar talkgroup names can be confusing on "
                    "the radio's small display."
                ))

    # ─── Trunk set checks ─────────────────────────────────────────

    for ts in trunk_sets:
        # Single control channel (no redundancy)
        if len(ts.channels) == 1:
            results.append((
                WARN, "Trunk Frequencies",
                f"Trunk set '{ts.name}' has only 1 frequency",
                "A single control channel provides no redundancy. "
                "If the control channel fails, the radio cannot "
                "connect to the system. Add alternate frequencies."
            ))

    # ─── Conventional channel checks ──────────────────────────────

    for cs in conv_sets:
        # Check for channels with no tones on potentially shared freqs
        no_tone_channels = []
        for ch in cs.channels:
            if not ch.tx_tone and not ch.rx_tone and ch.tx:
                no_tone_channels.append(ch)

        if len(no_tone_channels) > 0 and len(cs.channels) > 1:
            results.append((
                INFO, "Conventional",
                f"'{cs.name}': {len(no_tone_channels)} TX-enabled "
                f"channel(s) with no CTCSS/DCS tones",
                "Channels without tones on shared frequencies may "
                "cause interference. Consider adding CTCSS/DCS tones "
                "if these are shared/repeater frequencies."
            ))

    # ─── IDEN checks ──────────────────────────────────────────────

    for ids in iden_sets:
        active = [e for e in ids.elements if not e.is_empty()]
        if not active:
            results.append((
                WARN, "IDEN",
                f"IDEN set '{ids.name}' has no active identifiers",
                "Empty IDEN set cannot map logical channels to "
                "frequencies. Add identifier entries or remove the set."
            ))

    # ─── System-level checks ──────────────────────────────────────

    # Check for systems with no ECC entries (may not roam properly)
    for sec in prs.get_sections_by_class("CP25TrkSystem"):
        short_name = parse_system_short_name(sec.raw) or "?"

        # Find the system's data section and check for ECC
        idx = prs.sections.index(sec)
        if idx + 1 < len(prs.sections):
            data_sec = prs.sections[idx + 1]
            if is_system_config_data(data_sec.raw):
                try:
                    ecc_count, entries, _ = parse_ecc_entries(data_sec.raw)
                    if ecc_count == 0:
                        results.append((
                            INFO, "Roaming",
                            f"System '{short_name}' has no Enhanced CC "
                            f"entries",
                            "Without Enhanced CC entries, the radio may "
                            "not roam properly between sites."
                        ))
                except Exception:
                    pass

    # ─── Radio options checks ─────────────────────────────────────

    if xml_config:
        # GPS not enabled
        gps_config = xml_config.get("gpsConfig", {})
        gps_mode = gps_config.get("gpsMode", "OFF") if gps_config else "OFF"
        if gps_mode == "OFF":
            results.append((
                INFO, "Radio Options",
                "GPS is disabled",
                "Consider enabling GPS for automatic location reporting "
                "and emergency position tracking."
            ))

        # Password not set
        misc_config = xml_config.get("miscConfig", {})
        password = misc_config.get("password", "") if misc_config else ""
        if not password:
            results.append((
                INFO, "Radio Options",
                "No radio password set",
                "For fleet radios, consider setting a password to "
                "prevent unauthorized configuration changes."
            ))

    # ─── Home Unit ID checks ──────────────────────────────────────

    # Check for systems with default Home Unit ID = 0
    for sec in prs.get_sections_by_class("CP25TrkSystem"):
        short_name = parse_system_short_name(sec.raw) or "?"
        idx = prs.sections.index(sec)
        if idx + 1 < len(prs.sections):
            data_sec = prs.sections[idx + 1]
            if is_system_config_data(data_sec.raw):
                # Home Unit ID is at a variable offset — check via
                # the system config structure
                try:
                    from .binary_io import read_lps, read_uint32_le
                    pos = 44  # after SECTION_MARKER + SYSTEM_CONFIG_PREFIX
                    _, pos = read_lps(data_sec.raw, pos)  # long_name
                    pos += 15  # sys_flags
                    _, pos = read_lps(data_sec.raw, pos)  # trunk_set
                    _, pos = read_lps(data_sec.raw, pos)  # group_set
                    pos += 12  # 12 zeros
                    home_uid, _ = read_uint32_le(data_sec.raw, pos)
                    if home_uid == 0:
                        results.append((
                            INFO, "Configuration",
                            f"System '{short_name}' has default "
                            f"Home Unit ID (0)",
                            "Each radio should have a unique Home Unit ID "
                            "for proper fleet identification."
                        ))
                except Exception:
                    pass

    return results


def format_health_report(results):
    """Format health check results for display.

    Args:
        results: list of (severity, category, message, suggestion) tuples

    Returns:
        list of formatted strings
    """
    if not results:
        return ["Health Check: PASS", "",
                "No issues found. Configuration looks good."]

    lines = ["Health Check Results", "=" * 50, ""]

    # Group by category
    categories = {}
    for severity, category, message, suggestion in results:
        categories.setdefault(category, []).append(
            (severity, message, suggestion))

    # Severity counts
    critical_count = sum(1 for s, _, _, _ in results if s == CRITICAL)
    warn_count = sum(1 for s, _, _, _ in results if s == WARN)
    info_count = sum(1 for s, _, _, _ in results if s == INFO)

    for category, items in sorted(categories.items()):
        lines.append(f"  {category}:")
        for severity, message, suggestion in items:
            marker = {"CRITICAL": "!!!", "WARN": " ! ", "INFO": " i "}
            lines.append(f"    [{marker.get(severity, '   ')}] {message}")
            if suggestion:
                lines.append(f"          {suggestion}")
        lines.append("")

    lines.append("-" * 50)
    parts = []
    if critical_count:
        parts.append(f"{critical_count} critical")
    if warn_count:
        parts.append(f"{warn_count} warnings")
    if info_count:
        parts.append(f"{info_count} info")
    lines.append(f"Summary: {', '.join(parts)} "
                 f"({len(results)} total)")

    return lines


def suggest_improvements(prs, filepath="file.PRS"):
    """Suggest configuration improvements based on current state.

    Returns list of (category, suggestion, command) tuples where
    command is the quickprs CLI command to implement the suggestion.

    Args:
        prs: parsed PRSFile
        filepath: file path for CLI command suggestions
    """
    suggestions = []

    # Parse data
    group_sets = _parse_group_sets(prs)
    trunk_sets = _parse_trunk_sets(prs)
    conv_sets = _parse_conv_sets(prs)

    # Get platform config
    try:
        xml_config = extract_platform_config(prs)
    except Exception:
        xml_config = {}

    # ─── Missing channel templates ─────────────────────────────────

    if not _has_noaa_channels(conv_sets):
        suggestions.append((
            "Missing Channels",
            "Add NOAA weather monitoring channels",
            f"quickprs inject {filepath} conv --name NOAA --template noaa",
        ))

    if not _has_interop_channels(conv_sets, trunk_sets):
        suggestions.append((
            "Missing Channels",
            "Add national interop channels for mutual aid",
            f"quickprs inject {filepath} conv --name INTEROP "
            f"--template interop",
        ))

    # ─── Radio options suggestions ─────────────────────────────────

    if xml_config:
        gps_config = xml_config.get("gpsConfig", {})
        gps_mode = gps_config.get("gpsMode", "OFF") if gps_config else "OFF"
        if gps_mode == "OFF":
            suggestions.append((
                "Radio Options",
                "Enable GPS for automatic location reporting",
                f"quickprs set-option {filepath} gps.gpsMode ON",
            ))

        misc_config = xml_config.get("miscConfig", {})
        password = misc_config.get("password", "") if misc_config else ""
        if not password:
            suggestions.append((
                "Best Practices",
                "Set a radio password to prevent unauthorized changes",
                f"quickprs set-option {filepath} misc.password XXXX",
            ))

    # ─── Talkgroup suggestions ─────────────────────────────────────

    for gs in group_sets:
        # All TGs have scan disabled
        if gs.groups and all(not grp.scan for grp in gs.groups):
            suggestions.append((
                "Scanning",
                f"Enable scan on talkgroups in '{gs.name}' for monitoring",
                f"quickprs bulk-edit {filepath} talkgroups "
                f"--set \"{gs.name}\" --enable-scan",
            ))

    # ─── Conventional channel suggestions ──────────────────────────

    for cs in conv_sets:
        # Channels with no tones where TX is enabled
        no_tone_tx = [ch for ch in cs.channels
                      if not ch.tx_tone and ch.tx]
        if no_tone_tx and len(cs.channels) > 1:
            suggestions.append((
                "Best Practices",
                f"Consider adding CTCSS/DCS tones to '{cs.name}' channels",
                f"quickprs bulk-edit {filepath} channels "
                f"--set \"{cs.name}\" --set-tone \"100.0\"",
            ))

    return suggestions


def format_suggestions(suggestions, filepath="file.PRS"):
    """Format improvement suggestions for display.

    Args:
        suggestions: list of (category, suggestion, command) tuples
        filepath: PRS filename for display header

    Returns:
        list of formatted strings
    """
    from pathlib import Path

    if not suggestions:
        return [
            f"Configuration Suggestions for {Path(filepath).name}",
            "",
            "  No suggestions -- configuration looks complete.",
        ]

    lines = [
        f"Configuration Suggestions for {Path(filepath).name}",
        "",
    ]

    # Group by category
    categories = {}
    for category, suggestion, command in suggestions:
        categories.setdefault(category, []).append((suggestion, command))

    for category, items in sorted(categories.items()):
        lines.append(f"  {category}:")
        for suggestion, command in items:
            lines.append(f"    -> {suggestion}")
            lines.append(f"       {command}")
            lines.append("")
        if not items[-1][1]:
            lines.append("")

    return lines
