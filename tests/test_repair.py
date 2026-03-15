"""Tests for PRS file repair and recovery."""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs, parse_prs_bytes, PRSFile, Section
from conftest import cached_parse_prs
from quickprs.repair import repair_prs, extract_salvageable_data
from quickprs.validation import validate_structure, ERROR, WARNING
from quickprs.builder import create_blank_prs
from quickprs.binary_io import FILE_TERMINATOR
from quickprs.record_types import (
    build_class_header, is_system_config_data,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE_PRS = TESTDATA / "claude test.PRS"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Normal file (should pass through unchanged) ────────────────────

def test_repair_clean_file():
    """A valid file produces no repairs."""
    prs = create_blank_prs()
    _, repairs = repair_prs(prs)
    assert len(repairs) == 0


def test_repair_paws_no_changes():
    """PAWSOVERMAWS is valid and should not be modified."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(PAWS_PRS)
    original_bytes = prs.to_bytes()
    _, repairs = repair_prs(prs)
    assert len(repairs) == 0
    assert prs.to_bytes() == original_bytes


def test_repair_claude_test_no_changes():
    """claude test is valid and should not be modified."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE_PRS)
    original_bytes = prs.to_bytes()
    _, repairs = repair_prs(prs)
    assert len(repairs) == 0
    assert prs.to_bytes() == original_bytes


# ─── Missing CPersonality ───────────────────────────────────────────

def test_repair_missing_personality():
    """Missing CPersonality gets added."""
    prs = create_blank_prs()
    prs.sections = [s for s in prs.sections
                    if s.class_name != "CPersonality"]
    _, repairs = repair_prs(prs)
    assert any("CPersonality" in r for r in repairs)
    assert prs.get_section_by_class("CPersonality") is not None


def test_repair_personality_not_first():
    """CPersonality not first gets moved."""
    prs = create_blank_prs()
    pers = [s for s in prs.sections if s.class_name == "CPersonality"]
    rest = [s for s in prs.sections if s.class_name != "CPersonality"]
    prs.sections = rest + pers
    _, repairs = repair_prs(prs)
    assert any("Moved" in r for r in repairs)
    assert prs.sections[0].class_name == "CPersonality"


# ─── Duplicate sections ─────────────────────────────────────────────

def test_repair_duplicate_sections():
    """Duplicate singleton sections get removed (keep first)."""
    prs = create_blank_prs()
    # Duplicate the CConvSet section
    conv_set = prs.get_section_by_class("CConvSet")
    assert conv_set is not None
    dup = Section(offset=0, raw=conv_set.raw, class_name="CConvSet")
    prs.sections.append(dup)
    _, repairs = repair_prs(prs)
    assert any("duplicate" in r.lower() for r in repairs)
    # Only one CConvSet should remain
    conv_sets = [s for s in prs.sections if s.class_name == "CConvSet"]
    assert len(conv_sets) == 1


def test_repair_multiple_duplicates():
    """Multiple duplicated section types are all cleaned up."""
    prs = create_blank_prs()
    # Duplicate CConvSet and CConvChannel
    for cls in ["CConvSet", "CConvChannel"]:
        sec = prs.get_section_by_class(cls)
        if sec:
            prs.sections.append(
                Section(offset=0, raw=sec.raw, class_name=cls))
    _, repairs = repair_prs(prs)
    assert any("duplicate" in r.lower() for r in repairs)
    for cls in ["CConvSet", "CConvChannel"]:
        count = sum(1 for s in prs.sections if s.class_name == cls)
        assert count == 1


# ─── Orphan data sections ───────────────────────────────────────────

def test_repair_orphan_data_section():
    """Orphan system config data section gets removed."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import P25TrkSystemConfig
    from quickprs.injector import add_p25_trunked_system, make_group_set, make_trunk_set
    prs = cached_parse_prs(CLAUDE_PRS)

    # Create orphan data: insert a system config data section with
    # no preceding system header
    config = P25TrkSystemConfig(
        system_name="ORPHAN",
        long_name="ORPHAN TEST",
        trunk_set_name="ORPHTRK",
        group_set_name="ORPHGRP",
        wan_name="ORPHWAN",
        home_unit_id=1, system_id=1,
    )
    data_raw = config.build_data_section()
    # Insert at end (before terminator), without its header
    prs.sections.insert(len(prs.sections) - 1,
                        Section(offset=0, raw=data_raw, class_name=""))

    _, repairs = repair_prs(prs)
    assert any("orphan" in r.lower() for r in repairs)


# ─── Missing companion sections ─────────────────────────────────────

def test_repair_missing_companion_trunk():
    """CTrunkSet without CTrunkChannel gets removed."""
    from quickprs.binary_io import write_uint16_le
    prs = create_blank_prs()
    raw = build_class_header("CTrunkSet", 0x64, 0x00) + write_uint16_le(0)
    prs.sections.insert(3, Section(offset=0, raw=raw,
                                    class_name="CTrunkSet"))
    _, repairs = repair_prs(prs)
    assert any("CTrunkSet" in r for r in repairs)
    assert prs.get_section_by_class("CTrunkSet") is None


def test_repair_missing_companion_group():
    """CP25Group without CP25GroupSet gets removed."""
    from quickprs.binary_io import write_uint16_le
    prs = create_blank_prs()
    raw = build_class_header("CP25Group", 0x6a, 0x00) + write_uint16_le(0)
    prs.sections.insert(3, Section(offset=0, raw=raw,
                                    class_name="CP25Group"))
    _, repairs = repair_prs(prs)
    assert any("CP25Group" in r for r in repairs)
    assert prs.get_section_by_class("CP25Group") is None


# ─── Missing file terminator ────────────────────────────────────────

def test_repair_truncated_terminator():
    """Truncated terminator (bare ffff) gets completed."""
    from quickprs.repair import _has_terminator
    prs = create_blank_prs()
    # Replace the last two sections (the terminator pair) with a bare ffff
    # that looks like a truncated terminator
    from quickprs.repair import _is_terminator_section
    prs.sections = [s for s in prs.sections
                    if not _is_terminator_section(s)]
    # Add bare ffff as last section (simulates truncation)
    prs.sections.append(Section(offset=0, raw=b'\xff\xff', class_name=""))
    assert not _has_terminator(prs)
    _, repairs = repair_prs(prs)
    assert any("terminator" in r.lower() for r in repairs)
    assert _has_terminator(prs)


def test_repair_keeps_existing_terminator():
    """File with terminator doesn't get a duplicate."""
    from quickprs.repair import _has_terminator
    prs = create_blank_prs()
    assert _has_terminator(prs)
    _, repairs = repair_prs(prs)
    # No terminator repair should happen
    assert not any("terminator" in r.lower() for r in repairs)


# ─── Section reordering ─────────────────────────────────────────────

def test_repair_personality_position_after_removal():
    """CPersonality moved to first even after section removal."""
    prs = create_blank_prs()
    # Move CPersonality to position 2
    pers = prs.sections[0]
    prs.sections = prs.sections[1:3] + [pers] + prs.sections[3:]
    _, repairs = repair_prs(prs)
    assert any("Moved" in r for r in repairs)
    assert prs.sections[0].class_name == "CPersonality"


# ─── Repaired file validates ────────────────────────────────────────

def test_repair_result_validates():
    """After repair, the file should pass structural validation."""
    prs = create_blank_prs()
    # Create multiple issues
    pers = [s for s in prs.sections if s.class_name == "CPersonality"]
    rest = [s for s in prs.sections if s.class_name != "CPersonality"]
    prs.sections = rest + pers  # personality not first
    # Also duplicate a section
    conv_set = prs.get_section_by_class("CConvSet")
    if conv_set:
        prs.sections.append(
            Section(offset=0, raw=conv_set.raw, class_name="CConvSet"))

    prs, repairs = repair_prs(prs)
    assert len(repairs) >= 1

    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert len(errors) == 0, f"Post-repair errors: {errors}"


# ─── Salvage mode ───────────────────────────────────────────────────

def test_salvage_valid_file():
    """Salvage mode on a valid file extracts all data."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    result = extract_salvageable_data(PAWS_PRS)
    assert result['personality'] is not None
    assert len(result['systems']) > 0
    assert len(result['group_sets']) > 0
    assert len(result['trunk_sets']) > 0
    assert len(result['errors']) == 0


def test_salvage_claude_test():
    """Salvage mode on claude test extracts data."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    result = extract_salvageable_data(CLAUDE_PRS)
    assert result['personality'] is not None
    assert len(result['sections']) > 0


def test_salvage_truncated_file(tmp_path):
    """Salvage mode on a truncated file extracts what it can."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    # Truncate file to 50% of original
    data = PAWS_PRS.read_bytes()
    truncated = data[:len(data) // 2]
    trunc_path = tmp_path / "truncated.PRS"
    trunc_path.write_bytes(truncated)

    result = extract_salvageable_data(trunc_path)
    assert len(result['sections']) > 0
    # Personality should still be extractable (it's at the start)
    assert result['personality'] is not None


def test_salvage_empty_file(tmp_path):
    """Salvage mode on empty file returns error."""
    empty = tmp_path / "empty.PRS"
    empty.write_bytes(b'')

    result = extract_salvageable_data(empty)
    assert len(result['errors']) > 0
    assert "No ffff markers" in result['errors'][0]


def test_salvage_garbage_file(tmp_path):
    """Salvage mode on garbage data finds no valid sections."""
    garbage = tmp_path / "garbage.PRS"
    garbage.write_bytes(b'\x00\x01\x02\x03' * 100)

    result = extract_salvageable_data(garbage)
    assert len(result['sections']) == 0 or result['personality'] is None


def test_salvage_returns_conv_sets():
    """Salvage on file with conv sets extracts them."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    result = extract_salvageable_data(PAWS_PRS)
    assert len(result['conv_sets']) > 0


def test_salvage_returns_iden_sets():
    """Salvage on file with IDEN sets extracts them."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    result = extract_salvageable_data(PAWS_PRS)
    assert len(result['iden_sets']) > 0


# ─── Programmatic damage tests ──────────────────────────────────────

def test_repair_file_with_all_issues():
    """Create a file with multiple issues and verify all are fixed."""
    from quickprs.binary_io import write_uint16_le
    from quickprs.repair import _is_terminator_section

    prs = create_blank_prs()

    # 1. Remove personality
    prs.sections = [s for s in prs.sections
                    if s.class_name != "CPersonality"]

    # 2. Add orphan CTrunkSet (no CTrunkChannel)
    raw = build_class_header("CTrunkSet", 0x64, 0x00) + write_uint16_le(0)
    prs.sections.insert(0, Section(offset=0, raw=raw,
                                    class_name="CTrunkSet"))

    # 3. Replace terminator sections with bare ffff (truncated)
    prs.sections = [s for s in prs.sections
                    if not _is_terminator_section(s)]
    prs.sections.append(Section(offset=0, raw=b'\xff\xff', class_name=""))

    prs, repairs = repair_prs(prs)

    # Should have at least: added personality, removed orphan, fixed terminator
    assert len(repairs) >= 3
    assert prs.get_section_by_class("CPersonality") is not None
    assert prs.get_section_by_class("CTrunkSet") is None  # removed (no companion)


def test_repair_offsets_recalculated():
    """After repair, section offsets should be consistent."""
    prs = create_blank_prs()
    # Create a minor issue
    pers = [s for s in prs.sections if s.class_name == "CPersonality"]
    rest = [s for s in prs.sections if s.class_name != "CPersonality"]
    prs.sections = rest + pers

    prs, repairs = repair_prs(prs)

    # Verify offsets are sequential
    expected_offset = 0
    for sec in prs.sections:
        assert sec.offset == expected_offset, \
            f"Section {sec.class_name} at offset {sec.offset}, expected {expected_offset}"
        expected_offset += len(sec.raw)
    assert prs.file_size == expected_offset
