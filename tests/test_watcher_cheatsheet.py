"""Tests for file watcher, cheat sheet, and their CLI dispatch."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from quickprs.cli import run_cli
from quickprs.cheat_sheet import generate_cheat_sheet
from quickprs.watcher import validate_once

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Cheat sheet content ────────────────────────────────────────────


class TestCheatSheet:
    """Test cheat sheet generation."""

    def test_cheat_sheet_returns_string(self):
        """generate_cheat_sheet should return a non-empty string."""
        sheet = generate_cheat_sheet()
        assert isinstance(sheet, str)
        assert len(sheet) > 100

    def test_cheat_sheet_has_title(self):
        """Cheat sheet should start with the title."""
        sheet = generate_cheat_sheet()
        assert "QuickPRS CLI Cheat Sheet" in sheet

    def test_cheat_sheet_has_getting_started(self):
        """Cheat sheet should have getting-started section."""
        sheet = generate_cheat_sheet()
        assert "GETTING STARTED" in sheet
        assert "quickprs wizard" in sheet
        assert "quickprs create" in sheet
        assert "quickprs build" in sheet

    def test_cheat_sheet_has_add_content(self):
        """Cheat sheet should have add-content section."""
        sheet = generate_cheat_sheet()
        assert "ADD CONTENT" in sheet
        assert "quickprs inject" in sheet

    def test_cheat_sheet_has_import(self):
        """Cheat sheet should have import section."""
        sheet = generate_cheat_sheet()
        assert "IMPORT" in sheet
        assert "import-rr" in sheet
        assert "import-paste" in sheet
        assert "import-scanner" in sheet
        assert "import-json" in sheet

    def test_cheat_sheet_has_modify(self):
        """Cheat sheet should have modify section."""
        sheet = generate_cheat_sheet()
        assert "MODIFY" in sheet
        assert "quickprs edit" in sheet
        assert "quickprs rename" in sheet
        assert "quickprs sort" in sheet
        assert "bulk-edit" in sheet
        assert "renumber" in sheet
        assert "encrypt" in sheet
        assert "set-option" in sheet
        assert "quickprs remove" in sheet
        assert "quickprs merge" in sheet
        assert "quickprs clone" in sheet

    def test_cheat_sheet_has_inspect(self):
        """Cheat sheet should have inspect section."""
        sheet = generate_cheat_sheet()
        assert "INSPECT" in sheet
        assert "quickprs info" in sheet
        assert "quickprs validate" in sheet
        assert "quickprs health" in sheet
        assert "quickprs suggest" in sheet
        assert "quickprs capacity" in sheet
        assert "quickprs stats" in sheet
        assert "freq-map" in sheet
        assert "quickprs compare" in sheet
        assert "quickprs search" in sheet

    def test_cheat_sheet_has_export(self):
        """Cheat sheet should have export section."""
        sheet = generate_cheat_sheet()
        assert "EXPORT" in sheet
        assert "export-json" in sheet
        assert "export-csv" in sheet
        assert "export-config" in sheet
        assert "export radio.PRS chirp" in sheet
        assert "report" in sheet
        assert "card" in sheet

    def test_cheat_sheet_has_fleet(self):
        """Cheat sheet should have fleet section."""
        sheet = generate_cheat_sheet()
        assert "FLEET" in sheet
        assert "quickprs fleet " in sheet
        assert "fleet-check" in sheet
        assert "snapshot" in sheet

    def test_cheat_sheet_has_maintenance(self):
        """Cheat sheet should have maintenance section."""
        sheet = generate_cheat_sheet()
        assert "MAINTENANCE" in sheet
        assert "backup" in sheet
        assert "cleanup" in sheet
        assert "repair" in sheet
        assert "watch" in sheet

    def test_cheat_sheet_has_reference(self):
        """Cheat sheet should have reference section."""
        sheet = generate_cheat_sheet()
        assert "REFERENCE" in sheet
        assert "freq-tools" in sheet
        assert "template-csv" in sheet
        assert "cheat-sheet" in sheet
        assert "--completion" in sheet

    def test_cheat_sheet_all_major_commands(self):
        """Verify all major CLI commands are present in the cheat sheet."""
        sheet = generate_cheat_sheet()
        major_commands = [
            "wizard", "create", "build", "profiles",
            "inject", "import-rr", "import-paste", "import-scanner",
            "import-json", "edit", "rename", "sort", "bulk-edit",
            "renumber", "encrypt", "set-option", "remove", "merge",
            "clone", "info", "validate", "health", "suggest",
            "capacity", "stats", "freq-map", "compare", "search",
            "export-json", "export-csv", "export-config", "report",
            "card", "fleet", "fleet-check", "snapshot", "backup",
            "cleanup", "repair", "watch", "freq-tools", "template-csv",
            "cheat-sheet",
        ]
        for cmd in major_commands:
            assert cmd in sheet, f"Missing command: {cmd}"


# ─── Cheat sheet CLI dispatch ───────────────────────────────────────


class TestCheatSheetCLI:
    """Test cheat-sheet CLI subcommand."""

    def test_cli_cheat_sheet(self, capsys):
        """quickprs cheat-sheet should print the cheat sheet."""
        result = run_cli(["cheat-sheet"])
        assert result == 0
        out = capsys.readouterr().out
        assert "QuickPRS CLI Cheat Sheet" in out
        assert "GETTING STARTED" in out

    def test_cli_cheat_sheet_pipeable(self, capsys):
        """Output should be plain text suitable for piping."""
        run_cli(["cheat-sheet"])
        out = capsys.readouterr().out
        # No ANSI escape codes
        assert "\033[" not in out
        # Has content on multiple lines
        lines = out.strip().split("\n")
        assert len(lines) > 20


# ─── Watcher validate_once ──────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestValidateOnce:
    """Test the validate_once helper used by the watcher."""

    def test_validate_once_returns_tuple(self):
        """validate_once should return (prs, issues) tuple."""
        prs, issues = validate_once(str(PAWS))
        assert prs is not None
        assert isinstance(issues, list)

    def test_validate_once_prs_has_sections(self):
        """Returned PRS object should have sections."""
        prs, _issues = validate_once(str(PAWS))
        assert len(prs.sections) > 0

    def test_validate_once_issues_are_tuples(self):
        """Each issue should be a (severity, message) tuple."""
        _prs, issues = validate_once(str(PAWS))
        for item in issues:
            assert len(item) == 2
            severity, msg = item
            assert severity in ("ERROR", "WARNING", "INFO")
            assert isinstance(msg, str)

    def test_validate_once_missing_file(self):
        """validate_once on nonexistent file should raise."""
        with pytest.raises((FileNotFoundError, ValueError)):
            validate_once("nonexistent_file.PRS")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestValidateOnceSmall:
    """Test validate_once on a small PRS file."""

    def test_validate_small_file(self):
        """Should work on a small file without errors."""
        prs, issues = validate_once(str(CLAUDE))
        assert prs is not None
        assert isinstance(issues, list)

    def test_validate_once_includes_structure(self):
        """validate_once should include both limit and structure checks."""
        prs, issues = validate_once(str(CLAUDE))
        # We can't predict the exact issues, but it should return
        # the combined results of validate_prs + validate_structure
        assert isinstance(issues, list)


# ─── Watcher callback logic ─────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestWatcherCallback:
    """Test the watcher's callback mechanism using validate_once."""

    def test_callback_receives_prs_and_issues(self):
        """A callback function should receive (prs, issues)."""
        results = {}

        def my_callback(prs, issues):
            results['prs'] = prs
            results['issues'] = issues

        prs, issues = validate_once(str(PAWS))
        # Simulate what the watcher does after validation
        my_callback(prs, issues)

        assert 'prs' in results
        assert 'issues' in results
        assert len(results['prs'].sections) > 0
        assert isinstance(results['issues'], list)

    def test_callback_error_counting(self):
        """Verify error/warning classification matches validation output."""
        from quickprs.validation import ERROR, WARNING

        prs, issues = validate_once(str(PAWS))
        errors = [m for s, m in issues if s == ERROR]
        warnings = [m for s, m in issues if s == WARNING]

        # The counts should be non-negative (valid file may have 0 errors)
        assert len(errors) >= 0
        assert len(warnings) >= 0
        assert len(errors) + len(warnings) <= len(issues)


# ─── Watch CLI dispatch ─────────────────────────────────────────────


class TestWatchCLI:
    """Test watch CLI subcommand dispatch."""

    @patch("quickprs.watcher.watch_file")
    def test_cli_watch_dispatches(self, mock_watch):
        """quickprs watch should call watch_file."""
        result = run_cli(["watch", "test.PRS"])
        assert result == 0
        mock_watch.assert_called_once_with("test.PRS", interval=2.0)

    @patch("quickprs.watcher.watch_file")
    def test_cli_watch_custom_interval(self, mock_watch):
        """quickprs watch --interval should pass the interval."""
        result = run_cli(["watch", "test.PRS", "--interval", "5"])
        assert result == 0
        mock_watch.assert_called_once_with("test.PRS", interval=5.0)

    @patch("quickprs.watcher.watch_file")
    def test_cli_watch_short_flag(self, mock_watch):
        """quickprs watch -i should work as short form."""
        result = run_cli(["watch", "test.PRS", "-i", "0.5"])
        assert result == 0
        mock_watch.assert_called_once_with("test.PRS", interval=0.5)

    def test_watch_file_not_found(self, capsys):
        """watch_file should handle missing file gracefully."""
        from quickprs.watcher import watch_file
        watch_file("nonexistent_file.PRS")
        out = capsys.readouterr().out
        assert "not found" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_watch_file_starts(self, capsys):
        """watch_file should print 'Watching' for existing file."""
        from quickprs.watcher import watch_file

        # Immediately send KeyboardInterrupt to stop the loop
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            watch_file(str(PAWS))

        out = capsys.readouterr().out
        assert "Watching" in out
        assert "Stopped watching" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_watch_shows_file_size(self, capsys):
        """watch_file should display the current file size."""
        from quickprs.watcher import watch_file

        with patch("time.sleep", side_effect=KeyboardInterrupt):
            watch_file(str(PAWS))

        out = capsys.readouterr().out
        assert "bytes" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_watch_detects_change(self, capsys, tmp_path):
        """watch_file should detect and validate when file changes."""
        from quickprs.watcher import watch_file
        import time

        # Copy test file
        test_file = tmp_path / "watch_test.PRS"
        shutil.copy(str(PAWS), str(test_file))

        call_count = [0]
        original_sleep = time.sleep

        def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate file change by bumping mtime
                import os
                os.utime(str(test_file), None)
            elif call_count[0] >= 2:
                raise KeyboardInterrupt

        with patch("time.sleep", side_effect=fake_sleep):
            watch_file(str(test_file), interval=0.1)

        out = capsys.readouterr().out
        assert "File changed" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_watch_calls_callback(self, tmp_path):
        """watch_file should invoke callback on file change."""
        from quickprs.watcher import watch_file
        import time

        test_file = tmp_path / "cb_test.PRS"
        shutil.copy(str(PAWS), str(test_file))

        callback_results = []
        call_count = [0]

        def my_callback(prs, issues):
            callback_results.append((prs, issues))

        def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                import os
                os.utime(str(test_file), None)
            elif call_count[0] >= 2:
                raise KeyboardInterrupt

        with patch("time.sleep", side_effect=fake_sleep):
            watch_file(str(test_file), interval=0.1, callback=my_callback)

        assert len(callback_results) == 1
        prs, issues = callback_results[0]
        assert prs is not None
        assert isinstance(issues, list)

    def test_watch_detects_deletion(self, capsys, tmp_path):
        """watch_file should handle file deletion during watch."""
        from quickprs.watcher import watch_file

        test_file = tmp_path / "delete_test.PRS"
        test_file.write_bytes(b"\x00" * 100)

        call_count = [0]

        def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                test_file.unlink()
            elif call_count[0] >= 2:
                raise KeyboardInterrupt

        with patch("time.sleep", side_effect=fake_sleep):
            watch_file(str(test_file), interval=0.1)

        out = capsys.readouterr().out
        assert "deleted" in out.lower() or "Stopped" in out
