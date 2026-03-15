"""Tests for IDEN trailing data preservation during injection.

The CDefaultIdenElem section contains trailing data AFTER the IDEN elements:
  - Zero-byte padding
  - ff marker + uint16 LE XML length
  - <platformConfig> XML (radio configuration)
  - Passwords (LPS strings)
  - Radio GUID

This data must be preserved when IDEN sets are added, deleted, or renamed.
"""

import sys
from pathlib import Path
from copy import deepcopy

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    IdenElement, IdenDataSet,
    parse_class_header, parse_iden_section,
    extract_iden_trailing_data, build_iden_section,
)
from quickprs.injector import (
    add_iden_set, make_iden_set, _get_first_count,
)
from quickprs.option_maps import extract_platform_xml

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── extract_iden_trailing_data tests ────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestExtractIdenTrailingData:
    """Tests for the extract_iden_trailing_data function."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_size(self):
        """PAWSOVERMAWS has 3 IDEN sets, trailing = 3126 bytes."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert len(trailing) == 3126, f"Expected 3126, got {len(trailing)}"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_starts_with_zeros(self):
        """Trailing data begins with 6 zero-byte padding."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert trailing[:6] == b'\x00' * 6

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_has_ff_marker(self):
        """Trailing data has ff marker at byte 6."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert trailing[6:7] == b'\xff'

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_xml_length(self):
        """uint16 LE at byte 7 gives XML length = 3035."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        xml_len = int.from_bytes(trailing[7:9], 'little')
        assert xml_len == 3035

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_has_platform_xml(self):
        """Trailing data contains <platformConfig> XML."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert b'<platformConfig>' in trailing
        assert b'</platformConfig>' in trailing

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_has_passwords(self):
        """Trailing data contains LPS password strings '1115'."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        # LPS "1115" = 04 31 31 31 35
        assert b'\x041115' in trailing

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_has_guid(self):
        """Trailing data contains the radio GUID."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert b'00000000-2020-2020-2020-202020202020' in trailing

    def test_claude_test_trailing_size(self):
        """claude test.PRS has 1 IDEN set, trailing = 39 bytes."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert len(trailing) == 39, f"Expected 39, got {len(trailing)}"

    def test_claude_test_trailing_all_zeros(self):
        """claude test.PRS trailing data is all zeros."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        sec = prs.get_section_by_class("CDefaultIdenElem")
        first_count = _get_first_count(prs, "CIdenDataSet")
        trailing = extract_iden_trailing_data(sec.raw, first_count)
        assert trailing == b'\x00' * 39


# ─── IDEN injection preserves trailing data ──────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestIdenInjectionPreservesTrailing:
    """Tests that IDEN injection preserves trailing data."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_xml_preserved(self):
        """After IDEN injection on PAWSOVERMAWS, platformConfig XML is intact."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        xml_before = extract_platform_xml(prs)
        assert xml_before is not None, "XML missing before injection"

        prs2 = deepcopy(prs)
        iset = make_iden_set("TEST", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        xml_after = extract_platform_xml(prs2)
        assert xml_after is not None, "XML lost after injection"
        assert xml_after == xml_before, "XML content changed after injection"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_passwords_preserved(self):
        """After IDEN injection on PAWSOVERMAWS, passwords are intact."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        prs2 = deepcopy(prs)
        iset = make_iden_set("TEST", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        # Check LPS "1115" is in the modified section
        sec = prs2.get_section_by_class("CDefaultIdenElem")
        assert b'\x041115' in sec.raw, "Password LPS '1115' lost after injection"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_guid_preserved(self):
        """After IDEN injection on PAWSOVERMAWS, radio GUID is intact."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        prs2 = deepcopy(prs)
        iset = make_iden_set("TEST", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        sec = prs2.get_section_by_class("CDefaultIdenElem")
        assert b'00000000-2020-2020-2020-202020202020' in sec.raw

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_trailing_bytes_exact(self):
        """Trailing data is byte-for-byte identical after injection."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        first_count = _get_first_count(prs, "CIdenDataSet")
        sec_before = prs.get_section_by_class("CDefaultIdenElem")
        trailing_before = extract_iden_trailing_data(sec_before.raw, first_count)

        prs2 = deepcopy(prs)
        iset = make_iden_set("TEST", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        # Re-extract first_count (still same since first set unchanged)
        new_first_count = _get_first_count(prs2, "CIdenDataSet")
        sec_after = prs2.get_section_by_class("CDefaultIdenElem")
        trailing_after = extract_iden_trailing_data(sec_after.raw, new_first_count)

        assert trailing_after == trailing_before, (
            f"Trailing data changed: {len(trailing_before)} -> {len(trailing_after)}"
        )

    def test_claude_test_trailing_zeros_preserved(self):
        """After IDEN injection on claude test.PRS, trailing zeros preserved."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        first_count = _get_first_count(prs, "CIdenDataSet")
        sec_before = prs.get_section_by_class("CDefaultIdenElem")
        trailing_before = extract_iden_trailing_data(sec_before.raw, first_count)

        prs2 = deepcopy(prs)
        iset = make_iden_set("NEWSET", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        new_first_count = _get_first_count(prs2, "CIdenDataSet")
        sec_after = prs2.get_section_by_class("CDefaultIdenElem")
        trailing_after = extract_iden_trailing_data(sec_after.raw, new_first_count)

        assert trailing_after == trailing_before
        assert trailing_after == b'\x00' * 39

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_section_grew(self):
        """After adding an IDEN set, section is larger (new set + preserved trailing)."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec_before = prs.get_section_by_class("CDefaultIdenElem")
        size_before = len(sec_before.raw)

        prs2 = deepcopy(prs)
        iset = make_iden_set("TEST", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        sec_after = prs2.get_section_by_class("CDefaultIdenElem")
        size_after = len(sec_after.raw)
        assert size_after > size_before, (
            f"Section didn't grow: {size_before} -> {size_after}"
        )

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_iden_sets_parse_after_injection(self):
        """All IDEN sets (original + injected) still parse correctly."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        prs2 = deepcopy(prs)
        iset = make_iden_set("NEWIDN", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
        ])
        add_iden_set(prs2, iset)

        first_count = _get_first_count(prs2, "CIdenDataSet")
        sec = prs2.get_section_by_class("CDefaultIdenElem")
        _, _, _, data_start = parse_class_header(sec.raw, 0)
        sets = parse_iden_section(sec.raw, data_start, len(sec.raw), first_count)

        assert len(sets) == 4, f"Expected 4 sets, got {len(sets)}"
        assert sets[0].name == "BEE00"
        assert sets[1].name == "58544"
        assert sets[2].name == "92738"
        assert sets[3].name == "NEWIDN"


# ─── build_iden_section trailing_data parameter ──────────────────────

class TestBuildIdenSectionTrailing:
    """Tests for build_iden_section with trailing_data parameter."""

    def test_trailing_data_appended(self):
        """build_iden_section appends trailing_data to output."""
        elem = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                           base_freq_hz=851006250, tx_offset=0, iden_type=0)
        iset = IdenDataSet(name="TEST", elements=[elem])
        trailing = b'\x00' * 6 + b'\xff' + b'\x0b\x00' + b'<test/>'

        raw = build_iden_section([iset], trailing_data=trailing)
        assert raw.endswith(trailing)

    def test_no_trailing_data(self):
        """build_iden_section without trailing_data works as before."""
        elem = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                           base_freq_hz=851006250, tx_offset=0, iden_type=0)
        iset = IdenDataSet(name="TEST", elements=[elem])

        raw = build_iden_section([iset])
        # Should end with the metadata bytes, not trailing
        assert not raw.endswith(b'\x00' * 39)

    def test_roundtrip_with_trailing(self):
        """build_iden_section with trailing -> parse -> extract trailing = same."""
        elem = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                           base_freq_hz=851006250, tx_offset=0, iden_type=0)
        iset = IdenDataSet(name="RTTEST", elements=[elem])
        trailing = b'\xde\xad\xbe\xef' * 10

        raw = build_iden_section([iset], trailing_data=trailing)
        recovered = extract_iden_trailing_data(raw, 16)
        assert recovered == trailing
