"""Binary I/O edge case tests.

Exercises the low-level binary read/write functions with boundary
values: uint16/uint32 extremes, LPS strings at length 0/1/127/255,
frequencies at exact band edges, maximum-length names, and IDEN sets
with all 16 slots populated.
"""

import struct
import pytest

from quickprs.binary_io import (
    read_uint8, read_uint16_le, read_uint32_le, read_double_le,
    read_lps, read_bool, read_bytes,
    write_uint8, write_uint16_le, write_uint32_le, write_double_le,
    write_lps, write_bool,
    SECTION_MARKER, FILE_TERMINATOR,
    find_all_ffff,
)
from quickprs.record_types import (
    TrunkChannel, TrunkSet, ConvChannel, ConvSet,
    P25Group, P25GroupSet, IdenElement, IdenDataSet,
    ConvSystemConfig, build_class_header, parse_class_header,
)


# ─── uint8 read/write roundtrip ─────────────────────────────────────


class TestUint8:

    @pytest.mark.parametrize("val", [0, 1, 127, 128, 254, 255])
    def test_roundtrip(self, val):
        """uint8 roundtrips at boundary values."""
        data = write_uint8(val)
        assert len(data) == 1
        result, offset = read_uint8(data, 0)
        assert result == val
        assert offset == 1

    def test_zero(self):
        data = write_uint8(0)
        assert data == b'\x00'

    def test_max(self):
        data = write_uint8(255)
        assert data == b'\xff'


# ─── uint16 read/write roundtrip ────────────────────────────────────


class TestUint16:

    @pytest.mark.parametrize("val", [0, 1, 255, 256, 32767, 32768, 65534, 65535])
    def test_roundtrip(self, val):
        """uint16 LE roundtrips at boundary values."""
        data = write_uint16_le(val)
        assert len(data) == 2
        result, offset = read_uint16_le(data, 0)
        assert result == val
        assert offset == 2

    def test_endianness(self):
        """uint16 LE stores low byte first."""
        data = write_uint16_le(0x0102)
        assert data == b'\x02\x01'

    def test_zero(self):
        data = write_uint16_le(0)
        assert data == b'\x00\x00'

    def test_max(self):
        data = write_uint16_le(65535)
        assert data == b'\xff\xff'


# ─── uint32 read/write roundtrip ────────────────────────────────────


class TestUint32:

    @pytest.mark.parametrize("val", [
        0, 1, 255, 256, 65535, 65536,
        2147483647, 2147483648, 4294967294, 4294967295
    ])
    def test_roundtrip(self, val):
        """uint32 LE roundtrips at boundary values."""
        data = write_uint32_le(val)
        assert len(data) == 4
        result, offset = read_uint32_le(data, 0)
        assert result == val
        assert offset == 4

    def test_endianness(self):
        """uint32 LE stores bytes in little-endian order."""
        data = write_uint32_le(0x01020304)
        assert data == b'\x04\x03\x02\x01'

    def test_zero(self):
        data = write_uint32_le(0)
        assert data == b'\x00\x00\x00\x00'

    def test_max(self):
        data = write_uint32_le(0xFFFFFFFF)
        assert data == b'\xff\xff\xff\xff'


# ─── double read/write roundtrip ────────────────────────────────────


class TestDouble:

    @pytest.mark.parametrize("val", [
        0.0, 1.0, -1.0, 146.52, 851.0125, 870.0,
        136.0, 960.0,  # band boundaries
        0.001, 9999.9999,  # extreme values
    ])
    def test_roundtrip(self, val):
        """IEEE 754 double roundtrips correctly."""
        data = write_double_le(val)
        assert len(data) == 8
        result, offset = read_double_le(data, 0)
        assert result == val
        assert offset == 8

    def test_negative_zero(self):
        """Negative zero roundtrips."""
        data = write_double_le(-0.0)
        result, _ = read_double_le(data, 0)
        assert result == 0.0

    @pytest.mark.parametrize("freq", [
        30.0, 50.0, 136.0, 144.0, 148.0, 222.0, 225.0,
        420.0, 450.0, 462.5625, 806.0, 851.0, 870.0, 902.0, 928.0, 960.0,
    ])
    def test_frequency_band_boundaries(self, freq):
        """Frequencies at exact band boundaries roundtrip."""
        data = write_double_le(freq)
        result, _ = read_double_le(data, 0)
        assert abs(result - freq) < 1e-10


# ─── LPS string read/write roundtrip ────────────────────────────────


class TestLPS:

    def test_empty_string(self):
        """LPS with length 0."""
        data = write_lps("")
        assert len(data) == 1  # just the length byte
        assert data == b'\x00'
        result, offset = read_lps(data, 0)
        assert result == ""
        assert offset == 1

    def test_single_char(self):
        """LPS with length 1."""
        data = write_lps("A")
        assert len(data) == 2
        assert data == b'\x01A'
        result, offset = read_lps(data, 0)
        assert result == "A"
        assert offset == 2

    def test_length_127(self):
        """LPS with length 127 (below 0x80 boundary)."""
        s = "A" * 127
        data = write_lps(s)
        assert len(data) == 128
        assert data[0] == 127
        result, offset = read_lps(data, 0)
        assert result == s
        assert offset == 128

    def test_length_128(self):
        """LPS with length 128 (at 0x80 boundary)."""
        s = "B" * 128
        data = write_lps(s)
        assert len(data) == 129
        assert data[0] == 128
        result, offset = read_lps(data, 0)
        assert result == s

    def test_length_255(self):
        """LPS with maximum length 255."""
        s = "C" * 255
        data = write_lps(s)
        assert len(data) == 256
        assert data[0] == 255
        result, offset = read_lps(data, 0)
        assert result == s

    def test_length_256_raises(self):
        """LPS longer than 255 bytes raises ValueError."""
        s = "D" * 256
        with pytest.raises(ValueError, match="too long"):
            write_lps(s)

    @pytest.mark.parametrize("length", [0, 1, 2, 7, 8, 15, 16, 50, 100, 200, 255])
    def test_roundtrip_various_lengths(self, length):
        """LPS roundtrip for various string lengths."""
        s = "X" * length
        data = write_lps(s)
        result, _ = read_lps(data, 0)
        assert result == s

    def test_special_chars(self):
        """LPS with printable ASCII special characters."""
        s = "A-B.C_D"
        data = write_lps(s)
        result, _ = read_lps(data, 0)
        assert result == s

    def test_numbers_and_spaces(self):
        """LPS with numbers and spaces."""
        s = "CH 1 RX"
        data = write_lps(s)
        result, _ = read_lps(data, 0)
        assert result == s

    def test_non_ascii_replaced(self):
        """Non-ASCII characters are replaced during encoding."""
        # write_lps uses errors='replace' which converts non-ASCII to '?'
        s = "caf\xe9"  # 'cafe' with accented e
        data = write_lps(s)
        result, _ = read_lps(data, 0)
        assert len(result) == 4  # same length
        # First 3 chars should be intact
        assert result[:3] == "caf"

    def test_at_various_offsets(self):
        """LPS reads correctly at non-zero offsets."""
        prefix = b'\x00\x00\x00'
        s = "TEST"
        data = prefix + write_lps(s)
        result, offset = read_lps(data, 3)
        assert result == s
        assert offset == 3 + 5  # 3 prefix + 1 len + 4 chars


# ─── Boolean read/write ─────────────────────────────────────────────


class TestBool:

    def test_true(self):
        data = write_bool(True)
        assert data == b'\x01'
        result, offset = read_bool(data, 0)
        assert result is True
        assert offset == 1

    def test_false(self):
        data = write_bool(False)
        assert data == b'\x00'
        result, offset = read_bool(data, 0)
        assert result is False
        assert offset == 1


# ─── Section markers ────────────────────────────────────────────────


class TestMarkers:

    def test_section_marker(self):
        assert SECTION_MARKER == b'\xff\xff'

    def test_file_terminator(self):
        assert FILE_TERMINATOR == b'\xff\xff\xff\xff\x00\x01'

    def test_find_ffff_empty(self):
        """No markers in all-zeros data."""
        data = b'\x00' * 100
        assert find_all_ffff(data) == []

    def test_find_ffff_single(self):
        """Finds single marker."""
        data = b'\x00\x00\xff\xff\x00\x00'
        markers = find_all_ffff(data)
        assert 2 in markers

    def test_find_ffff_multiple(self):
        """Finds multiple non-overlapping markers."""
        data = b'\xff\xff\x00\x00\xff\xff'
        markers = find_all_ffff(data)
        assert 0 in markers
        assert 4 in markers

    def test_find_ffff_at_start(self):
        """Marker at position 0."""
        data = b'\xff\xff\x64\x00'
        markers = find_all_ffff(data)
        assert 0 in markers


# ─── Class header ────────────────────────────────────────────────────


class TestClassHeader:

    @pytest.mark.parametrize("class_name", [
        "CPersonality", "CTrunkSet", "CConvSet", "CConvChannel",
        "CP25GroupSet", "CP25Group", "CIdenDataSet", "CDefaultIdenElem",
        "CP25tWanOpts", "CP25TrkWan", "CType99Opts", "CT99",
    ])
    def test_header_roundtrip(self, class_name):
        """Class header roundtrips through build/parse."""
        header = build_class_header(class_name, 0x64, 0x00)
        assert header[:2] == SECTION_MARKER
        parsed_name, byte1, byte2, data_offset = parse_class_header(header, 0)
        assert parsed_name == class_name

    @pytest.mark.parametrize("byte1", [0x00, 0x64, 0x65, 0x6a, 0xFF])
    def test_header_byte1_variety(self, byte1):
        """Various byte1 values survive roundtrip."""
        header = build_class_header("CTest", byte1, 0x00)
        _, parsed_b1, _, _ = parse_class_header(header, 0)
        assert parsed_b1 == byte1

    @pytest.mark.parametrize("byte2", [0x00, 0x01, 0x80, 0xFF])
    def test_header_byte2_variety(self, byte2):
        """Various byte2 values survive roundtrip."""
        header = build_class_header("CTest", 0x64, byte2)
        _, _, parsed_b2, _ = parse_class_header(header, 0)
        assert parsed_b2 == byte2


# ─── TrunkChannel edge cases ────────────────────────────────────────


class TestTrunkChannelEdge:

    def test_record_size(self):
        """TrunkChannel is always 23 bytes."""
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0)
        data = ch.to_bytes()
        assert len(data) == TrunkChannel.RECORD_SIZE == 23

    def test_flags_preserved(self):
        """7-byte flags field is preserved through roundtrip."""
        custom_flags = b'\x01\x02\x03\x04\x05\x06\x07'
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0, flags=custom_flags)
        data = ch.to_bytes()
        parsed, _ = TrunkChannel.parse(data, 0)
        assert parsed.flags == custom_flags

    @pytest.mark.parametrize("flags", [
        b'\x00' * 7,
        b'\xff' * 7,
        b'\x01\x00\x00\x00\x00\x00\x00',
        b'\x00\x00\x00\x00\x00\x00\x01',
    ])
    def test_various_flags(self, flags):
        """Various flag byte patterns roundtrip."""
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0, flags=flags)
        data = ch.to_bytes()
        parsed, _ = TrunkChannel.parse(data, 0)
        assert parsed.flags == flags

    @pytest.mark.parametrize("freq", [
        0.0, 136.0, 400.0, 806.0, 851.0, 870.0, 935.0, 960.0, 9999.0
    ])
    def test_extreme_frequencies(self, freq):
        """Extreme frequency values roundtrip without error."""
        ch = TrunkChannel(tx_freq=freq, rx_freq=freq)
        data = ch.to_bytes()
        parsed, _ = TrunkChannel.parse(data, 0)
        assert abs(parsed.tx_freq - freq) < 1e-10
        assert abs(parsed.rx_freq - freq) < 1e-10


# ─── ConvChannel edge cases ─────────────────────────────────────────


class TestConvChannelEdge:

    def test_minimal_channel(self):
        """Minimal channel (short name, freq only) roundtrips."""
        ch = ConvChannel(short_name="A", tx_freq=146.52, rx_freq=146.52)
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.short_name == "A"
        assert abs(parsed.tx_freq - 146.52) < 1e-10

    def test_maximal_name(self):
        """8-char short name + 16-char long name roundtrip."""
        ch = ConvChannel(
            short_name="ABCDEFGH",
            tx_freq=146.52, rx_freq=146.52,
            long_name="ABCDEFGHIJKLMNOP",
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.short_name == "ABCDEFGH"
        assert parsed.long_name == "ABCDEFGHIJKLMNOP"

    def test_long_tones(self):
        """CTCSS tone strings roundtrip."""
        ch = ConvChannel(
            short_name="TONETEST",
            tx_freq=146.52, rx_freq=146.52,
            tx_tone="250.3", rx_tone="156.7",
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.tx_tone == "250.3"
        assert parsed.rx_tone == "156.7"

    def test_empty_tones(self):
        """Empty tone strings roundtrip."""
        ch = ConvChannel(
            short_name="NOTONE",
            tx_freq=146.52, rx_freq=146.52,
            tx_tone="", rx_tone="",
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.tx_tone == ""
        assert parsed.rx_tone == ""

    def test_byte_size_method(self):
        """byte_size matches actual to_bytes length."""
        ch = ConvChannel(
            short_name="TEST",
            tx_freq=146.52, rx_freq=146.52,
            tx_tone="100.0", rx_tone="100.0",
            long_name="Test Channel",
        )
        data = ch.to_bytes()
        assert len(data) == ch.byte_size()

    @pytest.mark.parametrize("power", [0, 1, 2])
    def test_power_level(self, power):
        """Power level values in pre_long_name roundtrip."""
        pre = bytearray(10)
        pre[0] = power
        ch = ConvChannel(
            short_name="POWER",
            tx_freq=146.52, rx_freq=146.52,
            pre_long_name=bytes(pre),
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.pre_long_name[0] == power


# ─── P25Group edge cases ────────────────────────────────────────────


class TestP25GroupEdge:

    def test_min_group_id(self):
        """Group ID 0 roundtrips."""
        g = P25Group(group_name="ZERO", group_id=0, long_name="Zero")
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.group_id == 0

    def test_max_group_id(self):
        """Group ID 65535 (uint16 max) roundtrips."""
        g = P25Group(group_name="MAXID", group_id=65535, long_name="Maximum")
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.group_id == 65535

    def test_all_bools_true(self):
        """All 7 boolean flags set to True."""
        g = P25Group(
            group_name="ALLTRUE", group_id=100, long_name="All True",
            rx=True, calls=True, alert=True, scan_list_member=True,
            scan=True, backlight=True, tx=True,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.rx is True
        assert parsed.calls is True
        assert parsed.alert is True
        assert parsed.scan_list_member is True
        assert parsed.scan is True
        assert parsed.backlight is True
        assert parsed.tx is True

    def test_all_bools_false(self):
        """All 7 boolean flags set to False."""
        g = P25Group(
            group_name="ALLOFF", group_id=100, long_name="All False",
            rx=False, calls=False, alert=False, scan_list_member=False,
            scan=False, backlight=False, tx=False,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.rx is False
        assert parsed.calls is False
        assert parsed.alert is False
        assert parsed.scan_list_member is False
        assert parsed.scan is False
        assert parsed.backlight is False
        assert parsed.tx is False

    def test_encryption_fields(self):
        """Encryption-related fields roundtrip."""
        g = P25Group(
            group_name="ENCRYPT", group_id=100, long_name="Encrypted",
            key_id=12345, encrypted=True, use_group_id=True,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.key_id == 12345
        assert parsed.encrypted is True
        assert parsed.use_group_id is True

    def test_priority_tg(self):
        """Priority talkgroup flag roundtrips."""
        g = P25Group(
            group_name="PRIO", group_id=100, long_name="Priority",
            priority_tg=True,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.priority_tg is True

    def test_audio_fields(self):
        """Audio file/profile fields roundtrip."""
        g = P25Group(
            group_name="AUDIO", group_id=100, long_name="Audio",
            audio_file=42, audio_profile=0x0A,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.audio_file == 42
        assert parsed.audio_profile == 0x0A

    def test_tg_type(self):
        """Talkgroup type field roundtrips."""
        g = P25Group(
            group_name="TYPE", group_id=100, long_name="Type",
            tg_type=2,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.tg_type == 2

    def test_suppress_flag(self):
        """Suppress flag roundtrips."""
        g = P25Group(
            group_name="SUPP", group_id=100, long_name="Suppress",
            suppress=True,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.suppress is True

    def test_byte_size_method(self):
        """byte_size matches actual to_bytes length."""
        g = P25Group(
            group_name="SIZE", group_id=100,
            long_name="Size Test Group",
        )
        data = g.to_bytes()
        assert len(data) == g.byte_size()

    @pytest.mark.parametrize("name_len", [1, 2, 4, 8])
    @pytest.mark.parametrize("long_len", [0, 1, 8, 16])
    def test_various_name_lengths(self, name_len, long_len):
        """Various name length combinations."""
        g = P25Group(
            group_name="X" * name_len,
            group_id=100,
            long_name="Y" * long_len if long_len > 0 else "",
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.group_name == "X" * name_len
        if long_len > 0:
            assert parsed.long_name == "Y" * long_len
        else:
            assert parsed.long_name == ""


# ─── IdenElement edge cases ─────────────────────────────────────────


class TestIdenElementEdge:

    def test_record_size(self):
        """IdenElement is always 15 bytes."""
        elem = IdenElement()
        data = elem.to_bytes()
        assert len(data) == IdenElement.RECORD_SIZE == 15

    def test_empty_element(self):
        """Empty/default element is_empty()."""
        elem = IdenElement()
        assert elem.is_empty()

    def test_non_empty_element(self):
        """Non-default element is not empty."""
        elem = IdenElement(base_freq_hz=851000000)
        assert not elem.is_empty()

    @pytest.mark.parametrize("base_freq_hz", [
        0, 136000000, 400000000, 806000000, 851000000,
        870000000, 935000000, 960000000, 4294967295,
    ])
    def test_base_freq_boundary(self, base_freq_hz):
        """Base frequency at uint32 boundary values roundtrips."""
        elem = IdenElement(base_freq_hz=base_freq_hz)
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert parsed.base_freq_hz == base_freq_hz

    @pytest.mark.parametrize("spacing", [6250, 12500, 25000, 50000])
    def test_channel_spacing(self, spacing):
        """Various channel spacings roundtrip."""
        elem = IdenElement(chan_spacing_hz=spacing)
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert parsed.chan_spacing_hz == spacing

    @pytest.mark.parametrize("bw", [6250, 12500, 25000])
    def test_bandwidth(self, bw):
        """Various bandwidths roundtrip."""
        elem = IdenElement(bandwidth_hz=bw)
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert parsed.bandwidth_hz == bw

    def test_tdma_iden_type(self):
        """TDMA iden_type (1) roundtrips."""
        elem = IdenElement(iden_type=1)
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert parsed.iden_type == 1

    def test_fdma_iden_type(self):
        """FDMA iden_type (0) roundtrips."""
        elem = IdenElement(iden_type=0)
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert parsed.iden_type == 0

    def test_tx_offset_negative(self):
        """Negative TX offset (-45 MHz for 800 band) roundtrips."""
        elem = IdenElement()
        elem.tx_offset_mhz = -45.0
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert abs(parsed.tx_offset_mhz - (-45.0)) < 0.01

    def test_tx_offset_positive(self):
        """Positive TX offset (+30 MHz) roundtrips."""
        elem = IdenElement()
        elem.tx_offset_mhz = 30.0
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert abs(parsed.tx_offset_mhz - 30.0) < 0.01

    def test_tx_offset_zero(self):
        """Zero TX offset roundtrips."""
        elem = IdenElement()
        elem.tx_offset_mhz = 0.0
        data = elem.to_bytes()
        parsed, _ = IdenElement.parse(data, 0)
        assert abs(parsed.tx_offset_mhz) < 0.001


# ─── IdenDataSet with all 16 slots ──────────────────────────────────


class TestIdenDataSetFull:

    def test_all_16_slots_populated(self):
        """IDEN set with all 16 slots filled serializes/parses."""
        elements = []
        for i in range(16):
            elem = IdenElement(
                base_freq_hz=851000000 + i * 1000000,
                chan_spacing_hz=12500,
                bandwidth_hz=6250,
                iden_type=i % 2,  # alternate FDMA/TDMA
            )
            elem.tx_offset_mhz = -45.0 + i
            elements.append(elem)

        iset = IdenDataSet(name="FULL16", elements=elements)
        data = iset.elements_to_bytes()
        assert len(data) > 0
        # 16 elements * 15 bytes + 15 separators * 2 bytes
        expected_size = 16 * 15 + 15 * 2
        assert len(data) == expected_size

    def test_mixed_empty_and_populated(self):
        """IDEN set with some empty, some populated elements."""
        elements = []
        for i in range(16):
            if i < 4:
                elements.append(IdenElement(base_freq_hz=851000000 + i * 1000000))
            else:
                elements.append(IdenElement())  # empty

        iset = IdenDataSet(name="MIXED", elements=elements)
        data = iset.elements_to_bytes()
        assert len(data) > 0

    def test_all_empty_slots(self):
        """IDEN set with 16 empty slots."""
        elements = [IdenElement() for _ in range(16)]
        iset = IdenDataSet(name="EMPTY16", elements=elements)
        data = iset.elements_to_bytes()
        # All zeros (empty elements) + separators
        expected_size = 16 * 15 + 15 * 2
        assert len(data) == expected_size

    def test_padding_to_16(self):
        """IDEN set with fewer than 16 elements pads to 16."""
        elements = [IdenElement(base_freq_hz=851000000)]
        iset = IdenDataSet(name="PAD", elements=elements)
        data = iset.elements_to_bytes()
        # Should still produce 16 elements worth of data
        expected_size = 16 * 15 + 15 * 2
        assert len(data) == expected_size


# ─── ConvSet metadata ───────────────────────────────────────────────


class TestConvSetMetadata:

    def test_metadata_size(self):
        """ConvSet metadata is always 60 bytes."""
        cs = ConvSet(name="TEST", channels=[])
        assert len(cs.metadata) == ConvSet.METADATA_SIZE == 60

    def test_metadata_roundtrip(self):
        """Setting metadata from bytes preserves all fields."""
        cs = ConvSet(name="TEST", channels=[])
        original = cs.metadata
        cs2 = ConvSet(name="TEST", channels=[])
        cs2.metadata = original
        assert cs2.metadata == original

    @pytest.mark.parametrize("has_limits", [True, False])
    def test_band_limits_flag(self, has_limits):
        """has_band_limits flag affects band limit doubles."""
        cs = ConvSet(
            name="LIMITS",
            channels=[],
            has_band_limits=1 if has_limits else 0,
            tx_min=136.0 if has_limits else 0.0,
            tx_max=870.0 if has_limits else 0.0,
            rx_min=136.0 if has_limits else 0.0,
            rx_max=870.0 if has_limits else 0.0,
        )
        meta = cs.metadata
        assert meta[1] == (1 if has_limits else 0)

    def test_metadata_invalid_length_raises(self):
        """Setting metadata with wrong length raises ValueError."""
        cs = ConvSet(name="TEST", channels=[])
        with pytest.raises(ValueError, match="60 bytes"):
            cs.metadata = b'\x00' * 59  # too short


# ─── P25GroupSet metadata ────────────────────────────────────────────


class TestP25GroupSetMetadata:

    def test_scan_list_size(self):
        """Default scan_list_size is 9."""
        gs = P25GroupSet(name="TEST")
        assert gs.scan_list_size == 0x09

    def test_system_id(self):
        """system_id defaults to 0."""
        gs = P25GroupSet(name="TEST")
        assert gs.system_id == 0

    @pytest.mark.parametrize("sys_id", [0, 1, 892, 65535])
    def test_system_id_values(self, sys_id):
        """Various system_id values can be set."""
        gs = P25GroupSet(name="TEST", system_id=sys_id)
        assert gs.system_id == sys_id


# ─── ConvSystemConfig ───────────────────────────────────────────────


class TestConvSystemConfig:

    def test_basic_config(self):
        """Basic config creation works."""
        cfg = ConvSystemConfig(
            system_name="MYSYS",
            long_name="My System",
            conv_set_name="MYSET",
        )
        assert cfg.system_name == "MYSYS"
        assert cfg.long_name == "My System"
        assert cfg.conv_set_name == "MYSET"

    def test_header_section_builds(self):
        """Header section builds without error."""
        cfg = ConvSystemConfig(
            system_name="TEST",
            long_name="Test",
            conv_set_name="TEST",
        )
        header = cfg.build_header_section()
        assert len(header) > 0
        # Should start with ffff marker
        assert header[:2] == SECTION_MARKER

    def test_data_section_builds(self):
        """Data section builds without error."""
        cfg = ConvSystemConfig(
            system_name="TEST",
            long_name="Test",
            conv_set_name="TEST",
        )
        data = cfg.build_data_section()
        assert len(data) > 0

    @pytest.mark.parametrize("name", ["A", "ABCDEFGH", "12345678"])
    def test_various_system_names(self, name):
        """Various system names produce valid output."""
        cfg = ConvSystemConfig(
            system_name=name,
            long_name=name,
            conv_set_name=name,
        )
        header = cfg.build_header_section()
        assert len(header) > 0

    def test_empty_long_name(self):
        """Empty long_name is valid."""
        cfg = ConvSystemConfig(
            system_name="SYS",
            long_name="",
            conv_set_name="SET",
        )
        data = cfg.build_data_section()
        assert len(data) > 0


# ─── Compound binary sequences ──────────────────────────────────────


class TestCompoundBinary:
    """Test reading multiple values from a compound buffer."""

    def test_read_sequential_fields(self):
        """Multiple fields packed together read correctly."""
        data = (
            write_uint16_le(1234) +
            write_double_le(146.52) +
            write_lps("TEST") +
            write_bool(True) +
            write_uint32_le(99999)
        )
        offset = 0

        val1, offset = read_uint16_le(data, offset)
        assert val1 == 1234

        freq, offset = read_double_le(data, offset)
        assert abs(freq - 146.52) < 1e-10

        name, offset = read_lps(data, offset)
        assert name == "TEST"

        flag, offset = read_bool(data, offset)
        assert flag is True

        val2, offset = read_uint32_le(data, offset)
        assert val2 == 99999

        assert offset == len(data)

    def test_read_at_offsets(self):
        """Reading at various offsets within a buffer."""
        # Build a buffer with padding between fields
        buf = bytearray(100)
        struct.pack_into('<H', buf, 10, 42)
        struct.pack_into('<I', buf, 20, 100000)
        struct.pack_into('<d', buf, 30, 462.5625)

        val1, _ = read_uint16_le(bytes(buf), 10)
        assert val1 == 42

        val2, _ = read_uint32_le(bytes(buf), 20)
        assert val2 == 100000

        freq, _ = read_double_le(bytes(buf), 30)
        assert abs(freq - 462.5625) < 1e-10

    def test_read_bytes_function(self):
        """read_bytes extracts exact byte range."""
        data = b'\x00\x01\x02\x03\x04\x05\x06\x07'
        chunk, offset = read_bytes(data, 2, 4)
        assert chunk == b'\x02\x03\x04\x05'
        assert offset == 6


# ─── Frequency precision ────────────────────────────────────────────


class TestFrequencyPrecision:
    """Verify that frequency values maintain precision through encoding."""

    @pytest.mark.parametrize("freq", [
        462.5625, 462.5875, 462.6125, 462.6375,
        462.6625, 462.6875, 462.7125,
        467.5625, 467.5875, 467.6125, 467.6375,
        155.7525, 155.7675, 155.7825, 155.7975,
        769.24375, 769.74375, 770.24375,
    ])
    def test_channel_freq_precision(self, freq):
        """Channel frequencies with 4-5 decimal places maintain precision."""
        data = write_double_le(freq)
        result, _ = read_double_le(data, 0)
        assert abs(result - freq) < 1e-10, \
            f"Frequency {freq} lost precision: got {result}"

    @pytest.mark.parametrize("freq", [
        462.5625, 462.5875, 462.6125, 462.6375,
    ])
    def test_conv_channel_freq_precision(self, freq):
        """ConvChannel preserves frequency precision through parse cycle."""
        ch = ConvChannel(short_name="PREC", tx_freq=freq, rx_freq=freq)
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert abs(parsed.tx_freq - freq) < 1e-10
        assert abs(parsed.rx_freq - freq) < 1e-10

    @pytest.mark.parametrize("freq", [
        851.0125, 851.0375, 851.0625, 851.0875,
    ])
    def test_trunk_channel_freq_precision(self, freq):
        """TrunkChannel preserves frequency precision through parse cycle."""
        ch = TrunkChannel(tx_freq=freq, rx_freq=freq)
        data = ch.to_bytes()
        parsed, _ = TrunkChannel.parse(data, 0)
        assert abs(parsed.tx_freq - freq) < 1e-10
        assert abs(parsed.rx_freq - freq) < 1e-10


# ─── Multi-record binary concatenation ──────────────────────────────


class TestMultiRecordConcatenation:
    """Test reading multiple records packed together in a buffer."""

    def test_sequential_trunk_channels(self):
        """Multiple TrunkChannels packed together parse correctly."""
        channels = [
            TrunkChannel(tx_freq=851.0 + i * 0.025, rx_freq=806.0 + i * 0.025)
            for i in range(5)
        ]
        data = b''.join(ch.to_bytes() for ch in channels)
        offset = 0
        for i in range(5):
            parsed, offset = TrunkChannel.parse(data, offset)
            assert abs(parsed.tx_freq - (851.0 + i * 0.025)) < 1e-10
            assert abs(parsed.rx_freq - (806.0 + i * 0.025)) < 1e-10
        assert offset == len(data)

    def test_sequential_p25_groups(self):
        """Multiple P25Groups packed together parse correctly."""
        groups = [
            P25Group(
                group_name=f"TG{i:04d}",
                group_id=i * 100,
                long_name=f"Group {i}",
            )
            for i in range(5)
        ]
        data = b''.join(g.to_bytes() for g in groups)
        offset = 0
        for i in range(5):
            parsed, offset = P25Group.parse(data, offset)
            assert parsed.group_id == i * 100
            assert parsed.group_name == f"TG{i:04d}"
        assert offset == len(data)

    def test_sequential_iden_elements(self):
        """Multiple IdenElements packed together parse correctly."""
        elements = [
            IdenElement(base_freq_hz=851000000 + i * 1000000)
            for i in range(16)
        ]
        data = b''.join(elem.to_bytes() for elem in elements)
        offset = 0
        for i in range(16):
            parsed, offset = IdenElement.parse(data, offset)
            assert parsed.base_freq_hz == 851000000 + i * 1000000
        assert offset == len(data)

    def test_mixed_types_in_buffer(self):
        """Mixed uint types read correctly from same buffer."""
        buf = (
            write_uint8(42) +
            write_uint16_le(1000) +
            write_uint32_le(100000) +
            write_double_le(146.52) +
            write_lps("HELLO") +
            write_bool(True) +
            write_uint8(255)
        )
        off = 0
        v1, off = read_uint8(buf, off)
        assert v1 == 42
        v2, off = read_uint16_le(buf, off)
        assert v2 == 1000
        v3, off = read_uint32_le(buf, off)
        assert v3 == 100000
        v4, off = read_double_le(buf, off)
        assert abs(v4 - 146.52) < 1e-10
        v5, off = read_lps(buf, off)
        assert v5 == "HELLO"
        v6, off = read_bool(buf, off)
        assert v6 is True
        v7, off = read_uint8(buf, off)
        assert v7 == 255
        assert off == len(buf)


# ─── P25Group middle/tail raw byte tests ────────────────────────────


class TestP25GroupMiddleTail:
    """Detailed tests for P25Group middle and tail byte blocks."""

    def test_middle_all_zeros(self):
        """All-zero middle block has default field values."""
        g = P25Group(group_name="ZERO", group_id=1, long_name="Z")
        g.middle = b'\x00' * 12
        assert g.audio_file == 0
        assert g.audio_profile == 0
        assert g.tg_index == 0
        assert g.key_id == 0
        assert g.priority_tg is False

    def test_middle_max_values(self):
        """Middle block with maximum field values."""
        mid = bytearray(12)
        struct.pack_into('<H', mid, 0, 65535)    # audio_file
        mid[2] = 255                              # audio_profile
        struct.pack_into('<H', mid, 3, 65535)    # tg_index
        struct.pack_into('<I', mid, 5, 0xFFFFFFFF)  # key_id
        mid[11] = 1                               # priority_tg
        g = P25Group(group_name="MAX", group_id=1, long_name="M")
        g.middle = bytes(mid)
        assert g.audio_file == 65535
        assert g.audio_profile == 255
        assert g.tg_index == 65535
        assert g.key_id == 0xFFFFFFFF
        assert g.priority_tg is True
        # Roundtrip
        assert g.middle == bytes(mid)

    def test_tail_all_true(self):
        """Tail block with all flags set."""
        g = P25Group(group_name="TAIL", group_id=1, long_name="T")
        g.tail = bytes([1, 1, 255, 1])
        assert g.use_group_id is True
        assert g.encrypted is True
        assert g.tg_type == 255
        assert g.suppress is True

    def test_tail_roundtrip(self):
        """Tail field values survive roundtrip."""
        g = P25Group(
            group_name="RT", group_id=1, long_name="R",
            use_group_id=True, encrypted=True, tg_type=3, suppress=True,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.use_group_id is True
        assert parsed.encrypted is True
        assert parsed.tg_type == 3
        assert parsed.suppress is True

    @pytest.mark.parametrize("key_id", [0, 1, 255, 65535, 0xFFFFFFFF])
    def test_encryption_key_roundtrip(self, key_id):
        """Encryption key_id (uint32) roundtrips at boundary values."""
        g = P25Group(
            group_name="KEY", group_id=1, long_name="K",
            key_id=key_id,
        )
        data = g.to_bytes()
        parsed, _ = P25Group.parse(data, 0)
        assert parsed.key_id == key_id


# ─── ConvSet metadata deep tests ────────────────────────────────────


class TestConvSetMetadataDeep:
    """Deeper tests for ConvSet 60-byte metadata block."""

    def test_default_metadata_values(self):
        """Default metadata has expected byte patterns."""
        cs = ConvSet(name="TEST", channels=[])
        meta = cs.metadata
        assert meta[0] == 0x01  # config_flag
        assert meta[1] == 0x00  # no band limits
        assert meta[38] == 0x01  # config pair byte 1
        assert meta[39] == 0x01  # config pair byte 2

    def test_band_limits_in_metadata(self):
        """Band limit doubles appear at correct offsets in metadata."""
        cs = ConvSet(
            name="BAND", channels=[],
            has_band_limits=1,
            tx_min=136.0, rx_min=136.0,
            tx_max=870.0, rx_max=870.0,
        )
        meta = cs.metadata
        assert meta[1] == 0x01
        # Read doubles from known offsets
        tx_min = struct.unpack_from('<d', meta, 2)[0]
        rx_min = struct.unpack_from('<d', meta, 10)[0]
        tx_max = struct.unpack_from('<d', meta, 18)[0]
        rx_max = struct.unpack_from('<d', meta, 26)[0]
        assert abs(tx_min - 136.0) < 1e-10
        assert abs(rx_min - 136.0) < 1e-10
        assert abs(tx_max - 870.0) < 1e-10
        assert abs(rx_max - 870.0) < 1e-10

    def test_metadata_setter_preserves_reserved(self):
        """Setting metadata from bytes preserves reserved bytes."""
        cs = ConvSet(name="RES", channels=[])
        original = cs.metadata
        # Modify and set back
        cs2 = ConvSet(name="RES", channels=[])
        cs2.metadata = original
        assert cs2.metadata == original

    @pytest.mark.parametrize("config_flag", [0x00, 0x01, 0x02, 0xFF])
    def test_config_flag_variety(self, config_flag):
        """Various config_flag values serialize correctly."""
        cs = ConvSet(name="CFG", channels=[], config_flag=config_flag)
        meta = cs.metadata
        assert meta[0] == config_flag


# ─── P25GroupSet metadata deep tests ─────────────────────────────────


class TestP25GroupSetMetadataDeep:
    """Deeper tests for P25GroupSet 16-byte metadata block."""

    @pytest.mark.parametrize("scan_size", [0, 1, 9, 15, 255])
    def test_scan_list_size_values(self, scan_size):
        """Various scan_list_size values."""
        gs = P25GroupSet(name="SCAN", scan_list_size=scan_size)
        assert gs.scan_list_size == scan_size

    @pytest.mark.parametrize("sys_id", [0, 1, 100, 892, 1000, 65535])
    def test_system_id_boundary(self, sys_id):
        """System ID at various uint16 boundary values."""
        gs = P25GroupSet(name="SYS", system_id=sys_id)
        assert gs.system_id == sys_id

    def test_empty_groups_list(self):
        """P25GroupSet with no groups."""
        gs = P25GroupSet(name="EMPTY", groups=[])
        assert len(gs.groups) == 0

    def test_single_group(self):
        """P25GroupSet with exactly one group."""
        g = P25Group(group_name="ONLY", group_id=1, long_name="Only One")
        gs = P25GroupSet(name="ONE", groups=[g])
        assert len(gs.groups) == 1


# ─── ConvChannel pre_long_name and trailer ───────────────────────────


class TestConvChannelBlocks:
    """Test ConvChannel pre_long_name and trailer byte blocks."""

    def test_default_pre_long_name(self):
        """Default pre_long_name is 10 bytes of zeros."""
        ch = ConvChannel(short_name="DEF", tx_freq=146.52, rx_freq=146.52)
        assert len(ch.pre_long_name) == 10

    def test_default_trailer(self):
        """Default trailer is 7 bytes of zeros."""
        ch = ConvChannel(short_name="DEF", tx_freq=146.52, rx_freq=146.52)
        assert len(ch.trailer) == 7

    def test_pre_long_name_roundtrip(self):
        """Custom pre_long_name survives roundtrip."""
        pre = bytes([2, 12, 0, 0, 0, 0, 0, 0, 0, 0])
        ch = ConvChannel(
            short_name="PLN", tx_freq=146.52, rx_freq=146.52,
            pre_long_name=pre,
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.pre_long_name == pre

    def test_trailer_roundtrip(self):
        """Custom trailer survives roundtrip."""
        trailer = bytes([0, 0, 2, 0, 0, 0, 0])
        ch = ConvChannel(
            short_name="TRL", tx_freq=146.52, rx_freq=146.52,
            trailer=trailer,
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.trailer == trailer

    @pytest.mark.parametrize("squelch", [0, 6, 12, 15, 255])
    def test_squelch_threshold_values(self, squelch):
        """Squelch threshold (pre_long_name byte 1) roundtrips."""
        pre = bytearray(10)
        pre[1] = squelch
        ch = ConvChannel(
            short_name="SQ", tx_freq=146.52, rx_freq=146.52,
            pre_long_name=bytes(pre),
        )
        data = ch.to_bytes()
        parsed, _ = ConvChannel.parse(data, 0)
        assert parsed.pre_long_name[1] == squelch


# ─── find_all_ffff detailed ─────────────────────────────────────────


class TestFindAllFFFFDetailed:
    """Detailed tests for ffff marker finder."""

    def test_no_false_positive_fffe(self):
        """0xFFFE is not a marker."""
        data = b'\xff\xfe\x00\x00'
        markers = find_all_ffff(data)
        assert len(markers) == 0

    def test_no_false_positive_00ff(self):
        """0x00FF is not a marker."""
        data = b'\x00\xff\x00\x00'
        markers = find_all_ffff(data)
        assert len(markers) == 0

    def test_triple_ff(self):
        """0xFFFFFF contains marker at pos 0, next at pos 2."""
        data = b'\xff\xff\xff\x00'
        markers = find_all_ffff(data)
        assert 0 in markers

    def test_marker_at_end(self):
        """Marker at last possible position."""
        data = b'\x00\x00\xff\xff'
        markers = find_all_ffff(data)
        assert 2 in markers

    def test_many_markers(self):
        """Data with many markers spaced apart."""
        parts = []
        for i in range(10):
            parts.append(b'\xff\xff')
            parts.append(b'\x64\x00\x04\x00CTest')
        data = b''.join(parts)
        markers = find_all_ffff(data)
        assert len(markers) >= 10

    def test_single_byte_data(self):
        """Single byte: too short for any marker."""
        data = b'\xff'
        markers = find_all_ffff(data)
        assert len(markers) == 0

    def test_empty_data(self):
        """Empty data: no markers."""
        data = b''
        markers = find_all_ffff(data)
        assert len(markers) == 0
