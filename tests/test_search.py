"""Tests for cross-file search module."""

import pytest
from pathlib import Path

from quickprs.search import (
    search_freq,
    search_talkgroup,
    search_name,
    format_search_results,
)
from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
ALL_PRS = [str(PAWS), str(CLAUDE)]


# ─── search_freq ──────────────────────────────────────────────────────


class TestSearchFreq:
    """Test frequency search across files."""

    def test_returns_list(self):
        results = search_freq(ALL_PRS, 999.999)
        assert isinstance(results, list)

    def test_no_match_returns_empty(self):
        results = search_freq(ALL_PRS, 999.999)
        assert len(results) == 0

    def test_result_has_required_keys(self):
        """If there are results, each should have the right keys."""
        # Use a frequency we know might exist — try several
        results = search_freq(ALL_PRS, 851.0125, tolerance=50.0)
        if results:
            r = results[0]
            assert 'file' in r
            assert 'filepath' in r
            assert 'set_type' in r
            assert 'set_name' in r
            assert 'freq' in r
            assert 'channel_name' in r

    def test_tolerance_default(self):
        """Default tolerance should be 0.001 MHz (1 kHz)."""
        results_tight = search_freq(ALL_PRS, 851.0125, tolerance=0.0001)
        results_loose = search_freq(ALL_PRS, 851.0125, tolerance=10.0)
        assert len(results_tight) <= len(results_loose)

    def test_nonexistent_file_skipped(self):
        """Non-existent files should be silently skipped."""
        files = ["/nonexistent/file.PRS"] + ALL_PRS
        results = search_freq(files, 999.999)
        assert isinstance(results, list)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_search_single_file(self):
        results = search_freq([str(PAWS)], 999.999)
        assert isinstance(results, list)

    def test_search_empty_file_list(self):
        results = search_freq([], 851.0125)
        assert results == []


class TestSearchFreqReal:
    """Test frequency search against actual PRS data."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_find_known_freq_in_paws(self):
        """Search for a frequency that exists in PAWS test file."""
        # Parse first to find a real frequency
        prs = cached_parse_prs(PAWS)
        from quickprs.record_types import (
            parse_trunk_channel_section, parse_conv_channel_section,
            parse_sets_from_sections,
        )

        # Try trunk frequencies
        data_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if data_sec and set_sec:
            sets = parse_sets_from_sections(
                set_sec.raw, data_sec.raw, parse_trunk_channel_section)
            if sets and sets[0].channels:
                target = sets[0].channels[0].tx_freq
                results = search_freq([str(PAWS)], target)
                assert len(results) > 0
                assert results[0]['freq'] == pytest.approx(target, abs=0.001)
                return

        # Try conv frequencies
        data_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        if data_sec and set_sec:
            sets = parse_sets_from_sections(
                set_sec.raw, data_sec.raw, parse_conv_channel_section)
            if sets and sets[0].channels:
                target = sets[0].channels[0].tx_freq
                results = search_freq([str(PAWS)], target)
                assert len(results) > 0

    def test_search_across_both_files(self):
        """Searching two files should not crash."""
        results = search_freq(ALL_PRS, 462.5625, tolerance=0.01)
        assert isinstance(results, list)


# ─── search_talkgroup ─────────────────────────────────────────────────


class TestSearchTalkgroup:
    """Test talkgroup ID search."""

    def test_returns_list(self):
        results = search_talkgroup(ALL_PRS, 99999)
        assert isinstance(results, list)

    def test_no_match_returns_empty(self):
        results = search_talkgroup(ALL_PRS, 99999)
        assert len(results) == 0

    def test_result_has_required_keys(self):
        # Search for a TG that might exist
        results = search_talkgroup(ALL_PRS, 1)
        if results:
            r = results[0]
            assert 'file' in r
            assert 'filepath' in r
            assert 'set_name' in r
            assert 'group_id' in r
            assert 'short_name' in r
            assert 'long_name' in r

    def test_nonexistent_file_skipped(self):
        files = ["/nonexistent/file.PRS"] + ALL_PRS
        results = search_talkgroup(files, 99999)
        assert isinstance(results, list)

    def test_search_empty_file_list(self):
        results = search_talkgroup([], 1000)
        assert results == []


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestSearchTalkgroupReal:
    """Test talkgroup search against actual PRS data."""

    def test_find_known_tg_in_file(self):
        """Search for a talkgroup that actually exists."""
        from quickprs.record_types import (
            parse_group_section, parse_sets_from_sections,
        )

        for fp in ALL_PRS:
            prs = parse_prs(fp)
            data_sec = prs.get_section_by_class("CP25Group")
            set_sec = prs.get_section_by_class("CP25GroupSet")
            if not data_sec or not set_sec:
                continue
            sets = parse_sets_from_sections(
                set_sec.raw, data_sec.raw, parse_group_section)
            if sets and sets[0].groups:
                target_id = sets[0].groups[0].group_id
                results = search_talkgroup([fp], target_id)
                assert len(results) > 0
                assert results[0]['group_id'] == target_id
                return

        pytest.skip("No talkgroups in test files")


# ─── search_name ──────────────────────────────────────────────────────


class TestSearchName:
    """Test name/string search."""

    def test_returns_list(self):
        results = search_name(ALL_PRS, "ZZZZNONEXISTENT")
        assert isinstance(results, list)

    def test_no_match_returns_empty(self):
        results = search_name(ALL_PRS, "ZZZZNONEXISTENT")
        assert len(results) == 0

    def test_result_has_required_keys(self):
        # Search for something likely to match
        results = search_name(ALL_PRS, "A")
        if results:
            r = results[0]
            assert 'file' in r
            assert 'filepath' in r
            assert 'match_type' in r
            assert 'set_name' in r
            assert 'name' in r
            assert 'detail' in r

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_case_insensitive(self):
        r_upper = search_name(ALL_PRS, "PAWS")
        r_lower = search_name(ALL_PRS, "paws")
        assert len(r_upper) == len(r_lower)

    def test_nonexistent_file_skipped(self):
        files = ["/nonexistent/file.PRS"] + ALL_PRS
        results = search_name(files, "ZZZZZ")
        assert isinstance(results, list)

    def test_search_empty_file_list(self):
        results = search_name([], "test")
        assert results == []

    def test_match_types_are_valid(self):
        """match_type should be one of the expected values."""
        results = search_name(ALL_PRS, "A")
        valid_types = {'system', 'trunk_set', 'group_set', 'conv_set',
                       'talkgroup', 'channel'}
        for r in results:
            assert r['match_type'] in valid_types, \
                f"Unexpected match_type: {r['match_type']}"


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestSearchNameReal:
    """Test name search against actual PRS data."""

    def test_find_paws_system(self):
        """PAWS file should match its system name."""
        # Check what systems exist in the file
        prs = cached_parse_prs(PAWS)
        from quickprs.record_types import parse_system_short_name
        for cls in ('CP25TrkSystem', 'CConvSystem', 'CP25ConvSystem'):
            for sec in prs.get_sections_by_class(cls):
                sn = parse_system_short_name(sec.raw)
                if sn:
                    results = search_name([str(PAWS)], sn)
                    assert len(results) > 0
                    return

        pytest.skip("No systems in test file")

    def test_partial_name_match(self):
        """Partial name matches should work."""
        prs = cached_parse_prs(PAWS)
        from quickprs.record_types import parse_system_short_name
        for cls in ('CP25TrkSystem', 'CConvSystem'):
            for sec in prs.get_sections_by_class(cls):
                sn = parse_system_short_name(sec.raw)
                if sn and len(sn) > 2:
                    # Search for first 2 chars
                    results = search_name([str(PAWS)], sn[:2])
                    assert len(results) > 0
                    return

        pytest.skip("No systems with names > 2 chars")


# ─── format_search_results ───────────────────────────────────────────


class TestFormatSearchResults:
    """Test result formatting."""

    def test_format_empty_freq(self):
        lines = format_search_results([], 'freq')
        assert any("No matches" in line for line in lines)

    def test_format_empty_tg(self):
        lines = format_search_results([], 'tg')
        assert any("No matches" in line for line in lines)

    def test_format_empty_name(self):
        lines = format_search_results([], 'name')
        assert any("No matches" in line for line in lines)

    def test_format_freq_results(self):
        results = [{
            'file': 'test.PRS',
            'filepath': '/path/test.PRS',
            'set_type': 'trunk',
            'set_name': 'PSERN',
            'freq': 851.0125,
            'channel_name': '',
        }]
        lines = format_search_results(results, 'freq')
        assert any("851.0125" in line for line in lines)
        assert any("PSERN" in line for line in lines)

    def test_format_tg_results(self):
        results = [{
            'file': 'test.PRS',
            'filepath': '/path/test.PRS',
            'set_name': 'PD',
            'group_id': 1000,
            'short_name': 'PD DISP',
            'long_name': 'PD DISPATCH',
        }]
        lines = format_search_results(results, 'tg')
        assert any("1000" in line for line in lines)
        assert any("PD DISP" in line for line in lines)

    def test_format_name_results(self):
        results = [{
            'file': 'test.PRS',
            'filepath': '/path/test.PRS',
            'match_type': 'system',
            'set_name': '',
            'name': 'PSERN',
            'detail': 'P25 Trunked',
        }]
        lines = format_search_results(results, 'name')
        assert any("PSERN" in line for line in lines)
        assert any("system" in line for line in lines)

    def test_format_freq_with_channel_name(self):
        results = [{
            'file': 'test.PRS',
            'filepath': '/path/test.PRS',
            'set_type': 'conv',
            'set_name': 'MURS',
            'freq': 151.82,
            'channel_name': 'MURS 1',
        }]
        lines = format_search_results(results, 'freq')
        assert any("MURS 1" in line for line in lines)

    def test_format_count_header(self):
        results = [
            {'file': 'a.PRS', 'filepath': '/a.PRS', 'set_type': 'trunk',
             'set_name': 'T1', 'freq': 851.0, 'channel_name': ''},
            {'file': 'b.PRS', 'filepath': '/b.PRS', 'set_type': 'trunk',
             'set_name': 'T2', 'freq': 851.0, 'channel_name': ''},
        ]
        lines = format_search_results(results, 'freq')
        assert any("2 match" in line for line in lines)
