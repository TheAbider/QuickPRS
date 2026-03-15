"""Low-level binary read/write helpers for .PRS file format.

PRS binary primitives:
- Frequencies: IEEE 754 double-precision, little-endian (8 bytes)
- Integers: uint16/uint32, little-endian
- Strings: 1-byte length prefix + ASCII (no null terminator)
- Booleans: single byte (0x00=false, 0x01=true)
- Section markers: 0xFF 0xFF
"""

import struct


# --- Readers (return (value, new_offset)) ---

def read_uint8(data, offset):
    return data[offset], offset + 1


def read_uint16_le(data, offset):
    val = struct.unpack_from('<H', data, offset)[0]
    return val, offset + 2


def read_uint32_le(data, offset):
    val = struct.unpack_from('<I', data, offset)[0]
    return val, offset + 4


def read_double_le(data, offset):
    val = struct.unpack_from('<d', data, offset)[0]
    return val, offset + 8


def read_lps(data, offset):
    """Read a length-prefixed string (1-byte length prefix + ASCII)."""
    length = data[offset]
    s = data[offset + 1:offset + 1 + length].decode('ascii', errors='replace')
    return s, offset + 1 + length


def read_bool(data, offset):
    return bool(data[offset]), offset + 1


def read_bytes(data, offset, count):
    return data[offset:offset + count], offset + count


# --- Writers (return bytes) ---

def write_uint8(value):
    return struct.pack('B', value)


def write_uint16_le(value):
    return struct.pack('<H', value)


def write_uint32_le(value):
    return struct.pack('<I', value)


def write_double_le(value):
    return struct.pack('<d', value)


def write_lps(s):
    """Write a length-prefixed string (1-byte length prefix + ASCII).

    Non-ASCII characters are replaced with '?' to avoid crashes.
    Raises ValueError if string exceeds 255 bytes (1-byte length limit).
    """
    encoded = s.encode('ascii', errors='replace')
    if len(encoded) > 255:
        raise ValueError(
            f"LPS string too long ({len(encoded)} bytes, max 255): "
            f"'{s[:20]}...'")
    return struct.pack('B', len(encoded)) + encoded


def write_bool(value):
    return b'\x01' if value else b'\x00'


# --- Section marker ---

SECTION_MARKER = b'\xff\xff'
FILE_TERMINATOR = b'\xff\xff\xff\xff\x00\x01'


def find_all_ffff(data):
    """Find all 0xFFFF marker positions in binary data.

    Returns list of offsets where 0xFF 0xFF appears.
    Skips the second 0xFF in overlapping sequences (0xFFFFFF → one at pos 0, next at pos 2).
    """
    positions = []
    i = 0
    while i < len(data) - 1:
        if data[i] == 0xFF and data[i + 1] == 0xFF:
            positions.append(i)
            i += 2  # skip past this marker
        else:
            i += 1
    return positions


def try_read_class_name(data, offset):
    """At a ffff marker, try to read a class name.

    Format after ffff: BYTE1 BYTE2 uint16_LE(name_len) ClassName

    Returns (class_name, header_size) or (None, 0) if not a class record.
    The header_size includes the ffff marker itself.
    """
    pos = offset + 2  # skip ffff
    if pos + 4 > len(data):
        return None, 0

    # Read 2 mystery bytes + uint16 name length
    name_len = struct.unpack_from('<H', data, pos + 2)[0]

    if name_len < 1 or name_len > 80:
        return None, 0

    name_start = pos + 4
    if name_start + name_len > len(data):
        return None, 0

    try:
        name = data[name_start:name_start + name_len].decode('ascii')
    except UnicodeDecodeError:
        return None, 0

    # Class names start with 'C' and are alphanumeric
    if not name[0] == 'C':
        return None, 0
    if not all(c.isalnum() or c == '_' for c in name):
        return None, 0

    header_size = 2 + 2 + 2 + name_len  # ffff + 2 bytes + uint16 + name
    return name, header_size
