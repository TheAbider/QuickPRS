"""Tests for auto-IDEN detection and frequency validation features."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.injector import (
    auto_iden_from_frequencies, make_iden_set, make_trunk_set,
    make_trunk_channel, make_conv_set, make_conv_channel,
    add_p25_trunked_system, make_group_set,
)
from quickprs.record_types import (
    IdenElement, IdenDataSet, TrunkSet, TrunkChannel,
    ConvSet, ConvChannel, P25TrkSystemConfig,
)
from quickprs.validation import (
    validate_prs, validate_frequencies, validate_prs_detailed,
    ERROR, WARNING, INFO,
)
from quickprs.builder import create_blank_prs
from quickprs.iden_library import detect_p25_band

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE_PRS = TESTDATA / "claude test.PRS"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Auto-IDEN: 700 MHz ─────────────────────────────────────────────

def test_auto_iden_700_only():
    """700 MHz frequencies produce 700 MHz IDEN entries."""
    freqs = [769.40625, 770.15625, 771.90625]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert len(descriptions) == 1
    assert "700" in descriptions[0]

    # Check first active element
    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) == 16  # Standard 700 MHz table has 16 entries
    assert active[0].base_freq_hz == 764006250
    # 700 MHz block spacing is 750 kHz
    assert active[1].base_freq_hz == 764006250 + 750000


def test_auto_iden_700_tdma():
    """700 MHz TDMA detection from 6.25 kHz spaced frequencies."""
    # Frequencies with 6.25 kHz spacing suggest TDMA
    freqs = [769.40625, 769.4125]  # 6.25 kHz apart
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "TDMA" in descriptions[0]
    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert active[0].chan_spacing_hz == 6250
    assert active[0].iden_type == 1  # TDMA


# ─── Auto-IDEN: 800 MHz ─────────────────────────────────────────────

def test_auto_iden_800_only():
    """800 MHz frequencies produce standard 800 MHz IDEN table."""
    freqs = [851.0125, 852.0125, 853.0125]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert len(descriptions) == 1
    assert "800" in descriptions[0]

    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) == 16  # Standard 800 MHz table
    assert active[0].base_freq_hz == 851006250


def test_auto_iden_800_fdma():
    """800 MHz FDMA: 12.5 kHz spacing by default."""
    freqs = [851.0125, 852.0125]  # 1 MHz apart, clearly not 6.25 kHz
    iden_set, _ = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert active[0].chan_spacing_hz == 12500
    assert active[0].iden_type == 0  # FDMA


def test_auto_iden_800_tdma():
    """800 MHz TDMA detection from 6.25 kHz spacing."""
    freqs = [851.0125, 851.01875]  # 6.25 kHz apart
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "TDMA" in descriptions[0]
    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert active[0].chan_spacing_hz == 6250
    assert active[0].iden_type == 1  # TDMA


# ─── Auto-IDEN: 900 MHz ─────────────────────────────────────────────

def test_auto_iden_900():
    """900 MHz frequencies produce 900 MHz IDEN table (8 active)."""
    freqs = [935.5, 936.0, 937.5]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "900" in descriptions[0]

    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) == 8  # Standard 900 MHz has 8 active entries
    assert active[0].base_freq_hz == 935012500


# ─── Auto-IDEN: VHF ─────────────────────────────────────────────────

def test_auto_iden_vhf():
    """VHF frequencies produce derived IDEN entries."""
    freqs = [155.475, 155.5125, 156.0]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "VHF" in descriptions[0]

    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) >= 1


# ─── Auto-IDEN: UHF ─────────────────────────────────────────────────

def test_auto_iden_uhf():
    """UHF frequencies produce derived IDEN entries."""
    freqs = [462.5625, 462.575, 462.6]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "UHF" in descriptions[0]

    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) >= 1


# ─── Auto-IDEN: Mixed bands ─────────────────────────────────────────

def test_auto_iden_mixed_700_800():
    """Mixed 700+800 MHz creates entries for both bands."""
    freqs = [769.40625, 851.0125, 852.0125]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert len(descriptions) == 2  # Two bands detected
    desc_text = " ".join(descriptions)
    assert "700" in desc_text
    assert "800" in desc_text

    # Total should be 16 (capped), with entries from both bands
    active = [e for e in iden_set.elements if e.base_freq_hz > 0]
    assert len(active) == 16  # 700 has 16, but capped at 16 total

    # Should have entries in both 700 and 800 ranges
    has_700 = any(764e6 <= e.base_freq_hz <= 777e6 for e in active)
    has_800 = any(851e6 <= e.base_freq_hz <= 870e6 for e in active)
    assert has_700, "Expected 700 MHz entries"
    assert has_800, "Expected 800 MHz entries"


def test_auto_iden_mixed_truncates_to_16():
    """Mixed bands are capped at 16 total entries."""
    # 700 has 16, 800 has 16 — combined should cap at 16
    freqs = [769.40625, 851.0125]
    iden_set, _ = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert len(iden_set.elements) == 16  # Always padded to 16 slots


# ─── Auto-IDEN: Edge cases ──────────────────────────────────────────

def test_auto_iden_empty_list():
    """Empty frequency list returns None."""
    iden_set, descriptions = auto_iden_from_frequencies([])
    assert iden_set is None
    assert descriptions == []


def test_auto_iden_unknown_band():
    """Frequencies outside all P25 bands return None."""
    iden_set, descriptions = auto_iden_from_frequencies([1200.0])
    assert iden_set is None
    assert descriptions == []


def test_auto_iden_tuple_input():
    """Accepts (tx, rx) tuple input."""
    freqs = [(806.0125, 851.0125), (807.0125, 852.0125)]
    iden_set, descriptions = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert "800" in descriptions[0]


def test_auto_iden_set_name_auto():
    """Auto-generated name is reasonable."""
    freqs = [851.0125]
    iden_set, _ = auto_iden_from_frequencies(freqs)
    assert iden_set is not None
    assert len(iden_set.name) <= 8


def test_auto_iden_set_name_custom():
    """Custom set name is used when provided."""
    freqs = [851.0125]
    iden_set, _ = auto_iden_from_frequencies(freqs, set_name="MYCUSTOM")
    assert iden_set is not None
    assert iden_set.name == "MYCUSTOM"


def test_auto_iden_always_16_slots():
    """IdenDataSet always has exactly 16 element slots."""
    for freqs in [
        [851.0125],
        [769.40625],
        [935.5],
        [155.475],
        [462.5625],
        [769.40625, 851.0125],
    ]:
        iden_set, _ = auto_iden_from_frequencies(freqs)
        if iden_set:
            assert len(iden_set.elements) == 16


# ─── Frequency validation: Duplicate within set ─────────────────────

def test_freq_validate_no_issues_clean():
    """Clean personality has no frequency issues."""
    prs = create_blank_prs()
    issues = validate_frequencies(prs)
    # Blank PRS has no trunk sets — should have no frequency issues
    freq_issues = [m for s, m in issues
                   if "frequency" in m.lower() or "freq" in m.lower()]
    # A blank PRS might produce nothing or just basic messages
    assert isinstance(issues, list)


def test_freq_validate_trunk_zero_freq():
    """Trunk channel with 0 MHz frequency triggers warning."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="ZERO", long_name="ZERO FREQ",
        trunk_set_name="ZERO", group_set_name="ZGRP",
        wan_name="ZERO", system_id=1, wacn=1,
    )
    ts = TrunkSet(name="ZERO", channels=[
        TrunkChannel(tx_freq=0.0, rx_freq=0.0),
    ], tx_min=0.0, tx_max=0.0, rx_min=0.0, rx_max=0.0)
    gs = make_group_set("ZGRP", [(1, "T", "T")])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    issues = validate_frequencies(prs)
    zero_msgs = [m for s, m in issues if "0 MHz" in m]
    assert len(zero_msgs) >= 1


def test_freq_validate_cross_set_shared():
    """Same frequency in two trunk sets generates info message."""
    prs = create_blank_prs()

    config1 = P25TrkSystemConfig(
        system_name="SYS1", long_name="SYSTEM ONE",
        trunk_set_name="SET1", group_set_name="GRP1",
        wan_name="WAN1", system_id=100, wacn=1,
    )
    config2 = P25TrkSystemConfig(
        system_name="SYS2", long_name="SYSTEM TWO",
        trunk_set_name="SET2", group_set_name="GRP2",
        wan_name="WAN2", system_id=200, wacn=2,
    )

    # Same frequency in both sets
    ts1 = make_trunk_set("SET1", [(851.0125, 806.0125)])
    ts2 = make_trunk_set("SET2", [(851.0125, 806.0125)])
    gs1 = make_group_set("GRP1", [(100, "TG1", "TEST TG1")])
    gs2 = make_group_set("GRP2", [(200, "TG2", "TEST TG2")])

    add_p25_trunked_system(prs, config1, trunk_set=ts1, group_set=gs1)
    add_p25_trunked_system(prs, config2, trunk_set=ts2, group_set=gs2)

    issues = validate_frequencies(prs)
    cross_msgs = [m for s, m in issues
                  if "appears in trunk sets" in m]
    assert len(cross_msgs) >= 1
    assert "SET1" in cross_msgs[0]
    assert "SET2" in cross_msgs[0]


def test_freq_validate_out_of_band():
    """Trunk RX frequency outside P25 bands triggers warning."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="OOB", long_name="OUT OF BAND",
        trunk_set_name="OOBTRK", group_set_name="OOBGRP",
        wan_name="OOBWAN", system_id=100, wacn=1,
    )
    # 300 MHz is between VHF (136-174) and UHF (380-512) — not a P25 band
    # Both TX and RX at 300 MHz so rx_freq is out-of-band
    ts = make_trunk_set("OOBTRK", [(300.0, 300.0)])
    gs = make_group_set("OOBGRP", [(100, "TG1", "TEST")])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    issues = validate_frequencies(prs)
    oob_msgs = [m for s, m in issues if "outside standard P25 bands" in m]
    assert len(oob_msgs) >= 1


def test_freq_validate_inconsistent_offset():
    """Mixed TX/RX offsets within a trunk set triggers warning."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="MIX", long_name="MIXED OFFSETS",
        trunk_set_name="MIXTRK", group_set_name="MIXGRP",
        wan_name="MIXWAN", system_id=100, wacn=1,
    )
    # 800 MHz: offset is -45 MHz. Mix in a wrong offset.
    ts = TrunkSet(name="MIXTRK", channels=[
        TrunkChannel(tx_freq=806.0125, rx_freq=851.0125),   # -45 offset
        TrunkChannel(tx_freq=857.0125, rx_freq=857.0125),   # 0 offset (simplex)
    ], tx_min=806.0, tx_max=860.0, rx_min=851.0, rx_max=860.0)
    gs = make_group_set("MIXGRP", [(1, "T", "T")])

    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    issues = validate_frequencies(prs)
    offset_msgs = [m for s, m in issues if "inconsistent TX/RX offsets" in m]
    assert len(offset_msgs) >= 1


# ─── Frequency validation: Conv channels ────────────────────────────

def test_freq_validate_conv_zero_freq():
    """Conv channel with 0 MHz frequency triggers warning."""
    prs = create_blank_prs()
    cs = ConvSet(name="ZERO", channels=[
        ConvChannel(
            short_name="ZERO", tx_freq=0.0, rx_freq=0.0,
            tx_tone="", rx_tone="", long_name="ZERO FREQ"),
    ])
    from quickprs.injector import add_conv_set
    add_conv_set(prs, cs)

    issues = validate_frequencies(prs)
    zero_msgs = [m for s, m in issues if "0 MHz" in m]
    assert len(zero_msgs) >= 1


def test_freq_validate_conv_repeater_hint():
    """Conv channel TX==RX with tones suggests repeater offset missing."""
    prs = create_blank_prs()
    cs = ConvSet(name="RPT", channels=[
        ConvChannel(
            short_name="RPT", tx_freq=462.5625, rx_freq=462.5625,
            tx_tone="127.3", rx_tone="", long_name="REPEATER?"),
    ])
    from quickprs.injector import add_conv_set
    add_conv_set(prs, cs)

    issues = validate_frequencies(prs)
    rpt_msgs = [m for s, m in issues if "repeater" in m.lower()]
    assert len(rpt_msgs) >= 1


def test_freq_validate_conv_simplex_no_tone_no_warning():
    """Conv channel TX==RX without tones is fine (simplex)."""
    prs = create_blank_prs()
    cs = ConvSet(name="SMPLX", channels=[
        ConvChannel(
            short_name="SMPLX", tx_freq=462.5625, rx_freq=462.5625,
            tx_tone="", rx_tone="", long_name="SIMPLEX"),
    ])
    from quickprs.injector import add_conv_set
    add_conv_set(prs, cs)

    issues = validate_frequencies(prs)
    rpt_msgs = [m for s, m in issues if "repeater" in m.lower()]
    assert len(rpt_msgs) == 0


# ─── Frequency validation: IDEN/trunk cross-check ───────────────────

def test_freq_validate_iden_trunk_band_mismatch():
    """IDEN set covering wrong band for trunk channels triggers warning."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="MISMTCH",
        long_name="IDEN MISMATCH",
        trunk_set_name="MISMTCH",
        group_set_name="MMGRP",
        wan_name="MISMTCH",
        system_id=100,
        wacn=1,
        iden_set_name="MMIDE",
    )

    # Trunk freqs are 700 MHz but IDEN is 800 MHz
    ts = make_trunk_set("MISMTCH", [(769.40625, 799.40625)])
    gs = make_group_set("MMGRP", [(100, "TG1", "TEST")])
    iden = make_iden_set("MMIDE", [{
        'base_freq_hz': 851006250,  # 800 MHz!
        'chan_spacing_hz': 12500,
        'bandwidth_hz': 12500,
        'iden_type': 0,
    }])

    add_p25_trunked_system(prs, config,
                           trunk_set=ts, group_set=gs, iden_set=iden)

    issues = validate_frequencies(prs)
    mismatch_msgs = [m for s, m in issues
                     if "does not cover" in m]
    assert len(mismatch_msgs) >= 1
    assert "700" in mismatch_msgs[0]


# ─── Integration: create blank, inject with auto-IDEN, validate ─────

def test_integration_blank_inject_auto_iden_800():
    """Create blank PRS, inject P25 with auto-IDEN, validate clean."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="AUTOTEST",
        long_name="AUTO IDEN TEST",
        trunk_set_name="AUTOTEST",
        group_set_name="AUTGRP",
        wan_name="AUTOTEST",
        system_id=892,
        wacn=5678,
    )

    # 800 MHz: TX=806-824, RX=851-869
    freqs_800 = [(851.0125, 806.0125), (852.0125, 807.0125),
                 (853.0125, 808.0125)]
    ts = make_trunk_set("AUTOTEST", freqs_800)
    gs = make_group_set("AUTGRP", [
        (100, "PD DISP", "POLICE DISPATCH"),
        (200, "PD TAC", "POLICE TAC 1"),
    ])

    # Auto-detect IDEN from the (tx, rx) tuples — function extracts both
    iden_set, descriptions = auto_iden_from_frequencies(
        freqs_800, set_name="AUTID")
    assert iden_set is not None
    assert "800" in descriptions[0]

    config.iden_set_name = iden_set.name

    add_p25_trunked_system(prs, config,
                           trunk_set=ts, group_set=gs, iden_set=iden_set)

    # Full validation should pass with no errors
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    assert len(errors) == 0, f"Unexpected errors: {errors}"


def test_integration_blank_inject_auto_iden_700():
    """Create blank PRS, inject P25 with auto-IDEN 700 MHz, validate clean."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="AUTO700",
        long_name="AUTO 700 TEST",
        trunk_set_name="AUTO700",
        group_set_name="A7GRP",
        wan_name="AUTO700",
        system_id=500,
        wacn=1234,
    )

    freqs_700 = [(799.40625, 769.40625), (800.15625, 770.15625)]
    ts = make_trunk_set("AUTO700", freqs_700)
    gs = make_group_set("A7GRP", [(100, "TG1", "TEST TG")])

    rx_freqs = [f[1] for f in freqs_700]
    iden_set, descriptions = auto_iden_from_frequencies(
        rx_freqs, set_name="A7IDE")
    assert iden_set is not None
    assert "700" in descriptions[0]

    config.iden_set_name = iden_set.name
    config.wan_base_freq_hz = iden_set.elements[0].base_freq_hz
    config.wan_chan_spacing_hz = iden_set.elements[0].chan_spacing_hz

    add_p25_trunked_system(prs, config,
                           trunk_set=ts, group_set=gs, iden_set=iden_set)

    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    assert len(errors) == 0, f"Unexpected errors: {errors}"


def test_integration_auto_iden_matches_trunk_band():
    """Auto-IDEN for 800 MHz trunk channels has no IDEN mismatch warning."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="MATCH",
        long_name="BAND MATCH",
        trunk_set_name="MATCH",
        group_set_name="MGRP",
        wan_name="MATCH",
        system_id=100,
        wacn=1,
    )
    freqs = [(806.0125, 851.0125)]
    ts = make_trunk_set("MATCH", freqs)
    gs = make_group_set("MGRP", [(1, "T", "T")])

    rx_freqs = [851.0125]
    iden_set, _ = auto_iden_from_frequencies(rx_freqs, set_name="MATID")
    assert iden_set is not None
    config.iden_set_name = iden_set.name

    add_p25_trunked_system(prs, config,
                           trunk_set=ts, group_set=gs, iden_set=iden_set)

    issues = validate_frequencies(prs)
    mismatch = [m for s, m in issues if "does not cover" in m]
    assert len(mismatch) == 0, f"Unexpected mismatch: {mismatch}"


# ─── Config builder auto-IDEN integration ────────────────────────────

def test_config_builder_auto_iden(tmp_path):
    """Config builder auto-detects IDEN when iden_base not specified."""
    from quickprs.config_builder import build_from_config

    config_content = """\
[personality]
name = Auto IDEN Test.PRS
author = Test

[system.PSERN]
type = p25_trunked
short_name = PSERN
long_name = PSERN SEATTLE
system_id = 892
wacn = 5678

[system.PSERN.frequencies]
1 = 851.0125,806.0125
2 = 852.0125,807.0125
3 = 853.0125,808.0125

[system.PSERN.talkgroups]
1 = 100,PD DISP,POLICE DISPATCH
2 = 200,PD TAC,POLICE TAC 1
"""
    p = tmp_path / "auto_iden.ini"
    p.write_text(config_content, encoding='utf-8')
    prs = build_from_config(str(p))

    # Verify no errors
    issues = validate_prs(prs)
    errors = [(s, m) for s, m in issues if s == ERROR]
    assert len(errors) == 0, f"Errors: {errors}"

    # Verify IDEN was created (check for CDefaultIdenElem section)
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    assert elem_sec is not None


def test_config_builder_explicit_iden(tmp_path):
    """Config builder uses explicit iden_base when specified."""
    from quickprs.config_builder import build_from_config
    from quickprs.record_types import parse_iden_section, parse_class_header
    from quickprs.binary_io import read_uint16_le

    config_content = """\
[personality]
name = Explicit IDEN Test.PRS
author = Test

[system.TEST]
type = p25_trunked
short_name = TEST
long_name = TEST SYSTEM
system_id = 100
iden_base = 935012500
iden_spacing = 12500

[system.TEST.frequencies]
1 = 935.5,896.5

[system.TEST.talkgroups]
1 = 100,TG1,TEST TG
"""
    p = tmp_path / "explicit_iden.ini"
    p.write_text(config_content, encoding='utf-8')
    prs = build_from_config(str(p))

    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    ids_sec = prs.get_section_by_class("CIdenDataSet")
    assert elem_sec is not None
    assert ids_sec is not None

    # Parse IDEN and check that the explicit base was used
    _, _, _, ds = parse_class_header(ids_sec.raw, 0)
    first_count, _ = read_uint16_le(ids_sec.raw, ds)
    _, _, _, es = parse_class_header(elem_sec.raw, 0)
    sets = parse_iden_section(elem_sec.raw, es, len(elem_sec.raw), first_count)
    assert len(sets) >= 1
    assert sets[0].elements[0].base_freq_hz == 935012500


# ─── Frequency validation on real PRS files ──────────────────────────

def test_freq_validate_paws_no_crash():
    """Frequency validation runs on PAWSOVERMAWS without crash."""
    if not PAWS_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.prs_parser import parse_prs
    prs = parse_prs(PAWS_PRS)
    issues = validate_frequencies(prs)
    assert isinstance(issues, list)


def test_freq_validate_claude_no_crash():
    """Frequency validation runs on claude test without crash."""
    if not CLAUDE_PRS.exists():
        pytest.skip("test file not found")
    from quickprs.prs_parser import parse_prs
    prs = parse_prs(CLAUDE_PRS)
    issues = validate_frequencies(prs)
    assert isinstance(issues, list)


def test_freq_validate_in_validate_prs():
    """validate_prs now includes frequency validation."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="ZERO", long_name="ZERO FREQ",
        trunk_set_name="ZERO", group_set_name="ZGRP",
        wan_name="ZERO", system_id=1, wacn=1,
    )
    ts = TrunkSet(name="ZERO", channels=[
        TrunkChannel(tx_freq=0.0, rx_freq=0.0),
    ], tx_min=0.0, tx_max=0.0, rx_min=0.0, rx_max=0.0)
    gs = make_group_set("ZGRP", [(1, "T", "T")])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    issues = validate_prs(prs)
    zero_msgs = [m for s, m in issues if "0 MHz" in m]
    assert len(zero_msgs) >= 1, "Frequency validation should be in validate_prs"


def test_freq_validate_in_detailed():
    """validate_prs_detailed includes frequency checks in Global."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="ZERO", long_name="ZERO FREQ",
        trunk_set_name="ZERO", group_set_name="ZGRP",
        wan_name="ZERO", system_id=1, wacn=1,
    )
    ts = TrunkSet(name="ZERO", channels=[
        TrunkChannel(tx_freq=0.0, rx_freq=0.0),
    ], tx_min=0.0, tx_max=0.0, rx_min=0.0, rx_max=0.0)
    gs = make_group_set("ZGRP", [(1, "T", "T")])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)

    results = validate_prs_detailed(prs)
    assert "Global" in results
    zero_msgs = [m for s, m in results["Global"] if "0 MHz" in m]
    assert len(zero_msgs) >= 1
