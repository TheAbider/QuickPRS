"""Tests for duplicate detection and cleanup module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from quickprs.cleanup import (
    find_duplicates,
    remove_duplicates,
    find_unused_sets,
    format_duplicates_report,
    format_unused_report,
    cleanup_report,
)
from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── find_duplicates ──────────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestFindDuplicates:
    """Test duplicate detection across set types."""

    def test_find_duplicates_returns_dict(self):
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert isinstance(result, dict)
        assert 'duplicate_tgs' in result
        assert 'duplicate_freqs' in result
        assert 'duplicate_channels' in result
        assert 'cross_set_tgs' in result

    def test_duplicate_tgs_list_type(self):
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert isinstance(result['duplicate_tgs'], list)

    def test_duplicate_freqs_list_type(self):
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert isinstance(result['duplicate_freqs'], list)

    def test_duplicate_channels_list_type(self):
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert isinstance(result['duplicate_channels'], list)

    def test_cross_set_tgs_list_type(self):
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert isinstance(result['cross_set_tgs'], list)

    def test_no_crash_on_paws(self):
        """Ensure duplicate detection doesn't crash on real files."""
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        assert result is not None

    def test_no_crash_on_claude(self):
        """Ensure duplicate detection works on multi-system files."""
        prs = cached_parse_prs(CLAUDE)
        result = find_duplicates(prs)
        assert result is not None

    def test_duplicate_tg_tuple_shape(self):
        """Each duplicate_tg entry should be (set_name, group_id, count)."""
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        for entry in result['duplicate_tgs']:
            assert len(entry) == 3
            assert isinstance(entry[0], str)   # set_name
            assert isinstance(entry[1], int)    # group_id
            assert isinstance(entry[2], int)    # count
            assert entry[2] > 1                 # must be > 1 to be a dupe

    def test_duplicate_freq_tuple_shape(self):
        """Each duplicate_freq entry should be (set_name, freq, count)."""
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        for entry in result['duplicate_freqs']:
            assert len(entry) == 3
            assert isinstance(entry[0], str)    # set_name
            assert isinstance(entry[1], float)  # freq
            assert isinstance(entry[2], int)    # count
            assert entry[2] > 1

    def test_duplicate_channel_tuple_shape(self):
        """Each duplicate_channel entry should be (set_name, name, count)."""
        prs = cached_parse_prs(PAWS)
        result = find_duplicates(prs)
        for entry in result['duplicate_channels']:
            assert len(entry) == 3
            assert isinstance(entry[0], str)  # set_name
            assert isinstance(entry[1], str)  # short_name
            assert isinstance(entry[2], int)  # count
            assert entry[2] > 1

    def test_cross_set_tg_tuple_shape(self):
        """Each cross_set entry should be (group_id, [set_names])."""
        prs = cached_parse_prs(CLAUDE)
        result = find_duplicates(prs)
        for entry in result['cross_set_tgs']:
            assert len(entry) == 2
            assert isinstance(entry[0], int)    # group_id
            assert isinstance(entry[1], list)   # set_names
            assert len(entry[1]) > 1            # must be in >1 sets

    def test_cross_set_tgs_contain_set_names(self):
        """Cross-set TG entries should have string set names."""
        prs = cached_parse_prs(CLAUDE)
        result = find_duplicates(prs)
        for gid, set_names in result['cross_set_tgs']:
            for name in set_names:
                assert isinstance(name, str)
                assert len(name) > 0


# ─── remove_duplicates ────────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRemoveDuplicates:
    """Test duplicate removal counting."""

    def test_remove_returns_dict(self):
        prs = cached_parse_prs(PAWS)
        result = remove_duplicates(prs)
        assert isinstance(result, dict)
        assert 'tgs_removed' in result
        assert 'freqs_removed' in result
        assert 'channels_removed' in result

    def test_remove_counts_nonnegative(self):
        prs = cached_parse_prs(PAWS)
        result = remove_duplicates(prs)
        assert result['tgs_removed'] >= 0
        assert result['freqs_removed'] >= 0
        assert result['channels_removed'] >= 0

    def test_remove_keep_first(self):
        prs = cached_parse_prs(PAWS)
        result = remove_duplicates(prs, keep='first')
        assert isinstance(result, dict)

    def test_remove_keep_last(self):
        prs = cached_parse_prs(PAWS)
        result = remove_duplicates(prs, keep='last')
        assert isinstance(result, dict)

    def test_remove_consistent_with_find(self):
        """Remove counts should match find counts minus 1 per duplicate."""
        prs = cached_parse_prs(PAWS)
        dupes = find_duplicates(prs)
        counts = remove_duplicates(prs)

        expected_tgs = sum(c - 1 for _, _, c in dupes['duplicate_tgs'])
        expected_freqs = sum(c - 1 for _, _, c in dupes['duplicate_freqs'])
        expected_ch = sum(c - 1 for _, _, c in dupes['duplicate_channels'])

        assert counts['tgs_removed'] == expected_tgs
        assert counts['freqs_removed'] == expected_freqs
        assert counts['channels_removed'] == expected_ch


# ─── find_unused_sets ─────────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestFindUnusedSets:
    """Test unused set detection."""

    def test_returns_dict(self):
        prs = cached_parse_prs(PAWS)
        result = find_unused_sets(prs)
        assert isinstance(result, dict)
        assert 'trunk_sets' in result
        assert 'group_sets' in result
        assert 'conv_sets' in result
        assert 'iden_sets' in result

    def test_values_are_lists(self):
        prs = cached_parse_prs(PAWS)
        result = find_unused_sets(prs)
        for key in ('trunk_sets', 'group_sets', 'conv_sets', 'iden_sets'):
            assert isinstance(result[key], list)

    def test_unused_set_names_are_strings(self):
        prs = cached_parse_prs(PAWS)
        result = find_unused_sets(prs)
        for key in ('trunk_sets', 'group_sets', 'conv_sets', 'iden_sets'):
            for name in result[key]:
                assert isinstance(name, str)

    def test_no_crash_on_real_files(self):
        prs = cached_parse_prs(CLAUDE)
        result = find_unused_sets(prs)
        assert result is not None

    def test_no_crash_on_paws(self):
        prs = cached_parse_prs(PAWS)
        result = find_unused_sets(prs)
        assert result is not None


# ─── format functions ─────────────────────────────────────────────────


class TestFormatFunctions:
    """Test report formatting."""

    def test_format_duplicates_report_no_dupes(self):
        dupes = {
            'duplicate_tgs': [],
            'duplicate_freqs': [],
            'duplicate_channels': [],
            'cross_set_tgs': [],
        }
        lines = format_duplicates_report(dupes)
        assert any("No duplicates" in line for line in lines)

    def test_format_duplicates_report_with_tg_dupes(self):
        dupes = {
            'duplicate_tgs': [("SET1", 1000, 2)],
            'duplicate_freqs': [],
            'duplicate_channels': [],
            'cross_set_tgs': [],
        }
        lines = format_duplicates_report(dupes)
        assert any("TG 1000" in line for line in lines)
        assert any("SET1" in line for line in lines)

    def test_format_duplicates_report_with_freq_dupes(self):
        dupes = {
            'duplicate_tgs': [],
            'duplicate_freqs': [("TRUNK1", 851.0125, 3)],
            'duplicate_channels': [],
            'cross_set_tgs': [],
        }
        lines = format_duplicates_report(dupes)
        assert any("851.0125" in line for line in lines)

    def test_format_duplicates_report_with_channel_dupes(self):
        dupes = {
            'duplicate_tgs': [],
            'duplicate_freqs': [],
            'duplicate_channels': [("MURS", "MURS 1", 2)],
            'cross_set_tgs': [],
        }
        lines = format_duplicates_report(dupes)
        assert any("MURS 1" in line for line in lines)

    def test_format_duplicates_report_with_cross_set(self):
        dupes = {
            'duplicate_tgs': [],
            'duplicate_freqs': [],
            'duplicate_channels': [],
            'cross_set_tgs': [(1000, ["SET1", "SET2"])],
        }
        lines = format_duplicates_report(dupes)
        assert any("TG 1000" in line for line in lines)
        assert any("SET1" in line for line in lines)
        assert any("SET2" in line for line in lines)

    def test_format_unused_report_no_unused(self):
        unused = {
            'trunk_sets': [],
            'group_sets': [],
            'conv_sets': [],
            'iden_sets': [],
        }
        lines = format_unused_report(unused)
        assert any("No unused" in line for line in lines)

    def test_format_unused_report_with_unused(self):
        unused = {
            'trunk_sets': ["OLD_TRK"],
            'group_sets': [],
            'conv_sets': ["ORPHAN"],
            'iden_sets': [],
        }
        lines = format_unused_report(unused)
        assert any("OLD_TRK" in line for line in lines)
        assert any("ORPHAN" in line for line in lines)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cleanup_report_returns_lines(self):
        prs = cached_parse_prs(PAWS)
        lines = cleanup_report(prs)
        assert isinstance(lines, list)
        assert len(lines) > 0
        assert any("Cleanup Report" in line for line in lines)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cleanup_report_has_summary(self):
        prs = cached_parse_prs(PAWS)
        lines = cleanup_report(prs)
        assert any("Summary:" in line for line in lines)


# ─── Edge cases ───────────────────────────────────────────────────────


class TestCleanupEdgeCases:
    """Test edge cases in cleanup module."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_empty_prs_no_crash(self):
        """File with no data sets should return empty results."""
        prs = cached_parse_prs(PAWS)
        # Force a minimal PRS with no data sections
        mock_prs = MagicMock()
        mock_prs.get_section_by_class.return_value = None
        mock_prs.get_sections_by_class.return_value = []
        mock_prs.sections = []

        result = find_duplicates(mock_prs)
        assert result['duplicate_tgs'] == []
        assert result['duplicate_freqs'] == []
        assert result['duplicate_channels'] == []
        assert result['cross_set_tgs'] == []

    def test_empty_prs_unused_sets(self):
        """File with no systems should have no unused sets."""
        mock_prs = MagicMock()
        mock_prs.get_section_by_class.return_value = None
        mock_prs.get_sections_by_class.return_value = []
        mock_prs.sections = []

        result = find_unused_sets(mock_prs)
        for key in ('trunk_sets', 'group_sets', 'conv_sets', 'iden_sets'):
            assert result[key] == []

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_cleanup_report_both_files(self):
        """Full report should work on both test files."""
        for fp in (PAWS, CLAUDE):
            prs = parse_prs(fp)
            lines = cleanup_report(prs)
            assert len(lines) > 0
