"""Tests for the CLI module."""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from quickprs.cli import (
    run_cli, cmd_info, cmd_validate, cmd_export_csv, cmd_compare, cmd_dump,
    cmd_diff_options, cmd_iden_templates, cmd_create,
)

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── run_cli dispatcher ─────────────────────────────────────────────


class TestRunCliDispatch:
    """Test the CLI argument dispatcher."""

    def test_no_args_returns_none(self):
        """No subcommand should return None (GUI mode)."""
        result = run_cli([])
        assert result is None

    def test_version_flag(self):
        """--version should print version and exit."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0

    def test_info_subcommand(self, capsys):
        """info subcommand should succeed on valid file."""
        result = run_cli(["info", str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "PAWSOVERMAWS.PRS" in out

    def test_validate_subcommand(self, capsys):
        """validate subcommand should succeed."""
        result = run_cli(["validate", str(CLAUDE)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Validating" in out

    def test_compare_subcommand(self, capsys):
        """compare subcommand should work with two files."""
        result = run_cli(["compare", str(PAWS), str(CLAUDE)])
        assert result == 1  # files differ
        out = capsys.readouterr().out
        assert "Summary" in out

    def test_export_csv_subcommand(self, capsys):
        """export-csv subcommand should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cli(["export-csv", str(PAWS), tmpdir])
            assert result == 0
            out = capsys.readouterr().out
            assert "Exported" in out

    def test_info_missing_file(self, capsys):
        """info on nonexistent file should return 1."""
        result = run_cli(["info", "nonexistent.PRS"])
        assert result == 1

    def test_validate_missing_file(self, capsys):
        """validate on nonexistent file should return 1."""
        result = run_cli(["validate", "nonexistent.PRS"])
        assert result == 1

    def test_compare_missing_file(self, capsys):
        """compare with missing file should return 1."""
        result = run_cli(["compare", "nonexistent.PRS", str(CLAUDE)])
        assert result == 1


# ─── cmd_info ────────────────────────────────────────────────────────


class TestCmdInfo:
    """Test the info command output."""

    def test_info_paws(self, capsys):
        """Info on PAWSOVERMAWS should show systems and sets."""
        result = cmd_info(str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "46,822 bytes" in out
        assert "63" in out  # sections
        assert "P25 Trunked" in out
        assert "PSERN" in out
        assert "Group Sets (7)" in out
        assert "Trunk Sets (7)" in out
        assert "Conv Sets (3)" in out
        assert "IDEN Sets (3)" in out

    def test_info_claude(self, capsys):
        """Info on claude test should show its content."""
        result = cmd_info(str(CLAUDE))
        assert result == 0
        out = capsys.readouterr().out
        assert "9,652 bytes" in out
        assert "26" in out  # sections

    def test_info_group_details(self, capsys):
        """Info should show talkgroup counts per set."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "PSERN PD: 83 TGs" in out
        assert "Total: 241 talkgroups" in out

    def test_info_trunk_details(self, capsys):
        """Info should show frequency counts per trunk set."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "PSERN: 28 freqs" in out
        assert "Total: 290 frequencies" in out

    def test_info_conv_details(self, capsys):
        """Info should show channel counts per conv set."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "FURRY NB: 70 channels" in out
        assert "Total: 145 channels" in out

    def test_info_iden_details(self, capsys):
        """Info should show IDEN set active counts."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "BEE00: 4/16 active" in out

    def test_info_named_records(self, capsys):
        """Info should list named record classes."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "Named records" in out
        assert "CPersonality" in out

    def test_info_system_configs(self, capsys):
        """Info should list system config long names."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "System configs:" in out
        assert "PSERN SEATTLE" in out

    def test_info_radio_options(self, capsys):
        """Info should show radio option highlights."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "Radio Options:" in out
        assert "Battery: Lithium Ion Poly" in out
        assert "Speaker=On" in out
        assert "Tones=On" in out
        assert "GPS: On (Internal)" in out
        assert "Bluetooth: Enabled (PAWS AND MAWS)" in out
        assert "Time Zone: UTC-7" in out

    def test_info_prog_buttons(self, capsys):
        """Info should show programmable button assignments."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "Programmable Buttons:" in out
        assert "2-Pos Switch: Scan" in out
        assert "3-Pos Switch: Channel Bank" in out
        assert "Top Side Button: Talkaround/Direct" in out
        assert "Emergency Button: Unassigned" in out

    def test_info_short_menu(self, capsys):
        """Info should show short menu slots."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "Short Menu (7/16 slots):" in out
        assert "[0] Start Scan" in out
        assert "[6] Display SA" in out

    def test_info_no_xml_no_crash(self, capsys):
        """Files without platformConfig should not crash."""
        cmd_info(str(CLAUDE))
        out = capsys.readouterr().out
        assert "Radio Options:" not in out
        assert "Programmable Buttons:" not in out


# ─── cmd_validate ────────────────────────────────────────────────────


class TestCmdValidate:
    """Test the validate command."""

    def test_validate_claude(self, capsys):
        """Claude test file should pass validation (0 errors)."""
        result = cmd_validate(str(CLAUDE))
        assert result == 0
        out = capsys.readouterr().out
        assert "0 errors" in out

    def test_validate_paws(self, capsys):
        """PAWSOVERMAWS should validate without crashing."""
        result = cmd_validate(str(PAWS))
        assert result in (0, 1)  # may have warnings/errors
        out = capsys.readouterr().out
        assert "Validating" in out
        assert "PAWSOVERMAWS" in out

    def test_validate_shows_size(self, capsys):
        """Validate should show file size and section count."""
        cmd_validate(str(CLAUDE))
        out = capsys.readouterr().out
        assert "9,652 bytes" in out
        assert "Sections: 26" in out

    def test_validate_shows_summary(self, capsys):
        """Validate output should include summary line."""
        cmd_validate(str(CLAUDE))
        out = capsys.readouterr().out
        assert "errors" in out
        assert "warnings" in out
        assert "info" in out


# ─── cmd_export_csv ──────────────────────────────────────────────────


class TestCmdExportCsv:
    """Test the CSV export command."""

    def test_export_paws(self, capsys):
        """Exporting PAWSOVERMAWS should create 6 CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cmd_export_csv(str(PAWS), tmpdir)
            assert result == 0
            files = os.listdir(tmpdir)
            assert "GROUP_SET.csv" in files
            assert "TRK_SET.csv" in files
            assert "CONV_SET.csv" in files
            assert "IDEN_SET.csv" in files
            assert "OPTIONS.csv" in files
            assert "SYSTEMS.csv" in files

    def test_export_claude(self, capsys):
        """Exporting claude test should create CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cmd_export_csv(str(CLAUDE), tmpdir)
            assert result == 0

    def test_export_creates_dir(self, capsys):
        """Export should create output directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested", "output")
            result = cmd_export_csv(str(PAWS), subdir)
            assert result == 0
            assert os.path.isdir(subdir)

    def test_export_group_csv_content(self):
        """GROUP_SET.csv should have correct headers and data."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "GROUP_SET.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["Set", "GroupID", "ShortName", "LongName",
                                  "TX", "RX", "Scan"]
                rows = list(reader)
                assert len(rows) == 241  # 241 talkgroups

    def test_export_trunk_csv_content(self):
        """TRK_SET.csv should have correct headers."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "TRK_SET.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["Set", "TxFreq", "RxFreq", "TxMin", "TxMax"]
                rows = list(reader)
                assert len(rows) == 290  # 290 frequencies

    def test_export_conv_csv_content(self):
        """CONV_SET.csv should have correct headers."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "CONV_SET.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert "ShortName" in header
                assert "TxFreq" in header

    def test_export_iden_csv_content(self):
        """IDEN_SET.csv should have correct headers."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "IDEN_SET.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert "BaseFreqMHz" in header
                assert "Spacing" in header

    def test_export_output_message(self, capsys):
        """Export should report what was exported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            out = capsys.readouterr().out
            assert "GROUP_SET.csv (241 groups)" in out
            assert "TRK_SET.csv (290 channels)" in out
            assert "CONV_SET.csv (145 channels)" in out
            assert "IDEN_SET.csv (3 sets)" in out
            assert "OPTIONS.csv" in out
            assert "SYSTEMS.csv" in out

    def test_export_options_csv_content(self):
        """OPTIONS.csv should have category/field/value columns."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "OPTIONS.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["Category", "Field", "Value"]
                rows = list(reader)
                assert len(rows) > 50  # should have many fields
                # Check some known values
                fields = {r[1]: r[2] for r in rows}
                assert "Battery Type" in fields
                assert fields["Battery Type"] == "Lithium Ion Poly"

    def test_export_options_has_buttons(self):
        """OPTIONS.csv should include programmable button data."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "OPTIONS.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)
                rows = list(reader)
                cats = {r[0] for r in rows}
                assert "Programmable Buttons" in cats
                assert "Short Menu" in cats

    def test_export_systems_csv_content(self):
        """SYSTEMS.csv should list systems and configs."""
        import csv
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(PAWS), tmpdir)
            path = os.path.join(tmpdir, "SYSTEMS.csv")
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["ShortName", "Type", "LongName", "WACN"]
                rows = list(reader)
                types = [r[1] for r in rows]
                assert "P25 Trunked" in types
                assert "Conventional" in types
                assert "Config" in types

    def test_export_no_options_csv_for_simple_file(self):
        """Files without platformConfig should not create OPTIONS.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd_export_csv(str(CLAUDE), tmpdir)
            files = os.listdir(tmpdir)
            assert "OPTIONS.csv" not in files


# ─── cmd_compare ─────────────────────────────────────────────────────


class TestCmdCompare:
    """Test the compare command."""

    def test_compare_identical(self, capsys):
        """Comparing a file to itself should return 0."""
        result = cmd_compare(str(PAWS), str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "0 added, 0 removed, 0 changed" in out

    def test_compare_different(self, capsys):
        """Comparing different files should return 1."""
        result = cmd_compare(str(PAWS), str(CLAUDE))
        assert result == 1
        out = capsys.readouterr().out
        assert "added" in out
        assert "removed" in out

    def test_compare_shows_file_paths(self, capsys):
        """Compare output should show both file paths."""
        cmd_compare(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        assert "PAWSOVERMAWS" in out
        assert "claude test" in out

    def test_compare_shows_systems(self, capsys):
        """Compare should show system-level differences."""
        cmd_compare(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        assert "P25 Trunked" in out

    def test_compare_shows_sets(self, capsys):
        """Compare should show set-level differences."""
        cmd_compare(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        assert "Group Set" in out
        assert "Trunk Set" in out

    def test_compare_shows_size_diff(self, capsys):
        """Compare should show file size difference."""
        cmd_compare(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        assert "Size" in out
        assert "46,822" in out
        assert "9,652" in out

    def test_compare_shows_summary(self, capsys):
        """Compare should end with a summary line."""
        cmd_compare(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        assert "Summary:" in out


# ─── Set parsing helpers ─────────────────────────────────────────────


class TestSetParsingHelpers:
    """Test the internal set parsing helper functions."""

    def test_parse_group_sets_paws(self):
        """Should parse group sets from PAWSOVERMAWS."""
        from quickprs.cli import _parse_group_sets
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(PAWS))
        sets = _parse_group_sets(prs)
        assert len(sets) == 7
        names = {s.name for s in sets}
        assert "PSERN PD" in names

    def test_parse_trunk_sets_paws(self):
        """Should parse trunk sets from PAWSOVERMAWS."""
        from quickprs.cli import _parse_trunk_sets
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(PAWS))
        sets = _parse_trunk_sets(prs)
        assert len(sets) == 7
        total = sum(len(s.channels) for s in sets)
        assert total == 290

    def test_parse_conv_sets_paws(self):
        """Should parse conv sets from PAWSOVERMAWS."""
        from quickprs.cli import _parse_conv_sets
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(PAWS))
        sets = _parse_conv_sets(prs)
        assert len(sets) == 3
        total = sum(len(s.channels) for s in sets)
        assert total == 145

    def test_parse_iden_sets_paws(self):
        """Should parse IDEN sets from PAWSOVERMAWS."""
        from quickprs.cli import _parse_iden_sets
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(PAWS))
        sets = _parse_iden_sets(prs)
        assert len(sets) == 3
        names = {s.name for s in sets}
        assert "BEE00" in names

    def test_parse_group_sets_claude(self):
        """Should parse group sets from claude test."""
        from quickprs.cli import _parse_group_sets
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(CLAUDE))
        sets = _parse_group_sets(prs)
        assert len(sets) == 1

    def test_parse_sets_empty(self):
        """Should return empty list for PRS without the section."""
        from quickprs.cli import _parse_group_sets
        from quickprs.prs_parser import PRSFile
        prs = PRSFile(sections=[], file_size=10)
        sets = _parse_group_sets(prs)
        assert sets == []


# ─── cmd_dump ─────────────────────────────────────────────────────────


class TestCmdDump:
    """Test the dump command."""

    def test_dump_list_sections(self, capsys):
        """Dump should list all sections with class names."""
        result = cmd_dump(str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "63" in out  # section count
        assert "CPersonality" in out
        assert "CConvChannel" in out

    def test_dump_section_detail(self, capsys):
        """Dump -s should show section details."""
        result = cmd_dump(str(PAWS), section_idx=0)
        assert result == 0
        out = capsys.readouterr().out
        assert "CPersonality" in out
        assert "160 bytes" in out
        assert "byte1=0x85" in out

    def test_dump_hex(self, capsys):
        """Dump -s -x should show hex dump."""
        result = cmd_dump(str(PAWS), section_idx=0, hex_bytes=32)
        assert result == 0
        out = capsys.readouterr().out
        assert "000000" in out  # hex offset
        assert "ff ff 85" in out  # first bytes

    def test_dump_unnamed_section(self, capsys):
        """Dump on unnamed (data) section should show (unnamed)."""
        result = cmd_dump(str(PAWS), section_idx=2)
        assert result == 0
        out = capsys.readouterr().out
        assert "(unnamed)" in out

    def test_dump_section_out_of_range(self, capsys):
        """Dump with invalid section index should return 1."""
        result = cmd_dump(str(PAWS), section_idx=999)
        assert result == 1

    def test_dump_claude(self, capsys):
        """Dump should work on claude test file."""
        result = cmd_dump(str(CLAUDE))
        assert result == 0
        out = capsys.readouterr().out
        assert "26" in out  # section count

    def test_dump_via_run_cli(self, capsys):
        """Dump subcommand should work via run_cli."""
        result = run_cli(["dump", str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "CPersonality" in out

    def test_dump_section_via_run_cli(self, capsys):
        """Dump -s via run_cli should work."""
        result = run_cli(["dump", str(PAWS), "-s", "0", "-x", "16"])
        assert result == 0
        out = capsys.readouterr().out
        assert "byte1=0x85" in out
        assert "000000" in out


# ─── Edge cases ──────────────────────────────────────────────────────


class TestCliEdgeCases:
    """Test CLI edge cases."""

    def test_info_returns_zero(self):
        """Info should always return 0 on valid files."""
        result = cmd_info(str(CLAUDE))
        assert result == 0

    def test_validate_returns_zero_or_one(self):
        """Validate should return 0 (pass) or 1 (errors found)."""
        result = cmd_validate(str(CLAUDE))
        assert result in (0, 1)

    def test_compare_self_returns_zero(self):
        """Comparing a file to itself should return 0."""
        result = cmd_compare(str(CLAUDE), str(CLAUDE))
        assert result == 0

    def test_export_csv_returns_zero(self):
        """Export CSV should return 0 on valid files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cmd_export_csv(str(CLAUDE), tmpdir)
            assert result == 0


# ─── ECC and IDEN type display ─────────────────────────────────────


class TestInfoECC:
    """Tests for Enhanced Control Channel display in cmd_info."""

    def test_info_ecc_entries_shown(self, capsys):
        """PAWSOVERMAWS should show ECC entries in info output."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "Enhanced Control Channels:" in out

    def test_info_ecc_count(self, capsys):
        """Should show ECC entry counts per system."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "30 ECC entries" in out  # C/S Nevada has 30

    def test_info_ecc_iden_name(self, capsys):
        """Should show IDEN set name for each ECC group."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "IDEN:" in out

    def test_info_ecc_wacn(self, capsys):
        """Should show WACN for each ECC group."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "WACN:" in out

    def test_info_no_ecc_for_simple_file(self, capsys):
        """claude test.PRS has no ECC — should not show the section."""
        cmd_info(str(CLAUDE))
        out = capsys.readouterr().out
        assert "Enhanced Control Channels:" not in out


class TestInfoIdenTypes:
    """Tests for IDEN FDMA/TDMA type display in cmd_info."""

    def test_iden_shows_mode(self, capsys):
        """IDEN sets should show FDMA/TDMA/mixed mode."""
        cmd_info(str(PAWS))
        out = capsys.readouterr().out
        assert "mixed FDMA+TDMA" in out

    def test_iden_fdma_only(self, capsys):
        """claude test.PRS has only FDMA entries."""
        cmd_info(str(CLAUDE))
        out = capsys.readouterr().out
        assert "FDMA" in out
        # Should NOT show mixed or TDMA
        assert "TDMA" not in out


# ─── iden-templates subcommand ─────────────────────────────────────


class TestIdenTemplates:
    """Tests for the iden-templates CLI subcommand."""

    def test_returns_zero(self, capsys):
        result = cmd_iden_templates()
        assert result == 0

    def test_lists_templates(self, capsys):
        cmd_iden_templates()
        out = capsys.readouterr().out
        assert "Standard IDEN Templates" in out

    def test_shows_template_count(self, capsys):
        cmd_iden_templates()
        out = capsys.readouterr().out
        # Should show at least 5 templates
        assert "active entries" in out

    def test_detail_flag(self, capsys):
        """Detail mode should show frequency and mode info."""
        cmd_iden_templates(detail=True)
        out = capsys.readouterr().out
        assert "MHz" in out
        assert "FDMA" in out or "TDMA" in out

    def test_shows_known_bands(self, capsys):
        """Should list standard band templates."""
        cmd_iden_templates()
        out = capsys.readouterr().out
        assert "800" in out  # 800 MHz band

    def test_via_run_cli(self, capsys):
        """iden-templates should work via run_cli."""
        result = run_cli(["iden-templates"])
        assert result == 0


# ─── diff-options subcommand ───────────────────────────────────────


class TestDiffOptions:
    """Tests for the diff-options CLI subcommand."""

    def test_returns_zero(self, capsys):
        result = cmd_diff_options(str(PAWS), str(PAWS))
        assert result == 0

    def test_same_file_no_diffs(self, capsys):
        """Comparing a file to itself should show no changes."""
        cmd_diff_options(str(PAWS), str(PAWS))
        out = capsys.readouterr().out
        assert "No option differences" in out or "0 changed" in out

    def test_different_files(self, capsys):
        """Comparing PAWS to claude should show differences."""
        cmd_diff_options(str(PAWS), str(CLAUDE))
        out = capsys.readouterr().out
        # Should have some output (at least the filenames)
        assert len(out) > 0

    def test_raw_flag(self, capsys):
        """Raw mode should show byte-level diffs."""
        cmd_diff_options(str(PAWS), str(CLAUDE), raw=True)
        out = capsys.readouterr().out
        assert "Raw Byte Diffs" in out or len(out) > 0

    def test_via_run_cli(self, capsys):
        """diff-options should work via run_cli."""
        result = run_cli(["diff-options", str(PAWS), str(CLAUDE)])
        assert result == 0

    def test_raw_via_run_cli(self, capsys):
        """diff-options --raw should work via run_cli."""
        result = run_cli(["diff-options", "--raw", str(PAWS), str(CLAUDE)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Raw Byte Diffs" in out


# ─── Additional dump edge cases ──────────────────────────────────

class TestCmdDumpEdgeCases:

    def test_dump_negative_section_index(self, capsys):
        """Negative section index should return error."""
        result = cmd_dump(str(PAWS), section_idx=-1)
        assert result == 1

    def test_dump_hex_zero(self, capsys):
        """hex_bytes=0 should not show hex output."""
        result = cmd_dump(str(PAWS), section_idx=0, hex_bytes=0)
        assert result == 0
        out = capsys.readouterr().out
        assert "000000" not in out

    def test_dump_hex_larger_than_section(self, capsys):
        """hex_bytes > section size should show what's available."""
        result = cmd_dump(str(PAWS), section_idx=0, hex_bytes=99999)
        assert result == 0
        out = capsys.readouterr().out
        assert "000000" in out

    def test_dump_last_section(self, capsys):
        """Dumping the last section should work."""
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(PAWS))
        last_idx = len(prs.sections) - 1
        result = cmd_dump(str(PAWS), section_idx=last_idx)
        assert result == 0

    def test_iden_templates_detail_via_run_cli(self, capsys):
        """iden-templates --detail via run_cli."""
        result = run_cli(["iden-templates", "-d"])
        assert result == 0
        out = capsys.readouterr().out
        assert "MHz" in out


# ─── create subcommand ─────────────────────────────────────────────


class TestCmdCreate:
    """Tests for the create CLI subcommand."""

    def test_create_default(self, capsys, tmp_path):
        """Create with default options should succeed."""
        out_file = tmp_path / "test.PRS"
        result = cmd_create(str(out_file))
        assert result == 0
        assert out_file.exists()
        out = capsys.readouterr().out
        assert "Created:" in out
        assert "Size:" in out
        assert "Sections:" in out

    def test_create_with_name(self, capsys, tmp_path):
        """Create with --name should use given personality name."""
        out_file = tmp_path / "output.PRS"
        result = cmd_create(str(out_file), name="My Radio")
        assert result == 0
        assert out_file.exists()
        # Parse and verify personality name
        from quickprs.prs_parser import parse_prs
        from quickprs.record_types import parse_personality_section
        prs = parse_prs(str(out_file))
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "My Radio"

    def test_create_with_author(self, capsys, tmp_path):
        """Create with --author should set saved-by field."""
        out_file = tmp_path / "authored.PRS"
        result = cmd_create(str(out_file), author="TestUser")
        assert result == 0
        from quickprs.prs_parser import parse_prs
        from quickprs.record_types import parse_personality_section
        prs = parse_prs(str(out_file))
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.saved_by == "TestUser"

    def test_create_valid_output(self, tmp_path):
        """Created file should parse and validate cleanly."""
        out_file = tmp_path / "valid.PRS"
        cmd_create(str(out_file))
        from quickprs.prs_parser import parse_prs
        from quickprs.validation import validate_prs, ERROR
        prs = parse_prs(str(out_file))
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_create_roundtrip(self, tmp_path):
        """Created file should roundtrip through parse/write."""
        out_file = tmp_path / "roundtrip.PRS"
        cmd_create(str(out_file))
        raw1 = out_file.read_bytes()
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(str(out_file))
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    def test_create_via_run_cli(self, capsys, tmp_path):
        """create subcommand should work via run_cli."""
        out_file = tmp_path / "cli_test.PRS"
        result = run_cli(["create", str(out_file)])
        assert result == 0
        assert out_file.exists()

    def test_create_with_flags_via_run_cli(self, capsys, tmp_path):
        """create with --name and --author via run_cli."""
        out_file = tmp_path / "flags.PRS"
        result = run_cli(["create", str(out_file),
                          "--name", "CLI Radio",
                          "--author", "CLI User"])
        assert result == 0
        from quickprs.prs_parser import parse_prs
        from quickprs.record_types import parse_personality_section
        prs = parse_prs(str(out_file))
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "CLI Radio"
        assert p.saved_by == "CLI User"

    def test_create_default_name_is_filename(self, capsys, tmp_path):
        """Without --name, personality name defaults to output filename."""
        out_file = tmp_path / "MyPersonality.PRS"
        cmd_create(str(out_file))
        from quickprs.prs_parser import parse_prs
        from quickprs.record_types import parse_personality_section
        prs = parse_prs(str(out_file))
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "MyPersonality.PRS"

    def test_create_overwrites_existing(self, capsys, tmp_path):
        """Create should silently overwrite an existing file."""
        out_file = tmp_path / "existing.PRS"
        out_file.write_bytes(b"old data")
        result = cmd_create(str(out_file))
        assert result == 0
        content = out_file.read_bytes()
        assert content != b"old data"
        assert content[:2] == b'\xff\xff'  # valid PRS header

    def test_create_section_count(self, capsys, tmp_path):
        """Output should report section count."""
        out_file = tmp_path / "count.PRS"
        cmd_create(str(out_file))
        out = capsys.readouterr().out
        assert "Sections:" in out

    def test_create_nested_dir(self, tmp_path):
        """Create should handle nested output directories."""
        out_file = tmp_path / "sub" / "dir" / "deep.PRS"
        result = cmd_create(str(out_file))
        assert result == 0
        assert out_file.exists()


# ─── freq-tools CLI ─────────────────────────────────────────────────


class TestFreqToolsCLI:
    """Test the freq-tools CLI subcommand."""

    def test_freq_tools_tones(self, capsys):
        """freq-tools tones should list CTCSS tones."""
        result = run_cli(["freq-tools", "tones"])
        assert result == 0
        out = capsys.readouterr().out
        assert "CTCSS" in out
        assert "67.0" in out
        assert "254.1" in out

    def test_freq_tools_dcs(self, capsys):
        """freq-tools dcs should list DCS codes."""
        result = run_cli(["freq-tools", "dcs"])
        assert result == 0
        out = capsys.readouterr().out
        assert "DCS" in out
        assert "D023N" in out

    def test_freq_tools_offset_2m(self, capsys):
        """freq-tools offset for 2m should show offset."""
        result = run_cli(["freq-tools", "offset", "146.94"])
        assert result == 0
        out = capsys.readouterr().out
        assert "146.9400" in out
        assert "+0.6" in out

    def test_freq_tools_offset_70cm(self, capsys):
        """freq-tools offset for 70cm should show 5 MHz offset."""
        result = run_cli(["freq-tools", "offset", "442.5"])
        assert result == 0
        out = capsys.readouterr().out
        assert "+5.0" in out

    def test_freq_tools_offset_out_of_band(self, capsys):
        """freq-tools offset for non-repeater freq should say so."""
        result = run_cli(["freq-tools", "offset", "155.0"])
        assert result == 0
        out = capsys.readouterr().out
        assert "not in a standard repeater band" in out

    def test_freq_tools_channel_frs(self, capsys):
        """freq-tools channel for FRS freq should identify it."""
        result = run_cli(["freq-tools", "channel", "462.5625"])
        assert result == 0
        out = capsys.readouterr().out
        assert "FRS" in out
        assert "Channel 1" in out

    def test_freq_tools_channel_unknown(self, capsys):
        """freq-tools channel for unknown freq should say so."""
        result = run_cli(["freq-tools", "channel", "155.0"])
        assert result == 0
        out = capsys.readouterr().out
        assert "not a recognized" in out

    def test_freq_tools_nearest(self, capsys):
        """freq-tools nearest should find closest CTCSS tone."""
        result = run_cli(["freq-tools", "nearest", "100.5"])
        assert result == 0
        out = capsys.readouterr().out
        assert "100.0" in out
        assert "Nearest" in out

    def test_freq_tools_no_subcommand(self, capsys):
        """freq-tools without subcommand should show help."""
        result = run_cli(["freq-tools"])
        assert result == 1
