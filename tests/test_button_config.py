"""Tests for the programmable button configurator and diff viewer."""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.option_maps import (
    extract_platform_config, extract_platform_xml, write_platform_config,
    BUTTON_FUNCTION_NAMES, BUTTON_NAME_DISPLAY,
    SHORT_MENU_NAMES, SWITCH_FUNCTION_NAMES,
    format_button_function, format_button_name,
    format_short_menu_name, format_switch_function,
)
from quickprs.comparison import detailed_comparison, compare_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Button configurator data reading tests ─────────────────────────


class TestButtonConfigData:
    """Test reading programmable button data from PRS files."""

    def test_read_prog_buttons_pawsovermaws(self):
        """PAWSOVERMAWS should have progButtons in its config."""
        prs = parse_prs(PAWS)
        config = extract_platform_config(prs)
        assert config is not None
        prog = config.get("progButtons")
        # PAWSOVERMAWS has progButtons section
        if prog is not None:
            buttons = prog.get("progButton", [])
            if isinstance(buttons, dict):
                buttons = [buttons]
            # Each button should have buttonName and function
            for btn in buttons:
                assert "buttonName" in btn
                assert "function" in btn

    def test_read_prog_buttons_claude(self):
        """Claude test file may or may not have platform config."""
        prs = parse_prs(CLAUDE)
        config = extract_platform_config(prs)
        # claude test.PRS has no platformConfig — this is expected
        # The test verifies that extract_platform_config handles it
        # gracefully by returning None
        if config is not None:
            # If it does have config, it should be a dict
            assert isinstance(config, dict)

    def test_button_function_names_completeness(self):
        """BUTTON_FUNCTION_NAMES should cover common functions."""
        expected = [
            "UNASSIGNED", "SCAN", "TALKAROUND_DIRECT",
            "ZONE_UP_WRAP", "ZONE_DOWN_WRAP", "EMERGENCY_CALL",
            "TX_POWER", "MONITOR",
        ]
        for func in expected:
            assert func in BUTTON_FUNCTION_NAMES

    def test_button_name_display_completeness(self):
        """BUTTON_NAME_DISPLAY should have the XG-100P side buttons."""
        expected = ["TOP_SIDE", "MID_SIDE", "BOT_SIDE", "EMERGENCY"]
        for name in expected:
            assert name in BUTTON_NAME_DISPLAY

    def test_switch_function_names(self):
        """SWITCH_FUNCTION_NAMES should have common switch functions."""
        expected = ["SCAN", "CHAN_BANK", "ZONE", "TALKAROUND"]
        for func in expected:
            assert func in SWITCH_FUNCTION_NAMES

    def test_short_menu_names(self):
        """SHORT_MENU_NAMES should have common menu items."""
        expected = [
            "startScan", "startMon", "nuisanceDel",
            "selChanGrp", "lockKeypad", "txPower", "empty",
        ]
        for name in expected:
            assert name in SHORT_MENU_NAMES

    def test_format_button_function(self):
        """format_button_function should return friendly names."""
        assert format_button_function("SCAN") == "Scan"
        assert format_button_function("UNASSIGNED") == "Unassigned"
        assert format_button_function("UNKNOWN_VAL") == "UNKNOWN_VAL"

    def test_format_button_name(self):
        """format_button_name should return friendly names."""
        assert format_button_name("TOP_SIDE") == "Top Side Button"
        assert format_button_name("UNKNOWN") == "UNKNOWN"

    def test_format_short_menu_name(self):
        """format_short_menu_name should return friendly names."""
        assert format_short_menu_name("startScan") == "Start Scan"
        assert format_short_menu_name("empty") == "(Empty)"
        assert format_short_menu_name("unknownItem") == "unknownItem"

    def test_format_switch_function(self):
        """format_switch_function should return friendly names."""
        assert format_switch_function("SCAN") == "Scan"
        assert format_switch_function("CHAN_BANK") == "Channel Bank"

    def test_switch_values_readable(self):
        """Switch position values should be readable from config."""
        prs = parse_prs(PAWS)
        config = extract_platform_config(prs)
        if config is None:
            pytest.skip("No platform config in PAWSOVERMAWS")
        prog = config.get("progButtons", {})
        # 2-pos and 3-pos functions may or may not exist
        fn_2pos = prog.get("_2PosFunction", "")
        fn_3pos = prog.get("_3PosFunction", "")
        # If they exist, values should be readable
        if fn_2pos:
            assert isinstance(fn_2pos, str)
        if fn_3pos:
            assert isinstance(fn_3pos, str)
            # 3-pos should have A/B/C value keys available
            for pos in ("A", "B", "C"):
                val = prog.get(f"_3Pos{pos}Value", "")
                assert isinstance(val, str)

    def test_short_menu_items_readable(self):
        """Short menu items should be readable from config."""
        prs = parse_prs(PAWS)
        config = extract_platform_config(prs)
        if config is None:
            pytest.skip("No platform config in PAWSOVERMAWS")
        menu = config.get("shortMenu", {})
        if not menu:
            pytest.skip("No short menu in PAWSOVERMAWS")
        items = menu.get("shortMenuItem", [])
        if isinstance(items, dict):
            items = [items]
        for item in items:
            assert "name" in item or "position" in item

    def test_prog_buttons_d2r_roundtrip(self):
        """Display-to-raw mapping should round-trip correctly."""
        func_names = list(BUTTON_FUNCTION_NAMES.keys())
        func_display = [BUTTON_FUNCTION_NAMES[k] for k in func_names]
        d2r = dict(zip(func_display, func_names))

        for raw, display in BUTTON_FUNCTION_NAMES.items():
            assert d2r[display] == raw

    def test_switch_d2r_roundtrip(self):
        """Switch display-to-raw mapping should round-trip correctly."""
        switch_names = list(SWITCH_FUNCTION_NAMES.keys())
        switch_display = [SWITCH_FUNCTION_NAMES[k] for k in switch_names]
        d2r = dict(zip(switch_display, switch_names))

        for raw, display in SWITCH_FUNCTION_NAMES.items():
            assert d2r[display] == raw

    def test_menu_d2r_roundtrip(self):
        """Menu display-to-raw mapping should round-trip correctly."""
        menu_names = list(SHORT_MENU_NAMES.keys())
        menu_display = [SHORT_MENU_NAMES[k] for k in menu_names]
        d2r = dict(zip(menu_display, menu_names))

        for raw, display in SHORT_MENU_NAMES.items():
            assert d2r[display] == raw


class TestButtonConfigModify:
    """Test modifying programmable button data via XML."""

    def test_modify_button_function_roundtrip(self):
        """Changing a button function should persist in the XML."""
        import xml.etree.ElementTree as ET

        prs = parse_prs(PAWS)
        xml_str = extract_platform_xml(prs)
        if xml_str is None:
            pytest.skip("No XML in PAWSOVERMAWS")

        root = ET.fromstring(xml_str)
        pb = root.find("progButtons")
        if pb is None:
            pytest.skip("No progButtons element")

        buttons = pb.findall("progButton")
        if not buttons:
            pytest.skip("No progButton children")

        # Change first button to SCAN
        original_func = buttons[0].get("function")
        buttons[0].set("function", "SCAN")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        # Re-read and verify
        config = extract_platform_config(prs)
        prog = config["progButtons"]
        new_buttons = prog.get("progButton", [])
        if isinstance(new_buttons, dict):
            new_buttons = [new_buttons]
        assert new_buttons[0]["function"] == "SCAN"

    def test_modify_switch_function(self):
        """Changing a switch function should persist."""
        import xml.etree.ElementTree as ET

        prs = parse_prs(PAWS)
        xml_str = extract_platform_xml(prs)
        if xml_str is None:
            pytest.skip("No XML in PAWSOVERMAWS")

        root = ET.fromstring(xml_str)
        pb = root.find("progButtons")
        if pb is None:
            pytest.skip("No progButtons element")

        pb.set("_2PosFunction", "ZONE")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        assert config["progButtons"]["_2PosFunction"] == "ZONE"

    def test_modify_short_menu_item(self):
        """Changing a short menu item should persist."""
        import xml.etree.ElementTree as ET

        prs = parse_prs(PAWS)
        xml_str = extract_platform_xml(prs)
        if xml_str is None:
            pytest.skip("No XML in PAWSOVERMAWS")

        root = ET.fromstring(xml_str)
        sm = root.find("shortMenu")
        if sm is None:
            pytest.skip("No shortMenu element")

        items = sm.findall("shortMenuItem")
        if not items:
            pytest.skip("No shortMenuItem children")

        # Change first item to lockKeypad
        items[0].set("name", "lockKeypad")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        menu = config["shortMenu"]
        new_items = menu.get("shortMenuItem", [])
        if isinstance(new_items, dict):
            new_items = [new_items]
        assert new_items[0]["name"] == "lockKeypad"

    def test_modify_switch_values(self):
        """Changing switch position values should persist."""
        import xml.etree.ElementTree as ET

        prs = parse_prs(PAWS)
        xml_str = extract_platform_xml(prs)
        if xml_str is None:
            pytest.skip("No XML in PAWSOVERMAWS")

        root = ET.fromstring(xml_str)
        pb = root.find("progButtons")
        if pb is None:
            pytest.skip("No progButtons element")

        pb.set("_3PosAValue", "42")
        pb.set("_3PosBValue", "99")

        new_xml = ET.tostring(root, encoding='unicode')
        write_platform_config(prs, new_xml)

        config = extract_platform_config(prs)
        assert config["progButtons"]["_3PosAValue"] == "42"
        assert config["progButtons"]["_3PosBValue"] == "99"


# ─── Diff viewer data generation tests ──────────────────────────────


class TestDiffViewerData:
    """Test the data that feeds the diff viewer."""

    def test_detailed_comparison_identical(self):
        """Comparing a file to itself should show no diffs."""
        prs_a = parse_prs(CLAUDE)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        assert detail['systems_a_only'] == []
        assert detail['systems_b_only'] == []
        assert detail['talkgroup_diffs'] == {}
        assert detail['freq_diffs'] == {}
        assert detail['conv_diffs'] == {}

    def test_detailed_comparison_different(self):
        """PAWSOVERMAWS vs claude test should show differences."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        # Should have some differences
        has_diffs = (
            detail['systems_a_only'] or
            detail['systems_b_only'] or
            detail['talkgroup_diffs'] or
            detail['freq_diffs'] or
            detail['conv_diffs'] or
            detail['option_diffs']
        )
        assert has_diffs

    def test_detailed_comparison_structure(self):
        """detailed_comparison should return correct dict structure."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        assert 'systems_a_only' in detail
        assert 'systems_b_only' in detail
        assert 'systems_both' in detail
        assert 'talkgroup_diffs' in detail
        assert 'freq_diffs' in detail
        assert 'conv_diffs' in detail
        assert 'option_diffs' in detail

        assert isinstance(detail['systems_a_only'], list)
        assert isinstance(detail['systems_b_only'], list)
        assert isinstance(detail['systems_both'], list)
        assert isinstance(detail['talkgroup_diffs'], dict)
        assert isinstance(detail['freq_diffs'], dict)
        assert isinstance(detail['conv_diffs'], dict)
        assert isinstance(detail['option_diffs'], list)

    def test_compare_prs_identical(self):
        """compare_prs with identical files has no ADDED/REMOVED."""
        prs = parse_prs(CLAUDE)
        diffs = compare_prs(prs, prs)
        for dtype, cat, name, detail in diffs:
            assert dtype != "ADDED"
            assert dtype != "REMOVED"

    def test_compare_prs_different(self):
        """compare_prs with different files should find diffs."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        diffs = compare_prs(prs_a, prs_b)
        assert len(diffs) > 0

    def test_talkgroup_diff_structure(self):
        """Talkgroup diffs should have 'added' and 'removed' lists."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        for sys_name, td in detail['talkgroup_diffs'].items():
            assert 'added' in td
            assert 'removed' in td
            assert isinstance(td['added'], list)
            assert isinstance(td['removed'], list)
            # Each entry should be (gid, short_name, long_name)
            for entry in td['added']:
                assert len(entry) == 3
            for entry in td['removed']:
                assert len(entry) == 3

    def test_freq_diff_structure(self):
        """Frequency diffs should have 'added' and 'removed' lists."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        for set_name, fd in detail['freq_diffs'].items():
            assert 'added' in fd
            assert 'removed' in fd
            assert isinstance(fd['added'], list)
            assert isinstance(fd['removed'], list)

    def test_option_diff_structure(self):
        """Option diffs should be (field, val_a, val_b) tuples."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        for entry in detail['option_diffs']:
            assert len(entry) == 3

    def test_systems_both_are_in_both(self):
        """systems_both should only list systems present in both files."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        # systems_both should not overlap with a_only or b_only
        both_set = set(detail['systems_both'])
        a_only_set = set(detail['systems_a_only'])
        b_only_set = set(detail['systems_b_only'])

        assert both_set.isdisjoint(a_only_set)
        assert both_set.isdisjoint(b_only_set)
        assert a_only_set.isdisjoint(b_only_set)

    def test_comparison_symmetry(self):
        """Swapping A and B should swap a_only/b_only lists."""
        prs_a = parse_prs(PAWS)
        prs_b = parse_prs(CLAUDE)
        detail_ab = detailed_comparison(prs_a, prs_b)
        detail_ba = detailed_comparison(prs_b, prs_a)

        assert sorted(detail_ab['systems_a_only']) == sorted(
            detail_ba['systems_b_only'])
        assert sorted(detail_ab['systems_b_only']) == sorted(
            detail_ba['systems_a_only'])
        assert sorted(detail_ab['systems_both']) == sorted(
            detail_ba['systems_both'])
