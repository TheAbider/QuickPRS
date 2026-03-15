"""Tests for binary_io.py — low-level binary read/write primitives.

These are the foundation of the entire PRS parser. Every read/write
function must roundtrip correctly, handle edge cases, and match the
binary format exactly.
"""

import struct
import pytest
from pathlib import Path

from quickprs.binary_io import (
    read_uint8, read_uint16_le, read_uint32_le, read_double_le,
    read_lps, read_bool, read_bytes,
    write_uint8, write_uint16_le, write_uint32_le, write_double_le,
    write_lps, write_bool,
    SECTION_MARKER, FILE_TERMINATOR,
    find_all_ffff, try_read_class_name,
)


TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ═══════════════════════════════════════════════════════════════════
# Integer read/write roundtrip
# ═══════════════════════════════════════════════════════════════════


class TestIntegers:

    def test_uint8_roundtrip(self):
        for val in [0, 1, 127, 255]:
            raw = write_uint8(val)
            assert len(raw) == 1
            result, offset = read_uint8(raw, 0)
            assert result == val
            assert offset == 1

    def test_uint16_roundtrip(self):
        for val in [0, 1, 255, 256, 0x08FF, 0xFFFF]:
            raw = write_uint16_le(val)
            assert len(raw) == 2
            result, offset = read_uint16_le(raw, 0)
            assert result == val
            assert offset == 2

    def test_uint16_little_endian(self):
        """0x08FF (TG ID 2303) should be FF 08 in memory."""
        raw = write_uint16_le(0x08FF)
        assert raw == b'\xff\x08'

    def test_uint32_roundtrip(self):
        for val in [0, 1, 65535, 0x003742F5, 0xFFFFFFFF]:
            raw = write_uint32_le(val)
            assert len(raw) == 4
            result, offset = read_uint32_le(raw, 0)
            assert result == val
            assert offset == 4

    def test_uint32_homeunitid(self):
        """HomeUnitID 3621621 should encode as F5 42 37 00."""
        raw = write_uint32_le(3621621)
        assert raw == b'\xf5\x42\x37\x00'

    def test_read_at_offset(self):
        """Readers should work at arbitrary offsets within data."""
        data = b'\x00\x00\xAB\xCD'
        val, off = read_uint16_le(data, 2)
        assert val == 0xCDAB  # little-endian
        assert off == 4


# ═══════════════════════════════════════════════════════════════════
# IEEE 754 double read/write
# ═══════════════════════════════════════════════════════════════════


class TestDoubles:

    def test_double_roundtrip(self):
        for freq in [0.0, 136.0, 462.5625, 806.8875, 851.8875, 870.0]:
            raw = write_double_le(freq)
            assert len(raw) == 8
            result, offset = read_double_le(raw, 0)
            assert abs(result - freq) < 1e-10
            assert offset == 8

    def test_known_frequency_851_88750(self):
        """851.88750 MHz = 9a 99 99 99 19 9f 8a 40 (from binary analysis)."""
        raw = write_double_le(851.88750)
        assert raw == bytes.fromhex("9a999999199f8a40")

    def test_known_frequency_462_56250(self):
        """462.56250 MHz = 00 00 00 00 00 e9 7c 40 (from claude test.PRS)."""
        raw = write_double_le(462.56250)
        assert raw == bytes.fromhex("0000000000e97c40")

    def test_known_frequency_136_0(self):
        """136.0 MHz (TX min) = 00 00 00 00 00 00 61 40."""
        raw = write_double_le(136.0)
        assert raw == bytes.fromhex("00000000000061 40".replace(" ", ""))

    def test_known_frequency_870_0(self):
        """870.0 MHz (TX max) = 00 00 00 00 00 30 8b 40."""
        raw = write_double_le(870.0)
        assert raw == bytes.fromhex("0000000000308b40")


# ═══════════════════════════════════════════════════════════════════
# Length-prefixed string (LPS)
# ═══════════════════════════════════════════════════════════════════


class TestLPS:

    def test_lps_roundtrip(self):
        for s in ["", "A", "PSERN", "PSERN PD", "BEE00", "ALGONA PD TAC 1"]:
            raw = write_lps(s)
            assert raw[0] == len(s)
            result, offset = read_lps(raw, 0)
            assert result == s
            assert offset == 1 + len(s)

    def test_lps_known_encoding(self):
        """'BEE00' encodes as 05 42 45 45 30 30 (from binary analysis)."""
        raw = write_lps("BEE00")
        assert raw == b'\x05\x42\x45\x45\x30\x30'

    def test_lps_empty_string(self):
        raw = write_lps("")
        assert raw == b'\x00'
        result, offset = read_lps(raw, 0)
        assert result == ""
        assert offset == 1

    def test_lps_max_length(self):
        """LPS supports up to 255 characters (1-byte length prefix)."""
        s = "A" * 255
        raw = write_lps(s)
        assert raw[0] == 255
        result, _ = read_lps(raw, 0)
        assert result == s

    def test_lps_at_offset(self):
        """Read LPS at non-zero offset in a larger buffer."""
        prefix = b'\x00\x00\x00'
        lps = write_lps("TEST")
        data = prefix + lps
        result, offset = read_lps(data, 3)
        assert result == "TEST"
        assert offset == 3 + 5  # 3 prefix + 1 len + 4 chars

    def test_lps_8_char_name(self):
        """8-char short names (RPM limit) roundtrip correctly."""
        raw = write_lps("ALG PD 1")
        result, _ = read_lps(raw, 0)
        assert result == "ALG PD 1"
        assert len(result) == 8

    def test_lps_16_char_name(self):
        """16-char long names (RPM limit) roundtrip correctly."""
        raw = write_lps("ALGONA PD TAC 1")
        result, _ = read_lps(raw, 0)
        assert result == "ALGONA PD TAC 1"

    def test_lps_over_255_raises(self):
        """Strings > 255 bytes should raise ValueError."""
        with pytest.raises(ValueError, match="too long"):
            write_lps("A" * 256)

    def test_lps_exactly_255_ok(self):
        """255 bytes is the max — should work fine."""
        s = "B" * 255
        raw = write_lps(s)
        result, _ = read_lps(raw, 0)
        assert result == s

    def test_lps_non_ascii_raises(self):
        """Non-ASCII characters should raise UnicodeEncodeError."""
        with pytest.raises(UnicodeEncodeError):
            write_lps("Système")

    def test_read_lps_truncated_data(self):
        """If length prefix says 10 but only 5 bytes remain, read what's there."""
        # Length prefix says 10, but only 5 bytes of data
        data = b'\x0aHELLO'
        result, offset = read_lps(data, 0)
        # Should read only available bytes (5), not crash
        assert len(result) == 5
        assert offset == 1 + 10  # offset advances by declared length

    def test_read_lps_corrupted_length_zero(self):
        """Zero-length prefix should return empty string."""
        data = b'\x00JUNK'
        result, offset = read_lps(data, 0)
        assert result == ""
        assert offset == 1


# ═══════════════════════════════════════════════════════════════════
# Boolean read/write
# ═══════════════════════════════════════════════════════════════════


class TestBooleans:

    def test_bool_true(self):
        raw = write_bool(True)
        assert raw == b'\x01'
        result, offset = read_bool(raw, 0)
        assert result is True
        assert offset == 1

    def test_bool_false(self):
        raw = write_bool(False)
        assert raw == b'\x00'
        result, offset = read_bool(raw, 0)
        assert result is False
        assert offset == 1


# ═══════════════════════════════════════════════════════════════════
# read_bytes
# ═══════════════════════════════════════════════════════════════════


class TestReadBytes:

    def test_read_bytes_basic(self):
        data = b'\x01\x02\x03\x04\x05'
        result, offset = read_bytes(data, 1, 3)
        assert result == b'\x02\x03\x04'
        assert offset == 4

    def test_read_bytes_zero(self):
        data = b'\xFF\xFF'
        result, offset = read_bytes(data, 0, 0)
        assert result == b''
        assert offset == 0


# ═══════════════════════════════════════════════════════════════════
# Section markers and ffff finder
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestMarkers:

    def test_section_marker_constant(self):
        assert SECTION_MARKER == b'\xff\xff'

    def test_file_terminator_constant(self):
        assert FILE_TERMINATOR == b'\xff\xff\xff\xff\x00\x01'

    def test_find_ffff_simple(self):
        data = b'\x00\xff\xff\x00\x00\xff\xff\x00'
        positions = find_all_ffff(data)
        assert positions == [1, 5]

    def test_find_ffff_at_start(self):
        data = b'\xff\xff\x00\x00'
        positions = find_all_ffff(data)
        assert positions == [0]

    def test_find_ffff_consecutive(self):
        """Overlapping 0xFFFF: ffffff has markers at 0 and 2, not 1."""
        data = b'\xff\xff\xff\xff'
        positions = find_all_ffff(data)
        assert positions == [0, 2]

    def test_find_ffff_none(self):
        data = b'\x00\x01\x02\x03\xff\x00'
        positions = find_all_ffff(data)
        assert positions == []

    def test_find_ffff_empty(self):
        positions = find_all_ffff(b'')
        assert positions == []

    def test_find_ffff_on_real_file(self):
        """PAWSOVERMAWS.PRS should have many ffff markers."""
        paws = TESTDATA / "PAWSOVERMAWS.PRS"
        if not paws.exists():
            pytest.skip("test file not found")
        data = paws.read_bytes()
        positions = find_all_ffff(data)
        assert len(positions) >= 60  # 63 sections


# ═══════════════════════════════════════════════════════════════════
# Class name reader
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestClassNameReader:

    def test_read_cpersonality(self):
        """Parse CPersonality class name from known header bytes."""
        # ffff + 85 00 + 0c 00 (len=12) + 'CPersonality'
        header = b'\xff\xff\x85\x00\x0c\x00CPersonality'
        name, size = try_read_class_name(header, 0)
        assert name == "CPersonality"
        assert size == 2 + 2 + 2 + 12  # ffff + 2 bytes + uint16 + name

    def test_read_cp25trksystem(self):
        """Parse CP25TrkSystem class name."""
        header = b'\xff\xff\x8d\x00\x0d\x00CP25TrkSystem'
        name, size = try_read_class_name(header, 0)
        assert name == "CP25TrkSystem"

    def test_read_cconvsystem(self):
        header = b'\xff\xff\x8d\x00\x0b\x00CConvSystem'
        name, size = try_read_class_name(header, 0)
        assert name == "CConvSystem"

    def test_not_a_class_name(self):
        """Data section (no C prefix) returns None."""
        data = b'\xff\xff\x01\x01\x00\x00\x00\x00\x01\x00'
        name, size = try_read_class_name(data, 0)
        assert name is None
        assert size == 0

    def test_too_short(self):
        data = b'\xff\xff\x00'
        name, size = try_read_class_name(data, 0)
        assert name is None

    def test_invalid_name_length(self):
        """Name length > 80 is rejected."""
        data = b'\xff\xff\x00\x00\x60\x00' + b'C' * 96
        name, size = try_read_class_name(data, 0)
        assert name is None

    def test_read_from_real_file(self):
        """Read class names from actual PAWSOVERMAWS header."""
        paws = TESTDATA / "PAWSOVERMAWS.PRS"
        if not paws.exists():
            pytest.skip("test file not found")
        data = paws.read_bytes()
        # First section should be CPersonality at offset 0
        name, size = try_read_class_name(data, 0)
        assert name == "CPersonality"
        assert size > 0
