"""Personality change report — diff two PRS states and produce a human-readable report.

Useful for fleet management: "what did I change in this version?"

Usage (CLI):
    quickprs diff-report before.PRS after.PRS [-o report.txt]

Usage (programmatic):
    from quickprs.diff_report import generate_diff_report
    report = generate_diff_report(original_bytes, modified_prs)
"""

import logging
from datetime import datetime
from pathlib import Path

from .prs_parser import parse_prs, parse_prs_bytes
from .comparison import (
    compare_prs, detailed_comparison, format_comparison,
    ADDED, REMOVED, CHANGED,
)

logger = logging.getLogger("quickprs")


def generate_diff_report(prs_before_bytes, prs_after, output=None):
    """Generate a human-readable report of what changed between two PRS states.

    Args:
        prs_before_bytes: bytes of the original PRS file
        prs_after: PRSFile of the modified version
        output: optional file path to write the report to

    Returns: formatted string report showing:
    - Systems added/removed
    - Talkgroups added/removed/modified
    - Channels added/removed/modified
    - Frequencies added/removed
    - Options changed
    - Set renames
    """
    prs_before = parse_prs_bytes(prs_before_bytes)

    # Get high-level comparison
    basic_diffs = compare_prs(prs_before, prs_after)

    # Get detailed comparison
    detail = detailed_comparison(prs_before, prs_after)

    lines = []
    lines.append("=" * 60)
    lines.append("  PERSONALITY CHANGE REPORT")
    lines.append("=" * 60)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Before: {prs_before.file_size:,} bytes, "
                 f"{len(prs_before.sections)} sections")
    after_size = len(prs_after.to_bytes())
    lines.append(f"After:  {after_size:,} bytes, "
                 f"{len(prs_after.sections)} sections")
    size_delta = after_size - prs_before.file_size
    if size_delta != 0:
        lines.append(f"Delta:  {size_delta:+,} bytes")
    lines.append("")

    has_changes = False

    # Systems
    if detail['systems_a_only'] or detail['systems_b_only']:
        has_changes = True
        lines.append("--- Systems ---")
        for name in detail['systems_a_only']:
            lines.append(f"  REMOVED: {name}")
        for name in detail['systems_b_only']:
            lines.append(f"  ADDED:   {name}")
        lines.append("")

    # Talkgroups
    if detail['talkgroup_diffs']:
        has_changes = True
        lines.append("--- Talkgroups ---")
        for sys_name, diffs in sorted(detail['talkgroup_diffs'].items()):
            lines.append(f"  {sys_name}:")
            for gid, short, long_name in diffs.get('added', []):
                lines.append(f"    + {gid} {short} ({long_name})")
            for gid, short, long_name in diffs.get('removed', []):
                lines.append(f"    - {gid} {short} ({long_name})")
        lines.append("")

    # Trunk frequencies
    if detail['freq_diffs']:
        has_changes = True
        lines.append("--- Trunk Frequencies ---")
        for set_name, diffs in sorted(detail['freq_diffs'].items()):
            lines.append(f"  {set_name}:")
            for freq in diffs.get('added', []):
                lines.append(f"    + {freq:.4f} MHz")
            for freq in diffs.get('removed', []):
                lines.append(f"    - {freq:.4f} MHz")
        lines.append("")

    # Conventional channels
    if detail['conv_diffs']:
        has_changes = True
        lines.append("--- Conventional Channels ---")
        for set_name, diffs in sorted(detail['conv_diffs'].items()):
            lines.append(f"  {set_name}:")
            for short, tx, rx in diffs.get('added', []):
                lines.append(f"    + {short} TX:{tx:.4f} RX:{rx:.4f}")
            for short, tx, rx in diffs.get('removed', []):
                lines.append(f"    - {short} TX:{tx:.4f} RX:{rx:.4f}")
        lines.append("")

    # Options
    if detail['option_diffs']:
        has_changes = True
        lines.append("--- Radio Options ---")
        for field, val_a, val_b in detail['option_diffs']:
            lines.append(f"  {field}: {val_a} -> {val_b}")
        lines.append("")

    # Set-level changes from basic comparison (catches renames, count changes)
    set_changes = [d for d in basic_diffs
                   if d[0] in (ADDED, REMOVED, CHANGED)
                   and d[1] in ("Group Set", "Trunk Set", "Conv Set",
                                "IDEN Set")]
    if set_changes:
        has_changes = True
        lines.append("--- Data Sets ---")
        for dtype, category, name, detail_str in set_changes:
            prefix = {"ADDED": "+", "REMOVED": "-", "CHANGED": "~"}.get(
                dtype, "?")
            lines.append(f"  {prefix} {category} '{name}': {detail_str}")
        lines.append("")

    if not has_changes:
        lines.append("No changes detected.")
        lines.append("")

    # Summary line
    lines.append("-" * 60)
    lines.append(format_change_summary(detail, basic_diffs))

    report = "\n".join(lines)

    if output:
        output_path = Path(output)
        output_path.write_text(report, encoding='utf-8')
        logger.info("Change report written to %s", output_path)

    return report


def generate_diff_report_from_files(path_before, path_after, output=None):
    """Generate a change report from two PRS file paths.

    Convenience function for CLI usage.
    """
    before_bytes = Path(path_before).read_bytes()
    prs_after = parse_prs(path_after)
    return generate_diff_report(before_bytes, prs_after, output=output)


def format_change_summary(detail, basic_diffs=None):
    """Format changes as a short one-line summary.

    Args:
        detail: dict from detailed_comparison()
        basic_diffs: optional list from compare_prs()

    Returns a one-line string like:
        "2 systems added, 15 talkgroups added, 3 options changed"
    """
    parts = []

    n_sys_added = len(detail.get('systems_b_only', []))
    n_sys_removed = len(detail.get('systems_a_only', []))
    if n_sys_added:
        parts.append(f"{n_sys_added} system(s) added")
    if n_sys_removed:
        parts.append(f"{n_sys_removed} system(s) removed")

    n_tg_added = sum(
        len(d.get('added', []))
        for d in detail.get('talkgroup_diffs', {}).values()
    )
    n_tg_removed = sum(
        len(d.get('removed', []))
        for d in detail.get('talkgroup_diffs', {}).values()
    )
    if n_tg_added:
        parts.append(f"{n_tg_added} talkgroup(s) added")
    if n_tg_removed:
        parts.append(f"{n_tg_removed} talkgroup(s) removed")

    n_freq_added = sum(
        len(d.get('added', []))
        for d in detail.get('freq_diffs', {}).values()
    )
    n_freq_removed = sum(
        len(d.get('removed', []))
        for d in detail.get('freq_diffs', {}).values()
    )
    if n_freq_added:
        parts.append(f"{n_freq_added} frequency(ies) added")
    if n_freq_removed:
        parts.append(f"{n_freq_removed} frequency(ies) removed")

    n_conv_added = sum(
        len(d.get('added', []))
        for d in detail.get('conv_diffs', {}).values()
    )
    n_conv_removed = sum(
        len(d.get('removed', []))
        for d in detail.get('conv_diffs', {}).values()
    )
    if n_conv_added:
        parts.append(f"{n_conv_added} channel(s) added")
    if n_conv_removed:
        parts.append(f"{n_conv_removed} channel(s) removed")

    n_opts = len(detail.get('option_diffs', []))
    if n_opts:
        parts.append(f"{n_opts} option(s) changed")

    # Count set-level changes from basic diffs
    if basic_diffs:
        set_added = sum(1 for d in basic_diffs
                        if d[0] == ADDED and "Set" in d[1])
        set_removed = sum(1 for d in basic_diffs
                          if d[0] == REMOVED and "Set" in d[1])
        if set_added:
            parts.append(f"{set_added} set(s) added")
        if set_removed:
            parts.append(f"{set_removed} set(s) removed")

    if not parts:
        return "No changes."

    return "Summary: " + ", ".join(parts)
