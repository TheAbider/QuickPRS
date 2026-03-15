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
    prs = cached_parse_prs(CLAUDE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.PRS"
        write_prs(prs, out)

        # Modify a section to make the output different
        original_raw = prs.sections[0].raw
        prs.sections[0].raw = b'\xff\xff' + b'\x00' * 10
        write_prs(prs, out)

        written = out.read_bytes()
        assert written != CLAUDE.read_bytes()

        # Backup should have the original content
        bak = out.with_suffix(".PRS.bak")
        assert bak.read_bytes() == CLAUDE.read_bytes()

        # Restore
        prs.sections[0].raw = original_raw
