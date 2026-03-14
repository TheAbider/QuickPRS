"""Tests for P25 encryption key management, NAC editing, and scan priority.

Feature 1: Encryption — set/clear encrypted flag and key_id on talkgroups
Feature 2: NAC — set Network Access Code on P25 conventional channels
Feature 3: Scan priority — reorder CPreferredSystemTableEntry entries
"""

import sys
import struct
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from quickprs.prs_parser import parse_prs
from quickprs.prs_writer import write_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    P25Group, P25GroupSet, PreferredSystemEntry,
    parse_class_header, parse_group_section,
    build_group_section,
    parse_preferred_section, build_preferred_section,
    P25ConvChannel, P25ConvSet,
    parse_p25_conv_channel_section, build_p25_conv_channel_section,
)
from quickprs.injector import (
    set_talkgroup_encryption,
    set_p25_conv_nac,
    reorder_preferred_entries,
    get_preferred_entries,
    add_talkgroups,
    make_p25_group,
)

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Encryption
# ═══════════════════════════════════════════════════════════════════

class TestEncryptionDataclass:
    """Test P25Group encrypted/key_id field behavior."""

    def test_default_not_encrypted(self):
        g = P25Group(group_name="TEST", group_id=1)
        assert g.encrypted is False
        assert g.key_id == 0

    def test_set_encrypted(self):
        g = P25Group(group_name="TEST", group_id=1)
        g.encrypted = True
        g.key_id = 5
        assert g.encrypted is True
        assert g.key_id == 5

    def test_tail_reflects_encrypted(self):
        g = P25Group(group_name="TEST", group_id=1, encrypted=True)
        assert g.tail[1] == 1

    def test_tail_reflects_not_encrypted(self):
        g = P25Group(group_name="TEST", group_id=1, encrypted=False)
        assert g.tail[1] == 0

    def test_middle_reflects_key_id(self):
        g = P25Group(group_name="TEST", group_id=1, key_id=42)
        key_id = struct.unpack_from('<I', g.middle, 5)[0]
        assert key_id == 42

    def test_middle_reflects_key_id_zero(self):
        g = P25Group(group_name="TEST", group_id=1, key_id=0)
        key_id = struct.unpack_from('<I', g.middle, 5)[0]
        assert key_id == 0

    def test_encrypted_roundtrip_bytes(self):
        g = P25Group(group_name="SECGRP", group_id=100,
                     encrypted=True, key_id=7)
        raw = g.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.encrypted is True
        assert parsed.key_id == 7
        assert parsed.to_bytes() == raw

    def test_unencrypted_roundtrip_bytes(self):
        g = P25Group(group_name="OPEN", group_id=200,
                     encrypted=False, key_id=0)
        raw = g.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.encrypted is False
        assert parsed.key_id == 0
        assert parsed.to_bytes() == raw

    def test_large_key_id(self):
        g = P25Group(group_name="BIGKEY", group_id=300,
                     encrypted=True, key_id=0xFFFFFFFF)
        raw = g.to_bytes()
        parsed, _ = P25Group.parse(raw, 0)
        assert parsed.key_id == 0xFFFFFFFF


class TestEncryptionInjector:
    """Test set_talkgroup_encryption() injector function."""

    @pytest.fixture
    def prs_with_groups(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        return deepcopy(parse_prs(CLAUDE))

    def _get_group_sets(self, prs):
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            return []
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(grp_sec.raw, 0)
        return parse_group_section(grp_sec.raw, cd, len(grp_sec.raw), fc)

    def test_encrypt_all_tgs(self, prs_with_groups):
        prs = prs_with_groups
        sets = self._get_group_sets(prs)
        if not sets:
            pytest.skip("no group sets")
        set_name = sets[0].name

        count = set_talkgroup_encryption(prs, set_name,
                                          encrypted=True, key_id=3)
        assert count == len(sets[0].groups)

        # Verify in rebuilt section
        new_sets = self._get_group_sets(prs)
        for g in new_sets[0].groups:
            assert g.encrypted is True
            assert g.key_id == 3

    def test_encrypt_single_tg(self, prs_with_groups):
        prs = prs_with_groups
        sets = self._get_group_sets(prs)
        if not sets or not sets[0].groups:
            pytest.skip("no group sets or groups")
        set_name = sets[0].name
        target_id = sets[0].groups[0].group_id

        count = set_talkgroup_encryption(prs, set_name,
                                          group_id=target_id,
                                          encrypted=True, key_id=1)
        assert count == 1

        new_sets = self._get_group_sets(prs)
        target = [g for g in new_sets[0].groups
                  if g.group_id == target_id][0]
        assert target.encrypted is True
        assert target.key_id == 1

        # Other TGs should be unchanged
        for g in new_sets[0].groups:
            if g.group_id != target_id:
                assert g.encrypted is False

    def test_decrypt_all(self, prs_with_groups):
        prs = prs_with_groups
        sets = self._get_group_sets(prs)
        if not sets:
            pytest.skip("no group sets")
        set_name = sets[0].name

        # First encrypt
        set_talkgroup_encryption(prs, set_name, encrypted=True, key_id=5)
        # Then decrypt
        count = set_talkgroup_encryption(prs, set_name,
                                          encrypted=False, key_id=0)
        assert count == len(sets[0].groups)

        new_sets = self._get_group_sets(prs)
        for g in new_sets[0].groups:
            assert g.encrypted is False
            assert g.key_id == 0

    def test_encrypt_bad_set_name(self, prs_with_groups):
        with pytest.raises(ValueError, match="not found"):
            set_talkgroup_encryption(prs_with_groups, "NONEXIST",
                                      encrypted=True, key_id=1)

    def test_encrypt_bad_tg_id(self, prs_with_groups):
        prs = prs_with_groups
        sets = self._get_group_sets(prs)
        if not sets:
            pytest.skip("no group sets")
        with pytest.raises(ValueError, match="not found"):
            set_talkgroup_encryption(prs, sets[0].name,
                                      group_id=99999,
                                      encrypted=True, key_id=1)

    def test_encrypt_roundtrip_file(self, prs_with_groups, tmp_path):
        """Encrypt TGs, write to file, read back, verify."""
        prs = prs_with_groups
        sets = self._get_group_sets(prs)
        if not sets:
            pytest.skip("no group sets")
        set_name = sets[0].name

        set_talkgroup_encryption(prs, set_name, encrypted=True, key_id=7)

        out = tmp_path / "encrypted.PRS"
        write_prs(prs, str(out))

        prs2 = parse_prs(str(out))
        new_sets = self._get_group_sets(prs2)
        for g in new_sets[0].groups:
            assert g.encrypted is True
            assert g.key_id == 7


class TestEncryptionGroupSection:
    """Test encryption fields survive group section rebuild."""

    def test_build_group_section_preserves_encryption(self):
        g1 = P25Group(group_name="CLEAR", group_id=100,
                      encrypted=False, key_id=0)
        g2 = P25Group(group_name="SECRET", group_id=200,
                      encrypted=True, key_id=42)
        gset = P25GroupSet(name="MIXED", groups=[g1, g2])

        raw = build_group_section([gset])
        _, _, _, ds = parse_class_header(raw, 0)
        parsed_sets = parse_group_section(raw, ds, len(raw), 2)

        assert len(parsed_sets) == 1
        assert parsed_sets[0].groups[0].encrypted is False
        assert parsed_sets[0].groups[0].key_id == 0
        assert parsed_sets[0].groups[1].encrypted is True
        assert parsed_sets[0].groups[1].key_id == 42


# ═══════════════════════════════════════════════════════════════════
# Feature 2: NAC
# ═══════════════════════════════════════════════════════════════════

class TestNACDataclass:
    """Test P25ConvChannel NAC field behavior."""

    def test_default_nac_zero(self):
        ch = P25ConvChannel(short_name="TEST", tx_freq=800.0, rx_freq=800.0)
        assert ch.nac_tx == 0
        assert ch.nac_rx == 0

    def test_set_nac(self):
        ch = P25ConvChannel(short_name="TEST", tx_freq=800.0, rx_freq=800.0,
                            nac_tx=0x293, nac_rx=0xF7E)
        assert ch.nac_tx == 0x293
        assert ch.nac_rx == 0xF7E

    def test_nac_in_bytes(self):
        ch = P25ConvChannel(short_name="TEST", tx_freq=800.0, rx_freq=800.0,
                            nac_tx=0x293, nac_rx=0x293)
        raw = ch.to_bytes()
        parsed, _ = P25ConvChannel.parse(raw, 0)
        assert parsed.nac_tx == 0x293
        assert parsed.nac_rx == 0x293

    def test_nac_max_value(self):
        ch = P25ConvChannel(short_name="TEST", tx_freq=800.0, rx_freq=800.0,
                            nac_tx=0xFFF, nac_rx=0xFFF)
        raw = ch.to_bytes()
        parsed, _ = P25ConvChannel.parse(raw, 0)
        assert parsed.nac_tx == 0xFFF
        assert parsed.nac_rx == 0xFFF

    def test_nac_roundtrip_bytes(self):
        ch = P25ConvChannel(short_name="P25CH", tx_freq=851.0, rx_freq=806.0,
                            nac_tx=0xF7F, nac_rx=0x000)
        raw = ch.to_bytes()
        parsed, _ = P25ConvChannel.parse(raw, 0)
        assert parsed.nac_tx == 0xF7F
        assert parsed.nac_rx == 0x000
        assert parsed.to_bytes() == raw


class TestNACInjector:
    """Test set_p25_conv_nac() injector function."""

    @pytest.fixture
    def prs_with_p25_conv(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        prs = parse_prs(CLAUDE)
        if not prs.get_section_by_class("CP25ConvChannel"):
            pytest.skip("no P25 conv channels")
        return deepcopy(prs)

    def _get_p25_conv_sets(self, prs):
        ch_sec = prs.get_section_by_class("CP25ConvChannel")
        set_sec = prs.get_section_by_class("CP25ConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        return parse_p25_conv_channel_section(ch_sec.raw, cd,
                                              len(ch_sec.raw), fc)

    def test_set_nac_both(self, prs_with_p25_conv):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        set_name = sets[0].name

        set_p25_conv_nac(prs, set_name, 0, nac_tx=0xF7E, nac_rx=0xF7E)

        new_sets = self._get_p25_conv_sets(prs)
        assert new_sets[0].channels[0].nac_tx == 0xF7E
        assert new_sets[0].channels[0].nac_rx == 0xF7E

    def test_set_nac_tx_only(self, prs_with_p25_conv):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        set_name = sets[0].name
        orig_rx = sets[0].channels[0].nac_rx

        set_p25_conv_nac(prs, set_name, 0, nac_tx=0x100)

        new_sets = self._get_p25_conv_sets(prs)
        assert new_sets[0].channels[0].nac_tx == 0x100
        assert new_sets[0].channels[0].nac_rx == orig_rx

    def test_set_nac_rx_only(self, prs_with_p25_conv):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        set_name = sets[0].name
        orig_tx = sets[0].channels[0].nac_tx

        set_p25_conv_nac(prs, set_name, 0, nac_rx=0x200)

        new_sets = self._get_p25_conv_sets(prs)
        assert new_sets[0].channels[0].nac_tx == orig_tx
        assert new_sets[0].channels[0].nac_rx == 0x200

    def test_set_nac_bad_set(self, prs_with_p25_conv):
        with pytest.raises(ValueError, match="not found"):
            set_p25_conv_nac(prs_with_p25_conv, "FAKE", 0, nac_tx=0x293)

    def test_set_nac_bad_channel_index(self, prs_with_p25_conv):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        with pytest.raises(ValueError, match="out of range"):
            set_p25_conv_nac(prs, sets[0].name, 999, nac_tx=0x293)

    def test_set_nac_out_of_range(self, prs_with_p25_conv):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        with pytest.raises(ValueError, match="out of range"):
            set_p25_conv_nac(prs, sets[0].name, 0, nac_tx=0x1000)

    def test_set_nac_roundtrip_file(self, prs_with_p25_conv, tmp_path):
        prs = prs_with_p25_conv
        sets = self._get_p25_conv_sets(prs)
        set_name = sets[0].name

        set_p25_conv_nac(prs, set_name, 0, nac_tx=0xABC, nac_rx=0xDEF)

        out = tmp_path / "nac_test.PRS"
        write_prs(prs, str(out))

        prs2 = parse_prs(str(out))
        new_sets = self._get_p25_conv_sets(prs2)
        assert new_sets[0].channels[0].nac_tx == 0xABC
        assert new_sets[0].channels[0].nac_rx == 0xDEF


class TestNACSectionRebuild:
    """Test NAC fields survive P25 conv section rebuild."""

    def test_build_p25_conv_preserves_nac(self):
        ch = P25ConvChannel(short_name="P25NAC", tx_freq=851.0, rx_freq=806.0,
                            nac_tx=0x293, nac_rx=0xF7F,
                            long_name="NAC TEST CH")
        cset = P25ConvSet(name="NACTEST", channels=[ch])

        raw = build_p25_conv_channel_section([cset])
        _, _, _, ds = parse_class_header(raw, 0)
        parsed = parse_p25_conv_channel_section(raw, ds, len(raw), 1)

        assert len(parsed) == 1
        assert parsed[0].channels[0].nac_tx == 0x293
        assert parsed[0].channels[0].nac_rx == 0xF7F


# ═══════════════════════════════════════════════════════════════════
# Feature 3: Scan Priority
# ═══════════════════════════════════════════════════════════════════

class TestScanPriorityDataclass:
    """Test PreferredSystemEntry behavior."""

    def test_default_values(self):
        e = PreferredSystemEntry()
        assert e.entry_type == 3
        assert e.system_id == 0
        assert e.field1 == 1
        assert e.field2 == 0

    def test_to_bytes_from_bytes_roundtrip(self):
        e = PreferredSystemEntry(entry_type=3, system_id=892,
                                  field1=1, field2=5)
        raw = e.to_bytes(is_last=True)
        parsed = PreferredSystemEntry.from_bytes(raw, 0)
        assert parsed.system_id == 892
        assert parsed.field1 == 1
        assert parsed.field2 == 5


class TestScanPriorityReorder:
    """Test reorder_preferred_entries() injector function."""

    @pytest.fixture
    def prs_with_preferred(self):
        if not PAWS.exists():
            pytest.skip("PAWSOVERMAWS not found")
        prs = parse_prs(PAWS)
        entries, _, _ = get_preferred_entries(prs)
        if len(entries) < 2:
            pytest.skip("need at least 2 preferred entries")
        return deepcopy(prs)

    def test_reorder_reverses(self, prs_with_preferred):
        prs = prs_with_preferred
        entries, _, _ = get_preferred_entries(prs)
        original_ids = [e.system_id for e in entries]

        reversed_ids = list(reversed(original_ids))
        result = reorder_preferred_entries(prs, reversed_ids)
        assert result is True

        new_entries, _, _ = get_preferred_entries(prs)
        new_ids = [e.system_id for e in new_entries]
        assert new_ids == reversed_ids

    def test_reorder_assigns_sequence(self, prs_with_preferred):
        prs = prs_with_preferred
        entries, _, _ = get_preferred_entries(prs)
        original_ids = [e.system_id for e in entries]

        # Same order, check field2 gets reassigned
        reorder_preferred_entries(prs, original_ids)
        new_entries, _, _ = get_preferred_entries(prs)
        for i, e in enumerate(new_entries):
            assert e.field2 == i

    def test_reorder_bad_count(self, prs_with_preferred):
        prs = prs_with_preferred
        entries, _, _ = get_preferred_entries(prs)
        with pytest.raises(ValueError, match="items"):
            reorder_preferred_entries(prs, [entries[0].system_id])

    def test_reorder_bad_sysid(self, prs_with_preferred):
        prs = prs_with_preferred
        entries, _, _ = get_preferred_entries(prs)
        bad = [99999] + [e.system_id for e in entries[1:]]
        with pytest.raises(ValueError, match="not found"):
            reorder_preferred_entries(prs, bad)

    def test_reorder_no_preferred(self):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        prs = deepcopy(parse_prs(CLAUDE))
        entries, _, _ = get_preferred_entries(prs)
        if entries:
            # claude test might have preferred entries
            result = reorder_preferred_entries(
                prs, [e.system_id for e in entries])
            assert result is True
        else:
            result = reorder_preferred_entries(prs, [])
            # No section = returns False
            assert result is False

    def test_reorder_roundtrip_file(self, prs_with_preferred, tmp_path):
        prs = prs_with_preferred
        entries, _, _ = get_preferred_entries(prs)
        reversed_ids = list(reversed([e.system_id for e in entries]))

        reorder_preferred_entries(prs, reversed_ids)

        out = tmp_path / "priority.PRS"
        write_prs(prs, str(out))

        prs2 = parse_prs(str(out))
        new_entries, _, _ = get_preferred_entries(prs2)
        new_ids = [e.system_id for e in new_entries]
        assert new_ids == reversed_ids


class TestScanPrioritySection:
    """Test preferred section build/parse with reordered entries."""

    def test_build_parse_roundtrip(self):
        e1 = PreferredSystemEntry(entry_type=3, system_id=100,
                                   field1=1, field2=0)
        e2 = PreferredSystemEntry(entry_type=3, system_id=200,
                                   field1=1, field2=1)
        e3 = PreferredSystemEntry(entry_type=4, system_id=300,
                                   field1=34, field2=2)

        raw = build_preferred_section([e1, e2, e3],
                                       iden_name="BEE00",
                                       chain_name="NEXT",
                                       chain_type=0x05)
        parsed, iden, tail, chain, ctype = parse_preferred_section(raw)

        assert len(parsed) == 3
        assert parsed[0].system_id == 100
        assert parsed[1].system_id == 200
        assert parsed[2].system_id == 300
        assert parsed[2].field1 == 34


# ═══════════════════════════════════════════════════════════════════
# CLI Tests
# ═══════════════════════════════════════════════════════════════════

class TestEncryptCLI:
    """Test the encrypt CLI subcommand."""

    @pytest.fixture
    def prs_file(self, tmp_path):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        dest = tmp_path / "encrypt_test.PRS"
        dest.write_bytes(CLAUDE.read_bytes())
        return str(dest)

    def test_encrypt_all(self, prs_file):
        from quickprs.cli import run_cli
        prs = parse_prs(prs_file)
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            pytest.skip("no group sets")

        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(grp_sec.raw, 0)
        sets = parse_group_section(grp_sec.raw, cd, len(grp_sec.raw), fc)
        if not sets:
            pytest.skip("no group sets")

        set_name = sets[0].name
        rc = run_cli(["encrypt", prs_file, "--set", set_name,
                      "--all", "--key-id", "5"])
        assert rc == 0

        prs2 = parse_prs(prs_file)
        grp_sec2 = prs2.get_section_by_class("CP25Group")
        set_sec2 = prs2.get_section_by_class("CP25GroupSet")
        _, _, _, ds2 = parse_class_header(set_sec2.raw, 0)
        fc2, _ = read_uint16_le(set_sec2.raw, ds2)
        _, _, _, cd2 = parse_class_header(grp_sec2.raw, 0)
        new_sets = parse_group_section(grp_sec2.raw, cd2,
                                        len(grp_sec2.raw), fc2)
        for g in new_sets[0].groups:
            assert g.encrypted is True
            assert g.key_id == 5

    def test_decrypt(self, prs_file):
        from quickprs.cli import run_cli
        prs = parse_prs(prs_file)
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if not grp_sec or not set_sec:
            pytest.skip("no group sets")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(grp_sec.raw, 0)
        sets = parse_group_section(grp_sec.raw, cd, len(grp_sec.raw), fc)
        if not sets:
            pytest.skip("no group sets")

        set_name = sets[0].name

        # Encrypt first
        run_cli(["encrypt", prs_file, "--set", set_name,
                 "--all", "--key-id", "1"])
        # Then decrypt
        rc = run_cli(["encrypt", prs_file, "--set", set_name,
                      "--all", "--decrypt"])
        assert rc == 0

    def test_encrypt_no_target(self, prs_file):
        from quickprs.cli import run_cli
        rc = run_cli(["encrypt", prs_file, "--set", "WHATEVER"])
        assert rc == 1  # need --tg or --all


class TestSetNacCLI:
    """Test the set-nac CLI subcommand."""

    @pytest.fixture
    def prs_file(self, tmp_path):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        prs = parse_prs(CLAUDE)
        if not prs.get_section_by_class("CP25ConvChannel"):
            pytest.skip("no P25 conv channels")
        dest = tmp_path / "nac_test.PRS"
        dest.write_bytes(CLAUDE.read_bytes())
        return str(dest)

    def test_set_nac_cli(self, prs_file):
        from quickprs.cli import run_cli
        prs = parse_prs(prs_file)
        ch_sec = prs.get_section_by_class("CP25ConvChannel")
        set_sec = prs.get_section_by_class("CP25ConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_p25_conv_channel_section(ch_sec.raw, cd,
                                              len(ch_sec.raw), fc)
        set_name = sets[0].name

        rc = run_cli(["set-nac", prs_file, "--set", set_name,
                      "--channel", "0", "--nac", "F7E"])
        assert rc == 0

        prs2 = parse_prs(prs_file)
        ch_sec2 = prs2.get_section_by_class("CP25ConvChannel")
        set_sec2 = prs2.get_section_by_class("CP25ConvSet")
        _, _, _, ds2 = parse_class_header(set_sec2.raw, 0)
        fc2, _ = read_uint16_le(set_sec2.raw, ds2)
        _, _, _, cd2 = parse_class_header(ch_sec2.raw, 0)
        new_sets = parse_p25_conv_channel_section(ch_sec2.raw, cd2,
                                                   len(ch_sec2.raw), fc2)
        assert new_sets[0].channels[0].nac_tx == 0xF7E
        assert new_sets[0].channels[0].nac_rx == 0xF7E

    def test_set_nac_split(self, prs_file):
        from quickprs.cli import run_cli
        prs = parse_prs(prs_file)
        ch_sec = prs.get_section_by_class("CP25ConvChannel")
        set_sec = prs.get_section_by_class("CP25ConvSet")
        _, _, _, ds = parse_class_header(set_sec.raw, 0)
        fc, _ = read_uint16_le(set_sec.raw, ds)
        _, _, _, cd = parse_class_header(ch_sec.raw, 0)
        sets = parse_p25_conv_channel_section(ch_sec.raw, cd,
                                              len(ch_sec.raw), fc)
        set_name = sets[0].name

        rc = run_cli(["set-nac", prs_file, "--set", set_name,
                      "--channel", "0", "--nac", "293", "--nac-rx", "F7F"])
        assert rc == 0

        prs2 = parse_prs(prs_file)
        ch_sec2 = prs2.get_section_by_class("CP25ConvChannel")
        set_sec2 = prs2.get_section_by_class("CP25ConvSet")
        _, _, _, ds2 = parse_class_header(set_sec2.raw, 0)
        fc2, _ = read_uint16_le(set_sec2.raw, ds2)
        _, _, _, cd2 = parse_class_header(ch_sec2.raw, 0)
        new_sets = parse_p25_conv_channel_section(ch_sec2.raw, cd2,
                                                   len(ch_sec2.raw), fc2)
        assert new_sets[0].channels[0].nac_tx == 0x293
        assert new_sets[0].channels[0].nac_rx == 0xF7F
