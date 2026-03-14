"""Tests for the 16 remaining option section dataclasses in record_types.py.

Verifies parse/build roundtrip for:
  CVgOpts, CNetworkOpts, CGEstarOpts, CConvScanOpts, CProSoundOpts,
  CSystemScanOpts, CKeypadCtrlOpts, CMdcOpts, CVoiceAnnunciation,
  CMrkOpts, CIgnitionOpts, CDiagnosticOpts, CMmsOpts, CSndcpOpts,
  CSecurityPolicy, CStatus

Each test class:
1. Parses the section from PAWSOVERMAWS.PRS
2. Verifies decoded field values match known values
3. Verifies to_bytes() produces byte-identical output
4. Tests synthetic construction and roundtrip
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.option_maps import extract_section_data
from quickprs.record_types import (
    VgOpts, NetworkOpts, GEstarOpts, ConvScanOpts, ProSoundOpts,
    SystemScanOpts, KeypadCtrlOpts, MdcOpts, VoiceAnnunciation,
    MrkOpts, IgnitionOpts, DiagnosticOpts, MmsOpts, SndcpOpts,
    SecurityPolicy, StatusOpts,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWSOVERMAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _get_section_data(class_name):
    """Helper: extract data payload from a named section in PAWSOVERMAWS."""
    prs = parse_prs(PAWSOVERMAWS)
    sec = prs.get_section_by_class(class_name)
    assert sec is not None, f"Section {class_name} not found"
    return extract_section_data(sec)


# ─── CVgOpts ──────────────────────────────────────────────────────────

class TestVgOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CVgOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == VgOpts.DATA_SIZE == 54

    def test_parse_polarity(self, paws_data):
        obj, _ = VgOpts.parse(paws_data)
        assert obj.tx_data_polarity == 0
        assert obj.rx_data_polarity == 0

    def test_parse_encryption(self, paws_data):
        obj, _ = VgOpts.parse(paws_data)
        assert obj.max_key_bank == 0
        assert obj.encryption_key_size == 16  # 0x10
        assert obj.encryption_mode == 1

    def test_roundtrip(self, paws_data):
        obj, _ = VgOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(54)
        raw[0] = 1
        raw[1] = 1
        raw[2] = 4
        raw[5] = 0x20
        raw[24] = 2
        raw = bytes(raw)
        obj, _ = VgOpts.parse(raw)
        assert obj.tx_data_polarity == 1
        assert obj.rx_data_polarity == 1
        assert obj.max_key_bank == 4
        assert obj.encryption_key_size == 0x20
        assert obj.encryption_mode == 2
        assert obj.to_bytes() == raw

    def test_parse_offset(self, paws_data):
        padded = b'\xAA' * 5 + paws_data
        obj, end = VgOpts.parse(padded, 5)
        assert end == 5 + 54
        assert obj.to_bytes() == paws_data

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="54 bytes"):
            VgOpts.parse(b'\x00' * 10)


# ─── CNetworkOpts ────────────────────────────────────────────────────

class TestNetworkOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CNetworkOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == NetworkOpts.DATA_SIZE == 38

    def test_parse_booleans(self, paws_data):
        obj, _ = NetworkOpts.parse(paws_data)
        assert obj.network_byte_5 is True
        assert obj.network_byte_13 is True

    def test_parse_params(self, paws_data):
        obj, _ = NetworkOpts.parse(paws_data)
        assert obj.network_byte_10 == 2
        assert obj.network_byte_15 == 5

    def test_parse_timers(self, paws_data):
        obj, _ = NetworkOpts.parse(paws_data)
        assert obj.network_timer_1 == 30.0
        assert obj.network_timer_2 == 2.0

    def test_roundtrip(self, paws_data):
        obj, _ = NetworkOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(38)
        raw[5] = 1
        raw[10] = 3
        raw[13] = 1
        raw[15] = 10
        struct.pack_into('<d', raw, 17, 45.0)
        struct.pack_into('<d', raw, 25, 5.0)
        raw = bytes(raw)
        obj, _ = NetworkOpts.parse(raw)
        assert obj.network_byte_5 is True
        assert obj.network_byte_10 == 3
        assert obj.network_timer_1 == 45.0
        assert obj.network_timer_2 == 5.0
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="38 bytes"):
            NetworkOpts.parse(b'\x00' * 10)


# ─── CGEstarOpts ─────────────────────────────────────────────────────

class TestGEstarOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CGEstarOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == GEstarOpts.DATA_SIZE == 35

    def test_parse_emer_tone(self, paws_data):
        obj, _ = GEstarOpts.parse(paws_data)
        assert obj.p25c_repeat_emer_tone is True

    def test_parse_start_delay(self, paws_data):
        obj, _ = GEstarOpts.parse(paws_data)
        assert obj.start_delay == 360.0

    def test_parse_emer_repeat(self, paws_data):
        obj, _ = GEstarOpts.parse(paws_data)
        assert obj.emer_repeat == 5

    def test_parse_gestar_bytes(self, paws_data):
        obj, _ = GEstarOpts.parse(paws_data)
        assert obj.gestar_byte_21 == 0x20  # 32
        assert obj.gestar_byte_22 == 0x20  # 32

    def test_roundtrip(self, paws_data):
        obj, _ = GEstarOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(35)
        raw[4] = 1
        struct.pack_into('<d', raw, 10, 120.0)
        raw[19] = 3
        raw[21] = 16
        raw[22] = 16
        raw = bytes(raw)
        obj, _ = GEstarOpts.parse(raw)
        assert obj.p25c_repeat_emer_tone is True
        assert obj.start_delay == 120.0
        assert obj.emer_repeat == 3
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="35 bytes"):
            GEstarOpts.parse(b'\x00' * 10)


# ─── CConvScanOpts ───────────────────────────────────────────────────

class TestConvScanOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CConvScanOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == ConvScanOpts.DATA_SIZE == 30

    def test_parse_booleans(self, paws_data):
        obj, _ = ConvScanOpts.parse(paws_data)
        assert obj.conv_scan_opt_0 is True
        assert obj.conv_scan_gap_1 is False
        assert obj.conv_scan_opt_1 is True
        assert obj.conv_scan_gap_3 is False
        assert obj.conv_scan_opt_2 is True
        assert obj.conv_scan_gap_5 is False
        assert obj.conv_scan_opt_3 is True

    def test_parse_mode(self, paws_data):
        obj, _ = ConvScanOpts.parse(paws_data)
        assert obj.conv_scan_mode == 2

    def test_parse_double(self, paws_data):
        obj, _ = ConvScanOpts.parse(paws_data)
        assert obj.conv_scan_double_9 == 2.0

    def test_roundtrip(self, paws_data):
        obj, _ = ConvScanOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(30)
        raw[0] = 1
        raw[2] = 1
        raw[4] = 1
        raw[6] = 1
        raw[7] = 3
        struct.pack_into('<d', raw, 9, 5.0)
        raw = bytes(raw)
        obj, _ = ConvScanOpts.parse(raw)
        assert obj.conv_scan_opt_0 is True
        assert obj.conv_scan_mode == 3
        assert obj.conv_scan_double_9 == 5.0
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="30 bytes"):
            ConvScanOpts.parse(b'\x00' * 10)


# ─── CProSoundOpts ───────────────────────────────────────────────────

class TestProSoundOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CProSoundOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == ProSoundOpts.DATA_SIZE == 28

    def test_parse_sensitivity(self, paws_data):
        obj, _ = ProSoundOpts.parse(paws_data)
        assert obj.sensitivity == 3.0

    def test_parse_system_sample_time(self, paws_data):
        obj, _ = ProSoundOpts.parse(paws_data)
        assert obj.system_sample_time == 250.0

    def test_parse_params(self, paws_data):
        obj, _ = ProSoundOpts.parse(paws_data)
        assert obj.proscan_param_17 == 5
        assert obj.proscan_param_19 == 31
        assert obj.proscan_param_21 == 21
        assert obj.proscan_param_23 == 31
        assert obj.proscan_param_25 == 18
        assert obj.proscan_param_27 == 3

    def test_roundtrip(self, paws_data):
        obj, _ = ProSoundOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(28)
        struct.pack_into('<d', raw, 1, 6.0)
        struct.pack_into('<d', raw, 9, 500.0)
        raw[17] = 10
        raw[19] = 20
        raw[21] = 30
        raw[23] = 40
        raw[25] = 50
        raw[27] = 60
        raw = bytes(raw)
        obj, _ = ProSoundOpts.parse(raw)
        assert obj.sensitivity == 6.0
        assert obj.system_sample_time == 500.0
        assert obj.proscan_param_17 == 10
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="28 bytes"):
            ProSoundOpts.parse(b'\x00' * 10)


# ─── CSystemScanOpts ─────────────────────────────────────────────────

class TestSystemScanOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CSystemScanOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == SystemScanOpts.DATA_SIZE == 24

    def test_parse_scan_type(self, paws_data):
        obj, _ = SystemScanOpts.parse(paws_data)
        assert obj.scan_type == 1

    def test_parse_booleans(self, paws_data):
        obj, _ = SystemScanOpts.parse(paws_data)
        assert obj.priority_scan is True
        assert obj.tone_suppress is False

    def test_parse_scan_bytes(self, paws_data):
        obj, _ = SystemScanOpts.parse(paws_data)
        assert obj.sys_scan_byte_5 == 98  # 0x62
        assert obj.sys_scan_byte_6 == 3

    def test_parse_doubles(self, paws_data):
        obj, _ = SystemScanOpts.parse(paws_data)
        assert obj.cc_loop_count == 2.0
        assert obj.priority_scan_time == 1.0

    def test_roundtrip(self, paws_data):
        obj, _ = SystemScanOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(24)
        raw[0] = 2
        raw[1] = 1
        raw[2] = 1
        raw[5] = 50
        raw[6] = 5
        struct.pack_into('<d', raw, 7, 10.0)
        struct.pack_into('<d', raw, 15, 3.0)
        raw = bytes(raw)
        obj, _ = SystemScanOpts.parse(raw)
        assert obj.scan_type == 2
        assert obj.priority_scan is True
        assert obj.tone_suppress is True
        assert obj.cc_loop_count == 10.0
        assert obj.priority_scan_time == 3.0
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="24 bytes"):
            SystemScanOpts.parse(b'\x00' * 10)


# ─── CKeypadCtrlOpts ─────────────────────────────────────────────────

class TestKeypadCtrlOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CKeypadCtrlOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == KeypadCtrlOpts.DATA_SIZE == 20

    def test_parse_booleans(self, paws_data):
        obj, _ = KeypadCtrlOpts.parse(paws_data)
        assert obj.keypad_opt_0 is True
        assert obj.keypad_opt_1 is True
        assert obj.keypad_opt_2 is True
        assert obj.keypad_opt_3 is True

    def test_roundtrip(self, paws_data):
        obj, _ = KeypadCtrlOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(20)
        raw[3] = 1
        raw[10] = 1
        raw[11] = 1
        raw[12] = 1
        raw = bytes(raw)
        obj, _ = KeypadCtrlOpts.parse(raw)
        assert obj.keypad_opt_0 is True
        assert obj.keypad_opt_1 is True
        assert obj.keypad_opt_2 is True
        assert obj.keypad_opt_3 is True
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="20 bytes"):
            KeypadCtrlOpts.parse(b'\x00' * 5)


# ─── CMdcOpts ────────────────────────────────────────────────────────

class TestMdcOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CMdcOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == MdcOpts.DATA_SIZE == 24

    def test_parse_encode_trigger(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.mdc_encode_trigger == 1

    def test_parse_emergency(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.mdc_emergency_enable is True
        assert obj.mdc_emergency_ack_tone is True

    def test_parse_pretime(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.system_pretime == 750   # 0x02EE
        assert obj.interpacket_delay == 500  # 0x01F4

    def test_parse_booleans(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.send_preamble_during_pretime is False
        assert obj.mdc_bool_12 is True

    def test_parse_hang_time(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.mdc_hang_time == 7

    def test_parse_enhanced_id(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.enhanced_id_encode_trigger == 0
        assert obj.enhanced_id_system_pretime == 750  # 0x02EE
        assert obj.enhanced_id_hang_time == 7

    def test_parse_emergency_tone(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.emergency_tone_volume == 31  # 0x1F
        assert obj.emergency_max_tx_power is False
        assert obj.enhanced_emergency_ack_tone is False
        assert obj.alternate_alert_tone is False

    def test_roundtrip(self, paws_data):
        obj, _ = MdcOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(24)
        raw[2] = 2
        raw[4] = 1
        raw[6] = 1
        struct.pack_into('<H', raw, 7, 1000)
        struct.pack_into('<H', raw, 9, 250)
        raw[12] = 1
        raw[13] = 1
        raw[14] = 10
        raw[15] = 1
        struct.pack_into('<H', raw, 17, 500)
        raw[19] = 5
        raw[20] = 20
        raw[21] = 1
        raw[22] = 1
        raw[23] = 1
        raw = bytes(raw)
        obj, _ = MdcOpts.parse(raw)
        assert obj.mdc_encode_trigger == 2
        assert obj.system_pretime == 1000
        assert obj.interpacket_delay == 250
        assert obj.emergency_tone_volume == 20
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="24 bytes"):
            MdcOpts.parse(b'\x00' * 10)


# ─── CVoiceAnnunciation ──────────────────────────────────────────────

class TestVoiceAnnunciation:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CVoiceAnnunciation")

    def test_data_size(self, paws_data):
        assert len(paws_data) == VoiceAnnunciation.DATA_SIZE == 12

    def test_parse_enables(self, paws_data):
        obj, _ = VoiceAnnunciation.parse(paws_data)
        assert obj.enable_voice_annunciation is False
        assert obj.enable_verbose_playback is False
        assert obj.power_on is False

    def test_parse_volume(self, paws_data):
        obj, _ = VoiceAnnunciation.parse(paws_data)
        assert obj.minimum_volume == 0
        assert obj.maximum_volume == 14  # 0x0E
        assert obj.va_byte_5 == 6

    def test_roundtrip(self, paws_data):
        obj, _ = VoiceAnnunciation.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(12)
        raw[0] = 1
        raw[1] = 1
        raw[2] = 1
        raw[3] = 5
        raw[4] = 10
        raw[5] = 3
        raw = bytes(raw)
        obj, _ = VoiceAnnunciation.parse(raw)
        assert obj.enable_voice_annunciation is True
        assert obj.enable_verbose_playback is True
        assert obj.power_on is True
        assert obj.minimum_volume == 5
        assert obj.maximum_volume == 10
        assert obj.va_byte_5 == 3
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="12 bytes"):
            VoiceAnnunciation.parse(b'\x00' * 5)


# ─── CMrkOpts ────────────────────────────────────────────────────────

class TestMrkOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CMrkOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == MrkOpts.DATA_SIZE == 16

    def test_parse_enable(self, paws_data):
        obj, _ = MrkOpts.parse(paws_data)
        assert obj.mrk_enable is True

    def test_parse_byte_12(self, paws_data):
        obj, _ = MrkOpts.parse(paws_data)
        assert obj.mrk_byte_12 == 64  # 0x40

    def test_roundtrip(self, paws_data):
        obj, _ = MrkOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(16)
        raw[7] = 1
        raw[12] = 128
        raw = bytes(raw)
        obj, _ = MrkOpts.parse(raw)
        assert obj.mrk_enable is True
        assert obj.mrk_byte_12 == 128
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="16 bytes"):
            MrkOpts.parse(b'\x00' * 5)


# ─── CIgnitionOpts ───────────────────────────────────────────────────

class TestIgnitionOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CIgnitionOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == IgnitionOpts.DATA_SIZE == 10

    def test_parse_timer(self, paws_data):
        obj, _ = IgnitionOpts.parse(paws_data)
        assert obj.ignition_timer == 20  # 0x14

    def test_roundtrip(self, paws_data):
        obj, _ = IgnitionOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(10)
        raw[7] = 60
        raw = bytes(raw)
        obj, _ = IgnitionOpts.parse(raw)
        assert obj.ignition_timer == 60
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="10 bytes"):
            IgnitionOpts.parse(b'\x00' * 5)


# ─── CDiagnosticOpts ─────────────────────────────────────────────────

class TestDiagnosticOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CDiagnosticOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == DiagnosticOpts.DATA_SIZE == 8

    def test_parse_modes(self, paws_data):
        obj, _ = DiagnosticOpts.parse(paws_data)
        assert obj.diagnostic_mode is False
        assert obj.system_diagnostic_mode is False
        assert obj.ip_echo is True

    def test_parse_serial(self, paws_data):
        obj, _ = DiagnosticOpts.parse(paws_data)
        assert obj.diag_baud_rate == 0
        assert obj.diag_bits_per_char == 0
        assert obj.diag_stop_bits == 0
        assert obj.diag_parity == 0
        assert obj.diag_byte_6 == 0

    def test_roundtrip(self, paws_data):
        obj, _ = DiagnosticOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(8)
        raw[0] = 1
        raw[1] = 1
        raw[2] = 5
        raw[3] = 8
        raw[4] = 2
        raw[5] = 1
        raw[6] = 3
        raw[7] = 1
        raw = bytes(raw)
        obj, _ = DiagnosticOpts.parse(raw)
        assert obj.diagnostic_mode is True
        assert obj.system_diagnostic_mode is True
        assert obj.diag_baud_rate == 5
        assert obj.diag_bits_per_char == 8
        assert obj.diag_stop_bits == 2
        assert obj.diag_parity == 1
        assert obj.diag_byte_6 == 3
        assert obj.ip_echo is True
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="8 bytes"):
            DiagnosticOpts.parse(b'\x00' * 3)


# ─── CMmsOpts ────────────────────────────────────────────────────────

class TestMmsOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CMmsOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == MmsOpts.DATA_SIZE == 13

    def test_parse_retries(self, paws_data):
        obj, _ = MmsOpts.parse(paws_data)
        assert obj.mms_retries == 3

    def test_parse_params(self, paws_data):
        obj, _ = MmsOpts.parse(paws_data)
        assert obj.mms_param_1 == 4
        assert obj.mms_param_2 == 3
        assert obj.mms_timeout == 15  # 0x0F

    def test_roundtrip(self, paws_data):
        obj, _ = MmsOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(13)
        raw[8] = 5
        raw[9] = 10
        raw[11] = 7
        raw[12] = 30
        raw = bytes(raw)
        obj, _ = MmsOpts.parse(raw)
        assert obj.mms_retries == 5
        assert obj.mms_param_1 == 10
        assert obj.mms_param_2 == 7
        assert obj.mms_timeout == 30
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="13 bytes"):
            MmsOpts.parse(b'\x00' * 5)


# ─── CSndcpOpts ──────────────────────────────────────────────────────

class TestSndcpOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CSndcpOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == SndcpOpts.DATA_SIZE == 8

    def test_parse_holdoff_timer(self, paws_data):
        obj, _ = SndcpOpts.parse(paws_data)
        assert obj.holdoff_timer_ms == 2000  # 0x07D0

    def test_roundtrip(self, paws_data):
        obj, _ = SndcpOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(8)
        struct.pack_into('<H', raw, 5, 5000)
        raw = bytes(raw)
        obj, _ = SndcpOpts.parse(raw)
        assert obj.holdoff_timer_ms == 5000
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="8 bytes"):
            SndcpOpts.parse(b'\x00' * 3)


# ─── CSecurityPolicy ─────────────────────────────────────────────────

class TestSecurityPolicy:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CSecurityPolicy")

    def test_data_size(self, paws_data):
        assert len(paws_data) == SecurityPolicy.DATA_SIZE == 2

    def test_parse_booleans(self, paws_data):
        obj, _ = SecurityPolicy.parse(paws_data)
        assert obj.k_erasure_unit_disable is True
        assert obj.k_erasure_zeroize is True

    def test_roundtrip(self, paws_data):
        obj, _ = SecurityPolicy.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytes([0, 1])
        obj, _ = SecurityPolicy.parse(raw)
        assert obj.k_erasure_unit_disable is False
        assert obj.k_erasure_zeroize is True
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="2 bytes"):
            SecurityPolicy.parse(b'\x00')


# ─── CStatus ─────────────────────────────────────────────────────────

class TestStatusOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CStatus")

    def test_data_size(self, paws_data):
        assert len(paws_data) == StatusOpts.DATA_SIZE == 7

    def test_parse_mode_hang_time(self, paws_data):
        obj, _ = StatusOpts.parse(paws_data)
        assert obj.mode_hang_time == 10  # 0x0A

    def test_parse_select_time(self, paws_data):
        obj, _ = StatusOpts.parse(paws_data)
        assert obj.select_time == 2

    def test_parse_transmit_type(self, paws_data):
        obj, _ = StatusOpts.parse(paws_data)
        assert obj.transmit_type == 0

    def test_parse_booleans(self, paws_data):
        obj, _ = StatusOpts.parse(paws_data)
        assert obj.reset_on_system_change is True
        assert obj.p25_standard_status_format is False

    def test_roundtrip(self, paws_data):
        obj, _ = StatusOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(7)
        raw[2] = 15
        raw[3] = 5
        raw[4] = 1
        raw[5] = 1
        raw[6] = 1
        raw = bytes(raw)
        obj, _ = StatusOpts.parse(raw)
        assert obj.mode_hang_time == 15
        assert obj.select_time == 5
        assert obj.transmit_type == 1
        assert obj.reset_on_system_change is True
        assert obj.p25_standard_status_format is True
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="7 bytes"):
            StatusOpts.parse(b'\x00' * 3)


# ─── Cross-section tests ─────────────────────────────────────────────

class TestAllRemainingOpts:
    """Tests that apply to all 16 remaining option dataclasses together."""

    CLASSES = {
        'CVgOpts': (VgOpts, 54),
        'CNetworkOpts': (NetworkOpts, 38),
        'CGEstarOpts': (GEstarOpts, 35),
        'CConvScanOpts': (ConvScanOpts, 30),
        'CProSoundOpts': (ProSoundOpts, 28),
        'CSystemScanOpts': (SystemScanOpts, 24),
        'CKeypadCtrlOpts': (KeypadCtrlOpts, 20),
        'CMdcOpts': (MdcOpts, 24),
        'CVoiceAnnunciation': (VoiceAnnunciation, 12),
        'CMrkOpts': (MrkOpts, 16),
        'CIgnitionOpts': (IgnitionOpts, 10),
        'CDiagnosticOpts': (DiagnosticOpts, 8),
        'CMmsOpts': (MmsOpts, 13),
        'CSndcpOpts': (SndcpOpts, 8),
        'CSecurityPolicy': (SecurityPolicy, 2),
        'CStatus': (StatusOpts, 7),
    }

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_roundtrip_from_pawsovermaws(self, class_name, cls_and_size):
        """Parse from PAWSOVERMAWS, rebuild, verify byte-identical."""
        cls, expected_size = cls_and_size
        data = _get_section_data(class_name)
        assert len(data) == expected_size
        obj, end = cls.parse(data)
        assert end == expected_size
        assert obj.to_bytes() == data

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_all_zeros(self, class_name, cls_and_size):
        """All-zeros data should parse and roundtrip cleanly."""
        cls, expected_size = cls_and_size
        raw = b'\x00' * expected_size
        obj, _ = cls.parse(raw)
        assert obj.to_bytes() == raw

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_all_ff_parses(self, class_name, cls_and_size):
        """All-0xFF data should parse without error.

        Booleans normalize 0xFF to True (0x01), so to_bytes() won't be
        identical for sections with bool fields. Double-roundtrip verifies
        stability.
        """
        cls, expected_size = cls_and_size
        raw = b'\xFF' * expected_size
        obj, end = cls.parse(raw)
        assert end == expected_size
        rebuilt = obj.to_bytes()
        obj2, _ = cls.parse(rebuilt)
        assert obj2.to_bytes() == rebuilt

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_data_size_attribute(self, class_name, cls_and_size):
        """DATA_SIZE class attribute matches expected size."""
        cls, expected_size = cls_and_size
        assert cls.DATA_SIZE == expected_size

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_parse_at_offset(self, class_name, cls_and_size):
        """Parse at non-zero offset returns correct end position."""
        cls, expected_size = cls_and_size
        data = _get_section_data(class_name)
        padded = b'\xBB' * 10 + data
        obj, end = cls.parse(padded, 10)
        assert end == 10 + expected_size
        assert obj.to_bytes() == data
