"""Tests for the frequency/tone reference tools."""

import pytest

from quickprs.freq_tools import (
    CTCSS_TONES, DCS_CODES,
    calculate_repeater_offset, freq_to_channel, channel_to_freq,
    validate_ctcss_tone, nearest_ctcss,
    format_ctcss_table, format_dcs_table,
    format_repeater_offset, format_channel_id,
)


# ─── CTCSS/DCS data ─────────────────────────────────────────────────


class TestToneData:
    """Verify tone/code data integrity."""

    def test_ctcss_count(self):
        """Standard EIA/TIA set has 50 tones."""
        assert len(CTCSS_TONES) == 50

    def test_ctcss_sorted(self):
        """CTCSS tones should be in ascending order."""
        assert CTCSS_TONES == sorted(CTCSS_TONES)

    def test_ctcss_range(self):
        """CTCSS tones range from 67.0 to 254.1 Hz."""
        assert CTCSS_TONES[0] == 67.0
        assert CTCSS_TONES[-1] == 254.1

    def test_ctcss_no_duplicates(self):
        """No duplicate CTCSS tones."""
        assert len(CTCSS_TONES) == len(set(CTCSS_TONES))

    def test_dcs_count(self):
        """Standard DCS set has 104 codes."""
        assert len(DCS_CODES) == 104

    def test_dcs_sorted(self):
        """DCS codes should be in ascending order."""
        assert DCS_CODES == sorted(DCS_CODES)

    def test_dcs_no_duplicates(self):
        """No duplicate DCS codes."""
        assert len(DCS_CODES) == len(set(DCS_CODES))

    def test_dcs_range(self):
        """DCS codes range from 23 to 754."""
        assert DCS_CODES[0] == 23
        assert DCS_CODES[-1] == 754

    def test_common_ctcss_tones_present(self):
        """Common CTCSS tones should be in the list."""
        common = [100.0, 110.9, 123.0, 141.3, 156.7, 162.2, 186.2]
        for tone in common:
            assert tone in CTCSS_TONES, f"Missing common tone: {tone}"

    def test_common_dcs_codes_present(self):
        """Common DCS codes should be in the list."""
        common = [23, 25, 71, 114, 155, 223, 411]
        for code in common:
            assert code in DCS_CODES, f"Missing common code: {code}"


# ─── Repeater Offset ─────────────────────────────────────────────────


class TestRepeaterOffset:
    """Test repeater offset calculations."""

    def test_2m_low_positive(self):
        """2m output below 147 MHz has + offset."""
        result = calculate_repeater_offset(146.940)
        assert result is not None
        offset, direction = result
        assert offset == 0.6
        assert direction == "+"

    def test_2m_high_negative(self):
        """2m output at/above 147 MHz has - offset."""
        result = calculate_repeater_offset(147.060)
        assert result is not None
        offset, direction = result
        assert offset == 0.6
        assert direction == "-"

    def test_2m_boundary(self):
        """Exactly 147.0 should give - offset."""
        result = calculate_repeater_offset(147.0)
        assert result is not None
        _, direction = result
        assert direction == "-"

    def test_220_band(self):
        """220 MHz band always has -1.6 MHz offset."""
        result = calculate_repeater_offset(224.360)
        assert result is not None
        offset, direction = result
        assert offset == 1.6
        assert direction == "-"

    def test_70cm_low_positive(self):
        """70cm output below 445 MHz has + offset."""
        result = calculate_repeater_offset(442.500)
        assert result is not None
        offset, direction = result
        assert offset == 5.0
        assert direction == "+"

    def test_70cm_high_negative(self):
        """70cm output at/above 445 MHz has - offset."""
        result = calculate_repeater_offset(449.500)
        assert result is not None
        offset, direction = result
        assert offset == 5.0
        assert direction == "-"

    def test_900_band(self):
        """900 MHz band has -12.0 MHz offset."""
        result = calculate_repeater_offset(927.0)
        assert result is not None
        offset, direction = result
        assert offset == 12.0
        assert direction == "-"

    def test_out_of_band(self):
        """Non-repeater frequencies return None."""
        assert calculate_repeater_offset(155.0) is None
        assert calculate_repeater_offset(450.5) is None
        assert calculate_repeater_offset(30.0) is None

    def test_band_boundaries(self):
        """Verify exact band edges work."""
        assert calculate_repeater_offset(144.0) is not None
        assert calculate_repeater_offset(148.0) is not None
        assert calculate_repeater_offset(222.0) is not None
        assert calculate_repeater_offset(225.0) is not None
        assert calculate_repeater_offset(420.0) is not None
        assert calculate_repeater_offset(450.0) is not None
        assert calculate_repeater_offset(902.0) is not None
        assert calculate_repeater_offset(928.0) is not None


# ─── Channel Identification ──────────────────────────────────────────


class TestFreqToChannel:
    """Test frequency to channel identification."""

    def test_frs_channel_1(self):
        """462.5625 MHz = FRS/GMRS channel 1."""
        result = freq_to_channel(462.5625)
        assert result is not None
        service, ch = result
        assert "FRS" in service
        assert ch == 1

    def test_frs_channel_8(self):
        """467.5625 MHz = FRS/GMRS channel 8."""
        result = freq_to_channel(467.5625)
        assert result is not None
        service, ch = result
        assert "FRS" in service
        assert ch == 8

    def test_murs_channel_1(self):
        """151.820 MHz = MURS channel 1."""
        result = freq_to_channel(151.820)
        assert result is not None
        service, ch = result
        assert service == "MURS"
        assert ch == 1

    def test_murs_channel_5(self):
        """154.600 MHz = MURS channel 5."""
        result = freq_to_channel(154.600)
        assert result is not None
        service, ch = result
        assert service == "MURS"
        assert ch == 5

    def test_marine_ch16(self):
        """156.800 MHz = Marine VHF channel 16."""
        result = freq_to_channel(156.800)
        assert result is not None
        service, ch = result
        assert service == "Marine VHF"
        assert ch == 16

    def test_noaa_ch1(self):
        """162.400 MHz = NOAA channel 1."""
        result = freq_to_channel(162.400)
        assert result is not None
        service, ch = result
        assert service == "NOAA"
        assert ch == 1

    def test_unknown_freq(self):
        """Non-service frequency returns None."""
        assert freq_to_channel(155.000) is None
        assert freq_to_channel(800.000) is None

    def test_noaa_all_channels(self):
        """All 7 NOAA channels should be identified."""
        noaa_freqs = [162.400, 162.425, 162.450, 162.475,
                      162.500, 162.525, 162.550]
        for i, freq in enumerate(noaa_freqs, 1):
            result = freq_to_channel(freq)
            assert result is not None, f"NOAA {freq} not found"
            assert result[1] == i


class TestChannelToFreq:
    """Test channel number to frequency conversion."""

    def test_frs_ch1(self):
        """FRS channel 1 = 462.5625 MHz."""
        assert channel_to_freq("FRS", 1) == 462.5625

    def test_gmrs_ch15(self):
        """GMRS channel 15 = 462.5500 MHz."""
        assert channel_to_freq("GMRS", 15) == 462.5500

    def test_murs_ch3(self):
        """MURS channel 3 = 151.940 MHz."""
        assert channel_to_freq("MURS", 3) == 151.940

    def test_marine_ch16(self):
        """Marine channel 16 = 156.800 MHz."""
        assert channel_to_freq("Marine", 16) == 156.800

    def test_marine_vhf_alias(self):
        """Marine VHF should work as an alias."""
        assert channel_to_freq("Marine VHF", 16) == 156.800

    def test_noaa_ch1(self):
        """NOAA channel 1 = 162.400 MHz."""
        assert channel_to_freq("NOAA", 1) == 162.400

    def test_invalid_service(self):
        """Unknown service returns None."""
        assert channel_to_freq("CB", 1) is None

    def test_invalid_channel(self):
        """Invalid channel number returns None."""
        assert channel_to_freq("FRS", 99) is None

    def test_case_insensitive(self):
        """Service name should be case-insensitive."""
        assert channel_to_freq("frs", 1) == 462.5625
        assert channel_to_freq("MURS", 1) == 151.820
        assert channel_to_freq("noaa", 7) == 162.550


# ─── Tone Validation ─────────────────────────────────────────────────


class TestValidateCtcssTone:
    """Test CTCSS/DCS tone validation."""

    def test_valid_ctcss(self):
        """Valid CTCSS tones should be recognized."""
        result = validate_ctcss_tone("100.0")
        assert result is not None
        assert result[0] == "CTCSS"
        assert result[1] == 100.0

    def test_valid_ctcss_low(self):
        """Lowest CTCSS tone."""
        result = validate_ctcss_tone("67.0")
        assert result is not None
        assert result[0] == "CTCSS"
        assert result[1] == 67.0

    def test_valid_ctcss_high(self):
        """Highest CTCSS tone."""
        result = validate_ctcss_tone("254.1")
        assert result is not None
        assert result[0] == "CTCSS"
        assert result[1] == 254.1

    def test_invalid_ctcss(self):
        """Non-standard tone value returns None."""
        assert validate_ctcss_tone("99.9") is None
        assert validate_ctcss_tone("105.0") is None

    def test_valid_dcs_full_format(self):
        """DCS code in D023N format."""
        result = validate_ctcss_tone("D023N")
        assert result is not None
        assert result[0] == "DCS"
        assert result[1] == 23

    def test_valid_dcs_inverted(self):
        """DCS code in D023I format."""
        result = validate_ctcss_tone("D023I")
        assert result is not None
        assert result[0] == "DCS_I"
        assert result[1] == 23

    def test_dcs_as_integer(self):
        """DCS code entered as bare integer."""
        result = validate_ctcss_tone("23")
        assert result is not None
        assert result[0] == "DCS"
        assert result[1] == 23

    def test_invalid_dcs(self):
        """Invalid DCS code returns None."""
        assert validate_ctcss_tone("D999N") is None

    def test_empty_string(self):
        """Empty string returns None."""
        assert validate_ctcss_tone("") is None
        assert validate_ctcss_tone("   ") is None

    def test_garbage(self):
        """Non-numeric garbage returns None."""
        assert validate_ctcss_tone("abc") is None
        assert validate_ctcss_tone("!@#") is None


# ─── Nearest CTCSS ───────────────────────────────────────────────────


class TestNearestCtcss:
    """Test nearest CTCSS tone finder."""

    def test_exact_match(self):
        """Exact tone match should have zero difference."""
        tone, diff = nearest_ctcss(100.0)
        assert tone == 100.0
        assert diff == 0.0

    def test_slightly_off(self):
        """Slightly off-frequency should find nearest."""
        tone, diff = nearest_ctcss(100.5)
        assert tone == 100.0
        assert abs(diff - 0.5) < 0.01

    def test_between_tones(self):
        """Value between two tones finds the closer one."""
        # 100.0 and 103.5 — midpoint is 101.75
        tone, _ = nearest_ctcss(101.0)
        assert tone == 100.0  # closer to 100.0

        tone, _ = nearest_ctcss(102.5)
        assert tone == 103.5  # closer to 103.5

    def test_very_low(self):
        """Very low frequency finds lowest tone."""
        tone, _ = nearest_ctcss(50.0)
        assert tone == 67.0

    def test_very_high(self):
        """Very high frequency finds highest tone."""
        tone, _ = nearest_ctcss(300.0)
        assert tone == 254.1


# ─── Formatting ──────────────────────────────────────────────────────


class TestFormatting:
    """Test text output formatting."""

    def test_ctcss_table_has_all_tones(self):
        """CTCSS table output should mention all 50 tones."""
        lines = format_ctcss_table()
        text = "\n".join(lines)
        assert "50" in text
        assert "67.0" in text
        assert "254.1" in text

    def test_dcs_table_has_all_codes(self):
        """DCS table output should mention all 104 codes."""
        lines = format_dcs_table()
        text = "\n".join(lines)
        assert "104" in text
        assert "D023N" in text

    def test_repeater_offset_format(self):
        """Repeater offset output should show output/input/offset."""
        lines = format_repeater_offset(146.940)
        text = "\n".join(lines)
        assert "146.9400" in text
        assert "+0.6" in text
        assert "2m" in text

    def test_repeater_offset_out_of_band(self):
        """Out-of-band frequency output says so."""
        lines = format_repeater_offset(155.0)
        text = "\n".join(lines)
        assert "not in a standard repeater band" in text

    def test_channel_id_format(self):
        """Channel ID output should show service and channel."""
        lines = format_channel_id(462.5625)
        text = "\n".join(lines)
        assert "FRS" in text
        assert "Channel 1" in text

    def test_channel_id_unknown(self):
        """Unknown freq output says not recognized."""
        lines = format_channel_id(155.0)
        text = "\n".join(lines)
        assert "not a recognized" in text
