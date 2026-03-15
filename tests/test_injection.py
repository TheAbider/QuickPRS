"""Injection tests — add data to test files, verify structure.

Tests add groups, channels, and IDEN elements to claude test.PRS
and verify:
1. Modified file is larger (data was added)
2. Group/channel/element counts increased correctly
3. Existing data is still intact
4. The section-level roundtrip still works (parse rebuilt -> rebuild again -> same bytes)
5. Validation passes with no errors
"""

import sys
import struct
from pathlib import Path
from copy import deepcopy
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.prs_writer import write_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    TrunkChannel, TrunkSet, ConvChannel, P25Group, P25GroupSet,
    IdenElement, IdenDataSet,
    parse_class_header, parse_group_section, parse_trunk_channel_section,
    parse_iden_section,
)
from quickprs.injector import (
    add_talkgroups, add_trunk_set, add_trunk_channels,
    add_group_set, add_iden_set, add_conv_set,
    add_p25_trunked_system, add_conv_system, add_p25_conv_system,
    remove_system_config, remove_system_by_class,
    make_p25_group, make_trunk_channel, make_trunk_set,
    make_group_set, make_iden_set,
    make_conv_channel, make_conv_set,
    add_preferred_entries, get_preferred_entries,
)
from quickprs.record_types import (
    P25TrkSystemConfig, ConvSystemConfig, P25ConvSystemConfig,
    parse_system_long_name, parse_system_short_name,
    is_system_config_data, parse_conv_channel_section,
    ConvSet, ConvChannel,
)
from quickprs.validation import validate_prs, validate_group_set, LIMITS

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _get_group_sets(prs):
    """Parse all group sets from a PRSFile using section raw bytes directly."""
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw), first_count)


def _get_trunk_sets(prs):
    """Parse all trunk sets from a PRSFile using section raw bytes directly."""
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    _, _, _, ts_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ts_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_trunk_channel_section(ch_sec.raw, ch_data, len(ch_sec.raw), first_count)


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_talkgroups():
    """Add talkgroups to an existing group set in claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    # Original: 1 group set "GROUP SE" with 1 group
    sets_before = _get_group_sets(prs)
    assert len(sets_before) == 1
    assert len(sets_before[0].groups) == 1

    # Add 3 new talkgroups
    new_groups = [
        make_p25_group(100, "TEST PD", "TEST PD DISPATCH"),
        make_p25_group(200, "TEST TAC", "TEST PD TAC"),
        make_p25_group(300, "TEST ADM", "TEST PD ADMIN"),
    ]
    add_talkgroups(prs, "GROUP SE", new_groups)

    # Verify
    sets_after = _get_group_sets(prs)
    assert len(sets_after) == 1, f"Set count changed: {len(sets_after)}"
    assert len(sets_after[0].groups) == 4, f"Group count: {len(sets_after[0].groups)}"

    # Original group still intact
    orig = sets_after[0].groups[0]
    assert orig.group_name == "name", f"Original group name: {orig.group_name}"
    assert orig.group_id == 12312, f"Original group ID: {orig.group_id}"

    # New groups present
    assert sets_after[0].groups[1].group_name == "TEST PD"
    assert sets_after[0].groups[1].group_id == 100
    assert sets_after[0].groups[2].group_name == "TEST TAC"
    assert sets_after[0].groups[3].group_name == "TEST ADM"

    # File grew
    new_size = len(prs.to_bytes())
    assert new_size > original_size, f"File didn't grow: {new_size} <= {original_size}"

    print(f"  PASS: Added 3 talkgroups (1 -> 4), size {original_size} -> {new_size}")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_group_set():
    """Add an entirely new group set to claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    sets_before = _get_group_sets(prs)
    assert len(sets_before) == 1

    # Create new group set
    new_set = make_group_set("NEW SET", [
        (500, "NEW GRP1", "NEW GROUP ONE"),
        (501, "NEW GRP2", "NEW GROUP TWO"),
        (502, "NEW GRP3", "NEW GROUP THREE"),
    ])
    add_group_set(prs, new_set)

    # Verify
    sets_after = _get_group_sets(prs)
    assert len(sets_after) == 2, f"Set count: {len(sets_after)}"
    assert sets_after[0].name == "GROUP SE", f"First set: {sets_after[0].name}"
    assert sets_after[1].name == "NEW SET", f"Second set: {sets_after[1].name}"
    assert len(sets_after[1].groups) == 3

    # Original set still intact
    assert len(sets_after[0].groups) == 1
    assert sets_after[0].groups[0].group_name == "name"

    new_size = len(prs.to_bytes())
    print(f"  PASS: Added new group set 'NEW SET' with 3 groups, "
          f"size {original_size} -> {new_size}")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_trunk_channels():
    """Add trunk channels to existing set in claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    sets_before = _get_trunk_sets(prs)
    orig_count = len(sets_before[0].channels)

    # Add 2 new channels
    new_channels = [
        make_trunk_channel(851.0, 806.0),
        make_trunk_channel(852.0, 807.0),
    ]
    add_trunk_channels(prs, sets_before[0].name, new_channels)

    sets_after = _get_trunk_sets(prs)
    assert len(sets_after[0].channels) == orig_count + 2

    # Original channels intact
    for i in range(orig_count):
        assert (abs(sets_after[0].channels[i].tx_freq -
                    sets_before[0].channels[i].tx_freq) < 0.001)

    new_size = len(prs.to_bytes())
    print(f"  PASS: Added 2 trunk channels ({orig_count} -> {orig_count + 2}), "
          f"size {original_size} -> {new_size}")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_trunk_set():
    """Add a new trunk set to claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    sets_before = _get_trunk_sets(prs)

    freqs = [(851.0 + i * 0.5, 806.0 + i * 0.5) for i in range(5)]
    new_set = make_trunk_set("TEST", freqs, tx_min=800.0, tx_max=860.0,
                              rx_min=800.0, rx_max=860.0)
    add_trunk_set(prs, new_set)

    sets_after = _get_trunk_sets(prs)
    assert len(sets_after) == len(sets_before) + 1
    assert sets_after[-1].name == "TEST"
    assert len(sets_after[-1].channels) == 5

    new_size = len(prs.to_bytes())
    print(f"  PASS: Added new trunk set 'TEST' with 5 channels, "
          f"size {original_size} -> {new_size}")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_injection_double_roundtrip():
    """Parse -> inject -> write -> parse again -> verify consistency."""
    prs = parse_prs(TESTDATA / "claude test.PRS")

    # Inject some data
    new_groups = [make_p25_group(999, "ROUNDTR", "ROUNDTRIP TEST")]
    add_talkgroups(prs, "GROUP SE", new_groups)

    # Get bytes
    modified_bytes = prs.to_bytes()

    # Write to temp file and re-parse
    tmp = TESTDATA / "injection_test.tmp"
    try:
        tmp.write_bytes(modified_bytes)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()

        assert modified_bytes == rebuilt, (
            f"Double roundtrip mismatch: {len(modified_bytes)} vs {len(rebuilt)}")

        # Verify the injected group survived
        sets = _get_group_sets(prs2)
        found = any(g.group_name == "ROUNDTR" for g in sets[0].groups)
        assert found, "Injected group not found after re-parse"

        print(f"  PASS: Double roundtrip ({len(modified_bytes)} bytes)")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_validation_clean():
    """Validate unmodified PAWSOVERMAWS — should have no errors."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    issues = validate_prs(prs)

    errors = [i for i in issues if i[0] == 'ERROR']
    warnings = [i for i in issues if i[0] == 'WARNING']

    if errors:
        for sev, msg in errors:
            print(f"  {sev}: {msg}")

    assert len(errors) == 0, f"PAWSOVERMAWS has {len(errors)} validation errors"
    print(f"  PASS: PAWSOVERMAWS validates clean ({len(warnings)} warnings)")


def test_validation_127_limit():
    """Verify the 127 scan limit is enforced."""
    # Create a set with 128 scan-enabled groups (should error)
    groups = [make_p25_group(i, f"TG{i:05d}", f"TALKGROUP {i}") for i in range(128)]
    gset = P25GroupSet(name="TOO MANY", groups=groups)

    issues = validate_group_set(gset)
    errors = [i for i in issues if i[0] == 'ERROR']
    assert any('128' in msg or '127' in msg or 'scan' in msg.lower()
               for _, msg in errors), f"127-limit not caught: {errors}"

    print(f"  PASS: 127 scan limit enforced ({len(errors)} errors)")


def test_validation_name_lengths():
    """Verify name length limits are enforced."""
    gset = P25GroupSet(name="TEST", groups=[
        P25Group(group_name="TOOLONGNAME", group_id=1, long_name="x" * 20),
    ])
    issues = validate_group_set(gset)
    errors = [i for i in issues if i[0] == 'ERROR']
    assert len(errors) >= 2, f"Expected 2 name length errors, got {len(errors)}"
    print(f"  PASS: Name length limits enforced ({len(errors)} errors)")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_system_name_extraction():
    """Extract system names from header and config data sections."""
    prs = parse_prs(TESTDATA / "claude test.PRS")

    # Extract short name from CP25TrkSystem header
    header = prs.get_section_by_class("CP25TrkSystem")
    assert header is not None
    short = parse_system_short_name(header.raw)
    assert short == "psern", f"Expected 'psern', got '{short}'"

    # Extract short name from CConvSystem header
    conv_header = prs.get_section_by_class("CConvSystem")
    assert conv_header is not None
    conv_short = parse_system_short_name(conv_header.raw)
    assert conv_short == "convent", f"Expected 'convent', got '{conv_short}'"

    # Extract long name from system config data section
    # Section [2] is the P25 trunk system config data
    data_sec = prs.sections[2]
    assert is_system_config_data(data_sec.raw), "Section [2] should be system config"
    long_name = parse_system_long_name(data_sec.raw)
    assert long_name == "PSERN LONG NAME", f"Expected 'PSERN LONG NAME', got '{long_name}'"

    print("  PASS: System name extraction")


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_system_name_extraction_pawsovermaws():
    """Extract system names from PAWSOVERMAWS test file."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # P25 trunk system header
    header = prs.get_section_by_class("CP25TrkSystem")
    short = parse_system_short_name(header.raw)
    assert short == "PSERN", f"Expected 'PSERN', got '{short}'"

    # Config data sections with long names
    data_sec = prs.sections[6]  # PSERN system config data
    assert is_system_config_data(data_sec.raw)
    long_name = parse_system_long_name(data_sec.raw)
    assert long_name == "PSERN SEATTLE", f"Expected 'PSERN SEATTLE', got '{long_name}'"

    # Another system config data
    data_sec8 = prs.sections[8]
    assert is_system_config_data(data_sec8.raw)
    long_name8 = parse_system_long_name(data_sec8.raw)
    assert long_name8 == "PSRS TACOMA", f"Expected 'PSRS TACOMA', got '{long_name8}'"

    print("  PASS: System name extraction (PAWSOVERMAWS)")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_system_config_detection():
    """Test is_system_config_data() on various section types."""
    prs = parse_prs(TESTDATA / "claude test.PRS")

    # Section [2] is system config data
    assert is_system_config_data(prs.sections[2].raw), "Section [2] should be config"

    # Section [0] (CPersonality) is NOT config data
    assert not is_system_config_data(prs.sections[0].raw), "CPersonality is not config"

    # CTrunkChannel section is NOT config data
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    assert not is_system_config_data(ch_sec.raw), "CTrunkChannel is not config"

    print("  PASS: System config detection")


def test_p25_trunked_system_config_build():
    """Test building P25TrkSystemConfig header and data sections."""
    config = P25TrkSystemConfig(
        system_name="TESTNET",
        long_name="TEST NETWORK",
        trunk_set_name="TESTNET",
        group_set_name="TESTNET",
        wan_name="TESTNET",
        home_unit_id=12345,
        system_id=0x3AB,
    )

    # Build header
    header = config.build_header_section()
    assert header[:2] == b'\xff\xff', "Header should start with ffff"
    assert b'CP25TrkSystem' in header
    assert b'TESTNET' in header

    # Parse the header back
    short = parse_system_short_name(header)
    assert short == "TESTNET", f"Expected 'TESTNET', got '{short}'"

    # Build data section
    data = config.build_data_section()
    assert data[:2] == b'\xff\xff', "Data should start with ffff"
    assert is_system_config_data(data), "Data should be detected as system config"

    # Parse long name back
    long_name = parse_system_long_name(data)
    assert long_name == "TEST NETWORK", f"Expected 'TEST NETWORK', got '{long_name}'"

    # Verify set name references are in the data
    assert b'TESTNET' in data

    # Verify HomeUnitID is embedded (12345 = 0x3039)
    import struct
    hid_bytes = struct.pack('<I', 12345)
    assert hid_bytes in data, "HomeUnitID not found in data"

    # Verify SystemID is embedded (0x3AB = 939)
    sid_bytes = struct.pack('<I', 0x3AB)
    assert sid_bytes in data, "SystemID not found in data"

    print("  PASS: P25TrkSystem config build")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_p25_trunked_system():
    """Add a complete P25 trunked system to claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    # Count original sections
    orig_section_count = len(prs.sections)

    # Create system config
    config = P25TrkSystemConfig(
        system_name="NEWNET",
        long_name="NEW TEST NETWORK",
        trunk_set_name="NEWNET",
        group_set_name="NEWNET",
        wan_name="NEWNET",
        home_unit_id=99999,
        system_id=0x100,
    )

    # Create associated data sets
    trunk_set = make_trunk_set("NEWNET", [
        (806.0125, 851.0125),
        (806.2625, 851.2625),
    ])
    group_set = make_group_set("NEWNET", [
        (100, "TEST PD", "TEST PD DISPATCH"),
        (200, "TEST FD", "TEST FIRE DISP"),
    ])
    iden_set = make_iden_set("NEWNET", [
        {'base_freq_hz': 851006250, 'chan_spacing_hz': 6250,
         'bandwidth_hz': 6250, 'tx_offset': -45000000, 'iden_type': 1},
    ])

    # Inject the full system
    add_p25_trunked_system(prs, config,
                            trunk_set=trunk_set,
                            group_set=group_set,
                            iden_set=iden_set)

    # Verify file grew
    new_size = len(prs.to_bytes())
    assert new_size > original_size, f"File didn't grow: {new_size} <= {original_size}"

    # Verify new sections were added
    assert len(prs.sections) > orig_section_count

    # Verify the system config data can be found and has correct long name
    found_config = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == "NEW TEST NETWORK":
                found_config = True
                break
    assert found_config, "New system config data section not found"

    # Verify group set was added
    sets = _get_group_sets(prs)
    new_gset = None
    for s in sets:
        if s.name == "NEWNET":
            new_gset = s
            break
    assert new_gset is not None, "New group set 'NEWNET' not found"
    assert len(new_gset.groups) == 2

    # Verify trunk set was added
    tsets = _get_trunk_sets(prs)
    new_tset = None
    for s in tsets:
        if s.name == "NEWNET":
            new_tset = s
            break
    assert new_tset is not None, "New trunk set 'NEWNET' not found"
    assert len(new_tset.channels) == 2

    # Verify double roundtrip
    tmp = TESTDATA / "system_injection_test.tmp"
    try:
        modified_bytes = prs.to_bytes()
        tmp.write_bytes(modified_bytes)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified_bytes == rebuilt, "Double roundtrip mismatch after system injection"
        print(f"  PASS: Added complete P25 system 'NEWNET', "
              f"size {original_size} -> {new_size}, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_add_system_to_pawsovermaws():
    """Add a system to the larger PAWSOVERMAWS file."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    original_size = len(prs.to_bytes())

    config = P25TrkSystemConfig(
        system_name="ADDED",
        long_name="ADDED SYSTEM",
        trunk_set_name="ADDED",
        group_set_name="ADDED",
        wan_name="ADDED",
        system_id=0x555,
    )

    trunk_set = make_trunk_set("ADDED", [(806.5, 851.5)])
    group_set = make_group_set("ADDED", [(1000, "ADD TG", "ADDED TG")])

    add_p25_trunked_system(prs, config,
                            trunk_set=trunk_set,
                            group_set=group_set)

    new_size = len(prs.to_bytes())
    assert new_size > original_size

    # Verify existing data is intact
    sets = _get_group_sets(prs)
    existing_names = {s.name for s in sets}
    assert "ADDED" in existing_names, "New group set not found"

    # Verify double roundtrip
    tmp = TESTDATA / "pawsovermaws_injection_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch on PAWSOVERMAWS"
        print(f"  PASS: Added system to PAWSOVERMAWS, "
              f"size {original_size} -> {new_size}")
    finally:
        if tmp.exists():
            tmp.unlink()


def _get_conv_sets(prs):
    """Parse all conv sets from a PRSFile using section raw bytes directly."""
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    _, _, _, cs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, cs_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_conv_channel_section(ch_sec.raw, ch_data, len(ch_sec.raw),
                                       first_count)


def test_conv_system_config_build():
    """Test building ConvSystemConfig header and data sections."""
    config = ConvSystemConfig(
        system_name="ANALOG",
        long_name="ANALOG SYSTEM",
        conv_set_name="ANALOG",
    )

    # Build header
    header = config.build_header_section()
    assert header[:2] == b'\xff\xff'
    assert b'CConvSystem' in header
    short = parse_system_short_name(header)
    assert short == "ANALOG", f"Expected 'ANALOG', got '{short}'"

    # Build data
    data = config.build_data_section()
    assert data[:2] == b'\xff\xff'
    assert is_system_config_data(data)
    long_name = parse_system_long_name(data)
    assert long_name == "ANALOG SYSTEM", f"Expected 'ANALOG SYSTEM', got '{long_name}'"

    print("  PASS: ConvSystem config build")


def test_p25_conv_system_config_build():
    """Test building P25ConvSystemConfig header, data, and trailing sections."""
    config = P25ConvSystemConfig(
        system_name="P25CONV",
        long_name="P25 CONV SYS",
        conv_set_name="P25CONV",
    )

    header = config.build_header_section()
    assert b'CP25ConvSystem' in header
    short = parse_system_short_name(header)
    assert short == "P25CONV"

    data = config.build_data_section()
    assert is_system_config_data(data)

    trailing = config.build_trailing_section()
    assert trailing[:2] == b'\xff\xff'
    assert len(trailing) == 30

    print("  PASS: P25ConvSystem config build")


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_conv_system():
    """Add a conventional system with channels to claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    config = ConvSystemConfig(
        system_name="NEWCONV",
        long_name="NEW CONV SYS",
        conv_set_name="NEWCONV",
    )

    conv_set = make_conv_set("NEWCONV", [
        {'short_name': 'CH 1', 'tx_freq': 462.5625, 'long_name': 'CHANNEL 1'},
        {'short_name': 'CH 2', 'tx_freq': 462.5875, 'long_name': 'CHANNEL 2'},
        {'short_name': 'CH 3', 'tx_freq': 467.5625, 'rx_freq': 462.5625,
         'tx_tone': '100.0', 'rx_tone': '100.0', 'long_name': 'CHANNEL 3'},
    ])

    add_conv_system(prs, config, conv_set=conv_set)

    new_size = len(prs.to_bytes())
    assert new_size > original_size

    # Verify system config exists
    found = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == "NEW CONV SYS":
                found = True
                break
    assert found, "New conv system config not found"

    # Verify conv set was added
    sets = _get_conv_sets(prs)
    new_cset = None
    for s in sets:
        if s.name == "NEWCONV":
            new_cset = s
            break
    assert new_cset is not None, "New conv set 'NEWCONV' not found"
    assert len(new_cset.channels) == 3

    # Verify channel data
    assert new_cset.channels[0].short_name == "CH 1"
    assert abs(new_cset.channels[0].tx_freq - 462.5625) < 0.001
    assert new_cset.channels[2].tx_tone == "100.0"

    # Double roundtrip
    tmp = TESTDATA / "conv_system_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after conv system injection"
        print(f"  PASS: Added conv system 'NEWCONV', "
              f"size {original_size} -> {new_size}, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_p25_conv_system():
    """Add a P25 conventional system to claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_size = len(prs.to_bytes())

    config = P25ConvSystemConfig(
        system_name="P25NEWC",
        long_name="P25 NEW CONV",
        conv_set_name="P25NEWC",
    )

    add_p25_conv_system(prs, config)

    new_size = len(prs.to_bytes())
    assert new_size > original_size

    # Verify system config data exists
    found = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == "P25 NEW CONV":
                found = True
                break
    assert found, "P25 conv system config not found"

    # Verify CP25ConvSystem header
    header = prs.get_section_by_class("CP25ConvSystem")
    assert header is not None

    # Double roundtrip
    tmp = TESTDATA / "p25conv_system_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after P25 conv system injection"
        print(f"  PASS: Added P25 conv system, "
              f"size {original_size} -> {new_size}, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_add_conv_set_to_existing():
    """Add a new conv set to PAWSOVERMAWS (which already has conv sets)."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    sets_before = _get_conv_sets(prs)
    original_count = len(sets_before)

    new_set = make_conv_set("TESTSET", [
        {'short_name': 'TEST CH', 'tx_freq': 151.625, 'long_name': 'TEST CHANNEL'},
    ])
    add_conv_set(prs, new_set)

    sets_after = _get_conv_sets(prs)
    assert len(sets_after) == original_count + 1
    assert sets_after[-1].name == "TESTSET"
    assert len(sets_after[-1].channels) == 1

    # Verify existing sets intact
    for i in range(original_count):
        assert sets_after[i].name == sets_before[i].name
        assert len(sets_after[i].channels) == len(sets_before[i].channels)

    # Double roundtrip
    tmp = TESTDATA / "conv_set_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after conv set addition"
        print(f"  PASS: Added conv set to PAWSOVERMAWS "
              f"({original_count} -> {len(sets_after)} sets), roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_conv_from_parsed_channels():
    """Full flow: parse conv channels -> make_conv_set -> inject into PRS."""
    from quickprs.radioreference import (
        parse_pasted_conv_channels, conv_channels_to_set_data)

    text = """Frequency    License    Type    Tone    Alpha Tag    Description    Mode    Tag
155.76000    KQD949    BM    136.5 PL    LE D1    Law Dispatch    FMN    Law Dispatch
155.01000    KQD949    BM    D023 N    FIRE D1    Fire Dispatch    FMN    Fire Dispatch
462.56250    WQGX784    BM    250.3 PL    FRS 1    FRS Channel 1    FM    Business
"""
    # Parse conventional channels from RR-style table
    channels = parse_pasted_conv_channels(text)
    assert len(channels) == 3

    # Convert to make_conv_set format
    set_data = conv_channels_to_set_data(channels)
    assert len(set_data) == 3
    assert set_data[0]['short_name'] == "LE D1"
    assert set_data[0]['tx_tone'] == "136.5"

    # Build conv set and system config
    conv_set = make_conv_set("CONVTEST", set_data)
    assert conv_set.name == "CONVTEST"
    assert len(conv_set.channels) == 3

    # Verify channel data is correct
    ch0 = conv_set.channels[0]
    assert ch0.short_name == "LE D1"
    assert abs(ch0.rx_freq - 155.76) < 0.001
    assert ch0.tx_tone == "136.5"

    # Inject into PRS
    prs = parse_prs(TESTDATA / "claude test.PRS")
    conv_before = _get_conv_sets(prs)
    original_conv_count = len(conv_before)

    conv_config = ConvSystemConfig(
        system_name="CONVTEST",
        long_name="CONV TEST SYSTEM",
        conv_set_name="CONVTEST",
    )
    add_conv_system(prs, conv_config, conv_set=conv_set)

    conv_after = _get_conv_sets(prs)
    assert len(conv_after) == original_conv_count + 1
    assert conv_after[-1].name == "CONVTEST"
    assert len(conv_after[-1].channels) == 3

    # Double roundtrip
    tmp = TESTDATA / "conv_parsed_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after conv injection"
        print(f"  PASS: Parsed conv channels -> injected "
              f"({len(channels)} channels), roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_remove_system_config():
    """Remove a system config data section by long name."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    original_count = len(prs.sections)

    # PSERN SEATTLE is the long name of the first P25 system config
    result = remove_system_config(prs, "PSERN SEATTLE")
    assert result is True, "Should have found and removed PSERN SEATTLE"
    assert len(prs.sections) < original_count

    # Verify it's gone
    found = False
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            name = parse_system_long_name(sec.raw)
            if name == "PSERN SEATTLE":
                found = True
    assert not found, "PSERN SEATTLE should be gone"

    # Trying to remove again should return False
    result2 = remove_system_config(prs, "PSERN SEATTLE")
    assert result2 is False

    # Double roundtrip
    tmp = TESTDATA / "remove_config_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after removal"
        print(f"  PASS: Removed PSERN SEATTLE config, "
              f"sections {original_count} -> {len(prs.sections)}, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_remove_system_by_class():
    """Remove all sections for a system type."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    original_count = len(prs.sections)

    # Remove CConvSystem
    removed = remove_system_by_class(prs, "CConvSystem")
    assert removed >= 2, f"Expected at least 2 sections removed, got {removed}"
    assert len(prs.sections) == original_count - removed

    # CConvSystem header should be gone
    assert prs.get_section_by_class("CConvSystem") is None

    # Double roundtrip
    tmp = TESTDATA / "remove_class_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        rebuilt = prs2.to_bytes()
        assert modified == rebuilt, "Roundtrip mismatch after class removal"
        print(f"  PASS: Removed CConvSystem ({removed} sections), roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_batch_modify_selected_tgs():
    """Batch-modify specific selected talkgroups by ID."""
    from quickprs.injector import (
        _parse_section_data, _replace_group_sections,
        _get_header_bytes, _get_first_count,
    )

    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    assert grp_sec and set_sec

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")
    existing_sets = _parse_section_data(
        grp_sec, parse_group_section, first_count)

    # Find first group set and pick 3 TGs to modify
    target_set = existing_sets[0]
    assert len(target_set.groups) >= 3, "Need at least 3 TGs"
    target_ids = {target_set.groups[0].group_id,
                  target_set.groups[1].group_id,
                  target_set.groups[2].group_id}

    # All TGs in PAWSOVERMAWS should be tx=False, scan=True
    for g in target_set.groups:
        if g.group_id in target_ids:
            assert g.tx is False, f"TG {g.group_id} expected tx=False"
            assert g.scan is True, f"TG {g.group_id} expected scan=True"

    # Enable TX on selected, disable scan
    for g in target_set.groups:
        if g.group_id in target_ids:
            g.tx = True
            g.scan = False

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)

    # Re-parse and verify changes persisted
    grp_sec2 = prs.get_section_by_class("CP25Group")
    set_sec2 = prs.get_section_by_class("CP25GroupSet")
    byte1_2, byte2_2 = _get_header_bytes(grp_sec2)
    set_byte1_2, set_byte2_2 = _get_header_bytes(set_sec2)
    first_count2 = _get_first_count(prs, "CP25GroupSet")
    sets2 = _parse_section_data(
        grp_sec2, parse_group_section, first_count2)

    target2 = sets2[0]
    modified_count = 0
    for g in target2.groups:
        if g.group_id in target_ids:
            assert g.tx is True, f"TG {g.group_id}: tx should be True"
            assert g.scan is False, f"TG {g.group_id}: scan should be False"
            modified_count += 1
        else:
            # Others should be unchanged
            assert g.tx is False, f"TG {g.group_id}: tx should still be False"
            assert g.scan is True, f"TG {g.group_id}: scan should still be True"

    assert modified_count == 3, f"Expected 3 modified, got {modified_count}"

    # Roundtrip check
    tmp = TESTDATA / "batch_modify_test.tmp"
    try:
        modified_bytes = prs.to_bytes()
        tmp.write_bytes(modified_bytes)
        prs3 = parse_prs(tmp)
        rebuilt = prs3.to_bytes()
        assert modified_bytes == rebuilt, "Roundtrip mismatch after batch modify"
        print(f"  PASS: Batch-modified 3 TGs, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_batch_delete_selected_tgs():
    """Batch-delete specific selected talkgroups by ID."""
    from quickprs.injector import (
        _parse_section_data, _replace_group_sections,
        _get_header_bytes, _get_first_count,
    )

    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    assert grp_sec and set_sec

    byte1, byte2 = _get_header_bytes(grp_sec)
    set_byte1, set_byte2 = _get_header_bytes(set_sec)
    first_count = _get_first_count(prs, "CP25GroupSet")
    existing_sets = _parse_section_data(
        grp_sec, parse_group_section, first_count)

    target_set = existing_sets[0]
    orig_count = len(target_set.groups)
    assert orig_count >= 5, "Need at least 5 TGs"

    # Pick 2 TGs to delete
    delete_ids = {target_set.groups[1].group_id,
                  target_set.groups[3].group_id}

    target_set.groups = [g for g in target_set.groups
                         if g.group_id not in delete_ids]

    assert len(target_set.groups) == orig_count - 2

    _replace_group_sections(prs, existing_sets, byte1, byte2,
                             set_byte1, set_byte2)

    # Re-parse and verify
    grp_sec2 = prs.get_section_by_class("CP25Group")
    set_sec2 = prs.get_section_by_class("CP25GroupSet")
    byte1_2, byte2_2 = _get_header_bytes(grp_sec2)
    set_byte1_2, set_byte2_2 = _get_header_bytes(set_sec2)
    first_count2 = _get_first_count(prs, "CP25GroupSet")
    sets2 = _parse_section_data(
        grp_sec2, parse_group_section, first_count2)

    target2 = sets2[0]
    assert len(target2.groups) == orig_count - 2
    remaining_ids = {g.group_id for g in target2.groups}
    for did in delete_ids:
        assert did not in remaining_ids, f"TG {did} should be deleted"

    # Roundtrip
    tmp = TESTDATA / "batch_delete_test.tmp"
    try:
        modified_bytes = prs.to_bytes()
        tmp.write_bytes(modified_bytes)
        prs3 = parse_prs(tmp)
        rebuilt = prs3.to_bytes()
        assert modified_bytes == rebuilt, "Roundtrip mismatch after batch delete"
        print(f"  PASS: Batch-deleted 2 TGs from {orig_count}, roundtrip OK")
    finally:
        if tmp.exists():
            tmp.unlink()


# ─── Preferred System Table Tests ──────────────────────────────────────

def test_parse_preferred_paws():
    """Parse preferred entries from PAWSOVERMAWS — 8 entries with chain."""
    fpath = TESTDATA / "PAWSOVERMAWS.PRS"
    if not fpath.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import PreferredSystemEntry
    prs = parse_prs(fpath)
    entries, iden, chain = get_preferred_entries(prs)
    assert len(entries) == 8
    assert iden == "BEE00"
    assert chain == "PSRS"

    # Verify known site IDs from PSERN network
    sysids = [e.system_id for e in entries]
    assert 933 in sysids  # entry[0]
    assert 932 in sysids  # entry[7]

    # All entries have type=3 and field1=1
    for e in entries:
        assert e.entry_type == 3
        assert e.field1 == 1

    # Sequential indices with gap
    f2_values = [e.field2 for e in entries]
    assert f2_values == [25, 26, 27, 28, 31, 32, 33, 34]


def test_parse_preferred_claude():
    """Parse preferred entries from claude test — 1 entry, no chain."""
    fpath = TESTDATA / "claude test.PRS"
    if not fpath.exists():
        pytest.skip("test file not found")
    prs = parse_prs(fpath)
    entries, iden, chain = get_preferred_entries(prs)
    assert len(entries) == 1
    assert entries[0].entry_type == 4
    assert entries[0].system_id == 546
    assert iden == "IDENT SE"
    assert chain is None


def test_add_preferred_entries():
    """Add preferred entries to claude test and verify."""
    fpath = TESTDATA / "claude test.PRS"
    if not fpath.exists():
        pytest.skip("test file not found")
    from quickprs.record_types import PreferredSystemEntry
    prs = parse_prs(fpath)

    # Get original state
    orig_entries, _, _ = get_preferred_entries(prs)
    assert len(orig_entries) == 1

    # Add 2 new entries
    new_entries = [
        PreferredSystemEntry(entry_type=3, system_id=100, field1=1),
        PreferredSystemEntry(entry_type=3, system_id=200, field1=1),
    ]
    add_preferred_entries(prs, new_entries)

    # Verify count increased
    entries, iden, chain = get_preferred_entries(prs)
    assert len(entries) == 3
    assert entries[1].system_id == 100
    assert entries[2].system_id == 200

    # Sequence indices should be auto-assigned
    assert entries[1].field2 == 35  # max was 34 + 1
    assert entries[2].field2 == 36

    # IDEN and chain preserved
    assert iden == "IDENT SE"

    # Roundtrip
    tmp = TESTDATA / "preferred_add_test.tmp"
    try:
        modified = prs.to_bytes()
        tmp.write_bytes(modified)
        prs2 = parse_prs(tmp)
        assert modified == prs2.to_bytes(), "Roundtrip failed after adding preferred entries"
        # Re-verify entries survived roundtrip
        entries2, _, _ = get_preferred_entries(prs2)
        assert len(entries2) == 3
    finally:
        if tmp.exists():
            tmp.unlink()


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_preferred_roundtrip():
    """Parse → build → compare for both test files."""
    from quickprs.record_types import parse_preferred_section, build_preferred_section
    for fpath in [TESTDATA / "claude test.PRS", TESTDATA / "PAWSOVERMAWS.PRS"]:
        if not fpath.exists():
            continue
        prs = parse_prs(fpath)
        for sec in prs.sections:
            if sec.class_name == 'CPreferredSystemTableEntry':
                original = sec.raw
                entries, iden, tail, chain, ctype = parse_preferred_section(original)
                rebuilt = build_preferred_section(entries, tail_bytes=tail)
                assert rebuilt == original, f"Roundtrip mismatch for {fpath.name}"


# ─── ValueError error path tests ─────────────────────────────────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_trunk_set_no_existing_raises():
    """add_trunk_set on a file without trunk sections should raise."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    # Remove trunk sections to simulate a file without them
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CTrunkChannel", "CTrunkSet")]
    ts = make_trunk_set("TEST", [(851.0125, 851.0125)])
    with pytest.raises(ValueError, match="No existing trunk"):
        add_trunk_set(prs, ts)


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_add_trunk_channels_missing_set_raises():
    """add_trunk_channels with a bad set name should raise."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    ch = make_trunk_channel(851.0125, 851.0125)
    with pytest.raises(ValueError, match="not found"):
        add_trunk_channels(prs, "NONEXISTENT_SET", [ch])


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_group_set_no_existing_raises():
    """add_group_set on a file without group sections should raise."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CP25Group", "CP25GroupSet")]
    gs = make_group_set("TEST", [(100, "TEST", "TEST TG")])
    with pytest.raises(ValueError, match="No existing group"):
        add_group_set(prs, gs)


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_add_talkgroups_missing_set_raises():
    """add_talkgroups with a bad set name should raise."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    tg = make_p25_group(100, "TEST", "TEST TG")
    with pytest.raises(ValueError, match="not found"):
        add_talkgroups(prs, "NONEXISTENT_SET", [tg])


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_iden_set_no_existing_raises():
    """add_iden_set on a file without IDEN sections should raise."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CDefaultIdenElem", "CIdenDataSet")]
    iset = make_iden_set("TEST", [])
    with pytest.raises(ValueError, match="No existing IDEN"):
        add_iden_set(prs, iset)


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_add_conv_set_no_existing_raises():
    """add_conv_set on a file without conv sections should raise."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CConvChannel", "CConvSet")]
    cs = make_conv_set("TEST", [{"short_name": "CH1", "tx_freq": 462.5625, "rx_freq": 462.5625, "long_name": "CHAN 1"}])
    with pytest.raises(ValueError, match="No existing conv"):
        add_conv_set(prs, cs)


# ─── Create-from-scratch tests (via add_p25_trunked_system) ─────────

@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_create_trunk_from_scratch():
    """Injecting a system with trunk set into a file without trunk sections
    should create them from scratch via _safe_add_trunk_set."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    # Remove trunk sections
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CTrunkChannel", "CTrunkSet")]
    assert prs.get_section_by_class("CTrunkChannel") is None

    ts = make_trunk_set("NEW", [(851.0125, 851.0125), (851.5125, 851.5125)])
    config = P25TrkSystemConfig(
        system_name="NEW",
        long_name="NEW SYSTEM",
        trunk_set_name="NEW",
        group_set_name="NEW",
        wan_name="NEW",
    )
    add_p25_trunked_system(prs, config, trunk_set=ts)

    # Should now have trunk sections
    assert prs.get_section_by_class("CTrunkChannel") is not None
    assert prs.get_section_by_class("CTrunkSet") is not None


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_create_group_from_scratch():
    """Injecting a system with group set into a file without group sections
    should create them from scratch."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CP25Group", "CP25GroupSet")]
    assert prs.get_section_by_class("CP25Group") is None

    gs = make_group_set("NEW", [(100, "TEST", "TEST TG"),
                                 (200, "TEST2", "TEST TG 2")])
    config = P25TrkSystemConfig(
        system_name="NEW",
        long_name="NEW SYSTEM",
        trunk_set_name="NEW",
        group_set_name="NEW",
        wan_name="NEW",
    )
    add_p25_trunked_system(prs, config, group_set=gs)

    assert prs.get_section_by_class("CP25Group") is not None
    assert prs.get_section_by_class("CP25GroupSet") is not None


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_create_iden_from_scratch():
    """Injecting a system with IDEN set into a file without IDEN sections
    should create them from scratch."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    prs.sections = [s for s in prs.sections
                    if s.class_name not in ("CDefaultIdenElem", "CIdenDataSet")]
    assert prs.get_section_by_class("CDefaultIdenElem") is None

    iset = make_iden_set("NEW", [
        {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
         "bandwidth_hz": 12500, "tx_offset_mhz": -45.0, "iden_type": 0},
    ])
    config = P25TrkSystemConfig(
        system_name="NEW",
        long_name="NEW SYSTEM",
        trunk_set_name="NEW",
        group_set_name="NEW",
        wan_name="NEW",
        iden_set_name="NEW",
    )
    add_p25_trunked_system(prs, config, iden_set=iset)

    assert prs.get_section_by_class("CDefaultIdenElem") is not None
    assert prs.get_section_by_class("CIdenDataSet") is not None


# ─── WAN Auto-Update Tests ──────────────────────────────────────────────

def test_wan_auto_update_blank_prs():
    """Add 3 P25 systems to blank PRS, verify WAN sections have 3 entries."""
    from quickprs.builder import create_blank_prs
    from quickprs.record_types import (
        parse_wan_section, parse_wan_opts_section,
    )

    prs = create_blank_prs()

    # Initially WAN should be empty (0 entries)
    opts_sec = prs.get_section_by_class("CP25tWanOpts")
    assert parse_wan_opts_section(opts_sec.raw) == 0

    # Add 3 systems with different WACNs/SysIDs
    for i, (name, wacn, sysid) in enumerate([
        ("SYS_A", 0xBEE00, 939),
        ("SYS_B", 0x58544, 15),
        ("SYS_C", 0x92738, 555),
    ]):
        config = P25TrkSystemConfig(
            system_name=name,
            long_name=f"{name} SYSTEM",
            trunk_set_name=name,
            group_set_name=name,
            wan_name=name,
            wacn=wacn,
            system_id=sysid,
        )
        trunk_set = make_trunk_set(name, [(806.0 + i, 851.0 + i)])
        group_set = make_group_set(name, [(100 + i, f"TG{i}", f"TG {i}")])
        add_p25_trunked_system(prs, config,
                                trunk_set=trunk_set,
                                group_set=group_set)

    # Verify WAN sections
    wan_sec = prs.get_section_by_class("CP25TrkWan")
    entries = parse_wan_section(wan_sec.raw)
    assert len(entries) == 3, f"Expected 3 WAN entries, got {len(entries)}"

    opts_sec = prs.get_section_by_class("CP25tWanOpts")
    assert parse_wan_opts_section(opts_sec.raw) == 3

    # Verify entry values
    assert entries[0].wan_name.strip() == "SYS_A"
    assert entries[0].wacn == 0xBEE00
    assert entries[0].system_id == 939

    assert entries[1].wan_name.strip() == "SYS_B"
    assert entries[1].wacn == 0x58544
    assert entries[1].system_id == 15

    assert entries[2].wan_name.strip() == "SYS_C"
    assert entries[2].wacn == 0x92738
    assert entries[2].system_id == 555


def test_wan_no_duplicate():
    """Adding system with same wan_name should NOT create duplicate entry."""
    from quickprs.builder import create_blank_prs
    from quickprs.record_types import (
        parse_wan_section, parse_wan_opts_section,
    )

    prs = create_blank_prs()

    # Add first system
    config1 = P25TrkSystemConfig(
        system_name="DUPSYS",
        long_name="DUP SYSTEM 1",
        trunk_set_name="DUPSYS",
        group_set_name="DUPSYS",
        wan_name="DUPSYS",
        wacn=0xAAAA,
        system_id=100,
    )
    trunk_set1 = make_trunk_set("DUPSYS", [(806.0, 851.0)])
    group_set1 = make_group_set("DUPSYS", [(100, "TG1", "TG 1")])
    add_p25_trunked_system(prs, config1,
                            trunk_set=trunk_set1,
                            group_set=group_set1)

    # Add second system with same wan_name but different WACN/SysID
    config2 = P25TrkSystemConfig(
        system_name="DUPSYS",
        long_name="DUP SYSTEM 2",
        trunk_set_name="DUPSYS",
        group_set_name="DUPSYS",
        wan_name="DUPSYS",
        wacn=0xBBBB,
        system_id=200,
    )
    add_p25_trunked_system(prs, config2)

    # Should still be 1 WAN entry (not 2)
    wan_sec = prs.get_section_by_class("CP25TrkWan")
    entries = parse_wan_section(wan_sec.raw)
    assert len(entries) == 1, f"Expected 1 WAN entry (no dup), got {len(entries)}"

    opts_sec = prs.get_section_by_class("CP25tWanOpts")
    assert parse_wan_opts_section(opts_sec.raw) == 1


def test_wan_update_roundtrip():
    """Full roundtrip after WAN auto-update on blank PRS."""
    from quickprs.builder import create_blank_prs

    prs = create_blank_prs()

    config = P25TrkSystemConfig(
        system_name="RNDTRP",
        long_name="ROUNDTRIP SYS",
        trunk_set_name="RNDTRP",
        group_set_name="RNDTRP",
        wan_name="RNDTRP",
        wacn=0x12345,
        system_id=678,
    )
    trunk_set = make_trunk_set("RNDTRP", [(806.0, 851.0)])
    group_set = make_group_set("RNDTRP", [(100, "TG1", "TG 1")])
    add_p25_trunked_system(prs, config,
                            trunk_set=trunk_set,
                            group_set=group_set)

    # Double roundtrip
    raw1 = prs.to_bytes()
    from quickprs.prs_parser import parse_prs_bytes
    prs2 = parse_prs_bytes(raw1)
    raw2 = prs2.to_bytes()
    assert raw1 == raw2, "Double roundtrip mismatch after WAN update"


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_wan_update_existing_file():
    """Add system to PAWSOVERMAWS, verify WAN count increases from 9 to 10."""
    from quickprs.record_types import (
        parse_wan_section, parse_wan_opts_section,
    )

    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # PAWSOVERMAWS has 9 WAN entries
    wan_sec = prs.get_section_by_class("CP25TrkWan")
    before = parse_wan_section(wan_sec.raw)
    assert len(before) == 9

    config = P25TrkSystemConfig(
        system_name="NEWWAN",
        long_name="NEW WAN SYSTEM",
        trunk_set_name="NEWWAN",
        group_set_name="NEWWAN",
        wan_name="NEWWAN",
        wacn=0xDEAD,
        system_id=999,
    )
    trunk_set = make_trunk_set("NEWWAN", [(806.5, 851.5)])
    group_set = make_group_set("NEWWAN", [(500, "NEW TG", "NEW TG")])
    add_p25_trunked_system(prs, config,
                            trunk_set=trunk_set,
                            group_set=group_set)

    wan_sec = prs.get_section_by_class("CP25TrkWan")
    after = parse_wan_section(wan_sec.raw)
    assert len(after) == 10, f"Expected 10 WAN entries, got {len(after)}"

    opts_sec = prs.get_section_by_class("CP25tWanOpts")
    assert parse_wan_opts_section(opts_sec.raw) == 10

    # Verify the new entry is at the end
    assert after[9].wan_name.strip() == "NEWWAN"
    assert after[9].wacn == 0xDEAD
    assert after[9].system_id == 999

    # Verify original entries are intact
    assert after[0].wan_name.strip() == "PSERN"
    assert after[0].wacn == 0xBEE00


def main():
    print("\n=== Injection Tests ===\n")

    tests = [
        ("Add talkgroups", test_add_talkgroups),
        ("Add group set", test_add_group_set),
        ("Add trunk channels", test_add_trunk_channels),
        ("Add trunk set", test_add_trunk_set),
        ("Double roundtrip", test_injection_double_roundtrip),
        ("Validation clean", test_validation_clean),
        ("Validation 127 limit", test_validation_127_limit),
        ("Validation name lengths", test_validation_name_lengths),
        ("System name extraction", test_system_name_extraction),
        ("System name extraction (PAWSOVERMAWS)", test_system_name_extraction_pawsovermaws),
        ("System config detection", test_system_config_detection),
        ("P25 system config build", test_p25_trunked_system_config_build),
        ("Add P25 trunked system", test_add_p25_trunked_system),
        ("Add system to PAWSOVERMAWS", test_add_system_to_pawsovermaws),
        ("Conv system config build", test_conv_system_config_build),
        ("P25 conv system config build", test_p25_conv_system_config_build),
        ("Add conv system", test_add_conv_system),
        ("Add P25 conv system", test_add_p25_conv_system),
        ("Add conv set to existing", test_add_conv_set_to_existing),
        ("Remove system config", test_remove_system_config),
        ("Remove system by class", test_remove_system_by_class),
        ("Batch modify selected TGs", test_batch_modify_selected_tgs),
        ("Batch delete selected TGs", test_batch_delete_selected_tgs),
        ("Parse preferred entries PAWSOVERMAWS", test_parse_preferred_paws),
        ("Parse preferred entries claude test", test_parse_preferred_claude),
        ("Add preferred entries", test_add_preferred_entries),
        ("Preferred section roundtrip", test_preferred_roundtrip),
        ("WAN auto-update blank PRS", test_wan_auto_update_blank_prs),
        ("WAN no duplicate", test_wan_no_duplicate),
        ("WAN update roundtrip", test_wan_update_roundtrip),
        ("WAN update existing file", test_wan_update_existing_file),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} - {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All injection tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
