"""Tests for polish features: welcome screen, convert command, stdin/stdout piping."""

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from quickprs.cli import run_cli, cmd_convert, cmd_export_json, _load_prs
from conftest import cached_parse_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
PATROL_INI = TESTDATA / "example_patrol.ini"


# ─── Feature 1: GUI Welcome Screen ──────────────────────────────────


class TestWelcomeScreen:
    """Test the welcome screen builds without errors."""

    def test_welcome_method_exists(self):
        """QuickPRSApp should have a _build_welcome method."""
        from quickprs.gui.app import QuickPRSApp
        assert hasattr(QuickPRSApp, '_build_welcome')
        assert callable(getattr(QuickPRSApp, '_build_welcome'))

    def test_launch_wizard_method_exists(self):
        """QuickPRSApp should have a _launch_wizard method."""
        from quickprs.gui.app import QuickPRSApp
        assert hasattr(QuickPRSApp, '_launch_wizard')
        assert callable(getattr(QuickPRSApp, '_launch_wizard'))

    def test_show_hide_welcome_methods_exist(self):
        """QuickPRSApp should have _show_welcome and _hide_welcome."""
        from quickprs.gui.app import QuickPRSApp
        assert hasattr(QuickPRSApp, '_show_welcome')
        assert hasattr(QuickPRSApp, '_hide_welcome')


# ─── Feature 2: Format Converter ────────────────────────────────────


class TestConvertCommand:
    """Test the convert CLI subcommand."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_prs_to_json(self, tmp_path, capsys):
        """Convert PRS to JSON."""
        out = tmp_path / "output.json"
        rc = cmd_convert(str(PAWS), 'json', output_path=str(out))
        assert rc == 0
        assert out.exists()
        # Verify it's valid JSON
        data = json.loads(out.read_text(encoding='utf-8'))
        assert "systems" in data or "sections" in data or isinstance(data, dict)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_prs_to_ini(self, tmp_path, capsys):
        """Convert PRS to INI config."""
        out = tmp_path / "output.ini"
        rc = cmd_convert(str(PAWS), 'ini', output_path=str(out))
        assert rc == 0
        assert out.exists()
        content = out.read_text(encoding='utf-8')
        assert "[personality]" in content

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_prs_to_csv(self, tmp_path, capsys):
        """Convert PRS to CSV directory."""
        out_dir = tmp_path / "csv_out"
        rc = cmd_convert(str(PAWS), 'csv', output_path=str(out_dir))
        assert rc == 0
        assert out_dir.exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_prs_to_chirp(self, tmp_path, capsys):
        """Convert PRS to CHIRP CSV."""
        out = tmp_path / "chirp.csv"
        rc = cmd_convert(str(PAWS), 'chirp', output_path=str(out))
        assert rc == 0
        assert out.exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_prs_to_markdown(self, tmp_path, capsys):
        """Convert PRS to Markdown."""
        out = tmp_path / "output.md"
        rc = cmd_convert(str(PAWS), 'markdown', output_path=str(out))
        assert rc == 0
        assert out.exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_json_roundtrip(self, tmp_path, capsys):
        """Convert PRS -> JSON -> PRS roundtrip."""
        json_out = tmp_path / "intermediate.json"
        prs_out = tmp_path / "rebuilt.PRS"

        rc1 = cmd_convert(str(PAWS), 'json', output_path=str(json_out))
        assert rc1 == 0
        assert json_out.exists()

        rc2 = cmd_convert(str(json_out), 'prs', output_path=str(prs_out))
        assert rc2 == 0
        assert prs_out.exists()
        assert prs_out.stat().st_size > 0

    @pytest.mark.skipif(not PATROL_INI.exists(), reason="patrol.ini not available")
    def test_ini_to_prs(self, tmp_path, capsys):
        """Convert INI config to PRS."""
        out = tmp_path / "output.PRS"
        rc = cmd_convert(str(PATROL_INI), 'prs', output_path=str(out))
        assert rc == 0
        assert out.exists()

    def test_unknown_input_format(self, tmp_path, capsys):
        """Unknown input extension returns error."""
        fake = tmp_path / "data.xyz"
        fake.write_text("test")
        rc = cmd_convert(str(fake), 'prs')
        assert rc == 1
        err = capsys.readouterr().err
        assert "Unknown input format" in err

    def test_unsupported_json_to_ini(self, tmp_path, capsys):
        """JSON to INI is not supported."""
        fake = tmp_path / "test.json"
        fake.write_text('{"test": true}')
        rc = cmd_convert(str(fake), 'ini')
        assert rc == 1
        err = capsys.readouterr().err
        assert "Cannot convert" in err

    def test_unsupported_prs_format(self, tmp_path, capsys):
        """PRS to unknown format returns error."""
        if not PAWS.exists():
            pytest.skip("Test PRS not available")
        rc = cmd_convert(str(PAWS), 'xyz')
        assert rc == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_convert_via_run_cli(self, tmp_path, capsys):
        """Test convert through the CLI dispatcher."""
        out = tmp_path / "output.json"
        rc = run_cli(["convert", str(PAWS), "--to", "json",
                      "-o", str(out)])
        assert rc == 0
        assert out.exists()


# ─── Feature 3: Stdin/Stdout Piping ─────────────────────────────────


class TestStdinStdout:
    """Test stdin reading and stdout writing."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_load_prs_from_stdin(self):
        """_load_prs('-') should read from stdin.buffer."""
        prs_bytes = PAWS.read_bytes()
        mock_stdin = MagicMock()
        mock_stdin.buffer.read.return_value = prs_bytes

        with patch('quickprs.cli.sys') as mock_sys:
            mock_sys.stdin = mock_stdin
            mock_sys.stderr = MagicMock()
            prs = _load_prs('-')
            assert prs is not None
            assert prs.file_size == len(prs_bytes)
            assert len(prs.sections) > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_load_prs_from_file(self):
        """_load_prs with a real path should work normally."""
        prs = _load_prs(str(PAWS))
        assert prs is not None
        assert prs.file_size > 0

    def test_load_prs_stdin_empty(self):
        """_load_prs('-') with empty stdin raises ValueError."""
        mock_stdin = MagicMock()
        mock_stdin.buffer.read.return_value = b''

        with patch('quickprs.cli.sys') as mock_sys:
            mock_sys.stdin = mock_stdin
            mock_sys.stderr = MagicMock()
            with pytest.raises(ValueError, match="No data received"):
                _load_prs('-')

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_export_json_stdout(self, capsys):
        """export-json --stdout should write JSON to stdout."""
        rc = cmd_export_json(str(PAWS), stdout=True)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_export_json_stdout_via_cli(self, capsys):
        """CLI: export-json --stdout writes JSON to stdout."""
        rc = run_cli(["export-json", str(PAWS), "--stdout"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS not available")
    def test_info_stdin_via_cli(self):
        """CLI: info - reads from stdin."""
        prs_bytes = PAWS.read_bytes()
        mock_stdin = MagicMock()
        mock_stdin.buffer.read.return_value = prs_bytes

        with patch('quickprs.cli.sys') as mock_sys:
            mock_sys.stdin = mock_stdin
            mock_sys.stderr = MagicMock()
            mock_sys.argv = ['quickprs']
            # Call cmd_info directly with '-'
            from quickprs.cli import cmd_info
            rc = cmd_info('-')
            assert rc == 0 or rc is None
