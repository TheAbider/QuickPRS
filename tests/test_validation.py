"""Tests for validation module."""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.validation import (
    validate_prs, validate_prs_detailed,
    validate_group_set, validate_trunk_set, validate_conv_set,
    validate_iden_set,
    ERROR, WARNING, INFO, LIMITS,
    _is_valid_tone,
)
from quickprs.injector import (
    make_group_set, make_trunk_set, make_iden_set,
    make_p25_group, make_trunk_channel,
)
from quickprs.record_types import (
    P25GroupSet, P25Group, TrunkSet, TrunkChannel,
    ConvSet, ConvChannel, IdenDataSet, IdenElement,
)


TESTDATA = Path(__file__).parent.parent / "tests" / "testdata"
CLAUDE_PRS = TESTDATA / "claude test.PRS"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── validate_prs (flat) ─────────────────────────────────────────────

def test_validate_prs_no_crash():
    """validate_prs runs without crashing on both test files."""
    for f in (CLAUDE_PRS, PAWS_PRS):
        if f.exists():
            prs = parse_prs(f)
            issues = validate_prs(prs)
            assert isinstance(issues, list)


def test_validate_prs_includes_conv_check():
    """validate_prs now includes conv set validation."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    # Should run without error; conv sets in claude test should be valid
    issues = validate_prs(prs)
    assert isinstance(issues, list)


# ─── validate_prs_detailed ───────────────────────────────────────────

def test_validate_detailed_returns_dict():
    """validate_prs_detailed returns a dict."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    result = validate_prs_detailed(prs)
    assert isinstance(result, dict)
    for key, issues in result.items():
        assert isinstance(key, str)
        assert isinstance(issues, list)
        for severity, msg in issues:
            assert severity in (ERROR, WARNING, INFO)
            assert isinstance(msg, str)


def test_validate_detailed_categorized():
    """Detailed results are grouped by set name."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    result = validate_prs_detailed(prs)
    # Keys should be like "Group Set: ...", "Trunk Set: ...", etc.
    for key in result:
        assert any(key.startswith(prefix) for prefix in
                   ("Global", "Group Set:", "Trunk Set:", "Conv Set:",
                    "IDEN Set:", "Group Sets", "Trunk Sets",
                    "Conv Sets", "IDEN Sets")), f"Unexpected key: {key}"


# ─── validate_group_set ──────────────────────────────────────────────

def test_validate_group_set_clean():
    """A small valid group set produces no issues."""
    gs = make_group_set("TEST", [
        (100, "TEST1", "TEST ONE"),
        (200, "TEST2", "TEST TWO"),
    ])
    issues = validate_group_set(gs)
    assert len(issues) == 0


def test_validate_group_set_scan_limit():
    """Exceeding 127 scan TGs produces an error."""
    tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i}") for i in range(130)]
    gs = make_group_set("BIG", tgs)
    issues = validate_group_set(gs)
    errors = [msg for sev, msg in issues if sev == ERROR]
    assert any("130 scan-enabled" in e for e in errors)


def test_validate_group_set_scan_warning():
    """Approaching scan limit produces a warning."""
    tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i}") for i in range(120)]
    gs = make_group_set("WARN", tgs)
    issues = validate_group_set(gs)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert any("approaching" in w for w in warnings)


def test_validate_group_set_duplicate_ids():
    """Duplicate talkgroup IDs produce warnings."""
    gs = P25GroupSet(name="DUP", groups=[
        make_p25_group(100, "TG1", "TG ONE"),
        make_p25_group(100, "TG2", "TG TWO"),
    ])
    issues = validate_group_set(gs)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert any("Duplicate" in w for w in warnings)


def test_validate_group_set_name_too_long():
    """Oversized names produce errors."""
    gs = P25GroupSet(name="LONG", groups=[
        P25Group(
            group_name="TOOLONGNAME",  # >8
            group_id=100,
            long_name="THIS IS WAY TOO LONG NAME",  # >16
            tx=False, rx=True, scan=True,
            calls=True, alert=True,
            scan_list_member=True, backlight=True,
        ),
    ])
    issues = validate_group_set(gs)
    errors = [msg for sev, msg in issues if sev == ERROR]
    assert len(errors) >= 2  # short name + long name


# ─── validate_trunk_set ──────────────────────────────────────────────

def test_validate_trunk_set_clean():
    """A valid trunk set produces no issues."""
    ts = make_trunk_set("TEST", [
        (851.0125, 806.0125),
        (852.0125, 807.0125),
    ])
    issues = validate_trunk_set(ts)
    assert len(issues) == 0


def test_validate_trunk_set_duplicate_freq():
    """Duplicate frequencies produce warnings."""
    ts = make_trunk_set("DUP", [
        (851.0125, 806.0125),
        (851.0125, 806.0125),
    ])
    issues = validate_trunk_set(ts)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert any("duplicate" in w for w in warnings)


def test_validate_trunk_set_out_of_band():
    """Frequencies outside XG-100P range produce errors."""
    ts = TrunkSet(name="OOB", channels=[
        TrunkChannel(tx_freq=10.0, rx_freq=10.0),
    ], tx_min=10.0, tx_max=10.0, rx_min=10.0, rx_max=10.0)
    issues = validate_trunk_set(ts)
    errors = [msg for sev, msg in issues if sev == ERROR]
    assert any("outside XG-100P range" in e for e in errors)


# ─── validate_conv_set ───────────────────────────────────────────────

def test_validate_conv_set_clean():
    """A valid conv set produces no issues."""
    cs = ConvSet(name="TEST", channels=[
        ConvChannel(
            short_name="CH1", tx_freq=462.5625, rx_freq=462.5625,
            tx_tone="127.3", rx_tone="127.3", long_name="CHANNEL 1"),
    ])
    issues = validate_conv_set(cs)
    assert len(issues) == 0


def test_validate_conv_set_bad_freq():
    """Frequencies outside range produce errors."""
    cs = ConvSet(name="BAD", channels=[
        ConvChannel(
            short_name="BAD", tx_freq=5.0, rx_freq=5.0,
            tx_tone="", rx_tone="", long_name="BAD FREQ"),
    ])
    issues = validate_conv_set(cs)
    errors = [msg for sev, msg in issues if sev == ERROR]
    assert len(errors) >= 1


# ─── validate_iden_set ───────────────────────────────────────────────

def test_validate_iden_set_clean():
    """A valid IDEN set produces no issues."""
    iset = make_iden_set("TEST", [
        {"base_freq_hz": 851006250, "chan_spacing_hz": 12500,
         "bandwidth_hz": 12500, "tx_offset": -45000000, "iden_type": 0},
    ])
    issues = validate_iden_set(iset)
    assert len(issues) == 0


def test_validate_iden_set_tdma_bandwidth():
    """TDMA element with unusual bandwidth produces warning."""
    elems = [IdenElement(
        base_freq_hz=851006250, chan_spacing_hz=12500,
        bandwidth_hz=25000, tx_offset=-45000000, iden_type=1,
    )]
    while len(elems) < 16:
        elems.append(IdenElement())
    iset = IdenDataSet(name="TDMA", elements=elems)
    issues = validate_iden_set(iset)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert any("TDMA bandwidth" in w for w in warnings)


def test_validate_iden_set_tdma_12500_ok():
    """TDMA with 12500 Hz bandwidth is valid (RPM default)."""
    elems = [IdenElement(
        base_freq_hz=851006250, chan_spacing_hz=12500,
        bandwidth_hz=12500, tx_offset=-45000000, iden_type=1,
    )]
    while len(elems) < 16:
        elems.append(IdenElement())
    iset = IdenDataSet(name="TDMA", elements=elems)
    issues = validate_iden_set(iset)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert not any("TDMA bandwidth" in w for w in warnings)


# ─── tone validation ────────────────────────────────────────────────

def test_valid_ctcss_tones():
    assert _is_valid_tone("127.3") is True
    assert _is_valid_tone("250.3") is True
    assert _is_valid_tone("67.0") is True
    assert _is_valid_tone("") is True


def test_valid_dcs_tones():
    assert _is_valid_tone("D023N") is True
    assert _is_valid_tone("D754I") is True


def test_invalid_tone():
    assert _is_valid_tone("999.9") is False
    assert _is_valid_tone("abc") is False


# ─── system count validation ────────────────────────────────────────

def test_validate_system_counts():
    """System count check runs on test file."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    assert isinstance(issues, list)


def test_validate_ecc_on_paws():
    """PAWSOVERMAWS has no ECC limit violations (max is 30 = limit)."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    ecc_issues = [msg for sev, msg in issues if "ECC entries" in msg]
    assert len(ecc_issues) == 0, f"Unexpected ECC issues: {ecc_issues}"


def test_validate_ecc_over_limit():
    """Injecting 31+ ECC entries triggers a warning."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.injector import add_p25_trunked_system, make_group_set, make_trunk_set
    from quickprs.record_types import (
        P25TrkSystemConfig, EnhancedCCEntry,
    )
    prs = parse_prs(CLAUDE_PRS)
    # Create system with 31 ECC entries (over the 30 limit)
    ecc_list = [
        EnhancedCCEntry(channel_ref1=i, channel_ref2=i)
        for i in range(31)
    ]
    config = P25TrkSystemConfig(
        system_name="OVERMAX",
        long_name="OVER LIMIT TEST",
        trunk_set_name="OVRTRK",
        group_set_name="OVRGRP",
        wan_name="OVERLMT",
        home_unit_id=123456,
        system_id=999,
        ecc_entries=ecc_list,
    )
    gs = make_group_set("OVRGRP", [(100, "TG1", "TEST TG")])
    ts = make_trunk_set("OVRTRK", [(851.0125, 806.0125)])
    add_p25_trunked_system(prs, config, group_set=gs, trunk_set=ts)

    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    ecc_issues = [msg for sev, msg in issues if "ECC entries" in msg]
    assert len(ecc_issues) >= 1
    assert "31" in ecc_issues[0]
    assert "OVER LIMIT TEST" in ecc_issues[0]


def test_validate_mixed_scanning_warning():
    """Personality with both trunked + conv gets mixed scanning info."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    info_msgs = [msg for sev, msg in issues if sev == INFO]
    assert any("Mixed trunked" in m for m in info_msgs)


def test_validate_no_wacn_conflict_in_paws():
    """PAWSOVERMAWS systems have unique WACNs — no conflict warning."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    wacn_issues = [msg for sev, msg in issues if "share WACN" in msg]
    assert len(wacn_issues) == 0


def test_validate_wacn_conflict_detected():
    """Two systems with same WACN triggers a conflict warning."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.injector import add_p25_trunked_system, make_group_set, make_trunk_set
    from quickprs.record_types import P25TrkSystemConfig
    prs = parse_prs(CLAUDE_PRS)
    # Add two systems with the same WAN name
    for name, long in [("SYS1", "SYSTEM ONE"), ("SYS2", "SYSTEM TWO")]:
        config = P25TrkSystemConfig(
            system_name=name,
            long_name=long,
            trunk_set_name=f"{name}TRK",
            group_set_name=f"{name}GRP",
            wan_name="SAMEWAN",
            home_unit_id=100,
            system_id=555,
        )
        gs = make_group_set(f"{name}GRP", [(100, "TG1", "TEST TG")])
        ts = make_trunk_set(f"{name}TRK", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config, group_set=gs, trunk_set=ts)

    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    wacn_issues = [msg for sev, msg in issues if "share WACN" in msg]
    assert len(wacn_issues) >= 1
    assert "SAMEWAN" in wacn_issues[0]


# ─── WAN name parsing ─────────────────────────────────────────────

def test_parse_wan_name_paws():
    """WAN names are correctly extracted from PAWSOVERMAWS systems."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import (
        is_system_config_data, parse_system_long_name,
        parse_system_wan_name,
    )
    prs = parse_prs(PAWS_PRS)
    wan_names = {}
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long = parse_system_long_name(sec.raw)
            wan = parse_system_wan_name(sec.raw)
            if long and wan:
                wan_names[long] = wan

    # Verify known WAN names from PAWSOVERMAWS
    assert wan_names.get("PSERN SEATTLE") == "PSERN"
    assert wan_names.get("PSRS TACOMA") == "PSRS"
    assert wan_names.get("P25 WA STATE PAT") == "WASP"
    assert wan_names.get("NELLIS/CREECH/NN") == "NNSS"
    assert wan_names.get("C/S NEVADA") == "C/S NSRS"


def test_validate_combined_channel_limit():
    """Combined TG+conv channel count is checked against personality limit."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    issues = validate_prs(prs)
    # claude test is small — should not trigger combined limit
    combined_issues = [m for _, m in issues if "channels+talkgroups" in m]
    assert len(combined_issues) == 0


def test_validate_duplicate_set_names():
    """Duplicate set names across types produce warnings."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.injector import add_p25_trunked_system, make_group_set, make_trunk_set
    from quickprs.record_types import P25TrkSystemConfig
    prs = parse_prs(CLAUDE_PRS)
    # Inject a system where trunk and group sets share the name "DUPE"
    config = P25TrkSystemConfig(
        system_name="DUPE",
        long_name="DUPE TEST",
        trunk_set_name="DUPE",
        group_set_name="DUPE",
        wan_name="DUPEWAN",
        home_unit_id=100,
        system_id=555,
    )
    gs = make_group_set("DUPE", [(100, "TG1", "TEST TG")])
    ts = make_trunk_set("DUPE", [(851.0125, 806.0125)])
    add_p25_trunked_system(prs, config, group_set=gs, trunk_set=ts)
    issues = validate_prs(prs)
    dup_issues = [m for _, m in issues if "Duplicate set name" in m]
    assert len(dup_issues) >= 1
    assert "DUPE" in dup_issues[0]


def test_validate_zone_advisory_large_group_set():
    """Large group set gets zone limit advisory."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    from quickprs.validation import _validate_system_counts
    issues = _validate_system_counts(prs)
    zone_info = [m for s, m in issues if s == INFO and "zone limit" in m]
    # PSERN PD has 83 TGs, should trigger zone advisory
    assert len(zone_info) >= 1


def test_validate_trunk_dup_freq_count_not_individual():
    """Trunk set with duplicates reports count, not individual warnings."""
    ts = make_trunk_set("MULTI", [
        (851.0125, 806.0125),
        (851.0125, 806.0125),
        (852.0125, 807.0125),
        (852.0125, 807.0125),
    ])
    issues = validate_trunk_set(ts)
    dup_warnings = [m for s, m in issues if s == WARNING and "duplicate" in m]
    # Should be exactly 1 summary warning, not 2 individual
    assert len(dup_warnings) == 1
    assert "2 duplicate" in dup_warnings[0]


def test_parse_wan_name_conv_returns_none():
    """Conventional system configs return None for WAN name."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import (
        is_system_config_data, parse_system_long_name,
        parse_system_wan_name,
    )
    prs = parse_prs(PAWS_PRS)
    # FURRY TRASH systems are conventional — WAN name should be None
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long = parse_system_long_name(sec.raw)
            if long and "FURRY" in long:
                wan = parse_system_wan_name(sec.raw)
                assert wan is None, f"Conv system {long} should have no WAN"


# ─── IDEN dedup validation ────────────────────────────────────────────

def test_validate_iden_dedup_warning():
    """Duplicate IDEN sets should trigger a warning."""
    from quickprs.iden_library import get_template
    from quickprs.injector import add_iden_set

    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(CLAUDE_PRS)

    # Add two identical IDEN sets with different names
    tmpl = get_template("800-TDMA")
    iset1 = make_iden_set("IDEN1", tmpl.entries)
    iset2 = make_iden_set("IDEN2", tmpl.entries)
    add_iden_set(prs, iset1)
    add_iden_set(prs, iset2)

    issues = validate_prs(prs)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    assert any("IDEN1" in w and "IDEN2" in w for w in warnings), \
        f"Expected duplicate IDEN warning, got: {warnings}"


def test_validate_iden_no_false_dedup():
    """Different IDEN sets (FDMA vs TDMA) should not trigger dedup warning."""
    from quickprs.iden_library import get_template
    from quickprs.injector import add_iden_set

    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(CLAUDE_PRS)

    fdma = get_template("800-FDMA")
    tdma = get_template("800-TDMA")
    add_iden_set(prs, make_iden_set("FDMA", fdma.entries))
    add_iden_set(prs, make_iden_set("TDMA", tdma.entries))

    issues = validate_prs(prs)
    warnings = [msg for sev, msg in issues if sev == WARNING]
    dedup_warnings = [w for w in warnings if "identical entries" in w]
    assert len(dedup_warnings) == 0, \
        f"FDMA and TDMA should not trigger dedup: {dedup_warnings}"


# ─── Platform config validation ────────────────────────────────────

def test_validate_platform_config_paws_clean():
    """PAWSOVERMAWS should have no platform config validation warnings."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    issues = validate_prs(prs)
    platform_warns = [msg for sev, msg in issues
                      if sev == WARNING and (
                          "function" in msg.lower() or
                          "menu" in msg.lower() or
                          "below minimum" in msg or
                          "exceeds maximum" in msg)]
    assert len(platform_warns) == 0, f"Unexpected warnings: {platform_warns}"


def test_validate_platform_config_no_xml_no_crash():
    """Files without platformConfig should not crash validation."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    issues = validate_prs(prs)
    # Should not crash, just return normal issues
    assert isinstance(issues, list)


def test_validate_invalid_button_function():
    """Invalid button function should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    # Corrupt a button function
    for btn in root.iter("progButton"):
        btn.set("function", "INVALID_FUNC_XYZ")
        break

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    func_warns = [msg for sev, msg in issues if "not recognized" in msg]
    assert len(func_warns) >= 1


def test_validate_invalid_switch_function():
    """Invalid switch function should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    for pb in root.iter("progButtons"):
        pb.set("_2PosFunction", "BOGUS_SWITCH")
        break

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    switch_warns = [msg for sev, msg in issues
                    if "switch function" in msg.lower()]
    assert len(switch_warns) >= 1


def test_validate_invalid_menu_name():
    """Invalid short menu name should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    for item in root.iter("shortMenuItem"):
        item.set("name", "totallyBogusName")
        break

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    menu_warns = [msg for sev, msg in issues if "not recognized" in msg]
    assert len(menu_warns) >= 1


def test_validate_int_range_over_max():
    """Int field above max should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    # Set front brightness to 99 (max is 15)
    for misc in root.iter("miscConfig"):
        misc.set("frontFpIntensity", "99")
        break

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    range_warns = [msg for sev, msg in issues if "exceeds maximum" in msg]
    assert len(range_warns) >= 1


def test_validate_int_range_under_min():
    """Int field below min should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    # Set mic gain to -20 (min is -12)
    # Use miscConfig minVol which has min_val=0
    for misc in root.iter("audioConfig"):
        misc.set("minVol", "-5")
        break

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    range_warns = [msg for sev, msg in issues if "below minimum" in msg]
    assert len(range_warns) >= 1


def test_validate_duplicate_menu_positions():
    """Duplicate short menu positions should produce a warning."""
    from quickprs.validation import _validate_platform_config
    from quickprs.option_maps import (
        extract_platform_xml, write_platform_config,
    )
    import xml.etree.ElementTree as ET

    if not PAWS_PRS.exists():
        pytest.skip("test file not found")

    prs = parse_prs(PAWS_PRS)
    xml_str = extract_platform_xml(prs)
    root = ET.fromstring(xml_str)

    # Set two menu items to same position
    menu_items = list(root.iter("shortMenuItem"))
    if len(menu_items) >= 2:
        menu_items[1].set("position", menu_items[0].get("position", "0"))

    new_xml = ET.tostring(root, encoding="unicode")
    write_platform_config(prs, new_xml)

    issues = _validate_platform_config(prs)
    dup_warns = [msg for sev, msg in issues if "Duplicate" in msg]
    assert len(dup_warns) >= 1


# ─── Cross-reference validation ─────────────────────────────────────

def test_validate_crossref_paws_clean():
    """PAWSOVERMAWS should have no cross-reference warnings (valid refs)."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    issues = validate_prs(prs)
    crossref_msgs = [msg for _, msg in issues
                     if "doesn't exist" in msg]
    assert crossref_msgs == [], f"Unexpected cross-ref issues: {crossref_msgs}"


def test_validate_crossref_ecc_iden_missing():
    """If ECC references an IDEN set name not in the file, warn."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import (
        is_system_config_data, parse_ecc_entries,
        parse_iden_section, parse_sets_from_sections,
    )

    prs = parse_prs(PAWS_PRS)

    # Rename ALL IDEN sets so every ECC reference becomes orphaned.
    # ECC entries reference names like "BEE00", "58544", "92738".
    # By renaming all IDEN sets to "ZZZZZ", no ECC ref will match.
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    assert elem_sec and ids_sec

    sets = parse_sets_from_sections(ids_sec.raw, elem_sec.raw,
                                     parse_iden_section)
    assert sets

    # Names are in the elem (data) section, not the set section.
    # Replace each IDEN set name so ECC references become orphaned.
    raw = bytearray(elem_sec.raw)
    for s in sets:
        old_name = s.name.encode('ascii')
        new_name = b'Z' * len(old_name)
        idx = raw.find(old_name)
        if idx >= 0:
            raw[idx:idx + len(old_name)] = new_name
    elem_sec.raw = bytes(raw)

    issues = validate_prs(prs)
    crossref_msgs = [msg for _, msg in issues
                     if "IDEN set" in msg and "doesn't exist" in msg]
    assert len(crossref_msgs) >= 1


def test_parse_system_set_refs():
    """parse_system_set_refs should extract trunk/group set names."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import (
        is_system_config_data, parse_system_set_refs,
    )

    prs = parse_prs(PAWS_PRS)
    found = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            trunk_ref, group_ref = parse_system_set_refs(sec.raw)
            # PAWS has P25 trunked systems with set references
            if trunk_ref or group_ref:
                found = True
                # Names should be <= 8 chars (short name format)
                if trunk_ref:
                    assert len(trunk_ref) <= 8
                if group_ref:
                    assert len(group_ref) <= 8
    assert found, "Expected at least one system config with set references"


# ─── validate_structure ──────────────────────────────────────────────

from quickprs.validation import validate_structure
from quickprs.builder import create_blank_prs
from quickprs.prs_parser import Section


def test_structure_paws_clean():
    """PAWSOVERMAWS passes structural validation with no issues."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    issues = validate_structure(prs)
    assert len(issues) == 0, f"Unexpected structural issues: {issues}"


def test_structure_claude_clean():
    """claude test passes structural validation with no issues."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(CLAUDE_PRS)
    issues = validate_structure(prs)
    assert len(issues) == 0, f"Unexpected structural issues: {issues}"


def test_structure_blank_clean():
    """Blank PRS passes structural validation."""
    prs = create_blank_prs()
    issues = validate_structure(prs)
    assert len(issues) == 0, f"Unexpected structural issues: {issues}"


def test_structure_blank_with_injection():
    """Blank PRS with P25 injection passes structural validation."""
    from quickprs.record_types import P25TrkSystemConfig
    from quickprs.injector import (
        add_p25_trunked_system, make_group_set,
        make_trunk_set, make_iden_set,
    )
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="TSTSYS",
        long_name="TEST SYSTEM",
        trunk_set_name="TSTSYS",
        group_set_name="TSTGRP",
        wan_name="TSTWAN",
        home_unit_id=1234,
        system_id=100,
        wacn=5678,
        iden_set_name="TSTIDEN",
    )
    gs = make_group_set("TSTGRP", [(100, "TG1", "TEST TG")])
    ts = make_trunk_set("TSTSYS", [(851.0125, 806.0125)])
    iden = make_iden_set("TSTIDEN", [
        {"base_freq_hz": 851006250, "chan_spacing_hz": 12500,
         "bandwidth_hz": 12500, "iden_type": 0},
    ])
    add_p25_trunked_system(prs, config, trunk_set=ts,
                            group_set=gs, iden_set=iden)
    issues = validate_structure(prs)
    assert len(issues) == 0, f"Unexpected structural issues: {issues}"


def test_structure_missing_personality():
    """File without CPersonality triggers an error."""
    prs = create_blank_prs()
    prs.sections = [s for s in prs.sections
                    if s.class_name != "CPersonality"]
    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("CPersonality" in e for e in errors)


def test_structure_personality_not_first():
    """CPersonality not first triggers an error."""
    prs = create_blank_prs()
    # Move CPersonality to the end
    pers = [s for s in prs.sections if s.class_name == "CPersonality"]
    rest = [s for s in prs.sections if s.class_name != "CPersonality"]
    prs.sections = rest + pers
    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("not the first" in e for e in errors)


def test_structure_no_systems():
    """File with no system sections triggers an error."""
    from quickprs.record_types import is_system_config_data
    prs = create_blank_prs()
    prs.sections = [
        s for s in prs.sections
        if s.class_name != "CConvSystem"
        and not (not s.class_name and is_system_config_data(s.raw))
    ]
    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("No system sections" in e for e in errors)


def test_structure_wan_count_mismatch():
    """WAN entry count mismatch triggers an error."""
    from quickprs.record_types import (
        P25TrkSystemConfig, build_wan_opts_section,
    )
    from quickprs.injector import (
        add_p25_trunked_system, make_group_set, make_trunk_set,
    )
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="WAN", long_name="WAN TEST",
        trunk_set_name="WANTRK", group_set_name="WANGRP",
        wan_name="WANWAN", home_unit_id=1, system_id=1, wacn=1,
    )
    gs = make_group_set("WANGRP", [(1, "T", "T")])
    ts = make_trunk_set("WANTRK", [(851.0125, 806.0125)])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    # Corrupt WAN opts count
    for i, s in enumerate(prs.sections):
        if s.class_name == "CP25tWanOpts":
            prs.sections[i] = Section(
                offset=0,
                raw=build_wan_opts_section(99),
                class_name="CP25tWanOpts")
            break

    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("WAN count mismatch" in e for e in errors)


def test_structure_missing_companion():
    """CTrunkSet without CTrunkChannel triggers an error."""
    from quickprs.record_types import build_class_header
    from quickprs.binary_io import write_uint16_le
    prs = create_blank_prs()
    raw = build_class_header("CTrunkSet", 0x64, 0x00) + write_uint16_le(0)
    prs.sections.insert(3, Section(offset=0, raw=raw, class_name="CTrunkSet"))
    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("CTrunkChannel is missing" in e for e in errors)


def test_structure_bad_set_crossref():
    """System referencing nonexistent trunk set triggers an error."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import P25TrkSystemConfig
    from quickprs.injector import (
        add_p25_trunked_system, make_group_set, make_trunk_set,
    )
    prs = parse_prs(CLAUDE_PRS)
    config = P25TrkSystemConfig(
        system_name="BAD", long_name="BAD REFS",
        trunk_set_name="NOEXIST", group_set_name="NOGRP",
        wan_name="BADWAN", home_unit_id=1, system_id=1, wacn=1,
    )
    # Add the system WITHOUT creating matching sets
    from quickprs.prs_parser import Section as Sec
    from quickprs.record_types import is_system_config_data
    header_raw = config.build_header_section()
    data_raw = config.build_data_section()
    # Insert before sets
    insert_idx = next(
        (i for i, s in enumerate(prs.sections)
         if s.class_name in ('CTrunkSet', 'CConvSet')),
        len(prs.sections))
    prs.sections.insert(insert_idx, Sec(offset=0, raw=data_raw, class_name=""))
    prs.sections.insert(insert_idx, Sec(offset=0, raw=header_raw,
                                         class_name="CP25TrkSystem"))
    issues = validate_structure(prs)
    errors = [m for s, m in issues if s == ERROR]
    assert any("NOEXIST" in e for e in errors), f"Expected NOEXIST ref error, got: {errors}"
    assert any("NOGRP" in e for e in errors), f"Expected NOGRP ref error, got: {errors}"


def test_structure_convset_metadata_config_pair():
    """ConvSet with wrong metadata bytes 38-39 triggers a warning."""
    prs = create_blank_prs()
    # Corrupt the ConvChannel section's metadata bytes 38-39
    conv_sec = prs.get_section_by_class("CConvChannel")
    assert conv_sec is not None
    raw = bytearray(conv_sec.raw)
    # Find the metadata area (after channel data + set name LPS)
    # The metadata is the 60 bytes after the set name in the CConvChannel section.
    # We need to find and modify bytes 38-39 of the metadata within the section.
    # Easier approach: rebuild with a ConvSet that has wrong metadata
    from quickprs.record_types import (
        ConvSet, ConvChannel, build_conv_channel_section,
        build_conv_set_section, parse_conv_channel_section,
        parse_sets_from_sections,
    )
    conv_set_sec = prs.get_section_by_class("CConvSet")
    sets = parse_sets_from_sections(
        conv_set_sec.raw, conv_sec.raw, parse_conv_channel_section)
    # Corrupt the metadata
    meta = bytearray(sets[0].metadata)
    meta[38] = 0x00
    meta[39] = 0x00
    sets[0]._metadata_reserved = bytes(meta)
    # Rebuild sections
    new_ch_raw = build_conv_channel_section(sets)
    ch_idx = next(i for i, s in enumerate(prs.sections)
                  if s.class_name == "CConvChannel")
    prs.sections[ch_idx] = Section(offset=0, raw=new_ch_raw,
                                    class_name="CConvChannel")
    issues = validate_structure(prs)
    warnings = [m for s, m in issues if s == WARNING]
    assert any("bytes 38-39" in w for w in warnings)
