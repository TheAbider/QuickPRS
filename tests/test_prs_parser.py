"""Tests for prs_parser and prs_writer modules."""

import pytest
import tempfile
import shutil
from pathlib import Path

from quickprs.prs_parser import parse_prs, parse_prs_bytes, Section, PRSFile
from quickprs.prs_writer import write_prs


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Section dataclass ──────────────────────────────────────────────

class TestSection:

    def test_section_defaults(self):
        sec = Section(offset=0, raw=b"\xff\xff\x00")
        assert sec.offset == 0
        assert sec.raw == b"\xff\xff\x00"
        assert sec.class_name == ""

    def test_section_with_class_name(self):
        sec = Section(offset=100, raw=b"\xff\xff", class_name="CTest")
        assert sec.class_name == "CTest"
        assert sec.offset == 100


# ─── PRSFile dataclass ──────────────────────────────────────────────

class TestPRSFile:

    def test_empty_prs(self):
        prs = PRSFile()
        assert prs.sections == []
        assert prs.filepath == ""
        assert prs.file_size == 0

    def test_to_bytes_roundtrip(self):
        s1 = Section(offset=0, raw=b"\xff\xffABC")
        s2 = Section(offset=5, raw=b"\xff\xffXYZ")
        prs = PRSFile(sections=[s1, s2], file_size=10)
        assert prs.to_bytes() == b"\xff\xffABC\xff\xffXYZ"

    def test_get_section_by_class(self):
        s1 = Section(offset=0, raw=b"", class_name="CAlpha")
        s2 = Section(offset=10, raw=b"", class_name="CBeta")
        s3 = Section(offset=20, raw=b"", class_name="CAlpha")
        prs = PRSFile(sections=[s1, s2, s3])
        assert prs.get_section_by_class("CAlpha") is s1
        assert prs.get_section_by_class("CBeta") is s2
        assert prs.get_section_by_class("CGamma") is None

    def test_get_sections_by_class(self):
        s1 = Section(offset=0, raw=b"", class_name="CAlpha")
        s2 = Section(offset=10, raw=b"", class_name="CBeta")
        s3 = Section(offset=20, raw=b"", class_name="CAlpha")
        prs = PRSFile(sections=[s1, s2, s3])
        result = prs.get_sections_by_class("CAlpha")
        assert len(result) == 2
        assert result[0] is s1
        assert result[1] is s3

    def test_get_sections_by_class_empty(self):
        prs = PRSFile(sections=[
            Section(offset=0, raw=b"", class_name="CAlpha"),
        ])
        assert prs.get_sections_by_class("CNothing") == []

    def test_summary(self):
        s1 = Section(offset=0, raw=b"\xff\xff\x00\x00", class_name="CTest")
        s2 = Section(offset=4, raw=b"\xff\xff\x00\x00\x00")
        prs = PRSFile(sections=[s1, s2], filepath="test.PRS", file_size=9)
        text = prs.summary()
        assert "test.PRS" in text
        assert "9 bytes" in text
        assert "CTest" in text
        assert "(data)" in text


# ─── parse_prs ──────────────────────────────────────────────────────

class TestParsePrs:

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_parse_claude(self):
        prs = parse_prs(CLAUDE)
        assert prs.file_size == 9652
        assert len(prs.sections) == 26
        assert prs.filepath.endswith("claude test.PRS")

    @pytest.mark.skipif(not PAWS.exists(), reason="Test file not found")
    def test_parse_paws(self):
        prs = parse_prs(PAWS)
        assert prs.file_size == 46822
        assert len(prs.sections) == 63

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_byte_identical_roundtrip(self):
        """Parsing and reassembling should produce identical bytes."""
        original = CLAUDE.read_bytes()
        prs = parse_prs(CLAUDE)
        reassembled = prs.to_bytes()
        assert original == reassembled

    @pytest.mark.skipif(not PAWS.exists(), reason="Test file not found")
    def test_paws_roundtrip(self):
        original = PAWS.read_bytes()
        prs = parse_prs(PAWS)
        assert prs.to_bytes() == original

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_sections_are_contiguous(self):
        """Sections should cover the entire file with no gaps."""
        prs = parse_prs(CLAUDE)
        total = sum(len(s.raw) for s in prs.sections)
        assert total == prs.file_size

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_all_sections_start_with_ffff(self):
        prs = parse_prs(CLAUDE)
        for sec in prs.sections:
            assert sec.raw[:2] == b"\xff\xff", (
                f"Section at {sec.offset} does not start with ffff")

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_named_sections_found(self):
        prs = parse_prs(CLAUDE)
        names = [s.class_name for s in prs.sections if s.class_name]
        assert "CPersonality" in names
        assert "CP25TrkSystem" in names

    def test_parse_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_prs("nonexistent_file_12345.PRS")

    def test_parse_no_markers(self):
        """File with no ffff markers should raise ValueError."""
        with tempfile.NamedTemporaryFile(suffix=".PRS", delete=False) as f:
            f.write(b"\x00" * 100)
            f.flush()
            with pytest.raises(ValueError, match="No ffff markers"):
                parse_prs(f.name)
        Path(f.name).unlink()

    def test_parse_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".PRS", delete=False) as f:
            f.write(b"")
            f.flush()
            with pytest.raises(ValueError, match="No ffff markers"):
                parse_prs(f.name)
        Path(f.name).unlink()


# ─── parse_prs_bytes ────────────────────────────────────────────────

class TestParsePrsBytes:

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_parse_bytes_matches_parse_file(self):
        data = CLAUDE.read_bytes()
        prs_file = parse_prs(CLAUDE)
        prs_bytes = parse_prs_bytes(data)
        assert len(prs_bytes.sections) == len(prs_file.sections)
        assert prs_bytes.file_size == prs_file.file_size
        assert prs_bytes.to_bytes() == prs_file.to_bytes()

    def test_parse_bytes_no_markers(self):
        with pytest.raises(ValueError, match="No ffff markers"):
            parse_prs_bytes(b"\x00" * 50)

    def test_parse_bytes_single_section(self):
        data = b"\xff\xff\x00\x01\x02"
        prs = parse_prs_bytes(data)
        assert len(prs.sections) == 1
        assert prs.sections[0].raw == data
        assert prs.file_size == 5

    def test_parse_bytes_two_sections(self):
        data = b"\xff\xff\xaa\xbb\xff\xff\xcc\xdd"
        prs = parse_prs_bytes(data)
        assert len(prs.sections) == 2
        assert prs.sections[0].raw == b"\xff\xff\xaa\xbb"
        assert prs.sections[1].raw == b"\xff\xff\xcc\xdd"

    def test_parse_bytes_filepath_marker(self):
        prs = parse_prs_bytes(b"\xff\xff\x00")
        assert prs.filepath == "(from bytes)"


# ─── write_prs ──────────────────────────────────────────────────────

class TestWritePrs:

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_write_creates_file(self):
        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "output.PRS"
            size = write_prs(prs, str(out), backup=False)
            assert out.exists()
            assert size == prs.file_size

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_write_byte_identical(self):
        """Written file should be byte-identical to original."""
        original = CLAUDE.read_bytes()
        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "output.PRS"
            write_prs(prs, str(out), backup=False)
            written = out.read_bytes()
            assert written == original

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_write_creates_backup(self):
        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "output.PRS"
            # Write once to create the file
            write_prs(prs, str(out), backup=False)
            # Write again with backup=True
            write_prs(prs, str(out), backup=True)
            bak = Path(tmpdir) / "output.PRS.bak"
            assert bak.exists()
            assert bak.read_bytes() == prs.to_bytes()

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_write_no_backup_when_new(self):
        """No .bak should be created when file doesn't exist."""
        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "new_file.PRS"
            write_prs(prs, str(out), backup=True)
            bak = Path(tmpdir) / "new_file.PRS.bak"
            assert not bak.exists()

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test file not found")
    def test_write_returns_size(self):
        prs = parse_prs(CLAUDE)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "output.PRS"
            size = write_prs(prs, str(out), backup=False)
            assert size == 9652

    @pytest.mark.skipif(not PAWS.exists(), reason="Test file not found")
    def test_full_roundtrip_paws(self):
        """Parse PAWS, write, re-parse, verify identical."""
        prs1 = parse_prs(PAWS)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "roundtrip.PRS"
            write_prs(prs1, str(out), backup=False)
            prs2 = parse_prs(str(out))
            assert len(prs2.sections) == len(prs1.sections)
            for s1, s2 in zip(prs1.sections, prs2.sections):
                assert s1.raw == s2.raw
                assert s1.class_name == s2.class_name
