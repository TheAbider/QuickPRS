"""Tests for import wizard data flow (non-GUI logic).

Tests the underlying data loading, format detection, and preview
generation used by the Import Wizard. Does not test tkinter UI.
"""

import pytest
import csv
from pathlib import Path

from quickprs.scanner_import import (
    detect_scanner_format,
    import_scanner_csv,
    import_dsd_freqs,
    import_sdrtrunk_tgs,
)
from quickprs.templates import get_template_names, get_template_channels
from quickprs.system_database import (
    search_systems, list_all_systems, get_system_by_name,
    get_iden_template_key,
)
from quickprs.radioreference import (
    parse_pasted_talkgroups, parse_pasted_frequencies,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Format detection for wizard ─────────────────────────────────────


class TestWizardFormatDetection:
    """Test format auto-detection used by the File tab."""

    def test_detect_chirp(self):
        assert detect_scanner_format(TESTDATA / "test_chirp.csv") == 'chirp'

    def test_detect_uniden(self):
        assert detect_scanner_format(TESTDATA / "test_uniden.csv") == 'uniden'

    def test_detect_sdrtrunk(self, tmp_path):
        sdr = tmp_path / "sdr.csv"
        sdr.write_text("System,Channel,Frequency,Protocol\nTest,CH1,460.050,P25\n")
        assert detect_scanner_format(str(sdr)) == 'sdrtrunk'

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_detect_unknown_for_prs(self):
        assert detect_scanner_format(PAWS) == 'unknown'

    def test_detect_freq_list(self, tmp_path):
        """Plain frequency list should be 'unknown' for scanner detect
        but loadable as DSD+/freq_list."""
        freq_file = tmp_path / "freqs.txt"
        freq_file.write_text("851012500\n852012500\n853012500\n")
        # Scanner detect sees it as unknown
        assert detect_scanner_format(str(freq_file)) == 'unknown'
        # But DSD+ import works
        channels = import_dsd_freqs(str(freq_file))
        assert len(channels) == 3

    def test_detect_quickprs_csv(self, tmp_path):
        """QuickPRS CSV with group_id should be detected by csv_import."""
        from quickprs.csv_import import import_csv
        qp = tmp_path / "tgs.csv"
        qp.write_text("group_id,short_name,long_name\n1000,PD DISP,PD DISPATCH\n")
        data_type, objects = import_csv(str(qp))
        assert data_type == "groups"


# ─── File import data loading ────────────────────────────────────────


class TestWizardFileLoading:
    """Test file loading for different formats."""

    def test_load_chirp(self):
        channels = import_scanner_csv(TESTDATA / "test_chirp.csv", fmt='chirp')
        assert len(channels) > 0
        assert 'short_name' in channels[0]
        assert 'tx_freq' in channels[0]

    def test_load_uniden(self):
        channels = import_scanner_csv(TESTDATA / "test_uniden.csv", fmt='uniden')
        assert len(channels) > 0
        assert 'short_name' in channels[0]

    def test_load_dsd_freqs(self, tmp_path):
        freq_file = tmp_path / "freqs.txt"
        freq_file.write_text("851012500\n852012500\n853012500\n")
        channels = import_dsd_freqs(str(freq_file))
        assert len(channels) == 3
        # Should be converted to MHz
        assert channels[0]['tx_freq'] == pytest.approx(851.0125, abs=0.001)

    def test_load_sdrtrunk_tgs(self, tmp_path):
        tg_file = tmp_path / "tgs.csv"
        tg_file.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n"
            "1000,3E8,PD DISP,T,PD Dispatch,Law Dispatch,Police\n"
            "2000,7D0,FD DISP,T,FD Dispatch,Fire Dispatch,Fire\n"
        )
        tgs = import_sdrtrunk_tgs(str(tg_file))
        assert len(tgs) == 2
        assert tgs[0]['group_id'] == 1000
        assert tgs[0]['short_name'] == 'PD DISP'

    def test_load_auto_detect(self):
        channels = import_scanner_csv(TESTDATA / "test_chirp.csv")
        assert len(channels) > 0


# ─── Template preview generation ─────────────────────────────────────


class TestWizardTemplatePreview:
    """Test template channel loading for the Template tab."""

    def test_template_names_not_empty(self):
        names = get_template_names()
        assert len(names) > 0

    def test_all_templates_loadable(self):
        for name in get_template_names():
            channels = get_template_channels(name)
            assert isinstance(channels, list)
            assert len(channels) > 0

    def test_murs_has_5_channels(self):
        channels = get_template_channels('murs')
        assert len(channels) == 5

    def test_gmrs_has_22_channels(self):
        channels = get_template_channels('gmrs')
        assert len(channels) == 22

    def test_frs_has_22_channels(self):
        channels = get_template_channels('frs')
        assert len(channels) == 22

    def test_noaa_has_7_channels(self):
        channels = get_template_channels('noaa')
        assert len(channels) == 7

    def test_weather_alias_same_as_noaa(self):
        noaa = get_template_channels('noaa')
        weather = get_template_channels('weather')
        assert len(noaa) == len(weather)

    def test_template_channels_have_required_keys(self):
        for name in get_template_names():
            channels = get_template_channels(name)
            for ch in channels:
                assert 'short_name' in ch, \
                    f"Template {name} channel missing short_name"
                assert 'tx_freq' in ch, \
                    f"Template {name} channel missing tx_freq"

    def test_template_frequencies_positive(self):
        for name in get_template_names():
            channels = get_template_channels(name)
            for ch in channels:
                assert ch['tx_freq'] > 0, \
                    f"Template {name}: invalid freq {ch['tx_freq']}"

    def test_invalid_template_raises(self):
        with pytest.raises(ValueError):
            get_template_channels('nonexistent_template')


# ─── Database search for wizard ──────────────────────────────────────


class TestWizardDatabaseSearch:
    """Test system database search for the Database tab."""

    def test_list_all_not_empty(self):
        systems = list_all_systems()
        assert len(systems) > 0

    def test_search_by_name(self):
        results = search_systems("PSERN")
        assert len(results) >= 1
        assert any(s.name == "PSERN" for s in results)

    def test_search_by_state(self):
        results = search_systems("WA")
        assert len(results) >= 1
        # "WA" matches state, location, or description text
        wa_systems = [s for s in results if s.state == "WA"]
        assert len(wa_systems) >= 1

    def test_search_by_id(self):
        results = search_systems("892")
        assert len(results) >= 1

    def test_search_empty_returns_all(self):
        results = search_systems("")
        assert len(results) > 0

    def test_search_no_match(self):
        results = search_systems("ZZZZNONEXISTENT")
        assert len(results) == 0

    def test_get_system_by_name_found(self):
        sys = get_system_by_name("PSERN")
        assert sys is not None
        assert sys.name == "PSERN"

    def test_get_system_by_name_not_found(self):
        sys = get_system_by_name("NONEXISTENT")
        assert sys is None

    def test_iden_template_key(self):
        sys = get_system_by_name("PSERN")
        key = get_iden_template_key(sys)
        assert key in ("800-TDMA", "800-FDMA", "700-TDMA", "700-FDMA")


# ─── Clipboard parsing for wizard ────────────────────────────────────


class TestWizardClipboardParsing:
    """Test clipboard data parsing for the Clipboard tab."""

    def test_parse_talkgroups_basic(self):
        text = (
            "DEC\tHEX\tAlpha Tag\tDescription\n"
            "1000\t3E8\tPD DISP\tPolice Dispatch\n"
            "2000\t7D0\tFD DISP\tFire Dispatch\n"
        )
        tgs = parse_pasted_talkgroups(text)
        assert len(tgs) >= 2

    def test_parse_talkgroups_empty(self):
        tgs = parse_pasted_talkgroups("")
        assert tgs == []

    def test_parse_talkgroups_whitespace_only(self):
        tgs = parse_pasted_talkgroups("   \n\n  ")
        assert tgs == []

    def test_parse_frequencies_basic(self):
        text = "851.0125\n851.5125\n852.0125\n"
        freqs = parse_pasted_frequencies(text)
        assert len(freqs) >= 3

    def test_parse_frequencies_empty(self):
        freqs = parse_pasted_frequencies("")
        assert freqs == []

    def test_parse_frequencies_with_labels(self):
        text = "851.0125 Site 1\n851.5125 Site 2\n"
        freqs = parse_pasted_frequencies(text)
        assert len(freqs) >= 2

    def test_clipboard_auto_detect_tgs_vs_freqs(self):
        """Talkgroup text should parse as talkgroups, not frequencies."""
        tg_text = (
            "DEC\tHEX\tAlpha Tag\tDescription\n"
            "1000\t3E8\tPD DISP\tPolice Dispatch\n"
        )
        tgs = parse_pasted_talkgroups(tg_text)
        freqs = parse_pasted_frequencies(tg_text)
        # Talkgroups should be the better match
        assert len(tgs) >= len(freqs)


# ─── Preview data integration ────────────────────────────────────────


class TestWizardPreviewIntegration:
    """Test that preview data flows correctly for import."""

    def test_chirp_channels_have_all_fields(self):
        """CHIRP import should produce complete channel dicts."""
        channels = import_scanner_csv(TESTDATA / "test_chirp.csv", fmt='chirp')
        for ch in channels:
            assert 'short_name' in ch
            assert 'tx_freq' in ch
            assert 'rx_freq' in ch
            assert 'long_name' in ch
            assert ch['tx_freq'] > 0
            assert ch['rx_freq'] > 0

    def test_uniden_channels_have_all_fields(self):
        """Uniden import should produce complete channel dicts."""
        channels = import_scanner_csv(TESTDATA / "test_uniden.csv", fmt='uniden')
        for ch in channels:
            assert 'short_name' in ch
            assert 'tx_freq' in ch
            assert 'rx_freq' in ch
            assert ch['tx_freq'] > 0

    def test_template_channels_convertible(self):
        """Template channels should be convertible to import format."""
        for name in ('murs', 'gmrs', 'frs', 'noaa'):
            channels = get_template_channels(name)
            for ch in channels:
                # Ensure we can build an import dict
                import_ch = {
                    'short_name': ch['short_name'][:8],
                    'tx_freq': ch['tx_freq'],
                    'rx_freq': ch.get('rx_freq', ch['tx_freq']),
                    'tx_tone': ch.get('tx_tone', ''),
                    'rx_tone': ch.get('rx_tone', ''),
                    'long_name': ch.get('long_name', '')[:16],
                }
                assert import_ch['tx_freq'] > 0

    def test_database_system_has_injection_fields(self):
        """Database systems should have all fields needed for injection."""
        sys = get_system_by_name("PSERN")
        assert sys.name
        assert sys.system_id > 0
        assert sys.wacn > 0
        assert sys.band
        assert sys.system_type
