"""Tests for demo mode, interactive tutorial, and about command."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from quickprs.cli import run_cli
from quickprs.demo import run_demo, run_tutorial, show_about


# ─── Feature 1: Demo Mode ────────────────────────────────────────────


class TestRunDemo:
    """Test the non-interactive demo."""

    def test_demo_returns_zero(self, tmp_path):
        """Demo should complete successfully and return 0."""
        rc = run_demo(output_dir=str(tmp_path))
        assert rc == 0

    def test_demo_creates_prs(self, tmp_path):
        """Demo should produce a valid PRS file."""
        run_demo(output_dir=str(tmp_path))
        prs_file = tmp_path / "DEMO_PATROL.PRS"
        assert prs_file.exists()
        assert prs_file.stat().st_size > 0

    def test_demo_creates_json(self, tmp_path):
        """Demo should produce a valid JSON export."""
        run_demo(output_dir=str(tmp_path))
        json_file = tmp_path / "DEMO_PATROL.json"
        assert json_file.exists()
        data = json.loads(json_file.read_text(encoding='utf-8'))
        assert isinstance(data, dict)

    def test_demo_creates_ini(self, tmp_path):
        """Demo should produce an INI config export."""
        run_demo(output_dir=str(tmp_path))
        ini_file = tmp_path / "DEMO_PATROL.ini"
        assert ini_file.exists()
        content = ini_file.read_text(encoding='utf-8')
        assert "[personality]" in content

    def test_demo_creates_html_report(self, tmp_path):
        """Demo should produce an HTML report."""
        run_demo(output_dir=str(tmp_path))
        report = tmp_path / "DEMO_PATROL_report.html"
        assert report.exists()
        content = report.read_text(encoding='utf-8')
        assert "<html" in content.lower() or "<!doctype" in content.lower()

    def test_demo_creates_summary_card(self, tmp_path):
        """Demo should produce a summary card."""
        run_demo(output_dir=str(tmp_path))
        card = tmp_path / "DEMO_PATROL_card.html"
        assert card.exists()
        content = card.read_text(encoding='utf-8')
        assert "<html" in content.lower() or "<!doctype" in content.lower()

    def test_demo_prs_validates(self, tmp_path):
        """Demo output PRS should pass validation."""
        from quickprs.prs_parser import parse_prs
        from quickprs.validation import validate_prs, ERROR

        run_demo(output_dir=str(tmp_path))
        prs_file = tmp_path / "DEMO_PATROL.PRS"
        prs = parse_prs(str(prs_file))
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_demo_prs_roundtrips(self, tmp_path):
        """Demo PRS should roundtrip through parse/write."""
        from quickprs.prs_parser import parse_prs

        run_demo(output_dir=str(tmp_path))
        prs_file = tmp_path / "DEMO_PATROL.PRS"
        original = prs_file.read_bytes()

        prs = parse_prs(str(prs_file))
        rebuilt = prs.to_bytes()
        assert rebuilt == original

    def test_demo_prs_has_systems(self, tmp_path):
        """Demo PRS should have the expected systems."""
        run_demo(output_dir=str(tmp_path))

        # Use JSON export to verify content
        json_file = tmp_path / "DEMO_PATROL.json"
        data = json.loads(json_file.read_text(encoding='utf-8'))

        # Should have systems
        assert len(data.get("systems", [])) >= 1

        # Should have trunk, group, conv sets
        assert len(data.get("trunk_sets", [])) >= 1
        assert len(data.get("group_sets", [])) >= 1
        assert len(data.get("conv_sets", [])) >= 3  # MURS + NOAA + INTEROP + default

    def test_demo_json_has_expected_content(self, tmp_path):
        """Demo JSON export should contain expected data."""
        run_demo(output_dir=str(tmp_path))
        json_file = tmp_path / "DEMO_PATROL.json"
        data = json.loads(json_file.read_text(encoding='utf-8'))

        # Should have systems
        assert "systems" in data
        assert len(data["systems"]) >= 1

    def test_demo_default_output_dir(self, tmp_path, capsys, monkeypatch):
        """Demo with no output_dir uses demo_output/ in cwd."""
        monkeypatch.chdir(str(tmp_path))
        rc = run_demo()
        assert rc == 0
        demo_dir = tmp_path / "demo_output"
        assert demo_dir.exists()
        assert (demo_dir / "DEMO_PATROL.PRS").exists()

    def test_demo_output_text(self, tmp_path, capsys):
        """Demo should print step-by-step output."""
        run_demo(output_dir=str(tmp_path))
        output = capsys.readouterr().out

        assert "Step 1/11" in output
        assert "Step 11/11" in output
        assert "Demo complete!" in output
        assert "DEMO_PATROL.PRS" in output

    def test_demo_via_cli(self, tmp_path, capsys):
        """Test demo through the CLI dispatcher."""
        rc = run_cli(["demo", "--output-dir", str(tmp_path)])
        assert rc == 0
        assert (tmp_path / "DEMO_PATROL.PRS").exists()


# ─── Feature 2: Interactive Tutorial ─────────────────────────────────


class TestRunTutorial:
    """Test the interactive tutorial (non-interactive parts)."""

    def test_tutorial_function_exists(self):
        """run_tutorial should be importable and callable."""
        assert callable(run_tutorial)

    def test_tutorial_completes_with_mocked_input(self, capsys):
        """Tutorial should complete when input() is mocked."""
        with patch('quickprs.demo.input', return_value=''):
            rc = run_tutorial()
        assert rc == 0

        output = capsys.readouterr().out
        assert "QuickPRS Tutorial" in output
        assert "Section 1" in output
        assert "Section 8" in output
        assert "Tutorial complete!" in output

    def test_tutorial_handles_ctrl_c(self, capsys):
        """Tutorial should handle Ctrl+C gracefully."""
        with patch('quickprs.demo.input',
                   side_effect=KeyboardInterrupt):
            rc = run_tutorial()
        assert rc == 1

    def test_tutorial_handles_eof(self, capsys):
        """Tutorial should handle EOF (piped input) gracefully."""
        with patch('quickprs.demo.input', side_effect=EOFError):
            rc = run_tutorial()
        assert rc == 1

    def test_tutorial_creates_temp_files(self, capsys):
        """Tutorial should create files in a temp directory."""
        with patch('quickprs.demo.input', return_value=''):
            run_tutorial()
        output = capsys.readouterr().out
        assert "tutorial.PRS" in output

    def test_tutorial_covers_all_sections(self, capsys):
        """Tutorial should have all 8 sections."""
        with patch('quickprs.demo.input', return_value=''):
            run_tutorial()
        output = capsys.readouterr().out
        for i in range(1, 9):
            assert f"Section {i}" in output

    def test_tutorial_via_cli(self, capsys):
        """Test tutorial through the CLI dispatcher."""
        with patch('quickprs.demo.input', return_value=''):
            rc = run_cli(["tutorial"])
        assert rc == 0

    def test_tutorial_mentions_key_commands(self, capsys):
        """Tutorial output should mention essential commands."""
        with patch('quickprs.demo.input', return_value=''):
            run_tutorial()
        output = capsys.readouterr().out
        assert "quickprs create" in output
        assert "quickprs inject" in output
        assert "quickprs validate" in output
        assert "quickprs cheat-sheet" in output


# ─── Feature 3: About / Project Statistics ────────────────────────────


class TestShowAbout:
    """Test the about command output."""

    def test_about_returns_zero(self, capsys):
        """about should return 0."""
        rc = show_about()
        assert rc == 0

    def test_about_shows_version(self, capsys):
        """about should display the current version."""
        from quickprs import __version__
        show_about()
        output = capsys.readouterr().out
        assert __version__ in output

    def test_about_shows_project_name(self, capsys):
        """about should display QuickPRS."""
        show_about()
        output = capsys.readouterr().out
        assert "QuickPRS" in output

    def test_about_shows_binary_format_info(self, capsys):
        """about should show binary format statistics."""
        show_about()
        output = capsys.readouterr().out
        assert "section types decoded" in output
        assert "binary fields mapped" in output
        assert "mapped bytes" in output
        assert "Lossless roundtrip" in output

    def test_about_shows_templates(self, capsys):
        """about should list channel and profile templates."""
        show_about()
        output = capsys.readouterr().out
        assert "Channel Templates:" in output
        assert "Profile Templates:" in output
        assert "murs" in output
        assert "noaa" in output

    def test_about_shows_system_database(self, capsys):
        """about should mention the P25 system database."""
        show_about()
        output = capsys.readouterr().out
        assert "P25 System Database:" in output
        assert "US systems" in output

    def test_about_shows_github(self, capsys):
        """about should show the GitHub URL."""
        show_about()
        output = capsys.readouterr().out
        assert "github.com/TheAbider/QuickPRS" in output

    def test_about_shows_license(self, capsys):
        """about should show the license."""
        show_about()
        output = capsys.readouterr().out
        assert "MIT" in output

    def test_about_field_counts(self, capsys):
        """about should show accurate field counts."""
        show_about()
        output = capsys.readouterr().out
        # Should show 27 sections and 514+ fields (from MEMORY.md)
        assert "27 section" in output
        assert "514" in output

    def test_about_via_cli(self, capsys):
        """Test about through the CLI dispatcher."""
        rc = run_cli(["about"])
        assert rc == 0
        output = capsys.readouterr().out
        assert "QuickPRS" in output


# ─── CLI Argument Parsing ─────────────────────────────────────────────


class TestCLIArgs:
    """Test that the new CLI subcommands parse correctly."""

    def test_demo_help(self, capsys):
        """demo --help should not error."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["demo", "--help"])
        assert exc.value.code == 0

    def test_tutorial_help(self, capsys):
        """tutorial --help should not error."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["tutorial", "--help"])
        assert exc.value.code == 0

    def test_about_help(self, capsys):
        """about --help should not error."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["about", "--help"])
        assert exc.value.code == 0

    def test_demo_output_dir_arg(self, tmp_path, capsys):
        """demo --output-dir should use the specified directory."""
        out = tmp_path / "custom"
        rc = run_cli(["demo", "--output-dir", str(out)])
        assert rc == 0
        assert (out / "DEMO_PATROL.PRS").exists()


# ─── Helper Functions ─────────────────────────────────────────────────


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_can_unicode(self):
        """_can_unicode should return a boolean."""
        from quickprs.demo import _can_unicode
        result = _can_unicode()
        assert isinstance(result, bool)

    def test_print_banner(self, capsys):
        """_print_banner should produce output."""
        from quickprs.demo import _print_banner
        _print_banner("Test Title", "subtitle")
        output = capsys.readouterr().out
        assert "Test Title" in output
        assert "subtitle" in output

    def test_print_banner_no_subtitle(self, capsys):
        """_print_banner without subtitle should work."""
        from quickprs.demo import _print_banner
        _print_banner("Test")
        output = capsys.readouterr().out
        assert "Test" in output

    def test_step_output(self, capsys):
        """_step should print step info."""
        from quickprs.demo import _step
        _step(3, 10, "Doing something")
        output = capsys.readouterr().out
        assert "Step 3/10" in output
        assert "Doing something" in output

    def test_result_output(self, capsys):
        """_result should print indented result."""
        from quickprs.demo import _result
        _result("It worked!")
        output = capsys.readouterr().out
        assert "It worked!" in output

    def test_file_size(self, tmp_path):
        """_file_size should return formatted size string."""
        from quickprs.demo import _file_size
        f = tmp_path / "test.bin"
        f.write_bytes(b'\x00' * 1234)
        result = _file_size(str(f))
        assert result == "1,234"
