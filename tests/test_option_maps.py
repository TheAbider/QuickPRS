"""Tests for quickprs.option_maps — XML extraction and field maps."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path


from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.option_maps import (
    extract_platform_xml, extract_platform_config, find_platform_xml_location,
    write_platform_config, config_to_xml,
    extract_blob_preamble, BlobPreamble, OOR_ALERT_VALUES,
    OPTION_MAPS, ACCESSORY_DEVICE_MAP, ALERT_OPTS_MAP, GEN_RADIO_OPTS_MAP,
    DTMF_OPTS_MAP, TIMER_OPTS_MAP, SUPERVISORY_OPTS_MAP,
    POWER_UP_OPTS_MAP, SCAN_OPTS_MAP, DIAGNOSTIC_OPTS_MAP,
    MDC_OPTS_MAP, SECURITY_POLICY_MAP, STATUS_OPTS_MAP,
    SYSTEM_SCAN_OPTS_MAP, VOICE_ANNUNCIATION_MAP, TYPE99_OPTS_MAP,
    DATA_OPTS_MAP, SNDCP_OPTS_MAP, GESTAR_OPTS_MAP, PROSCAN_OPTS_MAP,
    VG_OPTS_MAP, CONV_SCAN_OPTS_MAP, DISPLAY_OPTS_MAP, IGNITION_OPTS_MAP,
    NETWORK_OPTS_MAP, MMS_OPTS_MAP, KEYPAD_CTRL_OPTS_MAP, MRK_OPTS_MAP,
    XML_FIELDS, XML_FIELD_INDEX, XML_FIELDS_BY_CATEGORY,
    XG100P_DEFAULTS, ACCESSORY_DEVICE_DEFAULTS,
    read_field, write_field, extract_section_data, FieldDef,
    format_button_function, format_button_name,
    format_short_menu_name, format_switch_function,
    BUTTON_FUNCTION_NAMES, BUTTON_NAME_DISPLAY,
    SHORT_MENU_NAMES, SWITCH_FUNCTION_NAMES,
)


# ─── Test data paths ─────────────────────────────────────────────────

TESTDATA = Path(__file__).parent / "testdata"
EVERY_OPT = TESTDATA / "every option"
BASELINE = EVERY_OPT / "new radio - xg 100 portable .PRS"
BATTERY_NIMH = EVERY_OPT / "new radio -battery settings - battery type -lithium ion poly to nimh .PRS"
BATTERY_ALKALINE = EVERY_OPT / "new radio -battery settings - battery type - nimh to alkaline .PRS"
BATTERY_PRIMARY = EVERY_OPT / "new radio -battery settings - battery type - alkaline to primary lithium.PRS"
AUDIO_SPEAKER = EVERY_OPT / "new radio -audio settings - speaker- enabled to disabled.PRS"
AUDIO_NOISE = EVERY_OPT / "new radio -audio settings - noise cancelation - disabled to enabled.PRS"
AUDIO_TONES = EVERY_OPT / "new radio -audio settings - tones - disabled to enabled).PRS"
AUDIO_KEYPAD = EVERY_OPT / "new radio -audio settings - keypad tones - disabled to enabled).PRS"
AUDIO_MIC_GAIN = EVERY_OPT / "new radio -audio settings - external mic - mic gain - 0 to -12 .PRS"

# OOR alert files
OOR_SLOW = EVERY_OPT / "new radio -alert option - repeated out of range alert tone whatever - disabled to slow.PRS"
OOR_MED = EVERY_OPT / "new radio -alert option - repeated out of range alert tone interval- slow to med.PRS"
OOR_FAST = EVERY_OPT / "new radio -alert option - repeated out of range alert tone interval- med to fast.PRS"

# Standard test files
CLAUDE_TEST = TESTDATA / "claude test.PRS"
PAWSOVERMAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── XML extraction ──────────────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestExtractPlatformXml:

    def test_baseline_has_xml(self):
        prs = cached_parse_prs(BASELINE)
        xml_str = extract_platform_xml(prs)
        assert xml_str is not None
        assert xml_str.startswith("<platformConfig>")
        assert xml_str.endswith("</platformConfig>")

    def test_battery_file_has_xml(self):
        prs = cached_parse_prs(BATTERY_NIMH)
        xml_str = extract_platform_xml(prs)
        assert xml_str is not None
        assert "batteryType" in xml_str

    def test_audio_file_has_xml(self):
        prs = cached_parse_prs(AUDIO_SPEAKER)
        xml_str = extract_platform_xml(prs)
        assert xml_str is not None
        assert "audioConfig" in xml_str

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_has_xml(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        assert xml_str is not None
        assert "<platformConfig>" in xml_str


@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestExtractPlatformConfig:

    def test_baseline_config_keys(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        assert config is not None
        expected_keys = {
            "progButtons", "accessoryConfig", "manDownConfig",
            "shortMenu", "gpsConfig", "audioConfig",
            "bluetoothConfig", "miscConfig", "TimeDateCfg",
        }
        assert expected_keys.issubset(set(config.keys()))

    def test_baseline_audio_defaults(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        audio = config["audioConfig"]
        assert audio["speakerMode"] == "ON"
        assert audio["pttMode"] == "ON"
        assert audio["noiseCancellation"] == "OFF"
        assert audio["tones"] == "OFF"
        assert audio["minVol"] == "0"
        assert audio["pttAudio"] == "RADIO_ACCESSORY"

    def test_baseline_battery_default(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["batteryType"] == "LITHIUM_ION_POLY"

    def test_baseline_accessory_defaults(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        acc = config["accessoryConfig"]
        assert acc["noiseCancellation"] == "ON"
        assert acc["micSelectMode"] == "TOP"
        assert acc["pttMode"] == "BOTH"

    def test_baseline_mandown_defaults(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        md = config["manDownConfig"]
        assert md["sensitivity"] == "0"  # OFF
        assert md["inactivityTime"] == "240"
        assert md["warningTime"] == "30"

    def test_battery_nimh(self):
        prs = cached_parse_prs(BATTERY_NIMH)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["batteryType"] == "NIMH"

    def test_battery_alkaline(self):
        prs = cached_parse_prs(BATTERY_ALKALINE)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["batteryType"] == "ALKALINE"

    def test_battery_primary_lithium(self):
        prs = cached_parse_prs(BATTERY_PRIMARY)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["batteryType"] == "PRIMARY_LITHIUM"

    def test_audio_speaker_off(self):
        prs = cached_parse_prs(AUDIO_SPEAKER)
        config = extract_platform_config(prs)
        assert config["audioConfig"]["speakerMode"] == "OFF"

    def test_audio_noise_cancel_on(self):
        prs = cached_parse_prs(AUDIO_NOISE)
        config = extract_platform_config(prs)
        assert config["audioConfig"]["noiseCancellation"] == "ON"

    def test_audio_tones_on(self):
        prs = cached_parse_prs(AUDIO_TONES)
        config = extract_platform_config(prs)
        assert config["audioConfig"]["tones"] == "ON"

    def test_audio_keypad_on(self):
        prs = cached_parse_prs(AUDIO_KEYPAD)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["keypadTones"] == "ON"

    def test_external_mic_gain(self):
        prs = cached_parse_prs(AUDIO_MIC_GAIN)
        config = extract_platform_config(prs)
        # microphone children are in audioConfig
        audio = config["audioConfig"]
        mics = audio.get("microphone", [])
        if not isinstance(mics, list):
            mics = [mics]
        ext_mic = next(m for m in mics if m.get("micType") == "EXTERNAL")
        assert ext_mic["gain"] == "-12"
        assert ext_mic["alc"] == "ON"

    def test_microphone_children_present(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        audio = config["audioConfig"]
        mics = audio.get("microphone", [])
        if not isinstance(mics, list):
            mics = [mics]
        assert len(mics) == 2
        mic_types = {m["micType"] for m in mics}
        assert mic_types == {"INTERNAL", "EXTERNAL"}


@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestFindPlatformXmlLocation:

    def test_baseline_location(self):
        prs = cached_parse_prs(BASELINE)
        loc = find_platform_xml_location(prs)
        assert loc is not None
        sec_idx, start, end = loc
        assert sec_idx >= 0
        assert start < end
        # Verify the bytes at that location are XML
        section = prs.sections[sec_idx]
        xml_bytes = section.raw[start:end]
        assert xml_bytes.startswith(b"<platformConfig>")
        assert xml_bytes.endswith(b"</platformConfig>")


@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestWritePlatformConfig:

    def test_roundtrip_write(self):
        """Write new XML, verify it can be read back."""
        prs = cached_parse_prs(BASELINE)
        original_xml = extract_platform_xml(prs)
        assert original_xml is not None

        # Write it back unchanged
        result = write_platform_config(prs, original_xml)
        assert result is True

        # Verify roundtrip
        re_read = extract_platform_xml(prs)
        assert re_read == original_xml

    def test_modify_and_read_back(self):
        """Change a value in XML, write back, verify change persists."""
        prs = cached_parse_prs(BASELINE)
        xml_str = extract_platform_xml(prs)

        # Swap battery type
        modified = xml_str.replace(
            'batteryType="LITHIUM_ION_POLY"',
            'batteryType="ALKALINE"')
        assert modified != xml_str

        write_platform_config(prs, modified)
        config = extract_platform_config(prs)
        assert config["miscConfig"]["batteryType"] == "ALKALINE"


# ─── config_to_xml roundtrip ────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestConfigToXml:

    def test_simple_roundtrip(self):
        """parse → dict → xml → parse should preserve values."""
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        # Re-parse the generated XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_str)
        assert root.tag == "platformConfig"

    def test_full_roundtrip_preserves_values(self):
        """Dict roundtrip should preserve all audio settings."""
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        # Write back and re-extract
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        # Check key values survived
        assert config2["audioConfig"]["speakerMode"] == config["audioConfig"]["speakerMode"]
        assert config2["miscConfig"]["batteryType"] == config["miscConfig"]["batteryType"]
        assert config2["gpsConfig"]["gpsMode"] == config["gpsConfig"]["gpsMode"]

    def test_prog_buttons_roundtrip(self):
        """Prog buttons with child elements should survive roundtrip."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        # Check prog buttons structure preserved
        pb = config2["progButtons"]
        assert pb["_2PosFunction"] == "SCAN"
        buttons = pb["progButton"]
        assert isinstance(buttons, list)
        assert len(buttons) == 4
        top = next(b for b in buttons if b["buttonName"] == "TOP_SIDE")
        assert top["function"] == "TALKAROUND_DIRECT"

    def test_short_menu_roundtrip(self):
        """Short menu with 16 items should survive roundtrip."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        items = config2["shortMenu"]["shortMenuItem"]
        assert isinstance(items, list)
        assert len(items) == 16
        assert items[0]["name"] == "startScan"

    def test_modify_button_roundtrip(self):
        """Modifying a button function should persist through roundtrip."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        # Change top side button to SCAN
        buttons = config["progButtons"]["progButton"]
        top = next(b for b in buttons if b["buttonName"] == "TOP_SIDE")
        top["function"] = "SCAN"
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        buttons2 = config2["progButtons"]["progButton"]
        top2 = next(b for b in buttons2 if b["buttonName"] == "TOP_SIDE")
        assert top2["function"] == "SCAN"

    def test_modify_short_menu_roundtrip(self):
        """Modifying a short menu slot should persist."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        items = config["shortMenu"]["shortMenuItem"]
        # Change slot 7 (empty) to siteDisplay
        slot7 = next(i for i in items if i["position"] == "7")
        slot7["name"] = "siteDisplay"
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        items2 = config2["shortMenu"]["shortMenuItem"]
        slot7_new = next(i for i in items2 if i["position"] == "7")
        assert slot7_new["name"] == "siteDisplay"

    def test_modify_switch_function(self):
        """Modifying 2-pos switch function should persist."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        config["progButtons"]["_2PosFunction"] = "TALKAROUND"
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        assert config2["progButtons"]["_2PosFunction"] == "TALKAROUND"

    def test_accessory_buttons_roundtrip(self):
        """Accessory buttons should survive roundtrip."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        acc = config2["accessoryConfig"]["accessoryButtons"]["accessoryButton"]
        assert isinstance(acc, list)
        assert len(acc) == 3
        em = next(b for b in acc if b["buttonName"] == "ACC_EMERGENCY")
        assert em["function"] == "EMERGENCY_CALL"

    def test_empty_string_attributes(self):
        """Empty string attributes should be preserved."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        xml_str = config_to_xml(config)
        write_platform_config(prs, xml_str)
        config2 = extract_platform_config(prs)
        # 2-pos A/B values are empty strings
        assert config2["progButtons"]["_2PosAValue"] == ""
        assert config2["progButtons"]["_2PosBValue"] == ""


# ─── ElementTree-based editing (matches GUI editor pattern) ─────────

@pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestElementTreeEditing:
    """Tests that simulate the exact editing pattern used by the GUI editors.

    The GUI reads raw XML, modifies via ElementTree, then writes back.
    This tests that path rather than the dict-based config_to_xml path.
    """

    def test_et_button_function_change(self):
        """Change a button function via ElementTree, verify roundtrip."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        # Find TOP_SIDE button and change function
        pb = root.find("progButtons")
        for btn in pb.findall("progButton"):
            if btn.get("buttonName") == "TOP_SIDE":
                btn.set("function", "SCAN")
                break

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        # Verify
        config = extract_platform_config(prs)
        buttons = config["progButtons"]["progButton"]
        top = next(b for b in buttons if b["buttonName"] == "TOP_SIDE")
        assert top["function"] == "SCAN"

    def test_et_switch_function_change(self):
        """Change switch function via ElementTree."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        pb = root.find("progButtons")
        pb.set("_2PosFunction", "ZONE")
        pb.set("_3PosFunction", "TALKAROUND")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        assert config["progButtons"]["_2PosFunction"] == "ZONE"
        assert config["progButtons"]["_3PosFunction"] == "TALKAROUND"

    def test_et_short_menu_change(self):
        """Change short menu slots via ElementTree."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        sm = root.find("shortMenu")
        for item in sm.findall("shortMenuItem"):
            if item.get("position") == "7":
                item.set("name", "homeChannel")
                break

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        items = config["shortMenu"]["shortMenuItem"]
        slot7 = next(i for i in items if i["position"] == "7")
        assert slot7["name"] == "homeChannel"

    def test_et_accessory_button_change(self):
        """Change accessory button via ElementTree."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        acc = root.find("accessoryConfig/accessoryButtons")
        for btn in acc.findall("accessoryButton"):
            if btn.get("buttonName") == "ACC_USER_1":
                btn.set("function", "SCAN")
                break

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        acc_btns = config["accessoryConfig"]["accessoryButtons"]["accessoryButton"]
        user1 = next(b for b in acc_btns if b["buttonName"] == "ACC_USER_1")
        assert user1["function"] == "SCAN"

    def test_et_multiple_edits_single_save(self):
        """Multiple edits in one save should all persist."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        # Change switch, button, and menu slot
        pb = root.find("progButtons")
        pb.set("_2PosFunction", "TALKAROUND")
        for btn in pb.findall("progButton"):
            if btn.get("buttonName") == "MID_SIDE":
                btn.set("function", "HOME_CHANNEL")
                break

        sm = root.find("shortMenu")
        for item in sm.findall("shortMenuItem"):
            if item.get("position") == "0":
                item.set("name", "siteLock")
                break

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        assert config["progButtons"]["_2PosFunction"] == "TALKAROUND"
        buttons = config["progButtons"]["progButton"]
        mid = next(b for b in buttons if b["buttonName"] == "MID_SIDE")
        assert mid["function"] == "HOME_CHANNEL"
        items = config["shortMenu"]["shortMenuItem"]
        slot0 = next(i for i in items if i["position"] == "0")
        assert slot0["name"] == "siteLock"

    def test_et_prs_still_valid_after_edit(self):
        """PRS file should still be parseable after edits."""
        import xml.etree.ElementTree as ET
        prs = cached_parse_prs(PAWSOVERMAWS)
        xml_str = extract_platform_xml(prs)
        root = ET.fromstring(xml_str)

        pb = root.find("progButtons")
        pb.set("_2PosFunction", "ZONE")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        # Re-parse from bytes
        from quickprs.prs_parser import parse_prs_bytes
        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        config = extract_platform_config(prs2)
        assert config["progButtons"]["_2PosFunction"] == "ZONE"


# ─── Binary field maps ───────────────────────────────────────────────

class TestOptionMapRegistry:

    def test_maps_registered(self):
        assert "CAccessoryDevice" in OPTION_MAPS
        assert "CAlertOpts" in OPTION_MAPS
        assert "CGenRadioOpts" in OPTION_MAPS

    def test_accessory_device_fields(self):
        m = ACCESSORY_DEVICE_MAP
        assert m.data_size == 8
        assert len(m.fields) == 8
        names = [f.name for f in m.fields]
        assert "ptt_mode" in names
        assert "noise_cancellation" in names
        assert "mic_select" in names
        assert "mandown_sensitivity" in names
        assert "mandown_warning_delay" in names
        assert "mandown_detection_delay" in names

    def test_alert_opts_fields(self):
        m = ALERT_OPTS_MAP
        assert m.data_size == 19
        assert len(m.fields) >= 3
        names = [f.name for f in m.fields]
        assert "ready_to_talk_tone" in names
        assert "initial_oor_alert_tone" in names
        assert "alternate_alert_tone" in names
        assert "vr_activation_tone" in names
        assert "alert_bool_8" in names
        assert "alert_bool_9" in names
        assert "alert_bool_12" in names
        assert "alert_bool_14" in names

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_alert_bool_values(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CAlertOpts")
        data = extract_section_data(sec)
        for name in ("alert_bool_8", "alert_bool_9", "alert_bool_12", "alert_bool_14"):
            fd = [f for f in ALERT_OPTS_MAP.fields if f.name == name][0]
            assert read_field(data, fd) is True, f"{name} should be True"

    def test_fields_dont_overlap(self):
        for opt_map in OPTION_MAPS.values():
            used = set()
            for f in opt_map.fields:
                for i in range(f.size):
                    byte_pos = f.offset + i
                    assert byte_pos not in used, (
                        f"Overlap at byte {byte_pos} in {opt_map.class_name}")
                    used.add(byte_pos)

    def test_fields_within_data_size(self):
        for opt_map in OPTION_MAPS.values():
            for f in opt_map.fields:
                assert f.offset + f.size <= opt_map.data_size, (
                    f"Field {f.name} exceeds data_size in {opt_map.class_name}")

    def test_coverage(self):
        m = ACCESSORY_DEVICE_MAP
        coverage = m.coverage
        assert coverage == 1.0

    def test_unmapped_ranges(self):
        m = ACCESSORY_DEVICE_MAP
        ranges = m.unmapped_ranges
        assert len(ranges) == 0  # All bytes mapped


class TestReadWriteField:

    def test_read_bool_true(self):
        data = bytes([0x00, 0x01, 0x00])
        fd = FieldDef(1, 1, "test", "Test", "bool")
        assert read_field(data, fd) is True

    def test_read_bool_false(self):
        data = bytes([0x00, 0x00, 0x00])
        fd = FieldDef(1, 1, "test", "Test", "bool")
        assert read_field(data, fd) is False

    def test_read_uint8(self):
        data = bytes([0x00, 0xF0, 0x00])
        fd = FieldDef(1, 1, "test", "Test", "uint8")
        assert read_field(data, fd) == 240

    def test_read_int8_negative(self):
        data = bytes([0xF4])
        fd = FieldDef(0, 1, "test", "Test", "int8")
        assert read_field(data, fd) == -12

    def test_read_uint16(self):
        data = bytes([0x34, 0x12])
        fd = FieldDef(0, 2, "test", "Test", "uint16")
        assert read_field(data, fd) == 0x1234

    def test_read_enum(self):
        data = bytes([0x03])
        fd = FieldDef(0, 1, "test", "Test", "enum",
                      enum_values={0: "OFF", 1: "LOW", 3: "MED", 5: "HIGH"})
        assert read_field(data, fd) == "MED"

    def test_read_enum_unknown(self):
        data = bytes([0xFF])
        fd = FieldDef(0, 1, "test", "Test", "enum",
                      enum_values={0: "OFF", 1: "ON"})
        assert "UNKNOWN" in read_field(data, fd)

    def test_write_bool(self):
        data = bytes([0x00, 0x00, 0x00])
        fd = FieldDef(1, 1, "test", "Test", "bool")
        result = write_field(data, fd, True)
        assert result[1] == 0x01
        assert result[0] == 0x00  # Adjacent byte unchanged
        assert result[2] == 0x00

    def test_write_uint8(self):
        data = bytes([0x00, 0x00])
        fd = FieldDef(0, 1, "test", "Test", "uint8")
        result = write_field(data, fd, 42)
        assert result[0] == 42
        assert result[1] == 0x00

    def test_write_enum_by_int(self):
        data = bytes([0x00])
        fd = FieldDef(0, 1, "test", "Test", "enum",
                      enum_values={0: "OFF", 1: "LOW", 3: "MED"})
        result = write_field(data, fd, 3)
        assert result[0] == 3

    def test_write_enum_by_name(self):
        data = bytes([0x00])
        fd = FieldDef(0, 1, "test", "Test", "enum",
                      enum_values={0: "OFF", 1: "LOW", 3: "MED"})
        result = write_field(data, fd, "MED")
        assert result[0] == 3

    def test_roundtrip_field(self):
        """Write a value, read it back."""
        fd = FieldDef(0, 1, "test", "Test", "uint8")
        original = bytes([0x00])
        modified = write_field(original, fd, 42)
        assert read_field(modified, fd) == 42

    def test_write_doesnt_corrupt_adjacent(self):
        """Writing one field shouldn't touch adjacent bytes."""
        data = bytes([0xAA, 0xBB, 0xCC, 0xDD])
        fd = FieldDef(1, 1, "test", "Test", "uint8")
        result = write_field(data, fd, 0xFF)
        assert result == bytes([0xAA, 0xFF, 0xCC, 0xDD])

    def test_read_out_of_bounds(self):
        data = bytes([0x00])
        fd = FieldDef(5, 1, "test", "Test", "uint8")
        assert read_field(data, fd) is None


@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestExtractSectionData:

    def test_extract_from_named_section(self):
        """CAccessoryDevice section should have extractable data."""
        # Use a file that has CAccessoryDevice as a small section
        prs = cached_parse_prs(AUDIO_SPEAKER)
        sec = prs.get_section_by_class("CAccessoryDevice")
        if sec is not None:
            data = extract_section_data(sec)
            assert data is not None
            assert len(data) > 0


# ─── XML field catalog ───────────────────────────────────────────────

class TestXmlFieldCatalog:

    def test_fields_not_empty(self):
        assert len(XML_FIELDS) > 30  # We defined ~45 fields

    def test_index_matches_fields(self):
        assert len(XML_FIELD_INDEX) == len(XML_FIELDS)

    def test_categories_exist(self):
        cats = set(XML_FIELDS_BY_CATEGORY.keys())
        assert "Audio Settings" in cats
        assert "Battery Settings" in cats
        assert "GPS Settings" in cats
        assert "Bluetooth Settings" in cats
        assert "Accessory Options" in cats
        assert "Unity XG100 Portable Options" in cats
        assert "Display Settings" in cats
        assert "Clock Settings" in cats

    def test_audio_fields_present(self):
        audio = XML_FIELDS_BY_CATEGORY["Audio Settings"]
        names = [f.display_name for f in audio]
        assert "Speaker" in names
        assert "Noise Cancellation" in names
        assert "Internal Mic Gain (dB)" in names
        assert "External Mic Gain (dB)" in names

    def test_battery_field_present(self):
        battery = XML_FIELDS_BY_CATEGORY["Battery Settings"]
        names = [f.display_name for f in battery]
        assert "Battery Type" in names

    def test_unity_portable_fields(self):
        unity = XML_FIELDS_BY_CATEGORY["Unity XG100 Portable Options"]
        names = [f.display_name for f in unity]
        assert "Optimize Conv P25 Battery Life" in names
        assert "Channel Edit Password" in names
        assert "Maintenance Password" in names

    def test_display_settings_fields(self):
        display = XML_FIELDS_BY_CATEGORY["Display Settings"]
        names = [f.display_name for f in display]
        assert "Front Backlight" in names
        assert "Front Backlight Timeout" in names
        assert "Top Backlight Timeout" in names
        assert "Top Orientation" in names
        assert "Date Format" in names

    def test_gps_fields_complete(self):
        gps = XML_FIELDS_BY_CATEGORY["GPS Settings"]
        names = [f.display_name for f in gps]
        assert "GPS Type" in names
        assert "Elevation Basis" in names
        assert "Northing" in names
        assert "Grid Digits" in names

    def test_clock_fields(self):
        clock = XML_FIELDS_BY_CATEGORY["Clock Settings"]
        names = [f.display_name for f in clock]
        assert "Display Time" in names
        assert "Time Zone" in names

    def test_timezone_all_offsets(self):
        """Timezone field should cover UTC-12 to UTC+14."""
        clock = XML_FIELDS_BY_CATEGORY["Clock Settings"]
        tz_field = next(f for f in clock if f.attribute == "zone")
        assert len(tz_field.enum_values) == 27
        assert "BIT" in tz_field.enum_values  # UTC-12
        assert "LINT" in tz_field.enum_values  # UTC+14
        assert "EST" in tz_field.enum_values  # UTC-5
        assert "GMT" in tz_field.enum_values  # UTC+0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_passwords(self):
        """PAWSOVERMAWS has password fields in XML."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        misc = config["miscConfig"]
        assert misc["password"] == "1115"
        assert misc["maintenancePassword"] == "1115"


@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestXg100pDefaults:

    def test_audio_defaults_match_baseline(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        audio = config["audioConfig"]
        for key, expected in XG100P_DEFAULTS["audioConfig"].items():
            assert audio.get(key) == expected, f"audioConfig.{key}"

    def test_misc_defaults_match_baseline(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        misc = config["miscConfig"]
        for key, expected in XG100P_DEFAULTS["miscConfig"].items():
            assert misc.get(key) == expected, f"miscConfig.{key}"

    def test_gps_defaults_match_baseline(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        gps = config["gpsConfig"]
        for key, expected in XG100P_DEFAULTS["gpsConfig"].items():
            assert gps.get(key) == expected, f"gpsConfig.{key}"

    def test_bluetooth_defaults_match_baseline(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        bt = config["bluetoothConfig"]
        for key, expected in XG100P_DEFAULTS["bluetoothConfig"].items():
            assert bt.get(key) == expected, f"bluetoothConfig.{key}"

    def test_accessory_defaults_match_baseline(self):
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        acc = config["accessoryConfig"]
        for key, expected in XG100P_DEFAULTS["accessoryConfig"].items():
            assert acc.get(key) == expected, f"accessoryConfig.{key}"


# ═══════════════════════════════════════════════════════════════════
# Programmable Buttons
# ═══════════════════════════════════════════════════════════════════


class TestProgButtons:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_prog_buttons_extracted(self):
        """PAWSOVERMAWS has progButtons in XML."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        assert "progButtons" in config

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_prog_buttons_structure(self):
        """progButtons has switch configs and button list."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        prog = config["progButtons"]

        # Switch configs
        assert prog["_2PosFunction"] == "SCAN"
        assert prog["_3PosFunction"] == "CHAN_BANK"

        # Buttons
        buttons = prog["progButton"]
        assert isinstance(buttons, list)
        assert len(buttons) == 4

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_button_assignments(self):
        """Verify specific button assignments."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        buttons = config["progButtons"]["progButton"]

        by_name = {b["buttonName"]: b["function"] for b in buttons}
        assert by_name["TOP_SIDE"] == "TALKAROUND_DIRECT"
        assert by_name["MID_SIDE"] == "ZONE_UP_WRAP"
        assert by_name["BOT_SIDE"] == "ZONE_DOWN_WRAP"
        assert by_name["EMERGENCY"] == "UNASSIGNED"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_accessory_buttons(self):
        """Verify accessory button structure."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        acc = config["accessoryConfig"]["accessoryButtons"]
        buttons = acc["accessoryButton"]
        assert isinstance(buttons, list)
        assert len(buttons) == 3
        by_name = {b["buttonName"]: b["function"] for b in buttons}
        assert by_name["ACC_EMERGENCY"] == "EMERGENCY_CALL"

    def test_format_button_function_known(self):
        assert format_button_function("TALKAROUND_DIRECT") == \
            "Talkaround/Direct"
        assert format_button_function("ZONE_UP_WRAP") == "Zone Up (Wrap)"
        assert format_button_function("UNASSIGNED") == "Unassigned"

    def test_format_button_function_unknown(self):
        assert format_button_function("CUSTOM_FUNC") == "CUSTOM_FUNC"

    def test_format_button_name_known(self):
        assert format_button_name("TOP_SIDE") == "Top Side Button"
        assert format_button_name("ACC_USER_1") == "Accessory User 1"

    def test_format_button_name_unknown(self):
        assert format_button_name("UNKNOWN") == "UNKNOWN"

    def test_format_switch_function(self):
        assert format_switch_function("SCAN") == "Scan"
        assert format_switch_function("CHAN_BANK") == "Channel Bank"
        assert format_switch_function("NEW_FUNC") == "NEW_FUNC"


# ═══════════════════════════════════════════════════════════════════
# Short Menu
# ═══════════════════════════════════════════════════════════════════


class TestShortMenu:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_short_menu_extracted(self):
        """PAWSOVERMAWS has shortMenu in XML."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        assert "shortMenu" in config

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_short_menu_16_slots(self):
        """Short menu has 16 slots."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        items = config["shortMenu"]["shortMenuItem"]
        assert isinstance(items, list)
        assert len(items) == 16

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_short_menu_filled_slots(self):
        """First 7 slots should be filled, rest empty."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        config = extract_platform_config(prs)
        items = config["shortMenu"]["shortMenuItem"]
        filled = [i for i in items if i["name"] != "empty"]
        assert len(filled) == 7
        assert items[0]["name"] == "startScan"
        assert items[6]["name"] == "dispSA"

    def test_format_short_menu_name_known(self):
        assert format_short_menu_name("startScan") == "Start Scan"
        assert format_short_menu_name("nuisanceDel") == "Nuisance Delete"
        assert format_short_menu_name("empty") == "(Empty)"

    def test_format_short_menu_name_unknown(self):
        assert format_short_menu_name("customItem") == "customItem"

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_short_menu(self):
        """Even baseline 'new radio' PRS has short menu in XML."""
        prs = cached_parse_prs(BASELINE)
        config = extract_platform_config(prs)
        assert "shortMenu" in config
        items = config["shortMenu"]["shortMenuItem"]
        assert isinstance(items, list)
        assert len(items) == 16


# ─── XML field catalog: prog buttons & short menu entries ────────────

class TestXmlFieldCatalogButtons:
    """Tests for the prog button and short menu XML field catalog entries."""

    def test_prog_buttons_category_exists(self):
        assert "Programmable Buttons" in XML_FIELDS_BY_CATEGORY

    def test_2pos_switch_in_catalog(self):
        key = ("progButtons", "_2PosFunction")
        assert key in XML_FIELD_INDEX
        field = XML_FIELD_INDEX[key]
        assert field.display_name == "2-Position Switch"
        assert field.category == "Programmable Buttons"

    def test_3pos_switch_in_catalog(self):
        key = ("progButtons", "_3PosFunction")
        assert key in XML_FIELD_INDEX
        field = XML_FIELD_INDEX[key]
        assert field.display_name == "3-Position Switch"

    def test_3pos_abc_funcs_in_catalog(self):
        for pos in ("A", "B", "C"):
            key = ("progButtons", f"_3Pos{pos}Func")
            assert key in XML_FIELD_INDEX, f"Missing: _3Pos{pos}Func"
            field = XML_FIELD_INDEX[key]
            assert field.display_name == f"3-Pos {pos} Function"

    def test_switch_display_maps_applied(self):
        field = XML_FIELD_INDEX[("progButtons", "_2PosFunction")]
        assert field.display_map.get("SCAN") == "Scan"
        assert field.display_map.get("CHAN_BANK") == "Channel Bank"

    def test_prog_button_function_in_catalog(self):
        key = ("progButton", "function")
        assert key in XML_FIELD_INDEX
        field = XML_FIELD_INDEX[key]
        assert field.display_name == "Function"
        assert field.display_map.get("TALKAROUND_DIRECT") == "Talkaround/Direct"

    def test_accessory_button_in_catalog(self):
        key = ("accessoryButton", "function")
        assert key in XML_FIELD_INDEX
        field = XML_FIELD_INDEX[key]
        assert field.category == "Accessory Buttons"

    def test_short_menu_item_in_catalog(self):
        key = ("shortMenuItem", "name")
        assert key in XML_FIELD_INDEX
        field = XML_FIELD_INDEX[key]
        assert field.category == "Short Menu"
        assert field.display_map.get("startScan") == "Start Scan"
        assert field.display_map.get("empty") == "(Empty)"

    def test_all_prog_button_attrs_cataloged(self):
        """All known progButtons XML attributes should be in the catalog."""
        expected = [
            "_2PosFunction", "_2PosAValue", "_2PosBValue",
            "_2PosA_VAIndex", "_2PosB_VAIndex",
            "_3PosFunction", "_3PosAFunc", "_3PosBFunc", "_3PosCFunc",
            "_3PosAIndex", "_3PosBIndex", "_3PosCIndex",
            "_3PosAValue", "_3PosBValue", "_3PosCValue",
        ]
        for attr in expected:
            key = ("progButtons", attr)
            assert key in XML_FIELD_INDEX, f"Missing catalog entry: progButtons.{attr}"

    def test_total_field_count_increased(self):
        """Adding button/menu entries should bring total above 60."""
        assert len(XML_FIELDS) >= 60


# ═══════════════════════════════════════════════════════════════════
# Blob Preamble (file metadata, OOR Alert Interval)
# ═══════════════════════════════════════════════════════════════════


class TestBlobPreamble:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_has_preamble(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert bp is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_filename(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert bp.filename == "PAWSOVERMAWS.PRS"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_username(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert bp.username == "Abider"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_oor_off(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert bp.oor_alert_interval == 0
        assert bp.oor_display == "Off"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_gps(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert len(bp.gps_doubles) == 4
        assert bp.gps_doubles[0] == 136.0
        assert bp.gps_doubles[1] == 870.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pawsovermaws_marker(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        bp = extract_blob_preamble(prs)
        assert bp.marker_byte == 0x0E

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_preamble(self):
        prs = cached_parse_prs(BASELINE)
        bp = extract_blob_preamble(prs)
        assert bp is not None
        assert bp.oor_alert_interval == 0
        assert bp.oor_display == "Off"

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_gps(self):
        prs = cached_parse_prs(BASELINE)
        bp = extract_blob_preamble(prs)
        assert len(bp.gps_doubles) >= 2
        assert bp.gps_doubles[0] == 136.0
        assert bp.gps_doubles[1] == 870.0

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_oor_slow(self):
        prs = cached_parse_prs(OOR_SLOW)
        bp = extract_blob_preamble(prs)
        assert bp.oor_alert_interval == 1
        assert bp.oor_display == "Slow"

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_oor_medium(self):
        prs = cached_parse_prs(OOR_MED)
        bp = extract_blob_preamble(prs)
        assert bp.oor_alert_interval == 2
        assert bp.oor_display == "Medium"

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_oor_fast(self):
        prs = cached_parse_prs(OOR_FAST)
        bp = extract_blob_preamble(prs)
        assert bp.oor_alert_interval == 3
        assert bp.oor_display == "Fast"

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_oor_nonzero_clears_gps(self):
        """When OOR > 0, GPS doubles should be empty (byte overlap)."""
        prs = cached_parse_prs(OOR_FAST)
        bp = extract_blob_preamble(prs)
        assert bp.gps_doubles == []

    def test_oor_display_values(self):
        assert OOR_ALERT_VALUES == {0: "Off", 1: "Slow", 2: "Medium", 3: "Fast"}

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_every_option_file_has_preamble(self):
        """All test files should yield a valid preamble."""
        import os
        base = EVERY_OPT
        count = 0
        for f in sorted(os.listdir(base)):
            if not f.endswith('.PRS'):
                continue
            prs = cached_parse_prs(base / f)
            bp = extract_blob_preamble(prs)
            assert bp is not None, f"No preamble for {f}"
            count += 1
        assert count == 33  # all test files

    @pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
    def test_claude_test_preamble_via_ct99(self):
        """claude test.PRS has no CProgButtons; metadata comes from CT99 tail."""
        prs = cached_parse_prs(CLAUDE_TEST)
        bp = extract_blob_preamble(prs)
        assert bp is not None

    @pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
    def test_claude_test_filename(self):
        """CT99 fallback should extract the personality filename."""
        prs = cached_parse_prs(CLAUDE_TEST)
        bp = extract_blob_preamble(prs)
        assert bp.filename == "claude test.PRS"

    @pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
    def test_claude_test_empty_username(self):
        """CT99 fallback with empty username LPS."""
        prs = cached_parse_prs(CLAUDE_TEST)
        bp = extract_blob_preamble(prs)
        assert bp.username == ""

    @pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
    def test_claude_test_band_limits(self):
        """CT99 fallback should extract XG-100P band limits."""
        prs = cached_parse_prs(CLAUDE_TEST)
        bp = extract_blob_preamble(prs)
        assert len(bp.gps_doubles) == 4
        assert bp.gps_doubles[0] == 136.0  # TxMin
        assert bp.gps_doubles[1] == 870.0  # TxMax
        assert bp.gps_doubles[2] == 136.0  # RxMin
        assert bp.gps_doubles[3] == 870.0  # RxMax

    @pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
    def test_claude_test_marker(self):
        """CT99 fallback should read the 0x0E marker byte."""
        prs = cached_parse_prs(CLAUDE_TEST)
        bp = extract_blob_preamble(prs)
        assert bp.marker_byte == 0x0E

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_not_from_ct99(self):
        """PAWSOVERMAWS has CProgButtons, so CT99 fallback should not be used."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        # CProgButtons exists, so strategy 1 is used
        has_prog = any(s.class_name == "CProgButtons" for s in prs.sections)
        assert has_prog
        bp = extract_blob_preamble(prs)
        assert bp.filename == "PAWSOVERMAWS.PRS"
        assert bp.username == "Abider"


# ─── CT99 structure tests ───────────────────────────────────────────


@pytest.mark.skipif(not PAWSOVERMAWS.exists() or not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestCT99Structure:
    """Tests for CT99 (Type 99 Decode) binary section structure."""

    def test_ct99_present_in_both_files(self):
        """CT99 section should be present in both test files."""
        for f in [CLAUDE_TEST, PAWSOVERMAWS]:
            prs = cached_parse_prs(f)
            sec = prs.get_section_by_class("CT99")
            assert sec is not None, f"CT99 missing from {f.name}"

    def test_ct99_class_header(self):
        """CT99 class header should parse correctly."""
        from quickprs.record_types import parse_class_header
        prs = cached_parse_prs(CLAUDE_TEST)
        sec = prs.get_section_by_class("CT99")
        name, byte1, byte2, _ = parse_class_header(sec.raw, 0)
        assert name == "CT99"
        assert byte1 == 0x64
        assert byte2 == 0x00

    def test_ct99_fixed_prefix_size(self):
        """CT99 data should have at least 103 bytes (3 blocks + 2 seps)."""
        from quickprs.record_types import parse_class_header
        for f in [CLAUDE_TEST, PAWSOVERMAWS]:
            prs = cached_parse_prs(f)
            sec = prs.get_section_by_class("CT99")
            _, _, _, cd = parse_class_header(sec.raw, 0)
            data = sec.raw[cd:]
            assert len(data) >= 103, f"{f.name}: CT99 data too short ({len(data)}B)"

    def test_ct99_slot_separators(self):
        """CT99 should have 2-byte separators at offsets 0x21 and 0x44."""
        from quickprs.record_types import parse_class_header
        for f in [CLAUDE_TEST, PAWSOVERMAWS]:
            prs = cached_parse_prs(f)
            sec = prs.get_section_by_class("CT99")
            _, _, _, cd = parse_class_header(sec.raw, 0)
            data = sec.raw[cd:]
            # Separators are at fixed positions 0x21 and 0x44
            sep1 = data[0x21:0x23]
            sep2 = data[0x44:0x46]
            assert sep1 == sep2, f"{f.name}: CT99 separators differ"
            assert len(sep1) == 2
            # High byte should be >= 0x80 (PRS separator pattern)
            assert sep1[1] >= 0x80

    def test_ct99_tone_slots_empty(self):
        """In both test files, CT99 tone slots are all zeros (no tones)."""
        from quickprs.record_types import parse_class_header
        for f in [CLAUDE_TEST, PAWSOVERMAWS]:
            prs = cached_parse_prs(f)
            sec = prs.get_section_by_class("CT99")
            _, _, _, cd = parse_class_header(sec.raw, 0)
            data = sec.raw[cd:]
            slot1 = data[0x00:0x21]
            slot2 = data[0x23:0x44]
            slot3 = data[0x46:0x67]
            assert all(b == 0 for b in slot1), "Slot 1 not empty"
            assert all(b == 0 for b in slot2), "Slot 2 not empty"
            assert all(b == 0 for b in slot3), "Slot 3 not empty"

    def test_ct99_claude_has_metadata_tail(self):
        """claude test.PRS CT99 has metadata tail (no CProgButtons)."""
        from quickprs.record_types import parse_class_header
        prs = cached_parse_prs(CLAUDE_TEST)
        sec = prs.get_section_by_class("CT99")
        _, _, _, cd = parse_class_header(sec.raw, 0)
        data = sec.raw[cd:]
        assert len(data) > 103, "CT99 should have metadata tail"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_ct99_pawsovermaws_no_metadata_tail(self):
        """PAWSOVERMAWS CT99 has exactly 103 bytes (no metadata tail)."""
        from quickprs.record_types import parse_class_header
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CT99")
        _, _, _, cd = parse_class_header(sec.raw, 0)
        data = sec.raw[cd:]
        assert len(data) == 103

    def test_ct99_separator_values(self):
        """CT99 separators differ between files (file-specific)."""
        from quickprs.record_types import parse_class_header
        prs1 = cached_parse_prs(CLAUDE_TEST)
        sec1 = prs1.get_section_by_class("CT99")
        _, _, _, cd1 = parse_class_header(sec1.raw, 0)
        data1 = sec1.raw[cd1:]
        sep_claude = data1[0x21:0x23]
        assert sep_claude == b'\x5e\x80'

        if PAWSOVERMAWS.exists():
            prs2 = cached_parse_prs(PAWSOVERMAWS)
            sec2 = prs2.get_section_by_class("CT99")
            _, _, _, cd2 = parse_class_header(sec2.raw, 0)
            data2 = sec2.raw[cd2:]
            sep_paws = data2[0x21:0x23]
            assert sep_paws == b'\x81\x82'
            assert sep_claude != sep_paws  # file-specific


# ═══════════════════════════════════════════════════════════════════
# CGenRadioOpts
# ═══════════════════════════════════════════════════════════════════


class TestCGenRadioOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_gen_radio_opts_present(self):
        """PAWSOVERMAWS has a CGenRadioOpts section."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = None
        for s in prs.sections:
            if s.class_name == "CGenRadioOpts":
                sec = s
                break
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_gen_radio_opts_data_size(self):
        """CGenRadioOpts data payload should be 41 bytes."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        for s in prs.sections:
            if s.class_name == "CGenRadioOpts":
                data = extract_section_data(s)
                assert len(data) == 41
                break

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_edacs_min_lid(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        for s in prs.sections:
            if s.class_name == "CGenRadioOpts":
                data = extract_section_data(s)
                fd = [f for f in GEN_RADIO_OPTS_MAP.fields
                      if f.name == "edacs_min_lid"][0]
                assert read_field(data, fd) == 1
                break

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_edacs_max_lid(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        for s in prs.sections:
            if s.class_name == "CGenRadioOpts":
                data = extract_section_data(s)
                fd = [f for f in GEN_RADIO_OPTS_MAP.fields
                      if f.name == "edacs_max_lid"][0]
                assert read_field(data, fd) == 16382
                break

    def test_gen_radio_opts_map_registered(self):
        assert "CGenRadioOpts" in OPTION_MAPS
        assert OPTION_MAPS["CGenRadioOpts"] is GEN_RADIO_OPTS_MAP

    def test_gen_radio_opts_field_count(self):
        assert len(GEN_RADIO_OPTS_MAP.fields) == 39

    def test_gen_radio_opts_coverage(self):
        c = GEN_RADIO_OPTS_MAP.coverage
        assert c == 1.0

    def test_gen_radio_opts_fields_within_bounds(self):
        for fd in GEN_RADIO_OPTS_MAP.fields:
            assert fd.offset + fd.size <= GEN_RADIO_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_npspac_override(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields
              if f.name == "npspac_override"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_noise_cancellation_type(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields
              if f.name == "noise_cancellation_type"][0]
        assert read_field(data, fd) == "Method A"

    def test_gen_radio_opts_no_overlap(self):
        used = set()
        for fd in GEN_RADIO_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gen_radio_byte_19(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields if f.name == "gen_radio_byte_19"][0]
        assert read_field(data, fd) == 160

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gen_radio_byte_30(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields if f.name == "gen_radio_byte_30"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gen_radio_byte_33(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields if f.name == "gen_radio_byte_33"][0]
        assert read_field(data, fd) == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gen_radio_byte_37(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGenRadioOpts")
        data = extract_section_data(sec)
        fd = [f for f in GEN_RADIO_OPTS_MAP.fields if f.name == "gen_radio_byte_37"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_gen_radio_opts(self):
        """Baseline test file should NOT have CGenRadioOpts."""
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CGenRadioOpts"


# ─── CDTMFOpts tests ─────────────────────────────────────────────────

class TestCDTMFOpts:
    """Tests for CDTMFOpts binary field map (DTMF Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        assert len(data) == 56

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_start_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "start_delay"][0]
        assert read_field(data, fd) == 400.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_pause_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "pause_delay"][0]
        assert read_field(data, fd) == 1000.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_interdigit_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "interdigit_delay"][0]
        assert read_field(data, fd) == 100.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_hang_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "hang_delay"][0]
        assert read_field(data, fd) == 2000.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_tone_length_0_9(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "tone_length_0_9"][0]
        assert read_field(data, fd) == 70.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_tone_length_star_hash(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "tone_length_star_hash"][0]
        assert read_field(data, fd) == 200.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_side_tone(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "side_tone"][0]
        assert read_field(data, fd) == "Audible"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_no_pre_emphasis_filter(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDTMFOpts")
        data = extract_section_data(sec)
        fd = [f for f in DTMF_OPTS_MAP.fields if f.name == "no_pre_emphasis_filter"][0]
        assert read_field(data, fd) is False

    def test_dtmf_opts_registered(self):
        assert "CDTMFOpts" in OPTION_MAPS
        assert OPTION_MAPS["CDTMFOpts"] is DTMF_OPTS_MAP

    def test_dtmf_opts_field_count(self):
        assert len(DTMF_OPTS_MAP.fields) == 14

    def test_dtmf_opts_coverage(self):
        c = DTMF_OPTS_MAP.coverage
        assert c == 1.0

    def test_dtmf_opts_fields_within_bounds(self):
        for fd in DTMF_OPTS_MAP.fields:
            assert fd.offset + fd.size <= DTMF_OPTS_MAP.data_size

    def test_dtmf_opts_no_overlap(self):
        used = set()
        for fd in DTMF_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_dtmf_opts(self):
        """Baseline test file should NOT have CDTMFOpts."""
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CDTMFOpts"

    def test_double_read_write_roundtrip(self):
        """Verify double field type round-trips through read/write."""
        fd = FieldDef(
            offset=0, size=8, name="test_double",
            display_name="Test Double", field_type="double",
        )
        data = b'\x00' * 16
        data = write_field(data, fd, 1234.5)
        assert read_field(data, fd) == 1234.5


# ─── CTimerOpts tests ────────────────────────────────────────────────

class TestCTimerOpts:
    """Tests for CTimerOpts binary field map (Timer Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CTimerOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CTimerOpts")
        data = extract_section_data(sec)
        assert len(data) == 82

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_cct(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CTimerOpts")
        data = extract_section_data(sec)
        fd = [f for f in TIMER_OPTS_MAP.fields if f.name == "cct"][0]
        assert read_field(data, fd) == 60.0

    def test_timer_opts_registered(self):
        assert "CTimerOpts" in OPTION_MAPS
        assert OPTION_MAPS["CTimerOpts"] is TIMER_OPTS_MAP

    def test_timer_opts_field_count(self):
        assert len(TIMER_OPTS_MAP.fields) == 26  # 4 prefix + 8 doubles + timer_byte_63

    def test_timer_opts_fields_within_bounds(self):
        for fd in TIMER_OPTS_MAP.fields:
            assert fd.offset + fd.size <= TIMER_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_timer_field_12(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CTimerOpts")
        data = extract_section_data(sec)
        fd = [f for f in TIMER_OPTS_MAP.fields if f.name == "timer_field_12"][0]
        assert read_field(data, fd) == 1.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_timer_byte_63(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CTimerOpts")
        data = extract_section_data(sec)
        fd = [f for f in TIMER_OPTS_MAP.fields if f.name == "timer_byte_63"][0]
        assert read_field(data, fd) == 30

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_timer_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CTimerOpts"


# ─── CSupervisoryOpts tests ──────────────────────────────────────────

class TestCSupervisoryOpts:
    """Tests for CSupervisoryOpts binary field map (Supervisory Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSupervisoryOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSupervisoryOpts")
        data = extract_section_data(sec)
        assert len(data) == 36

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_emergency_key_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSupervisoryOpts")
        data = extract_section_data(sec)
        fd = [f for f in SUPERVISORY_OPTS_MAP.fields
              if f.name == "emergency_key_delay"][0]
        assert read_field(data, fd) == 1.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_emergency_autokey_timeout(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSupervisoryOpts")
        data = extract_section_data(sec)
        fd = [f for f in SUPERVISORY_OPTS_MAP.fields
              if f.name == "emergency_autokey_timeout"][0]
        assert read_field(data, fd) == 0.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_emergency_autocycle_timeout(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSupervisoryOpts")
        data = extract_section_data(sec)
        fd = [f for f in SUPERVISORY_OPTS_MAP.fields
              if f.name == "emergency_autocycle_timeout"][0]
        assert read_field(data, fd) == 0.0

    def test_supervisory_opts_registered(self):
        assert "CSupervisoryOpts" in OPTION_MAPS
        assert OPTION_MAPS["CSupervisoryOpts"] is SUPERVISORY_OPTS_MAP

    def test_supervisory_opts_field_count(self):
        assert len(SUPERVISORY_OPTS_MAP.fields) == 8

    def test_supervisory_opts_coverage(self):
        c = SUPERVISORY_OPTS_MAP.coverage
        assert c == 1.0

    def test_supervisory_opts_fields_within_bounds(self):
        for fd in SUPERVISORY_OPTS_MAP.fields:
            assert fd.offset + fd.size <= SUPERVISORY_OPTS_MAP.data_size

    def test_supervisory_opts_no_overlap(self):
        used = set()
        for fd in SUPERVISORY_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_supervisory_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CSupervisoryOpts"


# ─── CPowerUpOpts tests ──────────────────────────────────────────────

class TestCPowerUpOpts:
    """Tests for CPowerUpOpts binary field map (Power Up Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        assert len(data) == 36

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_squelch_level(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields
              if f.name == "squelch_level"][0]
        assert read_field(data, fd) == 9

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_max_bad_pin_entries(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields
              if f.name == "max_bad_pin_entries"][0]
        assert read_field(data, fd) == 5

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_power_up_selection(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields
              if f.name == "power_up_selection"][0]
        assert read_field(data, fd) == "Default"

    def test_power_up_opts_registered(self):
        assert "CPowerUpOpts" in OPTION_MAPS
        assert OPTION_MAPS["CPowerUpOpts"] is POWER_UP_OPTS_MAP

    def test_power_up_opts_fields_within_bounds(self):
        for fd in POWER_UP_OPTS_MAP.fields:
            assert fd.offset + fd.size <= POWER_UP_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_power_up_byte_11(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields if f.name == "power_up_byte_11"][0]
        assert read_field(data, fd) == 15

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_power_up_byte_13(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields if f.name == "power_up_byte_13"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_power_up_byte_20(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields if f.name == "power_up_byte_20"][0]
        assert read_field(data, fd) == 40

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_power_up_byte_22(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPowerUpOpts")
        data = extract_section_data(sec)
        fd = [f for f in POWER_UP_OPTS_MAP.fields if f.name == "power_up_byte_22"][0]
        assert read_field(data, fd) == 6

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_power_up_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CPowerUpOpts"


# ─── CScanOpts tests ─────────────────────────────────────────────────

class TestCScanOpts:
    """Tests for CScanOpts binary field map (Scan Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        assert len(data) == 33

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_always_scan_selected_chan(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "always_scan_selected_chan"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_scan_after_ptt(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "scan_after_ptt"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_conv_pri_scan_hang_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "conv_pri_scan_hang_time"][0]
        assert read_field(data, fd) == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_band_hunt_interval(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "band_hunt_interval"][0]
        assert read_field(data, fd) == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_scan_with_channel_guard(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "scan_with_channel_guard"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_alternate_scan(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "alternate_scan"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_conv_pri_scan_with_cg(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "conv_pri_scan_with_cg"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_universal_hang_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields
              if f.name == "universal_hang_time"][0]
        assert read_field(data, fd) == 0.0

    def test_scan_opts_registered(self):
        assert "CScanOpts" in OPTION_MAPS
        assert OPTION_MAPS["CScanOpts"] is SCAN_OPTS_MAP

    def test_scan_opts_fields_within_bounds(self):
        for fd in SCAN_OPTS_MAP.fields:
            assert fd.offset + fd.size <= SCAN_OPTS_MAP.data_size

    def test_scan_opts_no_overlap(self):
        used = set()
        for fd in SCAN_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_scan_byte_19(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SCAN_OPTS_MAP.fields if f.name == "scan_byte_19"][0]
        assert read_field(data, fd) == 64

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_scan_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CScanOpts"


# ─── CDiagnosticOpts tests ───────────────────────────────────────────

class TestCDiagnosticOpts:
    """Tests for CDiagnosticOpts binary field map (Diagnostic Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDiagnosticOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDiagnosticOpts")
        data = extract_section_data(sec)
        assert len(data) == 8

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_ip_echo(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDiagnosticOpts")
        data = extract_section_data(sec)
        fd = [f for f in DIAGNOSTIC_OPTS_MAP.fields
              if f.name == "ip_echo"][0]
        assert read_field(data, fd) is True

    def test_diagnostic_opts_registered(self):
        assert "CDiagnosticOpts" in OPTION_MAPS
        assert OPTION_MAPS["CDiagnosticOpts"] is DIAGNOSTIC_OPTS_MAP

    def test_diagnostic_opts_fields_within_bounds(self):
        for fd in DIAGNOSTIC_OPTS_MAP.fields:
            assert fd.offset + fd.size <= DIAGNOSTIC_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_diagnostic_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CDiagnosticOpts"


# ─── CMdcOpts tests ─────────────────────────────────────────────────

class TestCMdcOpts:
    """Tests for CMdcOpts binary field map (Signaling Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        assert len(data) == 24

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_system_pretime(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "system_pretime"][0]
        assert read_field(data, fd) == 750

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_interpacket_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "interpacket_delay"][0]
        assert read_field(data, fd) == 500

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_mdc_hang_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "mdc_hang_time"][0]
        assert read_field(data, fd) == 7

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_mdc_emergency_enable(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "mdc_emergency_enable"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_mdc_emergency_ack_tone(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "mdc_emergency_ack_tone"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_send_preamble_during_pretime(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "send_preamble_during_pretime"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enhanced_id_system_pretime(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "enhanced_id_system_pretime"][0]
        assert read_field(data, fd) == 750

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enhanced_id_hang_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "enhanced_id_hang_time"][0]
        assert read_field(data, fd) == 7

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_emergency_tone_volume(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "emergency_tone_volume"][0]
        assert read_field(data, fd) == 31

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_emergency_max_tx_power(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "emergency_max_tx_power"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enhanced_emergency_ack_tone(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "enhanced_emergency_ack_tone"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_alternate_alert_tone(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "alternate_alert_tone"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_mdc_encode_trigger(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "mdc_encode_trigger"][0]
        assert read_field(data, fd) == "PTT Press"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enhanced_id_encode_trigger(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields
              if f.name == "enhanced_id_encode_trigger"][0]
        assert read_field(data, fd) == "None"

    def test_mdc_opts_registered(self):
        assert "CMdcOpts" in OPTION_MAPS
        assert OPTION_MAPS["CMdcOpts"] is MDC_OPTS_MAP

    def test_mdc_opts_fields_within_bounds(self):
        for fd in MDC_OPTS_MAP.fields:
            assert fd.offset + fd.size <= MDC_OPTS_MAP.data_size

    def test_mdc_opts_no_overlap(self):
        used = set()
        for fd in MDC_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mdc_bool_12(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMdcOpts")
        data = extract_section_data(sec)
        fd = [f for f in MDC_OPTS_MAP.fields if f.name == "mdc_bool_12"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_mdc_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CMdcOpts"


# ─── CSecurityPolicy tests ──────────────────────────────────────────

class TestCSecurityPolicy:
    """Tests for CSecurityPolicy binary field map (Security Policy)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSecurityPolicy")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSecurityPolicy")
        data = extract_section_data(sec)
        assert len(data) == 2

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_k_erasure_unit_disable(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSecurityPolicy")
        data = extract_section_data(sec)
        fd = [f for f in SECURITY_POLICY_MAP.fields
              if f.name == "k_erasure_unit_disable"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_k_erasure_zeroize(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSecurityPolicy")
        data = extract_section_data(sec)
        fd = [f for f in SECURITY_POLICY_MAP.fields
              if f.name == "k_erasure_zeroize"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_full_coverage(self):
        """CSecurityPolicy is 100% mapped (2/2 bytes)."""
        assert SECURITY_POLICY_MAP.data_size == 2
        mapped_bytes = set()
        for fd in SECURITY_POLICY_MAP.fields:
            for i in range(fd.size):
                mapped_bytes.add(fd.offset + i)
        assert len(mapped_bytes) == 2

    def test_security_policy_registered(self):
        assert "CSecurityPolicy" in OPTION_MAPS
        assert OPTION_MAPS["CSecurityPolicy"] is SECURITY_POLICY_MAP

    def test_security_policy_fields_within_bounds(self):
        for fd in SECURITY_POLICY_MAP.fields:
            assert fd.offset + fd.size <= SECURITY_POLICY_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_security_policy(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CSecurityPolicy"


# ─── CStatus tests ──────────────────────────────────────────────────

class TestCStatus:
    """Tests for CStatus binary field map (Status/Message Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        assert len(data) == 7

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_mode_hang_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        fd = [f for f in STATUS_OPTS_MAP.fields
              if f.name == "mode_hang_time"][0]
        assert read_field(data, fd) == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_select_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        fd = [f for f in STATUS_OPTS_MAP.fields
              if f.name == "select_time"][0]
        assert read_field(data, fd) == 2

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_transmit_type(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        fd = [f for f in STATUS_OPTS_MAP.fields
              if f.name == "transmit_type"][0]
        assert read_field(data, fd) == "AUTO"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_reset_on_system_change(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        fd = [f for f in STATUS_OPTS_MAP.fields
              if f.name == "reset_on_system_change"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_p25_standard_status_format(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CStatus")
        data = extract_section_data(sec)
        fd = [f for f in STATUS_OPTS_MAP.fields
              if f.name == "p25_standard_status_format"][0]
        assert read_field(data, fd) is False

    def test_status_opts_registered(self):
        assert "CStatus" in OPTION_MAPS
        assert OPTION_MAPS["CStatus"] is STATUS_OPTS_MAP

    def test_status_opts_fields_within_bounds(self):
        for fd in STATUS_OPTS_MAP.fields:
            assert fd.offset + fd.size <= STATUS_OPTS_MAP.data_size

    def test_status_opts_no_overlap(self):
        used = set()
        for fd in STATUS_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_status_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CStatus"


# ─── CSystemScanOpts tests ──────────────────────────────────────────

class TestCSystemScanOpts:
    """Tests for CSystemScanOpts binary field map (System Scan Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        assert len(data) == 24

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_scan_type_proscan(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields
              if f.name == "scan_type"][0]
        assert read_field(data, fd) == "ProScan"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_priority_scan(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields
              if f.name == "priority_scan"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_tone_suppress(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields
              if f.name == "tone_suppress"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_cc_loop_count(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields
              if f.name == "cc_loop_count"][0]
        assert read_field(data, fd) == 2.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_priority_scan_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields
              if f.name == "priority_scan_time"][0]
        assert read_field(data, fd) == 1.0

    def test_system_scan_opts_registered(self):
        assert "CSystemScanOpts" in OPTION_MAPS
        assert OPTION_MAPS["CSystemScanOpts"] is SYSTEM_SCAN_OPTS_MAP

    def test_system_scan_opts_fields_within_bounds(self):
        for fd in SYSTEM_SCAN_OPTS_MAP.fields:
            assert fd.offset + fd.size <= SYSTEM_SCAN_OPTS_MAP.data_size

    def test_system_scan_opts_no_overlap(self):
        used = set()
        for fd in SYSTEM_SCAN_OPTS_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_sys_scan_byte_5(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields if f.name == "sys_scan_byte_5"][0]
        assert read_field(data, fd) == 98

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_sys_scan_byte_6(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSystemScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in SYSTEM_SCAN_OPTS_MAP.fields if f.name == "sys_scan_byte_6"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_system_scan_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CSystemScanOpts"


# ─── CVoiceAnnunciation tests ───────────────────────────────────────

class TestCVoiceAnnunciation:
    """Tests for CVoiceAnnunciation binary field map."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        assert len(data) == 12

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enable_voice_annunciation(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields
              if f.name == "enable_voice_annunciation"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_enable_verbose_playback(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields
              if f.name == "enable_verbose_playback"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_power_on(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields
              if f.name == "power_on"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_minimum_volume(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields
              if f.name == "minimum_volume"][0]
        assert read_field(data, fd) == 0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_maximum_volume(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields
              if f.name == "maximum_volume"][0]
        assert read_field(data, fd) == 14

    def test_voice_annunciation_registered(self):
        assert "CVoiceAnnunciation" in OPTION_MAPS
        assert OPTION_MAPS["CVoiceAnnunciation"] is VOICE_ANNUNCIATION_MAP

    def test_voice_annunciation_fields_within_bounds(self):
        for fd in VOICE_ANNUNCIATION_MAP.fields:
            assert fd.offset + fd.size <= VOICE_ANNUNCIATION_MAP.data_size

    def test_voice_annunciation_no_overlap(self):
        used = set()
        for fd in VOICE_ANNUNCIATION_MAP.fields:
            for i in range(fd.size):
                assert (fd.offset + i) not in used
                used.add(fd.offset + i)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_va_byte_5(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVoiceAnnunciation")
        data = extract_section_data(sec)
        fd = [f for f in VOICE_ANNUNCIATION_MAP.fields if f.name == "va_byte_5"][0]
        assert read_field(data, fd) == 6

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_voice_annunciation(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CVoiceAnnunciation"


# ─── CType99Opts tests ──────────────────────────────────────────────

class TestCType99Opts:
    """Tests for CType99Opts binary field map (Type 99 Decode Options)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CType99Opts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CType99Opts")
        data = extract_section_data(sec)
        assert len(data) == 4

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_disable_after_ptt(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CType99Opts")
        data = extract_section_data(sec)
        fd = [f for f in TYPE99_OPTS_MAP.fields
              if f.name == "disable_after_ptt"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_auto_reset(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CType99Opts")
        data = extract_section_data(sec)
        fd = [f for f in TYPE99_OPTS_MAP.fields
              if f.name == "auto_reset"][0]
        assert read_field(data, fd) is False

    def test_type99_opts_registered(self):
        assert "CType99Opts" in OPTION_MAPS
        assert OPTION_MAPS["CType99Opts"] is TYPE99_OPTS_MAP

    def test_type99_opts_fields_within_bounds(self):
        for fd in TYPE99_OPTS_MAP.fields:
            assert fd.offset + fd.size <= TYPE99_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_type99_byte_2(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CType99Opts")
        data = extract_section_data(sec)
        fd = [f for f in TYPE99_OPTS_MAP.fields if f.name == "type99_byte_2"][0]
        assert read_field(data, fd) == 36

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_type99_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CType99Opts"


# ─── CDataOpts tests ────────────────────────────────────────────────

class TestCDataOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_data_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        assert sec is not None

    def test_data_opts_data_size(self):
        assert DATA_OPTS_MAP.data_size == 41

    def test_data_opts_field_count(self):
        assert len(DATA_OPTS_MAP.fields) >= 16

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ptt_receive_data(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "ptt_receive_data"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ptt_transmit_data(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "ptt_transmit_data"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_tx_data_overrides(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "tx_data_overrides_rx_grp_call"][0]
        assert read_field(data, fd) is False

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_data_interface_protocol(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "data_interface_protocol"][0]
        assert read_field(data, fd) == "PPP/SLIP"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gps_mic_sample_interval(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "gps_mic_sample_interval"][0]
        assert read_field(data, fd) == 5

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_dcs_max_frame_retries(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "dcs_max_frame_retries"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_dcs_ack_response_timeout(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "dcs_ack_response_timeout"][0]
        assert read_field(data, fd) == 10  # 10 * 100 = 1000ms

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_dcs_data_response_timeout(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "dcs_data_response_timeout"][0]
        assert read_field(data, fd) == 80  # 80 * 100 = 8000ms

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ppp_slip_retry_count(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "ppp_slip_retry_count"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ppp_slip_retry_interval(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "ppp_slip_retry_interval"][0]
        assert read_field(data, fd) == 15

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ppp_slip_ttl(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "ppp_slip_ttl"][0]
        assert read_field(data, fd) == 29

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_service_address(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "service_address"][0]
        assert read_field(data, fd) == "192.168.0.14"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mdt_address(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "mdt_address"][0]
        assert read_field(data, fd) == "192.168.0.15"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_serial_baud_rate(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "serial_baud_rate"][0]
        assert read_field(data, fd) == "19200"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_serial_stop_bits(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDataOpts")
        data = extract_section_data(sec)
        fd = [f for f in DATA_OPTS_MAP.fields
              if f.name == "serial_stop_bits"][0]
        assert read_field(data, fd) == "One"

    def test_data_opts_registered(self):
        assert "CDataOpts" in OPTION_MAPS
        assert OPTION_MAPS["CDataOpts"] is DATA_OPTS_MAP

    def test_data_opts_no_overlap(self):
        used = set()
        for f in DATA_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_data_opts_within_bounds(self):
        for fd in DATA_OPTS_MAP.fields:
            assert fd.offset + fd.size <= DATA_OPTS_MAP.data_size

    def test_ipv4_read_write_roundtrip(self):
        fd = FieldDef(0, 4, "test_ip", "Test IP", "ipv4")
        data = bytes([192, 168, 1, 100, 0, 0])
        assert read_field(data, fd) == "192.168.1.100"
        written = write_field(bytes(6), fd, "192.168.1.100")
        assert written[0:4] == bytes([192, 168, 1, 100])

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_data_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CDataOpts"


# ─── CSndcpOpts tests ───────────────────────────────────────────────

class TestCSndcpOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_sndcp_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSndcpOpts")
        assert sec is not None

    def test_sndcp_opts_data_size(self):
        assert SNDCP_OPTS_MAP.data_size == 8

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_holdoff_timer(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CSndcpOpts")
        data = extract_section_data(sec)
        fd = [f for f in SNDCP_OPTS_MAP.fields
              if f.name == "holdoff_timer_ms"][0]
        assert read_field(data, fd) == 2000

    def test_sndcp_opts_registered(self):
        assert "CSndcpOpts" in OPTION_MAPS
        assert OPTION_MAPS["CSndcpOpts"] is SNDCP_OPTS_MAP

    def test_sndcp_opts_within_bounds(self):
        for fd in SNDCP_OPTS_MAP.fields:
            assert fd.offset + fd.size <= SNDCP_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_sndcp_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CSndcpOpts"


# ─── CGEstarOpts tests ──────────────────────────────────────────────

class TestCGEstarOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gestar_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        assert sec is not None

    def test_gestar_opts_data_size(self):
        assert GESTAR_OPTS_MAP.data_size == 35

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_start_delay(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        data = extract_section_data(sec)
        fd = [f for f in GESTAR_OPTS_MAP.fields
              if f.name == "start_delay"][0]
        assert read_field(data, fd) == 360.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_emer_repeat(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        data = extract_section_data(sec)
        fd = [f for f in GESTAR_OPTS_MAP.fields
              if f.name == "emer_repeat"][0]
        assert read_field(data, fd) == 5

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_p25c_repeat_emer_tone(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        data = extract_section_data(sec)
        fd = [f for f in GESTAR_OPTS_MAP.fields
              if f.name == "p25c_repeat_emer_tone"][0]
        assert read_field(data, fd) is True

    def test_gestar_opts_registered(self):
        assert "CGEstarOpts" in OPTION_MAPS
        assert OPTION_MAPS["CGEstarOpts"] is GESTAR_OPTS_MAP

    def test_gestar_opts_no_overlap(self):
        used = set()
        for f in GESTAR_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_gestar_opts_within_bounds(self):
        for fd in GESTAR_OPTS_MAP.fields:
            assert fd.offset + fd.size <= GESTAR_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gestar_byte_21(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        data = extract_section_data(sec)
        fd = [f for f in GESTAR_OPTS_MAP.fields if f.name == "gestar_byte_21"][0]
        assert read_field(data, fd) == 32

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_gestar_byte_22(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CGEstarOpts")
        data = extract_section_data(sec)
        fd = [f for f in GESTAR_OPTS_MAP.fields if f.name == "gestar_byte_22"][0]
        assert read_field(data, fd) == 32

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_gestar_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CGEstarOpts"


# ─── CProSoundOpts (ProScan) tests ──────────────────────────────────

class TestCProSoundOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_prosound_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        assert sec is not None

    def test_proscan_opts_data_size(self):
        assert PROSCAN_OPTS_MAP.data_size == 28

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_sensitivity(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields
              if f.name == "sensitivity"][0]
        assert read_field(data, fd) == 3.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_system_sample_time(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields
              if f.name == "system_sample_time"][0]
        assert read_field(data, fd) == 250.0

    def test_proscan_opts_registered(self):
        assert "CProSoundOpts" in OPTION_MAPS
        assert OPTION_MAPS["CProSoundOpts"] is PROSCAN_OPTS_MAP

    def test_proscan_opts_no_overlap(self):
        used = set()
        for f in PROSCAN_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_proscan_opts_within_bounds(self):
        for fd in PROSCAN_OPTS_MAP.fields:
            assert fd.offset + fd.size <= PROSCAN_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_17(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_17"][0]
        assert read_field(data, fd) == 5

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_19(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_19"][0]
        assert read_field(data, fd) == 31

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_21(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_21"][0]
        assert read_field(data, fd) == 21

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_23(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_23"][0]
        assert read_field(data, fd) == 31

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_25(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_25"][0]
        assert read_field(data, fd) == 18

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_proscan_param_27(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProSoundOpts")
        data = extract_section_data(sec)
        fd = [f for f in PROSCAN_OPTS_MAP.fields if f.name == "proscan_param_27"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_prosound_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CProSoundOpts"


# ─── CVgOpts (Digital Voice Options) tests ─────────────────────────

class TestCVgOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_vg_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        assert sec is not None

    def test_vg_opts_data_size(self):
        assert VG_OPTS_MAP.data_size == 54

    def test_vg_opts_field_count(self):
        assert len(VG_OPTS_MAP.fields) == 54

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_tx_data_polarity(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        fd = [f for f in VG_OPTS_MAP.fields
              if f.name == "tx_data_polarity"][0]
        assert read_field(data, fd) == "Normal"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_rx_data_polarity(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        fd = [f for f in VG_OPTS_MAP.fields
              if f.name == "rx_data_polarity"][0]
        assert read_field(data, fd) == "Normal"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_encryption_key_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        fd = [f for f in VG_OPTS_MAP.fields
              if f.name == "encryption_key_size"][0]
        assert read_field(data, fd) == "16 Bytes"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_encryption_mode(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        fd = [f for f in VG_OPTS_MAP.fields
              if f.name == "encryption_mode"][0]
        assert read_field(data, fd) == "Forced On"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_max_key_bank(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        fd = [f for f in VG_OPTS_MAP.fields
              if f.name == "max_key_bank"][0]
        assert read_field(data, fd) == 0

    def test_vg_opts_registered(self):
        assert "CVgOpts" in OPTION_MAPS
        assert OPTION_MAPS["CVgOpts"] is VG_OPTS_MAP

    def test_vg_opts_no_overlap(self):
        used = set()
        for f in VG_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_vg_opts_within_bounds(self):
        for fd in VG_OPTS_MAP.fields:
            assert fd.offset + fd.size <= VG_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_vg_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CVgOpts"


# ─── CConvScanOpts tests ──────────────────────────────────────────

class TestCConvScanOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_conv_scan_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CConvScanOpts")
        assert sec is not None

    def test_conv_scan_opts_data_size(self):
        assert CONV_SCAN_OPTS_MAP.data_size == 30

    def test_conv_scan_opts_field_count(self):
        assert len(CONV_SCAN_OPTS_MAP.fields) == 23

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_conv_scan_booleans_stride2(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CConvScanOpts")
        data = extract_section_data(sec)
        # Original stride-2 bools at offsets 0,2,4,6 are True
        for fd in CONV_SCAN_OPTS_MAP.fields:
            if fd.field_type == "bool" and fd.name.startswith("conv_scan_opt"):
                assert read_field(data, fd) is True, f"{fd.name} should be True"
        # Gap bools at offsets 1,3,5 are False
        for fd in CONV_SCAN_OPTS_MAP.fields:
            if fd.field_type == "bool" and fd.name.startswith("conv_scan_gap"):
                assert read_field(data, fd) is False, f"{fd.name} should be False"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_conv_scan_mode(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CConvScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in CONV_SCAN_OPTS_MAP.fields
              if f.name == "conv_scan_mode"][0]
        assert read_field(data, fd) == 2

    def test_conv_scan_opts_registered(self):
        assert "CConvScanOpts" in OPTION_MAPS
        assert OPTION_MAPS["CConvScanOpts"] is CONV_SCAN_OPTS_MAP

    def test_conv_scan_opts_no_overlap(self):
        used = set()
        for f in CONV_SCAN_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_conv_scan_opts_within_bounds(self):
        for fd in CONV_SCAN_OPTS_MAP.fields:
            assert fd.offset + fd.size <= CONV_SCAN_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_conv_scan_double_9(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CConvScanOpts")
        data = extract_section_data(sec)
        fd = [f for f in CONV_SCAN_OPTS_MAP.fields
              if f.name == "conv_scan_double_9"][0]
        assert read_field(data, fd) == 2.0

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_conv_scan_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CConvScanOpts"


# ─── CDisplayOpts tests ───────────────────────────────────────────

class TestCDisplayOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_display_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDisplayOpts")
        assert sec is not None

    def test_display_opts_data_size(self):
        assert DISPLAY_OPTS_MAP.data_size == 37

    def test_display_opts_field_count(self):
        assert len(DISPLAY_OPTS_MAP.fields) == 30

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_display_booleans_all_true(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDisplayOpts")
        data = extract_section_data(sec)
        for fd in DISPLAY_OPTS_MAP.fields:
            if fd.field_type == "bool":
                assert read_field(data, fd) is True, f"{fd.name} should be True"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_display_opt_byte_12(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDisplayOpts")
        data = extract_section_data(sec)
        fd = [f for f in DISPLAY_OPTS_MAP.fields
              if f.name == "display_opt_byte_12"][0]
        assert read_field(data, fd) == 42

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_display_opt_double_15(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CDisplayOpts")
        data = extract_section_data(sec)
        fd = [f for f in DISPLAY_OPTS_MAP.fields
              if f.name == "display_opt_double_15"][0]
        assert read_field(data, fd) == 3.5

    def test_display_opts_registered(self):
        assert "CDisplayOpts" in OPTION_MAPS
        assert OPTION_MAPS["CDisplayOpts"] is DISPLAY_OPTS_MAP

    def test_display_opts_no_overlap(self):
        used = set()
        for f in DISPLAY_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_display_opts_within_bounds(self):
        for fd in DISPLAY_OPTS_MAP.fields:
            assert fd.offset + fd.size <= DISPLAY_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_display_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CDisplayOpts"


# ─── CIgnitionOpts tests ──────────────────────────────────────────

class TestCIgnitionOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ignition_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CIgnitionOpts")
        assert sec is not None

    def test_ignition_opts_data_size(self):
        assert IGNITION_OPTS_MAP.data_size == 10

    def test_ignition_opts_field_count(self):
        assert len(IGNITION_OPTS_MAP.fields) == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_ignition_timer(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CIgnitionOpts")
        data = extract_section_data(sec)
        fd = IGNITION_OPTS_MAP.fields[0]
        assert read_field(data, fd) == 20

    def test_ignition_opts_registered(self):
        assert "CIgnitionOpts" in OPTION_MAPS
        assert OPTION_MAPS["CIgnitionOpts"] is IGNITION_OPTS_MAP

    def test_ignition_opts_within_bounds(self):
        for fd in IGNITION_OPTS_MAP.fields:
            assert fd.offset + fd.size <= IGNITION_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_ignition_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CIgnitionOpts"


# ─── CNetworkOpts tests ───────────────────────────────────────────

class TestCNetworkOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        assert sec is not None

    def test_network_opts_data_size(self):
        assert NETWORK_OPTS_MAP.data_size == 38

    def test_network_opts_field_count(self):
        assert len(NETWORK_OPTS_MAP.fields) == 24

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_timer_1(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields
              if f.name == "network_timer_1"][0]
        assert read_field(data, fd) == 30.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_timer_2(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields
              if f.name == "network_timer_2"][0]
        assert read_field(data, fd) == 2.0

    def test_network_opts_registered(self):
        assert "CNetworkOpts" in OPTION_MAPS
        assert OPTION_MAPS["CNetworkOpts"] is NETWORK_OPTS_MAP

    def test_network_opts_no_overlap(self):
        used = set()
        for f in NETWORK_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_network_opts_within_bounds(self):
        for fd in NETWORK_OPTS_MAP.fields:
            assert fd.offset + fd.size <= NETWORK_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_byte_5(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields if f.name == "network_byte_5"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_byte_10(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields if f.name == "network_byte_10"][0]
        assert read_field(data, fd) == 2

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_byte_13(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields if f.name == "network_byte_13"][0]
        assert read_field(data, fd) is True

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_network_byte_15(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CNetworkOpts")
        data = extract_section_data(sec)
        fd = [f for f in NETWORK_OPTS_MAP.fields if f.name == "network_byte_15"][0]
        assert read_field(data, fd) == 5

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_network_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CNetworkOpts"


# ─── CMmsOpts tests ───────────────────────────────────────────────

class TestCMmsOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mms_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMmsOpts")
        assert sec is not None

    def test_mms_opts_data_size(self):
        assert MMS_OPTS_MAP.data_size == 13

    def test_mms_opts_field_count(self):
        assert len(MMS_OPTS_MAP.fields) == 13

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mms_retries(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMmsOpts")
        data = extract_section_data(sec)
        fd = [f for f in MMS_OPTS_MAP.fields
              if f.name == "mms_retries"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mms_param_1(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMmsOpts")
        data = extract_section_data(sec)
        fd = [f for f in MMS_OPTS_MAP.fields
              if f.name == "mms_param_1"][0]
        assert read_field(data, fd) == 4

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mms_param_2(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMmsOpts")
        data = extract_section_data(sec)
        fd = [f for f in MMS_OPTS_MAP.fields
              if f.name == "mms_param_2"][0]
        assert read_field(data, fd) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mms_timeout(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMmsOpts")
        data = extract_section_data(sec)
        fd = [f for f in MMS_OPTS_MAP.fields
              if f.name == "mms_timeout"][0]
        assert read_field(data, fd) == 15

    def test_mms_opts_registered(self):
        assert "CMmsOpts" in OPTION_MAPS
        assert OPTION_MAPS["CMmsOpts"] is MMS_OPTS_MAP

    def test_mms_opts_no_overlap(self):
        used = set()
        for f in MMS_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_mms_opts_within_bounds(self):
        for fd in MMS_OPTS_MAP.fields:
            assert fd.offset + fd.size <= MMS_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_mms_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CMmsOpts"


# ─── CKeypadCtrlOpts tests ────────────────────────────────────────

class TestCKeypadCtrlOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_keypad_ctrl_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CKeypadCtrlOpts")
        assert sec is not None

    def test_keypad_ctrl_opts_data_size(self):
        assert KEYPAD_CTRL_OPTS_MAP.data_size == 20

    def test_keypad_ctrl_opts_field_count(self):
        assert len(KEYPAD_CTRL_OPTS_MAP.fields) == 20

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_keypad_booleans_all_true(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CKeypadCtrlOpts")
        data = extract_section_data(sec)
        for fd in KEYPAD_CTRL_OPTS_MAP.fields:
            if fd.field_type == "bool":
                assert read_field(data, fd) is True, f"{fd.name} should be True"

    def test_keypad_ctrl_opts_registered(self):
        assert "CKeypadCtrlOpts" in OPTION_MAPS
        assert OPTION_MAPS["CKeypadCtrlOpts"] is KEYPAD_CTRL_OPTS_MAP

    def test_keypad_ctrl_opts_no_overlap(self):
        used = set()
        for f in KEYPAD_CTRL_OPTS_MAP.fields:
            for i in range(f.size):
                pos = f.offset + i
                assert pos not in used, f"Overlap at byte {pos}"
                used.add(pos)

    def test_keypad_ctrl_opts_within_bounds(self):
        for fd in KEYPAD_CTRL_OPTS_MAP.fields:
            assert fd.offset + fd.size <= KEYPAD_CTRL_OPTS_MAP.data_size

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_keypad_ctrl_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CKeypadCtrlOpts"


# ─── CMrkOpts tests ───────────────────────────────────────────────

class TestCMrkOpts:

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mrk_opts_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMrkOpts")
        assert sec is not None

    def test_mrk_opts_data_size(self):
        assert MRK_OPTS_MAP.data_size == 16

    def test_mrk_opts_field_count(self):
        assert len(MRK_OPTS_MAP.fields) == 16

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mrk_enable(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMrkOpts")
        data = extract_section_data(sec)
        fd = MRK_OPTS_MAP.fields[0]
        assert read_field(data, fd) is True

    def test_mrk_opts_registered(self):
        assert "CMrkOpts" in OPTION_MAPS
        assert OPTION_MAPS["CMrkOpts"] is MRK_OPTS_MAP

    def test_mrk_opts_within_bounds(self):
        for fd in MRK_OPTS_MAP.fields:
            assert fd.offset + fd.size <= MRK_OPTS_MAP.data_size

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_mrk_byte_12(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CMrkOpts")
        data = extract_section_data(sec)
        fd = [f for f in MRK_OPTS_MAP.fields if f.name == "mrk_byte_12"][0]
        assert read_field(data, fd) == 64

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_baseline_has_no_mrk_opts(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CMrkOpts"


# ─── Cross-section coverage and reserved byte verification ──────────


class TestFullCoverage:
    """Verify 100% field coverage and reserved byte values across all maps."""

    def test_all_maps_100_coverage(self):
        """Every OptionMap must have 100% byte coverage."""
        for name, om in OPTION_MAPS.items():
            assert om.coverage == 1.0, f"{name} coverage is {om.coverage:.1%}"

    def test_all_maps_no_unmapped(self):
        """Every OptionMap must have zero unmapped ranges."""
        for name, om in OPTION_MAPS.items():
            assert om.unmapped_ranges == [], (
                f"{name} has unmapped ranges: {om.unmapped_ranges}")

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_all_reserved_bytes_zero(self):
        """All _rsv_ fields should read 0, except CVgOpts bytes 6-21 (0x41)."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        # CVgOpts bytes 6-21 are encryption key placeholder (0x41), not zero
        vg_exceptions = {f"vg_rsv_{i}" for i in range(6, 22)}
        failures = []
        for name, om in OPTION_MAPS.items():
            sec = prs.get_section_by_class(name)
            if sec is None:
                continue
            data = extract_section_data(sec)
            if data is None:
                continue
            for fd in om.fields:
                if "_rsv_" in fd.name:
                    if fd.name in vg_exceptions:
                        continue
                    val = read_field(data, fd)
                    if val != 0:
                        failures.append(f"{name}.{fd.name}={val}")
        assert failures == [], f"Non-zero reserved bytes: {failures}"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_vg_opts_cue_data_reserved(self):
        """CVgOpts bytes 6-21 are 0x41 (encryption key placeholder), not zero."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CVgOpts")
        data = extract_section_data(sec)
        for off in range(6, 22):
            fd = [f for f in VG_OPTS_MAP.fields
                  if f.name == f"vg_rsv_{off}"][0]
            assert read_field(data, fd) == 0x41, (
                f"vg_rsv_{off} should be 0x41, got {read_field(data, fd)}")

    def test_total_field_count(self):
        """Sanity check total field count across all maps."""
        total = sum(len(om.fields) for om in OPTION_MAPS.values())
        assert total == 514

    def test_total_mapped_bytes(self):
        """Sanity check total mapped bytes = total data size."""
        total_mapped = 0
        total_size = 0
        for om in OPTION_MAPS.values():
            total_size += om.data_size
            mapped = set()
            for f in om.fields:
                for i in range(f.size):
                    mapped.add(f.offset + i)
            total_mapped += len(mapped)
        assert total_mapped == total_size == 722


# ═══════════════════════════════════════════════════════════════════
# Array-type unmapped sections (CICall, CPhoneCall, CPrgrmICall, etc.)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestCICallStructure:
    """Tests for CICall (Individual Call) array section structure."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CICall")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CICall")
        data = extract_section_data(sec)
        assert len(data) == 238

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_10_entries_with_separators(self):
        """CICall = 10 entries x 22B + 9 separators x 2B = 238B."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CICall")
        data = extract_section_data(sec)
        # 10*22 + 9*2 = 238
        assert 10 * 22 + 9 * 2 == 238
        # Check separator positions
        sep = b'\x3f\x82'
        for i in range(9):
            offset = (i + 1) * 22 + i * 2
            assert data[offset:offset + 2] == sep, f"Missing sep at entry {i}"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_entries_are_default(self):
        """All ICall entries in PAWSOVERMAWS are empty (default)."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CICall")
        data = extract_section_data(sec)
        for i in range(10):
            offset = i * 24
            entry = data[offset:offset + 22]
            # Default entry: all zeros except byte 7 = 0x01
            assert entry[7] == 0x01
            non_flag = entry[:7] + entry[8:]
            assert all(b == 0 for b in non_flag), f"Entry {i} not default"

    def test_baseline_has_no_icall(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CICall"


@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestCPhoneCallStructure:
    """Tests for CPhoneCall (Phone Call) array section structure."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPhoneCall")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPhoneCall")
        data = extract_section_data(sec)
        assert len(data) == 98

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_10_entries_with_separators(self):
        """CPhoneCall = 10 entries x 8B + 9 separators x 2B = 98B."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPhoneCall")
        data = extract_section_data(sec)
        assert 10 * 8 + 9 * 2 == 98
        sep = b'\x4c\x82'
        for i in range(9):
            offset = (i + 1) * 8 + i * 2
            assert data[offset:offset + 2] == sep, f"Missing sep at entry {i}"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_entries_are_default(self):
        """All PhoneCall entries in PAWSOVERMAWS are default."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPhoneCall")
        data = extract_section_data(sec)
        default_entry = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
        for i in range(10):
            offset = i * 10
            entry = data[offset:offset + 8]
            assert entry == default_entry, f"Entry {i} not default"

    def test_baseline_has_no_phone_call(self):
        prs = cached_parse_prs(BASELINE)
        for s in prs.sections:
            assert s.class_name != "CPhoneCall"


class TestCPrgrmCountSections:
    """Tests for CPrgrmICall/CPrgrmPhoneCall (entry count sections)."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_prgrm_icall_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPrgrmICall")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_prgrm_icall_count_is_10(self):
        """CPrgrmICall stores uint16 entry count = 10."""
        import struct
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPrgrmICall")
        data = extract_section_data(sec)
        assert len(data) == 2
        count = struct.unpack_from('<H', data, 0)[0]
        assert count == 10

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_prgrm_phone_call_count_is_10(self):
        """CPrgrmPhoneCall stores uint16 entry count = 10."""
        import struct
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CPrgrmPhoneCall")
        data = extract_section_data(sec)
        assert len(data) == 2
        count = struct.unpack_from('<H', data, 0)[0]
        assert count == 10


class TestCCustomScanList:
    """Tests for CCustomScanList section."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CCustomScanList")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CCustomScanList")
        data = extract_section_data(sec)
        assert len(data) == 8

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_empty_scan_list(self):
        """CCustomScanList is all zeros when no custom scan lists configured."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CCustomScanList")
        data = extract_section_data(sec)
        assert all(b == 0 for b in data)


class TestCProFileOpts:
    """Tests for CProFileOpts section."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProFileOpts")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProFileOpts")
        data = extract_section_data(sec)
        assert len(data) == 3

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_profile_values(self):
        """CProFileOpts stores profile config: [00 01 04]."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProFileOpts")
        data = extract_section_data(sec)
        assert data[0] == 0x00
        assert data[1] == 0x01
        assert data[2] == 0x04


@pytest.mark.skipif(not PAWSOVERMAWS.exists() or not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestCProgButtonsStructure:
    """Tests for CProgButtons binary section structure."""

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_section_present(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        assert sec is not None

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_data_size(self):
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        data = extract_section_data(sec)
        assert len(data) == 66

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_personality_name(self):
        """CProgButtons data[2] is LPS for personality filename."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        data = extract_section_data(sec)
        fn_len = data[2]
        assert fn_len == 16
        filename = data[3:3 + fn_len].decode('ascii')
        assert filename == "PAWSOVERMAWS.PRS"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_username(self):
        """CProgButtons stores username after personality name."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        data = extract_section_data(sec)
        # Skip: 2 nulls + LPS(16 chars) + 2 nulls = offset 21
        uname_len = data[21]
        assert uname_len == 6
        username = data[22:22 + uname_len].decode('ascii')
        assert username == "Abider"

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_band_limits(self):
        """CProgButtons contains 4 band-limit doubles (136.0, 870.0 x2)."""
        import struct
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        data = extract_section_data(sec)
        # Band limits at offset 30 (after name+user+marker+pad)
        tx_min = struct.unpack_from('<d', data, 30)[0]
        tx_max = struct.unpack_from('<d', data, 38)[0]
        rx_min = struct.unpack_from('<d', data, 46)[0]
        rx_max = struct.unpack_from('<d', data, 54)[0]
        assert tx_min == 136.0
        assert tx_max == 870.0
        assert rx_min == 136.0
        assert rx_max == 870.0

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(),
                        reason="PAWSOVERMAWS.PRS not available")
    def test_trailer(self):
        """CProgButtons ends with 7e 00 XX 00 (XX = trunk set count)."""
        prs = cached_parse_prs(PAWSOVERMAWS)
        sec = prs.get_section_by_class("CProgButtons")
        data = extract_section_data(sec)
        assert data[-4] == 0x7E
        assert data[-3] == 0x00
        assert data[-2] == 0x07  # 7 trunk sets
        assert data[-1] == 0x00

    def test_baseline_has_no_prog_buttons(self):
        """Baseline (minimal) file has no CProgButtons section."""
        prs = cached_parse_prs(CLAUDE_TEST)
        for s in prs.sections:
            assert s.class_name != "CProgButtons"
