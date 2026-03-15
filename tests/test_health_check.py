"""Tests for health check, frequency map, and suggestion features."""

import pytest
from pathlib import Path
from unittest.mock import patch
import sys

from quickprs.prs_parser import parse_prs
from quickprs.health_check import (
    run_health_check, format_health_report,
    suggest_improvements, format_suggestions,
    CRITICAL, WARN, INFO,
    _has_noaa_channels, _has_interop_channels, _has_emergency_tg,
    _find_similar_names, _get_personality_name,
    _parse_group_sets, _parse_trunk_sets, _parse_conv_sets,
)
from quickprs.freq_tools import (
    generate_freq_map, _classify_freq, _BAND_ALIASES,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE_PRS = TESTDATA / "claude test.PRS"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Health Check Core ─────────────────────────────────────────────


class TestRunHealthCheck:
    """Test the main health check function."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_returns_list(self):
        """Health check returns a list of tuples."""
        prs = parse_prs(CLAUDE_PRS)
        results = run_health_check(prs)
        assert isinstance(results, list)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_tuple_format(self):
        """Each result is a (severity, category, message, suggestion) tuple."""
        prs = parse_prs(CLAUDE_PRS)
        results = run_health_check(prs)
        for item in results:
            assert len(item) == 4
            severity, category, message, suggestion = item
            assert severity in (CRITICAL, WARN, INFO)
            assert isinstance(category, str)
            assert isinstance(message, str)
            assert isinstance(suggestion, str)

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_health_check_pawsovermaws(self):
        """Health check runs on PAWSOVERMAWS without error."""
        prs = parse_prs(PAWS_PRS)
        results = run_health_check(prs)
        assert isinstance(results, list)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_no_crash(self):
        """Health check does not crash on either test file."""
        for f in (CLAUDE_PRS, PAWS_PRS):
            if f.exists():
                prs = parse_prs(f)
                results = run_health_check(prs)
                assert isinstance(results, list)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_severity_valid(self):
        """All severities are recognized values."""
        prs = parse_prs(CLAUDE_PRS)
        results = run_health_check(prs)
        valid = {CRITICAL, WARN, INFO}
        for sev, _, _, _ in results:
            assert sev in valid, f"Unknown severity: {sev}"


class TestFormatHealthReport:
    """Test health report formatting."""

    def test_format_empty_results(self):
        """Empty results produce a PASS message."""
        lines = format_health_report([])
        text = "\n".join(lines)
        assert "PASS" in text
        assert "No issues" in text

    def test_format_with_results(self):
        """Results produce formatted output with categories."""
        results = [
            (WARN, "Safety", "No emergency TG", "Add one"),
            (INFO, "Options", "GPS disabled", "Enable GPS"),
        ]
        lines = format_health_report(results)
        text = "\n".join(lines)
        assert "Safety" in text
        assert "Options" in text
        assert "No emergency TG" in text
        assert "GPS disabled" in text

    def test_format_summary_counts(self):
        """Summary line has correct counts."""
        results = [
            (WARN, "A", "msg1", "sug1"),
            (WARN, "B", "msg2", "sug2"),
            (INFO, "C", "msg3", "sug3"),
        ]
        lines = format_health_report(results)
        text = "\n".join(lines)
        assert "2 warnings" in text
        assert "1 info" in text

    def test_format_critical_shown(self):
        """Critical issues appear in output."""
        results = [
            (CRITICAL, "Error", "Big problem", "Fix it"),
        ]
        lines = format_health_report(results)
        text = "\n".join(lines)
        assert "1 critical" in text


# ─── Helper Functions ──────────────────────────────────────────────


class TestHelpers:
    """Test helper functions."""

    def test_find_similar_names_identical(self):
        """Identical names should not be flagged (same != similar)."""
        pairs = _find_similar_names(["FIRE 1", "FIRE 1"])
        assert len(pairs) == 0

    def test_find_similar_names_different(self):
        """Very different names should not match."""
        pairs = _find_similar_names(["FIRE", "WATER", "EARTH"])
        assert len(pairs) == 0

    def test_find_similar_names_close(self):
        """Very similar names should be detected."""
        pairs = _find_similar_names(["FIRE ENG1", "FIRE ENG2", "WATER"])
        # FIRE ENG1 and FIRE ENG2 are close (0.89 similarity)
        assert len(pairs) >= 1
        found = any("FIRE ENG1" in p and "FIRE ENG2" in p
                     for p in [(a, b) for a, b, _ in pairs])
        assert found

    def test_find_similar_names_empty(self):
        """Empty list returns empty."""
        pairs = _find_similar_names([])
        assert pairs == []

    def test_find_similar_names_single(self):
        """Single name returns empty."""
        pairs = _find_similar_names(["FIRE"])
        assert pairs == []

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_get_personality_name(self):
        """Personality name extraction works."""
        prs = parse_prs(CLAUDE_PRS)
        name = _get_personality_name(prs)
        assert isinstance(name, str)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_has_noaa_channels(self):
        """NOAA channel detection returns bool."""
        prs = parse_prs(CLAUDE_PRS)
        conv_sets = _parse_conv_sets(prs)
        result = _has_noaa_channels(conv_sets)
        assert isinstance(result, bool)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_has_interop_channels(self):
        """Interop channel detection returns bool."""
        prs = parse_prs(CLAUDE_PRS)
        conv_sets = _parse_conv_sets(prs)
        trunk_sets = _parse_trunk_sets(prs)
        result = _has_interop_channels(conv_sets, trunk_sets)
        assert isinstance(result, bool)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_has_emergency_tg(self):
        """Emergency TG detection returns bool."""
        prs = parse_prs(CLAUDE_PRS)
        group_sets = _parse_group_sets(prs)
        result = _has_emergency_tg(group_sets)
        assert isinstance(result, bool)


# ─── Suggestions ───────────────────────────────────────────────────


class TestSuggestions:
    """Test configuration improvement suggestions."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_suggest_returns_list(self):
        """suggest_improvements returns a list."""
        prs = parse_prs(CLAUDE_PRS)
        suggestions = suggest_improvements(prs)
        assert isinstance(suggestions, list)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_suggest_tuple_format(self):
        """Each suggestion is (category, suggestion, command)."""
        prs = parse_prs(CLAUDE_PRS)
        suggestions = suggest_improvements(prs)
        for item in suggestions:
            assert len(item) == 3
            category, suggestion, command = item
            assert isinstance(category, str)
            assert isinstance(suggestion, str)
            assert isinstance(command, str)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_suggest_commands_start_with_quickprs(self):
        """All CLI commands in suggestions start with 'quickprs'."""
        prs = parse_prs(CLAUDE_PRS)
        suggestions = suggest_improvements(prs, filepath="test.PRS")
        for _, _, command in suggestions:
            assert command.startswith("quickprs"), \
                f"Command should start with quickprs: {command}"

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_suggest_filepath_in_commands(self):
        """File path appears in suggestion commands."""
        prs = parse_prs(CLAUDE_PRS)
        suggestions = suggest_improvements(prs, filepath="MY_RADIO.PRS")
        for _, _, command in suggestions:
            assert "MY_RADIO.PRS" in command

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_suggest_pawsovermaws(self):
        """Suggestions work on PAWSOVERMAWS."""
        prs = parse_prs(PAWS_PRS)
        suggestions = suggest_improvements(prs, filepath="PAWSOVERMAWS.PRS")
        assert isinstance(suggestions, list)

    def test_format_suggestions_empty(self):
        """Empty suggestions produce 'no suggestions' message."""
        lines = format_suggestions([], filepath="test.PRS")
        text = "\n".join(lines)
        assert "No suggestions" in text or "no suggestions" in text.lower()

    def test_format_suggestions_with_items(self):
        """Suggestions are formatted with categories and commands."""
        suggestions = [
            ("Missing Channels", "Add NOAA", "quickprs inject f conv"),
            ("Best Practices", "Set password", "quickprs set-option f x"),
        ]
        lines = format_suggestions(suggestions, filepath="test.PRS")
        text = "\n".join(lines)
        assert "Missing Channels" in text
        assert "Best Practices" in text
        assert "Add NOAA" in text
        assert "quickprs inject" in text


# ─── Frequency Map ─────────────────────────────────────────────────


class TestFreqMap:
    """Test frequency spectrum map generation."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_freq_map_returns_list(self):
        """Freq map returns a list of strings."""
        prs = parse_prs(CLAUDE_PRS)
        lines = generate_freq_map(prs)
        assert isinstance(lines, list)
        for line in lines:
            assert isinstance(line, str)

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_freq_map_pawsovermaws(self):
        """Freq map works on PAWSOVERMAWS (has trunk freqs)."""
        prs = parse_prs(PAWS_PRS)
        lines = generate_freq_map(prs)
        assert isinstance(lines, list)
        assert len(lines) > 5  # should have content
        text = "\n".join(lines)
        assert "Total:" in text

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_freq_map_band_filter(self):
        """Band filter limits output to specified band."""
        prs = parse_prs(PAWS_PRS)
        lines = generate_freq_map(prs, band="800")
        text = "\n".join(lines)
        # Should have 800 MHz band
        assert "800" in text

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_freq_map_all_bands(self):
        """'all' band shows everything."""
        prs = parse_prs(PAWS_PRS)
        lines_all = generate_freq_map(prs, band="all")
        lines_none = generate_freq_map(prs, band=None)
        # Both should produce same result
        assert len(lines_all) == len(lines_none)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_freq_map_has_legend(self):
        """Freq map output includes a legend."""
        prs = parse_prs(CLAUDE_PRS)
        lines = generate_freq_map(prs)
        text = "\n".join(lines)
        if "No frequencies" not in text:
            assert "Legend:" in text or "simplex" in text

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_freq_map_has_total(self):
        """Freq map output includes a total count."""
        prs = parse_prs(CLAUDE_PRS)
        lines = generate_freq_map(prs)
        text = "\n".join(lines)
        if "No frequencies" not in text:
            assert "Total:" in text

    def test_classify_freq_vhf(self):
        """VHF frequencies are classified correctly."""
        assert _classify_freq(146.520) == "VHF"
        assert _classify_freq(155.475) == "VHF"

    def test_classify_freq_uhf(self):
        """UHF frequencies are classified correctly."""
        assert _classify_freq(462.5625) == "UHF"

    def test_classify_freq_800(self):
        """800 MHz frequencies are classified correctly."""
        assert _classify_freq(851.0125) == "800 MHz"

    def test_classify_freq_700(self):
        """700 MHz frequencies are classified correctly."""
        assert _classify_freq(769.24375) == "700 MHz"

    def test_classify_freq_vhf_low(self):
        """VHF Low Band frequencies are classified correctly."""
        assert _classify_freq(45.0) == "VHF Low"

    def test_classify_freq_900(self):
        """900 MHz frequencies are classified correctly."""
        assert _classify_freq(920.0) == "900 MHz"

    def test_classify_freq_other(self):
        """Out-of-range frequencies are 'Other'."""
        assert _classify_freq(1200.0) == "Other"
        assert _classify_freq(10.0) == "Other"

    def test_band_aliases(self):
        """Band aliases are defined for common band names."""
        assert "vhf" in _BAND_ALIASES
        assert "uhf" in _BAND_ALIASES
        assert "700" in _BAND_ALIASES
        assert "800" in _BAND_ALIASES
        assert "900" in _BAND_ALIASES
        assert "all" in _BAND_ALIASES
        assert _BAND_ALIASES["all"] is None

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_freq_map_invalid_band_no_crash(self):
        """Invalid band filter does not crash."""
        prs = parse_prs(PAWS_PRS)
        # "vhf" band filter on a file with mostly 800MHz
        lines = generate_freq_map(prs, band="vhf")
        assert isinstance(lines, list)


# ─── CLI Integration ──────────────────────────────────────────────


class TestCLI:
    """Test CLI command dispatch for new commands."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cmd_health(self):
        """cmd_health runs without error."""
        from quickprs.cli import cmd_health
        rc = cmd_health(str(CLAUDE_PRS))
        assert rc in (0, 1)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cmd_suggest(self):
        """cmd_suggest runs without error."""
        from quickprs.cli import cmd_suggest
        rc = cmd_suggest(str(CLAUDE_PRS))
        assert rc == 0

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cmd_freq_map(self):
        """cmd_freq_map runs without error."""
        from quickprs.cli import cmd_freq_map
        rc = cmd_freq_map(str(CLAUDE_PRS))
        assert rc == 0

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cmd_freq_map_with_band(self):
        """cmd_freq_map with band filter runs without error."""
        from quickprs.cli import cmd_freq_map
        rc = cmd_freq_map(str(PAWS_PRS), band="800")
        assert rc == 0

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cmd_health_pawsovermaws(self):
        """cmd_health works on PAWSOVERMAWS."""
        from quickprs.cli import cmd_health
        rc = cmd_health(str(PAWS_PRS))
        assert rc in (0, 1)

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cmd_suggest_pawsovermaws(self):
        """cmd_suggest works on PAWSOVERMAWS."""
        from quickprs.cli import cmd_suggest
        rc = cmd_suggest(str(PAWS_PRS))
        assert rc == 0

    def test_cmd_health_nonexistent(self):
        """cmd_health on nonexistent file raises error."""
        from quickprs.cli import cmd_health
        with pytest.raises(FileNotFoundError):
            cmd_health("DOES_NOT_EXIST.PRS")

    def test_cmd_suggest_nonexistent(self):
        """cmd_suggest on nonexistent file raises error."""
        from quickprs.cli import cmd_suggest
        with pytest.raises(FileNotFoundError):
            cmd_suggest("DOES_NOT_EXIST.PRS")

    def test_cmd_freq_map_nonexistent(self):
        """cmd_freq_map on nonexistent file raises error."""
        from quickprs.cli import cmd_freq_map
        with pytest.raises(FileNotFoundError):
            cmd_freq_map("DOES_NOT_EXIST.PRS")


class TestCLIDispatch:
    """Test CLI argument parsing for new commands."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cli_health_dispatch(self):
        """CLI dispatches 'health' command correctly."""
        from quickprs.cli import run_cli
        rc = run_cli(["health", str(CLAUDE_PRS)])
        assert rc in (0, 1)

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cli_suggest_dispatch(self):
        """CLI dispatches 'suggest' command correctly."""
        from quickprs.cli import run_cli
        rc = run_cli(["suggest", str(CLAUDE_PRS)])
        assert rc == 0

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_cli_freq_map_dispatch(self):
        """CLI dispatches 'freq-map' command correctly."""
        from quickprs.cli import run_cli
        rc = run_cli(["freq-map", str(CLAUDE_PRS)])
        assert rc == 0

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cli_freq_map_with_band_dispatch(self):
        """CLI dispatches 'freq-map --band' correctly."""
        from quickprs.cli import run_cli
        rc = run_cli(["freq-map", str(PAWS_PRS), "--band", "800"])
        assert rc == 0


# ─── Edge Cases ────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and corner scenarios."""

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_categories_non_empty(self):
        """All categories in results are non-empty strings."""
        prs = parse_prs(CLAUDE_PRS)
        results = run_health_check(prs)
        for _, cat, _, _ in results:
            assert len(cat) > 0

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_health_check_messages_non_empty(self):
        """All messages in results are non-empty strings."""
        prs = parse_prs(CLAUDE_PRS)
        results = run_health_check(prs)
        for _, _, msg, _ in results:
            assert len(msg) > 0

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_suggestions_categories_non_empty(self):
        """All suggestion categories are non-empty."""
        prs = parse_prs(CLAUDE_PRS)
        suggestions = suggest_improvements(prs)
        for cat, _, _ in suggestions:
            assert len(cat) > 0

    def test_format_health_report_single_item(self):
        """Single result formats correctly."""
        results = [(INFO, "Test", "Test message", "Test suggestion")]
        lines = format_health_report(results)
        text = "\n".join(lines)
        assert "Test message" in text
        assert "1 info" in text

    def test_format_suggestions_single_item(self):
        """Single suggestion formats correctly."""
        suggestions = [("Category", "Do this", "quickprs cmd file.PRS")]
        lines = format_suggestions(suggestions)
        text = "\n".join(lines)
        assert "Category" in text
        assert "Do this" in text
        assert "quickprs cmd" in text

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_freq_map_no_band_filter(self):
        """No band filter shows all available bands."""
        prs = parse_prs(CLAUDE_PRS)
        lines = generate_freq_map(prs, band=None)
        assert isinstance(lines, list)

    def test_classify_freq_boundary_vhf(self):
        """Boundary VHF frequency is classified correctly."""
        assert _classify_freq(136.0) == "VHF"
        assert _classify_freq(174.0) == "VHF"

    def test_classify_freq_boundary_uhf(self):
        """Boundary UHF frequency is classified correctly."""
        assert _classify_freq(400.0) == "UHF"
        assert _classify_freq(512.0) == "UHF"

    def test_classify_freq_gap(self):
        """Frequency in a gap between bands is 'Other'."""
        assert _classify_freq(600.0) == "Other"

    def test_similar_names_threshold(self):
        """Names below threshold are not flagged."""
        # "ALPHA" and "BRAVO" should not be similar
        pairs = _find_similar_names(["ALPHA", "BRAVO"], threshold=0.85)
        assert len(pairs) == 0

    def test_similar_names_above_threshold(self):
        """Names above threshold are flagged."""
        pairs = _find_similar_names(["FIRE ENG", "FIRE ENS"], threshold=0.5)
        assert len(pairs) >= 1
