"""Tests for the hex viewer display formatting.

Since HexViewer is a tkinter widget that requires a display,
these tests verify the data formatting logic without creating GUI.
"""

import pytest


class TestHexViewerDataFormat:
    """Test hex data formatting utilities used by the viewer."""

    def test_hex_dump_format(self):
        """Verify hex dump line format: offset + hex + ASCII."""
        data = bytes(range(32))
        lines = _format_hex_lines(data)

        # First data line should start with offset 00000000
        assert lines[0].startswith("00000000")
        # Should contain hex bytes
        assert "00 01 02 03" in lines[0]
        # Should contain ASCII (dots for non-printable)
        assert lines[0].endswith("................")

    def test_hex_dump_ascii_chars(self):
        """Printable ASCII characters should show in ASCII column."""
        data = b"Hello, World!   "  # 16 bytes
        lines = _format_hex_lines(data)

        assert "Hello, World!" in lines[0]

    def test_hex_dump_partial_line(self):
        """Partial last line (less than 16 bytes) should still format."""
        data = b"\x00\x01\x02"
        lines = _format_hex_lines(data)
        assert len(lines) == 1
        assert lines[0].startswith("00000000")

    def test_hex_dump_empty_data(self):
        """Empty data should produce no lines."""
        lines = _format_hex_lines(b"")
        assert lines == []

    def test_hex_dump_one_byte(self):
        """Single byte should produce one line."""
        lines = _format_hex_lines(b"\xFF")
        assert len(lines) == 1
        assert "FF" in lines[0].upper()

    def test_hex_dump_exactly_16(self):
        """Exactly 16 bytes = one full line."""
        lines = _format_hex_lines(bytes(16))
        assert len(lines) == 1

    def test_hex_dump_17_bytes(self):
        """17 bytes = two lines."""
        lines = _format_hex_lines(bytes(17))
        assert len(lines) == 2

    def test_hex_dump_256_bytes(self):
        """256 bytes = 16 lines."""
        lines = _format_hex_lines(bytes(256))
        assert len(lines) == 16

    def test_search_hex_pattern(self):
        """Search for hex bytes should find offsets."""
        data = b"\x00\x00\xFF\xAB\xCD\x00\x00\xFF\xAB\xCD"
        matches = _search_bytes(data, bytes.fromhex("FFABCD"))
        assert len(matches) == 2
        assert matches[0] == 2
        assert matches[1] == 7

    def test_search_ascii_string(self):
        """Search for ASCII string should find offsets."""
        data = b"\x00\x00Hello\x00\x00Hello\x00"
        matches = _search_bytes(data, b"Hello")
        assert len(matches) == 2
        assert matches[0] == 2
        assert matches[1] == 9

    def test_search_no_match(self):
        """Search with no matches returns empty list."""
        data = b"\x00" * 16
        matches = _search_bytes(data, b"\xFF\xFE")
        assert matches == []

    def test_search_overlapping(self):
        """Search should find overlapping matches."""
        data = b"\xAA\xAA\xAA"
        matches = _search_bytes(data, b"\xAA\xAA")
        assert len(matches) == 2
        assert matches[0] == 0
        assert matches[1] == 1


# ─── Helper functions (standalone, no GUI) ───────────────────────────
# These replicate the hex viewer's formatting logic for testability.


def _format_hex_lines(data):
    """Format data as hex dump lines (offset + hex + ASCII)."""
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        hex_part = hex_part.ljust(48)
        ascii_part = "".join(
            chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part} {ascii_part}")
    return lines


def _search_bytes(data, pattern):
    """Find all occurrences of pattern in data."""
    matches = []
    pos = 0
    while pos <= len(data) - len(pattern):
        idx = data.find(pattern, pos)
        if idx < 0:
            break
        matches.append(idx)
        pos = idx + 1
    return matches
