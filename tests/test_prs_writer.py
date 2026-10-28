"""Tests for the prs_writer module."""

import os
import tempfile
from pathlib import Path

import pytest

from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.prs_writer import write_prs


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def test_write_creates_file():
    """write_prs creates the output file."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        size = write_prs(prs, out)
        assert out.exists()
        assert size > 0


def test_write_roundtrip_identical():
    """Written file should be byte-identical to the original."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    original = CLAUDE.read_bytes()
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)
        written = out.read_bytes()
    assert written == original


def test_write_roundtrip_paws():
    """Roundtrip PAWSOVERMAWS — larger file."""
    if not PAWS.exists():
        pytest.skip("test file not found")
    original = PAWS.read_bytes()
    prs = cached_parse_prs(PAWS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)
        written = out.read_bytes()
    assert written == original


def test_write_returns_size():
    """write_prs returns the number of bytes written."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        size = write_prs(prs, out)
    assert size == len(CLAUDE.read_bytes())


def test_backup_created_when_file_exists():
    """Backup .bak file should be created when overwriting."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        # Write once
        write_prs(prs, out)
        # Write again — should create backup
        write_prs(prs, out)
        bak = out.with_suffix(".PRS.bak")
        assert bak.exists()
        assert bak.read_bytes() == CLAUDE.read_bytes()


def test_no_backup_for_new_file():
    """No .bak should be created when writing a new file."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)
        bak = out.with_suffix(".PRS.bak")
        assert not bak.exists()


def test_backup_disabled():
    """backup=False should skip backup even if file exists."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)
        write_prs(prs, out, backup=False)
        bak = out.with_suffix(".PRS.bak")
        assert not bak.exists()


def test_overwrite_preserves_content():
    """Overwriting with modified PRS should update file content."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE)   # edited below, so not the shared cached copy
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)

        # Make a real edit so the output differs
        from quickprs.injector import edit_personality
        original_raw = prs.sections[0].raw
        edit_personality(prs, saved_by="TESTER")
        write_prs(prs, out)

        written = out.read_bytes()
        assert written != CLAUDE.read_bytes()
        assert b"TESTER" in written

        # Backup should have the original content
        bak = out.with_suffix(".PRS.bak")
        assert bak.read_bytes() == CLAUDE.read_bytes()

        # Restore
        prs.sections[0].raw = original_raw


def test_refuses_to_write_broken_structure():
    """An edit that leaves a readable personality unreadable is not
    written, and the existing file is left alone."""
    if not CLAUDE.exists():
        pytest.skip("test file not found")
    from quickprs.prs_parser import parse_prs
    from quickprs.prs_writer import UnsafeWriteError
    prs = parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)
        before = out.read_bytes()
        prs.sections[0].raw = b'\xff\xff' + b'\x00' * 10
        with pytest.raises(UnsafeWriteError):
            write_prs(prs, out)
        assert out.read_bytes() == before


def test_write_fixes_stale_tags():
    """write_prs rewrites stale class tags (left by older QuickPRS versions)
    so RPM can open the file."""
    if not PAWS.exists():
        pytest.skip("test file not found")
    import struct
    from quickprs import archive
    from quickprs.prs_parser import parse_prs, parse_prs_bytes
    data = bytearray(PAWS.read_bytes())
    # Corrupt the first CDefaultIdenElem tag the way an old edit would
    _, rep = archive.read_document(bytes(data))
    site = next(t for t in rep.tags if t.class_name == "CDefaultIdenElem")
    struct.pack_into("<H", data, site.offset, 0x8000 | (site.value + 2))
    prs = parse_prs_bytes(bytes(data))
    assert archive.check(prs)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fixed.PRS"
        write_prs(prs, out)
        assert out.read_bytes() == PAWS.read_bytes()
        assert archive.check(parse_prs(out)) == []
