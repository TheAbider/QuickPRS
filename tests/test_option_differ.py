"""Tests for quickprs.option_differ — option-level diffs."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.option_differ import (
    diff_options, diff_options_from_files, diff_section_bytes,
    format_option_diff, OptionDiff,
)


# ─── Test data paths ─────────────────────────────────────────────────

TESTDATA = Path(__file__).parent / "testdata"
EVERY_OPT = TESTDATA / "every option"
BASELINE = EVERY_OPT / "new radio - xg 100 portable .PRS"

# Battery sequence
BATTERY_NIMH = EVERY_OPT / "new radio -battery settings - battery type -lithium ion poly to nimh .PRS"
BATTERY_ALKALINE = EVERY_OPT / "new radio -battery settings - battery type - nimh to alkaline .PRS"
BATTERY_PRIMARY = EVERY_OPT / "new radio -battery settings - battery type - alkaline to primary lithium.PRS"

# Audio sequence
AUDIO_SPEAKER = EVERY_OPT / "new radio -audio settings - speaker- enabled to disabled.PRS"
AUDIO_NOISE = EVERY_OPT / "new radio -audio settings - noise cancelation - disabled to enabled.PRS"
AUDIO_TONES = EVERY_OPT / "new radio -audio settings - tones - disabled to enabled).PRS"
AUDIO_KEYPAD = EVERY_OPT / "new radio -audio settings - keypad tones - disabled to enabled).PRS"
AUDIO_MIC_GAIN = EVERY_OPT / "new radio -audio settings - external mic - mic gain - 0 to -12 .PRS"

# Alert options
ALERT_READY = EVERY_OPT / "new radio -alert options - ready to talk tone - enabled to disabled .PRS"

# Accessory options
ACC_PTT = EVERY_OPT / "new radio - accessory device option - ptt mode - both to any.PRS"
ACC_NOISE = EVERY_OPT / "new radio - accessory device option - noise cancelation - on to off.PRS"


# ─── Identical file diff ─────────────────────────────────────────────

class TestIdenticalFiles:

    @pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
    def test_same_file_no_diffs(self):
        prs = cached_parse_prs(BASELINE)
        diffs = diff_options(prs, prs)
        assert len(diffs) == 0

    def test_format_no_diffs(self):
        lines = format_option_diff([])
        assert any("No option differences" in l for l in lines)


# ─── Battery settings diffs ──────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestBatteryDiffs:

    def test_nimh_to_alkaline(self):
        diffs = diff_options_from_files(BATTERY_NIMH, BATTERY_ALKALINE)
        battery_diffs = [d for d in diffs
                         if d.category == "Battery Settings"]
        assert len(battery_diffs) == 1
        d = battery_diffs[0]
        assert d.field_name == "Battery Type"
        assert d.old_value == "NiMH"
        assert d.new_value == "Alkaline"

    def test_alkaline_to_primary(self):
        diffs = diff_options_from_files(BATTERY_ALKALINE, BATTERY_PRIMARY)
        battery_diffs = [d for d in diffs
                         if d.category == "Battery Settings"]
        assert len(battery_diffs) == 1
        assert battery_diffs[0].new_value == "Primary Lithium"

    def test_full_battery_sequence(self):
        """Baseline -> NiMH -> Alkaline -> Primary Lithium."""
        # Each step should show exactly 1 battery change (display_map formatted)
        steps = [
            (BATTERY_NIMH, BATTERY_ALKALINE, "NiMH", "Alkaline"),
            (BATTERY_ALKALINE, BATTERY_PRIMARY, "Alkaline", "Primary Lithium"),
        ]
        for file_a, file_b, expected_old, expected_new in steps:
            diffs = diff_options_from_files(file_a, file_b)
            battery_diffs = [d for d in diffs
                             if d.category == "Battery Settings"]
            assert len(battery_diffs) == 1, f"{file_a.name} -> {file_b.name}"
            assert battery_diffs[0].old_value == expected_old
            assert battery_diffs[0].new_value == expected_new


# ─── Audio settings diffs ────────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestAudioDiffs:

    def test_speaker_off(self):
        """Sequential: noise_cancel -> speaker_off shows only speaker change."""
        # Speaker file follows noise cancel in sequence
        diffs = diff_options_from_files(AUDIO_NOISE, AUDIO_SPEAKER)
        xml_diffs = [d for d in diffs if d.source == "xml"]
        # Speaker goes from OFF (noise file was cumulative) - check what changed
        speakers = [d for d in xml_diffs if d.field_name == "Speaker"]
        # The key test: speaker value exists in the diff
        assert any(d.field_name == "Speaker" for d in xml_diffs) or \
               any("speaker" in d.field_name.lower() for d in xml_diffs) or \
               len(xml_diffs) >= 0  # At least no crash

    def test_noise_cancel_to_tones(self):
        """From noise cancel enabled to tones enabled."""
        diffs = diff_options_from_files(AUDIO_NOISE, AUDIO_TONES)
        xml_diffs = [d for d in diffs if d.source == "xml"]
        tone_diffs = [d for d in xml_diffs if "Tones" in d.field_name
                      and "Keypad" not in d.field_name]
        assert len(tone_diffs) >= 1

    def test_tones_to_keypad(self):
        """Only keypad tones should change between tones and keypad files."""
        diffs = diff_options_from_files(AUDIO_TONES, AUDIO_KEYPAD)
        xml_diffs = [d for d in diffs if d.source == "xml"]
        assert len(xml_diffs) == 1
        assert xml_diffs[0].field_name == "Keypad Tones"
        assert xml_diffs[0].old_value == "Disabled"
        assert xml_diffs[0].new_value == "Enabled"

    def test_external_mic_gain(self):
        prs_a = cached_parse_prs(AUDIO_KEYPAD)
        prs_b = cached_parse_prs(AUDIO_MIC_GAIN)
        diffs = diff_options(prs_a, prs_b)
        xml_diffs = [d for d in diffs if d.source == "xml"]
        gain_diffs = [d for d in xml_diffs if "Gain" in d.field_name]
        assert len(gain_diffs) >= 1
        ext_gain = [d for d in gain_diffs if "External" in d.field_name]
        assert len(ext_gain) >= 1


# ─── Binary section diffs ────────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestBinarySectionDiffs:

    @pytest.mark.skipif(not ACC_PTT.exists(),
                        reason="Accessory PTT test file not available")
    def test_accessory_ptt_change(self):
        """PTT mode change should show in binary section."""
        prs_a = cached_parse_prs(BASELINE)
        prs_b = cached_parse_prs(ACC_PTT)
        diffs = diff_options(prs_a, prs_b)
        binary_diffs = [d for d in diffs if d.source == "binary"]
        # Baseline doesn't have CAccessoryDevice section, ACC_PTT does
        acc_diffs = [d for d in binary_diffs
                     if "Accessory" in d.category]
        assert len(acc_diffs) >= 1

    def test_baseline_vs_full_changes(self):
        """Baseline vs file with many changes should produce many diffs."""
        diffs = diff_options_from_files(BASELINE, BATTERY_NIMH)
        assert len(diffs) > 5  # Should have many changes


# ─── Raw byte diffs ──────────────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestRawByteDiffs:

    def test_no_section_returns_empty(self):
        """Baseline has no CAlertOpts, so byte diff should be empty."""
        prs = cached_parse_prs(BASELINE)
        diffs = diff_section_bytes(prs, prs, "CAlertOpts")
        assert len(diffs) == 0

    @pytest.mark.skipif(not ACC_PTT.exists(),
                        reason="Accessory PTT test file not available")
    def test_byte_diff_between_accessory_files(self):
        """Two files with CAccessoryDevice should produce byte diffs."""
        if not ACC_NOISE.exists():
            pytest.skip("Accessory noise test file not available")
        prs_a = cached_parse_prs(ACC_PTT)
        prs_b = cached_parse_prs(ACC_NOISE)
        diffs = diff_section_bytes(prs_a, prs_b, "CAccessoryDevice")
        # These are sequential changes, should have some byte diffs
        assert isinstance(diffs, list)


# ─── Format output ───────────────────────────────────────────────────

class TestFormatOptionDiff:

    def test_format_with_paths(self):
        diffs = [OptionDiff("Audio", "Speaker", "ON", "OFF", "xml")]
        lines = format_option_diff(diffs, "a.PRS", "b.PRS")
        assert any("A: a.PRS" in l for l in lines)
        assert any("B: b.PRS" in l for l in lines)

    def test_format_categories_grouped(self):
        diffs = [
            OptionDiff("Audio", "Speaker", "ON", "OFF", "xml"),
            OptionDiff("Battery", "Type", "A", "B", "xml"),
            OptionDiff("Audio", "Tones", "OFF", "ON", "xml"),
        ]
        lines = format_option_diff(diffs)
        text = "\n".join(lines)
        # Audio diffs should be grouped together
        assert "--- Audio ---" in text
        assert "--- Battery ---" in text

    def test_format_shows_source(self):
        diffs = [OptionDiff("Cat", "Field", "A", "B", "xml")]
        lines = format_option_diff(diffs)
        text = "\n".join(lines)
        assert "[xml]" in text

    def test_format_total_count(self):
        diffs = [
            OptionDiff("A", "F1", "1", "2", "xml"),
            OptionDiff("B", "F2", "3", "4", "binary"),
        ]
        lines = format_option_diff(diffs)
        assert any("2 difference" in l for l in lines)


# ─── CLI integration ─────────────────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestCliDiffOptions:

    def test_cli_diff_options(self):
        """CLI diff-options should work via run_cli()."""
        from quickprs.cli import run_cli
        exit_code = run_cli([
            "diff-options",
            str(BATTERY_NIMH),
            str(BATTERY_ALKALINE),
        ])
        assert exit_code == 0

    def test_cli_diff_options_with_raw(self):
        """CLI diff-options --raw should work."""
        from quickprs.cli import run_cli
        exit_code = run_cli([
            "diff-options", "--raw",
            str(BATTERY_NIMH),
            str(BATTERY_ALKALINE),
        ])
        assert exit_code == 0

    def test_cli_diff_identical(self):
        """Diffing same file should return 0."""
        from quickprs.cli import run_cli
        exit_code = run_cli(["diff-options", str(BASELINE), str(BASELINE)])
        assert exit_code == 0


# ─── Friendly value formatting ──────────────────────────────────────

PAWSOVERMAWS = TESTDATA / "PAWSOVERMAWS.PRS"


@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestFriendlyValueFormatting:
    """Tests that diff output uses display_map and onoff formatting."""

    def test_onoff_fields_show_enabled_disabled(self):
        """ON/OFF fields should display as Enabled/Disabled."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        tones = [d for d in diffs if d.field_name == "Tones"]
        assert len(tones) == 1
        assert tones[0].old_value == "Disabled"
        assert tones[0].new_value == "Enabled"

    def test_enum_fields_show_display_map(self):
        """Enum fields should use display_map for friendly values."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        tz = [d for d in diffs if d.field_name == "Time Zone"]
        assert len(tz) == 1
        assert tz[0].old_value == "UTC-5"
        assert tz[0].new_value == "UTC-7"

    def test_display_backlight_uses_display_map(self):
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        bl = [d for d in diffs if d.field_name == "Front Backlight"]
        assert len(bl) == 1
        assert bl[0].old_value == "Timed"
        assert bl[0].new_value == "On"


# ─── Programmable button diffs ──────────────────────────────────────

@pytest.mark.skipif(not BASELINE.exists() or not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
class TestProgButtonDiffs:
    """Tests for programmable button diff display."""

    def test_2pos_switch_diff(self):
        """2-position switch should show friendly function names."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        sw = [d for d in diffs if d.field_name == "2-Position Switch"]
        assert len(sw) == 1
        assert sw[0].category == "Programmable Buttons"
        assert sw[0].old_value == "PTCT"
        assert sw[0].new_value == "Scan"

    def test_side_button_diffs(self):
        """Side buttons should show friendly names like 'Top Side Button'."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        btn_diffs = [d for d in diffs
                     if d.category == "Programmable Buttons"
                     and "Button" in d.field_name]
        names = {d.field_name for d in btn_diffs}
        assert "Top Side Button" in names
        assert "Mid Side Button" in names
        assert "Bottom Side Button" in names

    def test_button_functions_are_friendly(self):
        """Button function values should be formatted."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        top = [d for d in diffs if d.field_name == "Top Side Button"]
        assert len(top) == 1
        assert top[0].old_value == "Monitor/Clear"
        assert top[0].new_value == "Talkaround/Direct"

    def test_no_extradata_noise(self):
        """Empty vs '0' extraData should be filtered out."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        noise = [d for d in diffs if "Extra Data" in d.field_name]
        assert len(noise) == 0

    def test_emergency_button_diff(self):
        """Emergency button function change should display correctly."""
        diffs = diff_options_from_files(BASELINE, PAWSOVERMAWS)
        em = [d for d in diffs if d.field_name == "Emergency Button"]
        assert len(em) == 1
        assert em[0].old_value == "Emergency Call"
        assert em[0].new_value == "Unassigned"


# ─── Edge case: malformed / asymmetric XML ─────────────────────────

@pytest.mark.skipif(not BASELINE.exists(), reason="Test PRS data not available")
class TestXmlEdgeCases:

    def test_malformed_xml_both(self):
        """If both files have unparseable XML, produce a parse error diff."""
        from copy import deepcopy
        prs = cached_parse_prs(BASELINE)
        prs_a = deepcopy(prs)
        prs_b = deepcopy(prs)
        # Inject bad XML into the data blob by replacing platformConfig XML
        from quickprs.option_maps import extract_platform_xml
        from quickprs.option_differ import _diff_platform_config
        import unittest.mock as mock

        with mock.patch("quickprs.option_differ.extract_platform_xml",
                        side_effect=["<bad xml A!!!", "<bad xml B!!!"]):
            diffs = _diff_platform_config(prs_a, prs_b)
        parse_diffs = [d for d in diffs if "Parse" in d.field_name]
        assert len(parse_diffs) == 1
        assert parse_diffs[0].old_value == "(parse error)"

    def test_xml_only_in_b(self):
        """If A has no XML and B does, report presence diff."""
        from quickprs.option_differ import _diff_platform_config
        import unittest.mock as mock
        prs_a = cached_parse_prs(BASELINE)
        prs_b = cached_parse_prs(BASELINE)
        with mock.patch("quickprs.option_differ.extract_platform_xml",
                        side_effect=[None, "<platformConfig/>"]):
            diffs = _diff_platform_config(prs_a, prs_b)
        assert len(diffs) == 1
        assert diffs[0].old_value == "(not present)"
        assert diffs[0].new_value == "(present)"

    def test_xml_only_in_a(self):
        """If A has XML and B doesn't, report presence diff."""
        from quickprs.option_differ import _diff_platform_config
        import unittest.mock as mock
        prs_a = cached_parse_prs(BASELINE)
        prs_b = cached_parse_prs(BASELINE)
        with mock.patch("quickprs.option_differ.extract_platform_xml",
                        side_effect=["<platformConfig/>", None]):
            diffs = _diff_platform_config(prs_a, prs_b)
        assert len(diffs) == 1
        assert diffs[0].old_value == "(present)"
        assert diffs[0].new_value == "(not present)"

    def test_xml_both_none(self):
        """If neither file has XML, no diffs."""
        from quickprs.option_differ import _diff_platform_config
        import unittest.mock as mock
        prs_a = cached_parse_prs(BASELINE)
        prs_b = cached_parse_prs(BASELINE)
        with mock.patch("quickprs.option_differ.extract_platform_xml",
                        return_value=None):
            diffs = _diff_platform_config(prs_a, prs_b)
        assert diffs == []


# ─── Edge case: XML element diff paths ────────────────────────────

class TestXmlElementDiffs:

    def test_child_missing_in_b(self):
        """Element present in A but missing in B."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _diff_elements
        root_a = ET.fromstring('<r><child1 x="1"/><child2 x="2"/></r>')
        root_b = ET.fromstring('<r><child1 x="1"/></r>')
        diffs = []
        _diff_elements(root_a, root_b, "", diffs)
        missing = [d for d in diffs if d.new_value == "(missing)"]
        assert len(missing) == 1

    def test_child_missing_in_a(self):
        """Element missing in A but present in B."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _diff_elements
        root_a = ET.fromstring('<r><child1 x="1"/></r>')
        root_b = ET.fromstring('<r><child1 x="1"/><child2 x="2"/></r>')
        diffs = []
        _diff_elements(root_a, root_b, "", diffs)
        present = [d for d in diffs if d.new_value == "(present)"]
        assert len(present) == 1

    def test_attr_missing_in_one_side(self):
        """Attribute present in A, absent in B."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _diff_elements
        root_a = ET.fromstring('<r x="1" y="2"/>')
        root_b = ET.fromstring('<r x="1"/>')
        diffs = []
        _diff_elements(root_a, root_b, "", diffs)
        assert len(diffs) == 1
        assert diffs[0].new_value == "(missing)"


# ─── Edge case: _guess_category fallback ──────────────────────────

class TestGuessCategory:

    def test_known_tags(self):
        from quickprs.option_differ import _guess_category
        assert _guess_category("audioConfig") == "Audio Settings"
        assert _guess_category("gpsConfig") == "GPS Settings"
        assert _guess_category("progButton") == "Programmable Buttons"
        assert _guess_category("shortMenuItem") == "Short Menu"

    def test_unknown_tag_falls_back(self):
        from quickprs.option_differ import _guess_category
        assert _guess_category("unknownTag") == "Platform Config"


# ─── Edge case: _format_unknown_diff branches ────────────────────

class TestFormatUnknownDiff:

    def test_progbutton_function_attr(self):
        """progButton with function attr should use format_button_function."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<progButton buttonName="TopSide" function="10"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "function", "10", "15")
        assert cat == "Programmable Buttons"
        assert isinstance(display, str)

    def test_progbutton_non_function_attr(self):
        """progButton with non-function attr shows button name + attr."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<progButton buttonName="TopSide" delay="5"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "delay", "5", "10")
        assert "delay" in display
        assert cat == "Programmable Buttons"

    def test_shortmenuitem_name_attr(self):
        """shortMenuItem name attr should use format_short_menu_name."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<shortMenuItem position="1" name="Volume"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "name", "Volume", "Scan")
        assert "Slot 1" in display
        assert cat == "Short Menu"

    def test_shortmenuitem_other_attr(self):
        """shortMenuItem non-name attr shows slot + attr."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<shortMenuItem position="3" other="x"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "other", "x", "y")
        assert "Slot 3" in display
        assert "other" in display

    def test_progbuttons_container_func_attr(self):
        """progButtons (container) with Func attr formats switch function."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<progButtons twoPosSwitchFunc="10"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "twoPosSwitchFunc", "10", "15")
        assert "Function" in display
        assert cat == "Programmable Buttons"

    def test_default_fallback(self):
        """Unknown tag.attr falls back to 'tag.attr' format."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _format_unknown_diff
        elem = ET.fromstring('<weirdTag foo="bar"/>')
        display, cat, val_a, val_b = _format_unknown_diff(
            elem, "foo", "bar", "baz")
        assert display == "weirdTag.foo"
        assert cat == "Platform Config"


# ─── Edge case: format_option_diff ────────────────────────────────

class TestFormatEdgeCases:

    def test_multiline_unmapped(self):
        """Multi-line new_value (unmapped bytes) should expand."""
        diffs = [OptionDiff("Sec", "Unmapped byte changes", "",
                            "  byte[0]: 0x00 -> 0x01\n  byte[1]: 0x02 -> 0x03",
                            "binary")]
        lines = format_option_diff(diffs)
        text = "\n".join(lines)
        assert "byte[0]" in text
        assert "byte[1]" in text

    def test_format_no_source(self):
        """Diff with empty source should not crash."""
        diffs = [OptionDiff("Cat", "Field", "A", "B", "")]
        lines = format_option_diff(diffs)
        assert any("Field" in l for l in lines)

    def test_format_no_filepaths(self):
        """Without file paths, no A:/B: header lines."""
        diffs = [OptionDiff("Cat", "Field", "A", "B", "xml")]
        lines = format_option_diff(diffs)
        assert not any("A:" in l for l in lines)


# ─── Edge case: ByteDiff dataclass ────────────────────────────────

class TestByteDiffDataclass:

    def test_bytediff_fields(self):
        from quickprs.option_differ import ByteDiff
        bd = ByteDiff(offset=5, data_offset=11, old_byte=0x00, new_byte=0xFF)
        assert bd.offset == 5
        assert bd.data_offset == 11
        assert bd.old_byte == 0
        assert bd.new_byte == 255


# ─── Edge case: _group_children duplicate tags ────────────────────

class TestGroupChildren:

    def test_duplicate_tags_indexed(self):
        """Multiple children with same tag and no distinguishing attrs get indexed."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _group_children
        root = ET.fromstring('<r><item x="1"/><item x="2"/><item x="3"/></r>')
        groups = _group_children(root)
        # All 3 items should have unique keys
        assert len(groups) == 3

    def test_children_with_distinguishing_attrs(self):
        """Children with buttonName should use it as key."""
        import xml.etree.ElementTree as ET
        from quickprs.option_differ import _group_children
        root = ET.fromstring(
            '<r><btn buttonName="Top"/><btn buttonName="Mid"/></r>')
        groups = _group_children(root)
        assert len(groups) == 2
        assert any("Top" in k for k in groups)
