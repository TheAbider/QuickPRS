"""Integration tests — simulate real user workflows.

These tests chain multiple operations together to verify that the modules
interact correctly in real-world scenarios:
- Inject system -> validate -> compare before/after
- Add then remove systems (lifecycle)
- Hit XG-100P limits
- Multi-set batch operations
- Cross-file data extraction patterns
"""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs, parse_prs_bytes
from conftest import cached_parse_prs
from quickprs.prs_writer import write_prs
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    P25TrkSystemConfig, ConvSystemConfig, P25ConvSystemConfig,
    EnhancedCCEntry, P25GroupSet,
    parse_class_header, parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_system_long_name, is_system_config_data, parse_ecc_entries,
)
from quickprs.injector import (
    add_p25_trunked_system, add_conv_system, add_p25_conv_system,
    add_talkgroups, add_trunk_channels, add_group_set, add_trunk_set,
    add_conv_set, add_iden_set,
    remove_system_config, remove_system_by_class,
    make_p25_group, make_trunk_channel, make_trunk_set, make_group_set,
    make_iden_set, make_conv_set, make_conv_channel,
    get_preferred_entries, add_preferred_entries,
)
from quickprs.comparison import compare_prs, ADDED, REMOVED, CHANGED, SAME
from quickprs.validation import (
    validate_prs, validate_group_set, validate_prs_detailed,
    ERROR, WARNING, INFO,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _get_group_sets(prs):
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw),
                                first_count)


def _get_trunk_sets(prs):
    ch_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    _, _, _, ts_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ts_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_trunk_channel_section(ch_sec.raw, ch_data,
                                        len(ch_sec.raw), first_count)


# ═══════════════════════════════════════════════════════════════════
# Full system lifecycle: add → validate → compare → remove → roundtrip
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestSystemLifecycle:

    def test_add_validate_compare_remove(self):
        """Full lifecycle: inject P25 system, validate, compare, remove."""
        prs_original = cached_parse_prs(CLAUDE)
        prs_modified = cached_parse_prs(CLAUDE)

        # Step 1: Inject a complete P25 trunked system
        config = P25TrkSystemConfig(
            system_name="LIFECY",
            long_name="LIFECYCLE TEST",
            trunk_set_name="LIFECY",
            group_set_name="LIFECY",
            wan_name="LIFECY",
            home_unit_id=54321,
            system_id=0x42,
        )
        gset = make_group_set("LIFECY", [
            (100, "LIFE 1", "LIFECYCLE TG 1"),
            (200, "LIFE 2", "LIFECYCLE TG 2"),
            (300, "LIFE 3", "LIFECYCLE TG 3"),
        ])
        tset = make_trunk_set("LIFECY", [
            (851.0125, 806.0125),
            (851.5125, 806.5125),
        ])
        add_p25_trunked_system(prs_modified, config,
                                trunk_set=tset, group_set=gset)

        # Step 2: Validate — should pass without errors
        issues = validate_prs(prs_modified)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Step 3: Compare — should show additions
        diffs = compare_prs(prs_original, prs_modified)
        added = [d for d in diffs if d[0] == ADDED]
        assert len(added) > 0, "Should detect additions"
        assert any("LIFECYCLE" in d[2] or "LIFECY" in d[2]
                    for d in added)

        # Step 4: Remove the system config
        removed = remove_system_config(prs_modified, "LIFECYCLE TEST")
        assert removed is True

        # Step 5: Roundtrip the modified file
        modified_bytes = prs_modified.to_bytes()
        prs_reparsed = parse_prs_bytes(modified_bytes)
        assert prs_reparsed.to_bytes() == modified_bytes

    def test_add_conv_and_p25conv_systems(self):
        """Add both conventional and P25 conv systems."""
        prs = cached_parse_prs(CLAUDE)
        original_bytes = prs.to_bytes()

        # Add conventional analog system
        conv_config = ConvSystemConfig(
            system_name="ANALOG",
            long_name="ANALOG SYSTEM",
            conv_set_name="ANALOG",
        )
        cset = make_conv_set("ANALOG", [
            {'short_name': 'CH 1', 'tx_freq': 462.5625,
             'long_name': 'CHANNEL 1'},
        ])
        add_conv_system(prs, conv_config, conv_set=cset)

        # Add P25 conventional system
        p25conv_config = P25ConvSystemConfig(
            system_name="P25CONV",
            long_name="P25 CONV SYS",
            conv_set_name="P25CONV",
        )
        add_p25_conv_system(prs, p25conv_config)

        # Validate
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

        # Roundtrip
        modified = prs.to_bytes()
        assert len(modified) > len(original_bytes)
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    def test_multiple_systems_then_remove_one(self):
        """Add 3 systems, remove the middle one, verify others intact."""
        prs = cached_parse_prs(CLAUDE)

        names = ["ALPHA", "BRAVO", "CHARLI"]
        for name in names:
            config = P25TrkSystemConfig(
                system_name=name,
                long_name=f"{name} SYSTEM",
                trunk_set_name=name,
                group_set_name=name,
                wan_name=name,
            )
            gset = make_group_set(name, [(100, "TG 1", f"{name} TG")])
            tset = make_trunk_set(name, [(851.0125, 806.0125)])
            add_p25_trunked_system(prs, config,
                                    trunk_set=tset, group_set=gset)

        # Remove BRAVO
        removed = remove_system_config(prs, "BRAVO SYSTEM")
        assert removed is True

        # Verify ALPHA and CHARLI still exist
        configs = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name:
                    configs.append(name)
        assert "ALPHA SYSTEM" in configs
        assert "BRAVO SYSTEM" not in configs
        assert "CHARLI SYSTEM" in configs

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified


# ═══════════════════════════════════════════════════════════════════
# Stress tests — push limits
# ═══════════════════════════════════════════════════════════════════


class TestStressScenarios:

    def test_inject_127_scan_tgs_validates_clean(self):
        """Exactly 127 scan-enabled TGs should validate clean."""
        tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i:05d}") for i in range(127)]
        gset = make_group_set("MAXSCAN", tgs)
        issues = validate_group_set(gset)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"127 TGs should be clean: {errors}"

    def test_inject_128_scan_tgs_errors(self):
        """128 scan-enabled TGs should trigger an error."""
        tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i:05d}") for i in range(128)]
        gset = make_group_set("OVER", tgs)
        issues = validate_group_set(gset)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) >= 1
        assert any("128" in e[1] for e in [(ERROR, m) for _, m in issues
                                             if _ == ERROR])

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_large_group_set_injection(self):
        """Inject 100 TGs into claude test and verify roundtrip."""
        prs = cached_parse_prs(CLAUDE)
        tgs = [make_p25_group(i, f"TG{i:05d}", f"TG {i:05d} NAME")
               for i in range(100)]
        add_talkgroups(prs, "GROUP SE", tgs)

        sets = _get_group_sets(prs)
        assert len(sets[0].groups) == 101  # 1 original + 100 new

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_large_trunk_set_injection(self):
        """Inject 50 trunk channels."""
        prs = cached_parse_prs(CLAUDE)
        channels = [make_trunk_channel(851.0 + i * 0.025, 806.0 + i * 0.025)
                     for i in range(50)]
        tsets = _get_trunk_sets(prs)
        add_trunk_channels(prs, tsets[0].name, channels)

        tsets2 = _get_trunk_sets(prs)
        assert len(tsets2[0].channels) == len(tsets[0].channels) + 50

        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_many_sets_injection(self):
        """Add 5 group sets and 5 trunk sets."""
        prs = cached_parse_prs(CLAUDE)
        for i in range(5):
            gset = make_group_set(f"GS{i}", [(i * 100 + j, f"T{i}{j:02d}",
                                               f"TEST SET {i} TG {j}")
                                              for j in range(10)])
            add_group_set(prs, gset)
            tset = make_trunk_set(f"TS{i}",
                                   [(851.0 + j * 0.1, 806.0 + j * 0.1)
                                    for j in range(5)])
            add_trunk_set(prs, tset)

        gsets = _get_group_sets(prs)
        assert len(gsets) == 6  # 1 original + 5 new
        tsets = _get_trunk_sets(prs)
        assert len(tsets) == 6

        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    def test_30_ecc_entries_max(self):
        """System with 30 ECC entries (max) should build correctly."""
        ecc = [EnhancedCCEntry(entry_type=3, system_id=i,
                                channel_ref1=i, channel_ref2=i)
               for i in range(30)]
        config = P25TrkSystemConfig(
            system_name="MAXECC",
            long_name="MAX ECC TEST",
            trunk_set_name="MAXECC",
            group_set_name="MAXECC",
            wan_name="MAXECC",
            ecc_entries=ecc,
            iden_set_name="MAXIDEN",
            band_low_hz=767_000_000,
            band_high_hz=858_000_000,
            wan_chan_spacing_hz=6250,
            wan_base_freq_hz=851_006_250,
        )
        data = config.build_data_section()
        count, parsed, iden = parse_ecc_entries(data)
        assert count == 30
        assert iden == "MAXIDEN"


# ═══════════════════════════════════════════════════════════════════
# Undo simulation — parse → modify → restore from snapshot
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestUndoWorkflow:

    def test_undo_via_bytes_snapshot(self):
        """Simulate undo: save bytes before modify, restore after."""
        prs = cached_parse_prs(CLAUDE)
        snapshot = prs.to_bytes()

        # Modify
        tgs = [make_p25_group(999, "UNDO TG", "UNDO TEST TG")]
        add_talkgroups(prs, "GROUP SE", tgs)
        modified = prs.to_bytes()
        assert modified != snapshot

        # Undo: restore from snapshot
        prs_restored = parse_prs_bytes(snapshot)
        assert prs_restored.to_bytes() == snapshot

        # Verify original data is back
        sets = _get_group_sets(prs_restored)
        assert len(sets[0].groups) == 1
        assert sets[0].groups[0].group_name == "name"

    def test_multiple_undo_levels(self):
        """Simulate multi-level undo with multiple snapshots."""
        prs = cached_parse_prs(CLAUDE)
        snapshots = [prs.to_bytes()]

        # Level 1: add 1 TG
        add_talkgroups(prs, "GROUP SE",
                        [make_p25_group(100, "LVL1", "LEVEL 1")])
        snapshots.append(prs.to_bytes())
        assert len(_get_group_sets(prs)[0].groups) == 2

        # Level 2: add another TG
        add_talkgroups(prs, "GROUP SE",
                        [make_p25_group(200, "LVL2", "LEVEL 2")])
        snapshots.append(prs.to_bytes())
        assert len(_get_group_sets(prs)[0].groups) == 3

        # Undo to level 1
        prs = parse_prs_bytes(snapshots[1])
        assert len(_get_group_sets(prs)[0].groups) == 2

        # Undo to level 0 (original)
        prs = parse_prs_bytes(snapshots[0])
        assert len(_get_group_sets(prs)[0].groups) == 1


# ═══════════════════════════════════════════════════════════════════
# Comparison integration — before/after injection
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestComparisonIntegration:

    def test_compare_before_after_group_add(self):
        """Adding groups shows CHANGED in comparison."""
        prs_before = cached_parse_prs(CLAUDE)
        prs_after = cached_parse_prs(CLAUDE)

        add_talkgroups(prs_after, "GROUP SE",
                        [make_p25_group(500, "COMP TG", "COMPARE TG")])

        diffs = compare_prs(prs_before, prs_after)
        group_changes = [d for d in diffs if "Group" in d[1] and
                          d[0] == CHANGED]
        assert len(group_changes) >= 1

    def test_compare_before_after_system_add(self):
        """Adding full system shows multiple ADDED entries."""
        prs_before = cached_parse_prs(CLAUDE)
        prs_after = cached_parse_prs(CLAUDE)

        config = P25TrkSystemConfig(
            system_name="DIFFSYS",
            long_name="DIFF SYSTEM",
            trunk_set_name="DIFFSYS",
            group_set_name="DIFFSYS",
            wan_name="DIFFSYS",
        )
        gset = make_group_set("DIFFSYS", [(100, "TG 1", "DIFF TG")])
        tset = make_trunk_set("DIFFSYS", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs_after, config,
                                trunk_set=tset, group_set=gset)

        diffs = compare_prs(prs_before, prs_after)
        added = [d for d in diffs if d[0] == ADDED]
        assert len(added) >= 2  # at least system config + group/trunk set

    def test_compare_pawsovermaws_vs_claude(self):
        """PAWSOVERMAWS has significantly more data than claude test."""
        diffs = compare_prs(cached_parse_prs(PAWS), cached_parse_prs(CLAUDE))

        removed = [d for d in diffs if d[0] == REMOVED]
        assert len(removed) >= 5  # Many sets/systems in PAWS not in claude

        size_diffs = [d for d in diffs if d[1] == "File" and d[2] == "Size"]
        assert len(size_diffs) == 1
        assert "46,822" in size_diffs[0][3] or "46822" in size_diffs[0][3]


# ═══════════════════════════════════════════════════════════════════
# Validation integration — real-world checks
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestValidationIntegration:

    def test_pawsovermaws_validates_clean(self):
        """PAWSOVERMAWS has no validation errors."""
        prs = cached_parse_prs(PAWS)
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

    def test_claude_test_validates_clean(self):
        """claude test.PRS has no validation errors."""
        prs = cached_parse_prs(CLAUDE)
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

    def test_detailed_validation_categorized(self):
        """validate_prs_detailed groups issues by set name."""
        prs = cached_parse_prs(PAWS)
        result = validate_prs_detailed(prs)
        assert isinstance(result, dict)
        for key in result:
            assert isinstance(result[key], list)

    def test_validation_after_injection(self):
        """Modified file still validates after injection."""
        prs = cached_parse_prs(CLAUDE)
        config = P25TrkSystemConfig(
            system_name="VALID",
            long_name="VALIDATION TEST",
            trunk_set_name="VALID",
            group_set_name="VALID",
            wan_name="VALID",
        )
        gset = make_group_set("VALID", [(100, "TG1", "TEST TG")])
        tset = make_trunk_set("VALID", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config,
                                trunk_set=tset, group_set=gset)
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════
# File I/O integration — write → read → verify
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestFileIO:

    def test_write_modified_and_reread(self, tmp_path):
        """Inject → write to disk → re-read → verify data intact."""
        prs = cached_parse_prs(CLAUDE)
        add_talkgroups(prs, "GROUP SE",
                        [make_p25_group(777, "IO TEST", "IO TEST TG")])

        outpath = tmp_path / "modified.PRS"
        write_prs(prs, outpath, backup=False)

        prs2 = parse_prs(outpath)
        sets = _get_group_sets(prs2)
        found = any(g.group_id == 777 for g in sets[0].groups)
        assert found, "Injected TG not found after write/read"

        # Binary identical
        assert outpath.read_bytes() == prs.to_bytes()

    def test_write_pawsovermaws_modified(self, tmp_path):
        """Modify PAWSOVERMAWS, write, re-read, verify."""
        prs = cached_parse_prs(PAWS)
        gset = make_group_set("IOTEST", [(999, "IO TG", "IO TEST TG")])
        add_group_set(prs, gset)

        outpath = tmp_path / "paws_modified.PRS"
        write_prs(prs, outpath, backup=False)

        prs2 = parse_prs(outpath)
        gsets = _get_group_sets(prs2)
        names = {s.name for s in gsets}
        assert "IOTEST" in names
        assert outpath.read_bytes() == prs.to_bytes()

    def test_backup_creation(self, tmp_path):
        """write_prs creates a .bak backup file."""
        prs = cached_parse_prs(CLAUDE)
        outpath = tmp_path / "backup_test.PRS"
        outpath.write_bytes(prs.to_bytes())

        # Now write again with backup
        add_talkgroups(prs, "GROUP SE",
                        [make_p25_group(555, "BAK TG", "BACKUP TG")])
        write_prs(prs, outpath, backup=True)

        bakpath = outpath.with_suffix('.PRS.bak')
        assert bakpath.exists(), "Backup file should exist"
        assert bakpath.read_bytes() != outpath.read_bytes()


# ═══════════════════════════════════════════════════════════════════
# Preferred entries integration
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestPreferredIntegration:

    def test_preferred_roundtrip_after_add(self):
        """Add preferred entries, verify they survive roundtrip."""
        from quickprs.record_types import PreferredSystemEntry
        prs = cached_parse_prs(CLAUDE)

        orig_entries, orig_iden, orig_chain = get_preferred_entries(prs)

        new_entries = [
            PreferredSystemEntry(entry_type=3, system_id=800, field1=1),
            PreferredSystemEntry(entry_type=3, system_id=801, field1=1),
        ]
        add_preferred_entries(prs, new_entries)

        entries, iden, chain = get_preferred_entries(prs)
        assert len(entries) == len(orig_entries) + 2

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        entries2, _, _ = get_preferred_entries(prs2)
        assert len(entries2) == len(entries)
        assert entries2[-1].system_id == 801


# ═══════════════════════════════════════════════════════════════════
# IDEN dedup integration
# ═══════════════════════════════════════════════════════════════════


class TestIdenDedup:

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_find_matching_iden_after_inject(self):
        """Inject IDEN set, then find_matching should detect it."""
        from quickprs.iden_library import (
            find_matching_iden_set, get_template,
        )

        prs = cached_parse_prs(CLAUDE)
        template = get_template("800-TDMA")
        iset = make_iden_set("8TDMA", template.entries)
        add_iden_set(prs, iset)

        result = find_matching_iden_set(prs, "800-TDMA")
        assert result == "8TDMA"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_no_match_different_band(self):
        """Inject 800 IDEN, looking for 700 should return None."""
        from quickprs.iden_library import (
            find_matching_iden_set, get_template,
        )

        prs = cached_parse_prs(CLAUDE)
        template = get_template("800-FDMA")
        iset = make_iden_set("8FDMA", template.entries)
        add_iden_set(prs, iset)

        result = find_matching_iden_set(prs, "700-TDMA")
        assert result is None

    def test_auto_select_template_integration(self):
        """auto_select_template_key picks correct template for frequencies."""
        from quickprs.iden_library import auto_select_template_key

        # 800 MHz Phase II system
        key = auto_select_template_key(
            [851.0125, 851.5125, 852.0125],
            "Project 25 Phase II")
        assert key == "800-TDMA"

        # 700 MHz Phase I system
        key = auto_select_template_key(
            [769.40625],
            "Project 25 Phase I")
        assert key == "700-FDMA"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_inject_two_systems_same_band_iden_reuse(self):
        """Two 800 MHz systems should be able to share the same IDEN set."""
        from quickprs.iden_library import (
            find_matching_iden_set, get_template,
        )

        prs = cached_parse_prs(CLAUDE)

        # First system with IDEN
        template = get_template("800-TDMA")
        iset = make_iden_set("8TDMA", template.entries)
        config1 = P25TrkSystemConfig(
            system_name="SYS1",
            long_name="SYSTEM ONE",
            trunk_set_name="SYS1",
            group_set_name="SYS1",
            wan_name="SYS1",
            iden_set_name="8TDMA",
        )
        gset1 = make_group_set("SYS1", [(100, "TG 1", "SYSTEM 1")])
        tset1 = make_trunk_set("SYS1", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config1,
                               trunk_set=tset1, group_set=gset1,
                               iden_set=iset)

        # Second system — should find existing IDEN
        result = find_matching_iden_set(prs, "800-TDMA")
        assert result == "8TDMA"

        # Add second system reusing the IDEN set (no new iden_set arg)
        config2 = P25TrkSystemConfig(
            system_name="SYS2",
            long_name="SYSTEM TWO",
            trunk_set_name="SYS2",
            group_set_name="SYS2",
            wan_name="SYS2",
            iden_set_name="8TDMA",  # reuse
        )
        gset2 = make_group_set("SYS2", [(200, "TG 2", "SYSTEM 2")])
        tset2 = make_trunk_set("SYS2", [(851.5125, 806.5125)])
        add_p25_trunked_system(prs, config2,
                               trunk_set=tset2, group_set=gset2)

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Validation
        issues = validate_prs(prs2)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════
# Import flow edge cases
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestImportEdgeCases:

    def test_empty_talkgroup_list_still_injects_freqs(self):
        """System with frequencies but no talkgroups should still inject."""
        prs = cached_parse_prs(CLAUDE)
        config = P25TrkSystemConfig(
            system_name="NOGROUPS",
            long_name="NO GROUPS SYS",
            trunk_set_name="NOGROUPS",
            group_set_name="NOGROUPS",
            wan_name="NOGROUPS",
        )
        tset = make_trunk_set("NOGROUPS", [
            (851.0125, 806.0125),
            (851.5125, 806.5125),
        ])
        add_p25_trunked_system(prs, config, trunk_set=tset)

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    def test_system_with_ecc_and_iden_roundtrip(self):
        """System with both ECC entries and IDEN set roundtrips."""
        from quickprs.iden_library import get_template

        prs = cached_parse_prs(CLAUDE)

        ecc = [
            EnhancedCCEntry(entry_type=3, system_id=892,
                           channel_ref1=100, channel_ref2=100),
            EnhancedCCEntry(entry_type=4, system_id=892,
                           channel_ref1=200, channel_ref2=200),
        ]
        template = get_template("800-TDMA")
        iset = make_iden_set("8TDMA", template.entries)

        config = P25TrkSystemConfig(
            system_name="ECCTST",
            long_name="ECC TEST SYS",
            trunk_set_name="ECCTST",
            group_set_name="ECCTST",
            wan_name="ECCTST",
            system_id=892,
            ecc_entries=ecc,
            iden_set_name="8TDMA",
        )
        gset = make_group_set("ECCTST", [(100, "TG 1", "ECC TEST")])
        tset = make_trunk_set("ECCTST", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config,
                               trunk_set=tset, group_set=gset,
                               iden_set=iset)

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Validate
        issues = validate_prs(prs2)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════
# Create-from-scratch workflows
# ═══════════════════════════════════════════════════════════════════


class TestCreateFromScratch:

    def test_create_blank_inject_p25_system(self):
        """Create blank PRS, inject a complete P25 trunked system, validate."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="scratch_p25.PRS")
        original_bytes = prs.to_bytes()

        # Verify blank file is valid
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

        # Inject a complete P25 trunked system
        config = P25TrkSystemConfig(
            system_name="METRO",
            long_name="METRO PD MAIN",
            trunk_set_name="METRO",
            group_set_name="METRO",
            wan_name="METRO",
            home_unit_id=10001,
            system_id=0xBEE,
        )
        gset = make_group_set("METRO", [
            (100, "DISP", "DISPATCH"),
            (200, "TAC 1", "TACTICAL 1"),
            (300, "TAC 2", "TACTICAL 2"),
            (400, "ADMIN", "ADMIN CHANNEL"),
            (500, "FIRE D", "FIRE DISPATCH"),
        ])
        tset = make_trunk_set("METRO", [
            (851.0125, 806.0125),
            (851.5125, 806.5125),
            (852.0125, 807.0125),
            (852.5125, 807.5125),
        ])
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # File should be bigger now
        modified_bytes = prs.to_bytes()
        assert len(modified_bytes) > len(original_bytes)

        # Validate — no errors
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Roundtrip
        prs2 = parse_prs_bytes(modified_bytes)
        assert prs2.to_bytes() == modified_bytes

        # Verify injected data survives
        gsets = _get_group_sets(prs2)
        found_metro = [g for g in gsets if g.name == "METRO"]
        assert len(found_metro) == 1
        assert len(found_metro[0].groups) == 5
        assert found_metro[0].groups[0].group_id == 100
        assert found_metro[0].groups[0].group_name == "DISP"

        tsets = _get_trunk_sets(prs2)
        found_tset = [t for t in tsets if t.name == "METRO"]
        assert len(found_tset) == 1
        assert len(found_tset[0].channels) == 4

    def test_create_blank_inject_multiple_systems(self):
        """Create blank, inject 3 P25 systems + 2 conv systems, validate."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="multi_sys.PRS")

        # Add 3 P25 trunked systems
        p25_systems = [
            ("METRO", "METRO PD", 0xBEE),
            ("STATE", "STATE PATROL", 0xFAD),
            ("COUNTY", "COUNTY FIRE", 0xCAB),
        ]
        for name, long_name, sys_id in p25_systems:
            config = P25TrkSystemConfig(
                system_name=name,
                long_name=long_name,
                trunk_set_name=name,
                group_set_name=name,
                wan_name=name,
                system_id=sys_id,
            )
            gset = make_group_set(name, [
                (100, "DISP", f"{name} DISP"),
                (200, "TAC 1", f"{name} TAC 1"),
            ])
            tset = make_trunk_set(name, [
                (851.0125, 806.0125),
                (851.5125, 806.5125),
            ])
            add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # Add 2 conventional systems
        for i in range(2):
            conv_config = ConvSystemConfig(
                system_name=f"CONV{i+1}",
                long_name=f"CONV SYSTEM {i+1}",
                conv_set_name=f"CONV{i+1}",
            )
            cset = make_conv_set(f"CONV{i+1}", [
                {'short_name': 'CH 1', 'tx_freq': 462.5625,
                 'long_name': f'CONV{i+1} CH1'},
                {'short_name': 'CH 2', 'tx_freq': 462.5875,
                 'long_name': f'CONV{i+1} CH2'},
            ])
            add_conv_system(prs, conv_config, conv_set=cset)

        # Validate — no errors
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Verify all group sets are present
        gsets = _get_group_sets(prs2)
        gset_names = {g.name for g in gsets}
        for name, _, _ in p25_systems:
            assert name in gset_names, f"Group set {name} missing"

        # Verify all trunk sets are present
        tsets = _get_trunk_sets(prs2)
        tset_names = {t.name for t in tsets}
        for name, _, _ in p25_systems:
            assert name in tset_names, f"Trunk set {name} missing"

        # Verify system configs
        configs = []
        for sec in prs2.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name:
                    configs.append(name)
        assert "METRO PD" in configs
        assert "STATE PATROL" in configs
        assert "COUNTY FIRE" in configs

    def test_create_blank_inject_from_radioreference_data(self):
        """Create blank, inject RR-style data (many TGs, multiple sites)."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="rr_import.PRS")

        # Simulate a large RadioReference import: multi-site system with
        # many talkgroups across multiple departments
        talkgroups = []
        departments = ["POLICE", "FIRE", "EMS", "PUBLIC W", "TRANSIT"]
        for dept_idx, dept in enumerate(departments):
            base_id = (dept_idx + 1) * 1000
            for tg_idx in range(25):
                tg_id = base_id + tg_idx
                short = f"{dept[:4]}{tg_idx:02d}"[:8]
                long = f"{dept} TG {tg_idx}"[:16]
                talkgroups.append((tg_id, short, long))

        # Total: 125 talkgroups (under 127 scan limit)
        assert len(talkgroups) == 125

        gset = make_group_set("RRDEMO", talkgroups)

        # Multi-site: 60 frequencies representing 3 sites x 20 channels
        freqs = [(851.0 + i * 0.025, 806.0 + i * 0.025) for i in range(60)]
        tset = make_trunk_set("RRDEMO", freqs)

        config = P25TrkSystemConfig(
            system_name="RRDEMO",
            long_name="RR DEMO SYSTEM",
            trunk_set_name="RRDEMO",
            group_set_name="RRDEMO",
            wan_name="RRDEMO",
            system_id=0xABC,
        )
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # Validate — 125 TGs is under limit, should pass
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Should get a warning about approaching scan limit
        warnings = [i for i in issues if i[0] == WARNING]
        scan_warnings = [w for w in warnings if "scan" in w[1].lower()]
        assert len(scan_warnings) >= 1, "Should warn about approaching scan limit"

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Verify data integrity
        gsets = _get_group_sets(prs2)
        rr_set = [g for g in gsets if g.name == "RRDEMO"][0]
        assert len(rr_set.groups) == 125
        # Spot-check first and last talkgroup
        assert rr_set.groups[0].group_id == 1000
        assert rr_set.groups[-1].group_id == 5024

        tsets = _get_trunk_sets(prs2)
        rr_tset = [t for t in tsets if t.name == "RRDEMO"][0]
        assert len(rr_tset.channels) == 60


# ═══════════════════════════════════════════════════════════════════
# Modify-existing workflows
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestModifyExisting:

    def test_modify_pawsovermaws_add_system(self):
        """Add a new P25 system to PAWSOVERMAWS, verify all existing data preserved."""
        prs = cached_parse_prs(PAWS)
        original_bytes = prs.to_bytes()

        # Count existing data before modification
        orig_gsets = _get_group_sets(prs)
        orig_tsets = _get_trunk_sets(prs)
        orig_gset_names = {g.name for g in orig_gsets}
        orig_tset_names = {t.name for t in orig_tsets}
        orig_gset_counts = {g.name: len(g.groups) for g in orig_gsets}
        orig_tset_counts = {t.name: len(t.channels) for t in orig_tsets}

        # Add a new system
        config = P25TrkSystemConfig(
            system_name="NEWSYS",
            long_name="NEW TEST SYSTEM",
            trunk_set_name="NEWSYS",
            group_set_name="NEWSYS",
            wan_name="NEWSYS",
            system_id=0x999,
        )
        gset = make_group_set("NEWSYS", [
            (600, "NEW TG1", "NEW SYSTEM TG 1"),
            (601, "NEW TG2", "NEW SYSTEM TG 2"),
        ])
        tset = make_trunk_set("NEWSYS", [
            (851.0125, 806.0125),
            (851.5125, 806.5125),
            (852.0125, 807.0125),
        ])
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # Verify all original data is preserved
        new_gsets = _get_group_sets(prs)
        new_tsets = _get_trunk_sets(prs)
        new_gset_names = {g.name for g in new_gsets}
        new_tset_names = {t.name for t in new_tsets}

        # All original sets should still exist
        assert orig_gset_names.issubset(new_gset_names)
        assert orig_tset_names.issubset(new_tset_names)

        # Original set sizes should be unchanged
        for g in new_gsets:
            if g.name in orig_gset_counts:
                assert len(g.groups) == orig_gset_counts[g.name], \
                    f"Group set '{g.name}' changed from {orig_gset_counts[g.name]} to {len(g.groups)}"
        for t in new_tsets:
            if t.name in orig_tset_counts:
                assert len(t.channels) == orig_tset_counts[t.name], \
                    f"Trunk set '{t.name}' changed from {orig_tset_counts[t.name]} to {len(t.channels)}"

        # New set should exist
        assert "NEWSYS" in new_gset_names
        assert "NEWSYS" in new_tset_names

        # Validate
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Roundtrip
        modified = prs.to_bytes()
        assert len(modified) > len(original_bytes)
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    def test_modify_pawsovermaws_add_and_remove(self):
        """Add a system then remove it, verify file returns to near-original state."""
        prs = cached_parse_prs(PAWS)
        original_bytes = prs.to_bytes()

        # Snapshot original group/trunk data
        orig_gsets = _get_group_sets(prs)
        orig_tsets = _get_trunk_sets(prs)
        orig_gset_count = len(orig_gsets)
        orig_tset_count = len(orig_tsets)

        # Add a system
        config = P25TrkSystemConfig(
            system_name="TMPTEST",
            long_name="TEMPORARY TEST",
            trunk_set_name="TMPTEST",
            group_set_name="TMPTEST",
            wan_name="TMPTEST",
        )
        gset = make_group_set("TMPTEST", [(999, "TMP TG", "TEMP TALKGROUP")])
        tset = make_trunk_set("TMPTEST", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # Verify addition
        mid_gsets = _get_group_sets(prs)
        assert len(mid_gsets) == orig_gset_count + 1

        # Remove the system config
        removed = remove_system_config(prs, "TEMPORARY TEST")
        assert removed is True

        # System config should be gone, but data sets remain (injector removes
        # only the config section — data sets stay as orphans)
        configs_after = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name:
                    configs_after.append(name)
        assert "TEMPORARY TEST" not in configs_after

        # Roundtrip should still work
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    def test_modify_claude_test_add_groups(self):
        """Add talkgroups to claude test, verify P25ConvChannel preserved."""
        from quickprs.record_types import (
            parse_p25_conv_channel_section, parse_sets_from_sections,
        )

        prs = cached_parse_prs(CLAUDE)

        # Capture original P25ConvChannel data before modification
        pc_sec = prs.get_section_by_class("CP25ConvChannel")
        ps_sec = prs.get_section_by_class("CP25ConvSet")
        assert pc_sec is not None, "claude test should have CP25ConvChannel"
        assert ps_sec is not None, "claude test should have CP25ConvSet"
        orig_pc_raw = pc_sec.raw

        orig_p25conv = parse_sets_from_sections(
            ps_sec.raw, pc_sec.raw, parse_p25_conv_channel_section)
        assert len(orig_p25conv) == 1
        assert orig_p25conv[0].name == "NEW"
        assert len(orig_p25conv[0].channels) == 1
        orig_p25conv_name = orig_p25conv[0].channels[0].short_name
        orig_p25conv_tx = orig_p25conv[0].channels[0].tx_freq

        # Add talkgroups to the existing group set
        new_tgs = [
            make_p25_group(5000, "ADDED1", "ADDED GROUP 1"),
            make_p25_group(5001, "ADDED2", "ADDED GROUP 2"),
            make_p25_group(5002, "ADDED3", "ADDED GROUP 3"),
        ]
        add_talkgroups(prs, "GROUP SE", new_tgs)

        # Verify talkgroups were added
        gsets = _get_group_sets(prs)
        assert len(gsets[0].groups) == 4  # 1 original + 3 new
        assert gsets[0].groups[0].group_id == 12312  # original preserved
        assert gsets[0].groups[1].group_id == 5000
        assert gsets[0].groups[3].group_id == 5002

        # Verify P25ConvChannel is UNCHANGED
        pc_sec_after = prs.get_section_by_class("CP25ConvChannel")
        ps_sec_after = prs.get_section_by_class("CP25ConvSet")
        assert pc_sec_after is not None
        assert pc_sec_after.raw == orig_pc_raw, "P25ConvChannel raw bytes should be unchanged"

        p25conv_after = parse_sets_from_sections(
            ps_sec_after.raw, pc_sec_after.raw, parse_p25_conv_channel_section)
        assert len(p25conv_after) == 1
        assert p25conv_after[0].channels[0].short_name == orig_p25conv_name
        assert p25conv_after[0].channels[0].tx_freq == orig_p25conv_tx

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified


# ═══════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_max_talkgroups(self):
        """Inject 127 talkgroups (max scannable), validate passes."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs()
        tgs = [(i + 1, f"TG{i+1:05d}", f"TALKGROUP {i+1:04d}") for i in range(127)]
        gset = make_group_set("MAXSCAN", tgs)

        config = P25TrkSystemConfig(
            system_name="MAXSCAN",
            long_name="MAX SCAN TEST",
            trunk_set_name="MAXSCAN",
            group_set_name="MAXSCAN",
            wan_name="MAXSCAN",
        )
        tset = make_trunk_set("MAXSCAN", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"127 TGs should be clean: {errors}"

        # Verify all 127 survive roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified
        gsets = _get_group_sets(prs2)
        max_set = [g for g in gsets if g.name == "MAXSCAN"][0]
        assert len(max_set.groups) == 127

    def test_over_max_talkgroups(self):
        """Inject 128 talkgroups, validate returns error."""
        tgs = [(i, f"TG{i:05d}", f"TALKGROUP {i:05d}") for i in range(128)]
        gset = make_group_set("OVER", tgs)
        issues = validate_group_set(gset)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) >= 1, "128 scan-enabled TGs should error"
        assert any("128" in e[1] for e in errors), "Error should mention 128"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_max_trunk_channels(self):
        """Inject 1024 trunk frequencies in one set."""
        prs = cached_parse_prs(CLAUDE)
        channels = [make_trunk_channel(851.0 + i * 0.00625, 806.0 + i * 0.00625)
                     for i in range(1024)]
        tsets = _get_trunk_sets(prs)
        orig_name = tsets[0].name
        add_trunk_channels(prs, orig_name, channels)

        tsets2 = _get_trunk_sets(prs)
        assert len(tsets2[0].channels) == 1 + 1024  # 1 original + 1024 new

        # Validate: at limit, should not error
        from quickprs.validation import validate_trunk_set
        issues = validate_trunk_set(tsets2[0])
        errors = [i for i in issues if i[0] == ERROR]
        # 1025 > 1024 limit, so this SHOULD error
        assert len(errors) >= 1, "1025 channels exceeds 1024 limit"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_empty_names(self):
        """Inject with empty string names, verify defaults applied."""
        # make_p25_group: empty long_name defaults to short_name
        group = make_p25_group(100, "TESTGRP", "")
        assert group.long_name == "TESTGRP"

        # make_conv_channel: empty long_name defaults to short_name
        channel = make_conv_channel("TESTCH", 462.5625, long_name="")
        assert channel.long_name == "TESTCH"

        # Inject group with empty name and verify roundtrip
        prs = cached_parse_prs(CLAUDE)
        add_talkgroups(prs, "GROUP SE", [group])
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_unicode_names(self):
        """Try to inject non-ASCII names, verify truncation/handling."""
        # P25Group names are written as LPS (length-prefixed string).
        # Non-ASCII characters may raise or be silently truncated.
        # The important thing is that it doesn't crash and roundtrips.
        prs = cached_parse_prs(CLAUDE)

        # Short names are encoded to bytes — non-ASCII will fail at encode time
        # or be mangled. Test that we at least handle ASCII-safe truncation.
        group = make_p25_group(100, "CAFE\u0301", "CLICH\u00C9 GROUP")
        # make_p25_group truncates to 8/16 chars but doesn't strip non-ASCII
        assert len(group.group_name) <= 8
        assert len(group.long_name) <= 16

        # Injection and serialization — non-ASCII will be handled at write time
        try:
            add_talkgroups(prs, "GROUP SE", [group])
            modified = prs.to_bytes()
            # If it succeeds, verify roundtrip
            prs2 = parse_prs_bytes(modified)
            assert prs2.to_bytes() == modified
        except (UnicodeEncodeError, UnicodeDecodeError):
            # This is acceptable — non-ASCII is rejected
            pass

    def test_frequency_boundaries(self):
        """Test channels at 30 MHz (min) and 960 MHz (max XG-100P range)."""
        from quickprs.validation import validate_trunk_set, validate_conv_set, LIMITS

        # Exactly at boundaries — should pass
        tset_ok = make_trunk_set("BOUNDOK", [
            (LIMITS['freq_min_mhz'], LIMITS['freq_min_mhz']),
            (LIMITS['freq_max_mhz'], LIMITS['freq_max_mhz']),
        ])
        issues = validate_trunk_set(tset_ok)
        freq_errors = [i for i in issues if i[0] == ERROR and "range" in i[1].lower()]
        assert len(freq_errors) == 0, f"Boundary freqs should be valid: {freq_errors}"

        # Just outside boundaries — should fail
        tset_bad = make_trunk_set("BOUNDBAD", [
            (29.999, 29.999),
            (960.001, 960.001),
        ])
        issues = validate_trunk_set(tset_bad)
        freq_errors = [i for i in issues if i[0] == ERROR and "range" in i[1].lower()]
        assert len(freq_errors) >= 2, "Freqs outside 30-960 MHz should error"

    def test_zero_frequency(self):
        """Inject a channel with 0.0 MHz, check validation catches it."""
        from quickprs.validation import validate_trunk_set

        tset = make_trunk_set("ZEROF", [(0.0, 0.0)])
        issues = validate_trunk_set(tset)
        freq_errors = [i for i in issues if i[0] == ERROR and "range" in i[1].lower()]
        assert len(freq_errors) >= 1, "0.0 MHz should be caught as out-of-range"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_duplicate_talkgroup_ids_different_sets(self):
        """Same talkgroup ID in different sets should be OK."""
        prs = cached_parse_prs(CLAUDE)

        # Add two group sets with overlapping TG IDs
        gset1 = make_group_set("SET1", [(100, "SET1TG", "SET 1 TG 100")])
        gset2 = make_group_set("SET2", [(100, "SET2TG", "SET 2 TG 100")])
        add_group_set(prs, gset1)
        add_group_set(prs, gset2)

        # Validate: same ID in different sets is OK
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Duplicate IDs across sets should be fine: {errors}"

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Verify both sets have the ID
        gsets = _get_group_sets(prs2)
        set1 = [g for g in gsets if g.name == "SET1"][0]
        set2 = [g for g in gsets if g.name == "SET2"][0]
        assert set1.groups[0].group_id == 100
        assert set2.groups[0].group_id == 100

    def test_duplicate_talkgroup_ids_same_set_warns(self):
        """Duplicate talkgroup ID within the same set should warn."""
        gset = make_group_set("DUPS", [
            (100, "TG100A", "TALKGROUP 100 A"),
            (100, "TG100B", "TALKGROUP 100 B"),
        ])
        issues = validate_group_set(gset)
        warnings = [i for i in issues if i[0] == WARNING and "Duplicate" in i[1]]
        assert len(warnings) >= 1, "Duplicate TG ID in same set should warn"


# ═══════════════════════════════════════════════════════════════════
# Roundtrip stress tests
# ═══════════════════════════════════════════════════════════════════


class TestRoundtripStress:

    def test_triple_roundtrip_after_heavy_injection(self):
        """Create blank, inject 5 systems + 500 TGs + 100 channels, serialize 3 times."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="stress.PRS")

        # Inject 5 P25 trunked systems with many TGs and channels
        for sys_idx in range(5):
            name = f"SYS{sys_idx}"
            tgs = [(sys_idx * 200 + i, f"T{sys_idx}{i:03d}", f"SYS{sys_idx} TG{i}")
                    for i in range(100)]
            gset = make_group_set(name, tgs)
            freqs = [(851.0 + i * 0.025, 806.0 + i * 0.025) for i in range(20)]
            tset = make_trunk_set(name, freqs)
            config = P25TrkSystemConfig(
                system_name=name,
                long_name=f"SYSTEM {sys_idx}",
                trunk_set_name=name,
                group_set_name=name,
                wan_name=name,
            )
            add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        # Total: 5 systems, 500 TGs, 100 trunk channels
        gsets = _get_group_sets(prs)
        total_tgs = sum(len(g.groups) for g in gsets)
        assert total_tgs == 500

        tsets = _get_trunk_sets(prs)
        total_channels = sum(len(t.channels) for t in tsets)
        assert total_channels == 100

        # Triple roundtrip: serialize -> parse -> serialize -> parse -> serialize
        bytes1 = prs.to_bytes()
        prs2 = parse_prs_bytes(bytes1)
        bytes2 = prs2.to_bytes()
        prs3 = parse_prs_bytes(bytes2)
        bytes3 = prs3.to_bytes()

        assert bytes1 == bytes2 == bytes3, "Triple roundtrip should produce identical bytes"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_parse_modify_write_reparse(self):
        """Open PAWSOVERMAWS, modify every section type, write, re-parse, verify."""
        prs = cached_parse_prs(PAWS)

        # 1. Add a talkgroup to an existing group set
        add_talkgroups(prs, "PSERN PD",
                        [make_p25_group(9999, "MODTEST", "MODIFY TEST TG")])

        # 2. Add trunk channels to an existing trunk set
        add_trunk_channels(prs, "PSERN",
                            [make_trunk_channel(853.0125, 808.0125)])

        # 3. Add a new group set
        add_group_set(prs, make_group_set("NEWGRP", [
            (7001, "NEWTG1", "NEW GROUP TG 1"),
        ]))

        # 4. Add a new trunk set
        add_trunk_set(prs, make_trunk_set("NEWTRK", [
            (854.0125, 809.0125),
        ]))

        # 5. Add a new P25 system config
        config = P25TrkSystemConfig(
            system_name="MODIFY",
            long_name="MODIFY TEST SYS",
            trunk_set_name="NEWTRK",
            group_set_name="NEWGRP",
            wan_name="MODIFY",
        )
        add_p25_trunked_system(prs, config)

        # 6. Add a conventional system
        conv_config = ConvSystemConfig(
            system_name="MODCONV",
            long_name="MODIFY CONV SYS",
            conv_set_name="WA WIDE",  # reuse existing conv set
        )
        add_conv_system(prs, conv_config)

        # Validate — should be clean
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Serialize -> re-parse
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

        # Verify modifications survived
        gsets = _get_group_sets(prs2)
        psern_pd = [g for g in gsets if g.name == "PSERN PD"][0]
        assert any(g.group_id == 9999 for g in psern_pd.groups), "Added TG 9999 missing"
        assert len(psern_pd.groups) == 84  # 83 original + 1 added

        tsets = _get_trunk_sets(prs2)
        psern_t = [t for t in tsets if t.name == "PSERN"][0]
        assert len(psern_t.channels) == 29  # 28 original + 1 added

        newgrp = [g for g in gsets if g.name == "NEWGRP"]
        assert len(newgrp) == 1
        assert len(newgrp[0].groups) == 1

        newtrk = [t for t in tsets if t.name == "NEWTRK"]
        assert len(newtrk) == 1
        assert len(newtrk[0].channels) == 1

        # Verify system config was added
        configs = []
        for sec in prs2.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name:
                    configs.append(name)
        assert "MODIFY TEST SYS" in configs
        assert "MODIFY CONV SYS" in configs
        # Original systems still present
        assert "PSERN SEATTLE" in configs
        assert "FURRY TRASH WB" in configs


# ═══════════════════════════════════════════════════════════════════
# File I/O tests
# ═══════════════════════════════════════════════════════════════════


class TestFileIOExtended:

    def test_write_and_read_back(self, tmp_path):
        """Create PRS, write to disk, read back, verify byte-identical."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="disktest.PRS")

        # Inject a system so it's not trivially empty
        config = P25TrkSystemConfig(
            system_name="DISKTS",
            long_name="DISK I/O TEST",
            trunk_set_name="DISKTS",
            group_set_name="DISKTS",
            wan_name="DISKTS",
        )
        gset = make_group_set("DISKTS", [(100, "TG1", "DISK TEST TG")])
        tset = make_trunk_set("DISKTS", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        expected_bytes = prs.to_bytes()

        # Write to disk
        outpath = tmp_path / "disktest.PRS"
        write_prs(prs, outpath, backup=False)

        # Read back and compare
        disk_bytes = outpath.read_bytes()
        assert disk_bytes == expected_bytes, "Disk bytes should match in-memory bytes"

        # Parse from disk and verify
        prs2 = parse_prs(outpath)
        assert prs2.to_bytes() == expected_bytes

    def test_create_prs_file_valid_for_gui(self):
        """Create PRS, verify all GUI-accessed fields work."""
        from quickprs.builder import create_blank_prs
        from quickprs.record_types import (
            parse_sets_from_sections, parse_group_section,
            parse_trunk_channel_section, parse_conv_channel_section,
            parse_iden_section,
            parse_system_short_name, is_system_config_data,
            parse_system_long_name,
        )

        prs = create_blank_prs(filename="guitest.PRS")

        # Inject a complete P25 system with IDEN
        from quickprs.iden_library import get_template
        template = get_template("800-TDMA")
        iset = make_iden_set("8TDMA", template.entries)

        config = P25TrkSystemConfig(
            system_name="GUISYS",
            long_name="GUI TEST SYSTEM",
            trunk_set_name="GUISYS",
            group_set_name="GUISYS",
            wan_name="GUISYS",
            iden_set_name="8TDMA",
        )
        gset = make_group_set("GUISYS", [
            (100, "TG 1", "GUI TG ONE"),
            (200, "TG 2", "GUI TG TWO"),
        ])
        tset = make_trunk_set("GUISYS", [
            (851.0125, 806.0125),
            (851.5125, 806.5125),
        ])
        add_p25_trunked_system(prs, config,
                                trunk_set=tset, group_set=gset, iden_set=iset)

        # Simulate the field accesses PersonalityView does on the tree:

        # 1. System headers
        p25_systems = prs.get_sections_by_class("CP25TrkSystem")
        assert len(p25_systems) >= 1
        short = parse_system_short_name(p25_systems[0].raw)
        assert short == "GUISYS"

        conv_systems = prs.get_sections_by_class("CConvSystem")
        assert len(conv_systems) >= 1  # blank PRS has a default conv system

        # 2. System config data sections
        found_gui_sys = False
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                name = parse_system_long_name(sec.raw)
                if name == "GUI TEST SYSTEM":
                    found_gui_sys = True
        assert found_gui_sys

        # 3. Group sets (what the tree walks)
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        assert grp_sec is not None
        assert set_sec is not None
        gsets = parse_sets_from_sections(set_sec.raw, grp_sec.raw, parse_group_section)
        assert len(gsets) >= 1
        gui_gset = [g for g in gsets if g.name == "GUISYS"][0]
        assert len(gui_gset.groups) == 2
        # GUI displays group_name, group_id, long_name for each
        for g in gui_gset.groups:
            assert g.group_name  # non-empty
            assert g.group_id > 0
            assert g.long_name  # non-empty

        # 4. Trunk sets
        ch_sec = prs.get_section_by_class("CTrunkChannel")
        ts_sec = prs.get_section_by_class("CTrunkSet")
        assert ch_sec is not None
        assert ts_sec is not None
        tsets = parse_sets_from_sections(ts_sec.raw, ch_sec.raw,
                                          parse_trunk_channel_section)
        assert len(tsets) >= 1
        gui_tset = [t for t in tsets if t.name == "GUISYS"][0]
        assert len(gui_tset.channels) == 2
        for ch in gui_tset.channels:
            assert ch.tx_freq > 0
            assert ch.rx_freq > 0

        # 5. Conv sets (from blank template)
        conv_sec = prs.get_section_by_class("CConvChannel")
        conv_set_sec = prs.get_section_by_class("CConvSet")
        assert conv_sec is not None
        assert conv_set_sec is not None
        csets = parse_sets_from_sections(conv_set_sec.raw, conv_sec.raw,
                                          parse_conv_channel_section)
        assert len(csets) >= 1

        # 6. IDEN sets
        elem_sec = prs.get_section_by_class("CDefaultIdenElem")
        ids_sec = prs.get_section_by_class("CIdenDataSet")
        assert elem_sec is not None
        assert ids_sec is not None
        isets = parse_sets_from_sections(ids_sec.raw, elem_sec.raw,
                                          parse_iden_section)
        assert len(isets) >= 1
        gui_iset = [s for s in isets if s.name == "8TDMA"][0]
        assert len(gui_iset.elements) == 16  # IDEN sets always have 16 slots

        # 7. Preferred entries (optional — may or may not exist)
        entries, iden, chain = get_preferred_entries(prs)
        # Just verify it doesn't crash — blank PRS may or may not have these

        # 8. Validation (what the GUI runs on load)
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

    def test_write_large_file_and_reread(self, tmp_path):
        """Create a large PRS with many systems, write, re-read, verify."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs(filename="large.PRS")

        # Add 10 P25 systems with 50 TGs each and 10 trunk channels
        for i in range(10):
            name = f"SYS{i:02d}"
            tgs = [(i * 100 + j, f"T{i}{j:02d}", f"SYS{i} TG{j}")
                    for j in range(50)]
            gset = make_group_set(name, tgs)
            freqs = [(851.0 + j * 0.025, 806.0 + j * 0.025)
                      for j in range(10)]
            tset = make_trunk_set(name, freqs)
            config = P25TrkSystemConfig(
                system_name=name,
                long_name=f"SYSTEM {i:02d} LONG",
                trunk_set_name=name,
                group_set_name=name,
                wan_name=name,
            )
            add_p25_trunked_system(prs, config, trunk_set=tset, group_set=gset)

        outpath = tmp_path / "large.PRS"
        write_prs(prs, outpath, backup=False)

        # Verify file size is reasonable (10 systems * ~50 TGs * ~40 bytes/TG + overhead)
        file_size = outpath.stat().st_size
        assert file_size > 20000, f"Large file too small: {file_size}"

        # Re-read and verify
        prs2 = parse_prs(outpath)
        assert prs2.to_bytes() == outpath.read_bytes()

        # Verify data integrity
        gsets = _get_group_sets(prs2)
        assert len(gsets) == 10
        total_tgs = sum(len(g.groups) for g in gsets)
        assert total_tgs == 500

        tsets = _get_trunk_sets(prs2)
        assert len(tsets) == 10
        total_channels = sum(len(t.channels) for t in tsets)
        assert total_channels == 100


# ═══════════════════════════════════════════════════════════════════
# Cross-system validation tests
# ═══════════════════════════════════════════════════════════════════


class TestCrossValidation:

    def test_blank_prs_roundtrip(self):
        """Blank PRS should roundtrip perfectly."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        bytes1 = prs.to_bytes()
        prs2 = parse_prs_bytes(bytes1)
        assert prs2.to_bytes() == bytes1

    def test_blank_prs_validates_clean(self):
        """Blank PRS should have no validation errors."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0

    def test_inject_all_system_types_at_once(self):
        """Inject P25 trunked + conv + P25 conv into one file."""
        from quickprs.builder import create_blank_prs

        prs = create_blank_prs()

        # P25 trunked
        p25_config = P25TrkSystemConfig(
            system_name="P25TRK",
            long_name="P25 TRUNKED SYS",
            trunk_set_name="P25TRK",
            group_set_name="P25TRK",
            wan_name="P25TRK",
        )
        gset = make_group_set("P25TRK", [(100, "TG 1", "P25 TG 1")])
        tset = make_trunk_set("P25TRK", [(851.0125, 806.0125)])
        add_p25_trunked_system(prs, config=p25_config,
                                trunk_set=tset, group_set=gset)

        # Conventional
        conv_config = ConvSystemConfig(
            system_name="CONVS",
            long_name="CONV TEST SYS",
            conv_set_name="CONVS",
        )
        cset = make_conv_set("CONVS", [
            {'short_name': 'CH 1', 'tx_freq': 462.5625},
        ])
        add_conv_system(prs, conv_config, conv_set=cset)

        # P25 conventional
        p25conv_config = P25ConvSystemConfig(
            system_name="P25CON",
            long_name="P25 CONV SYS",
            conv_set_name="P25CON",
        )
        add_p25_conv_system(prs, p25conv_config)

        # All three types present
        assert len(prs.get_sections_by_class("CP25TrkSystem")) >= 1
        assert len(prs.get_sections_by_class("CConvSystem")) >= 1
        assert len(prs.get_sections_by_class("CP25ConvSystem")) >= 1

        # Validate
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

        # Roundtrip
        modified = prs.to_bytes()
        prs2 = parse_prs_bytes(modified)
        assert prs2.to_bytes() == modified

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_pawsovermaws_original_roundtrip(self):
        """PAWSOVERMAWS should be byte-for-byte identical after parse->to_bytes."""
        original = PAWS.read_bytes()
        prs = cached_parse_prs(PAWS)
        reassembled = prs.to_bytes()
        assert reassembled == original, \
            f"Roundtrip mismatch: {len(original)} vs {len(reassembled)} bytes"

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_claude_test_original_roundtrip(self):
        """claude test.PRS should be byte-for-byte identical after parse->to_bytes."""
        original = CLAUDE.read_bytes()
        prs = cached_parse_prs(CLAUDE)
        reassembled = prs.to_bytes()
        assert reassembled == original, \
            f"Roundtrip mismatch: {len(original)} vs {len(reassembled)} bytes"
