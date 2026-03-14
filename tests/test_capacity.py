"""Tests for capacity estimation."""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.validation import estimate_capacity, format_capacity, LIMITS
from quickprs.builder import create_blank_prs
from quickprs.injector import (
    add_p25_trunked_system, make_group_set, make_trunk_set, make_iden_set,
    add_conv_system,
)
from quickprs.record_types import (
    P25TrkSystemConfig, ConvChannel, ConvSet,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE_PRS = TESTDATA / "claude test.PRS"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Basic structure ────────────────────────────────────────────────

def test_capacity_returns_dict():
    """estimate_capacity returns a dict with expected keys."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    assert isinstance(cap, dict)
    for key in ['systems', 'channels', 'talkgroups', 'trunk_freqs',
                'conv_channels', 'iden_sets', 'file_size',
                'scan_tg_headroom', 'zones_needed']:
        assert key in cap, f"Missing key: {key}"


def test_capacity_systems_fields():
    """Systems dict has used/max/pct."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    sys_info = cap['systems']
    assert 'used' in sys_info
    assert 'max' in sys_info
    assert 'pct' in sys_info
    assert sys_info['max'] == 512


def test_capacity_channels_fields():
    """Channels dict has used/max/pct."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    ch_info = cap['channels']
    assert 'used' in ch_info
    assert 'max' in ch_info
    assert ch_info['max'] == 1250


# ─── Blank PRS (near zero usage) ───────────────────────────────────

def test_capacity_blank_minimal():
    """Blank PRS has 1 system, 1 conv channel, no talkgroups."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    assert cap['systems']['used'] == 1  # blank has one CConvSystem
    assert cap['conv_channels']['used'] == 1  # one default channel
    assert cap['talkgroups']['used'] == 0
    assert cap['trunk_freqs']['used'] == 0


def test_capacity_blank_low_pct():
    """Blank PRS has very low usage percentage."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    assert cap['systems']['pct'] < 1.0
    assert cap['channels']['pct'] < 1.0


def test_capacity_blank_no_scan_headroom():
    """Blank PRS has no group sets, so no scan headroom."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    assert len(cap['scan_tg_headroom']) == 0


# ─── PAWSOVERMAWS (real data) ──────────────────────────────────────

def test_capacity_paws_systems():
    """PAWSOVERMAWS has at least 2 system headers."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    # PAWSOVERMAWS has 1 CP25TrkSystem + 1 CConvSystem = 2 headers
    assert cap['systems']['used'] >= 2


def test_capacity_paws_talkgroups():
    """PAWSOVERMAWS has talkgroups in group sets."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert cap['talkgroups']['used'] > 0
    assert len(cap['talkgroups']['details']) > 0


def test_capacity_paws_trunk_freqs():
    """PAWSOVERMAWS has trunk frequencies."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert cap['trunk_freqs']['used'] > 0
    assert len(cap['trunk_freqs']['details']) > 0


def test_capacity_paws_conv_channels():
    """PAWSOVERMAWS has conv channels."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert cap['conv_channels']['used'] > 0


def test_capacity_paws_iden_sets():
    """PAWSOVERMAWS has IDEN sets."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert cap['iden_sets']['used'] > 0
    assert len(cap['iden_sets']['details']) > 0


def test_capacity_paws_scan_headroom():
    """PAWSOVERMAWS has scan headroom info for group sets."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert len(cap['scan_tg_headroom']) > 0
    for name, info in cap['scan_tg_headroom'].items():
        assert info['max'] == 127
        assert info['remaining'] == 127 - info['used']
        assert info['remaining'] >= 0


def test_capacity_paws_file_size():
    """PAWSOVERMAWS file size is reported correctly."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    assert cap['file_size']['bytes'] > 0
    assert cap['file_size']['sections'] > 0
    assert cap['file_size']['bytes'] == prs.file_size


def test_capacity_paws_channels_combined():
    """Combined channel count is sum of talkgroups + conv."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    expected = cap['talkgroups']['used'] + cap['conv_channels']['used']
    assert cap['channels']['used'] == expected


def test_capacity_paws_zones():
    """PAWSOVERMAWS zone estimate is reasonable."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    zones = cap['zones_needed']
    assert zones['zones_min'] >= 1
    assert zones['max'] == 50


# ─── Heavily loaded file (near limits) ─────────────────────────────

def test_capacity_heavy_load():
    """File with many talkgroups shows high usage."""
    prs = create_blank_prs()
    # Add a system with 200 talkgroups
    tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i}") for i in range(1, 201)]
    gs = make_group_set("HEAVY", tgs)
    ts = make_trunk_set("HEAVY", [(851.0125, 806.0125)])
    config = P25TrkSystemConfig(
        system_name="HEAVY",
        long_name="HEAVY LOAD TEST",
        trunk_set_name="HEAVY",
        group_set_name="HEAVY",
        wan_name="HEAVYW",
        home_unit_id=1, system_id=1,
    )
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    cap = estimate_capacity(prs)
    assert cap['talkgroups']['used'] == 200
    assert cap['talkgroups']['details']['HEAVY'] == 200
    assert cap['channels']['used'] >= 201  # 200 TGs + 1 default conv
    assert cap['channels']['pct'] > 15.0  # 201/1250 = 16%


def test_capacity_heavy_trunk():
    """File with many trunk frequencies shows count."""
    prs = create_blank_prs()
    freqs = [(850.0 + i * 0.025, 805.0 + i * 0.025)
             for i in range(50)]
    ts = make_trunk_set("BIGTRK", freqs)
    gs = make_group_set("BIGGRP", [(100, "TG1", "TEST TG")])
    config = P25TrkSystemConfig(
        system_name="BIGTRK",
        long_name="BIG TRUNK TEST",
        trunk_set_name="BIGTRK",
        group_set_name="BIGGRP",
        wan_name="BWAN",
        home_unit_id=1, system_id=1,
    )
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    cap = estimate_capacity(prs)
    assert cap['trunk_freqs']['used'] == 50
    assert cap['trunk_freqs']['details']['BIGTRK'] == 50


def test_capacity_scan_headroom_approaching():
    """Group set near scan limit shows low remaining."""
    prs = create_blank_prs()
    tgs = [(i, f"TG{i:05d}", f"TG {i}") for i in range(1, 121)]
    gs = make_group_set("FULL", tgs)
    ts = make_trunk_set("FULL", [(851.0125, 806.0125)])
    config = P25TrkSystemConfig(
        system_name="FULL",
        long_name="FULL SCAN TEST",
        trunk_set_name="FULL",
        group_set_name="FULL",
        wan_name="FULLW",
        home_unit_id=1, system_id=1,
    )
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    cap = estimate_capacity(prs)
    headroom = cap['scan_tg_headroom']
    assert 'FULL' in headroom
    assert headroom['FULL']['used'] == 120
    assert headroom['FULL']['remaining'] == 7  # 127 - 120


# ─── Format output ─────────────────────────────────────────────────

def test_format_capacity_returns_lines():
    """format_capacity returns a list of strings."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    lines = format_capacity(cap, filename="test.PRS")
    assert isinstance(lines, list)
    assert len(lines) > 0
    assert "test.PRS" in lines[0]


def test_format_capacity_has_sections():
    """format output includes system and channel sections."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    lines = format_capacity(cap)
    text = "\n".join(lines)
    assert "Systems:" in text
    assert "Channels:" in text
    assert "File:" in text


def test_format_capacity_paws():
    """PAWSOVERMAWS format includes trunk, conv, groups, headroom."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    prs = parse_prs(PAWS_PRS)
    cap = estimate_capacity(prs)
    lines = format_capacity(cap, filename="PAWSOVERMAWS.PRS")
    text = "\n".join(lines)
    assert "Trunk:" in text
    assert "Conv:" in text
    assert "Groups:" in text
    assert "Scan TG Headroom:" in text
    assert "IDEN Sets:" in text


def test_format_capacity_no_filename():
    """format_capacity without filename uses generic header."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    lines = format_capacity(cap)
    assert lines[0] == "Capacity Report"


# ─── Edge cases ─────────────────────────────────────────────────────

def test_capacity_multiple_group_sets():
    """Multiple group sets each appear in details."""
    prs = create_blank_prs()
    for name, tgs in [("SET1", [(1, "T1", "TG 1"), (2, "T2", "TG 2")]),
                      ("SET2", [(10, "T10", "TG 10")])]:
        gs = make_group_set(name, tgs)
        ts = make_trunk_set(name, [(851.0125, 806.0125)])
        config = P25TrkSystemConfig(
            system_name=name,
            long_name=f"{name} TEST",
            trunk_set_name=name,
            group_set_name=name,
            wan_name=name,
            home_unit_id=1, system_id=1,
        )
        add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    cap = estimate_capacity(prs)
    assert cap['talkgroups']['details']['SET1'] == 2
    assert cap['talkgroups']['details']['SET2'] == 1
    assert cap['talkgroups']['used'] == 3


def test_capacity_iden_active_count():
    """IDEN set details show active element count."""
    prs = create_blank_prs()
    iden = make_iden_set("TSTI", [
        {"base_freq_hz": 851006250, "chan_spacing_hz": 12500,
         "bandwidth_hz": 12500, "iden_type": 0},
        {"base_freq_hz": 762006250, "chan_spacing_hz": 6250,
         "bandwidth_hz": 6250, "iden_type": 0},
    ])
    gs = make_group_set("TSTGRP", [(100, "TG1", "TEST TG")])
    ts = make_trunk_set("TSTTRK", [(851.0125, 806.0125)])
    config = P25TrkSystemConfig(
        system_name="TSTSYS",
        long_name="TEST SYSTEM",
        trunk_set_name="TSTTRK",
        group_set_name="TSTGRP",
        wan_name="TSTW",
        home_unit_id=1, system_id=1,
        iden_set_name="TSTI",
    )
    add_p25_trunked_system(prs, config, trunk_set=ts,
                            group_set=gs, iden_set=iden)

    cap = estimate_capacity(prs)
    assert cap['iden_sets']['used'] >= 1
    assert 'TSTI' in cap['iden_sets']['details']
    # Should have 2 active elements
    assert cap['iden_sets']['details']['TSTI'] == 2


def test_capacity_zones_needed():
    """Zone estimate accounts for both TGs and conv channels."""
    prs = create_blank_prs()
    # Add 100 talkgroups
    tgs = [(i, f"TG{i:05d}", f"TG {i}") for i in range(1, 101)]
    gs = make_group_set("ZNS", tgs)
    ts = make_trunk_set("ZNS", [(851.0125, 806.0125)])
    config = P25TrkSystemConfig(
        system_name="ZNS",
        long_name="ZONE TEST",
        trunk_set_name="ZNS",
        group_set_name="ZNS",
        wan_name="ZNSWAN",
        home_unit_id=1, system_id=1,
    )
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    cap = estimate_capacity(prs)
    zones = cap['zones_needed']
    # 100 TGs + 1 default conv = 101 items
    # 101 / 48 = 3 zones minimum (ceil)
    assert zones['total_items'] == 101
    assert zones['zones_min'] == 3  # ceil(101/48) = 3


def test_capacity_percentage_accuracy():
    """Verify percentage calculation is correct."""
    prs = create_blank_prs()
    cap = estimate_capacity(prs)
    sys_info = cap['systems']
    expected_pct = sys_info['used'] / sys_info['max'] * 100
    assert abs(sys_info['pct'] - expected_pct) < 0.01
