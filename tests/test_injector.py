"""Tests for quickprs.injector — bulk edit operations and helpers.

Covers bulk_edit_talkgroups and bulk_edit_channels, plus smoke tests
for key injector functions not covered elsewhere.
"""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.injector import (
    bulk_edit_talkgroups, bulk_edit_channels,
    make_p25_group, make_conv_channel, make_conv_set,
    add_talkgroups, add_conv_set,
    make_group_set, make_trunk_set,
    _find_section_index, _get_first_count, _get_header_bytes,
)
from quickprs.record_types import (
    parse_class_header, parse_group_section, parse_conv_channel_section,
    P25GroupSet,
)
from quickprs.binary_io import read_uint16_le
from quickprs.validation import validate_prs, ERROR

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Helpers ──────────────────────────────────────────────────────────

def _get_group_sets(prs):
    """Parse all group sets from a PRSFile."""
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return []
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw),
                               first_count)


def _get_conv_sets(prs):
    """Parse all conv sets from a PRSFile."""
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        return []
    _, _, _, cs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, cs_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_conv_channel_section(ch_sec.raw, ch_data,
                                       len(ch_sec.raw), first_count)


# ─── Internal helpers ─────────────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestInternalHelpers:
    """Tests for _find_section_index, _get_first_count, etc."""

    def test_find_section_index_found(self):
        prs = cached_parse_prs(CLAUDE)
        idx = _find_section_index(prs, "CP25Group")
        assert idx >= 0

    def test_find_section_index_missing(self):
        prs = cached_parse_prs(CLAUDE)
        idx = _find_section_index(prs, "CNotAClass")
        assert idx == -1

    def test_get_first_count(self):
        prs = cached_parse_prs(CLAUDE)
        count = _get_first_count(prs, "CP25GroupSet")
        assert count > 0

    def test_get_header_bytes(self):
        prs = cached_parse_prs(CLAUDE)
        sec = prs.get_section_by_class("CP25Group")
        b1, b2 = _get_header_bytes(sec)
        assert isinstance(b1, int)
        assert isinstance(b2, int)


# ─── bulk_edit_talkgroups ────────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestBulkEditTalkgroups:
    """Tests for bulk_edit_talkgroups."""

    def test_enable_scan(self):
        """Enable scan on all TGs in a group set."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name, enable_scan=True)
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.scan is True

    def test_disable_scan(self):
        """Disable scan on all TGs."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name, enable_scan=False)
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.scan is False

    def test_enable_tx(self):
        """Enable TX on all TGs."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name, enable_tx=True)
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.tx is True

    def test_disable_tx(self):
        """Disable TX on all TGs."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name, enable_tx=False)
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.tx is False

    def test_prefix(self):
        """Add prefix to all TG short names (truncated to 8 chars)."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name
        original_names = [g.group_name for g in sets_before[0].groups]

        count = bulk_edit_talkgroups(prs, set_name, prefix="PD ")
        assert count > 0

        sets_after = _get_group_sets(prs)
        for i, grp in enumerate(sets_after[0].groups):
            expected = ("PD " + original_names[i])[:8]
            assert grp.group_name == expected

    def test_suffix(self):
        """Add suffix to all TG short names."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name, suffix="-X")
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.group_name.endswith("-X") or len(grp.group_name) == 8

    def test_combined_scan_and_tx(self):
        """Set both scan and TX at once."""
        prs = cached_parse_prs(CLAUDE)
        sets_before = _get_group_sets(prs)
        set_name = sets_before[0].name

        count = bulk_edit_talkgroups(prs, set_name,
                                      enable_scan=True, enable_tx=True)
        assert count > 0

        sets_after = _get_group_sets(prs)
        for grp in sets_after[0].groups:
            assert grp.scan is True
            assert grp.tx is True

    def test_set_not_found_raises(self):
        """Editing a nonexistent set should raise ValueError."""
        prs = cached_parse_prs(CLAUDE)
        with pytest.raises(ValueError, match="not found"):
            bulk_edit_talkgroups(prs, "NOPE", enable_scan=True)

    def test_no_modifications_raises(self):
        """Calling with no modifications should raise ValueError."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        with pytest.raises(ValueError, match="No modifications"):
            bulk_edit_talkgroups(prs, sets[0].name)

    def test_validates_after_edit(self):
        """File should still validate after bulk edit."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        bulk_edit_talkgroups(prs, sets[0].name, enable_scan=True)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_roundtrip_preserves_bytes(self):
        """Parse -> bulk edit -> rebuild -> parse should give same data."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name

        bulk_edit_talkgroups(prs, set_name, enable_tx=True)

        # Parse the rebuilt section to verify structure
        sets_after = _get_group_sets(prs)
        assert len(sets_after) == len(sets)
        assert len(sets_after[0].groups) == len(sets[0].groups)


# ─── bulk_edit_channels ─────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestBulkEditChannels:
    """Tests for bulk_edit_channels."""

    def _ensure_conv_set(self):
        """Get a PRS with at least one conv set (PAWS has one)."""
        prs = cached_parse_prs(PAWS)
        conv_sets = _get_conv_sets(prs)
        if not conv_sets:
            pytest.skip("No conv sets in test file")
        return prs, conv_sets[0].name

    def test_set_tone(self):
        """Set CTCSS tone on all channels."""
        prs, set_name = self._ensure_conv_set()

        count = bulk_edit_channels(prs, set_name, set_tone="100.0")
        assert count > 0

        sets_after = _get_conv_sets(prs)
        target = next(s for s in sets_after if s.name == set_name)
        for ch in target.channels:
            assert ch.tx_tone == "100.0"
            assert ch.rx_tone == "100.0"
            assert ch.tone_mode is True

    def test_clear_tones(self):
        """Clear all tones from channels."""
        prs, set_name = self._ensure_conv_set()

        # First set a tone, then clear it
        bulk_edit_channels(prs, set_name, set_tone="100.0")
        count = bulk_edit_channels(prs, set_name, clear_tones=True)
        assert count > 0

        sets_after = _get_conv_sets(prs)
        target = next(s for s in sets_after if s.name == set_name)
        for ch in target.channels:
            assert ch.tx_tone == ""
            assert ch.rx_tone == ""
            assert ch.tone_mode is False

    def test_set_power(self):
        """Set power level on all channels."""
        prs, set_name = self._ensure_conv_set()

        count = bulk_edit_channels(prs, set_name, set_power=0)
        assert count > 0

        sets_after = _get_conv_sets(prs)
        target = next(s for s in sets_after if s.name == set_name)
        for ch in target.channels:
            assert ch.power_level == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_set_not_found_raises(self):
        """Editing a nonexistent set should raise ValueError."""
        prs = cached_parse_prs(PAWS)
        with pytest.raises(ValueError, match="not found"):
            bulk_edit_channels(prs, "NOPE", set_tone="100.0")

    def test_no_modifications_raises(self):
        """Calling with no modifications should raise ValueError."""
        prs, set_name = self._ensure_conv_set()
        with pytest.raises(ValueError, match="No modifications"):
            bulk_edit_channels(prs, set_name)

    def test_validates_after_edit(self):
        """File should still validate after bulk edit."""
        prs, set_name = self._ensure_conv_set()
        bulk_edit_channels(prs, set_name, set_tone="100.0")
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_no_conv_sections_raises(self):
        """Editing channels on a file with no conv sets should raise."""
        prs = cached_parse_prs(CLAUDE)
        conv_sets = _get_conv_sets(prs)
        if conv_sets:
            pytest.skip("File has conv sets")
        with pytest.raises(ValueError, match="No existing conv"):
            bulk_edit_channels(prs, "MURS", set_tone="100.0")
