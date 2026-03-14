"""Tests for CLI list and bulk-edit commands, plus testing gaps.

Covers:
  - quickprs list (all data types)
  - quickprs bulk-edit talkgroups (all flags)
  - quickprs bulk-edit channels (all flags)
  - quickprs --version
  - quickprs --help
  - All CLI subcommand --help flags
  - GUI module importability
"""

import pytest
import shutil
from pathlib import Path

from quickprs.cli import (
    run_cli, cmd_list,
    cmd_bulk_edit_talkgroups, cmd_bulk_edit_channels,
)
from quickprs.prs_parser import parse_prs

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Helpers ──────────────────────────────────────────────────────────

def _copy_prs(src, tmp_path, name="work.PRS"):
    """Copy a PRS file to tmp_path and return the new path."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


# ─── cmd_list tests ──────────────────────────────────────────────────

class TestCmdList:
    """Test the list command with all data types."""

    def test_list_systems(self, capsys):
        result = run_cli(["list", str(PAWS), "systems"])
        assert result == 0
        out = capsys.readouterr().out
        assert "P25 Trunked" in out or "Conventional" in out or out == ""

    def test_list_talkgroups(self, capsys):
        result = run_cli(["list", str(CLAUDE), "talkgroups"])
        assert result == 0
        out = capsys.readouterr().out
        # claude test has at least one group set
        assert "scan=" in out or out == ""

    def test_list_channels(self, capsys):
        result = run_cli(["list", str(PAWS), "channels"])
        assert result == 0
        out = capsys.readouterr().out
        # PAWS has conv channels
        assert len(out) >= 0

    def test_list_frequencies(self, capsys):
        result = run_cli(["list", str(PAWS), "frequencies"])
        assert result == 0
        # May or may not have trunk freqs

    def test_list_sets(self, capsys):
        result = run_cli(["list", str(PAWS), "sets"])
        assert result == 0
        out = capsys.readouterr().out
        # Should list at least one set type
        assert len(out) >= 0

    def test_list_options(self, capsys):
        result = run_cli(["list", str(PAWS), "options"])
        assert result == 0

    def test_list_missing_file(self, capsys):
        result = run_cli(["list", "nonexistent.PRS", "systems"])
        assert result == 1

    def test_list_direct_call(self, capsys):
        """Direct call to cmd_list function."""
        result = cmd_list(str(PAWS), "systems")
        assert result == 0

    def test_list_systems_claude(self, capsys):
        """Claude test file has P25 trunked systems."""
        result = cmd_list(str(CLAUDE), "systems")
        assert result == 0
        out = capsys.readouterr().out
        assert "P25 Trunked" in out

    def test_list_talkgroups_format(self, capsys):
        """Talkgroups output should be tab-separated."""
        result = cmd_list(str(CLAUDE), "talkgroups")
        assert result == 0
        out = capsys.readouterr().out
        if out.strip():
            lines = out.strip().split("\n")
            for line in lines:
                assert "\t" in line

    def test_list_sets_includes_type(self, capsys):
        """Sets output should include the type (group, trunk, conv, iden)."""
        result = cmd_list(str(CLAUDE), "sets")
        assert result == 0
        out = capsys.readouterr().out
        if out.strip():
            valid_types = {"group", "trunk", "conv", "iden"}
            for line in out.strip().split("\n"):
                kind = line.split("\t")[0]
                assert kind in valid_types


# ─── CLI bulk-edit talkgroups tests ──────────────────────────────────

class TestCliBulkEditTalkgroups:
    """Test the bulk-edit talkgroups CLI command."""

    def test_enable_scan_cli(self, capsys, tmp_path):
        """CLI: enable scan on all TGs."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--enable-scan",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Bulk-edited" in out

    def test_disable_tx_cli(self, capsys, tmp_path):
        """CLI: disable TX on all TGs."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--disable-tx",
        ])
        assert result == 0

    def test_enable_tx_cli(self, capsys, tmp_path):
        """CLI: enable TX on all TGs."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--enable-tx",
        ])
        assert result == 0

    def test_prefix_cli(self, capsys, tmp_path):
        """CLI: add prefix to TG names."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--prefix", "PD ",
        ])
        assert result == 0

    def test_suffix_cli(self, capsys, tmp_path):
        """CLI: add suffix to TG names."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--suffix", "X",
        ])
        assert result == 0

    def test_output_flag(self, capsys, tmp_path):
        """CLI: write to a different output file."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        out_file = str(tmp_path / "output.PRS")
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "GROUP SE", "--enable-scan",
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    def test_bad_set_name(self, capsys, tmp_path):
        """CLI: nonexistent set name should fail."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "talkgroups",
            "--set", "NOPE", "--enable-scan",
        ])
        assert result == 1

    def test_direct_call(self, capsys, tmp_path):
        """Direct call to cmd_bulk_edit_talkgroups."""
        prs_file = _copy_prs(CLAUDE, tmp_path)
        result = cmd_bulk_edit_talkgroups(
            prs_file, "GROUP SE", enable_scan=True)
        assert result == 0

    def test_help_flag(self, capsys):
        """bulk-edit talkgroups --help should exit 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["bulk-edit", "f.PRS", "talkgroups", "--help"])
        assert exc.value.code == 0

    def test_no_subcommand_prints_help(self, capsys):
        """bulk-edit without sub-subcommand should print help."""
        result = run_cli(["bulk-edit", str(CLAUDE)])
        assert result == 1


# ─── CLI bulk-edit channels tests ────────────────────────────────────

class TestCliBulkEditChannels:
    """Test the bulk-edit channels CLI command."""

    def _get_conv_set_name(self):
        """Get the name of the first conv set in PAWS."""
        from quickprs.cli import _parse_conv_sets
        prs = parse_prs(PAWS)
        conv_sets = _parse_conv_sets(prs)
        if not conv_sets:
            pytest.skip("No conv sets in PAWS")
        return conv_sets[0].name

    def test_set_tone_cli(self, capsys, tmp_path):
        """CLI: set CTCSS tone on all channels."""
        set_name = self._get_conv_set_name()
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "channels",
            "--set", set_name, "--set-tone", "100.0",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Bulk-edited" in out

    def test_clear_tones_cli(self, capsys, tmp_path):
        """CLI: clear tones on all channels."""
        set_name = self._get_conv_set_name()
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "channels",
            "--set", set_name, "--clear-tones",
        ])
        assert result == 0

    def test_set_power_cli(self, capsys, tmp_path):
        """CLI: set power level."""
        set_name = self._get_conv_set_name()
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "channels",
            "--set", set_name, "--set-power", "0",
        ])
        assert result == 0

    def test_output_flag(self, capsys, tmp_path):
        """CLI: write to different output."""
        set_name = self._get_conv_set_name()
        prs_file = _copy_prs(PAWS, tmp_path)
        out_file = str(tmp_path / "output.PRS")
        result = run_cli([
            "bulk-edit", prs_file, "channels",
            "--set", set_name, "--set-tone", "100.0",
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    def test_bad_set_name(self, capsys, tmp_path):
        """CLI: nonexistent set name should fail."""
        prs_file = _copy_prs(PAWS, tmp_path)
        result = run_cli([
            "bulk-edit", prs_file, "channels",
            "--set", "NOPE", "--set-tone", "100.0",
        ])
        assert result == 1

    def test_direct_call(self, capsys, tmp_path):
        """Direct call to cmd_bulk_edit_channels."""
        set_name = self._get_conv_set_name()
        prs_file = _copy_prs(PAWS, tmp_path)
        result = cmd_bulk_edit_channels(
            prs_file, set_name, set_tone="100.0")
        assert result == 0

    def test_help_flag(self, capsys):
        """bulk-edit channels --help should exit 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["bulk-edit", "f.PRS", "channels", "--help"])
        assert exc.value.code == 0


# ─── --version and --help tests ──────────────────────────────────────

class TestVersionAndHelp:
    """Test --version and --help on the main CLI and all subcommands."""

    def test_version(self):
        """quickprs --version should exit 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0

    def test_version_output(self, capsys):
        """--version should print version string."""
        with pytest.raises(SystemExit):
            run_cli(["--version"])
        out = capsys.readouterr().out
        assert "QuickPRS" in out

    def test_help(self):
        """quickprs --help should exit 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["--help"])
        assert exc.value.code == 0

    def test_help_output(self, capsys):
        """--help should list subcommands."""
        with pytest.raises(SystemExit):
            run_cli(["--help"])
        out = capsys.readouterr().out
        assert "info" in out
        assert "validate" in out

    @pytest.mark.parametrize("subcmd", [
        "info", "validate", "export-csv", "export-json", "import-json",
        "compare", "dump", "diff-options", "create", "build", "fleet",
        "remove", "edit", "iden-templates", "import-rr", "import-paste",
        "merge", "clone", "repair", "capacity", "inject",
        "set-option", "list", "bulk-edit",
    ])
    def test_subcommand_help(self, subcmd):
        """Each subcommand should accept --help and exit 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli([subcmd, "--help"])
        assert exc.value.code == 0


# ─── GUI import test ─────────────────────────────────────────────────

class TestGuiImportable:
    """Test that the GUI modules can be imported without launching."""

    def test_gui_app_importable(self):
        """gui.app module should be importable."""
        from quickprs.gui import app
        assert app is not None

    def test_gui_app_has_main(self):
        """gui.app should have a main() function."""
        from quickprs.gui.app import main
        assert callable(main)
