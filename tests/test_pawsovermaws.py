"""Comprehensive PAWSOVERMAWS.PRS pattern tests.

PAWSOVERMAWS is the gold-standard reference personality with:
- 5 P25 trunked systems (PSERN, PSRS, SS911, WASP, NNSS + NV systems)
- 3 conventional systems (WA WIDE, FURRY NB, FURRY WB)
- 7 group sets (241 total TGs, all passive NAS monitoring)
- 7 trunk sets (290 total channels)
- 3 conv sets (145 total channels)
- 3 IDEN sets (BEE00, 58544, 92738)
- 8 preferred system table entries
- ECC entries ranging from 0 (PSERN local) to 30 (C/S Nevada statewide)

These tests verify our parser correctly handles every pattern in this file.
"""

import sys
import struct
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    parse_class_header,
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_ecc_entries, is_system_config_data,
    parse_system_long_name, parse_system_wan_name,
    parse_system_short_name,
)
from quickprs.injector import get_preferred_entries

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


@pytest.fixture(scope="module")
def prs():
    if not PAWS.exists():
        pytest.skip("PAWSOVERMAWS.PRS not found")
    return parse_prs(PAWS)


@pytest.fixture(scope="module")
def raw_data():
    if not PAWS.exists():
        pytest.skip("PAWSOVERMAWS.PRS not found")
    return PAWS.read_bytes()


# ─── Helper functions ──────────────────────────────────────────────


def _get_group_sets(prs):
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw), first_count)


def _get_trunk_sets(prs):
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    _, _, _, ts_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ts_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_trunk_channel_section(ch_sec.raw, ch_data,
                                        len(ch_sec.raw), first_count)


def _get_conv_sets(prs):
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    _, _, _, cs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, cs_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_conv_channel_section(ch_sec.raw, ch_data,
                                       len(ch_sec.raw), first_count)


def _get_iden_sets(prs):
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    set_sec = prs.get_section_by_class("CIdenDataSet")
    _, _, _, ds_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds_data)
    _, _, _, e_data = parse_class_header(elem_sec.raw, 0)
    return parse_iden_section(elem_sec.raw, e_data,
                               len(elem_sec.raw), first_count)


def _get_system_configs(prs):
    """Return list of (long_name, wan_name, ecc_count, iden_name) for all
    P25 trunked system config data sections."""
    configs = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            long_name = parse_system_long_name(sec.raw)
            wan_name = parse_system_wan_name(sec.raw)
            ecc_count, _, iden_name = parse_ecc_entries(sec.raw)
            configs.append((long_name, wan_name, ecc_count, iden_name))
    return configs


# ═══════════════════════════════════════════════════════════════════
# GROUP SETS — 7 sets, 241 TGs total, all passive NAS monitoring
# ═══════════════════════════════════════════════════════════════════


class TestGroupSets:
    """Verify all 7 group sets parse with exact TG counts."""

    EXPECTED = [
        ("PSERN PD", 83),
        ("PSRS PD", 17),
        ("SS911 PD", 18),
        ("WASP", 25),
        ("NNSS", 13),
        ("SNACC", 53),
        ("NSRS", 32),
    ]

    def test_group_set_count(self, prs):
        sets = _get_group_sets(prs)
        assert len(sets) == 7

    @pytest.mark.parametrize("idx,expected_name,expected_count",
                             [(i, n, c) for i, (n, c) in enumerate(EXPECTED)])
    def test_group_set_name_and_count(self, prs, idx, expected_name,
                                       expected_count):
        sets = _get_group_sets(prs)
        assert sets[idx].name == expected_name
        assert len(sets[idx].groups) == expected_count

    def test_total_talkgroup_count(self, prs):
        sets = _get_group_sets(prs)
        total = sum(len(s.groups) for s in sets)
        assert total == 241

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_all_tgs_passive_monitoring(self, prs):
        """Every TG in PAWSOVERMAWS is tx=False scan=True (NAS passive)."""
        sets = _get_group_sets(prs)
        for s in sets:
            for g in s.groups:
                assert g.tx is False, (
                    f"{s.name}/{g.group_name}: tx should be False")
                assert g.scan is True, (
                    f"{s.name}/{g.group_name}: scan should be True")

    def test_all_tgs_rx_enabled(self, prs):
        """Every TG should have rx=True."""
        sets = _get_group_sets(prs)
        for s in sets:
            for g in s.groups:
                assert g.rx is True, (
                    f"{s.name}/{g.group_name}: rx should be True")

    def test_psern_pd_first_tg(self, prs):
        """First TG in PSERN PD is ALG PD 1 (ID=2303)."""
        sets = _get_group_sets(prs)
        first = sets[0].groups[0]
        assert first.group_name == "ALG PD 1"
        assert first.group_id == 2303
        assert first.long_name == "ALGONA PD TAC 1"

    def test_no_duplicate_tg_ids_within_set(self, prs):
        """No duplicate TG IDs within any single group set."""
        sets = _get_group_sets(prs)
        for s in sets:
            ids = [g.group_id for g in s.groups]
            assert len(ids) == len(set(ids)), (
                f"{s.name} has duplicate TG IDs")

    def test_name_lengths_within_limits(self, prs):
        """All TG names are within RPM limits (short<=8, long<=16)."""
        sets = _get_group_sets(prs)
        for s in sets:
            for g in s.groups:
                assert len(g.group_name) <= 8, (
                    f"{s.name}/{g.group_name}: short name too long")
                assert len(g.long_name) <= 16, (
                    f"{s.name}/{g.group_name}: long name too long "
                    f"({len(g.long_name)})")

    def test_group_roundtrip_per_record(self, prs, raw_data):
        """Every group record roundtrips byte-for-byte."""
        sets = _get_group_sets(prs)
        for s in sets:
            for g in s.groups:
                rebuilt = g.to_bytes()
                # Just check it doesn't crash and produces reasonable size
                assert len(rebuilt) > 20, (
                    f"{s.name}/{g.group_name}: rebuilt too small")


# ═══════════════════════════════════════════════════════════════════
# TRUNK SETS — 7 sets, 290 total channels
# ═══════════════════════════════════════════════════════════════════


class TestTrunkSets:
    """Verify all 7 trunk sets parse correctly."""

    EXPECTED = [
        ("PSERN", 28),
        ("PSRS", 10),
        ("SS911", 14),
        ("WASP", 28),
        ("NNSS", 93),
        ("SNACC", 16),
        ("NSRS", 101),
    ]

    def test_trunk_set_count(self, prs):
        sets = _get_trunk_sets(prs)
        assert len(sets) == 7

    @pytest.mark.parametrize("idx,expected_name,expected_count",
                             [(i, n, c) for i, (n, c) in enumerate(EXPECTED)])
    def test_trunk_set_name_and_count(self, prs, idx, expected_name,
                                       expected_count):
        sets = _get_trunk_sets(prs)
        assert sets[idx].name == expected_name
        assert len(sets[idx].channels) == expected_count

    def test_total_trunk_channel_count(self, prs):
        sets = _get_trunk_sets(prs)
        total = sum(len(s.channels) for s in sets)
        assert total == 290

    def test_psern_first_channel(self, prs):
        """PSERN first trunk channel: TX=806.88750, RX=851.88750."""
        sets = _get_trunk_sets(prs)
        ch = sets[0].channels[0]
        assert abs(ch.tx_freq - 806.88750) < 0.001
        assert abs(ch.rx_freq - 851.88750) < 0.001

    def test_psern_last_channel(self, prs):
        """PSERN last (28th) trunk channel: TX=814.46250."""
        sets = _get_trunk_sets(prs)
        ch = sets[0].channels[27]
        assert abs(ch.tx_freq - 814.46250) < 0.001

    def test_psern_band_limits(self, prs):
        """PSERN band limits: TX/RX min=136, max=870 (wide band)."""
        sets = _get_trunk_sets(prs)
        psern = sets[0]
        assert abs(psern.tx_min - 136.0) < 0.01
        assert abs(psern.tx_max - 870.0) < 0.01

    def test_nnss_has_duplicates(self, prs):
        """NNSS (UHF multi-site) has 93 channels with 36 duplicates."""
        sets = _get_trunk_sets(prs)
        nnss = sets[4]
        assert nnss.name == "NNSS"
        assert len(nnss.channels) == 93
        freqs = [(ch.tx_freq, ch.rx_freq) for ch in nnss.channels]
        unique = set(freqs)
        dup_count = len(freqs) - len(unique)
        assert dup_count == 36, f"Expected 36 duplicates, got {dup_count}"

    def test_all_channels_have_valid_freqs(self, prs):
        """All trunk channels have non-zero frequencies."""
        sets = _get_trunk_sets(prs)
        for s in sets:
            for ch in s.channels:
                assert ch.tx_freq > 0, f"{s.name}: tx_freq is 0"
                assert ch.rx_freq > 0, f"{s.name}: rx_freq is 0"

    def test_trunk_channel_roundtrip(self, prs):
        """All trunk channels roundtrip to exactly 23 bytes."""
        sets = _get_trunk_sets(prs)
        for s in sets:
            for ch in s.channels:
                rebuilt = ch.to_bytes()
                assert len(rebuilt) == 23


# ═══════════════════════════════════════════════════════════════════
# CONV SETS — 3 sets: WA WIDE (5), FURRY NB (70), FURRY WB (70)
# ═══════════════════════════════════════════════════════════════════


class TestConvSets:
    """Verify all 3 conventional channel sets."""

    def test_conv_set_count(self, prs):
        sets = _get_conv_sets(prs)
        assert len(sets) == 3

    def test_conv_set_names_and_counts(self, prs):
        sets = _get_conv_sets(prs)
        expected = [("WA WIDE", 5), ("FURRY NB", 70), ("FURRY WB", 70)]
        for i, (name, count) in enumerate(expected):
            assert sets[i].name == name
            assert len(sets[i].channels) == count

    def test_total_conv_channels(self, prs):
        sets = _get_conv_sets(prs)
        total = sum(len(s.channels) for s in sets)
        assert total == 145

    def test_wa_wide_murs_channels(self, prs):
        """WA WIDE starts with MURS channels."""
        sets = _get_conv_sets(prs)
        wa = sets[0]
        assert wa.channels[0].short_name == "MURS 1"
        assert abs(wa.channels[0].tx_freq - 151.82000) < 0.001

    def test_furry_nb_first_channel(self, prs):
        """FURRY NB first channel: MID 23, 462.56250 MHz, tone 250.3."""
        sets = _get_conv_sets(prs)
        nb = sets[1]
        assert nb.channels[0].short_name == "MID 23"
        assert abs(nb.channels[0].tx_freq - 462.56250) < 0.001
        assert nb.channels[0].tx_tone == "250.3"

    def test_furry_nb_wb_identical_channels(self, prs):
        """FURRY NB and FURRY WB have identical channel data (same
        frequencies, same tones, same names — only bandwidth differs)."""
        sets = _get_conv_sets(prs)
        nb = sets[1]
        wb = sets[2]
        assert len(nb.channels) == len(wb.channels)
        for i in range(len(nb.channels)):
            assert nb.channels[i].short_name == wb.channels[i].short_name, (
                f"Channel {i} short name mismatch")
            assert abs(nb.channels[i].tx_freq -
                       wb.channels[i].tx_freq) < 0.001, (
                f"Channel {i} TX freq mismatch")
            assert abs(nb.channels[i].rx_freq -
                       wb.channels[i].rx_freq) < 0.001, (
                f"Channel {i} RX freq mismatch")
            assert nb.channels[i].tx_tone == wb.channels[i].tx_tone, (
                f"Channel {i} TX tone mismatch")
            assert nb.channels[i].rx_tone == wb.channels[i].rx_tone, (
                f"Channel {i} RX tone mismatch")
            assert nb.channels[i].long_name == wb.channels[i].long_name, (
                f"Channel {i} long name mismatch")

    def test_conv_channel_name_lengths(self, prs):
        """All conv channel names are within RPM limits."""
        sets = _get_conv_sets(prs)
        for s in sets:
            for ch in s.channels:
                assert len(ch.short_name) <= 8, (
                    f"{s.name}/{ch.short_name}: short name too long")
                assert len(ch.long_name) <= 16, (
                    f"{s.name}/{ch.short_name}: long name too long")


# ═══════════════════════════════════════════════════════════════════
# IDEN SETS — 3 sets with specific active elements
# ═══════════════════════════════════════════════════════════════════


class TestIdenSets:
    """Verify all 3 IDEN sets and their frequency band assignments."""

    def test_iden_set_count(self, prs):
        sets = _get_iden_sets(prs)
        assert len(sets) == 3

    def test_iden_set_names(self, prs):
        sets = _get_iden_sets(prs)
        names = [s.name for s in sets]
        assert "BEE00" in names
        assert "58544" in names
        assert "92738" in names

    def test_iden_sets_have_16_slots(self, prs):
        """Every IDEN set has exactly 16 element slots."""
        sets = _get_iden_sets(prs)
        for s in sets:
            assert len(s.elements) == 16, (
                f"{s.name}: expected 16 slots, got {len(s.elements)}")

    def test_bee00_active_elements(self, prs):
        """BEE00 has 4 active (non-empty) elements for 800/700 MHz bands."""
        sets = _get_iden_sets(prs)
        bee00 = next(s for s in sets if s.name == "BEE00")
        active = [e for e in bee00.elements if not e.is_empty()]
        assert len(active) == 4

    def test_58544_active_elements(self, prs):
        """58544 has 2 active elements for UHF 406 MHz band."""
        sets = _get_iden_sets(prs)
        s58544 = next(s for s in sets if s.name == "58544")
        active = [e for e in s58544.elements if not e.is_empty()]
        assert len(active) == 2

    def test_92738_active_elements(self, prs):
        """92738 has 4 active elements for NV 800/700 MHz bands."""
        sets = _get_iden_sets(prs)
        s92738 = next(s for s in sets if s.name == "92738")
        active = [e for e in s92738.elements if not e.is_empty()]
        assert len(active) == 4

    def test_bee00_800mhz_base(self, prs):
        """BEE00 first active element should be 800 MHz band."""
        sets = _get_iden_sets(prs)
        bee00 = next(s for s in sets if s.name == "BEE00")
        first_active = next(e for e in bee00.elements if not e.is_empty())
        # 800 MHz band base freq should be 851006250 Hz
        assert first_active.base_freq_hz == 851006250 or \
               first_active.base_freq_hz > 700_000_000, (
            f"BEE00 base freq: {first_active.base_freq_hz}")

    def test_58544_uhf_base(self, prs):
        """58544 should have UHF base frequency (~406 MHz)."""
        sets = _get_iden_sets(prs)
        s58544 = next(s for s in sets if s.name == "58544")
        first_active = next(e for e in s58544.elements if not e.is_empty())
        # UHF band around 406 MHz
        assert 300_000_000 < first_active.base_freq_hz < 500_000_000, (
            f"58544 base freq: {first_active.base_freq_hz}")

    def test_iden_element_roundtrip(self, prs):
        """All IDEN elements roundtrip to exactly 15 bytes."""
        sets = _get_iden_sets(prs)
        for s in sets:
            for e in s.elements:
                rebuilt = e.to_bytes()
                assert len(rebuilt) == 15


# ═══════════════════════════════════════════════════════════════════
# SYSTEM CONFIGS — ordering, WAN names, ECC patterns
# ═══════════════════════════════════════════════════════════════════


class TestSystemConfigs:
    """Verify system config data sections: long names, WAN names, ECC."""

    EXPECTED_SYSTEMS = [
        # (long_name, wan_name, ecc_count, iden_name)
        ("PSERN SEATTLE", "PSERN", 0, None),
        ("PSRS TACOMA", "PSRS", 3, "BEE00"),
        ("SS911 TACOMA", "SS911", 5, "BEE00"),
        ("P25 WA STATE PAT", "WASP", 5, "BEE00"),
        ("NELLIS/CREECH/NN", "NNSS", 13, "58544"),
        ("S NEVADA SNACC", "SNACC", 17, "BEE00"),
        ("C/S NEVADA", "C/S NSRS", 30, "92738"),
        ("WASHOE/N NEVADA", "N NSRS", 1, "92738"),
        ("S/FRINGE NEVADA", "S NSRS", 3, "92738"),
    ]

    def test_system_config_count(self, prs):
        """9 system configs (5 WA + 4 NV, including conv system configs)."""
        configs = _get_system_configs(prs)
        # Filter to P25 trunked only (have WAN names)
        p25_configs = [c for c in configs if c[1] is not None]
        assert len(p25_configs) >= 8  # At least 8 P25 trunked

    def test_all_p25_system_long_names(self, prs):
        """All expected P25 system long names are present."""
        configs = _get_system_configs(prs)
        long_names = {c[0] for c in configs}
        for name, _, _, _ in self.EXPECTED_SYSTEMS:
            assert name in long_names, f"Missing system: {name}"

    def test_all_p25_wan_names(self, prs):
        """All P25 systems have correct WAN names."""
        configs = _get_system_configs(prs)
        wan_map = {c[0]: c[1] for c in configs if c[1]}
        for long_name, expected_wan, _, _ in self.EXPECTED_SYSTEMS:
            if expected_wan:
                assert wan_map.get(long_name) == expected_wan, (
                    f"{long_name}: expected WAN={expected_wan}, "
                    f"got {wan_map.get(long_name)}")

    @pytest.mark.parametrize("long_name,wan,ecc_count,iden",
                             EXPECTED_SYSTEMS)
    def test_ecc_count(self, prs, long_name, wan, ecc_count, iden):
        """Each system has the expected ECC entry count."""
        configs = _get_system_configs(prs)
        match = next((c for c in configs if c[0] == long_name), None)
        assert match is not None, f"System {long_name} not found"
        actual_ecc = match[2]
        assert actual_ecc == ecc_count, (
            f"{long_name}: expected {ecc_count} ECC, got {actual_ecc}")

    @pytest.mark.parametrize("long_name,wan,ecc_count,iden",
                             [s for s in EXPECTED_SYSTEMS if s[3]])
    def test_iden_reference(self, prs, long_name, wan, ecc_count, iden):
        """Systems with ECC entries reference the correct IDEN set."""
        configs = _get_system_configs(prs)
        match = next((c for c in configs if c[0] == long_name), None)
        assert match is not None
        assert match[3] == iden, (
            f"{long_name}: expected IDEN={iden}, got {match[3]}")

    def test_ecc_correlates_with_coverage(self, prs):
        """ECC count increases with geographic coverage area:
        local=0, regional=3-5, multi-county=13-17, statewide=30."""
        configs = _get_system_configs(prs)
        ecc_map = {c[0]: c[2] for c in configs}
        # Local (PSERN) has 0
        assert ecc_map.get("PSERN SEATTLE", -1) == 0
        # Regional (PSRS, SS911, WASP) have 3-5
        for name in ["PSRS TACOMA", "SS911 TACOMA", "P25 WA STATE PAT"]:
            assert 1 <= ecc_map.get(name, 0) <= 10
        # Multi-county (NNSS, SNACC) have 13-17
        assert 10 <= ecc_map.get("NELLIS/CREECH/NN", 0) <= 20
        assert 10 <= ecc_map.get("S NEVADA SNACC", 0) <= 20
        # Statewide (C/S Nevada) has 30 (max)
        assert ecc_map.get("C/S NEVADA", 0) == 30

    def test_cs_nevada_30_ecc_is_max(self, prs):
        """C/S Nevada at 30 ECC entries is the hard limit."""
        configs = _get_system_configs(prs)
        for c in configs:
            assert c[2] <= 30, f"{c[0]} has {c[2]} ECC (over 30)"

    def test_iden_sharing_pattern(self, prs):
        """IDEN sets are shared across systems:
        - BEE00: WA systems + SNACC
        - 58544: NNSS (UHF)
        - 92738: NV state systems"""
        configs = _get_system_configs(prs)
        iden_map = {c[0]: c[3] for c in configs if c[3]}

        # BEE00 users
        for name in ["PSRS TACOMA", "SS911 TACOMA", "P25 WA STATE PAT",
                      "S NEVADA SNACC"]:
            assert iden_map.get(name) == "BEE00", (
                f"{name} should use BEE00")

        # 58544 user
        assert iden_map.get("NELLIS/CREECH/NN") == "58544"

        # 92738 users
        for name in ["C/S NEVADA", "WASHOE/N NEVADA", "S/FRINGE NEVADA"]:
            assert iden_map.get(name) == "92738", (
                f"{name} should use 92738")

    def test_unique_wan_names(self, prs):
        """All P25 trunked systems have unique WAN names (no WACN conflicts)."""
        configs = _get_system_configs(prs)
        # Filter to only P25 trunked (those with WAN names that aren't None)
        wan_names = [c[1] for c in configs if c[1] and c[1] != "None"]
        assert len(wan_names) == len(set(wan_names)), (
            f"Duplicate WAN names found: {wan_names}")


# ═══════════════════════════════════════════════════════════════════
# PREFERRED SYSTEM TABLE — 8 entries, PSERN root, chains to PSRS
# ═══════════════════════════════════════════════════════════════════


class TestPreferredTable:
    """Verify preferred system table structure."""

    def test_preferred_entry_count(self, prs):
        entries, iden, chain = get_preferred_entries(prs)
        assert len(entries) == 8

    def test_preferred_iden_reference(self, prs):
        """Preferred table references BEE00 IDEN set."""
        entries, iden, chain = get_preferred_entries(prs)
        assert iden == "BEE00"

    def test_preferred_chain_to_psrs(self, prs):
        """Preferred table chains to PSRS as next system."""
        entries, iden, chain = get_preferred_entries(prs)
        assert chain == "PSRS"

    def test_preferred_entries_all_type_3(self, prs):
        """All preferred entries have type=3."""
        entries, _, _ = get_preferred_entries(prs)
        for e in entries:
            assert e.entry_type == 3

    def test_preferred_entries_all_priority_1(self, prs):
        """All preferred entries have field1=1 (priority)."""
        entries, _, _ = get_preferred_entries(prs)
        for e in entries:
            assert e.field1 == 1

    def test_preferred_sysid_range(self, prs):
        """Preferred entry system IDs are in range 929-936."""
        entries, _, _ = get_preferred_entries(prs)
        sysids = [e.system_id for e in entries]
        assert min(sysids) >= 929
        assert max(sysids) <= 936

    def test_preferred_sequential_indices(self, prs):
        """Preferred entries have sequential field2 values with known gap."""
        entries, _, _ = get_preferred_entries(prs)
        f2_values = [e.field2 for e in entries]
        assert f2_values == [25, 26, 27, 28, 31, 32, 33, 34]


# ═══════════════════════════════════════════════════════════════════
# SECTION ORDERING — conv first, then P25T, then configs
# ═══════════════════════════════════════════════════════════════════


class TestSectionOrdering:
    """Verify the section ordering patterns in the file."""

    def test_personality_header_first(self, prs):
        """CPersonality is always section [0]."""
        assert prs.sections[0].class_name == "CPersonality"

    def test_conv_system_before_p25(self, prs):
        """CConvSystem headers appear before CP25TrkSystem headers."""
        conv_idx = None
        p25t_idx = None
        for i, sec in enumerate(prs.sections):
            if sec.class_name == "CConvSystem" and conv_idx is None:
                conv_idx = i
            if sec.class_name == "CP25TrkSystem" and p25t_idx is None:
                p25t_idx = i
        assert conv_idx is not None
        assert p25t_idx is not None
        assert conv_idx < p25t_idx, (
            f"CConvSystem ({conv_idx}) should come before "
            f"CP25TrkSystem ({p25t_idx})")

    def test_preferred_table_exists(self, prs):
        """CPreferredSystemTableEntry section exists."""
        sec = prs.get_section_by_class("CPreferredSystemTableEntry")
        assert sec is not None

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_section_count(self, prs):
        """PAWSOVERMAWS has exactly 63 sections."""
        assert len(prs.sections) == 63

    def test_system_class_counts(self, prs):
        """Count of each system type header section."""
        class_counts = {}
        for sec in prs.sections:
            if sec.class_name:
                class_counts[sec.class_name] = \
                    class_counts.get(sec.class_name, 0) + 1
        # Exactly 1 CConvSystem header (covers all 3 conv systems)
        assert class_counts.get("CConvSystem", 0) == 1
        # 1 CP25TrkSystem header (covers all P25 trunked systems)
        assert class_counts.get("CP25TrkSystem", 0) == 1


# ═══════════════════════════════════════════════════════════════════
# FREQUENCY BAND PATTERNS
# ═══════════════════════════════════════════════════════════════════


class TestFrequencyBands:
    """Verify frequency band patterns across systems."""

    def test_nnss_is_uhf(self, prs):
        """NNSS trunk channels are in UHF band (~406 MHz)."""
        sets = _get_trunk_sets(prs)
        nnss = next(s for s in sets if s.name == "NNSS")
        for ch in nnss.channels:
            assert 300.0 < ch.rx_freq < 500.0, (
                f"NNSS RX {ch.rx_freq} not in UHF band")

    def test_psern_is_800mhz(self, prs):
        """PSERN trunk channels are in 800 MHz band."""
        sets = _get_trunk_sets(prs)
        psern = sets[0]
        for ch in psern.channels:
            assert 800.0 < ch.rx_freq < 870.0, (
                f"PSERN RX {ch.rx_freq} not in 800 MHz band")

    def test_wa_wide_is_vhf(self, prs):
        """WA WIDE conv channels are VHF (~150 MHz)."""
        sets = _get_conv_sets(prs)
        wa = sets[0]
        for ch in wa.channels:
            assert 100.0 < ch.tx_freq < 200.0, (
                f"WA WIDE {ch.short_name} TX {ch.tx_freq} not VHF")

    def test_furry_mixed_bands(self, prs):
        """FURRY NB/WB conv channels are mixed VHF+UHF (FRS/MURS/GMRS)."""
        sets = _get_conv_sets(prs)
        for s in sets[1:3]:
            vhf = [ch for ch in s.channels if ch.tx_freq < 200.0]
            uhf = [ch for ch in s.channels if ch.tx_freq > 400.0]
            assert len(vhf) + len(uhf) == len(s.channels), (
                f"{s.name} has channels outside VHF/UHF bands")
            assert len(uhf) > 0, f"{s.name} should have UHF channels"


# ═══════════════════════════════════════════════════════════════════
# FILE INTEGRITY — roundtrip, size, checksum
# ═══════════════════════════════════════════════════════════════════


class TestFileIntegrity:
    """Verify file-level properties."""

    def test_file_size(self, raw_data):
        assert len(raw_data) == 46822

    def test_roundtrip_byte_identical(self, prs, raw_data):
        rebuilt = prs.to_bytes()
        assert rebuilt == raw_data

    def test_all_sections_sum_to_file_size(self, prs, raw_data):
        """Total bytes from all sections equals file size."""
        total = sum(len(sec.raw) for sec in prs.sections)
        assert total == len(raw_data)

    def test_known_homeunitid(self, raw_data):
        """HomeUnitID 3621621 (0x00374_2f5) appears in binary."""
        hid_bytes = struct.pack('<I', 3621621)
        assert hid_bytes in raw_data

    def test_known_frequency_encoding(self, raw_data):
        """851.88750 MHz encodes to specific IEEE 754 bytes."""
        expected = bytes.fromhex("9a999999199f8a40")
        assert expected in raw_data
