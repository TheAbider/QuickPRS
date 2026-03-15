"""Tests for advanced editing features: batch rename, channel sort, freq tools.

Tests batch rename with regex, sort by frequency/name/ID,
frequency identification, and conflict detection.
"""

import pytest
from pathlib import Path
from copy import deepcopy

from quickprs.prs_parser import parse_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    parse_class_header, parse_group_section,
    parse_conv_channel_section,
)
from quickprs.injector import (
    batch_rename, sort_channels,
    make_p25_group, make_group_set, add_group_set,
    make_conv_channel, make_conv_set, add_conv_set,
    add_talkgroups,
)
from quickprs.freq_tools import (
    calculate_all_offsets, identify_service, check_frequency_conflicts,
    format_service_id, format_all_offsets, format_conflict_check,
)

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _get_group_sets(prs):
    """Parse all group sets from a PRSFile."""
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw),
                                first_count)


def _get_conv_sets(prs):
    """Parse all conv sets from a PRSFile."""
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    _, _, _, cs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, cs_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_conv_channel_section(ch_sec.raw, ch_data, len(ch_sec.raw),
                                       first_count)


# ─── Batch Rename: Group Sets ────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(),
                    reason="Test PRS data not available")
class TestBatchRenameGroups:
    """Test batch rename on P25 group sets."""

    def test_basic_substitution(self):
        """Simple string replacement in group names."""
        prs = parse_prs(CLAUDE)

        # Add groups to have something to rename
        new_groups = [
            make_p25_group(100, "PD DISP", "PD DISPATCH"),
            make_p25_group(200, "PD TAC1", "PD TACTICAL 1"),
            make_p25_group(300, "FD DISP", "FD DISPATCH"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        # Rename: replace "DISP" with "DSP"
        count = batch_rename(prs, "GROUP SE", "DISP", "DSP",
                              set_type="group")
        assert count == 2  # PD DISP and FD DISP

        sets = _get_group_sets(prs)
        names = [g.group_name for g in sets[0].groups]
        assert "PD DSP" in names
        assert "FD DSP" in names
        assert "PD TAC1" in names  # unmodified

    def test_regex_prefix_removal(self):
        """Remove prefix using regex anchor."""
        prs = parse_prs(CLAUDE)

        new_groups = [
            make_p25_group(100, "PD DISP", "PD DISPATCH"),
            make_p25_group(200, "PD TAC1", "PD TACTICAL 1"),
            make_p25_group(300, "PD ADMIN", "PD ADMIN"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        count = batch_rename(prs, "GROUP SE", r"^PD ", "",
                              set_type="group")
        assert count == 3

        sets = _get_group_sets(prs)
        names = [g.group_name for g in sets[0].groups]
        assert "DISP" in names
        assert "TAC1" in names
        assert "ADMIN" in names

    def test_regex_backreference(self):
        """Regex backreference substitution."""
        prs = parse_prs(CLAUDE)

        new_groups = [
            make_p25_group(100, "ALPHA", "ALPHA"),
            make_p25_group(200, "BRAVO", "BRAVO"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        # Add Z1 prefix via backreference
        count = batch_rename(prs, "GROUP SE", r"^(.+)$", r"Z1 \1",
                              set_type="group")
        # All groups renamed (original "name" + ALPHA + BRAVO)
        assert count == 3

        sets = _get_group_sets(prs)
        names = [g.group_name for g in sets[0].groups]
        # Names are truncated to 8 chars
        assert "Z1 ALPH" in names or "Z1 ALPHA" in names

    def test_no_match_returns_zero(self):
        """Pattern that matches nothing returns 0."""
        prs = parse_prs(CLAUDE)

        count = batch_rename(prs, "GROUP SE", "ZZZZZ", "XXXXX",
                              set_type="group")
        assert count == 0

    def test_long_name_field(self):
        """Rename long_name field instead of short_name."""
        prs = parse_prs(CLAUDE)

        new_groups = [
            make_p25_group(100, "PD DISP", "PD DISPATCH"),
            make_p25_group(200, "PD TAC1", "PD TACTICAL 1"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        count = batch_rename(prs, "GROUP SE", "PD ", "POLICE ",
                              set_type="group", field="long_name")
        assert count == 2

        sets = _get_group_sets(prs)
        long_names = [g.long_name for g in sets[0].groups]
        assert any("POLICE" in n for n in long_names)

    def test_invalid_set_raises(self):
        """Non-existent set name raises ValueError."""
        prs = parse_prs(CLAUDE)

        with pytest.raises(ValueError, match="not found"):
            batch_rename(prs, "NOPE", "a", "b", set_type="group")

    def test_invalid_field_raises(self):
        """Invalid field name raises ValueError."""
        prs = parse_prs(CLAUDE)

        with pytest.raises(ValueError, match="Invalid field"):
            batch_rename(prs, "GROUP SE", "a", "b", set_type="group",
                          field="invalid")

    def test_invalid_set_type_raises(self):
        """Invalid set_type raises ValueError."""
        prs = parse_prs(CLAUDE)

        with pytest.raises(ValueError, match="Invalid set_type"):
            batch_rename(prs, "GROUP SE", "a", "b", set_type="trunk")

    def test_truncates_short_name_to_8(self):
        """Renamed short names are truncated to 8 characters."""
        prs = parse_prs(CLAUDE)

        new_groups = [make_p25_group(100, "AB", "AB")]
        add_talkgroups(prs, "GROUP SE", new_groups)

        count = batch_rename(prs, "GROUP SE", "^AB$", "VERY_LONG_NAME",
                              set_type="group")
        assert count == 1

        sets = _get_group_sets(prs)
        for g in sets[0].groups:
            assert len(g.group_name) <= 8

    def test_truncates_long_name_to_16(self):
        """Renamed long names are truncated to 16 characters."""
        prs = parse_prs(CLAUDE)

        new_groups = [make_p25_group(100, "X", "SHORT")]
        add_talkgroups(prs, "GROUP SE", new_groups)

        count = batch_rename(prs, "GROUP SE", "SHORT",
                              "THIS_IS_A_VERY_LONG_REPLACEMENT_STRING",
                              set_type="group", field="long_name")
        assert count == 1

        sets = _get_group_sets(prs)
        for g in sets[0].groups:
            assert len(g.long_name) <= 16


# ─── Batch Rename: Conv Sets ────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(),
                    reason="Test PRS data not available")
class TestBatchRenameConv:
    """Test batch rename on conventional channel sets."""

    def test_conv_rename_basic(self):
        """Basic rename on conv channels."""
        prs = parse_prs(PAWS)

        sets_before = _get_conv_sets(prs)
        assert len(sets_before) > 0, "No conv sets found in PAWS"

        target_set = sets_before[0].name
        old_names = [ch.short_name for ch in sets_before[0].channels]

        if old_names:
            # Try to rename first character
            first_char = old_names[0][0]
            count = batch_rename(prs, target_set, f"^{first_char}", "X",
                                  set_type="conv")
            # At least one should match (the one we picked)
            assert count >= 1

    def test_conv_rename_no_match(self):
        """No match returns 0 for conv sets."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets:
            pytest.skip("No conv sets in test file")
        count = batch_rename(prs, sets[0].name, "ZZZQQQ", "XXX",
                              set_type="conv")
        assert count == 0

    def test_conv_rename_long_name(self):
        """Rename long_name field on conv channels."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets or not sets[0].channels:
            pytest.skip("No conv channels in test file")

        target = sets[0].name
        # Get a long_name to modify
        first_long = sets[0].channels[0].long_name
        if first_long:
            count = batch_rename(prs, target, ".", "X",
                                  set_type="conv", field="long_name")
            assert count >= 1


# ─── Channel Sorter ──────────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(),
                    reason="Test PRS data not available")
class TestSortGroups:
    """Test sorting talkgroups within a group set."""

    def test_sort_by_id_ascending(self):
        """Sort groups by talkgroup ID ascending."""
        prs = parse_prs(CLAUDE)

        # Add groups in unsorted order
        new_groups = [
            make_p25_group(300, "CHARLIE", "CHARLIE"),
            make_p25_group(100, "ALPHA", "ALPHA"),
            make_p25_group(200, "BRAVO", "BRAVO"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        result = sort_channels(prs, "GROUP SE", set_type="group",
                                key="id")
        assert result is True

        sets = _get_group_sets(prs)
        ids = [g.group_id for g in sets[0].groups]
        assert ids == sorted(ids)

    def test_sort_by_id_descending(self):
        """Sort groups by talkgroup ID descending."""
        prs = parse_prs(CLAUDE)

        new_groups = [
            make_p25_group(100, "ALPHA", "ALPHA"),
            make_p25_group(300, "CHARLIE", "CHARLIE"),
            make_p25_group(200, "BRAVO", "BRAVO"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        result = sort_channels(prs, "GROUP SE", set_type="group",
                                key="id", reverse=True)
        assert result is True

        sets = _get_group_sets(prs)
        ids = [g.group_id for g in sets[0].groups]
        assert ids == sorted(ids, reverse=True)

    def test_sort_by_name(self):
        """Sort groups by short name alphabetically."""
        prs = parse_prs(CLAUDE)

        new_groups = [
            make_p25_group(100, "CHARLIE", "CHARLIE"),
            make_p25_group(200, "ALPHA", "ALPHA"),
            make_p25_group(300, "BRAVO", "BRAVO"),
        ]
        add_talkgroups(prs, "GROUP SE", new_groups)

        result = sort_channels(prs, "GROUP SE", set_type="group",
                                key="name")
        assert result is True

        sets = _get_group_sets(prs)
        names = [g.group_name for g in sets[0].groups]
        assert names == sorted(names)

    def test_sort_nonexistent_set_returns_false(self):
        """Sorting a non-existent set returns False."""
        prs = parse_prs(CLAUDE)
        result = sort_channels(prs, "NOPE", set_type="group", key="id")
        assert result is False

    def test_sort_invalid_key_raises(self):
        """Invalid sort key for group set raises ValueError."""
        prs = parse_prs(CLAUDE)
        with pytest.raises(ValueError, match="Invalid sort key"):
            sort_channels(prs, "GROUP SE", set_type="group",
                           key="frequency")

    def test_sort_invalid_set_type_raises(self):
        """Invalid set_type raises ValueError."""
        prs = parse_prs(CLAUDE)
        with pytest.raises(ValueError, match="Invalid set_type"):
            sort_channels(prs, "GROUP SE", set_type="trunk", key="name")


@pytest.mark.skipif(not PAWS.exists(),
                    reason="Test PRS data not available")
class TestSortConv:
    """Test sorting conventional channels."""

    def test_sort_by_frequency(self):
        """Sort conv channels by TX frequency."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets:
            pytest.skip("No conv sets in test file")

        target = sets[0].name
        result = sort_channels(prs, target, set_type="conv",
                                key="frequency")
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_set = None
        for s in sets_after:
            if s.name == target:
                target_set = s
                break
        assert target_set is not None
        freqs = [ch.tx_freq for ch in target_set.channels]
        assert freqs == sorted(freqs)

    def test_sort_by_name(self):
        """Sort conv channels by short name."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets:
            pytest.skip("No conv sets in test file")

        target = sets[0].name
        result = sort_channels(prs, target, set_type="conv", key="name")
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_set = None
        for s in sets_after:
            if s.name == target:
                target_set = s
                break
        assert target_set is not None
        names = [ch.short_name for ch in target_set.channels]
        assert names == sorted(names)

    def test_sort_by_tone(self):
        """Sort conv channels by CTCSS tone."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets:
            pytest.skip("No conv sets in test file")

        target = sets[0].name
        result = sort_channels(prs, target, set_type="conv", key="tone")
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_set = None
        for s in sets_after:
            if s.name == target:
                target_set = s
                break
        assert target_set is not None
        tones = [ch.tx_tone for ch in target_set.channels]
        assert tones == sorted(tones)

    def test_sort_reverse(self):
        """Sort conv channels by frequency descending."""
        prs = parse_prs(PAWS)
        sets = _get_conv_sets(prs)
        if not sets:
            pytest.skip("No conv sets in test file")

        target = sets[0].name
        result = sort_channels(prs, target, set_type="conv",
                                key="frequency", reverse=True)
        assert result is True

        sets_after = _get_conv_sets(prs)
        target_set = None
        for s in sets_after:
            if s.name == target:
                target_set = s
                break
        assert target_set is not None
        freqs = [ch.tx_freq for ch in target_set.channels]
        assert freqs == sorted(freqs, reverse=True)

    def test_sort_conv_nonexistent(self):
        """Sorting non-existent conv set returns False."""
        prs = parse_prs(PAWS)
        result = sort_channels(prs, "NOPE", set_type="conv",
                                key="frequency")
        assert result is False

    def test_sort_conv_invalid_key(self):
        """Invalid sort key for conv set raises ValueError."""
        prs = parse_prs(PAWS)
        with pytest.raises(ValueError, match="Invalid sort key"):
            sort_channels(prs, "x", set_type="conv", key="id")


# ─── Frequency Identification ────────────────────────────────────


class TestIdentifyService:
    """Test frequency service identification."""

    def test_frs_channel(self):
        """FRS/GMRS frequency should be identified."""
        info = identify_service(462.5625)
        assert "FRS" in info["service"] or "GMRS" in info["service"]
        assert "Channel 1" in info["notes"]

    def test_murs_channel(self):
        """MURS frequency should be identified."""
        info = identify_service(151.820)
        assert info["service"] == "MURS"
        assert "Channel 1" in info["notes"]

    def test_noaa_weather(self):
        """NOAA weather frequency should be identified."""
        info = identify_service(162.400)
        assert "NOAA" in info["service"]

    def test_marine_ch16(self):
        """Marine VHF channel 16 should be identified."""
        info = identify_service(156.800)
        assert "Marine" in info["service"]

    def test_amateur_2m(self):
        """2m amateur frequency identified."""
        info = identify_service(146.520)
        assert info["service"] == "Amateur"
        assert "2m" in info["band"]

    def test_amateur_70cm(self):
        """70cm amateur frequency identified."""
        info = identify_service(446.000)
        assert info["service"] == "Amateur"
        assert "70cm" in info["band"]

    def test_aeronautical(self):
        """Air band frequency identified."""
        info = identify_service(121.500)
        assert "Aeronautical" in info["service"]

    def test_public_safety_vhf(self):
        """VHF public safety frequency identified."""
        info = identify_service(155.475)
        assert "Public Safety" in info["service"]

    def test_800mhz_band(self):
        """800 MHz public safety band identified."""
        info = identify_service(851.0125)
        assert info["band"] == "800 MHz"

    def test_unknown_frequency(self):
        """Out-of-range frequency returns Unknown."""
        info = identify_service(10.0)
        assert info["service"] == "Unknown"

    def test_returns_dict_keys(self):
        """Result has all expected keys."""
        info = identify_service(462.5625)
        for key in ("frequency", "service", "band", "allocation", "notes"):
            assert key in info


# ─── Calculate All Offsets ───────────────────────────────────────


class TestCalculateAllOffsets:
    """Test comprehensive repeater offset calculations."""

    def test_2m_offsets(self):
        """2m frequency should return standard 0.6 MHz offsets."""
        results = calculate_all_offsets(146.940)
        assert len(results) >= 1
        # Should have at least the standard +0.6
        offsets = [r[1] for r in results]
        assert 0.6 in offsets

    def test_70cm_offsets(self):
        """70cm frequency should return 5.0 MHz offsets."""
        results = calculate_all_offsets(442.500)
        offsets = [r[1] for r in results]
        assert 5.0 in offsets

    def test_1_25m_offset(self):
        """1.25m frequency should return -1.6 MHz offset."""
        results = calculate_all_offsets(224.360)
        assert len(results) >= 1
        bands = [r[2] for r in results]
        assert "1.25m" in bands

    def test_gmrs_offset(self):
        """GMRS repeater frequency should return +5.0 MHz offset."""
        results = calculate_all_offsets(462.5625)
        bands = [r[2] for r in results]
        assert "GMRS" in bands

    def test_900_offset(self):
        """900 MHz frequency should return -12.0 MHz offset."""
        results = calculate_all_offsets(927.000)
        offsets = [r[1] for r in results]
        assert 12.0 in offsets

    def test_out_of_band(self):
        """Non-repeater frequency returns empty list."""
        results = calculate_all_offsets(155.000)
        assert results == []

    def test_800mhz_offset(self):
        """800 MHz commercial frequency should return 45.0 MHz offset."""
        results = calculate_all_offsets(851.000)
        offsets = [r[1] for r in results]
        assert 45.0 in offsets

    def test_results_are_tuples(self):
        """Each result should be a 4-tuple."""
        results = calculate_all_offsets(146.940)
        for r in results:
            assert len(r) == 4
            input_freq, offset, band, standard = r
            assert isinstance(input_freq, float)
            assert isinstance(offset, float)
            assert isinstance(band, str)
            assert isinstance(standard, str)


# ─── Frequency Conflict Check ───────────────────────────────────


class TestFrequencyConflicts:
    """Test frequency conflict detection."""

    def test_no_conflicts_with_good_spacing(self):
        """Well-spaced frequencies should produce no spacing warnings."""
        freqs = [462.5625, 462.5875, 462.6125]  # 25 kHz spacing
        warnings = check_frequency_conflicts(freqs)
        # Should have no spacing conflicts (25 kHz is fine)
        spacing_warnings = [w for w in warnings
                            if "spacing" in w.lower()]
        assert len(spacing_warnings) == 0

    def test_too_close_frequencies(self):
        """Frequencies < 12.5 kHz apart should warn."""
        freqs = [462.5625, 462.5635]  # 1 kHz apart
        warnings = check_frequency_conflicts(freqs)
        assert len(warnings) >= 1
        assert any("12.5" in w for w in warnings)

    def test_tight_spacing_warning(self):
        """Frequencies 12.5-25 kHz apart should warn about wideband."""
        freqs = [462.5625, 462.5800]  # 17.5 kHz apart — between 12.5 and 25
        warnings = check_frequency_conflicts(freqs)
        assert any("wideband" in w.lower() for w in warnings)

    def test_harmonic_detection(self):
        """Harmonic conflicts should be detected."""
        # 100 MHz and 200 MHz (2nd harmonic)
        freqs = [100.0, 200.0]
        warnings = check_frequency_conflicts(freqs)
        assert any("harmonic" in w.lower() for w in warnings)

    def test_intermod_detection(self):
        """Two-signal intermod products should be detected."""
        # If A=100, B=110, C=90: 2*100-110=90 (hits C)
        freqs = [90.0, 100.0, 110.0]
        warnings = check_frequency_conflicts(freqs)
        assert any("intermod" in w.lower() for w in warnings)

    def test_single_frequency_no_warnings(self):
        """Single frequency should produce no warnings."""
        warnings = check_frequency_conflicts([462.5625])
        assert len(warnings) == 0

    def test_empty_list_no_warnings(self):
        """Empty frequency list should produce no warnings."""
        warnings = check_frequency_conflicts([])
        assert len(warnings) == 0

    def test_duplicate_warnings_removed(self):
        """Duplicate warnings should be deduplicated."""
        freqs = [100.0, 200.0]  # Harmonic
        warnings = check_frequency_conflicts(freqs)
        assert len(warnings) == len(set(warnings))


# ─── Formatting Functions ────────────────────────────────────────


class TestFormatServiceId:
    """Test format_service_id text output."""

    def test_known_frequency(self):
        """Known frequency should show service info."""
        lines = format_service_id(462.5625)
        text = "\n".join(lines)
        assert "462.5625" in text
        assert "FRS" in text or "GMRS" in text

    def test_unknown_frequency(self):
        """Unknown frequency should still produce output."""
        lines = format_service_id(10.0)
        text = "\n".join(lines)
        assert "10.0000" in text
        assert "Unknown" in text

    def test_output_has_required_fields(self):
        """Output should include Service, Band, Allocation."""
        lines = format_service_id(146.520)
        text = "\n".join(lines)
        assert "Service:" in text
        assert "Band:" in text
        assert "Allocation:" in text


class TestFormatAllOffsets:
    """Test format_all_offsets text output."""

    def test_has_offsets(self):
        """2m frequency should list offset options."""
        lines = format_all_offsets(146.940)
        text = "\n".join(lines)
        assert "146.9400" in text
        assert "Input:" in text

    def test_no_offsets(self):
        """Out-of-band frequency says no offsets found."""
        lines = format_all_offsets(155.0)
        text = "\n".join(lines)
        assert "no standard repeater offsets found" in text


class TestFormatConflictCheck:
    """Test format_conflict_check text output."""

    def test_no_conflicts(self):
        """Clean frequency list shows no conflicts."""
        lines = format_conflict_check([462.5625, 462.5875, 462.6125])
        text = "\n".join(lines)
        assert "3 frequencies" in text

    def test_with_conflicts(self):
        """Conflicting frequencies show issues."""
        lines = format_conflict_check([462.5625, 462.5635])
        text = "\n".join(lines)
        assert "issue" in text.lower()


# ─── CLI Integration (via run_cli) ───────────────────────────────


class TestCLIFreqToolsNew:
    """Test new freq-tools CLI subcommands."""

    def test_identify_subcommand(self, capsys):
        """freq-tools identify should print service info."""
        from quickprs.cli import run_cli
        result = run_cli(["freq-tools", "identify", "462.5625"])
        assert result == 0
        out = capsys.readouterr().out
        assert "FRS" in out or "GMRS" in out

    def test_all_offsets_subcommand(self, capsys):
        """freq-tools all-offsets should print offset options."""
        from quickprs.cli import run_cli
        result = run_cli(["freq-tools", "all-offsets", "146.94"])
        assert result == 0
        out = capsys.readouterr().out
        assert "146.9400" in out

    def test_conflicts_subcommand(self, capsys):
        """freq-tools conflicts should check frequency list."""
        from quickprs.cli import run_cli
        result = run_cli(
            ["freq-tools", "conflicts", "462.5625,462.5875,462.6125"])
        assert result == 0
        out = capsys.readouterr().out
        assert "3 frequencies" in out

    def test_identify_no_freq_errors(self, capsys):
        """freq-tools identify without freq should error."""
        from quickprs.cli import run_cli
        # argparse should raise SystemExit for missing required arg
        with pytest.raises(SystemExit):
            run_cli(["freq-tools", "identify"])


@pytest.mark.skipif(not CLAUDE.exists(),
                    reason="Test PRS data not available")
class TestCLIRename:
    """Test rename CLI subcommand."""

    def test_rename_cli_args_parsed(self):
        """Verify rename parser is registered."""
        from quickprs.cli import run_cli
        import tempfile
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            # Copy test file
            test_file = tmp / "test.PRS"
            shutil.copy2(CLAUDE, test_file)

            result = run_cli([
                "rename", str(test_file),
                "--set", "GROUP SE",
                "--pattern", "ZZZZZ",
                "--replace", "XXXXX",
            ])
            assert result == 0  # No matches but succeeds
        finally:
            shutil.rmtree(tmp)


@pytest.mark.skipif(not CLAUDE.exists(),
                    reason="Test PRS data not available")
class TestCLISort:
    """Test sort CLI subcommand."""

    def test_sort_cli_group_by_id(self):
        """Sort groups by ID via CLI."""
        from quickprs.cli import run_cli
        import tempfile
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            test_file = tmp / "test.PRS"
            shutil.copy2(CLAUDE, test_file)

            result = run_cli([
                "sort", str(test_file),
                "--set", "GROUP SE",
                "--key", "id",
                "--type", "group",
            ])
            assert result == 0
        finally:
            shutil.rmtree(tmp)
