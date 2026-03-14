"""Roundtrip test: Parse → Write → binary diff must be zero.

This is THE GATE — nothing else proceeds until this passes on all test files.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.prs_writer import write_prs

TESTDATA = Path(__file__).parent / "testdata"

TEST_FILES = [
    TESTDATA / "claude test.PRS",
    TESTDATA / "PAWSOVERMAWS.PRS",
]


@pytest.mark.parametrize("filepath", TEST_FILES, ids=lambda p: p.name)
def test_roundtrip(filepath):
    """Parse a .PRS file and write it back. Compare byte-for-byte."""
    if not filepath.exists():
        pytest.skip(f"{filepath} not found")

    original = filepath.read_bytes()
    prs = parse_prs(filepath)
    rebuilt = prs.to_bytes()

    assert len(original) == len(rebuilt), (
        f"Size mismatch: original={len(original)} rebuilt={len(rebuilt)}")
    assert original == rebuilt, "Roundtrip produced different bytes"


@pytest.mark.parametrize("filepath", TEST_FILES, ids=lambda p: p.name)
def test_write_to_file(filepath, tmp_path):
    """Parse, write to temp file, compare temp file with original."""
    if not filepath.exists():
        pytest.skip(f"{filepath} not found")

    original = filepath.read_bytes()
    prs = parse_prs(filepath)

    tmp = tmp_path / filepath.name
    write_prs(prs, tmp, backup=False)
    written = tmp.read_bytes()

    assert original == written, "Written file differs from original"


@pytest.mark.parametrize("filepath", TEST_FILES, ids=lambda p: p.name)
def test_parse_from_bytes(filepath):
    """Parse from raw bytes produces identical output to file parse."""
    if not filepath.exists():
        pytest.skip(f"{filepath} not found")

    original = filepath.read_bytes()
    prs_from_file = parse_prs(filepath)
    prs_from_bytes = parse_prs_bytes(original)

    assert len(prs_from_file.sections) == len(prs_from_bytes.sections)
    assert prs_from_file.to_bytes() == prs_from_bytes.to_bytes()
    assert prs_from_bytes.to_bytes() == original
