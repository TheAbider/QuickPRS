"""Tests for reorder functions in quickprs.injector.

Covers reorder_talkgroup, reorder_conv_channel, reorder_trunk_channel,
including boundary conditions, no-op, invalid index, and roundtrip.
"""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs, parse_prs_bytes
from conftest import cached_parse_prs
from quickprs.injector import (
    reorder_talkgroup, reorder_conv_channel, reorder_trunk_channel,
    add_talkgroups, make_p25_group, make_trunk_set, make_trunk_channel,
    add_trunk_set, add_conv_set, make_conv_set, make_conv_channel,
    _get_first_count,
)
from quickprs.record_types import (
    parse_class_header, parse_group_section,
    parse_conv_channel_section, parse_trunk_channel_section,
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


def _get_trunk_sets(prs):
    """Parse all trunk sets from a PRSFile."""
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not ch_sec or not set_sec:
        return []
    _, _, _, ts_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ts_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_trunk_channel_section(ch_sec.raw, ch_data,
                                        len(ch_sec.raw), first_count)


def _ensure_multi_tg(prs, set_name, min_count=6):
    """Ensure a group set has at least min_count talkgroups."""
    sets = _get_group_sets(prs)
    target = next((s for s in sets if s.name == set_name), None)
    if not target:
        return
    current = len(target.groups)
    if current >= min_count:
        return
    new_groups = []
    for i in range(min_count - current):
        gid = 9900 + i
        new_groups.append(make_p25_group(gid, f"TEST{i:02d}"))
    add_talkgroups(prs, set_name, new_groups)


# ─── reorder_talkgroup ───────────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestReorderTalkgroup:
    """Tests for reorder_talkgroup."""

    def test_move_first_to_last(self):
        """Move talkgroup from position 0 to last position."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 6)

        sets = _get_group_sets(prs)
        n = len(sets[0].groups)
        first_id = sets[0].groups[0].group_id

        result = reorder_talkgroup(prs, set_name, 0, n - 1)
        assert result is True

        sets_after = _get_group_sets(prs)
        assert sets_after[0].groups[-1].group_id == first_id

    def test_move_last_to_first(self):
        """Move talkgroup from last position to 0."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 6)

        sets = _get_group_sets(prs)
        n = len(sets[0].groups)
        last_id = sets[0].groups[-1].group_id

        result = reorder_talkgroup(prs, set_name, n - 1, 0)
        assert result is True

        sets_after = _get_group_sets(prs)
        assert sets_after[0].groups[0].group_id == last_id

    def test_same_position_noop(self):
        """Move to same position is a no-op."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name

        original_bytes = prs.to_bytes()
        result = reorder_talkgroup(prs, set_name, 0, 0)
        assert result is True
        assert prs.to_bytes() == original_bytes

    def test_invalid_old_index(self):
        """Invalid old_index raises IndexError."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        n = len(sets[0].groups)

        with pytest.raises(IndexError):
            reorder_talkgroup(prs, set_name, n + 10, 0)

    def test_invalid_new_index(self):
        """Invalid new_index raises IndexError."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        n = len(sets[0].groups)

        with pytest.raises(IndexError):
            reorder_talkgroup(prs, set_name, 0, n + 10)

    def test_negative_index(self):
        """Negative index raises IndexError."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name

        with pytest.raises(IndexError):
            reorder_talkgroup(prs, set_name, -1, 0)

    def test_set_not_found(self):
        """Returns False for nonexistent set."""
        prs = cached_parse_prs(CLAUDE)
        result = reorder_talkgroup(prs, "NOPE_SET", 0, 1)
        assert result is False

    def test_preserves_all_groups(self):
        """All talkgroups survive the reorder."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 6)

        sets = _get_group_sets(prs)
        ids_before = [g.group_id for g in sets[0].groups]

        reorder_talkgroup(prs, set_name, 0, 3)

        sets_after = _get_group_sets(prs)
        ids_after = [g.group_id for g in sets_after[0].groups]
        assert sorted(ids_before) == sorted(ids_after)

    def test_roundtrip_after_reorder(self):
        """File roundtrips cleanly after reorder."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 3)

        reorder_talkgroup(prs, set_name, 0, 1)

        # Re-parse from bytes to verify roundtrip
        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        sets2 = _get_group_sets(prs2)
        assert len(sets2) == len(_get_group_sets(prs))

    def test_validates_after_reorder(self):
        """Reordered file should pass validation."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 3)

        reorder_talkgroup(prs, set_name, 0, 1)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0


# ─── reorder_trunk_channel ───────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestReorderTrunkChannel:
    """Tests for reorder_trunk_channel."""

    def test_move_channel_down(self):
        """Move trunk channel from position 0 to position 5."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets or len(sets[0].channels) < 6:
            pytest.skip("Need at least 6 trunk channels")
        set_name = sets[0].name
        first_freq = sets[0].channels[0].tx_freq

        result = reorder_trunk_channel(prs, set_name, 0, 5)
        assert result is True

        sets_after = _get_trunk_sets(prs)
        assert sets_after[0].channels[5].tx_freq == first_freq

    def test_move_channel_up(self):
        """Move trunk channel from position 5 to position 0."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets or len(sets[0].channels) < 6:
            pytest.skip("Need at least 6 trunk channels")
        set_name = sets[0].name
        fifth_freq = sets[0].channels[5].tx_freq

        result = reorder_trunk_channel(prs, set_name, 5, 0)
        assert result is True

        sets_after = _get_trunk_sets(prs)
        assert sets_after[0].channels[0].tx_freq == fifth_freq

    def test_same_position_noop(self):
        """Same position is a no-op."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets:
            pytest.skip("No trunk sets")
        set_name = sets[0].name

        original_bytes = prs.to_bytes()
        result = reorder_trunk_channel(prs, set_name, 0, 0)
        assert result is True
        assert prs.to_bytes() == original_bytes

    def test_invalid_index(self):
        """Out-of-range index raises IndexError."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets:
            pytest.skip("No trunk sets")
        set_name = sets[0].name
        n = len(sets[0].channels)

        with pytest.raises(IndexError):
            reorder_trunk_channel(prs, set_name, n + 5, 0)

    def test_set_not_found(self):
        """Returns False for nonexistent set."""
        prs = cached_parse_prs(CLAUDE)
        result = reorder_trunk_channel(prs, "NOPE_SET", 0, 1)
        assert result is False

    def test_preserves_all_channels(self):
        """All channels survive the reorder."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets or len(sets[0].channels) < 3:
            pytest.skip("Need at least 3 trunk channels")
        set_name = sets[0].name
        freqs_before = [ch.tx_freq for ch in sets[0].channels]

        reorder_trunk_channel(prs, set_name, 0, 2)

        sets_after = _get_trunk_sets(prs)
        freqs_after = [ch.tx_freq for ch in sets_after[0].channels]
        assert sorted(freqs_before) == sorted(freqs_after)

    def test_roundtrip_after_reorder(self):
        """File roundtrips cleanly after trunk channel reorder."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_trunk_sets(prs)
        if not sets or len(sets[0].channels) < 2:
            pytest.skip("Need at least 2 trunk channels")
        set_name = sets[0].name

        reorder_trunk_channel(prs, set_name, 0, 1)

        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        sets2 = _get_trunk_sets(prs2)
        assert len(sets2[0].channels) == len(sets[0].channels)


# ─── reorder_conv_channel ────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestReorderConvChannel:
    """Tests for reorder_conv_channel."""

    def _ensure_conv_set(self):
        """Return (prs, set_name) with a conv set with channels."""
        prs = cached_parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if sets and len(sets[0].channels) >= 2:
            return prs, sets[0].name
        # PAWS has conv sets, CLAUDE might not — try both
        prs = cached_parse_prs(CLAUDE)
        sets = _get_conv_sets(prs)
        if sets and len(sets[0].channels) >= 2:
            return prs, sets[0].name
        # Create one
        prs = cached_parse_prs(PAWS)
        channels_data = [
            {"short_name": "CH1", "tx_freq": 151.82000, "rx_freq": 151.82000},
            {"short_name": "CH2", "tx_freq": 151.88000, "rx_freq": 151.88000},
            {"short_name": "CH3", "tx_freq": 154.57000, "rx_freq": 154.57000},
            {"short_name": "CH4", "tx_freq": 154.60000, "rx_freq": 154.60000},
        ]
        cset = make_conv_set("TESTCNV", channels_data)
        add_conv_set(prs, cset)
        return prs, "TESTCNV"

    def test_move_channel_down(self):
        """Move conv channel from position 0 to position 1."""
        prs, set_name = self._ensure_conv_set()
        sets = _get_conv_sets(prs)
        target = next(s for s in sets if s.name == set_name)
        first_name = target.channels[0].short_name

        result = reorder_conv_channel(prs, set_name, 0, 1)
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_after = next(s for s in sets_after if s.name == set_name)
        assert target_after.channels[1].short_name == first_name

    def test_move_channel_up(self):
        """Move conv channel from last position to 0."""
        prs, set_name = self._ensure_conv_set()
        sets = _get_conv_sets(prs)
        target = next(s for s in sets if s.name == set_name)
        n = len(target.channels)
        last_name = target.channels[-1].short_name

        result = reorder_conv_channel(prs, set_name, n - 1, 0)
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_after = next(s for s in sets_after if s.name == set_name)
        assert target_after.channels[0].short_name == last_name

    def test_same_position_noop(self):
        """Same position is a no-op."""
        prs, set_name = self._ensure_conv_set()
        original_bytes = prs.to_bytes()

        result = reorder_conv_channel(prs, set_name, 0, 0)
        assert result is True
        assert prs.to_bytes() == original_bytes

    def test_invalid_index(self):
        """Out-of-range index raises IndexError."""
        prs, set_name = self._ensure_conv_set()
        with pytest.raises(IndexError):
            reorder_conv_channel(prs, set_name, 100, 0)

    def test_set_not_found(self):
        """Returns False for nonexistent set."""
        prs, _ = self._ensure_conv_set()
        result = reorder_conv_channel(prs, "NOPE_SET", 0, 1)
        assert result is False

    def test_preserves_all_channels(self):
        """All channels survive the reorder."""
        prs, set_name = self._ensure_conv_set()
        sets = _get_conv_sets(prs)
        target = next(s for s in sets if s.name == set_name)
        names_before = [ch.short_name for ch in target.channels]

        reorder_conv_channel(prs, set_name, 0, 1)

        sets_after = _get_conv_sets(prs)
        target_after = next(s for s in sets_after if s.name == set_name)
        names_after = [ch.short_name for ch in target_after.channels]
        assert sorted(names_before) == sorted(names_after)

    def test_roundtrip_after_reorder(self):
        """File roundtrips cleanly after conv channel reorder."""
        prs, set_name = self._ensure_conv_set()

        reorder_conv_channel(prs, set_name, 0, 1)

        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        sets2 = _get_conv_sets(prs2)
        target2 = next(s for s in sets2 if s.name == set_name)
        sets_orig = _get_conv_sets(prs)
        target_orig = next(s for s in sets_orig if s.name == set_name)
        assert len(target2.channels) == len(target_orig.channels)

    def test_validates_after_reorder(self):
        """Reordered file should pass validation."""
        prs, set_name = self._ensure_conv_set()

        reorder_conv_channel(prs, set_name, 0, 1)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0


# ─── Cross-type edge cases ──────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestReorderEdgeCases:
    """Edge cases and mixed scenarios."""

    def test_no_trunk_sections_returns_false(self):
        """reorder_trunk_channel on file with no trunk sections."""
        prs = cached_parse_prs(CLAUDE)
        # Remove trunk sections for test
        if not prs.get_section_by_class("CTrunkChannel"):
            result = reorder_trunk_channel(prs, "TEST", 0, 1)
            assert result is False
        else:
            # File has trunk, test with wrong name
            result = reorder_trunk_channel(prs, "NONEXIST", 0, 1)
            assert result is False

    def test_no_conv_sections_returns_false(self):
        """reorder_conv_channel on file with no conv sections."""
        prs = cached_parse_prs(CLAUDE)
        if not prs.get_section_by_class("CConvChannel"):
            result = reorder_conv_channel(prs, "TEST", 0, 1)
            assert result is False
        else:
            result = reorder_conv_channel(prs, "NONEXIST", 0, 1)
            assert result is False

    def test_no_group_sections_returns_false(self):
        """reorder_talkgroup on file with no group sections."""
        prs = cached_parse_prs(CLAUDE)
        if not prs.get_section_by_class("CP25Group"):
            result = reorder_talkgroup(prs, "TEST", 0, 1)
            assert result is False
        else:
            result = reorder_talkgroup(prs, "NONEXIST", 0, 1)
            assert result is False

    def test_multiple_reorders(self):
        """Multiple sequential reorders produce correct result."""
        prs = cached_parse_prs(CLAUDE)
        sets = _get_group_sets(prs)
        set_name = sets[0].name
        _ensure_multi_tg(prs, set_name, 5)

        sets = _get_group_sets(prs)
        ids = [g.group_id for g in sets[0].groups]

        # Move [0] to [2], then [1] to [3]
        reorder_talkgroup(prs, set_name, 0, 2)
        reorder_talkgroup(prs, set_name, 1, 3)

        sets_after = _get_group_sets(prs)
        ids_after = [g.group_id for g in sets_after[0].groups]
        # All IDs preserved
        assert sorted(ids) == sorted(ids_after)
        # Count unchanged
        assert len(ids) == len(ids_after)
