"""Tests for option section dataclasses in record_types.py.

Verifies parse/build roundtrip for the 7 major binary option sections:
  CGenRadioOpts, CTimerOpts, CScanOpts, CPowerUpOpts,
  CDisplayOpts, CDataOpts, CSupervisoryOpts

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
    GenRadioOpts, TimerOpts, ScanOpts, PowerUpOpts,
    DisplayOpts, DataOpts, SupervisoryOpts,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWSOVERMAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _get_section_data(class_name):
    """Helper: extract data payload from a named section in PAWSOVERMAWS."""
    prs = parse_prs(PAWSOVERMAWS)
    sec = prs.get_section_by_class(class_name)
    assert sec is not None, f"Section {class_name} not found"
    return extract_section_data(sec)


# ─── CGenRadioOpts ───────────────────────────────────────────────────

class TestGenRadioOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CGenRadioOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == GenRadioOpts.DATA_SIZE == 41

    def test_parse_npspac_override(self, paws_data):
        obj, _ = GenRadioOpts.parse(paws_data)
        assert obj.npspac_override is True

    def test_parse_noise_cancellation(self, paws_data):
        obj, _ = GenRadioOpts.parse(paws_data)
        assert obj.noise_cancellation_type == 1  # Method A

    def test_parse_edacs_lid_range(self, paws_data):
        obj, _ = GenRadioOpts.parse(paws_data)
        assert obj.edacs_min_lid == 1
        assert obj.edacs_max_lid == 16382  # 0x3FFE

    def test_parse_nonzero_bytes(self, paws_data):
        obj, _ = GenRadioOpts.parse(paws_data)
        assert obj.gen_radio_byte_19 == 160  # 0xA0
        assert obj.gen_radio_byte_30 is True
        assert obj.gen_radio_byte_33 == 10
        assert obj.gen_radio_byte_37 is True

    def test_roundtrip(self, paws_data):
        obj, _ = GenRadioOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        """Build from scratch, parse back, verify fields."""
        raw = bytearray(41)
        raw[0] = 1  # npspac_override
        raw[3] = 1  # noise cancellation Method A
        struct.pack_into('<H', raw, 13, 100)   # min LID
        struct.pack_into('<H', raw, 15, 8000)  # max LID
        raw[19] = 0xA0
        raw[30] = 1
        raw[33] = 10
        raw[37] = 1
        raw = bytes(raw)

        obj, _ = GenRadioOpts.parse(raw)
        assert obj.npspac_override is True
        assert obj.noise_cancellation_type == 1
        assert obj.edacs_min_lid == 100
        assert obj.edacs_max_lid == 8000
        assert obj.to_bytes() == raw

    def test_parse_offset(self, paws_data):
        """Parse at non-zero offset."""
        padded = b'\xAA' * 5 + paws_data
        obj, end = GenRadioOpts.parse(padded, 5)
        assert end == 5 + 41
        assert obj.to_bytes() == paws_data

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="41 bytes"):
            GenRadioOpts.parse(b'\x00' * 10)


# ─── CTimerOpts ──────────────────────────────────────────────────────

class TestTimerOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CTimerOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == TimerOpts.DATA_SIZE == 82

    def test_parse_cct(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.cct == 60.0

    def test_parse_timer_field_12(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.timer_field_12 == 1.0

    def test_parse_phone_entry_mode(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.phone_entry_mode == 10.0

    def test_parse_icall_timeout(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.icall_timeout == 10.0

    def test_parse_icall_entry_mode(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.icall_entry_mode == 10.0

    def test_parse_cc_scan_delay(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.cc_scan_delay_timer == 0.0

    def test_parse_priority_call_timeout(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.priority_call_timeout == 0.0

    def test_parse_timer_byte_63(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.timer_byte_63 == 30  # 0x1E

    def test_parse_vote_scan_hangtime(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.vote_scan_hangtime == 0.0

    def test_roundtrip(self, paws_data):
        obj, _ = TimerOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(82)
        struct.pack_into('<d', raw, 4, 5.0)
        struct.pack_into('<d', raw, 12, 2.0)
        struct.pack_into('<d', raw, 20, 15.0)
        struct.pack_into('<d', raw, 28, 20.0)
        struct.pack_into('<d', raw, 36, 25.0)
        struct.pack_into('<d', raw, 44, 3.0)
        struct.pack_into('<d', raw, 52, 120.0)
        raw[63] = 45
        struct.pack_into('<d', raw, 68, 7.0)
        raw = bytes(raw)

        obj, _ = TimerOpts.parse(raw)
        assert obj.priority_call_timeout == 5.0
        assert obj.timer_field_12 == 2.0
        assert obj.phone_entry_mode == 15.0
        assert obj.icall_timeout == 20.0
        assert obj.icall_entry_mode == 25.0
        assert obj.cc_scan_delay_timer == 3.0
        assert obj.cct == 120.0
        assert obj.timer_byte_63 == 45
        assert obj.vote_scan_hangtime == 7.0
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="82 bytes"):
            TimerOpts.parse(b'\x00' * 40)


# ─── CScanOpts ────────────────────────────────────────────────────────

class TestScanOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CScanOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == ScanOpts.DATA_SIZE == 33

    def test_parse_booleans(self, paws_data):
        obj, _ = ScanOpts.parse(paws_data)
        assert obj.scan_with_channel_guard is False
        assert obj.alternate_scan is False
        assert obj.always_scan_selected_chan is True
        assert obj.conv_pri_scan_with_cg is False
        assert obj.scan_after_ptt is True

    def test_parse_universal_hang_time(self, paws_data):
        """Universal hang time should be a valid double (might be 0.0 or 2.0)."""
        obj, _ = ScanOpts.parse(paws_data)
        # Bytes 11-18 are: 00 00 00 00 00 00 00 00 = 0.0
        assert obj.universal_hang_time == 0.0

    def test_parse_scan_byte_19(self, paws_data):
        obj, _ = ScanOpts.parse(paws_data)
        assert obj.scan_byte_19 == 64  # 0x40

    def test_parse_conv_pri_scan_hang_time(self, paws_data):
        obj, _ = ScanOpts.parse(paws_data)
        assert obj.conv_pri_scan_hang_time == 10

    def test_parse_band_hunt_interval(self, paws_data):
        obj, _ = ScanOpts.parse(paws_data)
        assert obj.band_hunt_interval == 10

    def test_roundtrip(self, paws_data):
        obj, _ = ScanOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(33)
        raw[0] = 1  # scan_with_channel_guard
        raw[2] = 1  # always_scan_selected_chan
        raw[4] = 1  # scan_after_ptt
        struct.pack_into('<d', raw, 11, 5.0)
        raw[19] = 0x40
        raw[29] = 15
        raw[32] = 20
        raw = bytes(raw)

        obj, _ = ScanOpts.parse(raw)
        assert obj.scan_with_channel_guard is True
        assert obj.always_scan_selected_chan is True
        assert obj.scan_after_ptt is True
        assert obj.universal_hang_time == 5.0
        assert obj.scan_byte_19 == 0x40
        assert obj.conv_pri_scan_hang_time == 15
        assert obj.band_hunt_interval == 20
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="33 bytes"):
            ScanOpts.parse(b'\x00' * 20)


# ─── CPowerUpOpts ─────────────────────────────────────────────────────

class TestPowerUpOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CPowerUpOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == PowerUpOpts.DATA_SIZE == 36

    def test_parse_power_up_selection(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.power_up_selection == 0  # Default

    def test_parse_booleans_all_false(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.pu_ignore_ab_switch is False
        assert obj.pu_contrast is False
        assert obj.pu_keypad_lock is False
        assert obj.pu_keypad_state is False
        assert obj.pu_edacs_auto_login is False
        assert obj.pu_squelch is False
        assert obj.pu_external_alarm is False
        assert obj.pu_scan is False
        assert obj.pu_audible_tone is False
        assert obj.pu_private_mode is False

    def test_parse_nonzero_bytes(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.power_up_byte_11 == 15   # 0x0F
        assert obj.power_up_byte_13 == 3
        assert obj.power_up_byte_20 == 40   # 0x28
        assert obj.power_up_byte_22 == 6

    def test_parse_squelch_level(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.squelch_level == 9

    def test_parse_max_bad_pin(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.max_bad_pin_entries == 5

    def test_roundtrip(self, paws_data):
        obj, _ = PowerUpOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(36)
        raw[0] = 1  # System/Group
        raw[1] = 1  # ignore AB switch
        raw[8] = 1  # scan
        raw[11] = 15
        raw[13] = 3
        raw[20] = 40
        raw[22] = 6
        raw[24] = 12  # squelch level
        raw[30] = 3   # max bad PIN
        raw = bytes(raw)

        obj, _ = PowerUpOpts.parse(raw)
        assert obj.power_up_selection == 1
        assert obj.pu_ignore_ab_switch is True
        assert obj.pu_scan is True
        assert obj.squelch_level == 12
        assert obj.max_bad_pin_entries == 3
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="36 bytes"):
            PowerUpOpts.parse(b'\x00' * 10)


# ─── CDisplayOpts ────────────────────────────────────────────────────

class TestDisplayOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CDisplayOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == DisplayOpts.DATA_SIZE == 37

    def test_parse_booleans(self, paws_data):
        obj, _ = DisplayOpts.parse(paws_data)
        assert obj.display_opt_bool_0 is True
        assert obj.display_opt_bool_1 is True
        assert obj.display_opt_bool_2 is True

    def test_parse_byte_12(self, paws_data):
        obj, _ = DisplayOpts.parse(paws_data)
        assert obj.display_opt_byte_12 == 42  # 0x2A

    def test_parse_double_15(self, paws_data):
        obj, _ = DisplayOpts.parse(paws_data)
        assert obj.display_opt_double_15 == 3.5

    def test_roundtrip(self, paws_data):
        obj, _ = DisplayOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(37)
        raw[3] = 1
        raw[8] = 1
        raw[12] = 99
        struct.pack_into('<d', raw, 15, 7.25)
        raw[29] = 1
        raw = bytes(raw)

        obj, _ = DisplayOpts.parse(raw)
        assert obj.display_opt_bool_0 is True
        assert obj.display_opt_byte_12 == 99
        assert obj.display_opt_double_15 == 7.25
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="37 bytes"):
            DisplayOpts.parse(b'\x00' * 15)


# ─── CDataOpts ───────────────────────────────────────────────────────

class TestDataOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CDataOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == DataOpts.DATA_SIZE == 41

    def test_parse_ptt_flags(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.ptt_receive_data is True
        assert obj.ptt_transmit_data is True
        assert obj.tx_data_overrides_rx_grp_call is False

    def test_parse_protocol(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.data_interface_protocol == 1  # PPP/SLIP

    def test_parse_gps_mic(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.gps_mic_sample_interval == 5

    def test_parse_dcs_settings(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.dcs_max_frame_retries == 3
        assert obj.dcs_max_frame_repeats == 3
        assert obj.dcs_ack_response_timeout == 10
        assert obj.dcs_data_response_timeout == 80  # 0x50

    def test_parse_ppp_slip(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.ppp_slip_retry_count == 3
        assert obj.ppp_slip_retry_interval == 15
        assert obj.ppp_slip_ttl == 29  # 0x1D

    def test_parse_service_address(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.service_address_str == "192.168.0.14"

    def test_parse_mdt_address(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.mdt_address_str == "192.168.0.15"

    def test_parse_serial(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.serial_baud_rate == 5    # 19200
        assert obj.serial_stop_bits == 1    # One

    def test_roundtrip(self, paws_data):
        obj, _ = DataOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(41)
        raw[3] = 1  # ptt_receive_data
        raw[4] = 1  # ptt_transmit_data
        raw[6] = 1  # PPP/SLIP
        raw[10] = 10  # gps mic
        raw[13] = 5
        raw[14] = 5
        raw[15] = 20
        raw[16] = 100
        raw[20] = 4
        raw[21] = 10
        raw[23] = 64
        raw[25:29] = bytes([10, 0, 0, 1])  # 10.0.0.1
        raw[31] = 4  # 9600
        raw[35:39] = bytes([172, 16, 0, 1])  # 172.16.0.1
        raw[39] = 2  # Two stop bits
        raw = bytes(raw)

        obj, _ = DataOpts.parse(raw)
        assert obj.ptt_receive_data is True
        assert obj.data_interface_protocol == 1
        assert obj.gps_mic_sample_interval == 10
        assert obj.service_address_str == "10.0.0.1"
        assert obj.mdt_address_str == "172.16.0.1"
        assert obj.serial_stop_bits == 2
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="41 bytes"):
            DataOpts.parse(b'\x00' * 20)


# ─── CSupervisoryOpts ────────────────────────────────────────────────

class TestSupervisoryOpts:

    @pytest.fixture
    def paws_data(self):
        return _get_section_data("CSupervisoryOpts")

    def test_data_size(self, paws_data):
        assert len(paws_data) == SupervisoryOpts.DATA_SIZE == 36

    def test_parse_doubles(self, paws_data):
        obj, _ = SupervisoryOpts.parse(paws_data)
        assert obj.supervisory_double_0 == 0.0
        assert obj.emergency_key_delay == 1.0
        assert obj.emergency_autokey_timeout == 0.0
        assert obj.emergency_autocycle_timeout == 0.0

    def test_parse_suffix_zeros(self, paws_data):
        """Bytes 32-35 should be zero (suffix)."""
        obj, _ = SupervisoryOpts.parse(paws_data)
        rebuilt = obj.to_bytes()
        assert rebuilt[32:36] == b'\x00\x00\x00\x00'

    def test_roundtrip(self, paws_data):
        obj, _ = SupervisoryOpts.parse(paws_data)
        assert obj.to_bytes() == paws_data

    def test_roundtrip_synthetic(self):
        raw = bytearray(36)
        struct.pack_into('<d', raw, 0, 5.0)
        struct.pack_into('<d', raw, 8, 2.5)
        struct.pack_into('<d', raw, 16, 30.0)
        struct.pack_into('<d', raw, 24, 15.0)
        raw = bytes(raw)

        obj, _ = SupervisoryOpts.parse(raw)
        assert obj.supervisory_double_0 == 5.0
        assert obj.emergency_key_delay == 2.5
        assert obj.emergency_autokey_timeout == 30.0
        assert obj.emergency_autocycle_timeout == 15.0
        assert obj.to_bytes() == raw

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="36 bytes"):
            SupervisoryOpts.parse(b'\x00' * 10)


# ─── Cross-section tests ─────────────────────────────────────────────

class TestAllOptionDataclasses:
    """Tests that apply to all 7 option dataclasses together."""

    CLASSES = {
        'CGenRadioOpts': (GenRadioOpts, 41),
        'CTimerOpts': (TimerOpts, 82),
        'CScanOpts': (ScanOpts, 33),
        'CPowerUpOpts': (PowerUpOpts, 36),
        'CDisplayOpts': (DisplayOpts, 37),
        'CDataOpts': (DataOpts, 41),
        'CSupervisoryOpts': (SupervisoryOpts, 36),
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

        Note: booleans normalize 0xFF to True (0x01), so to_bytes()
        won't be identical for sections with bool fields. This is
        expected — only raw_data preserves non-standard bool values.
        """
        cls, expected_size = cls_and_size
        raw = b'\xFF' * expected_size
        obj, end = cls.parse(raw)
        assert end == expected_size
        # Verify double-roundtrip: parse the rebuilt bytes
        rebuilt = obj.to_bytes()
        obj2, _ = cls.parse(rebuilt)
        assert obj2.to_bytes() == rebuilt

    @pytest.mark.parametrize("class_name,cls_and_size", CLASSES.items(),
                             ids=list(CLASSES.keys()))
    def test_data_size_attribute(self, class_name, cls_and_size):
        """DATA_SIZE class attribute matches expected size."""
        cls, expected_size = cls_and_size
        assert cls.DATA_SIZE == expected_size
