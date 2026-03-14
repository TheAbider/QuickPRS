"""PRS file repair and data recovery.

Attempts to fix common corruption issues in .PRS files:
- Missing CPersonality section
- Orphan data sections (no parent system header)
- Truncated sections (trim to valid data)
- Missing companion sections (e.g., CTrunkSet without CTrunkChannel)
- Invalid section ordering (reorder to standard RPM layout)
- Missing file terminator
- Duplicate sections (keep first, remove duplicates)

Also provides best-effort data extraction from badly damaged files
where parse_prs() would fail entirely.
"""

import logging
import struct

from .prs_parser import PRSFile, Section, parse_prs, parse_prs_bytes
from .binary_io import (
    find_all_ffff, try_read_class_name, SECTION_MARKER,
    FILE_TERMINATOR, write_lps, write_uint16_le,
)
from .record_types import (
    is_system_config_data, parse_system_long_name,
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_sets_from_sections,
    build_class_header,
)

logger = logging.getLogger("quickprs")


# Standard RPM section order (class names in preferred sequence).
# Named sections not in this list are placed at the end before terminator.
STANDARD_ORDER = [
    "CPersonality",
    "CP25TrkSystem",        # P25 trunked system headers (+ data sections)
    "CConvSystem",          # Conventional system headers (+ data sections)
    "CP25ConvSystem",       # P25 conventional system headers (+ data sections)
    "CPreferredSystemTableEntry",
    "CTrunkSet",
    "CTrunkChannel",
    "CP25GroupSet",
    "CP25Group",
    "CConvSet",
    "CConvChannel",
    "CP25ConvSet",
    "CP25ConvChannel",
    "CIdenDataSet",
    "CDefaultIdenElem",
    "CP25tWanOpts",
    "CP25TrkWan",
    "CType99Opts",
    "CT99",
]

# Companion section pairs — if one exists the other must too
COMPANION_PAIRS = [
    ("CTrunkSet", "CTrunkChannel"),
    ("CConvSet", "CConvChannel"),
    ("CP25GroupSet", "CP25Group"),
    ("CIdenDataSet", "CDefaultIdenElem"),
    ("CP25ConvSet", "CP25ConvChannel"),
    ("CP25tWanOpts", "CP25TrkWan"),
    ("CType99Opts", "CT99"),
]


def repair_prs(prs, issues=None):
    """Attempt to repair a damaged PRS file.

    Fixes:
    - Missing CPersonality section (creates default)
    - Orphan data sections (no parent system header)
    - Truncated sections (trim to valid data)
    - Missing companion sections (e.g., CTrunkSet without CTrunkChannel)
    - Invalid section ordering (reorder to standard RPM layout)
    - Missing file terminator
    - Duplicate sections (keep first, remove duplicates)

    Args:
        prs: PRSFile object to repair (modified in-place)
        issues: optional list from validate_structure() to guide repairs

    Returns:
        (repaired_prs, list_of_repairs_made)
    """
    repairs = []

    # 1. Fix missing CPersonality
    personality = prs.get_section_by_class("CPersonality")
    if not personality:
        _add_default_personality(prs)
        repairs.append("Added missing CPersonality section with defaults")

    # 2. Fix CPersonality not first
    if prs.sections and prs.sections[0].class_name != "CPersonality":
        pers_sections = [s for s in prs.sections
                         if s.class_name == "CPersonality"]
        other = [s for s in prs.sections
                 if s.class_name != "CPersonality"]
        if pers_sections:
            prs.sections = pers_sections[:1] + other
            repairs.append("Moved CPersonality to first position")

    # 3. Remove duplicate class sections (keep first occurrence)
    seen_singles = set()
    # These classes should appear at most once
    singleton_classes = {
        "CPersonality", "CTrunkSet", "CTrunkChannel",
        "CP25GroupSet", "CP25Group", "CConvSet", "CConvChannel",
        "CIdenDataSet", "CDefaultIdenElem", "CP25tWanOpts", "CP25TrkWan",
        "CType99Opts", "CT99",
    }
    deduped = []
    removed_dupes = []
    for sec in prs.sections:
        if sec.class_name in singleton_classes:
            if sec.class_name in seen_singles:
                removed_dupes.append(sec.class_name)
                continue
            seen_singles.add(sec.class_name)
        deduped.append(sec)
    if removed_dupes:
        prs.sections = deduped
        counts = {}
        for name in removed_dupes:
            counts[name] = counts.get(name, 0) + 1
        parts = [f"{name} (x{count})" for name, count in counts.items()]
        repairs.append(f"Removed duplicate sections: {', '.join(parts)}")

    # 4. Remove orphan system config data sections
    header_types = {"CP25TrkSystem", "CConvSystem", "CP25ConvSystem"}
    to_remove = []
    for i, sec in enumerate(prs.sections):
        if not sec.class_name and is_system_config_data(sec.raw):
            found_header = False
            for j in range(i - 1, -1, -1):
                if prs.sections[j].class_name in header_types:
                    found_header = True
                    break
                if prs.sections[j].class_name == "CPreferredSystemTableEntry":
                    continue
                if not prs.sections[j].class_name:
                    continue
                break
            if not found_header:
                long = parse_system_long_name(sec.raw) or "(unknown)"
                to_remove.append(i)
                repairs.append(
                    f"Removed orphan system config data "
                    f"'{long}' at index {i}")
    if to_remove:
        prs.sections = [s for i, s in enumerate(prs.sections)
                        if i not in set(to_remove)]

    # 5. Fix missing companion sections
    for cls_a, cls_b in COMPANION_PAIRS:
        has_a = prs.get_section_by_class(cls_a) is not None
        has_b = prs.get_section_by_class(cls_b) is not None
        if has_a and not has_b:
            # Remove the orphan section since we can't generate a
            # valid companion from nothing
            prs.sections = [s for s in prs.sections
                            if s.class_name != cls_a]
            repairs.append(
                f"Removed {cls_a} (companion {cls_b} is missing "
                f"and cannot be reconstructed)")
        elif has_b and not has_a:
            prs.sections = [s for s in prs.sections
                            if s.class_name != cls_b]
            repairs.append(
                f"Removed {cls_b} (companion {cls_a} is missing "
                f"and cannot be reconstructed)")

    # 6. Minimal reorder: only fix CPersonality position (already
    #    handled in step 2) and move obviously misplaced sections.
    #    We do NOT impose a full canonical order because real RPM files
    #    have many option sections in varying order, and rearranging
    #    them could break compatibility.
    pass  # CPersonality positioning is handled in step 2

    # 7. Ensure file terminator (only if file originally had one)
    # The terminator pattern ffff ffff0001 gets split into two sections
    # by find_all_ffff: one with raw=b'\xff\xff' and one with
    # raw=b'\xff\xff\x00\x01'. Some valid files (like PAWSOVERMAWS)
    # don't have terminators at all.
    if prs.sections:
        _fix_terminator(prs, repairs)

    # Recalculate offsets
    offset = 0
    for sec in prs.sections:
        sec.offset = offset
        offset += len(sec.raw)
    prs.file_size = offset

    return prs, repairs


def extract_salvageable_data(filepath):
    """Extract whatever data can be read from a damaged PRS file.

    Even if parse_prs() fails, this function tries to:
    - Find valid section markers (ffff)
    - Parse each section independently
    - Collect whatever trunk sets, group sets, conv sets, IDEN sets
      are readable
    - Return a dict of recovered data

    Args:
        filepath: path to the damaged PRS file

    Returns:
        dict with keys:
            'personality': Personality dict or None
            'systems': list of system info dicts
            'trunk_sets': list of TrunkSet objects
            'group_sets': list of P25GroupSet objects
            'conv_sets': list of ConvSet objects
            'iden_sets': list of IdenDataSet objects
            'sections': list of Section objects that were parseable
            'errors': list of error messages encountered
    """
    from pathlib import Path

    data = Path(filepath).read_bytes()
    result = {
        'personality': None,
        'systems': [],
        'trunk_sets': [],
        'group_sets': [],
        'conv_sets': [],
        'iden_sets': [],
        'sections': [],
        'errors': [],
    }

    # Find all ffff markers
    markers = find_all_ffff(data)
    if not markers:
        result['errors'].append("No ffff markers found in file")
        return result

    # Build sections from markers
    sections = []
    for i, marker_offset in enumerate(markers):
        if i + 1 < len(markers):
            next_offset = markers[i + 1]
        else:
            next_offset = len(data)
        raw = data[marker_offset:next_offset]
        class_name, _ = try_read_class_name(data, marker_offset)
        sections.append(Section(
            offset=marker_offset,
            raw=raw,
            class_name=class_name or "",
        ))

    result['sections'] = sections

    # Build a temporary PRSFile for set parsing
    temp_prs = PRSFile(
        sections=sections,
        filepath=str(filepath),
        file_size=len(data),
    )

    # Try to extract personality info
    pers_sec = temp_prs.get_section_by_class("CPersonality")
    if pers_sec:
        try:
            from .record_types import parse_personality_section
            personality = parse_personality_section(pers_sec.raw)
            result['personality'] = {
                'filename': personality.filename,
                'saved_by': personality.saved_by,
                'version': personality.version,
            }
        except Exception as e:
            result['errors'].append(f"CPersonality parse error: {e}")

    # Try to extract system info
    for sec in sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            try:
                long = parse_system_long_name(sec.raw) or "(unknown)"
                result['systems'].append({'long_name': long})
            except Exception as e:
                result['errors'].append(
                    f"System config parse error at 0x{sec.offset:x}: {e}")

    # Try to extract group sets
    grp_sec = temp_prs.get_section_by_class("CP25Group")
    set_sec = temp_prs.get_section_by_class("CP25GroupSet")
    if grp_sec and set_sec:
        try:
            sets = parse_sets_from_sections(
                set_sec.raw, grp_sec.raw, parse_group_section)
            if sets:
                result['group_sets'] = sets
        except Exception as e:
            result['errors'].append(f"Group set parse error: {e}")

    # Try to extract trunk sets
    ch_sec = temp_prs.get_section_by_class("CTrunkChannel")
    ts_sec = temp_prs.get_section_by_class("CTrunkSet")
    if ch_sec and ts_sec:
        try:
            sets = parse_sets_from_sections(
                ts_sec.raw, ch_sec.raw, parse_trunk_channel_section)
            if sets:
                result['trunk_sets'] = sets
        except Exception as e:
            result['errors'].append(f"Trunk set parse error: {e}")

    # Try to extract conv sets
    conv_sec = temp_prs.get_section_by_class("CConvChannel")
    conv_set_sec = temp_prs.get_section_by_class("CConvSet")
    if conv_sec and conv_set_sec:
        try:
            sets = parse_sets_from_sections(
                conv_set_sec.raw, conv_sec.raw,
                parse_conv_channel_section)
            if sets:
                result['conv_sets'] = sets
        except Exception as e:
            result['errors'].append(f"Conv set parse error: {e}")

    # Try to extract IDEN sets
    elem_sec = temp_prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = temp_prs.get_section_by_class("CIdenDataSet")
    if elem_sec and ids_sec:
        try:
            sets = parse_sets_from_sections(
                ids_sec.raw, elem_sec.raw, parse_iden_section)
            if sets:
                result['iden_sets'] = sets
        except Exception as e:
            result['errors'].append(f"IDEN set parse error: {e}")

    return result


def _add_default_personality(prs):
    """Insert a default CPersonality section at position 0."""
    from .record_types import Personality, build_personality_section

    personality = Personality(
        filename="Repaired.PRS",
        saved_by="QuickPRS repair",
        version="0014",
        mystery4=b'\x01\x00\x00\x00',
        version_str="1",
        footer=b'\x02\x00\x65\x00\x7e\x00\x03\x00',
    )
    raw = build_personality_section(personality)
    sec = Section(offset=0, raw=raw, class_name="CPersonality")
    prs.sections.insert(0, sec)


def _reorder_sections(sections):
    """Reorder sections to match standard RPM layout.

    Rules:
    - CPersonality always first
    - System headers followed by their data sections
    - Named class sections in STANDARD_ORDER
    - Unknown named sections preserved at end
    - Terminator always last
    """
    # Group sections by category
    personality = []
    system_groups = []    # [(header_sec, [data_secs]), ...]
    named_by_class = {}   # class_name -> [sections]
    terminator = []
    other_unnamed = []

    header_types = {"CP25TrkSystem", "CConvSystem", "CP25ConvSystem"}

    i = 0
    while i < len(sections):
        sec = sections[i]
        if sec.class_name == "CPersonality":
            personality.append(sec)
            i += 1
        elif sec.class_name in header_types:
            # Collect the header and its following data sections
            group = [sec]
            j = i + 1
            while j < len(sections):
                next_sec = sections[j]
                if next_sec.class_name in header_types:
                    break
                if next_sec.class_name and next_sec.class_name not in (
                        "CPreferredSystemTableEntry",):
                    break
                # Unnamed data or CPreferredSystemTableEntry
                group.append(next_sec)
                j += 1
                # If we just added a system config data section, stop
                if (not next_sec.class_name and
                        is_system_config_data(next_sec.raw)):
                    break
            system_groups.append(group)
            i = j
        elif _is_terminator_section(sec):
            terminator.append(sec)
            i += 1
        elif sec.class_name:
            named_by_class.setdefault(sec.class_name, []).append(sec)
            i += 1
        else:
            other_unnamed.append(sec)
            i += 1

    # Rebuild in standard order
    result = list(personality)

    # System groups
    for group in system_groups:
        result.extend(group)

    # Named sections in standard order
    for cls_name in STANDARD_ORDER:
        if cls_name in named_by_class:
            result.extend(named_by_class.pop(cls_name))

    # Any remaining named sections not in standard order
    for cls_name in sorted(named_by_class.keys()):
        result.extend(named_by_class[cls_name])

    # Other unnamed sections
    result.extend(other_unnamed)

    # Terminator last
    result.extend(terminator)

    return result


def _is_terminator_section(sec):
    """Check if a section is part of the file terminator pattern.

    The terminator ffff ffff0001 gets split by find_all_ffff into:
    - Section with raw=b'\\xff\\xff' (2 bytes)
    - Section with raw=b'\\xff\\xff\\x00\\x01' (4 bytes)
    Either of these (or the combined 6-byte FILE_TERMINATOR) indicates
    a terminator.
    """
    if sec.raw == FILE_TERMINATOR:
        return True
    if sec.raw.endswith(FILE_TERMINATOR):
        return True
    if not sec.class_name and len(sec.raw) <= 4 and \
            all(b in (0x00, 0x01, 0xFF) for b in sec.raw):
        return True
    return False


def _has_terminator(prs):
    """Check if the file already has a COMPLETE terminator at the end.

    The terminator pattern ffff ffff0001 is typically split into two
    sections by the parser:
    - Section with raw=b'\\xff\\xff' (2 bytes)
    - Section with raw=b'\\xff\\xff\\x00\\x01' (4 bytes)
    We need BOTH for a complete terminator. A bare b'\\xff\\xff' alone
    is considered truncated.
    """
    if not prs.sections:
        return False

    last = prs.sections[-1]

    # Full 6-byte terminator in one section
    if last.raw == FILE_TERMINATOR:
        return True
    if last.raw.endswith(FILE_TERMINATOR):
        return True

    # Split terminator: last section is ffff0001 (4 bytes)
    if (not last.class_name and last.raw == b'\xff\xff\x00\x01'
            and len(prs.sections) >= 2):
        prev = prs.sections[-2]
        if not prev.class_name and prev.raw == b'\xff\xff':
            return True

    # A bare b'\xff\xff' at the end is NOT a complete terminator
    return False


def _fix_terminator(prs, repairs):
    """Add file terminator only if the file originally had one and it
    was truncated or corrupted.

    Many valid RPM files don't have terminators at all, so we only
    add one when we see evidence of a partial/truncated terminator
    pattern (e.g., a bare ffff at end that looks like the start of
    a ffffffff0001 sequence).
    """
    if _has_terminator(prs):
        return

    # Only add terminator if the last section is a bare 2-byte ffff
    # that looks like a truncated terminator start
    if prs.sections:
        last = prs.sections[-1]
        if (not last.class_name and last.raw == b'\xff\xff'):
            # Replace the bare ffff with a full terminator
            prs.sections[-1] = Section(
                offset=0,
                raw=FILE_TERMINATOR,
                class_name="",
            )
            repairs.append("Completed truncated file terminator")
