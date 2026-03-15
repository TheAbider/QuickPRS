"""Tests for the backup module and CLI backup subcommand."""

import os
import tempfile
import time
from pathlib import Path

import pytest

from quickprs.backup import (
    create_backup,
    list_backups,
    restore_backup,
    BACKUP_DIR_NAME,
    MAX_BACKUPS,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"


def _make_test_prs(directory, name="test.PRS", content=b"TESTPRS"):
    """Create a minimal test PRS file."""
    path = Path(directory) / name
    path.write_bytes(content)
    return path


class TestCreateBackup:
    """Tests for create_backup()."""

    def test_creates_backup_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            result = create_backup(src)
            assert Path(result).exists()
            assert Path(result).read_bytes() == b"TESTPRS"

    def test_backup_in_default_dir(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            result = create_backup(src)
            backup_dir = Path(d) / BACKUP_DIR_NAME
            assert backup_dir.exists()
            assert Path(result).parent == backup_dir

    def test_backup_in_custom_dir(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            custom = Path(d) / "my_backups"
            result = create_backup(src, backup_dir=custom)
            assert Path(result).parent == custom

    def test_backup_has_timestamp_name(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            result = create_backup(src)
            name = Path(result).name
            # Should be like test_20260314_120000.PRS
            assert name.startswith("test_")
            assert name.endswith(".PRS")
            # Extract timestamp part
            ts_part = name[len("test_"):-len(".PRS")]
            assert len(ts_part) == 22  # YYYYMMDD_HHMMSS_ffffff

    def test_backup_preserves_content(self):
        with tempfile.TemporaryDirectory() as d:
            content = b"\x00\x01\x02" * 100
            src = _make_test_prs(d, content=content)
            result = create_backup(src)
            assert Path(result).read_bytes() == content

    def test_file_not_found_raises(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "nonexistent.PRS"
            with pytest.raises(FileNotFoundError):
                create_backup(fake)

    def test_multiple_backups_created(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            paths = []
            for i in range(3):
                # Ensure distinct timestamps
                time.sleep(0.05)
                src.write_bytes(f"version{i}".encode())
                paths.append(create_backup(src))
            # All three should exist
            for p in paths:
                assert Path(p).exists()

    def test_pruning_keeps_max_backups(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            for i in range(MAX_BACKUPS + 5):
                time.sleep(0.02)
                src.write_bytes(f"v{i}".encode())
                create_backup(src)
            backup_dir = Path(d) / BACKUP_DIR_NAME
            remaining = list(backup_dir.glob("test_*.PRS"))
            assert len(remaining) == MAX_BACKUPS

    def test_pruning_keeps_newest(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            for i in range(MAX_BACKUPS + 3):
                time.sleep(0.02)
                src.write_bytes(f"v{i}".encode())
                create_backup(src)
            backup_dir = Path(d) / BACKUP_DIR_NAME
            remaining = sorted(
                backup_dir.glob("test_*.PRS"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            # The newest backup should have the last content
            newest_content = remaining[0].read_bytes()
            assert newest_content == f"v{MAX_BACKUPS + 2}".encode()

    def test_real_prs_file_backup(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        with tempfile.TemporaryDirectory() as d:
            # Copy test file to temp dir
            test_file = Path(d) / "test.PRS"
            test_file.write_bytes(CLAUDE.read_bytes())
            result = create_backup(test_file)
            assert Path(result).read_bytes() == CLAUDE.read_bytes()


class TestListBackups:
    """Tests for list_backups()."""

    def test_no_backups_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            result = list_backups(src)
            assert result == []

    def test_lists_existing_backups(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            create_backup(src)
            time.sleep(0.02)
            create_backup(src)
            result = list_backups(src)
            assert len(result) == 2

    def test_backups_newest_first(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            src.write_bytes(b"old")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"new")
            create_backup(src)
            result = list_backups(src)
            # Index 1 = newest
            assert result[0][0] == 1
            assert result[0][1].read_bytes() == b"new"
            assert result[1][0] == 2
            assert result[1][1].read_bytes() == b"old"

    def test_list_returns_tuples(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            create_backup(src)
            result = list_backups(src)
            assert len(result) == 1
            idx, path, mtime = result[0]
            assert idx == 1
            assert isinstance(path, Path)
            assert hasattr(mtime, 'strftime')  # datetime object

    def test_no_backup_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            # File exists but no backup dir
            src = _make_test_prs(d)
            assert list_backups(src) == []

    def test_only_lists_matching_stem(self):
        """Backups for other files should not appear."""
        with tempfile.TemporaryDirectory() as d:
            file_a = _make_test_prs(d, name="alpha.PRS")
            file_b = _make_test_prs(d, name="bravo.PRS")
            create_backup(file_a)
            create_backup(file_b)
            result_a = list_backups(file_a)
            result_b = list_backups(file_b)
            assert len(result_a) == 1
            assert len(result_b) == 1
            assert "alpha_" in result_a[0][1].name
            assert "bravo_" in result_b[0][1].name


class TestRestoreBackup:
    """Tests for restore_backup()."""

    def test_restore_most_recent(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"original")
            create_backup(src)
            time.sleep(0.02)
            # Modify the file
            src.write_bytes(b"modified")
            # Restore
            restore_backup(src)
            assert src.read_bytes() == b"original"

    def test_restore_specific_index(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"v1")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v2")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v3")
            # Restore from index 2 (second newest = v1)
            restore_backup(src, index=2)
            assert src.read_bytes() == b"v1"

    def test_restore_index_1_is_newest(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"v1")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v2")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v3")
            # Restore from index 1 (newest = v2)
            restore_backup(src, index=1)
            assert src.read_bytes() == b"v2"

    def test_restore_no_backups_raises(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            with pytest.raises(FileNotFoundError, match="No backups"):
                restore_backup(src)

    def test_restore_invalid_index_raises(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            create_backup(src)
            with pytest.raises(ValueError, match="out of range"):
                restore_backup(src, index=5)

    def test_restore_index_zero_raises(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            create_backup(src)
            with pytest.raises(ValueError, match="out of range"):
                restore_backup(src, index=0)

    def test_restore_from_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"original")
            backup_path = create_backup(src)
            src.write_bytes(b"modified")
            restore_backup(src, backup_path=backup_path)
            assert src.read_bytes() == b"original"

    def test_restore_explicit_path_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            with pytest.raises(FileNotFoundError, match="Backup not found"):
                restore_backup(src, backup_path="/nonexistent/backup.PRS")

    def test_restore_returns_backup_path(self):
        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            bp = create_backup(src)
            result = restore_backup(src)
            assert result == bp


class TestWriterIntegration:
    """Test that prs_writer creates auto-backups."""

    def test_write_creates_auto_backup(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs

        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.PRS"
            # First write — no backup (file doesn't exist yet)
            write_prs(prs, out)
            backup_dir = Path(d) / BACKUP_DIR_NAME
            assert not backup_dir.exists()

            # Second write — should create auto-backup
            write_prs(prs, out)
            assert backup_dir.exists()
            backups = list(backup_dir.glob("out_*.PRS"))
            assert len(backups) >= 1

    def test_write_backup_false_no_auto_backup(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs

        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.PRS"
            write_prs(prs, out)
            write_prs(prs, out, backup=False)
            backup_dir = Path(d) / BACKUP_DIR_NAME
            assert not backup_dir.exists()


class TestCLIBackup:
    """Test CLI backup subcommand dispatch."""

    def test_cli_backup_create(self):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            rc = run_cli(["backup", str(src)])
            assert rc == 0
            backup_dir = Path(d) / BACKUP_DIR_NAME
            assert backup_dir.exists()
            assert len(list(backup_dir.glob("test_*.PRS"))) == 1

    def test_cli_backup_list_empty(self, capsys):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            rc = run_cli(["backup", str(src), "--list"])
            assert rc == 0
            out = capsys.readouterr().out
            assert "No backups" in out

    def test_cli_backup_list_with_backups(self, capsys):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            create_backup(src)
            rc = run_cli(["backup", str(src), "--list"])
            assert rc == 0
            out = capsys.readouterr().out
            assert "Backups for" in out
            assert "1." in out

    def test_cli_backup_restore(self, capsys):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"original")
            create_backup(src)
            src.write_bytes(b"modified")
            rc = run_cli(["backup", str(src), "--restore"])
            assert rc == 0
            assert src.read_bytes() == b"original"
            out = capsys.readouterr().out
            assert "Restored" in out

    def test_cli_backup_restore_index(self, capsys):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d, content=b"v1")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v2")
            create_backup(src)
            time.sleep(0.05)
            src.write_bytes(b"v3")
            rc = run_cli(["backup", str(src), "--restore", "2"])
            assert rc == 0
            assert src.read_bytes() == b"v1"

    def test_cli_backup_file_not_found(self, capsys):
        from quickprs.cli import run_cli

        rc = run_cli(["backup", "/nonexistent/file.PRS"])
        assert rc == 1

    def test_cli_backup_restore_no_backups(self, capsys):
        from quickprs.cli import run_cli

        with tempfile.TemporaryDirectory() as d:
            src = _make_test_prs(d)
            rc = run_cli(["backup", str(src), "--restore"])
            assert rc == 1
            err = capsys.readouterr().err
            assert "No backups" in err
