"""Comprehensive tests for comparison and prs_parser modules.

Tests cover:
  - Self-comparison (identical files)
  - System-level diffs (add/remove systems)
  - Set-level diffs (group, trunk, conv, IDEN)
  - Formatting of comparison output
  - Parser basics for both test files
  - parse_prs_bytes roundtrip
  - PRSFile methods (to_bytes, summary, get_section_*)
  - Edge cases (bad files, empty data, no markers)
"""

import sys
from pathlib import Path
from copy import deepcopy

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs, parse_prs_bytes, PRSFile, Section
from quickprs.comparison import (
    compare_prs, compare_prs_files, format_comparison,
    ADDED, REMOVED, CHANGED, SAME,
)
from quickprs.injector import (
    add_group_set, make_group_set, add_trunk_set, make_trunk_set,
    add_p25_trunked_system, add_iden_set, make_iden_set,
    add_conv_system, remove_system_config,
)
from quickprs.record_types import P25TrkSystemConfig, ConvSystemConfig

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def claude_prs():
    """Parse claude test.PRS once for the module."""
    if not CLAUDE.exists():
        pytest.skip("claude test.PRS not found")
    return parse_prs(CLAUDE)


@pytest.fixture(scope="module")
def paws_prs():
    """Parse PAWSOVERMAWS.PRS once for the module."""
    if not PAWS.exists():
        pytest.skip("PAWSOVERMAWS.PRS not found")
    return parse_prs(PAWS)


@pytest.fixture(scope="module")
def claude_bytes():
    """Raw bytes of claude test.PRS."""
    if not CLAUDE.exists():
        pytest.skip("claude test.PRS not found")
    return CLAUDE.read_bytes()


@pytest.fixture(scope="module")
def paws_bytes():
    """Raw bytes of PAWSOVERMAWS.PRS."""
    if not PAWS.exists():
        pytest.skip("PAWSOVERMAWS.PRS not found")
    return PAWS.read_bytes()


# ═══════════════════════════════════════════════════════════════════════
# 1. TestCompareIdentical
# ═══════════════════════════════════════════════════════════════════════


class TestCompareIdentical:
    """Compare same file to itself via both compare_prs and compare_prs_files."""

    def test_compare_prs_self_no_added(self, claude_prs):
        """No ADDED diffs when comparing file to itself."""
        diffs = compare_prs(claude_prs, claude_prs)
        assert all(d[0] != ADDED for d in diffs)

    def test_compare_prs_self_no_removed(self, claude_prs):
        """No REMOVED diffs when comparing file to itself."""
        diffs = compare_prs(claude_prs, claude_prs)
        assert all(d[0] != REMOVED for d in diffs)

    def test_compare_prs_self_no_changed(self, claude_prs):
        """No CHANGED diffs when comparing file to itself."""
        diffs = compare_prs(claude_prs, claude_prs)
        assert all(d[0] != CHANGED for d in diffs)

    def test_compare_prs_self_only_same(self, claude_prs):
        """Only SAME entries when comparing file to itself."""
        diffs = compare_prs(claude_prs, claude_prs)
        assert all(d[0] == SAME for d in diffs)

    def test_compare_prs_files_self_no_added(self):
        """compare_prs_files with same path shows no ADDED."""
        diffs = compare_prs_files(CLAUDE, CLAUDE)
        assert all(d[0] != ADDED for d in diffs)

    def test_compare_prs_files_self_no_removed(self):
        """compare_prs_files with same path shows no REMOVED."""
        diffs = compare_prs_files(CLAUDE, CLAUDE)
        assert all(d[0] != REMOVED for d in diffs)

    def test_compare_prs_files_self_no_changed(self):
        """compare_prs_files with same path shows no CHANGED."""
        diffs = compare_prs_files(CLAUDE, CLAUDE)
        assert all(d[0] != CHANGED for d in diffs)

    def test_paws_self_compare_no_added(self, paws_prs):
        """PAWSOVERMAWS self-compare has no ADDED."""
        diffs = compare_prs(paws_prs, paws_prs)
        assert all(d[0] != ADDED for d in diffs)

    def test_paws_self_compare_no_changed(self, paws_prs):
        """PAWSOVERMAWS self-compare has no CHANGED."""
        diffs = compare_prs(paws_prs, paws_prs)
        assert all(d[0] != CHANGED for d in diffs)


# ═══════════════════════════════════════════════════════════════════════
# 2. TestCompareSystems
# ═══════════════════════════════════════════════════════════════════════


class TestCompareSystems:
    """System-level comparison: add/remove systems, cross-file diffs."""

    def test_added_p25_system_shows_added(self):
        """Adding a P25 system should produce ADDED diff."""
        prs_before = parse_prs(CLAUDE)
        prs_after = parse_prs(CLAUDE)

        config = P25TrkSystemConfig(
            system_name="CMPSYS",
            long_name="CMP P25 SYSTEM",
            trunk_set_name="CMPSYS",
            group_set_name="CMPSYS",
            wan_name="CMPSYS",
        )
        gset = make_group_set("CMPSYS", [(999, "CMP TG", "CMP TALKGROUP")])
        tset = make_trunk_set("CMPSYS", [(851.0, 851.0)])

        add_p25_trunked_system(prs_after, config,
                               trunk_set=tset, group_set=gset)

        diffs = compare_prs(prs_before, prs_after)
        added = [d for d in diffs if d[0] == ADDED]
        assert len(added) > 0

    def test_added_p25_system_name_in_diffs(self):
        """Added system's name appears in diff entries."""
        prs_before = parse_prs(CLAUDE)
        prs_after = parse_prs(CLAUDE)

        config = P25TrkSystemConfig(
            system_name="NEWSYS",
            long_name="NEW SYS NAME",
            trunk_set_name="NEWSYS",
            group_set_name="NEWSYS",
            wan_name="NEWSYS",
        )
        gset = make_group_set("NEWSYS", [(100, "NS TG", "NS TALKGROUP")])
        tset = make_trunk_set("NEWSYS", [(852.0, 852.0)])

        add_p25_trunked_system(prs_after, config,
                               trunk_set=tset, group_set=gset)

        diffs = compare_prs(prs_before, prs_after)
        all_names = [d[2] for d in diffs]
        assert any("NEWSYS" in n or "NEW SYS" in n for n in all_names)

    def test_removed_system_shows_removed(self):
        """Removing a system config produces REMOVED diff."""
        prs_before = parse_prs(PAWS)
        prs_after = parse_prs(PAWS)

        remove_system_config(prs_after, "PSERN SEATTLE")

        diffs = compare_prs(prs_before, prs_after)
        removed = [d for d in diffs if d[0] == REMOVED]
        assert len(removed) > 0
        names = [d[2] for d in removed]
        assert "PSERN SEATTLE" in names

    def test_paws_vs_claude_has_many_removed(self):
        """PAWS has more systems, so comparing PAWS->CLAUDE shows REMOVED."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        removed = [d for d in diffs if d[0] == REMOVED]
        assert len(removed) > 10  # PAWS has many more sections/systems


# ═══════════════════════════════════════════════════════════════════════
# 3. TestCompareSetLevel
# ═══════════════════════════════════════════════════════════════════════


class TestCompareSetLevel:
    """Set-level diffs: group sets, trunk sets, modifications."""

    def test_added_group_set_shows_added(self):
        """Adding a group set produces ADDED in group set category."""
        prs_before = parse_prs(CLAUDE)
        prs_after = parse_prs(CLAUDE)

        new_gset = make_group_set("NEWGRP", [
            (100, "GRP 1", "GROUP ONE"),
            (200, "GRP 2", "GROUP TWO"),
        ])
        add_group_set(prs_after, new_gset)

        diffs = compare_prs(prs_before, prs_after)
        gs_added = [d for d in diffs
                    if d[1] == "Group Set" and d[0] == ADDED]
        assert len(gs_added) == 1
        assert gs_added[0][2] == "NEWGRP"

    def test_added_trunk_set_shows_added(self):
        """Adding a trunk set produces ADDED in trunk set category."""
        prs_before = parse_prs(CLAUDE)
        prs_after = parse_prs(CLAUDE)

        new_tset = make_trunk_set("NEWTRK", [(851.0, 851.0), (852.0, 852.0)])
        add_trunk_set(prs_after, new_tset)

        diffs = compare_prs(prs_before, prs_after)
        ts_added = [d for d in diffs
                    if d[1] == "Trunk Set" and d[0] == ADDED]
        assert len(ts_added) == 1
        assert ts_added[0][2] == "NEWTRK"

    def test_added_group_set_detail_has_tg_count(self):
        """ADDED group set detail shows talkgroup count."""
        prs_before = parse_prs(CLAUDE)
        prs_after = parse_prs(CLAUDE)

        new_gset = make_group_set("DETSET", [
            (10, "D1", "DETAIL ONE"),
            (20, "D2", "DETAIL TWO"),
            (30, "D3", "DETAIL THREE"),
        ])
        add_group_set(prs_after, new_gset)

        diffs = compare_prs(prs_before, prs_after)
        gs_added = [d for d in diffs
                    if d[1] == "Group Set" and d[0] == ADDED]
        assert "3" in gs_added[0][3]  # "3 talkgroups"

    def test_paws_vs_claude_group_set_differences(self):
        """PAWS vs CLAUDE shows specific group set differences."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        gs_diffs = [d for d in diffs if d[1] == "Group Set"]
        assert len(gs_diffs) > 0

        gs_removed = [d for d in gs_diffs if d[0] == REMOVED]
        assert len(gs_removed) == 7  # PAWS has 7 sets, all different names

        gs_added = [d for d in gs_diffs if d[0] == ADDED]
        assert len(gs_added) == 1  # claude has "GROUP SE"

    def test_paws_vs_claude_trunk_set_differences(self):
        """PAWS vs CLAUDE shows trunk set removals."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        ts_diffs = [d for d in diffs if d[1] == "Trunk Set"]
        ts_removed = [d for d in ts_diffs if d[0] == REMOVED]
        assert len(ts_removed) == 7  # PAWS has 7 trunk sets


# ═══════════════════════════════════════════════════════════════════════
# 4. TestFormatComparison
# ═══════════════════════════════════════════════════════════════════════


class TestFormatComparison:
    """Test format_comparison output formatting."""

    def test_empty_diffs_identical(self):
        """Empty diffs produce 'Files are identical.' message."""
        lines = format_comparison([])
        assert "Files are identical." in lines

    def test_empty_diffs_with_paths(self):
        """Empty diffs with paths show both paths and identical message."""
        lines = format_comparison([], "alpha.PRS", "beta.PRS")
        text = "\n".join(lines)
        assert "A: alpha.PRS" in text
        assert "B: beta.PRS" in text
        assert "Files are identical." in text

    def test_multiple_categories_grouped(self):
        """Multiple categories appear as separate groups."""
        diffs = [
            (ADDED, "Group Set", "SET A", "2 talkgroups"),
            (REMOVED, "Trunk Set", "SET B", "3 freqs"),
            (CHANGED, "File", "Size", "100 bytes"),
        ]
        lines = format_comparison(diffs)
        text = "\n".join(lines)
        assert "--- Group Set ---" in text
        assert "--- Trunk Set ---" in text
        assert "--- File ---" in text

    def test_summary_counts_correct(self):
        """Summary line shows correct added/removed/changed counts."""
        diffs = [
            (ADDED, "A", "x", "d"),
            (ADDED, "A", "y", "d"),
            (REMOVED, "B", "z", "d"),
            (CHANGED, "C", "w", "d"),
            (CHANGED, "C", "v", "d"),
            (CHANGED, "C", "u", "d"),
        ]
        lines = format_comparison(diffs)
        text = "\n".join(lines)
        assert "2 added" in text
        assert "1 removed" in text
        assert "3 changed" in text

    def test_diff_type_prefixes(self):
        """Each diff type uses correct prefix character."""
        diffs = [
            (ADDED, "Cat", "item1", "detail"),
            (REMOVED, "Cat", "item2", "detail"),
            (CHANGED, "Cat", "item3", "detail"),
            (SAME, "Cat", "item4", "detail"),
        ]
        lines = format_comparison(diffs)
        text = "\n".join(lines)
        assert "+ item1" in text
        assert "- item2" in text
        assert "~ item3" in text
        assert "= item4" in text

    def test_format_with_only_same(self):
        """SAME-only diffs still produce output (not 'identical')."""
        diffs = [(SAME, "File", "Sections", "26")]
        lines = format_comparison(diffs)
        # Should NOT say "Files are identical" since there are diffs
        assert "Files are identical." not in lines
        assert any("Summary" in line for line in lines)


# ═══════════════════════════════════════════════════════════════════════
# 5. TestCompareConvSets
# ═══════════════════════════════════════════════════════════════════════


class TestCompareConvSets:
    """Compare files with different conventional channel sets."""

    def test_paws_vs_claude_conv_set_diffs(self):
        """PAWS has conv sets that claude does not (FURRY WB, WA WIDE)."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        conv_diffs = [d for d in diffs if d[1] == "Conv Set"]
        removed = [d for d in conv_diffs if d[0] == REMOVED]
        names = {d[2] for d in removed}
        assert "WA WIDE" in names
        assert "FURRY WB" in names

    def test_conv_set_detail_has_channel_count(self):
        """REMOVED conv set detail shows channel count."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        wa_wide = [d for d in diffs
                   if d[1] == "Conv Set" and d[2] == "WA WIDE"]
        assert len(wa_wide) == 1
        assert "5" in wa_wide[0][3]  # "5 channels"


# ═══════════════════════════════════════════════════════════════════════
# 6. TestCompareIdenSets
# ═══════════════════════════════════════════════════════════════════════


class TestCompareIdenSets:
    """Compare files with different IDEN sets."""

    def test_paws_vs_claude_iden_set_diffs(self):
        """PAWS has IDEN sets that claude does not."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        iden_diffs = [d for d in diffs if d[1] == "IDEN Set"]
        removed = [d for d in iden_diffs if d[0] == REMOVED]
        removed_names = {d[2] for d in removed}
        assert "BEE00" in removed_names
        assert "58544" in removed_names
        assert "92738" in removed_names

    def test_claude_iden_set_added_in_reverse(self):
        """Claude's IDEN set appears as ADDED when comparing PAWS->CLAUDE."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        iden_added = [d for d in diffs
                      if d[1] == "IDEN Set" and d[0] == ADDED]
        assert len(iden_added) == 1
        assert iden_added[0][2] == "IDENT SE"

    def test_iden_detail_has_active_count(self):
        """IDEN set detail shows active element count."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)

        bee00 = [d for d in diffs
                 if d[1] == "IDEN Set" and d[2] == "BEE00"]
        assert len(bee00) == 1
        assert "4" in bee00[0][3]  # "4 active elements"


# ═══════════════════════════════════════════════════════════════════════
# 7. TestParseClaudeTest
# ═══════════════════════════════════════════════════════════════════════


class TestParseClaudeTest:
    """Parse claude test.PRS and verify structure."""

    def test_file_size(self, claude_prs):
        assert claude_prs.file_size == 9652

    def test_section_count(self, claude_prs):
        assert len(claude_prs.sections) == 26

    def test_has_cpersonality(self, claude_prs):
        sec = claude_prs.get_section_by_class("CPersonality")
        assert sec is not None

    def test_cpersonality_is_first(self, claude_prs):
        assert claude_prs.sections[0].class_name == "CPersonality"

    def test_exactly_one_cp25trksystem(self, claude_prs):
        secs = claude_prs.get_sections_by_class("CP25TrkSystem")
        assert len(secs) == 1

    def test_exactly_one_cconvsystem(self, claude_prs):
        secs = claude_prs.get_sections_by_class("CConvSystem")
        assert len(secs) == 1

    def test_exactly_one_cp25convsystem(self, claude_prs):
        secs = claude_prs.get_sections_by_class("CP25ConvSystem")
        assert len(secs) == 1

    def test_get_section_by_class_returns_section(self, claude_prs):
        sec = claude_prs.get_section_by_class("CTrunkChannel")
        assert sec is not None
        assert sec.class_name == "CTrunkChannel"
        assert len(sec.raw) > 0

    def test_get_sections_by_class_returns_list(self, claude_prs):
        secs = claude_prs.get_sections_by_class("CP25Group")
        assert isinstance(secs, list)
        assert len(secs) == 1

    def test_get_section_by_class_nonexistent(self, claude_prs):
        result = claude_prs.get_section_by_class("nonexistent")
        assert result is None

    def test_get_sections_by_class_nonexistent(self, claude_prs):
        result = claude_prs.get_sections_by_class("CSomethingFake")
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# 8. TestParsePawsovermaws
# ═══════════════════════════════════════════════════════════════════════


class TestParsePawsovermaws:
    """Parse PAWSOVERMAWS.PRS and verify structure."""

    def test_file_size(self, paws_prs):
        assert paws_prs.file_size == 46822

    def test_section_count(self, paws_prs):
        assert len(paws_prs.sections) == 63

    def test_has_one_cp25trksystem(self, paws_prs):
        secs = paws_prs.get_sections_by_class("CP25TrkSystem")
        assert len(secs) == 1

    def test_has_one_cconvsystem(self, paws_prs):
        secs = paws_prs.get_sections_by_class("CConvSystem")
        assert len(secs) == 1

    def test_conv_before_p25trk(self, paws_prs):
        """CConvSystem appears before CP25TrkSystem in section ordering."""
        conv_idx = None
        p25_idx = None
        for i, s in enumerate(paws_prs.sections):
            if s.class_name == "CConvSystem" and conv_idx is None:
                conv_idx = i
            if s.class_name == "CP25TrkSystem" and p25_idx is None:
                p25_idx = i
        assert conv_idx is not None
        assert p25_idx is not None
        assert conv_idx < p25_idx

    def test_summary_returns_string(self, paws_prs):
        s = paws_prs.summary()
        assert isinstance(s, str)

    def test_summary_contains_file_path(self, paws_prs):
        s = paws_prs.summary()
        assert "PAWSOVERMAWS" in s

    def test_summary_contains_section_count(self, paws_prs):
        s = paws_prs.summary()
        assert "63" in s


# ═══════════════════════════════════════════════════════════════════════
# 9. TestParsePrsBytes
# ═══════════════════════════════════════════════════════════════════════


class TestParsePrsBytes:
    """Test parse_prs_bytes produces same structure as parse_prs."""

    def test_bytes_parse_same_sections_claude(self, claude_prs, claude_bytes):
        """parse_prs_bytes produces same section count as parse_prs."""
        prs_from_bytes = parse_prs_bytes(claude_bytes)
        assert len(prs_from_bytes.sections) == len(claude_prs.sections)

    def test_bytes_parse_same_output_claude(self, claude_prs, claude_bytes):
        """parse_prs_bytes to_bytes produces original file bytes."""
        prs_from_bytes = parse_prs_bytes(claude_bytes)
        assert prs_from_bytes.to_bytes() == claude_bytes

    def test_bytes_parse_same_sections_paws(self, paws_prs, paws_bytes):
        """parse_prs_bytes produces same section count for PAWS."""
        prs_from_bytes = parse_prs_bytes(paws_bytes)
        assert len(prs_from_bytes.sections) == len(paws_prs.sections)

    def test_double_roundtrip_claude(self, claude_bytes):
        """to_bytes -> parse_prs_bytes -> to_bytes is stable."""
        prs1 = parse_prs_bytes(claude_bytes)
        bytes1 = prs1.to_bytes()
        prs2 = parse_prs_bytes(bytes1)
        bytes2 = prs2.to_bytes()
        assert bytes1 == bytes2

    def test_double_roundtrip_paws(self, paws_bytes):
        """to_bytes -> parse_prs_bytes -> to_bytes is stable for PAWS."""
        prs1 = parse_prs_bytes(paws_bytes)
        bytes1 = prs1.to_bytes()
        prs2 = parse_prs_bytes(bytes1)
        bytes2 = prs2.to_bytes()
        assert bytes1 == bytes2

    def test_class_names_match(self, claude_prs, claude_bytes):
        """Section class names match between file and bytes parsing."""
        prs_from_bytes = parse_prs_bytes(claude_bytes)
        for i, sec in enumerate(claude_prs.sections):
            assert sec.class_name == prs_from_bytes.sections[i].class_name


# ═══════════════════════════════════════════════════════════════════════
# 10. TestPRSFileMethods
# ═══════════════════════════════════════════════════════════════════════


class TestPRSFileMethods:
    """Test PRSFile methods: to_bytes, summary."""

    def test_to_bytes_claude_exact(self, claude_prs, claude_bytes):
        """to_bytes on claude test produces exact original file bytes."""
        assert claude_prs.to_bytes() == claude_bytes

    def test_to_bytes_paws_exact(self, paws_prs, paws_bytes):
        """to_bytes on PAWSOVERMAWS produces exact original file bytes."""
        assert paws_prs.to_bytes() == paws_bytes

    def test_summary_claude_has_path(self, claude_prs):
        """summary() contains the file path."""
        s = claude_prs.summary()
        assert "claude test" in s

    def test_summary_claude_has_section_count(self, claude_prs):
        """summary() contains the section count."""
        s = claude_prs.summary()
        assert "26" in s

    def test_summary_paws_has_path(self, paws_prs):
        """summary() contains the file path for PAWS."""
        s = paws_prs.summary()
        assert "PAWSOVERMAWS" in s

    def test_summary_paws_has_file_size(self, paws_prs):
        """summary() contains file size."""
        s = paws_prs.summary()
        assert "46822" in s


# ═══════════════════════════════════════════════════════════════════════
# 11. TestParserEdgeCases
# ═══════════════════════════════════════════════════════════════════════


class TestParserEdgeCases:
    """Edge cases: bad paths, empty data, no markers."""

    def test_nonexistent_file_raises(self):
        """parse_prs with nonexistent file raises an error."""
        with pytest.raises((FileNotFoundError, OSError)):
            parse_prs("C:/nonexistent/fake_file.PRS")

    def test_empty_data_raises_valueerror(self):
        """parse_prs_bytes with empty data raises ValueError."""
        with pytest.raises(ValueError, match="No ffff markers"):
            parse_prs_bytes(b"")

    def test_no_ffff_markers_raises_valueerror(self):
        """parse_prs_bytes with data lacking ffff markers raises ValueError."""
        with pytest.raises(ValueError, match="No ffff markers"):
            parse_prs_bytes(b"\x00\x01\x02\x03\x04\x05")

    def test_single_byte_raises_valueerror(self):
        """parse_prs_bytes with single byte raises ValueError."""
        with pytest.raises(ValueError, match="No ffff markers"):
            parse_prs_bytes(b"\xff")

    def test_minimal_ffff_data_parses(self):
        """parse_prs_bytes with minimal ffff + some data succeeds."""
        data = b"\xff\xff\x00\x01\x02"
        prs = parse_prs_bytes(data)
        assert len(prs.sections) == 1
        assert prs.sections[0].raw == data
        assert prs.to_bytes() == data
