"""Tests for scanner format import (Uniden, CHIRP, SDRTrunk)."""

import pytest
import shutil
import tempfile
from pathlib import Path

from quickprs.scanner_import import (
    detect_scanner_format,
    import_uniden_csv,
    import_chirp_csv,
    import_sdrtrunk_csv,
    import_scanner_csv,
)

TESTDATA = Path(__file__).parent / "testdata"
UNIDEN_CSV = TESTDATA / "test_uniden.csv"
CHIRP_CSV = TESTDATA / "test_chirp.csv"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Format auto-detection ────────────────────────────────────────────


class TestDetectFormat:
    """Test auto-detection of scanner CSV formats."""

    def test_detect_uniden(self):
        assert detect_scanner_format(UNIDEN_CSV) == 'uniden'

    def test_detect_chirp(self):
        assert detect_scanner_format(CHIRP_CSV) == 'chirp'

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_detect_unknown_for_prs(self):
        """Non-CSV file should return unknown."""
        assert detect_scanner_format(PAWS) == 'unknown'

    def test_detect_nonexistent_file(self):
        assert detect_scanner_format("/nonexistent/file.csv") == 'unknown'

    def test_detect_empty_csv(self, tmp_path):
        """Empty file should return unknown."""
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        assert detect_scanner_format(str(empty)) == 'unknown'

    def test_detect_generic_csv(self, tmp_path):
        """CSV without scanner markers should return unknown."""
        generic = tmp_path / "generic.csv"
        generic.write_text("col_a,col_b,col_c\n1,2,3\n")
        assert detect_scanner_format(str(generic)) == 'unknown'

    def test_detect_sdrtrunk(self, tmp_path):
        """SDRTrunk format should be detected by protocol+frequency."""
        sdr = tmp_path / "sdr.csv"
        sdr.write_text(
            "System,Channel,Frequency,Protocol\n"
            "Test,CH1,460.050,P25\n")
        assert detect_scanner_format(str(sdr)) == 'sdrtrunk'


# ─── Uniden import ─────────────────────────────────────────────────────


class TestUnidenImport:
    """Test Uniden Sentinel CSV import."""

    def test_import_uniden_basic(self):
        channels = import_uniden_csv(UNIDEN_CSV)
        assert len(channels) == 5

    def test_uniden_channel_names(self):
        channels = import_uniden_csv(UNIDEN_CSV)
        names = [ch['short_name'] for ch in channels]
        assert "PD DISP" in names
        assert "FD DISP" in names
        assert "HP CH1" in names

    def test_uniden_frequencies(self):
        channels = import_uniden_csv(UNIDEN_CSV)
        freqs = [ch['tx_freq'] for ch in channels]
        assert 460.0500 in freqs
        assert 155.4700 in freqs

    def test_uniden_tone(self):
        channels = import_uniden_csv(UNIDEN_CSV)
        pd_disp = [ch for ch in channels
                    if ch['short_name'] == "PD DISP"][0]
        assert pd_disp['tx_tone'] == "100.0"

    def test_uniden_system_name(self):
        channels = import_uniden_csv(UNIDEN_CSV)
        pd_disp = [ch for ch in channels
                    if ch['short_name'] == "PD DISP"][0]
        assert pd_disp['system_name'] == "County PD"

    def test_uniden_short_name_truncated(self):
        """Short names should be max 8 chars."""
        channels = import_uniden_csv(UNIDEN_CSV)
        for ch in channels:
            assert len(ch['short_name']) <= 8

    def test_uniden_long_name_truncated(self):
        """Long names should be max 16 chars."""
        channels = import_uniden_csv(UNIDEN_CSV)
        for ch in channels:
            assert len(ch['long_name']) <= 16


# ─── CHIRP import ──────────────────────────────────────────────────────


class TestChirpImport:
    """Test CHIRP CSV import."""

    def test_import_chirp_basic(self):
        channels = import_chirp_csv(CHIRP_CSV)
        assert len(channels) == 5

    def test_chirp_channel_names(self):
        channels = import_chirp_csv(CHIRP_CSV)
        names = [ch['short_name'] for ch in channels]
        assert "RPT IN" in names
        assert "SIMPLEX" in names
        assert "NOAA" in names

    def test_chirp_duplex_minus(self):
        """Duplex '-' should subtract offset from freq for TX."""
        channels = import_chirp_csv(CHIRP_CSV)
        rpt_in = [ch for ch in channels
                   if ch['short_name'] == "RPT IN"][0]
        # Freq=146.84, Duplex=-, Offset=0.6 -> TX=146.24
        assert abs(rpt_in['tx_freq'] - 146.24) < 0.001
        assert abs(rpt_in['rx_freq'] - 146.84) < 0.001

    def test_chirp_duplex_plus(self):
        """Duplex '+' should add offset to freq for TX."""
        channels = import_chirp_csv(CHIRP_CSV)
        rpt_out = [ch for ch in channels
                    if ch['short_name'] == "RPT OUT"][0]
        # Freq=146.24, Duplex=+, Offset=0.6 -> TX=146.84
        assert abs(rpt_out['tx_freq'] - 146.84) < 0.001
        assert abs(rpt_out['rx_freq'] - 146.24) < 0.001

    def test_chirp_simplex(self):
        """No duplex = simplex (TX=RX)."""
        channels = import_chirp_csv(CHIRP_CSV)
        noaa = [ch for ch in channels
                if ch['short_name'] == "NOAA"][0]
        assert noaa['tx_freq'] == noaa['rx_freq']

    def test_chirp_tone_mode(self):
        """Tone mode 'Tone' uses rToneFreq for TX."""
        channels = import_chirp_csv(CHIRP_CSV)
        rpt_in = [ch for ch in channels
                   if ch['short_name'] == "RPT IN"][0]
        assert rpt_in['tx_tone'] == "100.0"
        assert rpt_in['rx_tone'] == ""

    def test_chirp_tsql_mode(self):
        """Tone mode 'TSQL' uses cToneFreq for both TX and RX."""
        channels = import_chirp_csv(CHIRP_CSV)
        simplex = [ch for ch in channels
                    if ch['short_name'] == "SIMPLEX"][0]
        assert simplex['tx_tone'] == "100.0"
        assert simplex['rx_tone'] == "100.0"

    def test_chirp_dtcs_mode(self):
        """Tone mode 'DTCS' uses DtcsCode with D prefix."""
        channels = import_chirp_csv(CHIRP_CSV)
        dtcs = [ch for ch in channels
                if ch['short_name'] == "DTCS CH"][0]
        assert dtcs['tx_tone'] == "D023"
        assert dtcs['rx_tone'] == "D023"


# ─── Auto-detect and import ───────────────────────────────────────────


class TestImportScannerCsv:
    """Test the unified import_scanner_csv function."""

    def test_auto_detect_uniden(self):
        channels = import_scanner_csv(UNIDEN_CSV)
        assert len(channels) == 5

    def test_auto_detect_chirp(self):
        channels = import_scanner_csv(CHIRP_CSV)
        assert len(channels) == 5

    def test_explicit_format_uniden(self):
        channels = import_scanner_csv(UNIDEN_CSV, fmt='uniden')
        assert len(channels) == 5

    def test_explicit_format_chirp(self):
        channels = import_scanner_csv(CHIRP_CSV, fmt='chirp')
        assert len(channels) == 5

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            import_scanner_csv("/nonexistent/file.csv")

    def test_unknown_format_raises(self, tmp_path):
        """Unknown format should raise ValueError."""
        unknown = tmp_path / "unknown.csv"
        unknown.write_text("a,b,c\n1,2,3\n")
        with pytest.raises(ValueError, match="Cannot detect"):
            import_scanner_csv(str(unknown))

    def test_channel_dict_keys(self):
        """All channel dicts should have required keys."""
        channels = import_scanner_csv(UNIDEN_CSV)
        required = {'short_name', 'tx_freq', 'rx_freq',
                     'tx_tone', 'rx_tone', 'long_name'}
        for ch in channels:
            assert required.issubset(ch.keys()), (
                f"Missing keys: {required - ch.keys()}")


# ─── SDRTrunk import ──────────────────────────────────────────────────


class TestSdrtrunkImport:
    """Test SDRTrunk CSV import."""

    def test_import_sdrtrunk(self, tmp_path):
        sdr = tmp_path / "sdr.csv"
        sdr.write_text(
            "System,Channel,Frequency,Protocol\n"
            "County PD,Dispatch,460.050,P25\n"
            "County PD,Tactical,460.125,P25\n"
            "County FD,Dispatch,460.550,P25\n")
        channels = import_sdrtrunk_csv(str(sdr))
        assert len(channels) == 3
        assert channels[0]['short_name'] == "DISPATCH"
        assert channels[0]['tx_freq'] == 460.050
        assert channels[0]['system_name'] == "County PD"

    def test_sdrtrunk_empty(self, tmp_path):
        sdr = tmp_path / "sdr.csv"
        sdr.write_text("System,Channel,Frequency,Protocol\n")
        channels = import_sdrtrunk_csv(str(sdr))
        assert len(channels) == 0


# ─── CLI import-scanner ───────────────────────────────────────────────


class TestCliImportScanner:
    """Test the import-scanner CLI command."""

    def test_cli_import_uniden(self, capsys, tmp_path):
        """Import Uniden CSV via CLI."""
        from quickprs.cli import run_cli, cmd_create

        prs_file = tmp_path / "test.PRS"
        cmd_create(str(prs_file))

        result = run_cli([
            "import-scanner", str(prs_file),
            "--csv", str(UNIDEN_CSV),
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "5 channels" in out
        assert "uniden" in out.lower()

    def test_cli_import_chirp(self, capsys, tmp_path):
        """Import CHIRP CSV via CLI."""
        from quickprs.cli import run_cli, cmd_create

        prs_file = tmp_path / "test.PRS"
        cmd_create(str(prs_file))

        result = run_cli([
            "import-scanner", str(prs_file),
            "--csv", str(CHIRP_CSV),
            "--format", "chirp",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "5 channels" in out

    def test_cli_import_with_name(self, capsys, tmp_path):
        """Custom set name via --name."""
        from quickprs.cli import run_cli, cmd_create

        prs_file = tmp_path / "test.PRS"
        cmd_create(str(prs_file))

        result = run_cli([
            "import-scanner", str(prs_file),
            "--csv", str(UNIDEN_CSV),
            "--name", "COUNTY",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "COUNTY" in out

    def test_cli_import_with_output(self, capsys, tmp_path):
        """Output to different file."""
        from quickprs.cli import run_cli, cmd_create

        prs_file = tmp_path / "input.PRS"
        out_file = tmp_path / "output.PRS"
        cmd_create(str(prs_file))

        result = run_cli([
            "import-scanner", str(prs_file),
            "--csv", str(UNIDEN_CSV),
            "-o", str(out_file),
        ])
        assert result == 0
        assert out_file.exists()

    def test_cli_import_unknown_format(self, capsys, tmp_path):
        """Unknown CSV format should fail."""
        from quickprs.cli import run_cli, cmd_create

        prs_file = tmp_path / "test.PRS"
        cmd_create(str(prs_file))

        unknown = tmp_path / "unknown.csv"
        unknown.write_text("a,b,c\n1,2,3\n")

        result = run_cli([
            "import-scanner", str(prs_file),
            "--csv", str(unknown),
        ])
        assert result == 1


# ─── Roundtrip after import ───────────────────────────────────────────


class TestImportRoundtrip:
    """Verify PRS roundtrip integrity after scanner import."""

    def test_roundtrip_after_uniden_import(self, tmp_path):
        """Import Uniden CSV, save, reload, verify channels present."""
        from quickprs.cli import cmd_create
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs
        from quickprs.scanner_import import import_scanner_csv
        from quickprs.injector import add_conv_system, make_conv_set
        from quickprs.record_types import ConvSystemConfig

        prs_file = tmp_path / "roundtrip.PRS"
        cmd_create(str(prs_file))

        prs = parse_prs(prs_file)
        channels = import_scanner_csv(UNIDEN_CSV)
        assert len(channels) == 5

        conv_set = make_conv_set("SCANNER", channels)
        config = ConvSystemConfig(
            system_name="SCANNER",
            long_name="SCANNER",
            conv_set_name="SCANNER",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        # Save
        write_prs(prs, str(prs_file))

        # Reload and verify
        prs2 = parse_prs(prs_file)
        bytes1 = prs.to_bytes()
        bytes2 = prs2.to_bytes()
        assert bytes1 == bytes2

    def test_roundtrip_after_chirp_import(self, tmp_path):
        """Import CHIRP CSV, save, reload, verify bytes match."""
        from quickprs.cli import cmd_create
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs
        from quickprs.scanner_import import import_scanner_csv
        from quickprs.injector import add_conv_system, make_conv_set
        from quickprs.record_types import ConvSystemConfig

        prs_file = tmp_path / "roundtrip.PRS"
        cmd_create(str(prs_file))

        prs = parse_prs(prs_file)
        channels = import_scanner_csv(CHIRP_CSV)
        conv_set = make_conv_set("CHIRP", channels)
        config = ConvSystemConfig(
            system_name="CHIRP",
            long_name="CHIRP",
            conv_set_name="CHIRP",
        )
        add_conv_system(prs, config, conv_set=conv_set)
        write_prs(prs, str(prs_file))

        prs2 = parse_prs(prs_file)
        assert prs.to_bytes() == prs2.to_bytes()
