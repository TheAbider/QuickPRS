"""Zone planning — organize channels into logical groups for the XG-100P zone selector.

XG-100P radios organize channels into zones selectable via the channel knob.
Each zone can hold up to 48 channels (16 knob positions x 3 banks A/B/C).
The radio supports up to 50 zones per personality.

Zones aren't stored as explicit sections in PRS files — they're implied by
the channel ordering within sets. This module helps users plan and visualize
how channels would be organized into zones.

Strategies:
  - "auto":     one zone per conv set + one zone per group set
  - "by_set":   each set gets its own zone(s), split if >48 channels
  - "combined": merge all channels into zones of 48
  - "manual":   return empty plan for user customization
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from .prs_parser import PRSFile
from .record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section,
    parse_sets_from_sections,
)

logger = logging.getLogger("quickprs")

# XG-100P zone limits
MAX_CHANNELS_PER_ZONE = 48
MAX_ZONES = 50


@dataclass
class Zone:
    """A logical grouping of channels for the radio's zone selector."""
    name: str                                  # zone name (16 chars max)
    channels: List[Tuple[str, int]] = field(default_factory=list)
    # list of (set_name, channel_index) references

    MAX_CHANNELS = MAX_CHANNELS_PER_ZONE       # XG-100P zone limit

    def is_full(self):
        """Check if the zone is at capacity."""
        return len(self.channels) >= self.MAX_CHANNELS

    def remaining(self):
        """Number of channels that can still be added."""
        return max(0, self.MAX_CHANNELS - len(self.channels))


def _get_group_sets(prs):
    """Parse group (talkgroup) sets from a PRS file."""
    data_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(
        set_sec.raw, data_sec.raw, parse_group_section)


def _get_conv_sets(prs):
    """Parse conventional channel sets from a PRS file."""
    data_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(
        set_sec.raw, data_sec.raw, parse_conv_channel_section)


def _get_trunk_sets(prs):
    """Parse trunk channel sets from a PRS file."""
    data_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not data_sec or not set_sec:
        return []
    return parse_sets_from_sections(
        set_sec.raw, data_sec.raw, parse_trunk_channel_section)


def _split_into_zones(name, channel_refs, zones):
    """Split a list of channel refs into zones of MAX_CHANNELS_PER_ZONE."""
    if not channel_refs:
        return
    for i in range(0, len(channel_refs), MAX_CHANNELS_PER_ZONE):
        chunk = channel_refs[i:i + MAX_CHANNELS_PER_ZONE]
        suffix = ""
        if len(channel_refs) > MAX_CHANNELS_PER_ZONE:
            part = (i // MAX_CHANNELS_PER_ZONE) + 1
            suffix = f" {part}"
        zone_name = (name + suffix)[:16]
        zones.append(Zone(name=zone_name, channels=chunk))


def plan_zones(prs, strategy="auto"):
    """Generate a zone plan from the current personality data.

    Strategies:
    - "auto":     one zone per conv set + one zone per group set
    - "by_set":   each set gets its own zone(s), split if >48
    - "combined": merge all channels into zones of 48
    - "manual":   return empty plan for user customization

    Returns list of Zone objects.
    """
    if strategy == "manual":
        return []

    conv_sets = _get_conv_sets(prs)
    group_sets = _get_group_sets(prs)

    zones = []

    if strategy == "auto":
        # One zone per conv set (split if needed)
        for cs in conv_sets:
            refs = [(cs.name, i) for i in range(len(cs.channels))]
            _split_into_zones(cs.name, refs, zones)

        # One zone per group set (split if needed)
        for gs in group_sets:
            refs = [(gs.name, i) for i in range(len(gs.groups))]
            _split_into_zones(gs.name, refs, zones)

    elif strategy == "by_set":
        # Same as auto but with explicit "by set" semantics
        for cs in conv_sets:
            refs = [(cs.name, i) for i in range(len(cs.channels))]
            _split_into_zones(cs.name, refs, zones)

        for gs in group_sets:
            refs = [(gs.name, i) for i in range(len(gs.groups))]
            _split_into_zones(gs.name, refs, zones)

    elif strategy == "combined":
        # Merge all channels into zones of 48
        all_refs = []
        for cs in conv_sets:
            for i in range(len(cs.channels)):
                all_refs.append((cs.name, i))
        for gs in group_sets:
            for i in range(len(gs.groups)):
                all_refs.append((gs.name, i))

        _split_into_zones("Zone", all_refs, zones)

    else:
        raise ValueError(f"Unknown zone strategy: {strategy!r}")

    return zones


def format_zone_plan(zones):
    """Format a zone plan as readable text.

    Returns a list of text lines.
    """
    if not zones:
        return ["No zones in plan."]

    lines = []
    total_channels = sum(len(z.channels) for z in zones)
    lines.append(f"Zone Plan: {len(zones)} zones, "
                 f"{total_channels} total channels")
    lines.append("")

    for i, zone in enumerate(zones, 1):
        pct = len(zone.channels) / MAX_CHANNELS_PER_ZONE * 100
        lines.append(f"  Zone {i}: {zone.name} "
                     f"({len(zone.channels)}/{MAX_CHANNELS_PER_ZONE} "
                     f"channels, {pct:.0f}% full)")

        # Group channels by set
        by_set = {}
        for set_name, ch_idx in zone.channels:
            by_set.setdefault(set_name, []).append(ch_idx)

        for set_name, indices in by_set.items():
            if len(indices) <= 5:
                idx_str = ", ".join(str(i) for i in indices)
            else:
                idx_str = (f"{indices[0]}-{indices[-1]} "
                           f"({len(indices)} channels)")
            lines.append(f"    {set_name}: ch {idx_str}")

    return lines


def validate_zone_plan(zones):
    """Check zone plan against XG-100P limits.

    Returns list of (severity, message) tuples.
    Severity is 'error' or 'warning'.
    """
    issues = []

    if len(zones) > MAX_ZONES:
        issues.append(("error",
                       f"Too many zones: {len(zones)} "
                       f"(max {MAX_ZONES})"))

    for i, zone in enumerate(zones, 1):
        if len(zone.channels) > MAX_CHANNELS_PER_ZONE:
            issues.append(("error",
                           f"Zone {i} '{zone.name}' has "
                           f"{len(zone.channels)} channels "
                           f"(max {MAX_CHANNELS_PER_ZONE})"))

        if len(zone.channels) == 0:
            issues.append(("warning",
                           f"Zone {i} '{zone.name}' is empty"))

        if len(zone.name) > 16:
            issues.append(("warning",
                           f"Zone {i} name '{zone.name}' exceeds "
                           f"16 characters (will be truncated)"))

    # Check for duplicate zone names
    seen_names = {}
    for i, zone in enumerate(zones, 1):
        if zone.name in seen_names:
            issues.append(("warning",
                           f"Duplicate zone name '{zone.name}' "
                           f"(zones {seen_names[zone.name]} and {i})"))
        else:
            seen_names[zone.name] = i

    return issues


def export_zone_plan_csv(zones, filepath):
    """Export a zone plan to CSV.

    CSV columns: zone_number, zone_name, set_name, channel_index

    Args:
        zones: list of Zone objects
        filepath: output CSV file path
    """
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["zone_number", "zone_name",
                         "set_name", "channel_index"])
        for i, zone in enumerate(zones, 1):
            for set_name, ch_idx in zone.channels:
                writer.writerow([i, zone.name, set_name, ch_idx])


def format_zone_plan_csv(zones):
    """Format a zone plan as CSV string (for display/copy).

    Returns CSV text.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["zone_number", "zone_name",
                     "set_name", "channel_index"])
    for i, zone in enumerate(zones, 1):
        for set_name, ch_idx in zone.channels:
            writer.writerow([i, zone.name, set_name, ch_idx])
    return buf.getvalue()
