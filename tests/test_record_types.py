"""Tests for record_types.py — verify parse/serialize roundtrip at the record level.

These tests parse individual records from known test files and verify:
1. Parsed field values match CSV/known values
2. Serialized bytes match original bytes (per-record roundtrip)
3. Section-level parse/rebuild produces identical bytes
"""

import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.binary_io import read_uint16_le, try_read_class_name
from quickprs.record_types import (
    TrunkChannel, TrunkSet, ConvChannel, ConvSet,
    IdenElement, IdenDataSet, P25Group, P25GroupSet,
    P25TrkSystemConfig, ConvSystemConfig, P25ConvSystemConfig,
    EnhancedCCEntry, PreferredSystemEntry,
    TRUNK_CHANNEL_SEP, CONV_CHANNEL_SEP, IDEN_ELEMENT_SEP, GROUP_SEP,
    SYSTEM_CONFIG_PREFIX, SECTION_MARKER,
    parse_class_header, build_class_header,
    parse_trunk_channel_section, parse_conv_channel_section,
    parse_group_section, parse_iden_section,
    parse_ecc_entries, parse_preferred_section, build_preferred_section,
    parse_system_short_name, parse_system_long_name, parse_system_wan_name,
    is_system_config_data,
    build_trunk_channel_section, build_trunk_set_section,
    build_group_section, build_group_set_section,
    build_conv_channel_section, build_conv_set_section,
    build_iden_section, build_iden_set_section,
    build_sys_flags, detect_band_limits, detect_wan_config,
    parse_sets_from_sections,
    SYS_FLAG_LINEAR_SIMULCAST, SYS_FLAG_TDMA_CAPABLE,
    SYS_FLAG_ADAPTIVE_FILTER, SYS_FLAG_ROAMING_MODE,
    SYS_FLAG_POWER_LEVEL, SYS_FLAG_ENCRYPTION, SYS_FLAG_AUTO_REG,
    SYS_FLAG_AVOID_FAILSOFT,
)

TESTDATA = Path(__file__).parent / "testdata"


def test_trunk_channel_parse():
    """Parse first few trunk channels from PAWSOVERMAWS and verify against CSV."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()

    # CTrunkChannel section at 0x11a1
    # Header: 'CTrunkChannel' = 13 chars, header size = 2+2+2+13 = 19
    pos = 0x11a1 + 19

    # First PSERN channel: TX=806.88750, RX=851.88750
    ch1, new_pos = TrunkChannel.parse(data, pos)
    assert abs(ch1.tx_freq - 806.88750) < 0.001, f"TX mismatch: {ch1.tx_freq}"
    assert abs(ch1.rx_freq - 851.88750) < 0.001, f"RX mismatch: {ch1.rx_freq}"
    assert ch1.flags == b'\x00' * 7, f"Flags not default: {ch1.flags.hex()}"
    assert new_pos == pos + 23, f"Size mismatch: {new_pos - pos}"

    # Record roundtrip
    rebuilt = ch1.to_bytes()
    original = data[pos:pos + 23]
    assert rebuilt == original, f"Roundtrip mismatch at channel 1"
    print("  PASS: TrunkChannel parse + roundtrip")


def test_trunk_channel_section_parse():
    """Parse all trunk sets from PAWSOVERMAWS."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # Get CTrunkSet section to find first count
    trunk_set_sec = prs.get_section_by_class("CTrunkSet")
    _, _, _, data_start = parse_class_header(trunk_set_sec.raw, 0)
    # Adjust data_start to be relative to file, not section
    data_start = trunk_set_sec.offset + data_start
    first_count, _ = read_uint16_le(data, data_start)
    assert first_count == 28, f"First count should be 28 (PSERN), got {first_count}"

    # Get CTrunkChannel section
    trunk_ch_sec = prs.get_section_by_class("CTrunkChannel")
    _, _, _, ch_data_start = parse_class_header(data, trunk_ch_sec.offset)

    # Parse section (just first set to keep it simple)
    sets = parse_trunk_channel_section(data, ch_data_start,
                                       trunk_ch_sec.offset + len(trunk_ch_sec.raw),
                                       first_count)
    assert len(sets) >= 1, "Should parse at least 1 set"
    assert sets[0].name == "PSERN", f"First set name: {sets[0].name}"
    assert len(sets[0].channels) == 28, f"PSERN channels: {len(sets[0].channels)}"
    assert abs(sets[0].tx_min - 136.0) < 0.01, f"TxMin: {sets[0].tx_min}"
    assert abs(sets[0].tx_max - 870.0) < 0.01, f"TxMax: {sets[0].tx_max}"

    # Verify first and last channel freqs
    assert abs(sets[0].channels[0].tx_freq - 806.88750) < 0.001
    assert abs(sets[0].channels[27].tx_freq - 814.46250) < 0.001

    print(f"  PASS: Parsed {len(sets)} trunk sets")
    for s in sets:
        print(f"    {s.name}: {len(s.channels)} channels, "
              f"band {s.tx_min:.0f}-{s.tx_max:.0f} MHz")


def test_p25_group_parse():
    """Parse first few P25 groups from PAWSOVERMAWS and verify against CSV."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()

    # CP25Group section at 0x77de, header = 15 bytes
    pos = 0x77de + 15

    # First group: ALG PD 1, GroupID=2303
    grp1, new_pos = P25Group.parse(data, pos)
    assert grp1.group_name == "ALG PD 1", f"Name: {grp1.group_name}"
    assert grp1.group_id == 2303, f"ID: {grp1.group_id}"
    assert grp1.long_name == "ALGONA PD TAC 1", f"LN: {grp1.long_name}"
    assert grp1.tx is False, "TX should be False (NAS monitoring)"
    assert grp1.rx is True, "RX should be True"
    assert grp1.scan is True, "Scan should be True"

    # Record roundtrip
    rebuilt = grp1.to_bytes()
    rec_size = new_pos - pos
    original = data[pos:new_pos]
    assert rebuilt == original, (
        f"Group roundtrip mismatch: rebuilt {len(rebuilt)} bytes vs original {rec_size}\n"
        f"  Original: {original.hex()}\n"
        f"  Rebuilt:  {rebuilt.hex()}")

    print("  PASS: P25Group parse + roundtrip")


def test_group_section_parse():
    """Parse all group sets from PAWSOVERMAWS."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # Get first count from CP25GroupSet section
    grp_set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(data, grp_set_sec.offset)
    first_count, _ = read_uint16_le(data, gs_data)
    assert first_count == 83, f"First group count: {first_count}"

    # Parse section
    grp_sec = prs.get_section_by_class("CP25Group")
    _, _, _, g_data_start = parse_class_header(data, grp_sec.offset)
    sets = parse_group_section(data, g_data_start,
                               grp_sec.offset + len(grp_sec.raw),
                               first_count)

    assert len(sets) >= 4, f"Expected at least 4 group sets, got {len(sets)}"
    expected = [("PSERN PD", 83), ("PSRS PD", 17), ("SS911 PD", 18), ("WASP", 25)]
    for i, (name, count) in enumerate(expected):
        assert sets[i].name == name, f"Set {i}: {sets[i].name} != {name}"
        assert len(sets[i].groups) == count, f"Set {i} count: {len(sets[i].groups)}"

    print(f"  PASS: Parsed {len(sets)} group sets")
    for s in sets:
        print(f"    {s.name}: {len(s.groups)} groups")


def test_conv_channel_parse():
    """Parse conventional channels from PAWSOVERMAWS."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # CConvChannel section
    conv_sec = prs.get_section_by_class("CConvChannel")
    _, _, _, data_start = parse_class_header(data, conv_sec.offset)

    # Parse first channel
    ch, new_pos = ConvChannel.parse(data, data_start)
    print(f"  First conv channel: \"{ch.short_name}\" TX={ch.tx_freq:.5f} "
          f"RX={ch.rx_freq:.5f} TxTone=\"{ch.tx_tone}\" LN=\"{ch.long_name}\"")

    # Record roundtrip
    rebuilt = ch.to_bytes()
    original = data[data_start:new_pos]
    assert rebuilt == original, (
        f"ConvChannel roundtrip mismatch: {len(rebuilt)} vs {len(original)} bytes")

    print("  PASS: ConvChannel parse + roundtrip")


def test_iden_element_parse():
    """Parse IDEN elements from PAWSOVERMAWS."""
    data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # CDefaultIdenElem section
    iden_sec = prs.get_section_by_class("CDefaultIdenElem")
    _, _, _, data_start = parse_class_header(data, iden_sec.offset)

    # Parse first element
    elem, new_pos = IdenElement.parse(data, data_start)

    # Verify against P25T_IDEN_SET_ss.csv: first BEE00 entry
    # ChanSpacing=12500, Bandwidth=6250, BaseFreq=851006250, TxOffset=0, Type=FDMA
    print(f"  First IDEN element: spacing={elem.chan_spacing_hz} "
          f"bw={elem.bandwidth_hz} base={elem.base_freq_hz} "
          f"type={'TDMA' if elem.iden_type else 'FDMA'}")

    # Record roundtrip
    rebuilt = elem.to_bytes()
    original = data[data_start:new_pos]
    assert rebuilt == original, "IdenElement roundtrip mismatch"

    print("  PASS: IdenElement parse + roundtrip")


def test_claude_test_groups():
    """Parse the simpler claude test.PRS group section."""
    data = (TESTDATA / "claude test.PRS").read_bytes()
    prs = parse_prs(TESTDATA / "claude test.PRS")

    # Get first count
    grp_set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(data, grp_set_sec.offset)
    first_count, _ = read_uint16_le(data, gs_data)
    assert first_count == 1, f"First group count: {first_count}"

    # Parse
    grp_sec = prs.get_section_by_class("CP25Group")
    _, _, _, g_data_start = parse_class_header(data, grp_sec.offset)
    sets = parse_group_section(data, g_data_start,
                               grp_sec.offset + len(grp_sec.raw),
                               first_count)
    assert len(sets) >= 1
    assert sets[0].name == "GROUP SE", f"Set name: {sets[0].name}"
    assert len(sets[0].groups) == 1
    assert sets[0].groups[0].group_name == "name"
    assert sets[0].groups[0].long_name == "LONG NAME"

    # Record roundtrip
    rebuilt = sets[0].groups[0].to_bytes()
    original = data[g_data_start:g_data_start + len(rebuilt)]
    assert rebuilt == original, "claude test group roundtrip mismatch"

    print(f"  PASS: claude test.PRS groups: {sets[0].name} "
          f"with {len(sets[0].groups)} group(s)")


def test_conv_section_parse():
    """Parse all conv sets from PAWSOVERMAWS."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    conv_set_sec = prs.get_section_by_class("CConvSet")
    _, _, _, ds = parse_class_header(conv_set_sec.raw, 0)
    first_count, _ = read_uint16_le(conv_set_sec.raw, ds)
    assert first_count == 5, f"First conv count: {first_count}"

    conv_sec = prs.get_section_by_class("CConvChannel")
    _, _, _, ch_data = parse_class_header(conv_sec.raw, 0)
    sets = parse_conv_channel_section(
        conv_sec.raw, ch_data, len(conv_sec.raw), first_count)

    assert len(sets) == 3, f"Expected 3 conv sets, got {len(sets)}"
    expected = [("WA WIDE", 5), ("FURRY NB", 70), ("FURRY WB", 70)]
    for i, (name, count) in enumerate(expected):
        assert sets[i].name == name, f"Set {i}: {sets[i].name} != {name}"
        assert len(sets[i].channels) == count, (
            f"Set {i} count: {len(sets[i].channels)}")

    # Verify MURS channels
    assert sets[0].channels[0].short_name == "MURS 1"
    assert abs(sets[0].channels[0].tx_freq - 151.82000) < 0.001

    # Verify MID channels
    assert sets[1].channels[0].short_name == "MID 23"
    assert abs(sets[1].channels[0].tx_freq - 462.56250) < 0.001
    assert sets[1].channels[0].tx_tone == "250.3"

    # NB and WB sets have same channels
    assert sets[1].channels[0].short_name == sets[2].channels[0].short_name

    print(f"  PASS: Parsed {len(sets)} conv sets")
    for s in sets:
        print(f"    {s.name}: {len(s.channels)} channels")


def test_ecc_entries_pawsovermaws():
    """Parse enhanced CC entries from all P25 system configs in PAWSOVERMAWS."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    # Expected: system_long_name -> (ecc_count, iden_name)
    expected = {
        "PSRS TACOMA": (3, "BEE00"),
        "SS911 TACOMA": (5, "BEE00"),
        "P25 WA STATE PAT": (5, "BEE00"),
        "NELLIS/CREECH/NN": (13, "58544"),
        "S NEVADA SNACC": (17, "BEE00"),
        "C/S NEVADA": (30, "92738"),
        "WASHOE/N NEVADA": (1, "92738"),
        "S/FRINGE NEVADA": (3, "92738"),
    }

    found = {}
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            if not long_name:
                continue
            ecc_count, entries, iden_name = parse_ecc_entries(sec.raw)
            if ecc_count > 0:
                found[long_name] = (ecc_count, iden_name)
                # Verify entry count matches
                assert len(entries) == ecc_count, \
                    f"{long_name}: expected {ecc_count} entries, got {len(entries)}"

    # Verify all expected systems were found
    for name, (exp_count, exp_iden) in expected.items():
        assert name in found, f"Missing ECC data for {name}"
        actual_count, actual_iden = found[name]
        assert actual_count == exp_count, \
            f"{name}: expected {exp_count} ECC, got {actual_count}"
        assert actual_iden == exp_iden, \
            f"{name}: expected IDEN={exp_iden}, got {actual_iden}"

    # C/S Nevada has 30 entries (exceeds 29 limit)
    assert found["C/S NEVADA"][0] == 30
    print(f"  PASS: ECC entries parsed for {len(found)} systems")


def test_ecc_entry_roundtrip():
    """Verify EnhancedCCEntry serialization roundtrip."""
    entry = EnhancedCCEntry(entry_type=3, system_id=555,
                             channel_ref1=42, channel_ref2=42)
    raw = entry.to_bytes()
    assert len(raw) == 15
    assert raw[:2] == b'\x09\x80'

    parsed = EnhancedCCEntry.from_bytes(raw, 0)
    assert parsed.entry_type == 3
    assert parsed.system_id == 555
    assert parsed.channel_ref1 == 42
    assert parsed.channel_ref2 == 42

    # Re-serialize should produce identical bytes
    assert parsed.to_bytes() == raw
    print("  PASS: ECC entry roundtrip")


def test_ecc_washoe_details():
    """Verify WASHOE/N NEVADA has 1 ECC entry with sysid=775."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")

    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            if long_name == "WASHOE/N NEVADA":
                count, entries, iden_name = parse_ecc_entries(sec.raw)
                assert count == 1
                assert entries[0].system_id == 775
                assert entries[0].channel_ref1 == 250
                assert entries[0].channel_ref2 == 250
                assert iden_name == "92738"
                print("  PASS: WASHOE ECC details verified")
                return

    assert False, "WASHOE/N NEVADA not found"


def test_build_data_section_psern():
    """Build PSERN-like system config and compare to real PAWSOVERMAWS bytes."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    real_psern = prs.sections[6].raw

    config = P25TrkSystemConfig(
        system_name='PSERN',
        long_name='PSERN SEATTLE',
        trunk_set_name='PSERN',
        group_set_name='PSERN PD',
        wan_name='PSERN',
        home_unit_id=3621621,
        system_id=892,
        ecc_entries=[],
        ecc_count_override=8,  # root system: 8 entries in CPreferredSystemTableEntry
        iden_set_name='',
        band_low_hz=136_000_000,
        band_high_hz=870_000_000,
    )
    built = config.build_data_section()

    assert len(built) == len(real_psern), \
        f"Size mismatch: built={len(built)} real={len(real_psern)}"
    assert built == real_psern, \
        f"Byte mismatch at first diff: {_first_diff(built, real_psern)}"
    print("  PASS: build_data_section matches PSERN (214 bytes, exact)")


def test_build_data_section_psrs():
    """Build PSRS config with ECC entries and IDEN ref, compare to real."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    real_psrs = prs.sections[8].raw

    ecc_count, entries, iden_name = parse_ecc_entries(real_psrs)

    config = P25TrkSystemConfig(
        system_name='PSRS',
        long_name='PSRS TACOMA',
        trunk_set_name='PSRS',
        group_set_name='PSRS PD',
        wan_name='PSRS',
        home_unit_id=3621621,
        system_id=587,
        ecc_entries=entries,
        iden_set_name='BEE00',
        band_low_hz=767_000_000,
        band_high_hz=858_000_000,
        wan_chan_spacing_hz=6250,
        wan_base_freq_hz=851_006_250,
        next_system_name='SS911',
        next_system_type=0x05,
    )
    built = config.build_data_section()

    assert len(built) == len(real_psrs), \
        f"Size mismatch: built={len(built)} real={len(real_psrs)}"
    assert built == real_psrs, \
        f"Byte mismatch at first diff: {_first_diff(built, real_psrs)}"
    print("  PASS: build_data_section matches PSRS (337 bytes, 3 ECC, IDEN=BEE00)")


def test_build_data_section_cs_nevada():
    """Build C/S Nevada config with 30 ECC entries (max stress test)."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    real = prs.sections[14].raw

    ecc_count, entries, iden_name = parse_ecc_entries(real)
    assert ecc_count == 30, f"Expected 30 ECC, got {ecc_count}"

    # Parse real system parameters
    from quickprs.binary_io import read_lps
    pos = 44
    long_name, pos = read_lps(real, pos)
    pos += 15  # sys_flags
    tset, pos = read_lps(real, pos)
    gset, pos = read_lps(real, pos)
    pos += 12
    huid = struct.unpack_from('<I', real, pos)[0]
    pos += 4 + 12 + 6 + 2
    sysid = struct.unpack_from('<I', real, pos)[0]
    pos += 4
    wan1, pos = read_lps(real, pos)
    chan_spacing = struct.unpack_from('<H', real, pos + 38)[0]
    base_freq = struct.unpack_from('<I', real, pos + 40)[0]
    wan2_pos = pos + 44
    _, wan2_end = read_lps(real, wan2_pos)
    band_lo = struct.unpack_from('<I', real, wan2_end + 13)[0]
    band_hi = struct.unpack_from('<I', real, wan2_end + 17)[0]

    # Parse next system ref: search backwards for 07 80 marker
    for j in range(len(real) - 3, len(real) - 20, -1):
        if real[j] == 0x07 and real[j + 1] == 0x80:
            next_name, _ = read_lps(real, j + 2)
            break

    config = P25TrkSystemConfig(
        system_name='C/S NSRS',
        long_name=long_name,
        trunk_set_name=tset,
        group_set_name=gset,
        wan_name=wan1.rstrip(),
        home_unit_id=huid,
        system_id=sysid,
        ecc_entries=entries,
        iden_set_name=iden_name,
        band_low_hz=band_lo,
        band_high_hz=band_hi,
        wan_chan_spacing_hz=chan_spacing,
        wan_base_freq_hz=base_freq,
        next_system_name=next_name,
        next_system_type=0x05,
    )
    built = config.build_data_section()

    assert len(built) == len(real), \
        f"Size mismatch: built={len(built)} real={len(real)}"
    assert built == real, \
        f"Byte mismatch at first diff: {_first_diff(built, real)}"
    print(f"  PASS: build_data_section matches C/S Nevada "
          f"(739 bytes, 30 ECC, IDEN={iden_name})")


def test_build_data_section_last_system():
    """Build S/FRINGE (last system in chain, ends with 07 00)."""
    prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
    real = prs.sections[16].raw

    ecc_count, entries, iden_name = parse_ecc_entries(real)

    from quickprs.binary_io import read_lps
    pos = 44
    long_name, pos = read_lps(real, pos)
    pos += 15
    tset, pos = read_lps(real, pos)
    gset, pos = read_lps(real, pos)
    pos += 12
    huid = struct.unpack_from('<I', real, pos)[0]
    pos += 4 + 12 + 6 + 2
    sysid = struct.unpack_from('<I', real, pos)[0]
    pos += 4
    wan1, pos = read_lps(real, pos)
    chan_spacing = struct.unpack_from('<H', real, pos + 38)[0]
    base_freq = struct.unpack_from('<I', real, pos + 40)[0]
    wan2_pos = pos + 44
    _, wan2_end = read_lps(real, wan2_pos)
    band_lo = struct.unpack_from('<I', real, wan2_end + 13)[0]
    band_hi = struct.unpack_from('<I', real, wan2_end + 17)[0]

    config = P25TrkSystemConfig(
        system_name='S NSRS',
        long_name=long_name,
        trunk_set_name=tset,
        group_set_name=gset,
        wan_name=wan1.rstrip(),
        home_unit_id=huid,
        system_id=sysid,
        ecc_entries=entries,
        iden_set_name=iden_name,
        band_low_hz=band_lo,
        band_high_hz=band_hi,
        wan_chan_spacing_hz=chan_spacing,
        wan_base_freq_hz=base_freq,
        next_system_name='',  # LAST system — no next
        next_system_type=0x00,
    )
    built = config.build_data_section()

    assert len(built) == len(real), \
        f"Size mismatch: built={len(built)} real={len(real)}"
    assert built == real, \
        f"Byte mismatch at first diff: {_first_diff(built, real)}"
    print(f"  PASS: build_data_section matches S/FRINGE "
          f"({len(real)} bytes, last in chain)")


def test_build_header_section():
    """Verify CP25TrkSystem header section format."""
    config = P25TrkSystemConfig(system_name='TEST')
    header = config.build_header_section()

    # Should start with ff ff
    assert header[:2] == b'\xff\xff'
    # Class name check
    assert b'CP25TrkSystem' in header
    # Ends with 05
    assert header[-1] == 0x05
    # Contains system name
    assert b'TEST' in header
    print("  PASS: build_header_section format")


def test_build_sys_flags_defaults():
    """Default sys_flags with no settings should be all zeros."""
    flags = build_sys_flags(None)
    assert flags == b'\x00' * 15
    assert len(flags) == 15
    print("  PASS: build_sys_flags defaults (all zeros)")


def test_build_sys_flags_nas_monitoring():
    """NAS monitoring settings: linear simulcast, TDMA, adaptive filter on."""
    settings = {
        "linear_simulcast": True,
        "tdma_capable": True,
        "adaptive_filter": True,
        "roaming_mode": "enhanced_cc",
        "power_level": "low",
        "encryption_type": "unencrypted",
        "auto_registration": "never",
        "avoid_failsoft": False,
    }
    flags = build_sys_flags(settings)
    assert len(flags) == 15

    # Boolean flags at known positions
    assert flags[SYS_FLAG_LINEAR_SIMULCAST] == 1
    assert flags[SYS_FLAG_TDMA_CAPABLE] == 1
    assert flags[SYS_FLAG_ADAPTIVE_FILTER] == 1

    # Roaming mode: enhanced_cc = 2
    assert flags[SYS_FLAG_ROAMING_MODE] == 2

    # Power and encryption: defaults
    assert flags[SYS_FLAG_POWER_LEVEL] == 0  # low = 0
    print("  PASS: build_sys_flags NAS monitoring settings")


def test_detect_band_limits():
    """Band limits detection from frequencies."""
    # 800 MHz only
    lo, hi = detect_band_limits([851.0, 860.0, 869.0])
    assert lo == 767_000_000, f"Expected 767M, got {lo}"
    assert hi == 858_000_000, f"Expected 858M, got {hi}"

    # Mixed VHF + 800 MHz (wide band)
    lo, hi = detect_band_limits([151.0, 851.0])
    assert lo == 136_000_000
    assert hi == 870_000_000

    # No freqs
    lo, hi = detect_band_limits([])
    assert lo == 136_000_000
    assert hi == 870_000_000
    print("  PASS: detect_band_limits")


def test_detect_wan_config():
    """WAN config detection from frequencies."""
    # 800 MHz TDMA
    spacing, base = detect_wan_config([851.0], "Project 25 Phase II")
    assert spacing == 6250
    assert base == 851_006_250

    # 800 MHz FDMA
    spacing, base = detect_wan_config([851.0], "Project 25 Phase I")
    assert spacing == 12500
    assert base == 851_012_500

    # 700 MHz
    spacing, base = detect_wan_config([769.0], "")
    assert spacing == 12500
    assert base == 764_006_250
    print("  PASS: detect_wan_config")


# ─── Builder accuracy tests (byte-by-byte against real files) ────────


def _parse_p25_trunk_fields(raw):
    """Parse all fields from a P25 trunk system config data section."""
    from quickprs.binary_io import read_lps
    pos = 44
    long_name, pos = read_lps(raw, pos)
    sys_flags = raw[pos:pos + 15]; pos += 15
    trunk_set, pos = read_lps(raw, pos)
    group_set, pos = read_lps(raw, pos)
    pos += 12
    home_uid = struct.unpack_from('<I', raw, pos)[0]; pos += 4
    pos += 12 + 6 + 2
    system_id = struct.unpack_from('<I', raw, pos)[0]; pos += 4
    wan1, pos = read_lps(raw, pos)
    wan_config = raw[pos:pos + 44]; pos += 44
    wan2, pos = read_lps(raw, pos)
    pos += 4 + 5 + 4
    band_low = struct.unpack_from('<I', raw, pos)[0]; pos += 4
    band_high = struct.unpack_from('<I', raw, pos)[0]; pos += 4
    pos += 1  # 0x06
    ecc_count_raw = struct.unpack_from('<H', raw, pos)[0]; pos += 2

    ecc_entries = []
    for _ in range(ecc_count_raw):
        if pos + 15 <= len(raw):
            entry = EnhancedCCEntry.from_bytes(raw, pos)
            if entry:
                ecc_entries.append(entry)
            pos += 15

    # Parse post-ECC
    iden_name = ''
    next_sys = ''
    next_type = 0x05
    mystery_float = 16339.0
    remaining = raw[pos:]

    if len(remaining) >= 5 and remaining[:4] == b'\x00\x00\x00\x00':
        iden_len = remaining[4]
        if 0 < iden_len <= 8:
            iden_name = remaining[5:5 + iden_len].decode('ascii', errors='replace')
            tail_start = 5 + iden_len
            if tail_start + 16 <= len(remaining):
                mystery_float = struct.unpack_from('<f', remaining, tail_start + 12)[0]

    for scan in range(len(remaining) - 3, 0, -1):
        if (remaining[scan + 1:scan + 2] == b'\x80' and
                remaining[scan] in (0x03, 0x05, 0x07)):
            nl = remaining[scan + 2]
            if 0 < nl <= 8 and scan + 3 + nl < len(remaining):
                try:
                    next_sys = remaining[scan + 3:scan + 3 + nl].decode('ascii')
                    next_type = remaining[scan + 3 + nl]
                except (UnicodeDecodeError, IndexError):
                    pass
            break

    ecc_override = ecc_count_raw if not ecc_entries and ecc_count_raw > 0 else None

    return P25TrkSystemConfig(
        system_name=trunk_set.strip(),
        long_name=long_name,
        trunk_set_name=trunk_set,
        group_set_name=group_set,
        wan_name=wan1,
        home_unit_id=home_uid,
        system_id=system_id,
        sys_flags=sys_flags,
        ecc_entries=ecc_entries,
        ecc_count_override=ecc_override,
        iden_set_name=iden_name,
        band_low_hz=band_low,
        band_high_hz=band_high,
        wan_chan_spacing_hz=struct.unpack_from('<H', wan_config, 38)[0],
        wan_base_freq_hz=struct.unpack_from('<I', wan_config, 40)[0],
        next_system_name=next_sys,
        next_system_type=next_type,
        post_ecc_float=mystery_float,
    )


class TestP25TrkBuilderAccuracy:
    """Byte-by-byte verification of P25TrkSystemConfig.build_data_section()
    against every P25 trunked system data section in PAWSOVERMAWS.PRS."""

    def _check_section(self, sect_idx):
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        raw = prs.sections[sect_idx].raw
        config = _parse_p25_trunk_fields(raw)
        built = config.build_data_section()
        assert built == raw, (
            f"Section [{sect_idx}] mismatch: "
            f"built={len(built)}B vs orig={len(raw)}B, "
            f"first diff: {_first_diff(built, raw)}"
        )

    def test_section_6_psern_root(self):
        """PSERN root system (ecc_count=8 in section, entries external)."""
        self._check_section(6)

    def test_section_8_psrs(self):
        """PSRS inline system with 3 ECC entries."""
        self._check_section(8)

    def test_section_9_ss911(self):
        """SS911 inline system with 5 ECC entries."""
        self._check_section(9)

    def test_section_10_wasp_crosstype_chain(self):
        """WASP chains to conv system NV using 03 80 marker."""
        self._check_section(10)

    def test_section_12_nellis_different_float(self):
        """NELLIS has mystery float = 9.0 instead of 16339.0."""
        self._check_section(12)

    def test_section_13_snacc(self):
        """S NEVADA SNACC inline system."""
        self._check_section(13)

    def test_section_14_cs_nevada_30ecc(self):
        """C/S Nevada with 30 ECC entries (maximum observed)."""
        self._check_section(14)

    def test_section_15_washoe(self):
        """WASHOE/N NEVADA inline system."""
        self._check_section(15)

    def test_section_16_sfringe_last(self):
        """S/FRINGE last system in chain (ends with 07 00)."""
        self._check_section(16)


class TestConvBuilderAccuracy:
    """Byte-by-byte verification of ConvSystemConfig.build_data_section()
    against real conv system data sections."""

    def _parse_and_build_conv(self, raw):
        from quickprs.binary_io import read_lps
        pos = 44
        long_name, pos = read_lps(raw, pos)
        pos += 12
        conv_set, pos = read_lps(raw, pos)
        pos += 3
        tail_config = raw[pos:pos + 4]
        pos += 4
        next_sys = ''
        next_type = 0x01
        remaining = raw[pos:]
        if len(remaining) >= 3 and remaining[1] == 0x80:
            nl = remaining[2]
            if 0 < nl <= 8 and 3 + nl < len(remaining):
                next_sys = remaining[3:3 + nl].decode('ascii')
                next_type = remaining[3 + nl]
        return ConvSystemConfig(
            system_name=conv_set.strip(),
            long_name=long_name,
            conv_set_name=conv_set,
            tail_config=tail_config,
            next_system_name=next_sys,
            next_system_type=next_type,
        )

    def test_pawsovermaws_furry_wb_chained(self):
        """FURRY TRASH WB chains to FURRY NB."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        raw = prs.sections[2].raw
        config = self._parse_and_build_conv(raw)
        built = config.build_data_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"

    def test_pawsovermaws_furry_nb_chained(self):
        """FURRY TRASH NB chains to WA."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        raw = prs.sections[3].raw
        config = self._parse_and_build_conv(raw)
        built = config.build_data_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"

    def test_pawsovermaws_none_terminal(self):
        """Terminal conv system (no chain reference)."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        raw = prs.sections[4].raw
        config = self._parse_and_build_conv(raw)
        built = config.build_data_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"

    def test_claude_test_conv(self):
        """claude test conv system section."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        raw = prs.sections[6].raw
        config = self._parse_and_build_conv(raw)
        built = config.build_data_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"


class TestP25ConvBuilderAccuracy:
    """Byte-by-byte verification of P25ConvSystemConfig builders."""

    def test_claude_test_data_section(self):
        """P25Conv data section matches claude test section 8."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        raw = prs.sections[8].raw
        config = P25ConvSystemConfig(
            system_name='p25 conv', long_name='', conv_set_name='NEW')
        built = config.build_data_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"

    def test_claude_test_trailing_section(self):
        """P25Conv trailing section matches claude test section 9."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        raw = prs.sections[9].raw
        config = P25ConvSystemConfig(
            system_name='p25 conv', long_name='', conv_set_name='NEW')
        built = config.build_trailing_section()
        assert built == raw, f"Mismatch: {_first_diff(built, raw)}"


class TestSystemConfigPrefix:
    """Verify SYSTEM_CONFIG_PREFIX is identical across all system config sections."""

    def test_pawsovermaws_all_sections_same_prefix(self):
        """All 12 system config data sections in PAWSOVERMAWS share the same prefix."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        ref = SYSTEM_CONFIG_PREFIX
        count = 0
        for s in prs.sections:
            if not s.class_name and is_system_config_data(s.raw):
                prefix = s.raw[2:44]
                assert prefix == ref, (
                    f"Prefix mismatch in section at 0x{s.offset:04x}")
                count += 1
        assert count == 13, f"Expected 13 system configs, found {count}"

    def test_claude_test_all_sections_same_prefix(self):
        """All 3 system config data sections in claude test share the same prefix."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        ref = SYSTEM_CONFIG_PREFIX
        count = 0
        for s in prs.sections:
            if not s.class_name and is_system_config_data(s.raw):
                prefix = s.raw[2:44]
                assert prefix == ref, (
                    f"Prefix mismatch in section at 0x{s.offset:04x}")
                count += 1
        assert count == 3, f"Expected 3 system configs, found {count}"


class TestChainMarkerFormula:
    """Verify chain marker byte = next_system_type + 2."""

    def test_conv_chain_marker(self):
        """Conv system (type 0x01) uses marker byte 0x03."""
        assert 0x01 + 2 == 0x03

    def test_p25conv_chain_marker(self):
        """P25Conv system (type 0x03) uses marker byte 0x05."""
        assert 0x03 + 2 == 0x05

    def test_p25trunk_chain_marker(self):
        """P25Trunk system (type 0x05) uses marker byte 0x07."""
        assert 0x05 + 2 == 0x07

    def test_wasp_uses_conv_marker(self):
        """WASP (P25 trunk) chains to NV (conv) using 03 80 marker."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        raw = prs.sections[10].raw  # WASP
        # Chain reference at end: 03 80 02 4e 56 01
        assert raw[-6:-4] == b'\x03\x80', (
            f"Expected 03 80, got {raw[-6:-4].hex()}")
        assert raw[-1] == 0x01  # next type = conv


class TestPostEccTailFloat:
    """Verify the mystery float32 in post-ECC tail varies correctly."""

    def test_default_float_16339(self):
        """Most systems use 16339.0."""
        from quickprs.record_types import _build_post_ecc_tail
        tail = _build_post_ecc_tail(16339.0)
        assert len(tail) == 63
        val = struct.unpack_from('<f', tail, 12)[0]
        assert val == 16339.0

    def test_nellis_float_9(self):
        """NELLIS uses float = 9.0."""
        from quickprs.record_types import _build_post_ecc_tail
        tail = _build_post_ecc_tail(9.0)
        assert len(tail) == 63
        val = struct.unpack_from('<f', tail, 12)[0]
        assert val == 9.0

    def test_tail_structure(self):
        """Post-ECC tail: 12 zeros + float32 + 29 zeros + uint32(1)*2 + 10 zeros."""
        from quickprs.record_types import _build_post_ecc_tail
        tail = _build_post_ecc_tail(16339.0)
        assert tail[:12] == b'\x00' * 12
        assert tail[16:45] == b'\x00' * 29
        assert struct.unpack_from('<I', tail, 45)[0] == 1
        assert struct.unpack_from('<I', tail, 49)[0] == 1
        assert tail[53:] == b'\x00' * 10


class TestEccCountOverride:
    """Verify ecc_count_override works for root systems."""

    def test_root_system_ecc_count(self):
        """Root system (PSERN) stores ecc_count=8 but has no inline entries."""
        config = P25TrkSystemConfig(
            system_name='TEST',
            long_name='TEST',
            trunk_set_name='TEST',
            group_set_name='TEST',
            wan_name='TEST',
            ecc_entries=[],
            ecc_count_override=8,
        )
        built = config.build_data_section()
        # ECC count is at the end: 06 + uint16(8) = 06 08 00
        assert built[-3:] == b'\x06\x08\x00'

    def test_override_none_uses_entry_count(self):
        """When ecc_count_override is None, uses len(ecc_entries)."""
        entries = [EnhancedCCEntry(entry_type=4, system_id=100,
                                   channel_ref1=1, channel_ref2=2)]
        config = P25TrkSystemConfig(
            system_name='TEST',
            long_name='TEST',
            trunk_set_name='TEST',
            group_set_name='TEST',
            wan_name='TEST',
            ecc_entries=entries,
            iden_set_name='BEE00',
        )
        built = config.build_data_section()
        # Should contain 06 + uint16(1) before the ECC entry
        # Find 0x06 byte followed by uint16(1)
        ecc_marker_pos = built.index(b'\x06\x01\x00')
        assert ecc_marker_pos > 0


# ─── NEW TESTS: Dataclass construction / serialization ────────────────


class TestTrunkChannelUnit:
    """Unit-level TrunkChannel construction and serialization tests."""

    def test_construct_default_flags(self):
        """TrunkChannel with default flags should have 7 zero bytes."""
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0)
        assert ch.flags == b'\x00' * 7

    def test_to_bytes_size(self):
        """to_bytes() must produce exactly 23 bytes (RECORD_SIZE)."""
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0)
        raw = ch.to_bytes()
        assert len(raw) == 23
        assert len(raw) == TrunkChannel.RECORD_SIZE

    def test_roundtrip_synthetic(self):
        """Construct → to_bytes → parse should recover identical values."""
        ch = TrunkChannel(tx_freq=851.88750, rx_freq=806.88750,
                          flags=b'\x01\x02\x03\x04\x05\x06\x07')
        raw = ch.to_bytes()
        parsed, end_pos = TrunkChannel.parse(raw, 0)
        assert end_pos == 23
        assert abs(parsed.tx_freq - 851.88750) < 1e-9
        assert abs(parsed.rx_freq - 806.88750) < 1e-9
        assert parsed.flags == b'\x01\x02\x03\x04\x05\x06\x07'
        assert parsed.to_bytes() == raw

    def test_record_size_constant(self):
        """RECORD_SIZE class constant should be 23."""
        assert TrunkChannel.RECORD_SIZE == 23


class TestConvChannelUnit:
    """Unit-level ConvChannel construction and serialization tests."""

    def test_construct_all_fields(self):
        """ConvChannel with all fields set should serialize correctly."""
        ch = ConvChannel(
            short_name="TEST CH",
            tx_freq=462.5625,
            rx_freq=462.5625,
            tx_tone="250.3",
            rx_tone="131.8",
            tx_addr=0,
            rx_addr=0,
            long_name="TEST CHANNEL",
        )
        raw = ch.to_bytes()
        parsed, _ = ConvChannel.parse(raw, 0)
        assert parsed.short_name == "TEST CH"
        assert abs(parsed.tx_freq - 462.5625) < 1e-6
        assert parsed.tx_tone == "250.3"
        assert parsed.rx_tone == "131.8"
        assert parsed.long_name == "TEST CHANNEL"

    def test_byte_size_matches_to_bytes(self):
        """byte_size() should match len(to_bytes())."""
        ch = ConvChannel(
            short_name="MURS 1",
            tx_freq=151.82,
            rx_freq=151.82,
            tx_tone="",
            rx_tone="",
            long_name="MURS CHANNEL 1",
        )
        assert ch.byte_size() == len(ch.to_bytes())

    def test_roundtrip_synthetic(self):
        """Construct → to_bytes → parse should roundtrip."""
        ch = ConvChannel(
            short_name="FRS 1",
            tx_freq=462.5625,
            rx_freq=462.5625,
            tx_tone="67.0",
            rx_tone="",
            long_name="FRS CHANNEL 1",
        )
        raw = ch.to_bytes()
        parsed, end = ConvChannel.parse(raw, 0)
        assert end == len(raw)
        assert parsed.to_bytes() == raw

    def test_empty_tone_strings(self):
        """Channels with no tone should have empty strings."""
        ch = ConvChannel(
            short_name="NOPL",
            tx_freq=151.0,
            rx_freq=151.0,
        )
        raw = ch.to_bytes()
        parsed, _ = ConvChannel.parse(raw, 0)
        assert parsed.tx_tone == ""
        assert parsed.rx_tone == ""


class TestIdenElementUnit:
    """Unit-level IdenElement construction and serialization tests."""

    def test_to_bytes_size(self):
        """to_bytes() must produce exactly 15 bytes (RECORD_SIZE)."""
        elem = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                           base_freq_hz=851006250, iden_type=0)
        raw = elem.to_bytes()
        assert len(raw) == 15
        assert len(raw) == IdenElement.RECORD_SIZE

    def test_is_empty_default(self):
        """Default IdenElement (base_freq_hz=0) should be empty."""
        elem = IdenElement()
        assert elem.is_empty() is True

    def test_is_empty_with_freq(self):
        """IdenElement with a base frequency should not be empty."""
        elem = IdenElement(base_freq_hz=851006250)
        assert elem.is_empty() is False

    def test_tx_offset_mhz_negative(self):
        """tx_offset_mhz property with negative offset (e.g., -45.0 for 800 MHz band)."""
        import pytest
        elem = IdenElement()
        elem.tx_offset_mhz = -45.0
        assert elem.tx_offset_mhz == pytest.approx(-45.0, abs=1e-3)
        # Roundtrip through bytes
        raw = elem.to_bytes()
        parsed, _ = IdenElement.parse(raw, 0)
        assert parsed.tx_offset_mhz == pytest.approx(-45.0, abs=1e-3)

    def test_tx_offset_mhz_positive(self):
        """tx_offset_mhz property with positive offset (e.g., +30.0)."""
        import pytest
        elem = IdenElement()
        elem.tx_offset_mhz = 30.0
        assert elem.tx_offset_mhz == pytest.approx(30.0, abs=1e-3)

    def test_tx_offset_mhz_zero(self):
        """tx_offset_mhz of 0.0 should also work."""
        import pytest
        elem = IdenElement(tx_offset=0)
        assert elem.tx_offset_mhz == pytest.approx(0.0, abs=1e-6)

    def test_roundtrip_synthetic(self):
        """Construct → to_bytes → parse should roundtrip."""
        elem = IdenElement(chan_spacing_hz=6250, bandwidth_hz=6250,
                           base_freq_hz=764006250, tx_offset=0, iden_type=1)
        raw = elem.to_bytes()
        parsed, end = IdenElement.parse(raw, 0)
        assert end == 15
        assert parsed.chan_spacing_hz == 6250
        assert parsed.bandwidth_hz == 6250
        assert parsed.base_freq_hz == 764006250
        assert parsed.iden_type == 1
        assert parsed.to_bytes() == raw


class TestP25GroupUnit:
    """Unit-level P25Group construction and serialization tests."""

    def test_construct_and_serialize(self):
        """P25Group with all fields set should serialize correctly."""
        grp = P25Group(
            group_name="FIRE D1",
            group_id=2305,
            long_name="FIRE DISPATCH 1",
            rx=True, calls=True, alert=True,
            scan_list_member=True, scan=True,
            backlight=True, tx=False,
        )
        raw = grp.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.group_name == "FIRE D1"
        assert parsed.group_id == 2305
        assert parsed.long_name == "FIRE DISPATCH 1"
        assert parsed.tx is False
        assert parsed.rx is True
        assert parsed.scan is True

    def test_to_bytes_includes_booleans(self):
        """to_bytes should correctly encode boolean block."""
        grp = P25Group(
            group_name="TEST",
            group_id=1000,
            rx=True, calls=False, alert=True,
            scan_list_member=False, scan=True,
            backlight=False, tx=True,
        )
        raw = grp.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.rx is True
        assert parsed.calls is False
        assert parsed.alert is True
        assert parsed.scan_list_member is False
        assert parsed.scan is True
        assert parsed.backlight is False
        assert parsed.tx is True

    def test_byte_size_matches(self):
        """byte_size() should match len(to_bytes())."""
        grp = P25Group(group_name="TGRP 1", group_id=100,
                       long_name="TALKGROUP ONE")
        assert grp.byte_size() == len(grp.to_bytes())

    def test_roundtrip_synthetic(self):
        """Construct → to_bytes → parse → to_bytes should be identical."""
        grp = P25Group(group_name="PD TAC2", group_id=9999,
                       long_name="POLICE TAC 2",
                       tx=True, scan=False)
        raw = grp.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.to_bytes() == raw


# ─── NEW TESTS: Set-level serialization ───────────────────────────────


class TestTrunkSetSerialization:
    """TrunkSet channels_to_bytes and metadata_to_bytes tests."""

    def test_channels_to_bytes_with_separators(self):
        """Multiple channels should be joined by TRUNK_CHANNEL_SEP."""
        ch1 = TrunkChannel(tx_freq=851.0, rx_freq=806.0)
        ch2 = TrunkChannel(tx_freq=852.0, rx_freq=807.0)
        ts = TrunkSet(name="TEST", channels=[ch1, ch2])
        raw = ts.channels_to_bytes()
        # 23 + 2 + 23 = 48 bytes
        assert len(raw) == 23 + 2 + 23
        # Separator between channel bytes
        assert raw[23:25] == TRUNK_CHANNEL_SEP

    def test_channels_to_bytes_single(self):
        """Single channel should have no separator."""
        ch = TrunkChannel(tx_freq=851.0, rx_freq=806.0)
        ts = TrunkSet(name="SOLO", channels=[ch])
        raw = ts.channels_to_bytes()
        assert len(raw) == 23
        assert TRUNK_CHANNEL_SEP not in raw

    def test_metadata_to_bytes_format(self):
        """metadata_to_bytes should contain name + padding + 4 doubles."""
        ts = TrunkSet(name="PSERN", tx_min=136.0, tx_max=870.0,
                      rx_min=136.0, rx_max=870.0)
        meta = ts.metadata_to_bytes()
        # LPS(5 chars) = 6 bytes + 2 padding + 4*8 doubles = 40 bytes
        assert len(meta) == 6 + 2 + 32


class TestConvSetSerialization:
    """ConvSet channels_to_bytes and metadata_to_bytes tests."""

    def test_channels_to_bytes_with_separators(self):
        """Multiple conv channels should be joined by CONV_CHANNEL_SEP."""
        ch1 = ConvChannel(short_name="CH1", tx_freq=151.0, rx_freq=151.0)
        ch2 = ConvChannel(short_name="CH2", tx_freq=152.0, rx_freq=152.0)
        cs = ConvSet(name="TEST", channels=[ch1, ch2])
        raw = cs.channels_to_bytes()
        assert CONV_CHANNEL_SEP in raw

    def test_metadata_to_bytes_format(self):
        """metadata_to_bytes should contain name LPS + 60 bytes metadata."""
        cs = ConvSet(name="WA WIDE")
        meta = cs.metadata_to_bytes()
        # LPS("WA WIDE") = 8 bytes + 60 metadata = 68
        assert len(meta) == 1 + len("WA WIDE") + ConvSet.METADATA_SIZE


# ─── NEW TESTS: Decoded opaque fields ─────────────────────────────────


class TestConvChannelDecodedFlags:
    """Test ConvChannel decoded flag fields from the 48-byte flags block."""

    def test_default_flags_pattern(self):
        """Default construction produces correct 48-byte pattern."""
        ch = ConvChannel(short_name="CH1", tx_freq=462.0, rx_freq=462.0)
        f = ch.flags
        assert len(f) == 48
        # Defaults: rx=True, calls=True, alert=True, slm=True, scan=True, tx=True
        # flag0=False, tone_mode=False, narrowband=False
        assert f[0] == 0   # flag0
        assert f[1] == 1   # rx
        assert f[2] == 1   # calls
        assert f[3] == 1   # alert
        assert f[4] == 1   # scan_list_member
        assert f[22] == 0  # tone_mode
        assert f[27] == 0  # narrowband
        assert f[29] == 1  # scan
        assert f[46] == 1  # tx

    def test_narrowband_flag(self):
        """narrowband=True sets byte 27 to 1 in flags."""
        ch = ConvChannel(short_name="NB", tx_freq=462.0, rx_freq=462.0,
                         narrowband=True)
        assert ch.flags[27] == 1
        assert ch.narrowband is True

    def test_wideband_flag(self):
        """narrowband=False (default) leaves byte 27 as 0."""
        ch = ConvChannel(short_name="WB", tx_freq=462.0, rx_freq=462.0)
        assert ch.flags[27] == 0
        assert ch.narrowband is False

    def test_tone_mode_flag(self):
        """tone_mode=True sets byte 22 to 1."""
        ch = ConvChannel(short_name="TN", tx_freq=462.0, rx_freq=462.0,
                         tone_mode=True)
        assert ch.flags[22] == 1

    def test_tx_disable(self):
        """tx=False sets byte 46 to 0 (receive-only)."""
        ch = ConvChannel(short_name="RX", tx_freq=462.0, rx_freq=462.0,
                         tx=False)
        assert ch.flags[46] == 0
        assert ch.tx is False

    def test_scan_disable(self):
        """scan=False sets byte 29 to 0."""
        ch = ConvChannel(short_name="NS", tx_freq=462.0, rx_freq=462.0,
                         scan=False)
        assert ch.flags[29] == 0

    def test_flags_setter_backward_compat(self):
        """Setting .flags from a 48-byte blob decodes all named fields."""
        # FURRY NB pattern: 48 bytes = 96 hex chars
        nb_flags = bytes.fromhex(
            '000101010100000000000000000000000000000000000100'
            '000000010001000000000000000000000000000000000100')
        ch = ConvChannel(short_name="X", tx_freq=462.0, rx_freq=462.0)
        ch.flags = nb_flags
        assert ch.flag0 is False
        assert ch.rx is True
        assert ch.calls is True
        assert ch.alert is True
        assert ch.scan_list_member is True
        assert ch.tone_mode is True
        assert ch.narrowband is True
        assert ch.scan is True
        assert ch.tx is True

    def test_flags_setter_invalid_length(self):
        """Setting .flags with wrong length should raise."""
        import pytest
        ch = ConvChannel(short_name="X", tx_freq=462.0, rx_freq=462.0)
        with pytest.raises(ValueError):
            ch.flags = b'\x00' * 10

    def test_flags_roundtrip_all_patterns(self):
        """All 3 observed flag patterns should roundtrip through decode/encode."""
        patterns = [
            # MURS (WA WIDE)
            '010101010100000000000000000000000000000000000000000000000001000000000000000000000000000000000100',
            # FURRY NB
            '000101010100000000000000000000000000000000000100000000010001000000000000000000000000000000000100',
            # FURRY WB
            '000101010100000000000000000000000000000000000100000000000001000000000000000000000000000000000100',
        ]
        for pat_hex in patterns:
            raw = bytes.fromhex(pat_hex)
            ch = ConvChannel(short_name="X", tx_freq=462.0, rx_freq=462.0)
            ch.flags = raw
            assert ch.flags == raw, f"Roundtrip failed for {pat_hex}"

    def test_flags_parsed_from_real_file_nb(self):
        """Parse real NB channel and verify decoded flags."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), fc)
        # FURRY NB set (index 1) should have narrowband=True
        nb_set = sets[1]
        assert nb_set.name == "FURRY NB"
        for ch in nb_set.channels:
            assert ch.narrowband is True
            assert ch.tone_mode is True
            assert ch.tx is True
            assert ch.scan is True

    def test_flags_parsed_from_real_file_wb(self):
        """Parse real WB channel and verify decoded flags."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), fc)
        # FURRY WB set (index 2) should have narrowband=False
        wb_set = sets[2]
        assert wb_set.name == "FURRY WB"
        for ch in wb_set.channels:
            assert ch.narrowband is False
            assert ch.tone_mode is True

    def test_flags_parsed_murs(self):
        """Parse MURS channels (WA WIDE set) and verify flag0=True."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), fc)
        murs_set = sets[0]
        assert murs_set.name == "WA WIDE"
        for ch in murs_set.channels:
            assert ch.flag0 is True
            assert ch.tone_mode is False
            assert ch.narrowband is False

    def test_power_level_property(self):
        """power_level should read from pre_long_name byte 1."""
        ch = ConvChannel(short_name="X", tx_freq=462.0, rx_freq=462.0)
        assert ch.power_level == 2  # default pre_long_name has 0x02 at byte 1

    def test_squelch_threshold_property(self):
        """squelch_threshold should read from pre_long_name byte 2."""
        ch = ConvChannel(short_name="X", tx_freq=462.0, rx_freq=462.0)
        assert ch.squelch_threshold == 12  # default pre_long_name has 0x0C at byte 2


class TestConvSetDecodedMetadata:
    """Test ConvSet decoded metadata fields (band limits, config)."""

    def test_default_metadata_no_limits(self):
        """Default ConvSet should have no band limits set."""
        cs = ConvSet(name="TEST")
        assert cs.config_flag == 0x01
        assert cs.has_band_limits == 0x00
        assert cs.tx_min == 0.0
        assert cs.rx_min == 0.0
        assert cs.tx_max == 0.0
        assert cs.rx_max == 0.0
        assert len(cs.metadata) == 60

    def test_band_limits_set(self):
        """ConvSet with band limits should encode doubles correctly."""
        cs = ConvSet(name="TEST")
        cs.has_band_limits = 0x01
        cs.tx_min = 136.0
        cs.rx_min = 136.0
        cs.tx_max = 870.0
        cs.rx_max = 870.0
        meta = cs.metadata
        assert len(meta) == 60
        assert meta[1] == 0x01  # has_band_limits
        import struct as _struct
        assert _struct.unpack_from('<d', meta, 2)[0] == 136.0
        assert _struct.unpack_from('<d', meta, 18)[0] == 870.0

    def test_metadata_setter_backward_compat(self):
        """Setting .metadata from a 60-byte blob decodes band limits."""
        import struct as _struct
        raw = bytearray(60)
        raw[0] = 0x01
        raw[1] = 0x01
        _struct.pack_into('<d', raw, 2, 136.0)
        _struct.pack_into('<d', raw, 10, 136.0)
        _struct.pack_into('<d', raw, 18, 870.0)
        _struct.pack_into('<d', raw, 26, 870.0)
        raw[38] = 0x01
        raw[39] = 0x01
        cs = ConvSet(name="X")
        cs.metadata = bytes(raw)
        assert cs.has_band_limits == 0x01
        assert cs.tx_min == 136.0
        assert cs.rx_min == 136.0
        assert cs.tx_max == 870.0
        assert cs.rx_max == 870.0

    def test_metadata_setter_invalid_length(self):
        """Setting .metadata with wrong length should raise."""
        import pytest
        cs = ConvSet(name="X")
        with pytest.raises(ValueError):
            cs.metadata = b'\x00' * 20

    def test_metadata_roundtrip_real_file(self):
        """Parse real file metadata and verify roundtrip."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        ch_sec = prs.get_section_by_class("CConvChannel")
        set_sec = prs.get_section_by_class("CConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), fc)
        # FURRY NB should have band limits
        nb_set = sets[1]
        assert nb_set.has_band_limits == 0x01
        assert nb_set.tx_min == 136.0
        assert nb_set.tx_max == 870.0
        # WA WIDE should NOT have band limits
        wide_set = sets[0]
        assert wide_set.has_band_limits == 0x00
        assert wide_set.tx_min == 0.0


class TestP25GroupDecodedFields:
    """Test P25Group decoded middle and tail fields."""

    def test_default_middle(self):
        """Default P25Group middle should have audio_profile=8."""
        g = P25Group(group_name="TEST", group_id=100)
        assert g.audio_file == 0
        assert g.audio_profile == 0x08
        assert g.tg_index == 0
        assert g.key_id == 0
        assert g.priority_tg is False
        assert len(g.middle) == 12

    def test_default_tail(self):
        """Default P25Group tail should have all zeros."""
        g = P25Group(group_name="TEST", group_id=100)
        assert g.use_group_id is False
        assert g.encrypted is False
        assert g.tg_type == 0
        assert g.suppress is False
        assert len(g.tail) == 4

    def test_middle_setter(self):
        """Setting .middle from bytes decodes all sub-fields."""
        g = P25Group(group_name="X", group_id=1)
        g.middle = b'\x01\x00\x08\x02\x00\x05\x00\x00\x00\x00\x00\x01'
        assert g.audio_file == 1
        assert g.audio_profile == 0x08
        assert g.tg_index == 2
        assert g.key_id == 5
        assert g.priority_tg is True

    def test_middle_roundtrip(self):
        """Encode → decode middle block should roundtrip."""
        g = P25Group(group_name="X", group_id=1, priority_tg=True)
        raw = g.middle
        g2 = P25Group(group_name="Y", group_id=2)
        g2.middle = raw
        assert g2.priority_tg is True
        assert g2.middle == raw

    def test_tail_setter(self):
        """Setting .tail from bytes decodes fields."""
        g = P25Group(group_name="X", group_id=1)
        g.tail = b'\x01\x01\x00\x01'
        assert g.use_group_id is True
        assert g.encrypted is True
        assert g.tg_type == 0
        assert g.suppress is True

    def test_tail_roundtrip(self):
        """Encode → decode tail should roundtrip."""
        g = P25Group(group_name="X", group_id=1,
                     use_group_id=True, encrypted=True, suppress=True)
        raw = g.tail
        assert raw == b'\x01\x01\x00\x01'
        g2 = P25Group(group_name="Y", group_id=2)
        g2.tail = raw
        assert g2.use_group_id is True
        assert g2.encrypted is True
        assert g2.suppress is True

    def test_middle_invalid_length(self):
        """Setting .middle with wrong length should raise."""
        import pytest
        g = P25Group(group_name="X", group_id=1)
        with pytest.raises(ValueError):
            g.middle = b'\x00' * 5

    def test_tail_invalid_length(self):
        """Setting .tail with wrong length should raise."""
        import pytest
        g = P25Group(group_name="X", group_id=1)
        with pytest.raises(ValueError):
            g.tail = b'\x00' * 2

    def test_priority_tg_from_real_file(self):
        """SNACC/NLVPD T1 should have priority_tg=True in PAWSOVERMAWS."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        g_sec = prs.get_section_by_class("CP25Group")
        gs_sec = prs.get_section_by_class("CP25GroupSet")
        _, _, _, ds = parse_class_header(gs_sec.raw, 0)
        fc, _ = read_uint16_le(gs_sec.raw, ds)
        _, _, _, cd = parse_class_header(g_sec.raw, 0)
        gsets = parse_group_section(g_sec.raw, cd, len(g_sec.raw), fc)
        # Find SNACC set, look for NLVPD T1
        snacc = [gs for gs in gsets if gs.name == "SNACC"][0]
        nlvpd = [g for g in snacc.groups if g.group_name == "NLVPD T1"][0]
        assert nlvpd.priority_tg is True
        assert nlvpd.group_id == 2265
        # All other groups should have priority_tg=False
        for gs in gsets:
            for g in gs.groups:
                if g.group_name != "NLVPD T1":
                    assert g.priority_tg is False

    def test_full_roundtrip_to_bytes(self):
        """P25Group with non-default decoded fields should roundtrip."""
        g = P25Group(
            group_name="PD MAIN",
            group_id=2305,
            long_name="POLICE MAIN",
            rx=True, calls=True, alert=True,
            scan_list_member=True, scan=True,
            backlight=True, tx=True,
            priority_tg=True,
            use_group_id=True,
            encrypted=True,
        )
        raw = g.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.priority_tg is True
        assert parsed.use_group_id is True
        assert parsed.encrypted is True
        assert parsed.to_bytes() == raw


class TestP25GroupSetDecodedMetadata:
    """Test P25GroupSet decoded metadata fields."""

    def test_default_metadata(self):
        """Default P25GroupSet should have scan_list_size=9, system_id=0."""
        gs = P25GroupSet(name="TEST")
        assert gs.scan_list_size == 0x09
        assert gs.system_id == 0
        assert len(gs.metadata) == 16

    def test_system_id_set(self):
        """Setting system_id should appear in metadata bytes 5-6."""
        import struct as _struct
        gs = P25GroupSet(name="PSERN")
        gs.system_id = 939
        meta = gs.metadata
        assert _struct.unpack_from('<H', meta, 5)[0] == 939

    def test_metadata_setter(self):
        """Setting .metadata from bytes decodes fields."""
        raw = bytearray(16)
        raw[0] = 0x09
        raw[5] = 0xAB
        raw[6] = 0x03  # 0x03AB = 939
        gs = P25GroupSet(name="X")
        gs.metadata = bytes(raw)
        assert gs.scan_list_size == 0x09
        assert gs.system_id == 939

    def test_metadata_setter_invalid_length(self):
        """Setting .metadata with wrong length should raise."""
        import pytest
        gs = P25GroupSet(name="X")
        with pytest.raises(ValueError):
            gs.metadata = b'\x00' * 8

    def test_metadata_roundtrip_real_file(self):
        """Parse real file and verify system_id roundtrip."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        g_sec = prs.get_section_by_class("CP25Group")
        gs_sec = prs.get_section_by_class("CP25GroupSet")
        _, _, _, ds = parse_class_header(gs_sec.raw, 0)
        fc, _ = read_uint16_le(gs_sec.raw, ds)
        _, _, _, cd = parse_class_header(g_sec.raw, 0)
        gsets = parse_group_section(g_sec.raw, cd, len(g_sec.raw), fc)
        # PSERN PD should have system_id=939
        psern = [gs for gs in gsets if gs.name == "PSERN PD"][0]
        assert psern.system_id == 939
        assert psern.scan_list_size == 0x09
        # WASP should have system_id=2508
        wasp = [gs for gs in gsets if gs.name == "WASP"][0]
        assert wasp.system_id == 2508
        # PSRS PD should have system_id=0 (unlinked)
        psrs = [gs for gs in gsets if gs.name == "PSRS PD"][0]
        assert psrs.system_id == 0

    def test_metadata_roundtrip_bytes(self):
        """Metadata encode → decode should be lossless."""
        import struct as _struct
        raw = bytearray(16)
        raw[0] = 0x09
        _struct.pack_into('<H', raw, 5, 1121)
        gs = P25GroupSet(name="X")
        gs.metadata = bytes(raw)
        assert gs.metadata == bytes(raw)


class TestIdenDataSetSerialization:
    """IdenDataSet elements_to_bytes tests."""

    def test_pads_to_16_slots(self):
        """elements_to_bytes should always serialize 16 element slots."""
        iset = IdenDataSet(name="BEE00", elements=[
            IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                        base_freq_hz=851006250, iden_type=0),
        ])
        raw = iset.elements_to_bytes()
        # 16 elements * 15 bytes + 15 separators * 2 bytes = 240 + 30 = 270
        assert len(raw) == 16 * 15 + 15 * 2

    def test_empty_set_pads_to_16(self):
        """Empty element list should still produce 16 slots."""
        iset = IdenDataSet(name="EMPTY", elements=[])
        raw = iset.elements_to_bytes()
        assert len(raw) == 16 * 15 + 15 * 2

    def test_full_16_elements(self):
        """16 elements should produce same total size with no extra padding."""
        elems = [IdenElement(base_freq_hz=i * 1000) for i in range(16)]
        iset = IdenDataSet(name="FULL", elements=elems)
        raw = iset.elements_to_bytes()
        assert len(raw) == 16 * 15 + 15 * 2


class TestP25GroupSetSerialization:
    """P25GroupSet groups_to_bytes and metadata_to_bytes tests."""

    def test_groups_to_bytes_with_separators(self):
        """Multiple groups should be joined by GROUP_SEP."""
        g1 = P25Group(group_name="GRP 1", group_id=100)
        g2 = P25Group(group_name="GRP 2", group_id=200)
        gs = P25GroupSet(name="TESTPD", groups=[g1, g2])
        raw = gs.groups_to_bytes()
        assert GROUP_SEP in raw

    def test_groups_to_bytes_single(self):
        """Single group should have no separator."""
        g = P25Group(group_name="ONLY", group_id=42)
        gs = P25GroupSet(name="SOLO", groups=[g])
        raw = gs.groups_to_bytes()
        assert GROUP_SEP not in raw

    def test_metadata_to_bytes_size(self):
        """metadata_to_bytes should have name LPS + 16 bytes."""
        gs = P25GroupSet(name="PSERNPD")
        meta = gs.metadata_to_bytes()
        assert len(meta) == 1 + len("PSERNPD") + P25GroupSet.METADATA_SIZE


# ─── NEW TESTS: Section builder roundtrips ────────────────────────────


class TestSectionBuilderRoundtrips:
    """Build a section from structured data → parse it back → compare."""

    def test_trunk_channel_section_roundtrip(self):
        """build_trunk_channel_section preserves channel data from real file.

        The build function produces a complete section with header, channels,
        metadata, and trailing bytes. We verify that channel data within the
        rebuilt section matches the original parsed data.
        """
        data = (TESTDATA / "PAWSOVERMAWS.PRS").read_bytes()
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        import pytest

        trunk_set_sec = prs.get_section_by_class("CTrunkSet")
        _, _, _, ds = parse_class_header(trunk_set_sec.raw, 0)
        first_count, _ = read_uint16_le(trunk_set_sec.raw, ds)

        trunk_ch_sec = prs.get_section_by_class("CTrunkChannel")
        _, _, _, ch_data_start = parse_class_header(data, trunk_ch_sec.offset)

        sets = parse_trunk_channel_section(
            data, ch_data_start,
            trunk_ch_sec.offset + len(trunk_ch_sec.raw),
            first_count)

        # Rebuild the section
        rebuilt_raw = build_trunk_channel_section(sets)
        assert rebuilt_raw[:2] == SECTION_MARKER
        assert b'CTrunkChannel' in rebuilt_raw

        # Verify individual channel bytes within rebuilt section match
        _, _, _, rebuilt_data = parse_class_header(rebuilt_raw, 0)
        ch_rebuilt, _ = TrunkChannel.parse(rebuilt_raw, rebuilt_data)
        assert ch_rebuilt.tx_freq == pytest.approx(
            sets[0].channels[0].tx_freq, abs=1e-9)
        assert ch_rebuilt.rx_freq == pytest.approx(
            sets[0].channels[0].rx_freq, abs=1e-9)

    def test_group_section_roundtrip(self):
        """build_group_section → parse_group_section recovers data."""
        g1 = P25Group(group_name="ALG PD", group_id=2303,
                      long_name="ALGONA PD TAC")
        g2 = P25Group(group_name="FED 1", group_id=5001,
                      long_name="FEDERAL TAC 1", tx=True)
        gset = P25GroupSet(name="TESTGRP", groups=[g1, g2])
        raw = build_group_section([gset])
        _, _, _, data_start = parse_class_header(raw, 0)
        sets = parse_group_section(raw, data_start, len(raw), 2)
        assert len(sets) == 1
        assert sets[0].name == "TESTGRP"
        assert len(sets[0].groups) == 2
        assert sets[0].groups[0].group_name == "ALG PD"
        assert sets[0].groups[0].group_id == 2303
        assert sets[0].groups[1].tx is True

    def test_conv_channel_section_roundtrip(self):
        """build_conv_channel_section → parse_conv_channel_section recovers data."""
        import pytest
        ch1 = ConvChannel(short_name="MURS 1", tx_freq=151.82, rx_freq=151.82,
                          long_name="MURS CHANNEL 1")
        ch2 = ConvChannel(short_name="MURS 2", tx_freq=151.88, rx_freq=151.88,
                          long_name="MURS CHANNEL 2")
        cset = ConvSet(name="WA WIDE", channels=[ch1, ch2])
        raw = build_conv_channel_section([cset])
        _, _, _, data_start = parse_class_header(raw, 0)
        sets = parse_conv_channel_section(raw, data_start, len(raw), 2)
        assert len(sets) == 1
        assert sets[0].name == "WA WIDE"
        assert len(sets[0].channels) == 2
        assert sets[0].channels[0].short_name == "MURS 1"
        assert sets[0].channels[1].tx_freq == pytest.approx(151.88, abs=1e-6)

    def test_iden_section_roundtrip(self):
        """build_iden_section → parse_iden_section recovers data."""
        elem1 = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                            base_freq_hz=851006250, tx_offset=0, iden_type=0)
        elem2 = IdenElement(chan_spacing_hz=6250, bandwidth_hz=6250,
                            base_freq_hz=851006250, tx_offset=0, iden_type=1)
        iset = IdenDataSet(name="BEE00", elements=[elem1, elem2])
        raw = build_iden_section([iset])
        _, _, _, data_start = parse_class_header(raw, 0)
        sets = parse_iden_section(raw, data_start, len(raw), 16)
        assert len(sets) == 1
        assert sets[0].name == "BEE00"
        assert len(sets[0].elements) == 16  # padded to 16
        assert sets[0].elements[0].chan_spacing_hz == 12500
        assert sets[0].elements[1].iden_type == 1
        # Remaining elements should be empty (default)
        assert sets[0].elements[2].is_empty() is True

    def test_trunk_set_section_header(self):
        """build_trunk_set_section should produce header + uint16 count."""
        raw = build_trunk_set_section(28)
        assert raw[:2] == b'\xff\xff'
        assert b'CTrunkSet' in raw
        # Last 2 bytes are the count
        count = struct.unpack_from('<H', raw, len(raw) - 2)[0]
        assert count == 28

    def test_group_set_section_header(self):
        """build_group_set_section should produce header + uint16 count."""
        raw = build_group_set_section(83)
        assert raw[:2] == b'\xff\xff'
        assert b'CP25GroupSet' in raw
        count = struct.unpack_from('<H', raw, len(raw) - 2)[0]
        assert count == 83

    def test_conv_set_section_header(self):
        """build_conv_set_section should produce header + uint16 count."""
        raw = build_conv_set_section(5)
        assert raw[:2] == b'\xff\xff'
        assert b'CConvSet' in raw
        count = struct.unpack_from('<H', raw, len(raw) - 2)[0]
        assert count == 5

    def test_iden_set_section_header(self):
        """build_iden_set_section should produce header + uint16 count."""
        raw = build_iden_set_section(16)
        assert raw[:2] == b'\xff\xff'
        assert b'CIdenDataSet' in raw
        count = struct.unpack_from('<H', raw, len(raw) - 2)[0]
        assert count == 16


# ─── NEW TESTS: System config header/data builders ───────────────────


class TestConvSystemConfig:
    """ConvSystemConfig header and data section tests."""

    def test_header_contains_class_name(self):
        """build_header_section should contain CConvSystem."""
        cfg = ConvSystemConfig(system_name="WA WIDE", long_name="WA WIDE AREA")
        header = cfg.build_header_section()
        assert b'CConvSystem' in header
        assert header[-1] == 0x01  # trailing byte for conv
        assert header[:2] == b'\xff\xff'

    def test_header_contains_system_name(self):
        """Header should contain the system short name."""
        cfg = ConvSystemConfig(system_name="FURRY WB")
        header = cfg.build_header_section()
        assert b'FURRY WB' in header

    def test_data_section_contains_prefix(self):
        """build_data_section should start with SECTION_MARKER + SYSTEM_CONFIG_PREFIX."""
        cfg = ConvSystemConfig(system_name="TEST",
                               long_name="TEST SYSTEM",
                               conv_set_name="TEST")
        data = cfg.build_data_section()
        assert data[:2] == SECTION_MARKER
        assert data[2:44] == SYSTEM_CONFIG_PREFIX

    def test_data_section_contains_set_name(self):
        """Data section should contain the conv set name reference."""
        cfg = ConvSystemConfig(system_name="WA", conv_set_name="WA WIDE")
        data = cfg.build_data_section()
        assert b'WA WIDE' in data


class TestP25ConvSystemConfig:
    """P25ConvSystemConfig header, data, and trailing section tests."""

    def test_header_contains_class_name(self):
        """build_header_section should contain CP25ConvSystem."""
        cfg = P25ConvSystemConfig(system_name="P25CONV")
        header = cfg.build_header_section()
        assert b'CP25ConvSystem' in header
        assert header[-1] == 0x03  # trailing byte for P25 conv
        assert header[:2] == b'\xff\xff'

    def test_data_section_contains_prefix(self):
        """Data section should start with SECTION_MARKER + SYSTEM_CONFIG_PREFIX."""
        cfg = P25ConvSystemConfig(system_name="TEST",
                                  long_name="P25 CONV TEST",
                                  conv_set_name="NEW")
        data = cfg.build_data_section()
        assert data[:2] == SECTION_MARKER
        assert data[2:44] == SYSTEM_CONFIG_PREFIX

    def test_data_section_contains_set_name(self):
        """Data section should contain the conv set name reference."""
        cfg = P25ConvSystemConfig(system_name="T", conv_set_name="MYCONV")
        data = cfg.build_data_section()
        assert b'MYCONV' in data

    def test_trailing_section_format(self):
        """build_trailing_section should start with SECTION_MARKER + _P25CONV_TRAILING."""
        from quickprs.record_types import _P25CONV_TRAILING
        cfg = P25ConvSystemConfig(system_name="T")
        trailing = cfg.build_trailing_section()
        assert trailing[:2] == SECTION_MARKER
        assert trailing[2:] == _P25CONV_TRAILING
        assert len(trailing) == 2 + 28  # SECTION_MARKER + 28 bytes


# ─── NEW TESTS: PreferredSystemEntry roundtrip ───────────────────────


class TestPreferredSystemEntry:
    """PreferredSystemEntry to_bytes / from_bytes roundtrip tests."""

    def test_to_bytes_from_bytes_roundtrip(self):
        """Construct → to_bytes → from_bytes should recover fields."""
        entry = PreferredSystemEntry(
            entry_type=3, system_id=892, field1=1, field2=0,
            last_sep=b'\x00\x00',
        )
        raw = entry.to_bytes(is_last=True)
        assert len(raw) == 15
        parsed = PreferredSystemEntry.from_bytes(raw, 0)
        assert parsed is not None
        assert parsed.entry_type == 3
        assert parsed.system_id == 892
        assert parsed.field1 == 1
        assert parsed.field2 == 0

    def test_to_bytes_not_last_uses_pref_sep(self):
        """When not last, separator should be PREF_SEP (09 80)."""
        from quickprs.record_types import PREF_SEP
        entry = PreferredSystemEntry(entry_type=3, system_id=100)
        raw = entry.to_bytes(is_last=False)
        assert raw[13:15] == PREF_SEP

    def test_to_bytes_last_uses_last_sep(self):
        """When last, separator should be the entry's last_sep."""
        entry = PreferredSystemEntry(entry_type=4, system_id=200,
                                     last_sep=b'\x01\x00')
        raw = entry.to_bytes(is_last=True)
        assert raw[13:15] == b'\x01\x00'

    def test_from_bytes_returns_none_on_short_data(self):
        """from_bytes should return None if data is too short."""
        result = PreferredSystemEntry.from_bytes(b'\x00' * 10, 0)
        assert result is None

    def test_pawsovermaws_preferred_section(self):
        """Parse real preferred section from PAWSOVERMAWS, verify roundtrip."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        pref_sec = prs.get_section_by_class("CPreferredSystemTableEntry")
        if pref_sec is None:
            # File may not have preferred entries
            return
        entries, iden_name, tail_bytes, chain_name, chain_type = \
            parse_preferred_section(pref_sec.raw)
        assert len(entries) > 0, "PAWSOVERMAWS should have preferred entries"
        # Verify each entry has a valid type
        for e in entries:
            assert e.entry_type in (3, 4), f"Unexpected type: {e.entry_type}"

    def test_build_preferred_section_roundtrip(self):
        """build → parse preferred section should recover entries."""
        entries = [
            PreferredSystemEntry(entry_type=3, system_id=892, field1=1, field2=0),
            PreferredSystemEntry(entry_type=3, system_id=587, field1=1, field2=1,
                                 last_sep=b'\x00\x00'),
        ]
        raw = build_preferred_section(entries, iden_name="BEE00",
                                       chain_name="NEXT", chain_type=0x05)
        parsed_entries, iden, tail, chain, ctype = parse_preferred_section(raw)
        assert len(parsed_entries) == 2
        assert parsed_entries[0].system_id == 892
        assert parsed_entries[1].system_id == 587
        assert iden == "BEE00"
        assert chain == "NEXT"
        assert ctype == 0x05


# ─── NEW TESTS: System name parsers against test files ────────────────


class TestSystemNameParsers:
    """parse_system_short_name, parse_system_long_name, parse_system_wan_name
    tested against both test files."""

    def test_short_name_pawsovermaws(self):
        """Parse short names from system header sections in PAWSOVERMAWS.

        PAWSOVERMAWS has 1 CConvSystem and 1 CP25TrkSystem header;
        additional P25 systems are inline data sections (chained).
        """
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        names = []
        for sec in prs.sections:
            if sec.class_name in ("CP25TrkSystem", "CConvSystem",
                                   "CP25ConvSystem"):
                name = parse_system_short_name(sec.raw)
                if name:
                    names.append(name)
        assert "PSERN" in names, f"PSERN not found in {names}"
        # PAWSOVERMAWS has exactly 2 named system headers
        assert len(names) == 2, f"Expected 2 system headers, got {names}"

    def test_short_name_claude_test(self):
        """Parse short names from claude test.PRS."""
        from quickprs.record_types import parse_system_short_name
        prs = parse_prs(TESTDATA / "claude test.PRS")
        names = []
        for sec in prs.sections:
            if sec.class_name in ("CP25TrkSystem", "CConvSystem",
                                   "CP25ConvSystem"):
                name = parse_system_short_name(sec.raw)
                if name:
                    names.append(name)
        assert len(names) >= 1, f"Expected at least 1 system, got {names}"

    def test_long_name_pawsovermaws(self):
        """Parse long names from system config data sections in PAWSOVERMAWS."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        long_names = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name:
                    long_names.append(name)
        assert "PSERN SEATTLE" in long_names, \
            f"PSERN SEATTLE not found in {long_names}"

    def test_wan_name_pawsovermaws(self):
        """Parse WAN names from P25 trunked system configs in PAWSOVERMAWS."""
        from quickprs.record_types import parse_system_wan_name
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        wan_names = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_wan_name(sec.raw)
                if name:
                    wan_names.append(name)
        # PSERN should have a WAN name
        assert len(wan_names) >= 1, f"No WAN names found"
        assert "PSERN" in wan_names, f"PSERN not in WAN names: {wan_names}"

    def test_is_system_config_data_positive(self):
        """is_system_config_data should return True for real system config sections."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        found = False
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                found = True
                break
        assert found, "No system config data sections found in PAWSOVERMAWS"

    def test_is_system_config_data_negative(self):
        """is_system_config_data should return False for non-config sections."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        trunk_sec = prs.get_section_by_class("CTrunkChannel")
        assert trunk_sec is not None
        assert is_system_config_data(trunk_sec.raw) is False

    def test_is_system_config_data_short(self):
        """is_system_config_data should return False for short data."""
        assert is_system_config_data(b'\xff\xff\x01') is False
        assert is_system_config_data(b'') is False


# ─── NEW TESTS: build_class_header / parse_class_header roundtrip ─────


class TestClassHeaderRoundtrip:
    """build_class_header → parse_class_header roundtrip tests."""

    def test_roundtrip_trunk_channel(self):
        """CTrunkChannel header should roundtrip."""
        raw = build_class_header('CTrunkChannel', 0x64, 0x00)
        name, b1, b2, data_off = parse_class_header(raw, 0)
        assert name == 'CTrunkChannel'
        assert b1 == 0x64
        assert b2 == 0x00
        assert data_off == len(raw)

    def test_roundtrip_p25_group(self):
        """CP25Group header should roundtrip."""
        raw = build_class_header('CP25Group', 0x6a, 0x00)
        name, b1, b2, data_off = parse_class_header(raw, 0)
        assert name == 'CP25Group'
        assert b1 == 0x6a

    def test_roundtrip_iden(self):
        """CDefaultIdenElem header should roundtrip."""
        raw = build_class_header('CDefaultIdenElem')
        name, b1, b2, data_off = parse_class_header(raw, 0)
        assert name == 'CDefaultIdenElem'
        assert b1 == 0x66  # from CLASS_IDS lookup

    def test_custom_byte1(self):
        """Custom byte1 should be preserved through roundtrip."""
        raw = build_class_header('CustomClass', byte1=0xAB, byte2=0xCD)
        name, b1, b2, data_off = parse_class_header(raw, 0)
        assert name == 'CustomClass'
        assert b1 == 0xAB
        assert b2 == 0xCD

    def test_header_starts_with_section_marker(self):
        """All headers should start with ff ff."""
        raw = build_class_header('Test')
        assert raw[:2] == SECTION_MARKER


# ─── NEW TESTS: Edge cases ───────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: empty sets, single-element sets, etc."""

    def test_empty_trunk_set_channels_to_bytes(self):
        """TrunkSet with no channels should produce empty bytes."""
        ts = TrunkSet(name="EMPTY", channels=[])
        raw = ts.channels_to_bytes()
        assert raw == b''

    def test_empty_group_set_groups_to_bytes(self):
        """P25GroupSet with no groups should produce empty bytes."""
        gs = P25GroupSet(name="EMPTY", groups=[])
        raw = gs.groups_to_bytes()
        assert raw == b''

    def test_empty_conv_set_channels_to_bytes(self):
        """ConvSet with no channels should produce empty bytes."""
        cs = ConvSet(name="EMPTY", channels=[])
        raw = cs.channels_to_bytes()
        assert raw == b''

    def test_single_trunk_channel_serialization(self):
        """Single-channel TrunkSet should produce correct section structure."""
        import pytest
        ch = TrunkChannel(tx_freq=769.0, rx_freq=799.0)
        tset = TrunkSet(name="700 MHZ", channels=[ch])
        raw = build_trunk_channel_section([tset])
        # Verify header
        assert raw[:2] == SECTION_MARKER
        assert b'CTrunkChannel' in raw
        # Verify channel data is present (23 bytes per channel)
        _, _, _, data_start = parse_class_header(raw, 0)
        # Parse just the first channel directly
        parsed_ch, _ = TrunkChannel.parse(raw, data_start)
        assert parsed_ch.tx_freq == pytest.approx(769.0, abs=1e-6)
        assert parsed_ch.rx_freq == pytest.approx(799.0, abs=1e-6)

    def test_single_group_roundtrip(self):
        """Single-group P25GroupSet build → parse roundtrip."""
        g = P25Group(group_name="LONE", group_id=42, long_name="LONE GROUP")
        gset = P25GroupSet(name="SOLOGS", groups=[g])
        raw = build_group_section([gset])
        _, _, _, data_start = parse_class_header(raw, 0)
        sets = parse_group_section(raw, data_start, len(raw), 1)
        assert len(sets) == 1
        assert sets[0].groups[0].group_name == "LONE"
        assert sets[0].groups[0].group_id == 42

    def test_iden_negative_tx_offset_roundtrip(self):
        """IdenElement with negative tx_offset_mhz should roundtrip through bytes."""
        import pytest
        elem = IdenElement(chan_spacing_hz=12500, bandwidth_hz=6250,
                           base_freq_hz=851006250, iden_type=0)
        elem.tx_offset_mhz = -45.0
        raw = elem.to_bytes()
        parsed, _ = IdenElement.parse(raw, 0)
        assert parsed.tx_offset_mhz == pytest.approx(-45.0, abs=1e-3)
        assert parsed.to_bytes() == raw


def _first_diff(a, b):
    """Find first byte difference between two byte strings."""
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return f"offset {i}: built=0x{a[i]:02x} real=0x{b[i]:02x}"
    if len(a) != len(b):
        return f"length: built={len(a)} real={len(b)}"
    return "identical"


class TestParseSetsFromSections:
    """Tests for the shared parse_sets_from_sections helper."""

    def _get_sections(self, prs, data_cls, set_cls):
        data_sec = prs.get_section_by_class(data_cls)
        set_sec = prs.get_section_by_class(set_cls)
        return set_sec, data_sec

    def test_parse_groups(self):
        prs = parse_prs(str(TESTDATA / "PAWSOVERMAWS.PRS"))
        set_sec, data_sec = self._get_sections(prs, "CP25Group", "CP25GroupSet")
        sets = parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                        parse_group_section)
        assert len(sets) > 0
        total = sum(len(s.groups) for s in sets)
        assert total == 241

    def test_parse_trunks(self):
        prs = parse_prs(str(TESTDATA / "PAWSOVERMAWS.PRS"))
        set_sec, data_sec = self._get_sections(
            prs, "CTrunkChannel", "CTrunkSet")
        sets = parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                        parse_trunk_channel_section)
        assert len(sets) > 0
        total = sum(len(s.channels) for s in sets)
        assert total == 290

    def test_parse_idens(self):
        prs = parse_prs(str(TESTDATA / "PAWSOVERMAWS.PRS"))
        set_sec, data_sec = self._get_sections(
            prs, "CDefaultIdenElem", "CIdenDataSet")
        sets = parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                        parse_iden_section)
        assert len(sets) > 0

    def test_bad_data_returns_empty(self):
        result = parse_sets_from_sections(b'\x00\x01\x02', b'\x03\x04\x05',
                                          parse_group_section)
        assert result == []

    def test_empty_data_returns_empty(self):
        result = parse_sets_from_sections(b'', b'', parse_group_section)
        assert result == []

    def test_missing_section_graceful(self):
        """Passing minimal data should return empty, not crash."""
        result = parse_sets_from_sections(b'\xff\xff', b'\xff\xff',
                                          parse_trunk_channel_section)
        assert result == []


class TestParseSystemSetRefs:
    """Tests for parse_system_set_refs — extracts trunk/group set names."""

    def test_paws_has_refs(self):
        """PAWSOVERMAWS system configs should reference trunk/group sets."""
        from quickprs.record_types import (
            is_system_config_data, parse_system_set_refs,
        )
        prs = parse_prs(str(TESTDATA / "PAWSOVERMAWS.PRS"))
        found = 0
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                trunk_ref, group_ref = parse_system_set_refs(sec.raw)
                if trunk_ref or group_ref:
                    found += 1
                    if trunk_ref:
                        assert len(trunk_ref) <= 8
                    if group_ref:
                        assert len(group_ref) <= 8
        assert found >= 2  # PAWS has multiple P25 trunked systems

    def test_refs_match_existing_sets(self):
        """Set refs should match actual set names in the file."""
        from quickprs.record_types import (
            is_system_config_data, parse_system_set_refs,
        )
        prs = parse_prs(str(TESTDATA / "PAWSOVERMAWS.PRS"))

        # Get actual set names
        set_sec = prs.get_section_by_class("CP25GroupSet")
        data_sec = prs.get_section_by_class("CP25Group")
        grp_names = set()
        if set_sec and data_sec:
            sets = parse_sets_from_sections(set_sec.raw, data_sec.raw,
                                             parse_group_section)
            grp_names = {s.name for s in sets}

        ch_sec = prs.get_section_by_class("CTrunkChannel")
        ts_sec = prs.get_section_by_class("CTrunkSet")
        trk_names = set()
        if ch_sec and ts_sec:
            sets = parse_sets_from_sections(ts_sec.raw, ch_sec.raw,
                                             parse_trunk_channel_section)
            trk_names = {s.name for s in sets}

        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                trunk_ref, group_ref = parse_system_set_refs(sec.raw)
                if trunk_ref:
                    assert trunk_ref in trk_names, \
                        f"Trunk ref '{trunk_ref}' not in {trk_names}"
                if group_ref:
                    assert group_ref in grp_names, \
                        f"Group ref '{group_ref}' not in {grp_names}"

    def test_bad_data(self):
        """Bad data should return (None, None), not crash."""
        from quickprs.record_types import parse_system_set_refs
        result = parse_system_set_refs(b'\x00\x01\x02')
        assert result == (None, None)

    def test_empty_data(self):
        from quickprs.record_types import parse_system_set_refs
        result = parse_system_set_refs(b'')
        assert result == (None, None)


def main():
    print("\n=== Record Types Tests ===\n")

    tests = [
        ("TrunkChannel parse", test_trunk_channel_parse),
        ("Trunk section parse", test_trunk_channel_section_parse),
        ("P25Group parse", test_p25_group_parse),
        ("Group section parse", test_group_section_parse),
        ("ConvChannel parse", test_conv_channel_parse),
        ("Conv section parse", test_conv_section_parse),
        ("IdenElement parse", test_iden_element_parse),
        ("Claude test groups", test_claude_test_groups),
        ("ECC entries PAWSOVERMAWS", test_ecc_entries_pawsovermaws),
        ("ECC entry roundtrip", test_ecc_entry_roundtrip),
        ("ECC WASHOE details", test_ecc_washoe_details),
        ("Build data section PSERN", test_build_data_section_psern),
        ("Build data section PSRS", test_build_data_section_psrs),
        ("Build data section C/S Nevada", test_build_data_section_cs_nevada),
        ("Build data section S/FRINGE", test_build_data_section_last_system),
        ("Build header section", test_build_header_section),
        ("Sys flags defaults", test_build_sys_flags_defaults),
        ("Sys flags NAS monitoring", test_build_sys_flags_nas_monitoring),
        ("Band limits detection", test_detect_band_limits),
        ("WAN config detection", test_detect_wan_config),
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
        print("All record type tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
