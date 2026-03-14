"""Tests for channel templates and template-based injection."""

import pytest
from pathlib import Path

from quickprs.templates import (
    get_murs_channels, get_gmrs_channels, get_frs_channels,
    get_marine_channels, get_noaa_channels,
    get_interop_channels, get_public_safety_channels,
    get_template_channels, get_template_names,
    TEMPLATE_REGISTRY,
)


# ─── Template data correctness ────────────────────────────────────────


class TestMursTemplate:
    """Test MURS channel data."""

    def test_murs_count(self):
        """MURS has exactly 5 channels."""
        channels = get_murs_channels()
        assert len(channels) == 5

    def test_murs_frequencies(self):
        """MURS frequencies match FCC Part 95."""
        channels = get_murs_channels()
        freqs = [ch['tx_freq'] for ch in channels]
        assert freqs == [151.820, 151.880, 151.940, 154.570, 154.600]

    def test_murs_short_names(self):
        """MURS short names are 8 chars or less."""
        for ch in get_murs_channels():
            assert len(ch['short_name']) <= 8

    def test_murs_has_long_names(self):
        """Each MURS channel has a long_name."""
        for ch in get_murs_channels():
            assert ch['long_name']
            assert len(ch['long_name']) <= 16

    def test_murs_has_required_keys(self):
        """Each channel has the required keys for make_conv_set."""
        for ch in get_murs_channels():
            assert 'short_name' in ch
            assert 'tx_freq' in ch
            assert 'long_name' in ch


class TestGmrsTemplate:
    """Test GMRS channel data."""

    def test_gmrs_count(self):
        """GMRS has exactly 22 channels."""
        channels = get_gmrs_channels()
        assert len(channels) == 22

    def test_gmrs_short_names_length(self):
        """All GMRS short names are 8 chars or less."""
        for ch in get_gmrs_channels():
            assert len(ch['short_name']) <= 8

    def test_gmrs_ch1_freq(self):
        """Channel 1 is 462.5625 MHz."""
        channels = get_gmrs_channels()
        assert channels[0]['tx_freq'] == 462.5625

    def test_gmrs_ch8_freq(self):
        """Channel 8 is 467.5625 MHz (interstitial)."""
        channels = get_gmrs_channels()
        assert channels[7]['tx_freq'] == 467.5625

    def test_gmrs_ch15_freq(self):
        """Channel 15 is 462.5500 MHz (GMRS only)."""
        channels = get_gmrs_channels()
        assert channels[14]['tx_freq'] == 462.5500

    def test_gmrs_ch22_freq(self):
        """Channel 22 is 462.7250 MHz."""
        channels = get_gmrs_channels()
        assert channels[21]['tx_freq'] == 462.7250

    def test_gmrs_has_long_names(self):
        """Each GMRS channel has a long name."""
        for ch in get_gmrs_channels():
            assert ch['long_name']
            assert len(ch['long_name']) <= 16

    def test_gmrs_frequencies_in_range(self):
        """All GMRS freqs are in 462-468 MHz range."""
        for ch in get_gmrs_channels():
            assert 462.0 <= ch['tx_freq'] <= 468.0


class TestFrsTemplate:
    """Test FRS channel data."""

    def test_frs_count(self):
        """FRS has exactly 22 channels."""
        channels = get_frs_channels()
        assert len(channels) == 22

    def test_frs_short_names_length(self):
        """All FRS short names are 8 chars or less."""
        for ch in get_frs_channels():
            assert len(ch['short_name']) <= 8

    def test_frs_ch1_freq(self):
        """FRS channel 1 is 462.5625 MHz."""
        channels = get_frs_channels()
        assert channels[0]['tx_freq'] == 462.5625

    def test_frs_shares_freqs_with_gmrs(self):
        """FRS channels 1-7 share frequencies with GMRS 1-7."""
        frs = get_frs_channels()
        gmrs = get_gmrs_channels()
        for i in range(7):
            assert frs[i]['tx_freq'] == gmrs[i]['tx_freq']

    def test_frs_has_long_names(self):
        """Each FRS channel has a long name."""
        for ch in get_frs_channels():
            assert ch['long_name']


class TestMarineTemplate:
    """Test Marine VHF channel data."""

    def test_marine_count(self):
        """Marine template has at least 10 channels."""
        channels = get_marine_channels()
        assert len(channels) >= 10

    def test_marine_ch16_present(self):
        """Channel 16 (distress/calling) must be present."""
        channels = get_marine_channels()
        ch16 = [ch for ch in channels if ch['short_name'] == 'MAR 16']
        assert len(ch16) == 1
        assert ch16[0]['tx_freq'] == 156.800

    def test_marine_ch9_present(self):
        """Channel 9 (secondary calling) must be present."""
        channels = get_marine_channels()
        ch9 = [ch for ch in channels if ch['short_name'] == 'MAR  9']
        assert len(ch9) == 1
        assert ch9[0]['tx_freq'] == 156.450

    def test_marine_short_names_length(self):
        """All marine short names are 8 chars or less."""
        for ch in get_marine_channels():
            assert len(ch['short_name']) <= 8

    def test_marine_frequencies_in_range(self):
        """All marine freqs are in 156-158 MHz range."""
        for ch in get_marine_channels():
            assert 156.0 <= ch['tx_freq'] <= 158.0

    def test_marine_has_long_names(self):
        """Each marine channel has a long name."""
        for ch in get_marine_channels():
            assert ch['long_name']
            assert len(ch['long_name']) <= 16


class TestNoaaTemplate:
    """Test NOAA Weather Radio channel data."""

    def test_noaa_count(self):
        """NOAA has exactly 7 channels."""
        channels = get_noaa_channels()
        assert len(channels) == 7

    def test_noaa_frequencies(self):
        """NOAA frequencies are the standard 7."""
        channels = get_noaa_channels()
        freqs = [ch['tx_freq'] for ch in channels]
        assert freqs == [162.400, 162.425, 162.450, 162.475,
                         162.500, 162.525, 162.550]

    def test_noaa_short_names_length(self):
        """All NOAA short names are 8 chars or less."""
        for ch in get_noaa_channels():
            assert len(ch['short_name']) <= 8

    def test_noaa_has_long_names(self):
        """Each NOAA channel has a long name."""
        for ch in get_noaa_channels():
            assert ch['long_name']
            assert len(ch['long_name']) <= 16

    def test_noaa_frequencies_in_range(self):
        """All NOAA freqs are in 162.x MHz range."""
        for ch in get_noaa_channels():
            assert 162.0 <= ch['tx_freq'] <= 163.0


# ─── Template registry ────────────────────────────────────────────────


class TestTemplateRegistry:
    """Test the template registry and lookup functions."""

    def test_registry_has_all_templates(self):
        """Registry should have 8 templates (5 original + weather alias + interop + public_safety)."""
        assert len(TEMPLATE_REGISTRY) == 8

    def test_get_template_names(self):
        """get_template_names returns sorted list."""
        names = get_template_names()
        assert names == sorted(names)
        assert 'murs' in names
        assert 'gmrs' in names
        assert 'frs' in names
        assert 'marine' in names
        assert 'noaa' in names
        assert 'weather' in names
        assert 'interop' in names
        assert 'public_safety' in names

    def test_get_template_channels_murs(self):
        """get_template_channels('murs') returns MURS data."""
        channels = get_template_channels('murs')
        assert len(channels) == 5
        assert channels[0]['tx_freq'] == 151.820

    def test_get_template_channels_case_insensitive(self):
        """Template lookup should be case-insensitive."""
        ch_lower = get_template_channels('murs')
        ch_upper = get_template_channels('MURS')
        ch_mixed = get_template_channels('Murs')
        assert ch_lower == ch_upper == ch_mixed

    def test_get_template_channels_unknown(self):
        """Unknown template should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown template"):
            get_template_channels('nonexistent')

    def test_get_template_channels_shows_available(self):
        """Error message should list available templates."""
        with pytest.raises(ValueError, match="murs"):
            get_template_channels('bad')

    def test_all_templates_return_valid_data(self):
        """Every registered template should return non-empty list of dicts."""
        for name in get_template_names():
            channels = get_template_channels(name)
            assert len(channels) > 0
            for ch in channels:
                assert isinstance(ch, dict)
                assert 'short_name' in ch
                assert 'tx_freq' in ch
                assert isinstance(ch['tx_freq'], float)
                assert ch['tx_freq'] > 0

    def test_all_short_names_within_limit(self):
        """Every template channel short_name must be <= 8 chars."""
        for name in get_template_names():
            for ch in get_template_channels(name):
                assert len(ch['short_name']) <= 8, \
                    f"Template '{name}': '{ch['short_name']}' exceeds 8 chars"

    def test_all_long_names_within_limit(self):
        """Every template channel long_name must be <= 16 chars."""
        for name in get_template_names():
            for ch in get_template_channels(name):
                assert len(ch['long_name']) <= 16, \
                    f"Template '{name}': '{ch['long_name']}' exceeds 16 chars"

    def test_no_duplicate_frequencies_within_template(self):
        """No duplicate frequencies within a single template."""
        for name in get_template_names():
            channels = get_template_channels(name)
            freqs = [ch['tx_freq'] for ch in channels]
            assert len(freqs) == len(set(freqs)), \
                f"Template '{name}' has duplicate frequencies"


# ─── Weather alias ───────────────────────────────────────────────────


class TestWeatherAlias:
    """Test 'weather' alias for NOAA template."""

    def test_weather_returns_noaa_data(self):
        """'weather' template returns same data as 'noaa'."""
        weather = get_template_channels('weather')
        noaa = get_template_channels('noaa')
        assert weather == noaa

    def test_weather_case_insensitive(self):
        """Weather alias is case-insensitive."""
        w1 = get_template_channels('WEATHER')
        w2 = get_template_channels('weather')
        assert w1 == w2


# ─── Interop template ────────────────────────────────────────────────


class TestInteropTemplate:
    """Test National Interoperability channel data."""

    def test_interop_count(self):
        """Interop has exactly 20 channels (5 VHF + 5 UHF + 5 800 + 5 700)."""
        channels = get_interop_channels()
        assert len(channels) == 20

    def test_interop_short_names_length(self):
        """All interop short names are 8 chars or less."""
        for ch in get_interop_channels():
            assert len(ch['short_name']) <= 8, \
                f"'{ch['short_name']}' exceeds 8 chars"

    def test_interop_long_names_length(self):
        """All interop long names are 16 chars or less."""
        for ch in get_interop_channels():
            assert len(ch['long_name']) <= 16, \
                f"'{ch['long_name']}' exceeds 16 chars"

    def test_interop_vcall10_present(self):
        """VCALL10 (VHF calling) must be present at 155.7525 MHz."""
        channels = get_interop_channels()
        vcall = [ch for ch in channels if ch['short_name'] == 'VCALL10']
        assert len(vcall) == 1
        assert vcall[0]['tx_freq'] == 155.7525

    def test_interop_ucall40_present(self):
        """UCALL40 (UHF calling) must be present at 453.2125 MHz."""
        channels = get_interop_channels()
        ucall = [ch for ch in channels if ch['short_name'] == 'UCALL40']
        assert len(ucall) == 1
        assert ucall[0]['tx_freq'] == 453.2125

    def test_interop_8call90_present(self):
        """8CALL90 (800 MHz calling) must be present at 866.0125 MHz."""
        channels = get_interop_channels()
        call800 = [ch for ch in channels if ch['short_name'] == '8CALL90']
        assert len(call800) == 1
        assert call800[0]['tx_freq'] == 866.0125

    def test_interop_7call50_present(self):
        """7CALL50 (700 MHz calling) must be present at 769.24375 MHz."""
        channels = get_interop_channels()
        call700 = [ch for ch in channels if ch['short_name'] == '7CALL50']
        assert len(call700) == 1
        assert call700[0]['tx_freq'] == 769.24375

    def test_interop_vhf_channels(self):
        """Interop has 5 VHF channels (VCALL10 + VTAC11-14)."""
        channels = get_interop_channels()
        vhf = [ch for ch in channels
               if ch['short_name'].startswith('V')]
        assert len(vhf) == 5

    def test_interop_uhf_channels(self):
        """Interop has 5 UHF channels (UCALL40 + UTAC41-44)."""
        channels = get_interop_channels()
        uhf = [ch for ch in channels
               if ch['short_name'].startswith('U')]
        assert len(uhf) == 5

    def test_interop_800_channels(self):
        """Interop has 5 800 MHz channels (8CALL90 + 8TAC91-94)."""
        channels = get_interop_channels()
        ch800 = [ch for ch in channels
                 if ch['short_name'].startswith('8')]
        assert len(ch800) == 5

    def test_interop_700_channels(self):
        """Interop has 5 700 MHz channels (7CALL50 + 7TAC51-54)."""
        channels = get_interop_channels()
        ch700 = [ch for ch in channels
                 if ch['short_name'].startswith('7')]
        assert len(ch700) == 5

    def test_interop_vhf_tones(self):
        """VHF interop channels use 156.7 Hz CTCSS tone."""
        channels = get_interop_channels()
        for ch in channels:
            if ch['short_name'].startswith('V'):
                assert ch.get('tx_tone') == '156.7'
                assert ch.get('rx_tone') == '156.7'

    def test_interop_uhf_tones(self):
        """UHF interop channels use 156.7 Hz CTCSS tone."""
        channels = get_interop_channels()
        for ch in channels:
            if ch['short_name'].startswith('U'):
                assert ch.get('tx_tone') == '156.7'
                assert ch.get('rx_tone') == '156.7'

    def test_interop_no_duplicate_freqs(self):
        """No duplicate frequencies in interop template."""
        channels = get_interop_channels()
        freqs = [ch['tx_freq'] for ch in channels]
        assert len(freqs) == len(set(freqs))

    def test_interop_has_required_keys(self):
        """Each interop channel has required keys."""
        for ch in get_interop_channels():
            assert 'short_name' in ch
            assert 'tx_freq' in ch
            assert 'long_name' in ch

    def test_interop_lookup_by_name(self):
        """get_template_channels('interop') returns data."""
        channels = get_template_channels('interop')
        assert len(channels) == 20


# ─── Public Safety template ──────────────────────────────────────────


class TestPublicSafetyTemplate:
    """Test public safety simplex frequency data."""

    def test_public_safety_count(self):
        """Public safety has 10 channels."""
        channels = get_public_safety_channels()
        assert len(channels) == 10

    def test_public_safety_short_names_length(self):
        """All public safety short names are 8 chars or less."""
        for ch in get_public_safety_channels():
            assert len(ch['short_name']) <= 8

    def test_public_safety_long_names_length(self):
        """All public safety long names are 16 chars or less."""
        for ch in get_public_safety_channels():
            assert len(ch['long_name']) <= 16

    def test_public_safety_has_vhf(self):
        """Public safety includes VHF channels."""
        channels = get_public_safety_channels()
        vhf = [ch for ch in channels if ch['tx_freq'] < 200.0]
        assert len(vhf) >= 4

    def test_public_safety_has_uhf(self):
        """Public safety includes UHF channels."""
        channels = get_public_safety_channels()
        uhf = [ch for ch in channels if ch['tx_freq'] > 400.0]
        assert len(uhf) >= 3

    def test_public_safety_fire_channel(self):
        """Fire simplex at 154.2800 MHz must be present."""
        channels = get_public_safety_channels()
        fire = [ch for ch in channels
                if ch['short_name'] == 'FIRE VH']
        assert len(fire) == 1
        assert fire[0]['tx_freq'] == 154.2800

    def test_public_safety_no_duplicate_freqs(self):
        """No duplicate frequencies in public safety template."""
        channels = get_public_safety_channels()
        freqs = [ch['tx_freq'] for ch in channels]
        assert len(freqs) == len(set(freqs))

    def test_public_safety_has_required_keys(self):
        """Each public safety channel has required keys."""
        for ch in get_public_safety_channels():
            assert 'short_name' in ch
            assert 'tx_freq' in ch
            assert 'long_name' in ch

    def test_public_safety_lookup_by_name(self):
        """get_template_channels('public_safety') returns data."""
        channels = get_template_channels('public_safety')
        assert len(channels) == 10
