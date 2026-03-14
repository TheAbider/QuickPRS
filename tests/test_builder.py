"""Tests for builder.py — create_blank_prs() and minimal PRS file generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.builder import create_blank_prs
from quickprs.prs_parser import parse_prs_bytes
from quickprs.validation import validate_prs
from quickprs.record_types import (
    parse_personality_section,
    parse_class_header,
    parse_conv_channel_section,
    parse_sets_from_sections,
    is_system_config_data,
    parse_system_long_name,
    parse_system_short_name,
    parse_wan_opts_section,
)
from quickprs.binary_io import read_uint16_le


# ─── Roundtrip tests ────────────────────────────────────────────────


def test_blank_prs_roundtrip():
    """create_blank_prs output roundtrips through parse_prs_bytes."""
    prs = create_blank_prs()
    raw1 = prs.to_bytes()
    prs2 = parse_prs_bytes(raw1)
    raw2 = prs2.to_bytes()
    assert raw1 == raw2, "Blank PRS failed byte-identical roundtrip"


def test_blank_prs_double_roundtrip():
    """Roundtrip twice to catch any drift."""
    prs = create_blank_prs()
    raw1 = prs.to_bytes()
    prs2 = parse_prs_bytes(raw1)
    raw2 = prs2.to_bytes()
    prs3 = parse_prs_bytes(raw2)
    raw3 = prs3.to_bytes()
    assert raw1 == raw2 == raw3, "Double roundtrip produced different bytes"


def test_blank_prs_custom_filename():
    """Custom filename is stored in personality section."""
    prs = create_blank_prs(filename="MyRadio.PRS")
    raw = prs.to_bytes()
    prs2 = parse_prs_bytes(raw)
    assert prs2.to_bytes() == raw

    # Check personality
    sec = prs.get_section_by_class("CPersonality")
    assert sec is not None
    p = parse_personality_section(sec.raw)
    assert p.filename == "MyRadio.PRS"


def test_blank_prs_saved_by():
    """saved_by parameter is stored in personality section."""
    prs = create_blank_prs(saved_by="TestUser")
    sec = prs.get_section_by_class("CPersonality")
    p = parse_personality_section(sec.raw)
    assert p.saved_by == "TestUser"


# ─── Validation tests ──────────────────────────────────────────────


def test_blank_prs_validates_clean():
    """Blank PRS passes validation with no errors."""
    prs = create_blank_prs()
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == "ERROR"]
    assert len(errors) == 0, f"Validation errors: {errors}"


def test_blank_prs_no_warnings():
    """Blank PRS has no warnings (advisory INFO is OK)."""
    prs = create_blank_prs()
    issues = validate_prs(prs)
    warnings = [(s, m) for s, m in issues if s == "WARNING"]
    assert len(warnings) == 0, f"Validation warnings: {warnings}"


# ─── Section presence tests ─────────────────────────────────────────


def test_blank_prs_has_personality():
    """Blank PRS contains a CPersonality section."""
    prs = create_blank_prs()
    sec = prs.get_section_by_class("CPersonality")
    assert sec is not None


def test_blank_prs_has_conv_system():
    """Blank PRS contains a CConvSystem header section."""
    prs = create_blank_prs()
    sec = prs.get_section_by_class("CConvSystem")
    assert sec is not None


def test_blank_prs_has_conv_data():
    """Blank PRS contains a system config data section."""
    prs = create_blank_prs()
    found = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            found = True
            break
    assert found, "No system config data section found"


def test_blank_prs_has_conv_set():
    """Blank PRS contains CConvSet section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CConvSet") is not None


def test_blank_prs_has_conv_channel():
    """Blank PRS contains CConvChannel section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CConvChannel") is not None


def test_blank_prs_has_wan_opts():
    """Blank PRS contains CP25tWanOpts section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CP25tWanOpts") is not None


def test_blank_prs_has_wan():
    """Blank PRS contains CP25TrkWan section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CP25TrkWan") is not None


def test_blank_prs_has_type99_opts():
    """Blank PRS contains CType99Opts section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CType99Opts") is not None


def test_blank_prs_has_ct99():
    """Blank PRS contains CT99 section."""
    prs = create_blank_prs()
    assert prs.get_section_by_class("CT99") is not None


def test_blank_prs_has_terminator():
    """Blank PRS ends with the file terminator (ffff + ffff0001)."""
    prs = create_blank_prs()
    last = prs.sections[-1]
    second_last = prs.sections[-2]
    assert second_last.raw == b'\xff\xff', "Missing terminator marker"
    assert last.raw == b'\xff\xff\x00\x01', "Missing terminator tail"


# ─── Content tests ──────────────────────────────────────────────────


def test_blank_prs_personality_values():
    """Personality section has correct default values."""
    prs = create_blank_prs(filename="Test.PRS", saved_by="Me")
    sec = prs.get_section_by_class("CPersonality")
    p = parse_personality_section(sec.raw)

    assert p.filename == "Test.PRS"
    assert p.saved_by == "Me"
    assert p.version == "0014"
    assert p.version_str == "1"
    assert p.mystery4 == b'\x01\x00\x00\x00'


def test_blank_prs_conv_system_name():
    """CConvSystem header has correct system name."""
    prs = create_blank_prs()
    sec = prs.get_section_by_class("CConvSystem")
    name = parse_system_short_name(sec.raw)
    assert name == "Conv 1"


def test_blank_prs_conv_channel_parseable():
    """CConvChannel section can be parsed into ConvSets."""
    prs = create_blank_prs()
    set_sec = prs.get_section_by_class("CConvSet")
    ch_sec = prs.get_section_by_class("CConvChannel")

    sets = parse_sets_from_sections(
        set_sec.raw, ch_sec.raw, parse_conv_channel_section)
    assert len(sets) == 1
    assert sets[0].name == "Conv 1"
    assert len(sets[0].channels) == 1

    ch = sets[0].channels[0]
    assert ch.short_name == "CH 1"
    assert abs(ch.tx_freq - 146.520) < 0.001
    assert abs(ch.rx_freq - 146.520) < 0.001
    assert ch.long_name == "Channel 1"


def test_blank_prs_wan_opts_zero():
    """CP25tWanOpts reports 0 WAN entries."""
    prs = create_blank_prs()
    sec = prs.get_section_by_class("CP25tWanOpts")
    count = parse_wan_opts_section(sec.raw)
    assert count == 0


def test_blank_prs_type99_opts_data():
    """CType99Opts has correct data bytes (00 00 24 00)."""
    prs = create_blank_prs()
    sec = prs.get_section_by_class("CType99Opts")
    _, _, _, ds = parse_class_header(sec.raw, 0)
    data = sec.raw[ds:]
    assert data == b'\x00\x00\x24\x00'


def test_blank_prs_ct99_has_filename():
    """CT99 section embeds the personality filename."""
    prs = create_blank_prs(filename="Radio.PRS")
    sec = prs.get_section_by_class("CT99")
    # The filename should appear as an LPS in the CT99 data
    assert b"Radio.PRS" in sec.raw


def test_blank_prs_file_size_reasonable():
    """Blank PRS file is under 1KB (minimal)."""
    prs = create_blank_prs()
    size = len(prs.to_bytes())
    assert size < 1024, f"Blank PRS is {size} bytes, expected < 1024"
    assert size > 200, f"Blank PRS is only {size} bytes, suspiciously small"


# ─── Idempotency tests ─────────────────────────────────────────────


def test_blank_prs_deterministic():
    """Two calls with same params produce identical bytes."""
    raw1 = create_blank_prs(filename="A.PRS").to_bytes()
    raw2 = create_blank_prs(filename="A.PRS").to_bytes()
    assert raw1 == raw2


def test_blank_prs_different_filenames():
    """Different filenames produce different file bytes."""
    raw1 = create_blank_prs(filename="A.PRS").to_bytes()
    raw2 = create_blank_prs(filename="B.PRS").to_bytes()
    assert raw1 != raw2
