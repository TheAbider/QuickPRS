"""Tests for CLI inject subcommands (p25, conv, talkgroups)."""

import pytest
import shutil
import tempfile
from pathlib import Path

from quickprs.cli import (
    run_cli, cmd_inject_p25, cmd_inject_conv, cmd_inject_talkgroups,
)
from quickprs.prs_parser import parse_prs
from quickprs.validation import validate_prs, ERROR

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
FREQS_CSV = TESTDATA / "test_freqs.csv"
TGS_CSV = TESTDATA / "test_tgs.csv"
CONV_CSV = TESTDATA / "test_conv_channels.csv"


# ─── Helpers ─────────────────────────────────────────────────────────

def _copy_prs(src, tmp_path, name="work.PRS"):
    """Copy a PRS file to tmp_path and return the new path."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


def _create_blank(tmp_path, name="blank.PRS"):
    """Create a blank PRS file and return its path."""
    from quickprs.cli import cmd_create
    out = tmp_path / name
    cmd_create(str(out))
    return str(out)


def _count_group_sets(prs):
    """Count group sets in a parsed PRS."""
    from quickprs.cli import _parse_group_sets
    return _parse_group_sets(prs)


def _count_trunk_sets(prs):
    """Count trunk sets in a parsed PRS."""
    from quickprs.cli import _parse_trunk_sets
    return _parse_trunk_sets(prs)


def _count_conv_sets(prs):
    """Count conv sets in a parsed PRS."""
    from quickprs.cli import _parse_conv_sets
    return _parse_conv_sets(prs)


# ─── inject p25 — blank PRS ─────────────────────────────────────────

class TestInjectP25Blank:
    """Inject a P25 system into a blank PRS file."""

    def test_inject_p25_basic(self, capsys, tmp_path):
        """Inject P25 system with freqs and TGs into blank PRS."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Injected P25 system 'TEST'" in out
        assert "SysID 100" in out

    def test_inject_p25_creates_trunk_set(self, capsys, tmp_path):
        """After injection, trunk set should exist with 5 frequencies."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            freqs_csv=str(FREQS_CSV),
        )
        prs = parse_prs(prs_file)
        sets = _count_trunk_sets(prs)
        assert len(sets) == 1
        assert sets[0].name == "TEST"
        assert len(sets[0].channels) == 5

    def test_inject_p25_creates_group_set(self, capsys, tmp_path):
        """After injection, group set should exist with 10 talkgroups."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            tgs_csv=str(TGS_CSV),
        )
        prs = parse_prs(prs_file)
        sets = _count_group_sets(prs)
        assert len(sets) == 1
        assert sets[0].name == "TEST"
        assert len(sets[0].groups) == 10

    def test_inject_p25_validates_clean(self, capsys, tmp_path):
        """Injected PRS should validate with no errors."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_inject_p25_roundtrip(self, capsys, tmp_path):
        """Injected PRS should roundtrip cleanly."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        raw1 = Path(prs_file).read_bytes()
        prs = parse_prs(prs_file)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    def test_inject_p25_with_wacn(self, capsys, tmp_path):
        """WACN should be accepted and injected."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_p25(
            prs_file, "MYTEST", sysid=892, wacn=781824,
            freqs_csv=str(FREQS_CSV),
        )
        assert result == 0

    def test_inject_p25_long_name(self, capsys, tmp_path):
        """Long name should be set when provided."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            long_name="Test System 1",
            freqs_csv=str(FREQS_CSV),
        )
        assert result == 0

    def test_inject_p25_no_freqs_no_tgs(self, capsys, tmp_path):
        """Inject P25 system without freqs or TGs (system config only)."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_p25(
            prs_file, "EMPTY", sysid=999,
        )
        assert result == 0

    def test_inject_p25_output_flag(self, capsys, tmp_path):
        """Output flag should write to a different file."""
        prs_file = _create_blank(tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        result = cmd_inject_p25(
            prs_file, "TEST", sysid=100,
            freqs_csv=str(FREQS_CSV),
            output=out_file,
        )
        assert result == 0
        assert Path(out_file).exists()
        # Input should be unchanged
        orig_size = Path(prs_file).stat().st_size
        out_size = Path(out_file).stat().st_size
        assert out_size > orig_size


# ─── inject p25 — PAWSOVERMAWS ──────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestInjectP25Paws:
    """Inject P25 system into PAWSOVERMAWS, verify existing data preserved."""

    def test_inject_preserves_existing_systems(self, capsys, tmp_path):
        """Existing P25 systems should remain after injection."""
        prs_file = _copy_prs(PAWS, tmp_path)
        cmd_inject_p25(
            prs_file, "NEW", sysid=500,
            freqs_csv=str(FREQS_CSV),
        )
        prs = parse_prs(prs_file)
        sets = _count_trunk_sets(prs)
        names = {s.name for s in sets}
        # PSERN and other original sets still present
        assert "PSERN" in names
        # New set also present
        assert "NEW" in names

    def test_inject_preserves_existing_groups(self, capsys, tmp_path):
        """Existing group sets should remain after injection."""
        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        groups_before = _count_group_sets(prs_before)

        cmd_inject_p25(
            prs_file, "NEW", sysid=500,
            tgs_csv=str(TGS_CSV),
        )
        prs_after = parse_prs(prs_file)
        groups_after = _count_group_sets(prs_after)
        # One more group set than before
        assert len(groups_after) == len(groups_before) + 1

    def test_inject_preserves_conv_sets(self, capsys, tmp_path):
        """Existing conv sets should be unaffected."""
        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        conv_before = _count_conv_sets(prs_before)

        cmd_inject_p25(
            prs_file, "NEW", sysid=500,
            freqs_csv=str(FREQS_CSV),
        )
        prs_after = parse_prs(prs_file)
        conv_after = _count_conv_sets(prs_after)
        assert len(conv_after) == len(conv_before)

    def test_inject_output_larger(self, capsys, tmp_path):
        """Injected file should be larger than original."""
        prs_file = _copy_prs(PAWS, tmp_path)
        orig_size = Path(prs_file).stat().st_size
        cmd_inject_p25(
            prs_file, "NEW", sysid=500,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        new_size = Path(prs_file).stat().st_size
        assert new_size > orig_size


# ─── inject conv ─────────────────────────────────────────────────────

class TestInjectConv:
    """Tests for the inject conv subcommand."""

    def test_inject_conv_blank(self, capsys, tmp_path):
        """Inject conv channels into a blank PRS."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(
            prs_file, "MURS",
            str(CONV_CSV),
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Injected conv system 'MURS'" in out
        assert "5 channels" in out

    def test_inject_conv_channels_present(self, capsys, tmp_path):
        """After injection, conv set should have 5 channels."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", str(CONV_CSV))
        prs = parse_prs(prs_file)
        sets = _count_conv_sets(prs)
        # Blank PRS already has "Conv 1", plus new "MURS"
        murs = [s for s in sets if s.name == "MURS"]
        assert len(murs) == 1
        assert len(murs[0].channels) == 5

    def test_inject_conv_validates_clean(self, capsys, tmp_path):
        """Injected conv should validate with no errors."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", str(CONV_CSV))
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_inject_conv_roundtrip(self, capsys, tmp_path):
        """Injected conv PRS should roundtrip cleanly."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", str(CONV_CSV))
        raw1 = Path(prs_file).read_bytes()
        prs = parse_prs(prs_file)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_conv_preserves_existing(self, capsys, tmp_path):
        """Inject into PAWS should preserve existing conv sets."""
        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        conv_before = _count_conv_sets(prs_before)

        cmd_inject_conv(prs_file, "MURS", str(CONV_CSV))
        prs_after = parse_prs(prs_file)
        conv_after = _count_conv_sets(prs_after)
        assert len(conv_after) == len(conv_before) + 1

    def test_inject_conv_output_flag(self, capsys, tmp_path):
        """Output flag should write to separate file."""
        prs_file = _create_blank(tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        result = cmd_inject_conv(
            prs_file, "MURS", str(CONV_CSV),
            output=out_file,
        )
        assert result == 0
        assert Path(out_file).exists()

    def test_inject_conv_name_truncation(self, capsys, tmp_path):
        """Name longer than 8 chars should be truncated."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "LONGERNAME", str(CONV_CSV))
        prs = parse_prs(prs_file)
        sets = _count_conv_sets(prs)
        names = {s.name for s in sets}
        assert "LONGERNA" in names  # truncated to 8


# ─── inject talkgroups ───────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestInjectTalkgroups:
    """Tests for the inject talkgroups subcommand."""

    def test_inject_tgs_into_paws(self, capsys, tmp_path):
        """Add talkgroups to existing PSERN PD set."""
        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        sets_before = _count_group_sets(prs_before)
        psern_before = [s for s in sets_before if s.name == "PSERN PD"][0]
        count_before = len(psern_before.groups)

        result = cmd_inject_talkgroups(
            prs_file, "PSERN PD", str(TGS_CSV),
        )
        assert result == 0

        prs_after = parse_prs(prs_file)
        sets_after = _count_group_sets(prs_after)
        psern_after = [s for s in sets_after if s.name == "PSERN PD"][0]
        assert len(psern_after.groups) == count_before + 10

    def test_inject_tgs_summary(self, capsys, tmp_path):
        """Should print summary of what was added."""
        prs_file = _copy_prs(PAWS, tmp_path)
        cmd_inject_talkgroups(prs_file, "PSERN PD", str(TGS_CSV))
        out = capsys.readouterr().out
        assert "Added 10 talkgroups" in out
        assert "PSERN PD" in out

    def test_inject_tgs_preserves_other_sets(self, capsys, tmp_path):
        """Other group sets should be unaffected."""
        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        sets_before = _count_group_sets(prs_before)

        cmd_inject_talkgroups(prs_file, "PSERN PD", str(TGS_CSV))

        prs_after = parse_prs(prs_file)
        sets_after = _count_group_sets(prs_after)
        # Same number of sets (no new sets added)
        assert len(sets_after) == len(sets_before)

    def test_inject_tgs_validates_clean(self, capsys, tmp_path):
        """After adding TGs, file should validate with no errors."""
        prs_file = _copy_prs(PAWS, tmp_path)
        cmd_inject_talkgroups(prs_file, "PSERN PD", str(TGS_CSV))
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_inject_tgs_output_flag(self, capsys, tmp_path):
        """Output flag should write to separate file."""
        prs_file = _copy_prs(PAWS, tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        result = cmd_inject_talkgroups(
            prs_file, "PSERN PD", str(TGS_CSV),
            output=out_file,
        )
        assert result == 0
        assert Path(out_file).exists()
        # Input should be original size
        assert Path(prs_file).stat().st_size == PAWS.stat().st_size


# ─── Error cases ─────────────────────────────────────────────────────

class TestInjectErrors:
    """Tests for error handling in inject commands."""

    def test_inject_p25_missing_file(self, capsys, tmp_path):
        """Inject into nonexistent PRS should return 1."""
        result = run_cli([
            "inject", "nonexistent.PRS", "p25",
            "--name", "TEST", "--sysid", "100",
        ])
        assert result == 1

    def test_inject_p25_missing_freqs_csv(self, capsys, tmp_path):
        """Missing frequencies CSV should return 1."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "p25",
            "--name", "TEST", "--sysid", "100",
            "--freqs-csv", "nonexistent.csv",
        ])
        assert result == 1

    def test_inject_p25_missing_tgs_csv(self, capsys, tmp_path):
        """Missing talkgroups CSV should return 1."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "p25",
            "--name", "TEST", "--sysid", "100",
            "--tgs-csv", "nonexistent.csv",
        ])
        assert result == 1

    def test_inject_conv_missing_csv(self, capsys, tmp_path):
        """Missing channels CSV should return 1."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "MURS",
            "--channels-csv", "nonexistent.csv",
        ])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_tgs_missing_csv(self, capsys, tmp_path):
        """Missing talkgroups CSV should return 1."""
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "inject", prs_file, "talkgroups",
            "--set", "PSERN PD",
            "--tgs-csv", "nonexistent.csv",
        ])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_tgs_bad_set_name(self, capsys, tmp_path):
        """Inject TGs into nonexistent set should return 1."""
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "inject", prs_file, "talkgroups",
            "--set", "NOSUCHSET",
            "--tgs-csv", str(TGS_CSV),
        ])
        assert result == 1

    def test_inject_no_subcommand(self, capsys, tmp_path):
        """inject without p25/conv/talkgroups should return 1."""
        prs_file = _create_blank(tmp_path)
        result = run_cli(["inject", prs_file])
        assert result == 1

    def test_inject_conv_missing_prs(self, capsys, tmp_path):
        """Conv inject with missing PRS should return 1."""
        result = run_cli([
            "inject", "nonexistent.PRS", "conv",
            "--name", "MURS",
            "--channels-csv", str(CONV_CSV),
        ])
        assert result == 1

    def test_inject_p25_bad_freq_csv(self, capsys, tmp_path):
        """CSV with bad frequency data should return 1."""
        bad_csv = tmp_path / "bad_freqs.csv"
        bad_csv.write_text("tx_freq,rx_freq\nnot_a_number,abc\n")
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "p25",
            "--name", "TEST", "--sysid", "100",
            "--freqs-csv", str(bad_csv),
        ])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_tgs_bad_id_csv(self, capsys, tmp_path):
        """CSV with non-integer talkgroup ID should return 1."""
        bad_csv = tmp_path / "bad_tgs.csv"
        bad_csv.write_text("id,short_name,long_name\nabc,TEST,Test\n")
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "inject", prs_file, "talkgroups",
            "--set", "PSERN PD",
            "--tgs-csv", str(bad_csv),
        ])
        assert result == 1


# ─── run_cli dispatch ────────────────────────────────────────────────

class TestInjectRunCli:
    """Test inject commands via run_cli dispatcher."""

    def test_inject_p25_via_cli(self, capsys, tmp_path):
        """inject p25 should work through run_cli."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "p25",
            "--name", "CLI", "--sysid", "42",
            "--freqs-csv", str(FREQS_CSV),
            "--tgs-csv", str(TGS_CSV),
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Injected P25 system 'CLI'" in out

    def test_inject_p25_all_flags(self, capsys, tmp_path):
        """inject p25 with all optional flags."""
        prs_file = _create_blank(tmp_path)
        out_file = str(tmp_path / "out.PRS")
        result = run_cli([
            "inject", prs_file, "p25",
            "--name", "FULL",
            "--long-name", "Full System",
            "--sysid", "892",
            "--wacn", "781824",
            "--freqs-csv", str(FREQS_CSV),
            "--tgs-csv", str(TGS_CSV),
            "--iden-base", "851012500",
            "--iden-spacing", "12500",
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    def test_inject_conv_via_cli(self, capsys, tmp_path):
        """inject conv should work through run_cli."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "MURS",
            "--channels-csv", str(CONV_CSV),
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Injected conv system 'MURS'" in out

    def test_inject_conv_output_via_cli(self, capsys, tmp_path):
        """inject conv with -o flag."""
        prs_file = _create_blank(tmp_path)
        out_file = str(tmp_path / "conv_out.PRS")
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "MURS",
            "--channels-csv", str(CONV_CSV),
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_tgs_via_cli(self, capsys, tmp_path):
        """inject talkgroups should work through run_cli."""
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "inject", prs_file, "talkgroups",
            "--set", "PSERN PD",
            "--tgs-csv", str(TGS_CSV),
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Added 10 talkgroups" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_inject_tgs_output_via_cli(self, capsys, tmp_path):
        """inject talkgroups with -o flag."""
        prs_file = _copy_prs(PAWS, tmp_path, "input.PRS")
        out_file = str(tmp_path / "tgs_out.PRS")
        result = run_cli([
            "inject", prs_file, "talkgroups",
            "--set", "PSERN PD",
            "--tgs-csv", str(TGS_CSV),
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()


# ─── CSV parser unit tests ──────────────────────────────────────────

class TestCSVParsers:
    """Test the internal CSV parsing helpers."""

    def test_parse_freq_csv(self):
        """Should parse 5 frequency pairs."""
        from quickprs.cli import _parse_freq_csv
        freqs = _parse_freq_csv(str(FREQS_CSV))
        assert len(freqs) == 5
        assert freqs[0] == (851.0125, 851.0125)
        assert freqs[4] == (852.2625, 852.2625)

    def test_parse_freq_csv_missing_file(self):
        """Should raise FileNotFoundError."""
        from quickprs.cli import _parse_freq_csv
        with pytest.raises(FileNotFoundError):
            _parse_freq_csv("nonexistent.csv")

    def test_parse_tgs_csv(self):
        """Should parse 10 talkgroups."""
        from quickprs.cli import _parse_tgs_csv
        tgs = _parse_tgs_csv(str(TGS_CSV))
        assert len(tgs) == 10
        # (id, short_name, long_name, tx, scan)
        assert tgs[0] == (100, "DISP", "Dispatch", False, True)
        assert tgs[1] == (200, "TAC1", "Tactical 1", True, True)
        assert tgs[6] == (700, "ADMIN", "Administration", False, False)

    def test_parse_tgs_csv_missing_file(self):
        """Should raise FileNotFoundError."""
        from quickprs.cli import _parse_tgs_csv
        with pytest.raises(FileNotFoundError):
            _parse_tgs_csv("nonexistent.csv")

    def test_parse_conv_csv(self):
        """Should parse 5 conventional channels."""
        from quickprs.cli import _parse_conv_csv
        channels = _parse_conv_csv(str(CONV_CSV))
        assert len(channels) == 5
        assert channels[0]['short_name'] == "MURS1"
        assert channels[0]['tx_freq'] == 151.820
        assert channels[0]['rx_freq'] == 151.820
        assert channels[0]['long_name'] == "MURS Channel 1"

    def test_parse_conv_csv_missing_file(self):
        """Should raise FileNotFoundError."""
        from quickprs.cli import _parse_conv_csv
        with pytest.raises(FileNotFoundError):
            _parse_conv_csv("nonexistent.csv")

    def test_parse_freq_csv_bad_data(self, tmp_path):
        """Bad frequency data should raise ValueError."""
        from quickprs.cli import _parse_freq_csv
        bad = tmp_path / "bad.csv"
        bad.write_text("tx_freq,rx_freq\nnot_a_number,123\n")
        with pytest.raises(ValueError):
            _parse_freq_csv(str(bad))

    def test_parse_tgs_csv_bad_id(self, tmp_path):
        """Non-integer TG ID should raise ValueError."""
        from quickprs.cli import _parse_tgs_csv
        bad = tmp_path / "bad.csv"
        bad.write_text("id,short_name,long_name\nabc,TEST,Test\n")
        with pytest.raises(ValueError):
            _parse_tgs_csv(str(bad))

    def test_parse_conv_csv_missing_name(self, tmp_path):
        """Row without short_name should raise ValueError."""
        from quickprs.cli import _parse_conv_csv
        bad = tmp_path / "bad.csv"
        bad.write_text("short_name,tx_freq\n,151.820\n")
        with pytest.raises(ValueError):
            _parse_conv_csv(str(bad))

    def test_parse_freq_csv_rx_defaults_to_tx(self, tmp_path):
        """When rx_freq column missing, rx should default to tx."""
        from quickprs.cli import _parse_freq_csv
        csv_file = tmp_path / "tx_only.csv"
        csv_file.write_text("tx_freq\n851.0125\n852.0125\n")
        freqs = _parse_freq_csv(str(csv_file))
        assert len(freqs) == 2
        assert freqs[0] == (851.0125, 851.0125)

    def test_parse_conv_csv_rx_defaults_to_tx(self, tmp_path):
        """When rx_freq is empty, rx should default to tx (simplex)."""
        from quickprs.cli import _parse_conv_csv
        csv_file = tmp_path / "simplex.csv"
        csv_file.write_text("short_name,tx_freq,rx_freq\nCH1,146.520,\n")
        channels = _parse_conv_csv(str(csv_file))
        assert len(channels) == 1
        assert channels[0]['rx_freq'] == 146.520


# ─── End-to-end pipeline tests ──────────────────────────────────────

class TestInjectPipeline:
    """Full pipeline: create blank -> inject -> verify -> validate."""

    def test_full_p25_pipeline(self, capsys, tmp_path):
        """Create blank, inject P25, verify everything round-trips."""
        prs_file = _create_blank(tmp_path)

        # Inject P25 system
        result = cmd_inject_p25(
            prs_file, "PSERN", sysid=892, wacn=781824,
            long_name="PSERN SEATTLE",
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        assert result == 0

        # Verify data
        prs = parse_prs(prs_file)
        trunk_sets = _count_trunk_sets(prs)
        group_sets = _count_group_sets(prs)
        assert any(s.name == "PSERN" for s in trunk_sets)
        assert any(s.name == "PSERN" for s in group_sets)

        # Roundtrip
        raw1 = Path(prs_file).read_bytes()
        raw2 = prs.to_bytes()
        assert raw1 == raw2

        # Validate
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == []

    def test_full_conv_pipeline(self, capsys, tmp_path):
        """Create blank, inject conv, verify round-trips."""
        prs_file = _create_blank(tmp_path)

        result = cmd_inject_conv(
            prs_file, "MURS", str(CONV_CSV),
        )
        assert result == 0

        prs = parse_prs(prs_file)
        conv_sets = _count_conv_sets(prs)
        murs = [s for s in conv_sets if s.name == "MURS"]
        assert len(murs) == 1
        assert len(murs[0].channels) == 5

        raw1 = Path(prs_file).read_bytes()
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    def test_multi_inject_pipeline(self, capsys, tmp_path):
        """Create blank, inject P25 + conv, verify both present."""
        prs_file = _create_blank(tmp_path)

        # Inject P25
        cmd_inject_p25(
            prs_file, "P25SYS", sysid=100,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )

        # Inject conv
        cmd_inject_conv(prs_file, "MURS", str(CONV_CSV))

        # Verify both
        prs = parse_prs(prs_file)
        trunk_sets = _count_trunk_sets(prs)
        conv_sets = _count_conv_sets(prs)
        assert any(s.name == "P25SYS" for s in trunk_sets)
        assert any(s.name == "MURS" for s in conv_sets)

        # Validate
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"
