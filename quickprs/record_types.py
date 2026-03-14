"""Record type definitions for .PRS binary format.

Provides dataclasses with parse/serialize for each record type found in .PRS files.
Unknown fields are preserved as raw bytes for lossless roundtrip.

Hierarchy:
  - Channel/Group/Element sections contain ALL sets packed together
  - Set sections (CTrunkSet, CP25GroupSet, etc.) just hold first-set element count
  - Records are separated by type-specific 2-byte separators
  - Set metadata follows the last record in each set
  - Inter-set gaps: set_name + metadata(16) + marker(2) + count(2) + marker(2)
"""

from dataclasses import dataclass, field
from typing import List, Optional
import struct

from .binary_io import (
    read_uint8, read_uint16_le, read_uint32_le, read_double_le,
    read_lps, read_bytes,
    write_uint8, write_uint16_le, write_uint32_le, write_double_le,
    write_lps,
    SECTION_MARKER,
)


# ─── Separator constants ─────────────────────────────────────────────

TRUNK_CHANNEL_SEP = b'\x6a\x80'
CONV_CHANNEL_SEP = b'\x95\x81'
IDEN_ELEMENT_SEP = b'\x8b\x83'
GROUP_SEP = b'\x91\x82'

# Inter-set gap markers (type-specific first marker, shared second)
TRUNK_SET_MARKER = b'\x68\x80'    # used as: 01 68 80 + count + 6a 80
GROUP_SET_MARKER = b'\x8f\x82'    # used as: 8f 82 + count + 91 82
CONV_SET_MARKER = b'\x93\x81'     # used as: 93 81 + count + 95 81
IDEN_SET_MARKER = b'\x89\x83'     # used as: name + 2meta + 89 83 + count + 8b 83

# Valid second-byte values for inter-record/set markers.
# All observed separators and set markers use 0x80-0x83 as byte2.
_MARKER_BYTE2_VALUES = frozenset({0x80, 0x81, 0x82, 0x83})


def _is_record_marker(data, pos):
    """Check if data[pos:pos+2] looks like a valid record/set marker.

    Valid markers have their second byte in {0x80, 0x81, 0x82, 0x83}.
    Also verifies that the 2 bytes after the uint16 count (at pos+4)
    look like a valid separator, to reduce false positives.
    """
    if pos + 6 > len(data):
        return False
    if data[pos + 1] not in _MARKER_BYTE2_VALUES:
        return False
    # Also verify the separator 2 bytes after the count
    if data[pos + 5] not in _MARKER_BYTE2_VALUES:
        return False
    return True


# Class header byte1 values (record type IDs)
CLASS_IDS = {
    'CTrunkSet': 0x64,
    'CConvSet': 0x65,       # actually CConvSetF in some files
    'CIdenDataSet': 0x66,
    'CP25GroupSet': 0x6a,
    'CTrunkChannel': 0x65,
    'CConvChannel': 0x6a,
    'CP25Group': 0x6a,
    'CDefaultIdenElem': 0x66,
}


# ─── Class header helpers ─────────────────────────────────────────────

def build_class_header(class_name, byte1=None, byte2=0x00):
    """Build ffff + byte1 + byte2 + uint16(name_len) + name."""
    if byte1 is None:
        byte1 = CLASS_IDS.get(class_name, 0x64)
    encoded = class_name.encode('ascii')
    return (SECTION_MARKER +
            struct.pack('B', byte1) +
            struct.pack('B', byte2) +
            struct.pack('<H', len(encoded)) +
            encoded)


def parse_class_header(data, offset):
    """Parse class header, return (class_name, byte1, byte2, data_offset)."""
    pos = offset + 2  # skip ffff
    byte1, pos = read_uint8(data, pos)
    byte2, pos = read_uint8(data, pos)
    name_len, pos = read_uint16_le(data, pos)
    name = data[pos:pos + name_len].decode('ascii')
    return name, byte1, byte2, pos + name_len


# ─── CTrunkChannel ────────────────────────────────────────────────────

@dataclass
class TrunkChannel:
    """Single trunk frequency entry. 23 bytes fixed.

    flags (7 bytes): Per-channel config. Default all zeros = standard P25
    NAS monitoring settings (SiteId=0, BaudRate=9600, Bandwidth=Wide,
    PreAmp=off, UnkeyMsg=off, OscShift=default, NPSPAC=off).
    """
    tx_freq: float          # MHz, IEEE 754 double LE
    rx_freq: float          # MHz, IEEE 754 double LE
    flags: bytes = b'\x00' * 7  # 7 bytes per-channel config

    RECORD_SIZE = 23

    @classmethod
    def parse(cls, data, offset):
        tx, offset = read_double_le(data, offset)
        rx, offset = read_double_le(data, offset)
        flags, offset = read_bytes(data, offset, 7)
        return cls(tx_freq=tx, rx_freq=rx, flags=flags), offset

    def to_bytes(self):
        return (write_double_le(self.tx_freq) +
                write_double_le(self.rx_freq) +
                self.flags)


# ─── Trunk Set (collection of TrunkChannels + metadata) ──────────────

@dataclass
class TrunkSet:
    """One trunk frequency set with name, channels, and band limits.

    gap_bytes: 12-byte inter-set gap following this set's metadata.
        Not always all zeros — byte 7 can be 0x01 for some sets.
        Only meaningful for non-last sets; preserved during roundtrip.
    trailing_bytes: trailing data after the last set in the section.
        Only populated on the last TrunkSet in a parsed list.
        Structure: 12 gap + 01 + 00*5 + 00 + uint16(unknown).
    """
    name: str               # set name (e.g., "PSERN")
    channels: List[TrunkChannel] = field(default_factory=list)
    tx_min: float = 136.0   # band limit doubles (MHz)
    tx_max: float = 870.0
    rx_min: float = 136.0
    rx_max: float = 870.0
    gap_bytes: bytes = b'\x00' * 12     # 12-byte inter-set gap
    trailing_bytes: bytes = b''         # trailing data (last set only)
    separator: bytes = b'\x6a\x80'      # inter-channel separator (file-specific)
    set_marker: bytes = b'\x68\x80'     # inter-set marker (file-specific)

    def channels_to_bytes(self):
        """Serialize channels with inter-channel separators."""
        parts = []
        for i, ch in enumerate(self.channels):
            parts.append(ch.to_bytes())
            if i < len(self.channels) - 1:
                parts.append(self.separator)
        return b''.join(parts)

    def metadata_to_bytes(self):
        """Serialize set name + padding + band limits."""
        return (write_lps(self.name) +
                b'\x00\x00' +  # 2-byte padding
                write_double_le(self.tx_min) +
                write_double_le(self.tx_max) +
                write_double_le(self.rx_min) +
                write_double_le(self.rx_max))


# ─── CConvChannel ────────────────────────────────────────────────────

# Decoded flag byte positions within the 48-byte ConvChannel flags block.
# Bytes not listed here are always 0x00 in observed data.
_CONV_FLAG_OFFSETS = {
    'flag0':          0,   # 1 for MURS/VHF, 0 for UHF — purpose TBD
    'rx':             1,   # receive enable
    'calls':          2,   # call alert enable
    'alert':          3,   # alert tone enable
    'scan_list_member': 4, # scan list membership
    'tone_mode':     22,   # 1 when CTCSS/DCS tones configured on the set
    'narrowband':    27,   # 1=narrowband (12.5kHz), 0=wideband (25kHz)
    'scan':          29,   # scan enable
    'tx':            46,   # transmit enable
}

# Bytes with known non-zero values; all other 48 bytes stay 0x00
_CONV_FLAG_KNOWN = frozenset(_CONV_FLAG_OFFSETS.values())

@dataclass
class ConvChannel:
    """Single conventional channel. Variable length.

    Total size = 89 + len(short_name) + len(tx_tone) + len(rx_tone) + len(long_name)

    The 48-byte flags block is decoded into named boolean fields.
    Unrecognized flag bytes are preserved in _flags_reserved for roundtrip.
    The ``flags`` property reconstructs the 48-byte blob from individual fields
    for backward compatibility.

    pre_long_name (10 bytes): per-channel config block before the long name.
        Byte 1 = power_level (0=low, 1=med, 2=high).
        Byte 2 = squelch_threshold (observed: 0x0C=12).
        Remaining bytes preserved for roundtrip.

    trailer (7 bytes): per-channel config block after the long name.
        Byte 3 = power_level_dup (mirrors pre_long_name byte 1 in observed data).
        Remaining bytes preserved for roundtrip.
    """
    short_name: str         # 8-char max display name
    tx_freq: float          # MHz
    rx_freq: float          # MHz
    tx_tone: str = ""       # CTCSS/DCS tone string (e.g., "250.3", "" for none)
    rx_tone: str = ""
    tx_addr: int = 0        # uint16, tone address code
    rx_addr: int = 0        # uint16

    # Decoded flag fields (from 48-byte flags block)
    flag0: bool = False             # byte 0: 1 for MURS/VHF channels
    rx: bool = True                 # byte 1: receive enable
    calls: bool = True              # byte 2: call alert enable
    alert: bool = True              # byte 3: alert tone enable
    scan_list_member: bool = True   # byte 4: scan list membership
    tone_mode: bool = False         # byte 22: 1 when CTCSS/DCS active
    narrowband: bool = False        # byte 27: 1=12.5kHz, 0=25kHz
    scan: bool = True               # byte 29: scan enable
    tx: bool = True                 # byte 46: transmit enable
    _flags_reserved: bytes = b'\x00' * 48  # full 48 bytes for unrecognized positions

    pre_long_name: bytes = b'\x00\x02\x0c\x00\x00\x00\x00\x00\x01\x01'  # 10 bytes
    long_name: str = ""     # 16-char max long name
    trailer: bytes = b'\x00\x00\x00\x02\x00\x00\x00'  # 7 bytes

    FLAGS_SIZE = 48

    @property
    def flags(self):
        """Reconstruct the 48-byte flags blob from decoded fields + reserved."""
        buf = bytearray(self._flags_reserved)
        for name, offset in _CONV_FLAG_OFFSETS.items():
            buf[offset] = int(getattr(self, name))
        return bytes(buf)

    @flags.setter
    def flags(self, value):
        """Set decoded fields from a 48-byte blob (for backward compat)."""
        if len(value) != 48:
            raise ValueError(f"flags must be 48 bytes, got {len(value)}")
        self._flags_reserved = bytes(value)
        for name, offset in _CONV_FLAG_OFFSETS.items():
            setattr(self, name, bool(value[offset]))

    @property
    def power_level(self):
        """Power level from pre_long_name byte 1 (0=low, 1=med, 2=high)."""
        return self.pre_long_name[1]

    @property
    def squelch_threshold(self):
        """Squelch threshold from pre_long_name byte 2 (observed: 12)."""
        return self.pre_long_name[2]

    @classmethod
    def parse(cls, data, offset):
        short_name, offset = read_lps(data, offset)
        tx_freq, offset = read_double_le(data, offset)
        rx_freq, offset = read_double_le(data, offset)
        tx_tone, offset = read_lps(data, offset)
        rx_tone, offset = read_lps(data, offset)
        tx_addr, offset = read_uint16_le(data, offset)
        rx_addr, offset = read_uint16_le(data, offset)
        flags_raw, offset = read_bytes(data, offset, 48)
        pre_long_name, offset = read_bytes(data, offset, 10)
        long_name, offset = read_lps(data, offset)
        trailer, offset = read_bytes(data, offset, 7)

        # Decode named flags from raw bytes
        obj = cls(
            short_name=short_name, tx_freq=tx_freq, rx_freq=rx_freq,
            tx_tone=tx_tone, rx_tone=rx_tone, tx_addr=tx_addr, rx_addr=rx_addr,
            pre_long_name=pre_long_name, long_name=long_name,
            trailer=trailer,
            _flags_reserved=flags_raw,
        )
        for name, off in _CONV_FLAG_OFFSETS.items():
            setattr(obj, name, bool(flags_raw[off]))
        return obj, offset

    def to_bytes(self):
        return (write_lps(self.short_name) +
                write_double_le(self.tx_freq) +
                write_double_le(self.rx_freq) +
                write_lps(self.tx_tone) +
                write_lps(self.rx_tone) +
                write_uint16_le(self.tx_addr) +
                write_uint16_le(self.rx_addr) +
                self.flags +
                self.pre_long_name +
                write_lps(self.long_name) +
                self.trailer)

    def byte_size(self):
        return (89 + len(self.short_name) + len(self.tx_tone) +
                len(self.rx_tone) + len(self.long_name))


# ─── Conv Set (collection of ConvChannels) ────────────────────────────

@dataclass
class ConvSet:
    """One conventional channel set with name and channels.

    The 60-byte metadata block is decoded into named fields:
      byte 0:     config_flag (always 0x01)
      byte 1:     has_band_limits (0x01 = band limit doubles populated)
      bytes 2-33: four IEEE 754 doubles — band limits in MHz
                  (tx_min, rx_min, tx_max, rx_max when has_band_limits=True, else 0.0)
      bytes 34-37: reserved (zeros)
      bytes 38-39: config pair (both 0x01 in all observed data)
      bytes 40-59: reserved (zeros)

    The ``metadata`` property reconstructs the 60-byte blob for backward compat.
    """
    name: str
    channels: List[ConvChannel] = field(default_factory=list)
    # Decoded metadata fields
    config_flag: int = 0x01         # byte 0 (always 0x01)
    has_band_limits: int = 0x00     # byte 1 (0x01 = band limits present)
    tx_min: float = 0.0             # bytes 2-9 (MHz, 0.0 if no limits)
    rx_min: float = 0.0             # bytes 10-17
    tx_max: float = 0.0             # bytes 18-25
    rx_max: float = 0.0             # bytes 26-33
    _metadata_reserved: bytes = (b'\x00' * 38 + b'\x01\x01' +
                                 b'\x00' * 20)  # 60 bytes; [38:40]=0x01,0x01 per RPM
    separator: bytes = b'\x95\x81'      # inter-channel separator (file-specific)
    set_marker: bytes = b'\x93\x81'     # inter-set marker (file-specific)
    trailing_uint16: int = 0            # trailing 2 bytes at end of section (last set only)

    METADATA_SIZE = 60

    @property
    def metadata(self):
        """Reconstruct 60-byte metadata blob from decoded fields + reserved."""
        buf = bytearray(self._metadata_reserved)
        buf[0] = self.config_flag
        buf[1] = self.has_band_limits
        struct.pack_into('<d', buf, 2, self.tx_min)
        struct.pack_into('<d', buf, 10, self.rx_min)
        struct.pack_into('<d', buf, 18, self.tx_max)
        struct.pack_into('<d', buf, 26, self.rx_max)
        return bytes(buf)

    @metadata.setter
    def metadata(self, value):
        """Set decoded fields from a 60-byte blob (for backward compat)."""
        if len(value) != 60:
            raise ValueError(f"metadata must be 60 bytes, got {len(value)}")
        self._metadata_reserved = bytes(value)
        self.config_flag = value[0]
        self.has_band_limits = value[1]
        self.tx_min = struct.unpack_from('<d', value, 2)[0]
        self.rx_min = struct.unpack_from('<d', value, 10)[0]
        self.tx_max = struct.unpack_from('<d', value, 18)[0]
        self.rx_max = struct.unpack_from('<d', value, 26)[0]

    def channels_to_bytes(self):
        """Serialize channels with inter-channel separators."""
        parts = []
        for i, ch in enumerate(self.channels):
            parts.append(ch.to_bytes())
            if i < len(self.channels) - 1:
                parts.append(self.separator)
        return b''.join(parts)

    def metadata_to_bytes(self):
        """Serialize set name + metadata."""
        return write_lps(self.name) + self.metadata


# ─── CP25ConvChannel ─────────────────────────────────────────────────

# Separator and set markers for P25 conventional channels
P25_CONV_CHANNEL_SEP = b'\xbc\x81'
P25_CONV_SET_MARKER = b'\xba\x81'

# Decoded flag byte positions within the 22-byte P25ConvChannel flags block.
_P25_CONV_FLAG_OFFSETS = {
    'flag0':             0,   # purpose TBD (always 0 observed)
    'rx':                1,   # receive enable
    'calls':             2,   # call alert enable
    'alert':             3,   # alert tone enable
    'scan_list_member':  4,   # scan list membership
    'scan_byte6':        6,   # possibly related to scan
    'tone_mode':        10,   # CTCSS/DCS tones configured
    'narrowband':       11,   # 1=12.5kHz, 0=25kHz
    'scan':             13,   # scan enable
    'backlight':        14,   # backlight enable
    'tx_enable':        19,   # transmit enable
    'tx':               21,   # transmit enable (dup?)
}

_P25_CONV_FLAG_KNOWN = frozenset(_P25_CONV_FLAG_OFFSETS.values())


@dataclass
class P25ConvChannel:
    """Single P25 conventional channel. Variable length.

    Similar to CConvChannel but with a shorter 22-byte flags block,
    no pre_long_name block, a 20-byte trailer, and NAC (Network Access
    Code) fields instead of analog tone addresses.

    Binary layout:
      LPS(short_name) + tx_freq(8) + rx_freq(8) + LPS(tx_tone) + LPS(rx_tone)
      + uint16(tx_addr) + uint16(rx_addr) + uint16(nac_tx) + uint16(nac_rx)
      + flags(22) + LPS(long_name) + trailer(20)
    """
    short_name: str          # 8-char max display name
    tx_freq: float           # MHz, IEEE 754 double LE
    rx_freq: float           # MHz
    tx_tone: str = ""        # CTCSS/DCS tone string (usually empty for P25)
    rx_tone: str = ""
    tx_addr: int = 0         # uint16
    rx_addr: int = 0         # uint16
    nac_tx: int = 0          # uint16, P25 Network Access Code (TX)
    nac_rx: int = 0          # uint16, P25 Network Access Code (RX)

    # Decoded flag fields (from 22-byte flags block)
    flag0: bool = False
    rx: bool = True
    calls: bool = True
    alert: bool = True
    scan_list_member: bool = True
    scan_byte6: bool = True
    tone_mode: bool = False
    narrowband: bool = False
    scan: bool = True
    backlight: bool = True
    tx_enable: bool = True
    tx: bool = True
    _flags_reserved: bytes = b'\x00' * 22  # full 22 bytes for unrecognized positions

    long_name: str = ""      # 16-char max long name
    trailer: bytes = b'\x00' * 20  # 20 bytes per-channel trailing config

    FLAGS_SIZE = 22
    TRAILER_SIZE = 20

    @property
    def flags(self):
        """Reconstruct the 22-byte flags blob from decoded fields + reserved."""
        buf = bytearray(self._flags_reserved)
        for name, offset in _P25_CONV_FLAG_OFFSETS.items():
            buf[offset] = int(getattr(self, name))
        return bytes(buf)

    @flags.setter
    def flags(self, value):
        """Set decoded fields from a 22-byte blob."""
        if len(value) != 22:
            raise ValueError(f"flags must be 22 bytes, got {len(value)}")
        self._flags_reserved = bytes(value)
        for name, offset in _P25_CONV_FLAG_OFFSETS.items():
            setattr(self, name, bool(value[offset]))

    @classmethod
    def parse(cls, data, offset):
        short_name, offset = read_lps(data, offset)
        tx_freq, offset = read_double_le(data, offset)
        rx_freq, offset = read_double_le(data, offset)
        tx_tone, offset = read_lps(data, offset)
        rx_tone, offset = read_lps(data, offset)
        tx_addr, offset = read_uint16_le(data, offset)
        rx_addr, offset = read_uint16_le(data, offset)
        nac_tx, offset = read_uint16_le(data, offset)
        nac_rx, offset = read_uint16_le(data, offset)
        flags_raw, offset = read_bytes(data, offset, cls.FLAGS_SIZE)
        long_name, offset = read_lps(data, offset)
        trailer, offset = read_bytes(data, offset, cls.TRAILER_SIZE)

        obj = cls(
            short_name=short_name, tx_freq=tx_freq, rx_freq=rx_freq,
            tx_tone=tx_tone, rx_tone=rx_tone,
            tx_addr=tx_addr, rx_addr=rx_addr,
            nac_tx=nac_tx, nac_rx=nac_rx,
            long_name=long_name, trailer=trailer,
            _flags_reserved=flags_raw,
        )
        for name, off in _P25_CONV_FLAG_OFFSETS.items():
            setattr(obj, name, bool(flags_raw[off]))
        return obj, offset

    def to_bytes(self):
        return (write_lps(self.short_name) +
                write_double_le(self.tx_freq) +
                write_double_le(self.rx_freq) +
                write_lps(self.tx_tone) +
                write_lps(self.rx_tone) +
                write_uint16_le(self.tx_addr) +
                write_uint16_le(self.rx_addr) +
                write_uint16_le(self.nac_tx) +
                write_uint16_le(self.nac_rx) +
                self.flags +
                write_lps(self.long_name) +
                self.trailer)


# ─── P25 Conv Set (collection of P25ConvChannels + metadata) ────────

@dataclass
class P25ConvSet:
    """One P25 conventional channel set with name, channels, and band limits.

    Set metadata layout:
      LPS(set_name) + uint8(scan_list_size) + uint8(0) + tx_min(8) + rx_min(8)
      + tx_max(8) + rx_max(8) + LPS(group_set_ref) + trailing(17 bytes)

    Total metadata: 4 (LPS) + 2 (config) + 32 (4 doubles) + 9 (LPS) + 17 (trail)
    """
    name: str
    channels: List[P25ConvChannel] = field(default_factory=list)
    scan_list_size: int = 8           # byte after set name (like P25GroupSet)
    config_byte2: int = 0             # second config byte (always 0 observed)
    tx_min: float = 136.0             # band limits (MHz)
    rx_min: float = 136.0
    tx_max: float = 870.0
    rx_max: float = 870.0
    group_set_ref: str = ""           # reference to CP25GroupSet or group name
    trailing: bytes = (b'\x00' * 15 + b'\x01\x00')  # 17-byte set trailing
    separator: bytes = P25_CONV_CHANNEL_SEP   # inter-channel separator
    set_marker: bytes = P25_CONV_SET_MARKER   # inter-set marker

    def channels_to_bytes(self):
        """Serialize channels with inter-channel separators."""
        parts = []
        for i, ch in enumerate(self.channels):
            parts.append(ch.to_bytes())
            if i < len(self.channels) - 1:
                parts.append(self.separator)
        return b''.join(parts)

    def metadata_to_bytes(self):
        """Serialize set name + config + band limits + group ref + trailing."""
        return (write_lps(self.name) +
                write_uint8(self.scan_list_size) +
                write_uint8(self.config_byte2) +
                write_double_le(self.tx_min) +
                write_double_le(self.rx_min) +
                write_double_le(self.tx_max) +
                write_double_le(self.rx_max) +
                write_lps(self.group_set_ref) +
                self.trailing)


def parse_p25_conv_channel_section(data, offset, end, first_count):
    """Parse CP25ConvChannel section into list of P25ConvSets.

    Args:
        data: full file bytes or section raw bytes
        offset: start of channel data (after class header)
        end: end of section
        first_count: number of channels in first set (from CP25ConvSet section)

    Returns:
        list of P25ConvSet objects
    """
    sets = []
    pos = offset
    remaining_count = first_count
    observed_sep = None
    observed_set_marker = None

    while pos < end - 10 and remaining_count > 0:
        channels = []
        for i in range(remaining_count):
            ch, pos = P25ConvChannel.parse(data, pos)
            channels.append(ch)
            if i < remaining_count - 1:
                sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = sep
                pos += 2

        # After last channel: set metadata
        set_name, pos = read_lps(data, pos)
        scan_list_size, pos = read_uint8(data, pos)
        config_byte2, pos = read_uint8(data, pos)
        tx_min, pos = read_double_le(data, pos)
        rx_min, pos = read_double_le(data, pos)
        tx_max, pos = read_double_le(data, pos)
        rx_max, pos = read_double_le(data, pos)
        group_ref, pos = read_lps(data, pos)
        trailing, pos = read_bytes(data, pos, 17)

        cset = P25ConvSet(
            name=set_name, channels=channels,
            scan_list_size=scan_list_size, config_byte2=config_byte2,
            tx_min=tx_min, rx_min=rx_min, tx_max=tx_max, rx_max=rx_max,
            group_set_ref=group_ref, trailing=trailing,
        )
        sets.append(cset)

        # Inter-set gap: set_marker(2) + uint16(count) + separator(2)
        if pos < end - 6 and _is_record_marker(data, pos):
            sm = bytes(data[pos:pos + 2])
            if observed_set_marker is None:
                observed_set_marker = sm
            pos += 2
            remaining_count, pos = read_uint16_le(data, pos)
            ch_sep = bytes(data[pos:pos + 2])
            if observed_sep is None:
                observed_sep = ch_sep
            pos += 2
        else:
            remaining_count = 0

    # Propagate observed separators to all sets
    if observed_sep:
        for s in sets:
            s.separator = observed_sep
    if observed_set_marker:
        for s in sets:
            s.set_marker = observed_set_marker

    return sets


def build_p25_conv_channel_section(sets, byte1=0x71, byte2=0x00):
    """Build CP25ConvChannel section bytes from list of P25ConvSets."""
    header = build_class_header('CP25ConvChannel', byte1, byte2)
    parts = [header]

    set_marker = sets[0].set_marker if sets else P25_CONV_SET_MARKER
    sep = sets[0].separator if sets else P25_CONV_CHANNEL_SEP

    for i, cset in enumerate(sets):
        parts.append(cset.channels_to_bytes())
        parts.append(cset.metadata_to_bytes())
        if i < len(sets) - 1:
            next_count = len(sets[i + 1].channels)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)

    return b''.join(parts)


def build_p25_conv_set_section(first_count, byte1=0x66, byte2=0x00):
    """Build CP25ConvSet section bytes (header + first set count)."""
    header = build_class_header('CP25ConvSet', byte1, byte2)
    return header + write_uint16_le(first_count)


# ─── CDefaultIdenElem ────────────────────────────────────────────────

@dataclass
class IdenElement:
    """P25 channel identifier element. 15 bytes fixed.

    Defines how logical channel numbers map to RF frequencies.
    tx_offset is stored as raw uint32 (preserves bytes for roundtrip)
    but is actually an IEEE 754 float32 LE representing MHz offset.
    Use tx_offset_mhz property for the human-readable value.
    """
    chan_spacing_hz: int = 12500    # uint32, channel spacing in Hz
    bandwidth_hz: int = 6250       # uint16, bandwidth in Hz
    base_freq_hz: int = 0          # uint32, base frequency in Hz
    tx_offset: int = 0             # raw uint32 (actually float32 LE bytes for MHz)
    iden_type: int = 0             # byte: 0=FDMA, 1=TDMA

    RECORD_SIZE = 15

    @classmethod
    def parse(cls, data, offset):
        spacing, offset = read_uint32_le(data, offset)
        bw, offset = read_uint16_le(data, offset)
        base, offset = read_uint32_le(data, offset)
        tx_off, offset = read_uint32_le(data, offset)
        itype, offset = read_uint8(data, offset)
        return cls(
            chan_spacing_hz=spacing, bandwidth_hz=bw, base_freq_hz=base,
            tx_offset=tx_off, iden_type=itype,
        ), offset

    def to_bytes(self):
        # tx_offset may be negative (e.g. -45 MHz for 800 band); convert to uint32
        tx_off = self.tx_offset & 0xFFFFFFFF
        return (write_uint32_le(self.chan_spacing_hz) +
                write_uint16_le(self.bandwidth_hz) +
                write_uint32_le(self.base_freq_hz) +
                write_uint32_le(tx_off) +
                write_uint8(self.iden_type))

    @property
    def tx_offset_mhz(self):
        """Interpret tx_offset as float32 LE (MHz). E.g. -45.0, +30.0."""
        raw = struct.pack('<I', self.tx_offset & 0xFFFFFFFF)
        return struct.unpack('<f', raw)[0]

    @tx_offset_mhz.setter
    def tx_offset_mhz(self, mhz):
        """Set tx_offset from a float MHz value."""
        raw = struct.pack('<f', mhz)
        self.tx_offset = struct.unpack('<I', raw)[0]

    def is_empty(self):
        return self.base_freq_hz == 0


# ─── IDEN Data Set (collection of IdenElements) ──────────────────────

@dataclass
class IdenDataSet:
    """One IDEN set (e.g., BEE00). Always 16 element slots."""
    name: str
    elements: List[IdenElement] = field(default_factory=list)
    metadata: bytes = b'\x0c\x00'  # 2 bytes after name (observed as 0c 00)
    separator: bytes = b'\x8b\x83'      # inter-element separator (file-specific)
    set_marker: bytes = b'\x89\x83'     # inter-set marker (file-specific)

    SLOTS = 16  # fixed number of element slots per set
    METADATA_SIZE = 2

    def elements_to_bytes(self):
        """Serialize elements with inter-element separators."""
        parts = []
        elems = self.elements[:]
        # Pad to 16 slots with empty elements
        while len(elems) < self.SLOTS:
            elems.append(IdenElement())
        for i, elem in enumerate(elems[:self.SLOTS]):
            parts.append(elem.to_bytes())
            if i < self.SLOTS - 1:
                parts.append(self.separator)
        return b''.join(parts)


# ─── CP25Group ────────────────────────────────────────────────────────

@dataclass
class P25Group:
    """Single P25 talkgroup record.

    Binary layout:
      GroupName(LPS) + GroupID(uint16) + middle(12) + bools(7) + LongName(LPS) + tail(4)

    Middle block (12 bytes) decoded fields:
      bytes 0-1: audio_file (uint16 LE, 0 = none)
      byte 2:    audio_profile (0x08 = default)
      bytes 3-4: index (uint16 LE, 0 = none)
      bytes 5-8: key_id (uint32 LE, encryption key, 0 = none)
      bytes 9-10: reserved (zeros)
      byte 11:   priority_tg (0 or 1, priority talkgroup flag)

    The 7-byte boolean block: RX, Calls, Alert, ScanListMember,
    Scan, BackLight, TX (TX=last byte, 0=no transmit).

    Tail block (4 bytes) decoded fields:
      byte 0: use_group_id (bool, use talkgroup ID for selection)
      byte 1: encrypted (bool, encryption required)
      byte 2: tg_type (0=standard, other values TBD)
      byte 3: suppress (bool, suppress from display)

    The ``middle`` and ``tail`` properties reconstruct the raw bytes
    from decoded fields for backward compat.
    """
    group_name: str         # 8-char short name
    group_id: int           # uint16 talkgroup ID (decimal)
    long_name: str = ""     # 16-char long name

    # Boolean flags (individual fields for the ones we care about)
    rx: bool = True
    calls: bool = True
    alert: bool = True
    scan_list_member: bool = True
    scan: bool = True
    backlight: bool = True
    tx: bool = False        # False = receive-only (NAS monitoring default)

    # Decoded middle block fields
    audio_file: int = 0         # uint16 LE (0=none)
    audio_profile: int = 0x08   # byte 2 (0x08=default profile)
    tg_index: int = 0           # uint16 LE (0=none)
    key_id: int = 0             # uint32 LE (0=no encryption key)
    _middle_reserved_9_10: bytes = b'\x00\x00'  # bytes 9-10
    priority_tg: bool = False   # byte 11 (priority talkgroup flag)

    # Decoded tail block fields
    use_group_id: bool = False  # byte 0
    encrypted: bool = False     # byte 1
    tg_type: int = 0            # byte 2 (0=standard)
    suppress: bool = False      # byte 3

    MIDDLE_SIZE = 12
    BOOLS_SIZE = 7
    TAIL_SIZE = 4

    @property
    def middle(self):
        """Reconstruct 12-byte middle block from decoded fields."""
        return (struct.pack('<H', self.audio_file) +
                struct.pack('B', self.audio_profile) +
                struct.pack('<H', self.tg_index) +
                struct.pack('<I', self.key_id) +
                self._middle_reserved_9_10 +
                struct.pack('B', int(self.priority_tg)))

    @middle.setter
    def middle(self, value):
        """Set decoded fields from a 12-byte blob (for backward compat)."""
        if len(value) != 12:
            raise ValueError(f"middle must be 12 bytes, got {len(value)}")
        self.audio_file = struct.unpack_from('<H', value, 0)[0]
        self.audio_profile = value[2]
        self.tg_index = struct.unpack_from('<H', value, 3)[0]
        self.key_id = struct.unpack_from('<I', value, 5)[0]
        self._middle_reserved_9_10 = bytes(value[9:11])
        self.priority_tg = bool(value[11])

    @property
    def tail(self):
        """Reconstruct 4-byte tail block from decoded fields."""
        return bytes([int(self.use_group_id), int(self.encrypted),
                      self.tg_type, int(self.suppress)])

    @tail.setter
    def tail(self, value):
        """Set decoded fields from a 4-byte blob (for backward compat)."""
        if len(value) != 4:
            raise ValueError(f"tail must be 4 bytes, got {len(value)}")
        self.use_group_id = bool(value[0])
        self.encrypted = bool(value[1])
        self.tg_type = value[2]
        self.suppress = bool(value[3])

    @classmethod
    def parse(cls, data, offset):
        group_name, offset = read_lps(data, offset)
        group_id, offset = read_uint16_le(data, offset)
        middle_raw, offset = read_bytes(data, offset, cls.MIDDLE_SIZE)
        bools, offset = read_bytes(data, offset, cls.BOOLS_SIZE)
        long_name, offset = read_lps(data, offset)
        tail_raw, offset = read_bytes(data, offset, cls.TAIL_SIZE)

        obj = cls(
            group_name=group_name, group_id=group_id, long_name=long_name,
            rx=bool(bools[0]), calls=bool(bools[1]), alert=bool(bools[2]),
            scan_list_member=bool(bools[3]), scan=bool(bools[4]),
            backlight=bool(bools[5]), tx=bool(bools[6]),
        )
        # Decode middle and tail via property setters
        obj.middle = middle_raw
        obj.tail = tail_raw
        return obj, offset

    def to_bytes(self):
        bools = bytes([
            int(self.rx), int(self.calls), int(self.alert),
            int(self.scan_list_member), int(self.scan), int(self.backlight),
            int(self.tx),
        ])
        return (write_lps(self.group_name) +
                write_uint16_le(self.group_id) +
                self.middle +
                bools +
                write_lps(self.long_name) +
                self.tail)

    def byte_size(self):
        return (1 + len(self.group_name) + 2 + self.MIDDLE_SIZE +
                self.BOOLS_SIZE + 1 + len(self.long_name) + self.TAIL_SIZE)


# ─── P25 Group Set (collection of P25Groups + metadata) ──────────────

@dataclass
class P25GroupSet:
    """One talkgroup set (e.g., PSERN PD).

    Metadata (16 bytes) decoded fields:
      byte 0:    scan_list_size (0x09 = 9, max scan list capacity)
      bytes 1-4: reserved (zeros)
      bytes 5-6: system_id (uint16 LE, P25 System ID, 0 if unlinked)
      bytes 7-15: reserved (zeros)

    The ``metadata`` property reconstructs the 16-byte blob.

    trailing_bytes: trailing data after the last set in the section.
        Only populated on the last P25GroupSet in a parsed list.
    """
    name: str
    groups: List[P25Group] = field(default_factory=list)
    # Decoded metadata fields
    scan_list_size: int = 0x09      # byte 0 (scan list capacity)
    system_id: int = 0              # bytes 5-6, uint16 LE (P25 System ID)
    _gset_meta_reserved: bytes = (b'\x09\x00\x00\x00\x00'
                                  b'\x00\x00\x00\x00\x00'
                                  b'\x00\x00\x00\x00\x00\x00')  # full 16 bytes
    trailing_bytes: bytes = b''         # trailing data (last set only)
    separator: bytes = b'\x91\x82'      # inter-group separator (file-specific)
    set_marker: bytes = b'\x8f\x82'     # inter-set marker (file-specific)

    METADATA_SIZE = 16

    @property
    def metadata(self):
        """Reconstruct 16-byte metadata blob from decoded fields + reserved."""
        buf = bytearray(self._gset_meta_reserved)
        buf[0] = self.scan_list_size
        struct.pack_into('<H', buf, 5, self.system_id)
        return bytes(buf)

    @metadata.setter
    def metadata(self, value):
        """Set decoded fields from a 16-byte blob (for backward compat)."""
        if len(value) != 16:
            raise ValueError(f"metadata must be 16 bytes, got {len(value)}")
        self._gset_meta_reserved = bytes(value)
        self.scan_list_size = value[0]
        self.system_id = struct.unpack_from('<H', value, 5)[0]

    def groups_to_bytes(self):
        """Serialize groups with inter-group separators."""
        parts = []
        for i, grp in enumerate(self.groups):
            parts.append(grp.to_bytes())
            if i < len(self.groups) - 1:
                parts.append(self.separator)
        return b''.join(parts)

    def metadata_to_bytes(self):
        """Serialize set name + metadata."""
        return write_lps(self.name) + self.metadata


# ─── Section-level parsers ────────────────────────────────────────────
#
# These parse the packed data within a single ffff-delimited section
# that contains ALL sets of a given type (e.g., all trunk sets).
# The first set's element count comes from the companion Set section.

def parse_trunk_channel_section(data, offset, end, first_count):
    """Parse CTrunkChannel section into list of TrunkSets.

    Args:
        data: full file bytes
        offset: start of channel data (after class header)
        end: end of section
        first_count: number of channels in first set (from CTrunkSet section)

    Returns:
        list of TrunkSet objects.  The last set's .trailing_bytes holds
        everything after its metadata to end-of-section. Intermediate
        sets store their 12-byte inter-set gap in .gap_bytes.
    """
    sets = []
    pos = offset
    remaining_count = first_count
    observed_sep = None
    observed_set_marker = None

    while pos < end and remaining_count > 0:
        channels = []
        for i in range(remaining_count):
            ch, pos = TrunkChannel.parse(data, pos)
            channels.append(ch)
            if i < remaining_count - 1:
                # Read and store the inter-channel separator
                sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = sep
                pos += 2

        # After last channel: set metadata
        set_name, pos = read_lps(data, pos)
        # 2 padding bytes
        pos += 2
        tx_min, pos = read_double_le(data, pos)
        tx_max, pos = read_double_le(data, pos)
        rx_min, pos = read_double_le(data, pos)
        rx_max, pos = read_double_le(data, pos)

        tset = TrunkSet(
            name=set_name, channels=channels,
            tx_min=tx_min, tx_max=tx_max, rx_min=rx_min, rx_max=rx_max,
        )
        sets.append(tset)

        # Inter-set gap: 12 bytes + 01 + set_marker(2) + count(2) + separator(2)
        # OR trailing:   remaining bytes to end of section
        if pos < end - 10:
            # Read the 12-byte inter-set gap
            gap, pos = read_bytes(data, pos, 12)
            # 01 byte
            marker_byte, pos = read_uint8(data, pos)
            # Check if this is a real inter-set boundary by verifying
            # both the set marker and separator have valid byte2 patterns
            if marker_byte == 0x01 and _is_record_marker(data, pos):
                # Read set marker (2 bytes)
                sm = bytes(data[pos:pos + 2])
                if observed_set_marker is None:
                    observed_set_marker = sm
                # Inter-set boundary — save gap bytes, advance past markers
                tset.gap_bytes = gap
                pos += 2  # skip set marker
                remaining_count, pos = read_uint16_le(data, pos)
                # Read channel separator after count
                ch_sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = ch_sep
                pos += 2  # skip channel separator
            else:
                # Last set — put back and capture everything as trailing
                pos -= 13  # un-read gap(12) + marker(1)
                tset.trailing_bytes = bytes(data[pos:end])
                remaining_count = 0
        else:
            # Capture any leftover bytes as trailing on the last set
            tset.trailing_bytes = bytes(data[pos:end])
            remaining_count = 0

    # Propagate observed separators to all sets
    if observed_sep:
        for s in sets:
            s.separator = observed_sep
    if observed_set_marker:
        for s in sets:
            s.set_marker = observed_set_marker

    return sets


def parse_conv_channel_section(data, offset, end, first_count):
    """Parse CConvChannel section into list of ConvSets.

    Args:
        data: full file bytes or section raw bytes
        offset: start of channel data (after class header)
        end: end of section
        first_count: number of channels in first set (from CConvSet section)

    Returns:
        list of ConvSet objects
    """
    sets = []
    pos = offset
    remaining_count = first_count
    observed_sep = None
    observed_set_marker = None

    while pos < end - 10 and remaining_count > 0:
        channels = []
        for i in range(remaining_count):
            ch, pos = ConvChannel.parse(data, pos)
            channels.append(ch)
            if i < remaining_count - 1:
                # Read and store the inter-channel separator
                sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = sep
                pos += 2

        # After last channel: set name (LPS) + 60 bytes metadata
        set_name, pos = read_lps(data, pos)
        meta, pos = read_bytes(data, pos, ConvSet.METADATA_SIZE)

        cset = ConvSet(name=set_name, channels=channels)
        cset.metadata = meta
        sets.append(cset)

        # Inter-set gap: set_marker(2) + uint16(count) + separator(2)
        # Detect by checking both marker and separator have valid byte2
        if pos < end - 6 and _is_record_marker(data, pos):
            sm = bytes(data[pos:pos + 2])
            if observed_set_marker is None:
                observed_set_marker = sm
            pos += 2  # skip set marker
            remaining_count, pos = read_uint16_le(data, pos)
            # Read channel separator after count
            ch_sep = bytes(data[pos:pos + 2])
            if observed_sep is None:
                observed_sep = ch_sep
            pos += 2  # skip channel separator
        else:
            remaining_count = 0

    # Read trailing uint16 (last 2 bytes of section)
    trailing_val = 0
    if pos + 2 <= end:
        trailing_val, _ = read_uint16_le(data, pos)

    # Propagate observed separators to all sets; store trailing on last set
    if observed_sep:
        for s in sets:
            s.separator = observed_sep
    if observed_set_marker:
        for s in sets:
            s.set_marker = observed_set_marker
    if sets:
        sets[-1].trailing_uint16 = trailing_val

    return sets


def parse_group_section(data, offset, end, first_count):
    """Parse CP25Group section into list of P25GroupSets.

    Args:
        data: full file bytes
        offset: start of group data (after class header)
        end: end of section
        first_count: number of groups in first set (from CP25GroupSet section)

    Returns:
        list of P25GroupSet objects.  The last set's .trailing_bytes
        holds everything after its metadata to end-of-section.
    """
    sets = []
    pos = offset
    remaining_count = first_count
    observed_sep = None
    observed_set_marker = None

    while pos < end - 4 and remaining_count > 0:
        groups = []
        for i in range(remaining_count):
            grp, pos = P25Group.parse(data, pos)
            groups.append(grp)
            if i < remaining_count - 1:
                # Read and store the inter-group separator
                sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = sep
                pos += 2

        # After last group: set metadata (name + 16 bytes)
        set_name, pos = read_lps(data, pos)
        meta, pos = read_bytes(data, pos, P25GroupSet.METADATA_SIZE)

        gset = P25GroupSet(name=set_name, groups=groups)
        gset.metadata = meta
        sets.append(gset)

        # Inter-set gap: set_marker(2) + count(2) + separator(2)
        # Detect by checking both marker and separator have valid byte2
        if pos < end - 6 and _is_record_marker(data, pos):
            marker1 = bytes(data[pos:pos + 2])
            if observed_set_marker is None:
                observed_set_marker = marker1
            pos += 2  # skip set marker
            remaining_count, pos = read_uint16_le(data, pos)
            # Read group separator after count
            grp_sep = bytes(data[pos:pos + 2])
            if observed_sep is None:
                observed_sep = grp_sep
            pos += 2  # skip group separator
        else:
            # Last set — capture trailing bytes
            gset.trailing_bytes = bytes(data[pos:end])
            remaining_count = 0

    # Propagate observed separators to all sets
    if observed_sep:
        for s in sets:
            s.separator = observed_sep
    if observed_set_marker:
        for s in sets:
            s.set_marker = observed_set_marker

    return sets


def parse_iden_section(data, offset, end, first_count):
    """Parse CDefaultIdenElem section into list of IdenDataSets.

    Args:
        data: full file bytes or section raw bytes
        offset: start of element data (after class header)
        end: end of section
        first_count: number of elements in first set (from CIdenDataSet section)

    Returns:
        list of IdenDataSet objects
    """
    sets = []
    pos = offset
    remaining_count = first_count
    observed_sep = None
    observed_set_marker = None

    while pos < end - 4 and remaining_count > 0:
        elements = []
        for i in range(remaining_count):
            elem, pos = IdenElement.parse(data, pos)
            elements.append(elem)
            if i < remaining_count - 1:
                # Read and store the inter-element separator
                sep = bytes(data[pos:pos + 2])
                if observed_sep is None:
                    observed_sep = sep
                pos += 2

        # After last element: set name (LPS) + 2-byte metadata
        set_name, pos = read_lps(data, pos)
        meta, pos = read_bytes(data, pos, IdenDataSet.METADATA_SIZE)

        sets.append(IdenDataSet(name=set_name, elements=elements,
                                metadata=meta))

        # Inter-set gap: set_marker(2) + uint16(count) + separator(2)
        # Detect by checking both marker and separator have valid byte2
        if pos < end - 6 and _is_record_marker(data, pos):
            sm = bytes(data[pos:pos + 2])
            if observed_set_marker is None:
                observed_set_marker = sm
            pos += 2  # skip set marker
            remaining_count, pos = read_uint16_le(data, pos)
            # Read element separator after count
            elem_sep = bytes(data[pos:pos + 2])
            if observed_sep is None:
                observed_sep = elem_sep
            pos += 2  # skip element separator
        else:
            remaining_count = 0

    # Propagate observed separators to all sets
    if observed_sep:
        for s in sets:
            s.separator = observed_sep
    if observed_set_marker:
        for s in sets:
            s.set_marker = observed_set_marker

    return sets


def extract_iden_trailing_data(raw_section, first_count):
    """Extract trailing data from a CDefaultIdenElem section.

    The IDEN parser stops after the last set's 2-byte metadata. Everything
    after that is trailing data: padding, platformConfig XML, passwords,
    and radio GUID. This data must be preserved when rebuilding the section.

    Args:
        raw_section: full raw bytes of the CDefaultIdenElem section
        first_count: number of elements in first set (from CIdenDataSet)

    Returns:
        bytes: trailing data after the last IDEN set, or b'' if none
    """
    _, _, _, data_start = parse_class_header(raw_section, 0)
    pos = data_start
    remaining_count = first_count

    while pos < len(raw_section) - 4 and remaining_count > 0:
        # Skip through elements
        for i in range(remaining_count):
            _, pos = IdenElement.parse(raw_section, pos)
            if i < remaining_count - 1:
                pos += 2  # skip inter-element separator

        # After last element: set name (LPS) + 2-byte metadata
        _, pos = read_lps(raw_section, pos)
        _, pos = read_bytes(raw_section, pos, IdenDataSet.METADATA_SIZE)

        # Inter-set gap: set_marker(2) + uint16(count) + separator(2)
        # Detect by checking both set_marker and separator have valid byte2
        if pos + 6 <= len(raw_section) and _is_record_marker(raw_section, pos):
            pos += 2  # skip set marker
            remaining_count, pos = read_uint16_le(raw_section, pos)
            pos += 2  # skip separator
        else:
            remaining_count = 0

    return raw_section[pos:]


def parse_sets_from_sections(set_sec_raw, data_sec_raw, parser_func):
    """Parse data sets from raw set + data section bytes.

    Extracts the first-count from the set section header, then calls
    parser_func on the data section. Returns [] on any parse failure.

    Args:
        set_sec_raw: raw bytes of the set section (e.g. CP25GroupSet)
        data_sec_raw: raw bytes of the data section (e.g. CP25Group)
        parser_func: one of parse_group_section, parse_trunk_channel_section, etc.

    Returns:
        list of parsed set objects, or [] on failure
    """
    try:
        _, _, _, ds = parse_class_header(set_sec_raw, 0)
        fc, _ = read_uint16_le(set_sec_raw, ds)
        _, _, _, cd = parse_class_header(data_sec_raw, 0)
        return parser_func(data_sec_raw, cd, len(data_sec_raw), fc)
    except Exception:
        return []


# ─── CP25TrkSystem configuration ──────────────────────────────────────
#
# Each P25 trunked system is stored as:
#   1. A class header section: ffff 8d00 0d00 CP25TrkSystem LPS(name) 05
#   2. One or more data sections containing system parameters
#
# The data section has a universal prefix (shared with CConvSystem and
# CP25ConvSystem configs) followed by type-specific fields.

# Universal system config prefix (42 bytes, same for ALL system types)
SYSTEM_CONFIG_PREFIX = (
    b'\x01\x01\x00\x00\x00\x00\x01\x00'  # 8 bytes: system type flags
    b'\xb6\xb6\xb6\xb7\xb7\xb6\xb7'      # 7 bytes: fixed options block
    b'\x00\x00\x00\x00\x00'               # 5 bytes: block1
    b'\x01\x00\x00\x00'                   # 4 bytes: block2
    b'\xff\x00'                            # 2 bytes: constant 255
    b'\x05\x32\x05\x32'                   # 16 bytes: timer values
    b'\x02\x1e\x02\x23'
    b'\x14\x3c\x14\x32'
    b'\x0a\x1e\x0a\x1e'
)

# Block4: constant 12 bytes between HomeUnitID and WAN config
SYSTEM_BLOCK4 = b'\x03\x04\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00'

# WAN config block (44 bytes between WAN name 1 and WAN name 2).
# Structure: block_a(12) + wan_mode(2) + block_b(24) + chan_spacing(2) + base_freq(4)
# Verified from PAWSOVERMAWS — all systems have this same template.
_WAN_CONFIG_TEMPLATE = (
    b'\x00' * 12 +                                          # 12 bytes: block_a
    b'\x02\x01' +                                           # 2 bytes: wan_mode
    b'\x00\x00\x00\x01' +                                   # 4 bytes: block_b start (byte[3]=roaming flag)
    b'\x00' * 20 +                                           # 20 bytes: block_b rest
    b'\x6a\x18' +                                            # uint16: 6250 Hz (standard P25 spacing)
    b'\x2a\x53\xb9\x32'                                     # uint32: 851006250 Hz (standard 800 MHz base)
)

# Post-ECC tail (after IDEN set name LPS).
# Structure: 12 zeros + float32(value) + 29 zeros + uint32(1) + uint32(1) + 10 zeros
# The float32 at offset 12 varies per system (16339.0 for most, 9.0 for NELLIS).
# Total: 63 bytes.

def _build_post_ecc_tail(mystery_float=16339.0):
    """Build the 63-byte post-ECC tail with a specific mystery float.

    Structure: 12 zeros + float32(mystery_float) + 29 zeros +
    uint32(1) + uint32(1) + 10 zeros.

    Args:
        mystery_float: float32 value at offset 12 (default 16339.0)
    """
    buf = bytearray(63)
    struct.pack_into('<f', buf, 12, mystery_float)
    struct.pack_into('<I', buf, 45, 1)
    struct.pack_into('<I', buf, 49, 1)
    return bytes(buf)

# Default tail for backward compatibility
_POST_ECC_TAIL_AFTER_IDEN = _build_post_ecc_tail(16339.0)

# P25 trunk system flags: 15 bytes between long name and set references.
# Byte positions verified from claude test.PRS vs PAWSOVERMAWS comparison.
# Bytes [6,7,8,13] are confirmed booleans; [9-12] appear to be enum values.
P25_TRUNK_DEFAULT_FLAGS = b'\x00' * 15

# sys_flags byte index mapping (best-effort from binary analysis)
SYS_FLAG_LINEAR_SIMULCAST = 6
SYS_FLAG_TDMA_CAPABLE = 7
SYS_FLAG_ADAPTIVE_FILTER = 8
SYS_FLAG_ROAMING_MODE = 9      # 0=fixed, 1=dynamic, 2=enhanced_cc
SYS_FLAG_POWER_LEVEL = 10      # 0=low, 1=high, 2=max
SYS_FLAG_ENCRYPTION = 11       # 0=unencrypted, 1=DES, 2=AES
SYS_FLAG_AUTO_REG = 12         # 0=never, 1=system
SYS_FLAG_AVOID_FAILSOFT = 13


def build_sys_flags(settings=None):
    """Build the 15-byte sys_flags from a settings dict.

    Args:
        settings: dict with keys from gui/settings.py DEFAULTS.
                  If None, returns all-zeros (PAWSOVERMAWS defaults).

    Returns:
        15-byte bytes object
    """
    flags = bytearray(15)
    if not settings:
        return bytes(flags)

    # Boolean flags
    flags[SYS_FLAG_LINEAR_SIMULCAST] = int(
        settings.get("linear_simulcast", False))
    flags[SYS_FLAG_TDMA_CAPABLE] = int(
        settings.get("tdma_capable", False))
    flags[SYS_FLAG_ADAPTIVE_FILTER] = int(
        settings.get("adaptive_filter", False))
    flags[SYS_FLAG_AVOID_FAILSOFT] = int(
        settings.get("avoid_failsoft", False))

    # Enum values
    roaming = settings.get("roaming_mode", "fixed")
    flags[SYS_FLAG_ROAMING_MODE] = {
        "fixed": 0, "dynamic": 1, "enhanced_cc": 2}.get(roaming, 0)

    power = settings.get("power_level", "low")
    flags[SYS_FLAG_POWER_LEVEL] = {
        "low": 0, "high": 1, "max": 2}.get(power, 0)

    enc = settings.get("encryption_type", "unencrypted")
    flags[SYS_FLAG_ENCRYPTION] = {
        "unencrypted": 0, "des": 1, "aes": 2}.get(enc, 0)

    auto_reg = settings.get("auto_registration", "never")
    flags[SYS_FLAG_AUTO_REG] = {"never": 0, "system": 1}.get(auto_reg, 0)

    return bytes(flags)


def detect_band_limits(frequencies):
    """Determine band_low_hz/band_high_hz from a list of frequencies.

    Args:
        frequencies: list of frequency values in MHz

    Returns:
        (band_low_hz, band_high_hz) tuple. Defaults to 136-870 MHz
        for wide band coverage. Uses narrower limits for single-band
        systems (e.g., 767-858 for 700/800 only).
    """
    if not frequencies:
        return 136_000_000, 870_000_000

    min_freq = min(frequencies)
    max_freq = max(frequencies)

    # If all frequencies are in a narrow band, use tighter limits
    # 700/800 MHz only (WA State Patrol pattern: 767-858)
    if 700 <= min_freq <= 870 and 700 <= max_freq <= 870:
        return 767_000_000, 858_000_000

    # Default wide band
    return 136_000_000, 870_000_000


def detect_wan_config(frequencies, system_type=""):
    """Determine WAN channel spacing and base frequency from frequencies.

    Args:
        frequencies: list of frequency values in MHz
        system_type: RadioReference system type string

    Returns:
        (chan_spacing_hz, base_freq_hz) tuple
    """
    is_tdma = "Phase II" in system_type if system_type else False
    spacing = 6250 if is_tdma else 12500

    if not frequencies:
        return spacing, 851_006_250

    min_freq = min(frequencies)

    # Determine base frequency from band
    if 851 <= min_freq <= 870:
        base = 851_006_250 if is_tdma else 851_012_500
    elif 764 <= min_freq <= 806:
        base = 764_006_250
    elif 935 <= min_freq <= 940:
        base = 935_012_500
    elif 380 <= min_freq <= 512:
        base = int(min_freq * 1_000_000)
    else:
        base = int(min_freq * 1_000_000)

    return spacing, base

# Enhanced CC entry marker and size
ECC_MARKER = b'\x09\x80'
ECC_ENTRY_SIZE = 15  # 2 marker + 1 type + 2 sysid + 2 pad + 4 ch1 + 4 ch2


@dataclass
class EnhancedCCEntry:
    """Enhanced Control Channel entry for P25 trunked system band scanning.

    Structure (15 bytes):
      09 80    marker (2 bytes)
      type     uint8: 0x03 or 0x04
      sysid    uint16 LE: P25 System ID
      pad      2 zero bytes
      ch1      uint32 LE: channel reference 1
      ch2      uint32 LE: channel reference 2 (often same as ch1)
    """
    entry_type: int = 3        # 0x03 or 0x04
    system_id: int = 0         # P25 System ID
    channel_ref1: int = 0      # primary control channel reference
    channel_ref2: int = 0      # secondary (often same as ch1)

    def to_bytes(self):
        """Serialize to 15 bytes."""
        return (ECC_MARKER +
                struct.pack('<B', self.entry_type) +
                struct.pack('<H', self.system_id) +
                b'\x00\x00' +
                struct.pack('<I', self.channel_ref1) +
                struct.pack('<I', self.channel_ref2))

    @classmethod
    def from_bytes(cls, data, offset=0):
        """Parse from 15 bytes at the given offset."""
        if data[offset:offset + 2] != ECC_MARKER:
            return None
        entry_type = data[offset + 2]
        system_id = struct.unpack_from('<H', data, offset + 3)[0]
        ch1 = struct.unpack_from('<I', data, offset + 7)[0]
        ch2 = struct.unpack_from('<I', data, offset + 11)[0]
        return cls(entry_type=entry_type, system_id=system_id,
                   channel_ref1=ch1, channel_ref2=ch2)


def parse_ecc_entries(raw_section):
    """Parse enhanced CC entries from a P25 trunked system config section.

    Searches for the ECC count marker (byte 0x06 followed by uint16 count)
    in the trailing portion of the section, after the second WAN name.

    Returns: (ecc_count, list[EnhancedCCEntry], iden_set_name or None)
    """
    # Search backwards for 0x06 followed by uint16 count + 09 80 entries.
    # We require count > 0 and valid entries to avoid false positives
    # (the byte 0x06 can appear inside ECC entries as a channel reference).
    best_result = None

    for pos in range(len(raw_section) - 3, 40, -1):
        if raw_section[pos] != 0x06:
            continue

        count = struct.unpack_from('<H', raw_section, pos + 1)[0]

        if count == 0:
            # Zero entries — only valid if there's IDEN data or end of section
            # Skip: 0x06 + uint16(0) could be a false positive inside data
            continue

        if count > 50:
            # Unreasonably large — skip
            continue

        ecc_start = pos + 3
        if ecc_start + 2 > len(raw_section):
            continue
        if raw_section[ecc_start:ecc_start + 2] != ECC_MARKER:
            continue

        # Verify all entries fit
        ecc_end = ecc_start + count * ECC_ENTRY_SIZE
        if ecc_end > len(raw_section):
            continue

        # Parse entries — all must have valid 09 80 marker
        entries = []
        for i in range(count):
            entry = EnhancedCCEntry.from_bytes(
                raw_section, ecc_start + i * ECC_ENTRY_SIZE)
            if entry:
                entries.append(entry)
            else:
                break

        if len(entries) != count:
            continue

        # Look for IDEN set name after entries (4 zero bytes + LPS)
        iden_name = None
        iden_pos = ecc_end + 4  # skip 4 zero bytes
        if (iden_pos < len(raw_section) and
                raw_section[ecc_end:ecc_end + 4] == b'\x00\x00\x00\x00'):
            name_len = raw_section[iden_pos]
            if (0 < name_len <= 8 and
                    iden_pos + 1 + name_len <= len(raw_section)):
                try:
                    iden_name = raw_section[
                        iden_pos + 1:iden_pos + 1 + name_len
                    ].decode('ascii')
                except UnicodeDecodeError:
                    pass

        # Prefer results with IDEN name (more likely correct)
        if iden_name or best_result is None:
            best_result = (count, entries, iden_name)
        if iden_name:
            return best_result

    if best_result:
        return best_result
    return 0, [], None


# ─── Preferred System Table ────────────────────────────────────────────

PREF_ENTRY_SIZE = 15  # same as ECC: 1 type + 2 sysid + 2 pad + 4 field1 + 4 field2 + 2 sep
PREF_SEP = b'\x09\x80'  # separator between entries (same as ECC_MARKER)


@dataclass
class PreferredSystemEntry:
    """Preferred System Table entry for P25 scan priority.

    Structure (15 bytes, same frame as ECC entries):
      type    uint8:  0x03 or 0x04 (observed)
      sysid   uint16 LE: P25 site-level System ID
      pad     uint16 LE: always 0x0000
      field1  uint32 LE: priority/weight (observed: 1, 34)
      field2  uint32 LE: sequential index
      sep     2 bytes: 09 80 (more follow) or 00 00 / 01 00 (last)
    """
    entry_type: int = 3     # 0x03 typical
    system_id: int = 0      # P25 site System ID
    field1: int = 1         # priority (1 = standard)
    field2: int = 0         # sequence index
    last_sep: bytes = b'\x00\x00'  # terminator for last entry (varies by file)

    def to_bytes(self, is_last=False):
        """Serialize to 15 bytes."""
        sep = self.last_sep if is_last else PREF_SEP
        return (struct.pack('<B', self.entry_type) +
                struct.pack('<H', self.system_id) +
                b'\x00\x00' +
                struct.pack('<I', self.field1) +
                struct.pack('<I', self.field2) +
                sep)

    @staticmethod
    def from_bytes(data, offset):
        """Parse a 15-byte preferred entry. Returns entry or None."""
        if offset + PREF_ENTRY_SIZE > len(data):
            return None
        entry_type = data[offset]
        sysid = struct.unpack_from('<H', data, offset + 1)[0]
        # skip 2-byte pad
        field1 = struct.unpack_from('<I', data, offset + 5)[0]
        field2 = struct.unpack_from('<I', data, offset + 9)[0]
        sep = data[offset + 13:offset + 15]
        return PreferredSystemEntry(
            entry_type=entry_type, system_id=sysid,
            field1=field1, field2=field2, last_sep=sep)


def parse_preferred_section(raw):
    """Parse a CPreferredSystemTableEntry section.

    Args:
        raw: full section bytes (including ff ff header)

    Returns:
        (entries: list[PreferredSystemEntry],
         iden_name: str or None,
         tail_bytes: bytes,       # post-entries raw tail (gap + iden + tail + chain)
         chain_name: str or None, # next system name if chained
         chain_type: int)         # next system type byte
    """
    # Parse class header to find data start
    _, _, _, data_start = parse_class_header(raw, 0)

    # Parse entries until we hit a non-09-80 separator or end
    entries = []
    pos = data_start
    while pos + PREF_ENTRY_SIZE <= len(raw):
        entry = PreferredSystemEntry.from_bytes(raw, pos)
        if entry is None:
            break
        entries.append(entry)
        # Check separator (last 2 bytes of this 15-byte entry)
        sep = raw[pos + 13:pos + 15]
        pos += PREF_ENTRY_SIZE
        if sep != PREF_SEP:
            break  # last entry

    # Everything after entries is the tail
    tail_bytes = raw[pos:]

    # Try to parse tail: 2-byte gap + LPS(iden) + 63-byte tail + optional chain
    iden_name = None
    chain_name = None
    chain_type = 0
    try:
        tail_pos = pos + 2  # skip 2-byte gap
        if tail_pos < len(raw):
            iden_name, tail_pos = read_lps(raw, tail_pos)
        # Look for chain marker at the end: 07 80 + LPS + type
        # The 63-byte post-ECC tail sits between IDEN and chain
        for scan in range(len(raw) - 4, pos, -1):
            if raw[scan:scan + 2] == b'\x07\x80':
                name_len = raw[scan + 2]
                if (0 < name_len <= 8 and
                        scan + 3 + name_len < len(raw)):
                    try:
                        chain_name = raw[
                            scan + 3:scan + 3 + name_len
                        ].decode('ascii')
                        chain_type = raw[scan + 3 + name_len]
                    except (UnicodeDecodeError, IndexError):
                        pass
                break
    except (IndexError, ValueError):
        pass

    return entries, iden_name, tail_bytes, chain_name, chain_type


def build_preferred_section(entries, iden_name="", tail_bytes=None,
                            chain_name="", chain_type=0x05):
    """Build a CPreferredSystemTableEntry section from structured data.

    Args:
        entries: list of PreferredSystemEntry
        iden_name: IDEN set name reference
        tail_bytes: raw tail bytes to preserve (overrides iden/chain if set)
        chain_name: next system name for chaining
        chain_type: next system type (0x05=P25trunk, 0x01=conv, 0x03=P25conv)

    Returns:
        bytes: complete section including header
    """
    header = build_class_header('CPreferredSystemTableEntry', 0x64, 0x00)
    parts = [header]

    # Entry bytes
    for i, entry in enumerate(entries):
        parts.append(entry.to_bytes(is_last=(i == len(entries) - 1)))

    if tail_bytes is not None:
        # Preserve original tail verbatim
        parts.append(tail_bytes)
    else:
        # Build tail from components
        parts.append(b'\x00\x00')  # 2-byte gap
        parts.append(write_lps(iden_name[:8] if iden_name else ''))
        parts.append(_POST_ECC_TAIL_AFTER_IDEN)
        if chain_name:
            parts.append(b'\x07\x80')
            parts.append(write_lps(chain_name[:8]))
            parts.append(struct.pack('<B', chain_type))

    return b''.join(parts)


@dataclass
class P25TrkSystemConfig:
    """Full P25 trunked system configuration.

    Represents all the data needed to create a CP25TrkSystem header
    and its associated data section in a .PRS file.

    Binary layout (verified from PAWSOVERMAWS.PRS):
      SYSTEM_CONFIG_PREFIX(42) + LPS(long_name) + sys_flags(15)
      + LPS(trunk_set) + LPS(group_set) + 12 zeros
      + HomeUnitID(4) + BLOCK4(12) + 6 zeros + uint16(15)
      + system_id(4) + LPS(wan_name_1) + WAN_CONFIG(44)
      + LPS(wan_name_2) + HomeUnitID(4) + 5 zeros + HomeUnitID(4)
      + band_low(4) + band_high(4) + 0x06 + uint16(ecc_count)
      + N*ECC(15) [+ post_ecc_tail if inline system]
    """
    system_name: str         # short name for header (e.g., "PSERN")
    long_name: str = ""      # 16-char display name (e.g., "PSERN SEATTLE")
    trunk_set_name: str = "" # reference to CTrunkSet (e.g., "PSERN")
    group_set_name: str = "" # reference to CP25GroupSet (e.g., "PSERN PD")
    wan_name: str = ""       # WAN name, 8-char padded (e.g., "PSERN   ")
    home_unit_id: int = 0    # radio's unit ID on this system
    system_id: int = 0       # P25 System ID (decimal, e.g., 892 for PSERN)
    wacn: int = 0            # Wide Area Communication Network ID (for WAN section)
    sys_flags: bytes = P25_TRUNK_DEFAULT_FLAGS  # 15 bytes

    # Enhanced CC entries (for band scanning / roaming)
    ecc_entries: List[EnhancedCCEntry] = field(default_factory=list)

    # ECC count override: for root systems where the count is stored in the data
    # section but the actual entries live in CPreferredSystemTableEntry.
    # Set to None to use len(ecc_entries) (default for inline systems).
    ecc_count_override: Optional[int] = None

    # IDEN set reference (post-ECC, for inline systems)
    iden_set_name: str = ""  # e.g., "BEE00" — empty for root system

    # Band limits (Hz) for WAN after-WAN2 block
    band_low_hz: int = 136_000_000   # 136 MHz default (wide band)
    band_high_hz: int = 870_000_000  # 870 MHz default (wide band)

    # WAN config overrides
    wan_chan_spacing_hz: int = 6250   # standard P25 channel spacing
    wan_base_freq_hz: int = 851_006_250  # standard 800 MHz base freq

    # Next system reference (for chained inline configs)
    next_system_name: str = ""  # e.g., "SS911" — empty if last/root
    next_system_type: int = 0x05  # 0x05=P25trunk, 0x01=conv, 0x03=P25conv

    # Mystery float in post-ECC tail (varies per system, default 16339.0)
    post_ecc_float: float = 16339.0

    def build_header_section(self):
        """Build the CP25TrkSystem class header section bytes.

        Format: ffff 8d 00 0d00 CP25TrkSystem LPS(name) 05
        """
        return (SECTION_MARKER +
                b'\x8d\x00' +
                struct.pack('<H', 13) +  # len("CP25TrkSystem")
                b'CP25TrkSystem' +
                write_lps(self.system_name) +
                b'\x05')  # trailing byte (constant for P25 trunk)

    def build_data_section(self):
        """Build the system config data section bytes.

        Produces the correct binary structure matching PAWSOVERMAWS.PRS.
        """
        # Pad WAN name to 8 chars
        wan = self.wan_name or self.system_name
        if len(wan) < 8:
            wan = wan + ' ' * (8 - len(wan))
        wan = wan[:8]

        # Build WAN config block (44 bytes)
        wan_config = (
            b'\x00' * 12 +                                  # block_a
            b'\x02\x01' +                                    # wan_mode
            b'\x00\x00\x00\x01' +                           # block_b[0:4] (byte[3]=1 roaming flag)
            b'\x00' * 20 +                                   # block_b[4:24]
            write_uint16_le(self.wan_chan_spacing_hz) +       # channel spacing
            write_uint32_le(self.wan_base_freq_hz)           # base frequency
        )

        # Use ecc_count_override for root systems where entries are in
        # CPreferredSystemTableEntry, otherwise use actual entry count.
        ecc_count = (self.ecc_count_override if self.ecc_count_override is not None
                     else len(self.ecc_entries))

        parts = [
            SECTION_MARKER,
            SYSTEM_CONFIG_PREFIX,
            write_lps(self.long_name[:16] if self.long_name else ''),
            self.sys_flags,
            write_lps(self.trunk_set_name[:8] if self.trunk_set_name else ''),
            write_lps(self.group_set_name[:8] if self.group_set_name else ''),
            b'\x00' * 12,                          # 12-byte gap
            write_uint32_le(self.home_unit_id),     # HomeUnitID
            SYSTEM_BLOCK4,                          # 12-byte constant
            b'\x00' * 6,                            # 6-byte gap
            write_uint16_le(15),                    # constant 15
            write_uint32_le(self.system_id),        # P25 System ID
            write_lps(wan),                         # WAN name (first)
            wan_config,                             # WAN config (44 bytes)
            write_lps(wan),                         # WAN name (second)
            # After-WAN2 block
            write_uint32_le(self.home_unit_id),     # HomeUnitID repeat
            b'\x00' * 5,                            # 5 zero bytes
            write_uint32_le(self.home_unit_id),     # HomeUnitID repeat
            write_uint32_le(self.band_low_hz),      # band low limit Hz
            write_uint32_le(self.band_high_hz),     # band high limit Hz
            # ECC section
            b'\x06',                                # ECC marker
            write_uint16_le(ecc_count),
        ]

        # ECC entries
        for ecc in self.ecc_entries:
            parts.append(ecc.to_bytes())

        # Post-ECC tail (only for inline systems with IDEN reference)
        if self.iden_set_name:
            parts.append(b'\x00' * 4)
            parts.append(write_lps(self.iden_set_name[:8]))
            parts.append(_build_post_ecc_tail(self.post_ecc_float))
            # Next system reference — chain marker depends on next system type:
            # 0x01 (conv) -> 03 80, 0x03 (P25conv) -> 05 80, 0x05 (P25trunk) -> 07 80
            if self.next_system_name:
                chain_marker_byte = self.next_system_type + 2
                parts.append(struct.pack('BB', chain_marker_byte, 0x80))
                parts.append(write_lps(self.next_system_name[:8]))
                parts.append(struct.pack('B', self.next_system_type))
            else:
                parts.append(b'\x07\x00')

        return b''.join(parts)


@dataclass
class ConvSystemConfig:
    """Conventional system configuration.

    Creates a CConvSystem header and its data section. The data section
    references a CConvSet (conventional channel set) by name.

    The 4-byte tail after the 3-zero gap is a config value that varies:
      - 0x00000001 (1) for empty/terminal systems
      - other values (e.g., 0x00020621) for systems with channel data
    Preserved as raw bytes for roundtrip fidelity.

    Optional chain reference for multi-system configs:
      chain_marker_byte + 0x80 + LPS(next_system_name) + next_system_type
    """
    system_name: str         # short name for header (e.g., "FURRY WB")
    long_name: str = ""      # 16-char display name
    conv_set_name: str = ""  # reference to CConvSet (e.g., "FURRY WB")
    tail_config: bytes = b'\x01\x00\x00\x00'  # 4-byte config after 3-zero gap
    next_system_name: str = ""  # next system in chain (empty = terminal)
    next_system_type: int = 0x01  # 0x01=conv, 0x03=P25conv, 0x05=P25trunk

    def build_header_section(self):
        """Build the CConvSystem class header section bytes.

        Format: ffff 8d 00 0b00 CConvSystem LPS(name) 01
        """
        return (SECTION_MARKER +
                b'\x8d\x00' +
                struct.pack('<H', 11) +  # len("CConvSystem")
                b'CConvSystem' +
                write_lps(self.system_name) +
                b'\x01')  # trailing byte (constant for conv)

    def build_data_section(self):
        """Build the system config data section bytes."""
        parts = [
            SECTION_MARKER,
            SYSTEM_CONFIG_PREFIX,
            write_lps(self.long_name[:16] if self.long_name else ''),
            b'\x00' * 12,                              # 12-byte gap
            write_lps(self.conv_set_name[:8] if self.conv_set_name else ''),
            b'\x00' * 3,                                # 3-byte gap
            self.tail_config,                            # 4-byte config value
        ]
        # Chain reference for multi-system configs
        if self.next_system_name:
            chain_marker_byte = self.next_system_type + 2
            parts.append(struct.pack('BB', chain_marker_byte, 0x80))
            parts.append(write_lps(self.next_system_name[:8]))
            parts.append(struct.pack('B', self.next_system_type))
        return b''.join(parts)


# CP25ConvSystem trailing section template (28 bytes after ffff marker)
_P25CONV_TRAILING = (
    b'\x00\x00\x03\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00'
)


@dataclass
class P25ConvSystemConfig:
    """P25 conventional system configuration.

    Creates a CP25ConvSystem header, its data section, and a trailing
    data section. The data section references a CP25ConvSet by name.
    """
    system_name: str         # short name for header (e.g., "p25 conv")
    long_name: str = ""      # 16-char display name
    conv_set_name: str = ""  # reference to CP25ConvSet (e.g., "NEW")

    def build_header_section(self):
        """Build the CP25ConvSystem class header section bytes.

        Format: ffff 8d 00 0e00 CP25ConvSystem LPS(name) 03
        """
        return (SECTION_MARKER +
                b'\x8d\x00' +
                struct.pack('<H', 14) +  # len("CP25ConvSystem")
                b'CP25ConvSystem' +
                write_lps(self.system_name) +
                b'\x03')  # trailing byte (constant for P25 conv)

    def build_data_section(self):
        """Build the system config data section bytes."""
        parts = [
            SECTION_MARKER,
            SYSTEM_CONFIG_PREFIX,
            write_lps(self.long_name[:16] if self.long_name else ''),
            b'\x00' * 5,                                # 5-byte gap
            struct.pack('<I', 1),                        # uint32(1) constant
            write_lps(self.conv_set_name[:8] if self.conv_set_name else ''),
            b'\x00' * 27,                               # 27-byte padding
            b'\x01\x00\x01\x01\x00\xfc',               # terminal bytes
        ]
        return b''.join(parts)

    def build_trailing_section(self):
        """Build the second data section that follows CP25ConvSystem config."""
        return SECTION_MARKER + _P25CONV_TRAILING


def parse_system_long_name(raw):
    """Extract the long display name from a system config data section.

    The long name is an LPS string at a fixed offset (0x2c from section
    start) in all system config data sections (P25 trunk, conv, P25 conv).

    Args:
        raw: raw bytes of the data section (starts with ff ff)

    Returns:
        str or None
    """
    try:
        # Universal prefix is 44 bytes from start (including ff ff marker)
        # Long name LPS starts at byte 44
        name, _ = read_lps(raw, 44)
        return name if name else None
    except (IndexError, ValueError):
        return None


def parse_system_wan_name(raw):
    """Extract the WAN name from a P25 trunked system config data section.

    Navigates the variable-length field layout:
      SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42) + LPS(long_name)
      + sys_flags(15) + LPS(trunk_set) + LPS(group_set)
      + 12 zeros + HomeUnitID(4) + SYSTEM_BLOCK4(12)
      + 6 zeros + uint16(15) + system_id(4) + LPS(wan_name)

    Only works on P25 trunked system config sections.

    Args:
        raw: raw bytes of the data section (starts with ff ff)

    Returns:
        str or None
    """
    try:
        pos = 44  # after SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
        # Skip LPS(long_name)
        long_name, pos = read_lps(raw, pos)
        # Skip sys_flags (15 bytes)
        pos += 15
        # Skip LPS(trunk_set)
        _, pos = read_lps(raw, pos)
        # Skip LPS(group_set)
        _, pos = read_lps(raw, pos)
        # Skip 12 zeros + HomeUnitID(4) + SYSTEM_BLOCK4(12)
        pos += 12 + 4 + 12
        # Skip 6 zeros + uint16(15) + system_id(4)
        pos += 6 + 2 + 4
        # Now at LPS(wan_name)
        wan_name, _ = read_lps(raw, pos)
        return wan_name.strip() if wan_name else None
    except (IndexError, ValueError):
        return None


def parse_system_set_refs(raw):
    """Extract trunk set and group set names from a system config data section.

    The system config layout after the long name is:
      LPS(long_name) + sys_flags(15) + LPS(trunk_set) + LPS(group_set)

    Returns: (trunk_set_name, group_set_name) — either may be None.
    """
    try:
        pos = 44  # after SECTION_MARKER(2) + SYSTEM_CONFIG_PREFIX(42)
        _, pos = read_lps(raw, pos)   # skip long_name
        pos += 15                      # skip sys_flags
        trunk_set, pos = read_lps(raw, pos)
        group_set, _ = read_lps(raw, pos)
        return (trunk_set or None, group_set or None)
    except (IndexError, ValueError):
        return (None, None)


def parse_system_short_name(raw):
    """Extract the short system name from a class header section.

    System header sections (CP25TrkSystem, CConvSystem, CP25ConvSystem)
    have: ffff + 8d 00 + uint16(name_len) + class_name + LPS(system_name)

    Args:
        raw: raw bytes of the header section

    Returns:
        str or None
    """
    try:
        _, _, _, data_start = parse_class_header(raw, 0)
        name, _ = read_lps(raw, data_start)
        return name if name else None
    except (IndexError, ValueError):
        return None


def is_system_config_data(raw):
    """Check if a data section is a system config (P25 trunk/conv/P25conv).

    System config data sections all start with:
      ff ff 01 01 00 00 00 00 01 00 b6 b6 b6 b7 b7 b6 b7
    """
    if len(raw) < 20:
        return False
    return raw[2:9] == b'\x01\x01\x00\x00\x00\x00\x01' and \
           raw[10:17] == b'\xb6\xb6\xb6\xb7\xb7\xb6\xb7'


# ─── Section builders ─────────────────────────────────────────────────
#
# Build complete section raw bytes from structured data.

def build_trunk_channel_section(sets, byte1=0x64, byte2=0x00):
    """Build CTrunkChannel section bytes from list of TrunkSets."""
    header = build_class_header('CTrunkChannel', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else TRUNK_SET_MARKER
    sep = sets[0].separator if sets else TRUNK_CHANNEL_SEP

    for i, tset in enumerate(sets):
        # Channel data with separators
        parts.append(tset.channels_to_bytes())
        # Set metadata
        parts.append(tset.metadata_to_bytes())
        # Inter-set gap (not after last set)
        if i < len(sets) - 1:
            next_count = len(sets[i + 1].channels)
            parts.append(tset.gap_bytes)
            parts.append(b'\x01')
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)
        else:
            # Use preserved trailing if available, otherwise generate default
            if tset.trailing_bytes:
                parts.append(tset.trailing_bytes)
            else:
                parts.append(_build_trunk_trailing(len(sets)))

    return b''.join(parts)


def build_trunk_set_section(first_count, byte1=0x64, byte2=0x00):
    """Build CTrunkSet section bytes (just header + first set count)."""
    header = build_class_header('CTrunkSet', byte1, byte2)
    return header + write_uint16_le(first_count)


def build_group_section(sets, byte1=0x6a, byte2=0x00):
    """Build CP25Group section bytes from list of P25GroupSets."""
    header = build_class_header('CP25Group', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else GROUP_SET_MARKER
    sep = sets[0].separator if sets else GROUP_SEP

    for i, gset in enumerate(sets):
        parts.append(gset.groups_to_bytes())
        parts.append(gset.metadata_to_bytes())
        if i < len(sets) - 1:
            next_count = len(sets[i + 1].groups)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)
        else:
            # Append preserved trailing bytes if available
            if gset.trailing_bytes:
                parts.append(gset.trailing_bytes)

    return b''.join(parts)


def build_group_set_section(first_count, byte1=0x6a, byte2=0x00):
    """Build CP25GroupSet section bytes (header + first set count)."""
    header = build_class_header('CP25GroupSet', byte1, byte2)
    return header + write_uint16_le(first_count)


def build_conv_channel_section(sets, byte1=0x6a, byte2=0x00):
    """Build CConvChannel section bytes from list of ConvSets."""
    header = build_class_header('CConvChannel', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else CONV_SET_MARKER
    sep = sets[0].separator if sets else CONV_CHANNEL_SEP

    for i, cset in enumerate(sets):
        parts.append(cset.channels_to_bytes())
        parts.append(cset.metadata_to_bytes())
        if i < len(sets) - 1:
            next_count = len(sets[i + 1].channels)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)

    # Trailing 2 bytes — use stored value from last set
    trailing = sets[-1].trailing_uint16 if sets else len(sets)
    parts.append(write_uint16_le(trailing))

    return b''.join(parts)


def build_conv_set_section(first_count, byte1=0x65, byte2=0x00):
    """Build CConvSet section bytes (header + first set count)."""
    header = build_class_header('CConvSet', byte1, byte2)
    return header + write_uint16_le(first_count)


def build_iden_section(sets, byte1=0x66, byte2=0x00, trailing_data=None):
    """Build CDefaultIdenElem section bytes from list of IdenDataSets.

    Args:
        sets: list of IdenDataSet objects
        byte1: class header byte1
        byte2: class header byte2
        trailing_data: optional bytes to append after the last set's metadata.
            This preserves platformConfig XML, passwords, and GUID that live
            after the IDEN elements in the section.
    """
    header = build_class_header('CDefaultIdenElem', byte1, byte2)
    parts = [header]

    # Use separator/marker from first set (file-specific)
    set_marker = sets[0].set_marker if sets else IDEN_SET_MARKER
    sep = sets[0].separator if sets else IDEN_ELEMENT_SEP

    for i, iset in enumerate(sets):
        parts.append(iset.elements_to_bytes())
        parts.append(write_lps(iset.name))
        parts.append(iset.metadata)
        # Inter-set gap if not last
        if i < len(sets) - 1:
            next_count = len(sets[i + 1].elements)
            parts.append(set_marker)
            parts.append(write_uint16_le(next_count))
            parts.append(sep)

    if trailing_data:
        parts.append(trailing_data)

    return b''.join(parts)


def build_iden_set_section(first_count, byte1=0x66, byte2=0x00):
    """Build CIdenDataSet section bytes (header + first set count)."""
    header = build_class_header('CIdenDataSet', byte1, byte2)
    return header + write_uint16_le(first_count)


# ─── Internal helpers ─────────────────────────────────────────────────

def _build_trunk_interset_gap(next_count,
                              set_marker=TRUNK_SET_MARKER,
                              separator=TRUNK_CHANNEL_SEP):
    """Build the inter-set gap bytes for trunk channel sets.

    Format: 12 zeros + 01 + set_marker(2) + uint16(count) + separator(2)
    """
    return (b'\x00' * 12 +
            b'\x01' +
            set_marker +
            write_uint16_le(next_count) +
            separator)


def _build_trunk_trailing(num_sets):
    """Build trailing bytes after last trunk set.

    This is the end-of-section data that appears after the last set's metadata.
    Format: 12 zeros + 01 + trailing data
    """
    return (b'\x00' * 12 +
            b'\x01' +
            b'\x00' * 3 +
            write_uint8(num_sets) +
            b'\x00' * 2 +
            b'\xff\xff')


# ─── CPersonality ────────────────────────────────────────────────────
#
# The CPersonality section is the first section in every .PRS file.
# Structure:
#   class_header: ffff 85 00 0c 00 CPersonality
#   uint8(kv_len): length of the 0x08-delimited key-value block
#   kv_block: "Name" 08 filename 08 "LastSaved" 08 08 "SavedBy" 08 user 08
#             "Version" 08 "0014" 08
#   mystery4: 4 bytes (uint32 LE, 0 for saved files, 1 for unsaved)
#   LPS(version_str): typically "1"
#   LPS(guid): 36-char GUID or empty
#   LPS(platform): e.g. "PC" or empty
#   LPS(save_date): e.g. "31-10-2025" or empty
#   LPS(save_time): e.g. "09:22:23" or empty
#   LPS(tz_offset): e.g. "- 08:00" or empty
#   footer: variable-length tail bytes (preserved for roundtrip)

KV_DELIM = 0x08  # field delimiter in CPersonality key-value block


@dataclass
class Personality:
    """CPersonality file metadata section.

    The first section in every .PRS file, containing filename,
    save info, GUID, and platform metadata.
    """
    filename: str = ""          # PRS filename (e.g. "PAWSOVERMAWS.PRS")
    last_saved: str = ""        # usually empty in the KV block
    saved_by: str = ""          # user who last saved (e.g. "Abider")
    version: str = "0014"       # RPM version string
    mystery4: bytes = b'\x01\x00\x00\x00'  # 4 bytes, 01000000 for unsaved
    version_str: str = "1"      # always "1" observed
    guid: str = ""              # 36-char GUID or empty
    platform: str = ""          # "PC" or empty
    save_date: str = ""         # "31-10-2025" format or empty
    save_time: str = ""         # "09:22:23" format or empty
    tz_offset: str = ""         # "- 08:00" format or empty
    footer: bytes = b'\x02\x00\x65\x00\x7e\x00\x03\x00'  # tail bytes


def parse_personality_section(raw):
    """Parse a CPersonality section into a Personality dataclass.

    Args:
        raw: complete section bytes (including ff ff header)

    Returns:
        Personality object with all fields populated
    """
    # Skip class header: ffff(2) + byte1(1) + byte2(1) + uint16(name_len=12) + "CPersonality"(12)
    pos = 18

    # KV block length
    kv_len = raw[pos]
    pos += 1

    # Parse 0x08-delimited KV block
    kv_raw = raw[pos:pos + kv_len]
    pos += kv_len

    fields = []
    current = b''
    for b in kv_raw:
        if b == KV_DELIM:
            fields.append(current.decode('ascii', errors='replace'))
            current = b''
        else:
            current += bytes([b])
    if current:
        fields.append(current.decode('ascii', errors='replace'))

    # KV fields: Name, filename, LastSaved, (value), SavedBy, (value), Version, (value)
    filename = fields[1] if len(fields) > 1 else ""
    last_saved = fields[3] if len(fields) > 3 else ""
    saved_by = fields[5] if len(fields) > 5 else ""
    version = fields[7] if len(fields) > 7 else "0014"

    # After KV: mystery4 (4 bytes)
    mystery4 = raw[pos:pos + 4]
    pos += 4

    # LPS strings: version_str, guid, platform, date, time, tz
    version_str, pos = read_lps(raw, pos)
    guid, pos = read_lps(raw, pos)
    platform, pos = read_lps(raw, pos)
    save_date, pos = read_lps(raw, pos)
    save_time, pos = read_lps(raw, pos)
    tz_offset, pos = read_lps(raw, pos)

    # Remaining bytes are the footer
    footer = raw[pos:]

    return Personality(
        filename=filename, last_saved=last_saved, saved_by=saved_by,
        version=version, mystery4=mystery4, version_str=version_str,
        guid=guid, platform=platform, save_date=save_date,
        save_time=save_time, tz_offset=tz_offset, footer=footer,
    )


def build_personality_section(personality):
    """Build a CPersonality section from a Personality dataclass.

    Args:
        personality: Personality object

    Returns:
        bytes: complete section including header
    """
    p = personality

    # Build KV block
    kv_parts = [
        b'Name', p.filename.encode('ascii'),
        b'LastSaved', p.last_saved.encode('ascii'),
        b'SavedBy', p.saved_by.encode('ascii'),
        b'Version', p.version.encode('ascii'),
    ]
    kv_block = b''
    for i, part in enumerate(kv_parts):
        kv_block += part
        kv_block += bytes([KV_DELIM])

    # Class header
    header = build_class_header('CPersonality', 0x85, 0x00)

    parts = [
        header,
        write_uint8(len(kv_block)),     # KV block length
        kv_block,                        # KV block
        p.mystery4,                      # 4 mystery bytes
        write_lps(p.version_str),        # version string LPS
        write_lps(p.guid),              # GUID LPS
        write_lps(p.platform),          # platform LPS
        write_lps(p.save_date),         # date LPS
        write_lps(p.save_time),         # time LPS
        write_lps(p.tz_offset),         # timezone LPS
        p.footer,                        # footer tail bytes
    ]

    return b''.join(parts)


# ─── CP25TrkWan / CP25tWanOpts ──────────────────────────────────────
#
# CP25tWanOpts: class header + uint16(wan_count)
#   Tells how many WAN entries follow in the CP25TrkWan section.
#
# CP25TrkWan: class header + N entries
#   Each entry: LPS(8, wan_name) + uint32_LE(wacn) + uint16_LE(system_id)
#   Inter-entry separator: 31 82 (2 bytes)
#   Last entry has no separator.
#
# WACN = Wide Area Communication Network ID (20-bit P25 identifier)
# System ID = P25 site-level System ID (uint16)

WAN_ENTRY_SEP = b'\x31\x82'


@dataclass
class P25TrkWanEntry:
    """Single P25 trunked WAN entry.

    Each entry maps a WAN name to its WACN and System ID.
    WAN names are padded to 8 characters with spaces.

    Attributes:
        wan_name: 8-char WAN name (e.g. "PSERN   ")
        wacn: Wide Area Communication Network ID (uint32)
        system_id: P25 site-level System ID (uint16)
    """
    wan_name: str = ""
    wacn: int = 0           # uint32 LE, WACN identifier
    system_id: int = 0      # uint16 LE, P25 System ID

    ENTRY_DATA_SIZE = 6     # 4 bytes WACN + 2 bytes System ID

    @classmethod
    def parse(cls, data, offset):
        """Parse a WAN entry at the given offset.

        Returns (P25TrkWanEntry, new_offset).
        """
        wan_name, offset = read_lps(data, offset)
        wacn, offset = read_uint32_le(data, offset)
        system_id, offset = read_uint16_le(data, offset)
        return cls(wan_name=wan_name, wacn=wacn, system_id=system_id), offset

    def to_bytes(self):
        """Serialize entry data (name + WACN + SysID), without separator."""
        # Pad WAN name to 8 chars
        name = self.wan_name
        if len(name) < 8:
            name = name + ' ' * (8 - len(name))
        name = name[:8]
        return (write_lps(name) +
                write_uint32_le(self.wacn) +
                write_uint16_le(self.system_id))


def parse_wan_opts_section(raw):
    """Parse a CP25tWanOpts section to get the WAN entry count.

    Args:
        raw: complete section bytes (including ff ff header)

    Returns:
        int: number of WAN entries
    """
    _, _, _, data_start = parse_class_header(raw, 0)
    count, _ = read_uint16_le(raw, data_start)
    return count


def build_wan_opts_section(wan_count):
    """Build a CP25tWanOpts section.

    Args:
        wan_count: number of WAN entries

    Returns:
        bytes: complete section including header
    """
    header = build_class_header('CP25tWanOpts', 0x64, 0x00)
    return header + write_uint16_le(wan_count)


def parse_wan_section(raw):
    """Parse a CP25TrkWan section into a list of P25TrkWanEntry.

    Args:
        raw: complete section bytes (including ff ff header)

    Returns:
        list[P25TrkWanEntry]
    """
    _, _, _, data_start = parse_class_header(raw, 0)
    entries = []
    pos = data_start

    while pos < len(raw):
        entry, pos = P25TrkWanEntry.parse(raw, pos)
        entries.append(entry)

        # Check for separator (31 82)
        if pos + 2 <= len(raw) and raw[pos:pos + 2] == WAN_ENTRY_SEP:
            pos += 2  # skip separator
        else:
            break  # last entry or end of data

    return entries


def build_wan_section(entries):
    """Build a CP25TrkWan section from a list of P25TrkWanEntry.

    Args:
        entries: list of P25TrkWanEntry objects

    Returns:
        bytes: complete section including header
    """
    header = build_class_header('CP25TrkWan', 0x64, 0x00)
    parts = [header]

    for i, entry in enumerate(entries):
        parts.append(entry.to_bytes())
        if i < len(entries) - 1:
            parts.append(WAN_ENTRY_SEP)

    return b''.join(parts)


# ─── Option section dataclasses ───────────────────────────────────────
# These provide parse/build roundtrip for the major binary option sections.
# Each stores raw_data for guaranteed byte-identical rebuild, plus decoded
# named fields for the bytes whose meaning is known.


@dataclass
class GenRadioOpts:
    """CGenRadioOpts — General Radio Options (41 data bytes).

    Contains NPSPAC override, noise cancellation type, EDACS LID range,
    and various boolean settings. Most booleans are unchecked (0x00)
    in the reference file.
    """
    DATA_SIZE = 41

    raw_data: bytes = b'\x00' * 41

    # Decoded fields (known meanings)
    npspac_override: bool = False           # byte 0
    noise_cancellation_type: int = 0x00     # byte 3 (0=Method B, 1=Method A)
    edacs_min_lid: int = 1                  # bytes 13-14, uint16 LE
    edacs_max_lid: int = 16382              # bytes 15-16, uint16 LE
    # Bytes with observed non-zero values but uncertain RPM names
    gen_radio_byte_19: int = 0              # byte 19 (0xA0/160 in PAWSOVERMAWS)
    gen_radio_byte_30: bool = False         # byte 30
    gen_radio_byte_33: int = 0              # byte 33 (10 in PAWSOVERMAWS)
    gen_radio_byte_37: bool = False         # byte 37

    @classmethod
    def parse(cls, data, offset=0):
        """Parse from raw data bytes (after class header)."""
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"GenRadioOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            npspac_override=bool(raw[0]),
            noise_cancellation_type=raw[3],
            edacs_min_lid=struct.unpack_from('<H', raw, 13)[0],
            edacs_max_lid=struct.unpack_from('<H', raw, 15)[0],
            gen_radio_byte_19=raw[19],
            gen_radio_byte_30=bool(raw[30]),
            gen_radio_byte_33=raw[33],
            gen_radio_byte_37=bool(raw[37]),
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        """Rebuild from raw_data with decoded fields written back."""
        buf = bytearray(self.raw_data)
        buf[0] = int(self.npspac_override)
        buf[3] = self.noise_cancellation_type
        struct.pack_into('<H', buf, 13, self.edacs_min_lid)
        struct.pack_into('<H', buf, 15, self.edacs_max_lid)
        buf[19] = self.gen_radio_byte_19
        buf[30] = int(self.gen_radio_byte_30)
        buf[33] = self.gen_radio_byte_33
        buf[37] = int(self.gen_radio_byte_37)
        return bytes(buf)


@dataclass
class TimerOpts:
    """CTimerOpts — Timer Options (82 data bytes).

    Contains timeout values for various radio functions stored as IEEE 754
    doubles. Layout: 4-byte prefix (zeros) + timer doubles + suffix.

    Known doubles:
      offset 4:  priority_call_timeout (0.0 in reference)
      offset 12: timer_field_12 (1.0 — unidentified)
      offset 20: phone_entry_mode (10.0)
      offset 28: icall_timeout (10.0)
      offset 36: icall_entry_mode (10.0)
      offset 44: cc_scan_delay_timer (0.0)
      offset 52: cct (60.0 — confirmed)
      offset 68: vote_scan_hangtime (0.0)
    Byte 63: standalone uint8 (30/0x1E — NOT part of a double)
    """
    DATA_SIZE = 82

    raw_data: bytes = b'\x00' * 82

    # Decoded fields
    priority_call_timeout: float = 0.0      # bytes 4-11
    timer_field_12: float = 1.0             # bytes 12-19
    phone_entry_mode: float = 10.0          # bytes 20-27
    icall_timeout: float = 10.0             # bytes 28-35
    icall_entry_mode: float = 10.0          # bytes 36-43
    cc_scan_delay_timer: float = 0.0        # bytes 44-51
    cct: float = 60.0                       # bytes 52-59
    timer_byte_63: int = 0x1E              # byte 63 (30)
    vote_scan_hangtime: float = 0.0         # bytes 68-75

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"TimerOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            priority_call_timeout=struct.unpack_from('<d', raw, 4)[0],
            timer_field_12=struct.unpack_from('<d', raw, 12)[0],
            phone_entry_mode=struct.unpack_from('<d', raw, 20)[0],
            icall_timeout=struct.unpack_from('<d', raw, 28)[0],
            icall_entry_mode=struct.unpack_from('<d', raw, 36)[0],
            cc_scan_delay_timer=struct.unpack_from('<d', raw, 44)[0],
            cct=struct.unpack_from('<d', raw, 52)[0],
            timer_byte_63=raw[63],
            vote_scan_hangtime=struct.unpack_from('<d', raw, 68)[0],
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        struct.pack_into('<d', buf, 4, self.priority_call_timeout)
        struct.pack_into('<d', buf, 12, self.timer_field_12)
        struct.pack_into('<d', buf, 20, self.phone_entry_mode)
        struct.pack_into('<d', buf, 28, self.icall_timeout)
        struct.pack_into('<d', buf, 36, self.icall_entry_mode)
        struct.pack_into('<d', buf, 44, self.cc_scan_delay_timer)
        struct.pack_into('<d', buf, 52, self.cct)
        buf[63] = self.timer_byte_63
        struct.pack_into('<d', buf, 68, self.vote_scan_hangtime)
        return bytes(buf)


@dataclass
class ScanOpts:
    """CScanOpts — Scan Options (33 data bytes).

    Contains conventional scan, trunked scan, and universal scan settings.
    5 booleans at bytes 0-4, a universal hang time double at 11-18,
    and scan parameters at bytes 19, 29, 32.
    """
    DATA_SIZE = 33

    raw_data: bytes = b'\x00' * 33

    # Decoded fields
    scan_with_channel_guard: bool = False    # byte 0
    alternate_scan: bool = False             # byte 1
    always_scan_selected_chan: bool = False   # byte 2
    conv_pri_scan_with_cg: bool = False      # byte 3
    scan_after_ptt: bool = False             # byte 4
    universal_hang_time: float = 0.0         # bytes 11-18
    scan_byte_19: int = 0                    # byte 19 (0x40/64 in PAWSOVERMAWS)
    conv_pri_scan_hang_time: int = 0         # byte 29
    band_hunt_interval: int = 0              # byte 32

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"ScanOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            scan_with_channel_guard=bool(raw[0]),
            alternate_scan=bool(raw[1]),
            always_scan_selected_chan=bool(raw[2]),
            conv_pri_scan_with_cg=bool(raw[3]),
            scan_after_ptt=bool(raw[4]),
            universal_hang_time=struct.unpack_from('<d', raw, 11)[0],
            scan_byte_19=raw[19],
            conv_pri_scan_hang_time=raw[29],
            band_hunt_interval=raw[32],
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = int(self.scan_with_channel_guard)
        buf[1] = int(self.alternate_scan)
        buf[2] = int(self.always_scan_selected_chan)
        buf[3] = int(self.conv_pri_scan_with_cg)
        buf[4] = int(self.scan_after_ptt)
        struct.pack_into('<d', buf, 11, self.universal_hang_time)
        buf[19] = self.scan_byte_19
        buf[29] = self.conv_pri_scan_hang_time
        buf[32] = self.band_hunt_interval
        return bytes(buf)


@dataclass
class PowerUpOpts:
    """CPowerUpOpts — Power Up Options (36 data bytes).

    Controls radio behavior at power-on: startup selection mode, various
    boolean overrides, squelch level, and PIN lockout settings.
    """
    DATA_SIZE = 36

    raw_data: bytes = b'\x00' * 36

    # Decoded fields
    power_up_selection: int = 0x00           # byte 0 (0=Default, 1=Sys/Grp, 2=Zone/Grp)
    pu_ignore_ab_switch: bool = False        # byte 1
    pu_contrast: bool = False                # byte 2
    pu_keypad_lock: bool = False             # byte 3
    pu_keypad_state: bool = False            # byte 4
    pu_edacs_auto_login: bool = False        # byte 5
    pu_squelch: bool = False                 # byte 6
    pu_external_alarm: bool = False          # byte 7
    pu_scan: bool = False                    # byte 8
    pu_audible_tone: bool = False            # byte 9
    pu_private_mode: bool = False            # byte 10
    power_up_byte_11: int = 0               # byte 11 (15 in PAWSOVERMAWS)
    power_up_byte_13: int = 0               # byte 13 (3 in PAWSOVERMAWS)
    power_up_byte_20: int = 0               # byte 20 (40/0x28 in PAWSOVERMAWS)
    power_up_byte_22: int = 0               # byte 22 (6 in PAWSOVERMAWS)
    squelch_level: int = 0                   # byte 24 (0-15)
    max_bad_pin_entries: int = 0             # byte 30

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"PowerUpOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            power_up_selection=raw[0],
            pu_ignore_ab_switch=bool(raw[1]),
            pu_contrast=bool(raw[2]),
            pu_keypad_lock=bool(raw[3]),
            pu_keypad_state=bool(raw[4]),
            pu_edacs_auto_login=bool(raw[5]),
            pu_squelch=bool(raw[6]),
            pu_external_alarm=bool(raw[7]),
            pu_scan=bool(raw[8]),
            pu_audible_tone=bool(raw[9]),
            pu_private_mode=bool(raw[10]),
            power_up_byte_11=raw[11],
            power_up_byte_13=raw[13],
            power_up_byte_20=raw[20],
            power_up_byte_22=raw[22],
            squelch_level=raw[24],
            max_bad_pin_entries=raw[30],
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = self.power_up_selection
        buf[1] = int(self.pu_ignore_ab_switch)
        buf[2] = int(self.pu_contrast)
        buf[3] = int(self.pu_keypad_lock)
        buf[4] = int(self.pu_keypad_state)
        buf[5] = int(self.pu_edacs_auto_login)
        buf[6] = int(self.pu_squelch)
        buf[7] = int(self.pu_external_alarm)
        buf[8] = int(self.pu_scan)
        buf[9] = int(self.pu_audible_tone)
        buf[10] = int(self.pu_private_mode)
        buf[11] = self.power_up_byte_11
        buf[13] = self.power_up_byte_13
        buf[20] = self.power_up_byte_20
        buf[22] = self.power_up_byte_22
        buf[24] = self.squelch_level
        buf[30] = self.max_bad_pin_entries
        return bytes(buf)


@dataclass
class DisplayOpts:
    """CDisplayOpts — Display Options (37 data bytes).

    Contains display-related settings. Cross-references with the XML
    platformConfig miscConfig section which covers some display settings
    (backlight mode, brightness, timeout, LED, orientation).

    Known fields:
      byte 3:  display boolean (True in PAWSOVERMAWS)
      byte 8:  display boolean (True in PAWSOVERMAWS)
      byte 12: uint8 parameter (42/0x2A in PAWSOVERMAWS)
      bytes 15-22: IEEE 754 double (3.5 in PAWSOVERMAWS)
      byte 29: display boolean (True in PAWSOVERMAWS)
    """
    DATA_SIZE = 37

    raw_data: bytes = b'\x00' * 37

    # Decoded fields
    display_opt_bool_0: bool = False         # byte 3
    display_opt_bool_1: bool = False         # byte 8
    display_opt_byte_12: int = 0             # byte 12 (42/0x2A in PAWSOVERMAWS)
    display_opt_double_15: float = 0.0       # bytes 15-22 (3.5 in PAWSOVERMAWS)
    display_opt_bool_2: bool = False         # byte 29

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"DisplayOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            display_opt_bool_0=bool(raw[3]),
            display_opt_bool_1=bool(raw[8]),
            display_opt_byte_12=raw[12],
            display_opt_double_15=struct.unpack_from('<d', raw, 15)[0],
            display_opt_bool_2=bool(raw[29]),
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[3] = int(self.display_opt_bool_0)
        buf[8] = int(self.display_opt_bool_1)
        buf[12] = self.display_opt_byte_12
        struct.pack_into('<d', buf, 15, self.display_opt_double_15)
        buf[29] = int(self.display_opt_bool_2)
        return bytes(buf)


@dataclass
class DataOpts:
    """CDataOpts — Data Options (41 data bytes).

    Contains data interface protocol, DCS+ settings, PPP/SLIP configuration,
    IP addresses, serial port settings, and GPS mic interval.
    """
    DATA_SIZE = 41

    raw_data: bytes = b'\x00' * 41

    # Decoded fields
    ptt_receive_data: bool = False           # byte 3
    ptt_transmit_data: bool = False          # byte 4
    tx_data_overrides_rx_grp_call: bool = False  # byte 5
    data_interface_protocol: int = 0x00      # byte 6 (0=DI, 1=PPP/SLIP)
    gps_mic_sample_interval: int = 0         # byte 10
    dcs_max_frame_retries: int = 0           # byte 13
    dcs_max_frame_repeats: int = 0           # byte 14
    dcs_ack_response_timeout: int = 0        # byte 15 (x100=ms, 10=1000ms)
    dcs_data_response_timeout: int = 0       # byte 16 (x100=ms, 80=8000ms)
    ppp_slip_retry_count: int = 0            # byte 20
    ppp_slip_retry_interval: int = 0         # byte 21
    ppp_slip_ttl: int = 0                    # byte 23
    service_address: bytes = b'\x00' * 4     # bytes 25-28, IPv4
    serial_baud_rate: int = 0x00             # byte 31 (0=300..5=19200)
    mdt_address: bytes = b'\x00' * 4         # bytes 35-38, IPv4
    serial_stop_bits: int = 0x01             # byte 39 (1=One, 2=Two)

    @property
    def service_address_str(self):
        """Human-readable service IP address."""
        return '.'.join(str(b) for b in self.service_address)

    @property
    def mdt_address_str(self):
        """Human-readable MDT IP address."""
        return '.'.join(str(b) for b in self.mdt_address)

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"DataOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            ptt_receive_data=bool(raw[3]),
            ptt_transmit_data=bool(raw[4]),
            tx_data_overrides_rx_grp_call=bool(raw[5]),
            data_interface_protocol=raw[6],
            gps_mic_sample_interval=raw[10],
            dcs_max_frame_retries=raw[13],
            dcs_max_frame_repeats=raw[14],
            dcs_ack_response_timeout=raw[15],
            dcs_data_response_timeout=raw[16],
            ppp_slip_retry_count=raw[20],
            ppp_slip_retry_interval=raw[21],
            ppp_slip_ttl=raw[23],
            service_address=bytes(raw[25:29]),
            serial_baud_rate=raw[31],
            mdt_address=bytes(raw[35:39]),
            serial_stop_bits=raw[39],
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[3] = int(self.ptt_receive_data)
        buf[4] = int(self.ptt_transmit_data)
        buf[5] = int(self.tx_data_overrides_rx_grp_call)
        buf[6] = self.data_interface_protocol
        buf[10] = self.gps_mic_sample_interval
        buf[13] = self.dcs_max_frame_retries
        buf[14] = self.dcs_max_frame_repeats
        buf[15] = self.dcs_ack_response_timeout
        buf[16] = self.dcs_data_response_timeout
        buf[20] = self.ppp_slip_retry_count
        buf[21] = self.ppp_slip_retry_interval
        buf[23] = self.ppp_slip_ttl
        buf[25:29] = self.service_address
        buf[31] = self.serial_baud_rate
        buf[35:39] = self.mdt_address
        buf[39] = self.serial_stop_bits
        return bytes(buf)


@dataclass
class SupervisoryOpts:
    """CSupervisoryOpts — Supervisory Options (36 data bytes).

    Contains emergency-related timer values stored as IEEE 754 doubles.
    Layout: 4 doubles (32 bytes) + 4-byte suffix (zeros).
    """
    DATA_SIZE = 36

    raw_data: bytes = b'\x00' * 36

    # Decoded fields — all 4 doubles
    supervisory_double_0: float = 0.0          # bytes 0-7 (0.0 in PAWSOVERMAWS)
    emergency_key_delay: float = 1.0           # bytes 8-15 (1.0 confirmed)
    emergency_autokey_timeout: float = 0.0     # bytes 16-23
    emergency_autocycle_timeout: float = 0.0   # bytes 24-31

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"SupervisoryOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        obj = cls(
            raw_data=raw,
            supervisory_double_0=struct.unpack_from('<d', raw, 0)[0],
            emergency_key_delay=struct.unpack_from('<d', raw, 8)[0],
            emergency_autokey_timeout=struct.unpack_from('<d', raw, 16)[0],
            emergency_autocycle_timeout=struct.unpack_from('<d', raw, 24)[0],
        )
        return obj, offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        struct.pack_into('<d', buf, 0, self.supervisory_double_0)
        struct.pack_into('<d', buf, 8, self.emergency_key_delay)
        struct.pack_into('<d', buf, 16, self.emergency_autokey_timeout)
        struct.pack_into('<d', buf, 24, self.emergency_autocycle_timeout)
        return bytes(buf)


# ─── Remaining option section dataclasses ─────────────────────────────
# All use the raw_data blob pattern for guaranteed roundtrip fidelity.
# Named properties decode the fields whose meanings are known from RPM
# option maps. Reserved/unknown bytes are preserved in raw_data.


@dataclass
class VgOpts:
    """CVgOpts — Voice Guard / Encryption Options (54 data bytes).

    Contains encryption key settings, polarity options, and a 16-byte
    key bank field (bytes 6-21). Byte 5 holds max_key_bank size,
    byte 24 is encryption_mode.
    """
    DATA_SIZE = 54

    raw_data: bytes = b'\x00' * 54

    # Decoded fields
    tx_data_polarity: int = 0           # byte 0
    rx_data_polarity: int = 0           # byte 1
    max_key_bank: int = 0               # byte 2
    encryption_key_size: int = 0        # byte 5
    encryption_mode: int = 0            # byte 24

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"VgOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            tx_data_polarity=raw[0],
            rx_data_polarity=raw[1],
            max_key_bank=raw[2],
            encryption_key_size=raw[5],
            encryption_mode=raw[24],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = self.tx_data_polarity
        buf[1] = self.rx_data_polarity
        buf[2] = self.max_key_bank
        buf[5] = self.encryption_key_size
        buf[24] = self.encryption_mode
        return bytes(buf)


@dataclass
class NetworkOpts:
    """CNetworkOpts — Network Options (38 data bytes).

    Contains network configuration including two IEEE 754 doubles
    (timer values at offsets 17 and 25) and boolean/uint8 settings.
    """
    DATA_SIZE = 38

    raw_data: bytes = b'\x00' * 38

    # Decoded fields
    network_byte_5: bool = False        # byte 5
    network_byte_10: int = 0            # byte 10
    network_byte_13: bool = False       # byte 13
    network_byte_15: int = 0            # byte 15
    network_timer_1: float = 0.0        # bytes 17-24
    network_timer_2: float = 0.0        # bytes 25-32

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"NetworkOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            network_byte_5=bool(raw[5]),
            network_byte_10=raw[10],
            network_byte_13=bool(raw[13]),
            network_byte_15=raw[15],
            network_timer_1=struct.unpack_from('<d', raw, 17)[0],
            network_timer_2=struct.unpack_from('<d', raw, 25)[0],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[5] = int(self.network_byte_5)
        buf[10] = self.network_byte_10
        buf[13] = int(self.network_byte_13)
        buf[15] = self.network_byte_15
        struct.pack_into('<d', buf, 17, self.network_timer_1)
        struct.pack_into('<d', buf, 25, self.network_timer_2)
        return bytes(buf)


@dataclass
class GEstarOpts:
    """CGEstarOpts — GE-STAR Options (35 data bytes).

    Contains GE-STAR trunking protocol settings. Includes a P25C
    repeat emergency tone boolean, a start delay double at offset 10,
    and emergency repeat count.
    """
    DATA_SIZE = 35

    raw_data: bytes = b'\x00' * 35

    # Decoded fields
    p25c_repeat_emer_tone: bool = False  # byte 4
    start_delay: float = 0.0            # bytes 10-17
    emer_repeat: int = 0                # byte 19
    gestar_byte_21: int = 0            # byte 21
    gestar_byte_22: int = 0            # byte 22

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"GEstarOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            p25c_repeat_emer_tone=bool(raw[4]),
            start_delay=struct.unpack_from('<d', raw, 10)[0],
            emer_repeat=raw[19],
            gestar_byte_21=raw[21],
            gestar_byte_22=raw[22],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[4] = int(self.p25c_repeat_emer_tone)
        struct.pack_into('<d', buf, 10, self.start_delay)
        buf[19] = self.emer_repeat
        buf[21] = self.gestar_byte_21
        buf[22] = self.gestar_byte_22
        return bytes(buf)


@dataclass
class ConvScanOpts:
    """CConvScanOpts — Conventional Scan Options (30 data bytes).

    Contains conventional scan booleans (bytes 0-6), scan mode (byte 7),
    and a double at offset 9 (value 2.0 in reference file).
    """
    DATA_SIZE = 30

    raw_data: bytes = b'\x00' * 30

    # Decoded fields
    conv_scan_opt_0: bool = False       # byte 0
    conv_scan_gap_1: bool = False       # byte 1
    conv_scan_opt_1: bool = False       # byte 2
    conv_scan_gap_3: bool = False       # byte 3
    conv_scan_opt_2: bool = False       # byte 4
    conv_scan_gap_5: bool = False       # byte 5
    conv_scan_opt_3: bool = False       # byte 6
    conv_scan_mode: int = 0             # byte 7
    conv_scan_double_9: float = 0.0     # bytes 9-16

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"ConvScanOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            conv_scan_opt_0=bool(raw[0]),
            conv_scan_gap_1=bool(raw[1]),
            conv_scan_opt_1=bool(raw[2]),
            conv_scan_gap_3=bool(raw[3]),
            conv_scan_opt_2=bool(raw[4]),
            conv_scan_gap_5=bool(raw[5]),
            conv_scan_opt_3=bool(raw[6]),
            conv_scan_mode=raw[7],
            conv_scan_double_9=struct.unpack_from('<d', raw, 9)[0],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = int(self.conv_scan_opt_0)
        buf[1] = int(self.conv_scan_gap_1)
        buf[2] = int(self.conv_scan_opt_1)
        buf[3] = int(self.conv_scan_gap_3)
        buf[4] = int(self.conv_scan_opt_2)
        buf[5] = int(self.conv_scan_gap_5)
        buf[6] = int(self.conv_scan_opt_3)
        buf[7] = self.conv_scan_mode
        struct.pack_into('<d', buf, 9, self.conv_scan_double_9)
        return bytes(buf)


@dataclass
class ProSoundOpts:
    """CProSoundOpts — ProSound Options (28 data bytes).

    Contains sensitivity and system sample time as doubles, plus
    six uint8 parameters at odd offsets (17, 19, 21, 23, 25, 27).
    """
    DATA_SIZE = 28

    raw_data: bytes = b'\x00' * 28

    # Decoded fields
    sensitivity: float = 0.0            # bytes 1-8
    system_sample_time: float = 0.0     # bytes 9-16
    proscan_param_17: int = 0           # byte 17
    proscan_param_19: int = 0           # byte 19
    proscan_param_21: int = 0           # byte 21
    proscan_param_23: int = 0           # byte 23
    proscan_param_25: int = 0           # byte 25
    proscan_param_27: int = 0           # byte 27

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"ProSoundOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            sensitivity=struct.unpack_from('<d', raw, 1)[0],
            system_sample_time=struct.unpack_from('<d', raw, 9)[0],
            proscan_param_17=raw[17],
            proscan_param_19=raw[19],
            proscan_param_21=raw[21],
            proscan_param_23=raw[23],
            proscan_param_25=raw[25],
            proscan_param_27=raw[27],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        struct.pack_into('<d', buf, 1, self.sensitivity)
        struct.pack_into('<d', buf, 9, self.system_sample_time)
        buf[17] = self.proscan_param_17
        buf[19] = self.proscan_param_19
        buf[21] = self.proscan_param_21
        buf[23] = self.proscan_param_23
        buf[25] = self.proscan_param_25
        buf[27] = self.proscan_param_27
        return bytes(buf)


@dataclass
class SystemScanOpts:
    """CSystemScanOpts — System Scan Options (24 data bytes).

    Contains scan type, priority scan boolean, tone suppress,
    CC loop count double (offset 7), and priority scan time double
    (offset 15).
    """
    DATA_SIZE = 24

    raw_data: bytes = b'\x00' * 24

    # Decoded fields
    scan_type: int = 0                  # byte 0
    priority_scan: bool = False         # byte 1
    tone_suppress: bool = False         # byte 2
    sys_scan_byte_5: int = 0            # byte 5
    sys_scan_byte_6: int = 0            # byte 6
    cc_loop_count: float = 0.0          # bytes 7-14
    priority_scan_time: float = 0.0     # bytes 15-22

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"SystemScanOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            scan_type=raw[0],
            priority_scan=bool(raw[1]),
            tone_suppress=bool(raw[2]),
            sys_scan_byte_5=raw[5],
            sys_scan_byte_6=raw[6],
            cc_loop_count=struct.unpack_from('<d', raw, 7)[0],
            priority_scan_time=struct.unpack_from('<d', raw, 15)[0],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = self.scan_type
        buf[1] = int(self.priority_scan)
        buf[2] = int(self.tone_suppress)
        buf[5] = self.sys_scan_byte_5
        buf[6] = self.sys_scan_byte_6
        struct.pack_into('<d', buf, 7, self.cc_loop_count)
        struct.pack_into('<d', buf, 15, self.priority_scan_time)
        return bytes(buf)


@dataclass
class KeypadCtrlOpts:
    """CKeypadCtrlOpts — Keypad Control Options (20 data bytes).

    Contains keypad enable/disable booleans at bytes 3, 10, 11, 12.
    Remaining bytes are reserved.
    """
    DATA_SIZE = 20

    raw_data: bytes = b'\x00' * 20

    # Decoded fields
    keypad_opt_0: bool = False          # byte 3
    keypad_opt_1: bool = False          # byte 10
    keypad_opt_2: bool = False          # byte 11
    keypad_opt_3: bool = False          # byte 12

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"KeypadCtrlOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            keypad_opt_0=bool(raw[3]),
            keypad_opt_1=bool(raw[10]),
            keypad_opt_2=bool(raw[11]),
            keypad_opt_3=bool(raw[12]),
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[3] = int(self.keypad_opt_0)
        buf[10] = int(self.keypad_opt_1)
        buf[11] = int(self.keypad_opt_2)
        buf[12] = int(self.keypad_opt_3)
        return bytes(buf)


@dataclass
class MdcOpts:
    """CMdcOpts — MDC-1200 Options (24 data bytes).

    Contains MDC encode/decode trigger settings, pretime values,
    emergency settings, and enhanced ID parameters.
    """
    DATA_SIZE = 24

    raw_data: bytes = b'\x00' * 24

    # Decoded fields
    mdc_encode_trigger: int = 0         # byte 2 (enum)
    send_preamble_during_pretime: bool = False  # byte 4
    mdc_emergency_enable: bool = False  # byte 6
    system_pretime: int = 0             # bytes 7-8, uint16 LE
    interpacket_delay: int = 0          # bytes 9-10, uint16 LE
    mdc_bool_12: bool = False           # byte 12
    mdc_emergency_ack_tone: bool = False  # byte 13
    mdc_hang_time: int = 0              # byte 14
    enhanced_id_encode_trigger: int = 0  # byte 15 (enum)
    enhanced_id_system_pretime: int = 0  # bytes 17-18, uint16 LE
    enhanced_id_hang_time: int = 0      # byte 19
    emergency_tone_volume: int = 0      # byte 20
    emergency_max_tx_power: bool = False  # byte 21
    enhanced_emergency_ack_tone: bool = False  # byte 22
    alternate_alert_tone: bool = False  # byte 23

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"MdcOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            mdc_encode_trigger=raw[2],
            send_preamble_during_pretime=bool(raw[4]),
            mdc_emergency_enable=bool(raw[6]),
            system_pretime=struct.unpack_from('<H', raw, 7)[0],
            interpacket_delay=struct.unpack_from('<H', raw, 9)[0],
            mdc_bool_12=bool(raw[12]),
            mdc_emergency_ack_tone=bool(raw[13]),
            mdc_hang_time=raw[14],
            enhanced_id_encode_trigger=raw[15],
            enhanced_id_system_pretime=struct.unpack_from('<H', raw, 17)[0],
            enhanced_id_hang_time=raw[19],
            emergency_tone_volume=raw[20],
            emergency_max_tx_power=bool(raw[21]),
            enhanced_emergency_ack_tone=bool(raw[22]),
            alternate_alert_tone=bool(raw[23]),
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[2] = self.mdc_encode_trigger
        buf[4] = int(self.send_preamble_during_pretime)
        buf[6] = int(self.mdc_emergency_enable)
        struct.pack_into('<H', buf, 7, self.system_pretime)
        struct.pack_into('<H', buf, 9, self.interpacket_delay)
        buf[12] = int(self.mdc_bool_12)
        buf[13] = int(self.mdc_emergency_ack_tone)
        buf[14] = self.mdc_hang_time
        buf[15] = self.enhanced_id_encode_trigger
        struct.pack_into('<H', buf, 17, self.enhanced_id_system_pretime)
        buf[19] = self.enhanced_id_hang_time
        buf[20] = self.emergency_tone_volume
        buf[21] = int(self.emergency_max_tx_power)
        buf[22] = int(self.enhanced_emergency_ack_tone)
        buf[23] = int(self.alternate_alert_tone)
        return bytes(buf)


@dataclass
class VoiceAnnunciation:
    """CVoiceAnnunciation — Voice Annunciation Options (12 data bytes).

    Contains VA enable/disable flags, verbose playback, power-on setting,
    and volume min/max parameters.
    """
    DATA_SIZE = 12

    raw_data: bytes = b'\x00' * 12

    # Decoded fields
    enable_voice_annunciation: bool = False  # byte 0
    enable_verbose_playback: bool = False    # byte 1
    power_on: bool = False                   # byte 2
    minimum_volume: int = 0                  # byte 3
    maximum_volume: int = 0                  # byte 4
    va_byte_5: int = 0                       # byte 5

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"VoiceAnnunciation needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            enable_voice_annunciation=bool(raw[0]),
            enable_verbose_playback=bool(raw[1]),
            power_on=bool(raw[2]),
            minimum_volume=raw[3],
            maximum_volume=raw[4],
            va_byte_5=raw[5],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = int(self.enable_voice_annunciation)
        buf[1] = int(self.enable_verbose_playback)
        buf[2] = int(self.power_on)
        buf[3] = self.minimum_volume
        buf[4] = self.maximum_volume
        buf[5] = self.va_byte_5
        return bytes(buf)


@dataclass
class MrkOpts:
    """CMrkOpts — MRK Options (16 data bytes).

    Contains MRK enable (byte 7) and a parameter at byte 12.
    Remaining bytes are reserved.
    """
    DATA_SIZE = 16

    raw_data: bytes = b'\x00' * 16

    # Decoded fields
    mrk_enable: bool = False            # byte 7
    mrk_byte_12: int = 0               # byte 12

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"MrkOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            mrk_enable=bool(raw[7]),
            mrk_byte_12=raw[12],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[7] = int(self.mrk_enable)
        buf[12] = self.mrk_byte_12
        return bytes(buf)


@dataclass
class IgnitionOpts:
    """CIgnitionOpts — Ignition Options (10 data bytes).

    Contains ignition timer at byte 7 (20/0x14 in reference file).
    Remaining bytes are reserved.
    """
    DATA_SIZE = 10

    raw_data: bytes = b'\x00' * 10

    # Decoded fields
    ignition_timer: int = 0             # byte 7

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"IgnitionOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            ignition_timer=raw[7],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[7] = self.ignition_timer
        return bytes(buf)


@dataclass
class DiagnosticOpts:
    """CDiagnosticOpts — Diagnostic Options (8 data bytes).

    Contains diagnostic mode booleans, baud rate, bits per char,
    stop bits, parity, and IP echo settings.
    """
    DATA_SIZE = 8

    raw_data: bytes = b'\x00' * 8

    # Decoded fields
    diagnostic_mode: bool = False       # byte 0
    system_diagnostic_mode: bool = False  # byte 1
    diag_baud_rate: int = 0             # byte 2
    diag_bits_per_char: int = 0         # byte 3
    diag_stop_bits: int = 0             # byte 4
    diag_parity: int = 0                # byte 5
    diag_byte_6: int = 0               # byte 6
    ip_echo: bool = False               # byte 7

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"DiagnosticOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            diagnostic_mode=bool(raw[0]),
            system_diagnostic_mode=bool(raw[1]),
            diag_baud_rate=raw[2],
            diag_bits_per_char=raw[3],
            diag_stop_bits=raw[4],
            diag_parity=raw[5],
            diag_byte_6=raw[6],
            ip_echo=bool(raw[7]),
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = int(self.diagnostic_mode)
        buf[1] = int(self.system_diagnostic_mode)
        buf[2] = self.diag_baud_rate
        buf[3] = self.diag_bits_per_char
        buf[4] = self.diag_stop_bits
        buf[5] = self.diag_parity
        buf[6] = self.diag_byte_6
        buf[7] = int(self.ip_echo)
        return bytes(buf)


@dataclass
class MmsOpts:
    """CMmsOpts — MMS Options (13 data bytes).

    Contains MMS retry count, parameters, and timeout values.
    Bytes 0-7 are reserved (all zero in reference file).
    """
    DATA_SIZE = 13

    raw_data: bytes = b'\x00' * 13

    # Decoded fields
    mms_retries: int = 0                # byte 8
    mms_param_1: int = 0               # byte 9
    mms_param_2: int = 0               # byte 11
    mms_timeout: int = 0               # byte 12

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"MmsOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            mms_retries=raw[8],
            mms_param_1=raw[9],
            mms_param_2=raw[11],
            mms_timeout=raw[12],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[8] = self.mms_retries
        buf[9] = self.mms_param_1
        buf[11] = self.mms_param_2
        buf[12] = self.mms_timeout
        return bytes(buf)


@dataclass
class SndcpOpts:
    """CSndcpOpts — SNDCP Options (8 data bytes).

    Contains holdoff timer (uint16 LE at offset 5) for sub-network
    dependent convergence protocol. Remaining bytes are reserved.
    """
    DATA_SIZE = 8

    raw_data: bytes = b'\x00' * 8

    # Decoded fields
    holdoff_timer_ms: int = 0           # bytes 5-6, uint16 LE

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"SndcpOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            holdoff_timer_ms=struct.unpack_from('<H', raw, 5)[0],
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        struct.pack_into('<H', buf, 5, self.holdoff_timer_ms)
        return bytes(buf)


@dataclass
class SecurityPolicy:
    """CSecurityPolicy — Security Policy Options (2 data bytes).

    Contains two booleans controlling key erasure behavior.
    """
    DATA_SIZE = 2

    raw_data: bytes = b'\x00' * 2

    # Decoded fields
    k_erasure_unit_disable: bool = False  # byte 0
    k_erasure_zeroize: bool = False       # byte 1

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"SecurityPolicy needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            k_erasure_unit_disable=bool(raw[0]),
            k_erasure_zeroize=bool(raw[1]),
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[0] = int(self.k_erasure_unit_disable)
        buf[1] = int(self.k_erasure_zeroize)
        return bytes(buf)


@dataclass
class StatusOpts:
    """CStatus — Status/Message Options (7 data bytes).

    Contains mode hang time, select time, transmit type enum,
    and P25 format flags.
    """
    DATA_SIZE = 7

    raw_data: bytes = b'\x00' * 7

    # Decoded fields
    mode_hang_time: int = 0             # byte 2
    select_time: int = 0               # byte 3
    transmit_type: int = 0             # byte 4 (enum)
    reset_on_system_change: bool = False  # byte 5
    p25_standard_status_format: bool = False  # byte 6

    @classmethod
    def parse(cls, data, offset=0):
        raw = bytes(data[offset:offset + cls.DATA_SIZE])
        if len(raw) < cls.DATA_SIZE:
            raise ValueError(f"StatusOpts needs {cls.DATA_SIZE} bytes, got {len(raw)}")
        return cls(
            raw_data=raw,
            mode_hang_time=raw[2],
            select_time=raw[3],
            transmit_type=raw[4],
            reset_on_system_change=bool(raw[5]),
            p25_standard_status_format=bool(raw[6]),
        ), offset + cls.DATA_SIZE

    def to_bytes(self):
        buf = bytearray(self.raw_data)
        buf[2] = self.mode_hang_time
        buf[3] = self.select_time
        buf[4] = self.transmit_type
        buf[5] = int(self.reset_on_system_change)
        buf[6] = int(self.p25_standard_status_format)
        return bytes(buf)
