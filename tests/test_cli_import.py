"""Tests for CLI import-rr and import-paste subcommands.

Tests use mocked API responses — no network calls are made.
"""

import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from quickprs.cli import (
    run_cli, cmd_import_rr, cmd_import_paste,
)
from quickprs.prs_parser import parse_prs
from quickprs.validation import validate_prs, ERROR
from quickprs.radioreference import (
    RRSystem, RRTalkgroup, RRSite, RRSiteFreq,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Helpers ─────────────────────────────────────────────────────────

def _create_blank(tmp_path, name="blank.PRS"):
    """Create a blank PRS file and return its path."""
    from quickprs.cli import cmd_create
    out = tmp_path / name
    cmd_create(str(out))
    return str(out)


def _copy_prs(src, tmp_path, name="work.PRS"):
    """Copy a PRS file to tmp_path and return the new path."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


def _count_group_sets(prs):
    from quickprs.cli import _parse_group_sets
    return _parse_group_sets(prs)


def _count_trunk_sets(prs):
    from quickprs.cli import _parse_trunk_sets
    return _parse_trunk_sets(prs)


def _make_mock_rr_system(sid=8155):
    """Build a realistic mock RRSystem for testing."""
    return RRSystem(
        sid=sid,
        name="Test County Public Safety (TCPS)",
        system_type="Project 25 Phase II",
        sysid="37C",
        wacn="BEE00",
        voice="APCO-25 Common Air Interface Exclusive",
        city="Testville",
        state="Washington",
        county="Test",
        categories={1: "Law Enforcement", 2: "Fire/EMS"},
        talkgroups=[
            RRTalkgroup(dec_id=100, alpha_tag="TC PD D",
                        description="Police Dispatch", mode="T",
                        tag="Law Dispatch", category="Law Enforcement",
                        category_id=1),
            RRTalkgroup(dec_id=200, alpha_tag="TC PD T1",
                        description="Police Tac 1", mode="T",
                        tag="Law Tac", category="Law Enforcement",
                        category_id=1),
            RRTalkgroup(dec_id=300, alpha_tag="TC FD D",
                        description="Fire Dispatch", mode="T",
                        tag="Fire Dispatch", category="Fire/EMS",
                        category_id=2),
            RRTalkgroup(dec_id=400, alpha_tag="TC EMS D",
                        description="EMS Dispatch", mode="T",
                        tag="EMS Dispatch", category="Fire/EMS",
                        category_id=2),
            RRTalkgroup(dec_id=500, alpha_tag="TC ADMIN",
                        description="Administration", mode="D",
                        tag="Other", category="Law Enforcement",
                        category_id=1),
        ],
        sites=[
            RRSite(site_id=1, site_number="001", name="Hilltop",
                   rfss=1, nac="3AB",
                   freqs=[
                       RRSiteFreq(freq=851.0125, use="c"),
                       RRSiteFreq(freq=851.2625, use="a"),
                       RRSiteFreq(freq=851.5125, use="a"),
                   ]),
            RRSite(site_id=2, site_number="002", name="Valley",
                   rfss=1, nac="3AB",
                   freqs=[
                       RRSiteFreq(freq=852.0125, use="c"),
                       RRSiteFreq(freq=852.2625, use="a"),
                   ]),
        ],
    )


def _write_tgs_paste(path):
    """Write a sample talkgroup paste file."""
    path.write_text(
        "DEC\tHEX\tMode\tAlpha Tag\tDescription\tTag\n"
        "100\t64\tT\tTC PD D\tPolice Dispatch\tLaw Dispatch\n"
        "200\tc8\tT\tTC PD T1\tPolice Tac 1\tLaw Tac\n"
        "300\t12c\tT\tTC FD D\tFire Dispatch\tFire Dispatch\n"
        "400\t190\tT\tTC EMS D\tEMS Dispatch\tEMS Dispatch\n",
        encoding='utf-8',
    )


def _write_freqs_paste(path):
    """Write a sample frequency paste file."""
    path.write_text(
        "851.0125c\n"
        "851.2625\n"
        "851.5125\n"
        "852.0125c\n"
        "852.2625\n",
        encoding='utf-8',
    )


# ─── import-rr — mock API ───────────────────────────────────────────

class TestImportRR:
    """Test import-rr command with mocked RadioReference API."""

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_basic(self, mock_api_cls, capsys, tmp_path):
        """Basic import from mocked API should succeed."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Test County Public Safety" in out
        assert "SID 8155" in out
        assert "Talkgroups: 5" in out
        assert "Frequencies: 5" in out

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_creates_sets(self, mock_api_cls, capsys, tmp_path):
        """After import, trunk and group sets should exist."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        prs = parse_prs(prs_file)
        trunk_sets = _count_trunk_sets(prs)
        group_sets = _count_group_sets(prs)
        assert len(trunk_sets) >= 1
        assert len(group_sets) >= 1

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_validates_clean(self, mock_api_cls, capsys, tmp_path):
        """Imported PRS should validate with no errors."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_roundtrip(self, mock_api_cls, capsys, tmp_path):
        """Imported PRS should roundtrip cleanly."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        raw1 = Path(prs_file).read_bytes()
        prs = parse_prs(prs_file)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_url_flag(self, mock_api_cls, capsys, tmp_path):
        """--url flag should parse SID from URL."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file,
            url="https://www.radioreference.com/db/sid/8155",
            username="testuser", apikey="testkey",
        )
        assert result == 0
        mock_api.get_system.assert_called_once_with(8155)

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_output_flag(self, mock_api_cls, capsys, tmp_path):
        """Output flag should write to a different file."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
            output=out_file,
        )
        assert result == 0
        assert Path(out_file).exists()

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_category_filter(self, mock_api_cls, capsys, tmp_path):
        """Category filter should limit talkgroups."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
            categories="1",  # Law Enforcement only
        )
        assert result == 0
        out = capsys.readouterr().out
        # Category 1 has 3 TGs (100, 200, 500)
        assert "Talkgroups: 3" in out

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_tag_filter(self, mock_api_cls, capsys, tmp_path):
        """Tag filter should limit talkgroups."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
            tags="Law Dispatch,Law Tac",
        )
        assert result == 0
        out = capsys.readouterr().out
        # Only Law Dispatch (100) and Law Tac (200)
        assert "Talkgroups: 2" in out

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_into_paws(self, mock_api_cls, capsys, tmp_path):
        """Import into PAWS should preserve existing systems."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _copy_prs(PAWS, tmp_path)
        prs_before = parse_prs(str(PAWS))
        trunk_before = _count_trunk_sets(prs_before)

        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        assert result == 0

        prs_after = parse_prs(prs_file)
        trunk_after = _count_trunk_sets(prs_after)
        # Should have one more trunk set
        assert len(trunk_after) == len(trunk_before) + 1
        # PSERN should still exist
        names = {s.name for s in trunk_after}
        assert "PSERN" in names


# ─── import-rr — error cases ────────────────────────────────────────

class TestImportRRErrors:
    """Test error handling for import-rr command."""

    def test_import_rr_no_sid_no_url(self, capsys, tmp_path):
        """Missing both --sid and --url should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, username="testuser", apikey="testkey",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "--sid or --url is required" in err

    def test_import_rr_bad_url(self, capsys, tmp_path):
        """Invalid URL should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, url="https://google.com",
            username="testuser", apikey="testkey",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "cannot parse system ID" in err

    @patch('quickprs.radioreference.HAS_ZEEP', False)
    def test_import_rr_no_zeep(self, capsys, tmp_path):
        """Missing zeep library should return 1 with install hint."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "zeep" in err
        assert "pip install" in err

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_api_connection_error(self, mock_api_cls, capsys,
                                             tmp_path):
        """API connection failure should return 1."""
        mock_api_cls.side_effect = ConnectionError(
            "Cannot connect to RadioReference API")

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=8155,
            username="testuser", apikey="testkey",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "Cannot connect" in err

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_empty_system(self, mock_api_cls, capsys, tmp_path):
        """System with no name should return 1."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = RRSystem(sid=9999, name="")
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = cmd_import_rr(
            prs_file, sid=9999,
            username="testuser", apikey="testkey",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "no system found" in err

    def test_import_rr_missing_prs(self, capsys, tmp_path):
        """Nonexistent PRS file should return 1."""
        result = run_cli([
            "import-rr", "nonexistent.PRS",
            "--sid", "8155",
            "--username", "testuser",
            "--apikey", "testkey",
        ])
        assert result == 1


# ─── import-paste ────────────────────────────────────────────────────

class TestImportPaste:
    """Test import-paste command with pasted text files."""

    def test_import_paste_tgs_only(self, capsys, tmp_path):
        """Import with talkgroups file only should succeed."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Talkgroups: 4" in out
        assert "Frequencies: 0" in out

    def test_import_paste_freqs_only(self, capsys, tmp_path):
        """Import with frequencies file only should succeed."""
        prs_file = _create_blank(tmp_path)
        freqs_file = tmp_path / "freqs.txt"
        _write_freqs_paste(freqs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            freqs_file=str(freqs_file),
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Frequencies: 5" in out
        assert "Talkgroups: 0" in out

    def test_import_paste_both(self, capsys, tmp_path):
        """Import with both talkgroups and frequencies files."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892, wacn=781824,
            tgs_file=str(tgs_file),
            freqs_file=str(freqs_file),
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Talkgroups: 4" in out
        assert "Frequencies: 5" in out

    def test_import_paste_creates_sets(self, capsys, tmp_path):
        """After import, trunk and group sets should exist."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)

        cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
            freqs_file=str(freqs_file),
        )
        prs = parse_prs(prs_file)
        trunk_sets = _count_trunk_sets(prs)
        group_sets = _count_group_sets(prs)
        assert any(s.name == "TCPS" for s in trunk_sets)
        assert any(s.name == "TCPS" for s in group_sets)

    def test_import_paste_validates_clean(self, capsys, tmp_path):
        """Imported PRS should validate with no errors."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)

        cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
            freqs_file=str(freqs_file),
        )
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_import_paste_roundtrip(self, capsys, tmp_path):
        """Imported PRS should roundtrip cleanly."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)

        cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
            freqs_file=str(freqs_file),
        )
        raw1 = Path(prs_file).read_bytes()
        prs = parse_prs(prs_file)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    def test_import_paste_with_wacn(self, capsys, tmp_path):
        """WACN should be accepted."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892, wacn=781824,
            tgs_file=str(tgs_file),
        )
        assert result == 0

    def test_import_paste_output_flag(self, capsys, tmp_path):
        """Output flag should write to a different file."""
        prs_file = _create_blank(tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
            output=out_file,
        )
        assert result == 0
        assert Path(out_file).exists()

    def test_import_paste_long_name(self, capsys, tmp_path):
        """Long name should be set when provided."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            long_name="Test County PS",
            tgs_file=str(tgs_file),
        )
        assert result == 0

    def test_import_paste_name_truncation(self, capsys, tmp_path):
        """Long system name should be truncated to 8 chars."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = cmd_import_paste(
            prs_file, "TOOLONGNAME", sysid=892,
            tgs_file=str(tgs_file),
        )
        assert result == 0
        prs = parse_prs(prs_file)
        group_sets = _count_group_sets(prs)
        names = {s.name for s in group_sets}
        assert "TOOLONGN" in names  # truncated to 8

    def test_import_paste_into_paws(self, capsys, tmp_path):
        """Import into PAWS should preserve existing systems."""
        prs_file = _copy_prs(PAWS, tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)

        prs_before = parse_prs(str(PAWS))
        trunk_before = _count_trunk_sets(prs_before)

        result = cmd_import_paste(
            prs_file, "NEWTST", sysid=500,
            tgs_file=str(tgs_file),
            freqs_file=str(freqs_file),
        )
        assert result == 0

        prs_after = parse_prs(prs_file)
        trunk_after = _count_trunk_sets(prs_after)
        assert len(trunk_after) == len(trunk_before) + 1
        names = {s.name for s in trunk_after}
        assert "PSERN" in names
        assert "NEWTST" in names


# ─── import-paste — error cases ──────────────────────────────────────

class TestImportPasteErrors:
    """Test error handling for import-paste command."""

    def test_import_paste_no_files(self, capsys, tmp_path):
        """Missing both --tgs-file and --freqs-file should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "at least one" in err

    def test_import_paste_missing_tgs_file(self, capsys, tmp_path):
        """Nonexistent talkgroups file should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file="nonexistent.txt",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_import_paste_missing_freqs_file(self, capsys, tmp_path):
        """Nonexistent frequencies file should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            freqs_file="nonexistent.txt",
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_import_paste_empty_tgs_file(self, capsys, tmp_path):
        """Empty talkgroups file should return 1."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "empty_tgs.txt"
        tgs_file.write_text("", encoding='utf-8')

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            tgs_file=str(tgs_file),
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "no talkgroups found" in err

    def test_import_paste_empty_freqs_file(self, capsys, tmp_path):
        """Empty frequencies file should return 1."""
        prs_file = _create_blank(tmp_path)
        freqs_file = tmp_path / "empty_freqs.txt"
        freqs_file.write_text("just some text with no numbers\n",
                              encoding='utf-8')

        result = cmd_import_paste(
            prs_file, "TCPS", sysid=892,
            freqs_file=str(freqs_file),
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "no frequencies found" in err

    def test_import_paste_missing_prs(self, capsys, tmp_path):
        """Nonexistent PRS file should return 1."""
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = run_cli([
            "import-paste", "nonexistent.PRS",
            "--name", "TCPS", "--sysid", "892",
            "--tgs-file", str(tgs_file),
        ])
        assert result == 1


# ─── run_cli dispatch ────────────────────────────────────────────────

class TestImportRunCli:
    """Test import commands via run_cli dispatcher."""

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_via_cli_sid(self, mock_api_cls, capsys, tmp_path):
        """import-rr with --sid should work through run_cli."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "import-rr", prs_file,
            "--sid", "8155",
            "--username", "testuser",
            "--apikey", "testkey",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Test County Public Safety" in out

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_via_cli_url(self, mock_api_cls, capsys, tmp_path):
        """import-rr with --url should work through run_cli."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "import-rr", prs_file,
            "--url", "https://www.radioreference.com/db/sid/8155",
            "--username", "testuser",
            "--apikey", "testkey",
        ])
        assert result == 0

    @patch('quickprs.radioreference.RadioReferenceAPI')
    def test_import_rr_via_cli_all_flags(self, mock_api_cls, capsys,
                                          tmp_path):
        """import-rr with all optional flags."""
        mock_api = MagicMock()
        mock_api.get_system.return_value = _make_mock_rr_system()
        mock_api_cls.return_value = mock_api

        prs_file = _create_blank(tmp_path)
        out_file = str(tmp_path / "out.PRS")
        result = run_cli([
            "import-rr", prs_file,
            "--sid", "8155",
            "--username", "testuser",
            "--apikey", "testkey",
            "--categories", "1,2",
            "--tags", "Law Dispatch",
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    def test_import_paste_via_cli(self, capsys, tmp_path):
        """import-paste should work through run_cli."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        _write_tgs_paste(tgs_file)

        result = run_cli([
            "import-paste", prs_file,
            "--name", "TCPS",
            "--sysid", "892",
            "--tgs-file", str(tgs_file),
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Talkgroups: 4" in out

    def test_import_paste_via_cli_all_flags(self, capsys, tmp_path):
        """import-paste with all optional flags."""
        prs_file = _create_blank(tmp_path)
        tgs_file = tmp_path / "tgs.txt"
        freqs_file = tmp_path / "freqs.txt"
        _write_tgs_paste(tgs_file)
        _write_freqs_paste(freqs_file)
        out_file = str(tmp_path / "out.PRS")

        result = run_cli([
            "import-paste", prs_file,
            "--name", "TCPS",
            "--sysid", "892",
            "--wacn", "781824",
            "--long-name", "Test County PS",
            "--tgs-file", str(tgs_file),
            "--freqs-file", str(freqs_file),
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()
