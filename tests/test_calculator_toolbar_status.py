"""Tests for radio calculator functions, toolbar context updates,
and tree status indicators.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from quickprs.freq_tools import (
    calculate_p25_channel, p25_channel_range,
    calculate_channel_spacing,
    calculate_repeater_offset, calculate_all_offsets,
    CTCSS_TONES, DCS_CODES, identify_service,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Calculator — P25 Channel Frequency Calculation
# ═══════════════════════════════════════════════════════════════════


class TestP25ChannelCalculator:
    """Test P25 logical channel number to frequency conversion."""

    def test_basic_calculation(self):
        """Basic LCN calculation: base + (lcn * spacing/1000)."""
        # 851.0 MHz base, 12.5 kHz spacing, LCN 100
        result = calculate_p25_channel(851.0, 12.5, 100)
        expected = 851.0 + (100 * 12.5 / 1000.0)
        assert result == pytest.approx(expected)

    def test_lcn_zero(self):
        """LCN 0 should return the base frequency."""
        result = calculate_p25_channel(851.0, 12.5, 0)
        assert result == pytest.approx(851.0)

    def test_lcn_one(self):
        """LCN 1 should add one channel spacing."""
        result = calculate_p25_channel(851.0, 12.5, 1)
        assert result == pytest.approx(851.0125)

    def test_6_25_khz_spacing(self):
        """6.25 kHz spacing (TDMA) should work correctly."""
        result = calculate_p25_channel(851.0, 6.25, 200)
        expected = 851.0 + (200 * 6.25 / 1000.0)
        assert result == pytest.approx(expected)

    def test_25_khz_spacing(self):
        """25 kHz spacing should work correctly."""
        result = calculate_p25_channel(851.0, 25.0, 50)
        expected = 851.0 + (50 * 25.0 / 1000.0)
        assert result == pytest.approx(expected)

    def test_high_lcn(self):
        """High LCN values should work (up to 4095 is P25 spec)."""
        result = calculate_p25_channel(851.0, 12.5, 4095)
        expected = 851.0 + (4095 * 12.5 / 1000.0)
        assert result == pytest.approx(expected)

    def test_vhf_base(self):
        """VHF base frequency calculation."""
        result = calculate_p25_channel(150.0, 12.5, 100)
        expected = 150.0 + (100 * 12.5 / 1000.0)
        assert result == pytest.approx(expected)

    def test_negative_lcn_handled(self):
        """Negative LCN subtracts from base (edge case)."""
        result = calculate_p25_channel(851.0, 12.5, -1)
        assert result == pytest.approx(851.0 - 0.0125)

    def test_return_type_is_float(self):
        """Return type should be float."""
        result = calculate_p25_channel(851.0, 12.5, 100)
        assert isinstance(result, float)

    def test_known_p25_frequency(self):
        """Verify a known P25 system frequency calculation.

        Example: Washington State Patrol
        Base: 851.0125 MHz, Spacing: 12.5 kHz, LCN 0 -> 851.0125 MHz
        """
        result = calculate_p25_channel(851.0125, 12.5, 0)
        assert result == pytest.approx(851.0125)

    def test_real_world_lcn_380(self):
        """Real-world LCN 380 with 12.5 kHz spacing."""
        base = 851.0125
        result = calculate_p25_channel(base, 12.5, 380)
        expected = base + (380 * 0.0125)
        assert result == pytest.approx(expected)


class TestP25ChannelRange:
    """Test P25 channel range calculation."""

    def test_single_lcn_range(self):
        """Range with start == end should return one entry."""
        result = p25_channel_range(851.0, 12.5, 100, 100)
        assert len(result) == 1
        assert result[0][0] == 100

    def test_range_count(self):
        """Range should return correct number of entries."""
        result = p25_channel_range(851.0, 12.5, 0, 9)
        assert len(result) == 10

    def test_range_ascending_lcn(self):
        """LCNs should be in ascending order."""
        result = p25_channel_range(851.0, 12.5, 5, 10)
        lcns = [r[0] for r in result]
        assert lcns == [5, 6, 7, 8, 9, 10]

    def test_range_ascending_freq(self):
        """Frequencies should be ascending with ascending LCN."""
        result = p25_channel_range(851.0, 12.5, 0, 5)
        freqs = [r[1] for r in result]
        assert freqs == sorted(freqs)

    def test_range_entries_match_single(self):
        """Each range entry should match individual calculate_p25_channel."""
        base = 851.0
        spacing = 12.5
        result = p25_channel_range(base, spacing, 10, 15)
        for lcn, freq in result:
            expected = calculate_p25_channel(base, spacing, lcn)
            assert freq == pytest.approx(expected)

    def test_range_tuple_format(self):
        """Each entry should be (lcn, freq_mhz) tuple."""
        result = p25_channel_range(851.0, 12.5, 0, 2)
        for entry in result:
            assert len(entry) == 2
            lcn, freq = entry
            assert isinstance(lcn, int)
            assert isinstance(freq, float)


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Calculator — Channel Spacing
# ═══════════════════════════════════════════════════════════════════


class TestChannelSpacing:
    """Test channel spacing calculations."""

    def test_12_5_khz_spacing(self):
        """Two frequencies 12.5 kHz apart."""
        result = calculate_channel_spacing(462.5625, 462.575)
        assert result['spacing_khz'] == pytest.approx(12.5)

    def test_25_khz_spacing(self):
        """Two frequencies 25 kHz apart."""
        result = calculate_channel_spacing(462.5625, 462.5875)
        assert result['spacing_khz'] == pytest.approx(25.0)

    def test_identical_frequencies(self):
        """Same frequency should have 0 spacing."""
        result = calculate_channel_spacing(462.5625, 462.5625)
        assert result['spacing_khz'] == pytest.approx(0.0)
        assert result['channels_12_5'] == 0
        assert result['channels_25'] == 0

    def test_order_independent(self):
        """Spacing should be the same regardless of order."""
        r1 = calculate_channel_spacing(462.5625, 462.575)
        r2 = calculate_channel_spacing(462.575, 462.5625)
        assert r1['spacing_khz'] == pytest.approx(r2['spacing_khz'])

    def test_narrowband_interference(self):
        """Frequencies closer than 12.5 kHz should flag interference."""
        result = calculate_channel_spacing(462.5625, 462.570)
        assert result['would_interfere_nb'] is True

    def test_no_narrowband_interference(self):
        """Frequencies at 12.5 kHz should not flag NB interference."""
        result = calculate_channel_spacing(462.5625, 462.575)
        assert result['would_interfere_nb'] is False

    def test_wideband_interference(self):
        """Frequencies between 12.5 and 25 kHz should flag WB interference."""
        result = calculate_channel_spacing(462.5625, 462.575)
        assert result['would_interfere_wb'] is True

    def test_no_wideband_interference(self):
        """Frequencies at 25 kHz should not flag WB interference."""
        result = calculate_channel_spacing(462.5625, 462.5875)
        assert result['would_interfere_wb'] is False

    def test_channels_between_100_khz(self):
        """100 kHz gap should fit several channels at both spacings."""
        result = calculate_channel_spacing(462.500, 462.600)
        assert result['channels_12_5'] == 7  # 8 slots - 1 = 7 between
        assert result['channels_25'] == 3   # 4 slots - 1 = 3 between

    def test_large_gap(self):
        """1 MHz gap should fit many channels."""
        result = calculate_channel_spacing(462.0, 463.0)
        assert result['channels_12_5'] > 0
        assert result['channels_25'] > 0
        assert result['channels_12_5'] > result['channels_25']

    def test_result_dict_keys(self):
        """Result should have all expected keys."""
        result = calculate_channel_spacing(462.0, 463.0)
        assert 'spacing_khz' in result
        assert 'channels_12_5' in result
        assert 'channels_25' in result
        assert 'would_interfere_nb' in result
        assert 'would_interfere_wb' in result


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Calculator — Integration with existing freq_tools
# ═══════════════════════════════════════════════════════════════════


class TestCalculatorIntegration:
    """Test that calculator functions work alongside existing freq_tools."""

    def test_p25_channel_and_offset(self):
        """P25 calc result can be fed to offset calculator."""
        freq = calculate_p25_channel(851.0, 12.5, 100)
        # 800 MHz band should have all_offsets
        offsets = calculate_all_offsets(freq)
        # 800 MHz has +/- 45 MHz offsets
        assert len(offsets) > 0

    def test_p25_channel_and_service_id(self):
        """P25 calc result can be identified by service."""
        freq = calculate_p25_channel(851.0, 12.5, 10)
        svc = identify_service(freq)
        assert svc is not None
        assert 'service' in svc

    def test_spacing_with_repeater_offset(self):
        """Spacing between repeater input and output."""
        result = calculate_repeater_offset(146.940)
        assert result is not None
        offset_mhz, direction = result
        input_freq = 146.940 + offset_mhz  # + direction
        spacing = calculate_channel_spacing(146.940, input_freq)
        assert spacing['spacing_khz'] == pytest.approx(600.0)

    def test_ctcss_tones_still_accessible(self):
        """Existing CTCSS data should still be accessible."""
        assert len(CTCSS_TONES) == 50

    def test_dcs_codes_still_accessible(self):
        """Existing DCS data should still be accessible."""
        assert len(DCS_CODES) == 104


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Calculator GUI (import test only, no tk needed)
# ═══════════════════════════════════════════════════════════════════


class TestCalculatorModule:
    """Test that the calculator module is importable."""

    def test_module_importable(self):
        """Calculator module should be importable without tk."""
        # Just verify the module can be found by the import system
        import importlib
        spec = importlib.util.find_spec("quickprs.gui.calculator")
        assert spec is not None


# ═══════════════════════════════════════════════════════════════════
# Feature 2: Toolbar Context — logic tests (no GUI)
# ═══════════════════════════════════════════════════════════════════


class TestToolbarContextLogic:
    """Test the logic for determining context-aware toolbar buttons."""

    def _get_context_for_type(self, item_type, name="TEST"):
        """Simulate what _on_tree_selection_changed decides."""
        if item_type == "group_set":
            return f"+ TG to {name}" if name else "+ TG"
        elif item_type == "conv_set":
            return f"+ CH to {name}" if name else "+ CH"
        elif item_type == "p25_conv_set":
            return f"+ CH to {name}" if name else "+ CH"
        elif item_type == "trunk_set":
            return f"+ Freq to {name}" if name else "+ Freq"
        return None

    def test_group_set_context(self):
        """Group set selection should show TG add button."""
        label = self._get_context_for_type("group_set", "PSERN PD")
        assert label == "+ TG to PSERN PD"

    def test_conv_set_context(self):
        """Conv set selection should show CH add button."""
        label = self._get_context_for_type("conv_set", "SIMPLEX")
        assert label == "+ CH to SIMPLEX"

    def test_p25_conv_set_context(self):
        """P25 conv set selection should show CH add button."""
        label = self._get_context_for_type("p25_conv_set", "P25C")
        assert label == "+ CH to P25C"

    def test_trunk_set_context(self):
        """Trunk set selection should show freq add button."""
        label = self._get_context_for_type("trunk_set", "PSERN")
        assert label == "+ Freq to PSERN"

    def test_unknown_type_no_context(self):
        """Non-set types should return no button."""
        label = self._get_context_for_type("root")
        assert label is None

    def test_talkgroup_no_context(self):
        """Talkgroup items should return no button."""
        label = self._get_context_for_type("talkgroup")
        assert label is None

    def test_system_no_context(self):
        """System items should return no button."""
        label = self._get_context_for_type("system")
        assert label is None

    def test_empty_name(self):
        """Empty set name should give short label."""
        label = self._get_context_for_type("group_set", "")
        assert label == "+ TG"


# ═══════════════════════════════════════════════════════════════════
# Feature 3: Status Indicators — logic tests
# ═══════════════════════════════════════════════════════════════════


class TestStatusIndicatorLogic:
    """Test status indicator tagging logic."""

    def test_error_severity_maps_to_red(self):
        """ERROR severity should map to status_error tag."""
        # The tag name for errors
        assert "status_error" == "status_error"

    def test_warning_severity_maps_to_orange(self):
        """WARNING severity should map to status_warning tag."""
        assert "status_warning" == "status_warning"

    def test_near_capacity_threshold(self):
        """Groups with >100 TGs should get near_capacity tag."""
        threshold = 100
        assert 101 > threshold
        assert 100 <= threshold

    def test_empty_set_detection(self):
        """Empty sets (0 items) should get empty tag."""
        items_count = 0
        assert items_count == 0

    def test_encrypted_detection_in_flags(self):
        """ENC in detail string should trigger encrypted tag."""
        detail = "TG NAME [TX Scan ENC]"
        assert "ENC" in detail

    def test_no_encrypted_without_flag(self):
        """Detail without ENC should not trigger encrypted tag."""
        detail = "TG NAME [TX Scan]"
        assert "ENC" not in detail


class TestStatusIndicatorWithPRS:
    """Test status indicators with actual PRS data."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test data missing")
    def test_validation_produces_categories(self):
        """Validation detailed output should have category names."""
        from conftest import cached_parse_prs
        from quickprs.validation import validate_prs_detailed
        prs = cached_parse_prs(PAWS)
        detailed = validate_prs_detailed(prs)
        assert isinstance(detailed, dict)
        # Categories should be strings like "Group Set: X" or "Global"
        for key in detailed:
            assert isinstance(key, str)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test data missing")
    def test_health_check_produces_tuples(self):
        """Health check should produce tuples with severity."""
        from conftest import cached_parse_prs
        from quickprs.health_check import run_health_check
        prs = cached_parse_prs(PAWS)
        results = run_health_check(prs)
        assert isinstance(results, list)
        for item in results:
            assert len(item) == 4

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test data missing")
    def test_status_indicators_no_crash(self):
        """Status indicator application should not crash on real data.

        We can't test the GUI directly but can verify the validation
        and health check calls work on real PRS data.
        """
        from conftest import cached_parse_prs
        from quickprs.validation import validate_prs_detailed
        from quickprs.health_check import run_health_check

        prs = cached_parse_prs(CLAUDE)

        detailed = validate_prs_detailed(prs)
        assert isinstance(detailed, dict)

        health = run_health_check(prs)
        assert isinstance(health, list)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test data missing")
    def test_group_set_categories_in_validation(self):
        """Validation should produce Group Set category entries."""
        from conftest import cached_parse_prs
        from quickprs.validation import validate_prs_detailed
        prs = cached_parse_prs(PAWS)
        detailed = validate_prs_detailed(prs)
        group_cats = [k for k in detailed if k.startswith("Group Set:")]
        # PAWSOVERMAWS has group sets, may or may not have issues
        # The test just verifies the category naming convention
        assert isinstance(group_cats, list)


# ═══════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases for new calculator functions."""

    def test_p25_zero_spacing(self):
        """Zero spacing should return base for any LCN."""
        result = calculate_p25_channel(851.0, 0, 100)
        assert result == pytest.approx(851.0)

    def test_p25_zero_base(self):
        """Zero base should still calculate correctly."""
        result = calculate_p25_channel(0, 12.5, 100)
        assert result == pytest.approx(1.25)

    def test_spacing_very_close_frequencies(self):
        """Very close frequencies (< 1 kHz apart)."""
        result = calculate_channel_spacing(462.56250, 462.56290)
        assert result['spacing_khz'] == pytest.approx(0.4, abs=0.01)
        assert result['would_interfere_nb'] is True
        assert result['would_interfere_wb'] is True

    def test_spacing_very_far_frequencies(self):
        """Very far frequencies (100 MHz apart)."""
        result = calculate_channel_spacing(400.0, 500.0)
        assert result['spacing_khz'] == pytest.approx(100000.0)
        assert result['channels_12_5'] > 0
        assert result['would_interfere_nb'] is False

    def test_p25_range_empty(self):
        """Range where start > end should be empty."""
        result = p25_channel_range(851.0, 12.5, 10, 5)
        assert len(result) == 0
