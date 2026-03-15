"""Tests for PRS file comparison."""

import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.comparison import (
    compare_prs, compare_prs_files, format_comparison,
    ADDED, REMOVED, CHANGED, SAME,
)
from quickprs.injector import (
    add_group_set, make_group_set, add_trunk_set, make_trunk_set,
    add_p25_trunked_system, remove_system_config,
)
from quickprs.record_types import P25TrkSystemConfig

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_compare_identical():
    """Comparing a file to itself should show no added/removed/changed."""
    prs_a = parse_prs(CLAUDE)
    prs_b = parse_prs(CLAUDE)
    diffs = compare_prs(prs_a, prs_b)
    for dtype, cat, name, detail in diffs:
        assert dtype != ADDED
        assert dtype != REMOVED
        assert dtype != CHANGED


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
def test_compare_different_files():
    """PAWSOVERMAWS vs claude test should show differences."""
    diffs = compare_prs_files(PAWS, CLAUDE)
    assert len(diffs) > 0

    # PAWSOVERMAWS has more systems than claude test
    categories = set(d[1] for d in diffs)
    assert len(categories) > 0


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_compare_after_injection():
    """Adding a group set should show it as ADDED in comparison."""
    prs_before = parse_prs(CLAUDE)
    prs_after = parse_prs(CLAUDE)

    new_gset = make_group_set("TESTSET", [
        (100, "TEST 1", "TEST GROUP ONE"),
        (200, "TEST 2", "TEST GROUP TWO"),
    ])
    add_group_set(prs_after, new_gset)

    diffs = compare_prs(prs_before, prs_after)

    # Should have at least one ADDED or CHANGED in group sets
    group_diffs = [d for d in diffs if "Group" in d[1]]
    assert len(group_diffs) > 0
    has_change = any(d[0] in (ADDED, CHANGED) for d in group_diffs)
    assert has_change


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_compare_after_system_add():
    """Adding a full P25 system should show system as ADDED."""
    prs_before = parse_prs(CLAUDE)
    prs_after = parse_prs(CLAUDE)

    config = P25TrkSystemConfig(
        system_name="NEWCOMP",
        long_name="NEW COMPARE SYS",
        trunk_set_name="NEWCOMP",
        group_set_name="NEWCOMP",
        wan_name="NEWCOMP",
    )
    gset = make_group_set("NEWCOMP", [(500, "COMP 1", "COMPARE ONE")])
    tset = make_trunk_set("NEWCOMP", [(851.0125, 851.0125)])

    add_p25_trunked_system(prs_after, config,
                            trunk_set=tset, group_set=gset)

    diffs = compare_prs(prs_before, prs_after)
    added = [d for d in diffs if d[0] == ADDED]
    assert len(added) > 0

    # Should mention NEWCOMP somewhere
    all_names = [d[2] for d in diffs]
    assert any("NEWCOMP" in n or "COMPARE" in n for n in all_names)


def test_format_comparison():
    """format_comparison should produce readable output."""
    diffs = [
        (ADDED, "Group Set", "TESTSET", "2 talkgroups"),
        (REMOVED, "P25 Trunked", "OLD SYS", "system removed"),
        (CHANGED, "File", "Size", "9652 -> 12000 bytes (+2348)"),
    ]
    lines = format_comparison(diffs, "file_a.PRS", "file_b.PRS")
    text = "\n".join(lines)

    assert "file_a.PRS" in text
    assert "file_b.PRS" in text
    assert "TESTSET" in text
    assert "OLD SYS" in text
    assert "1 added" in text
    assert "1 removed" in text
    assert "1 changed" in text


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
def test_compare_pawsovermaws_has_systems():
    """PAWSOVERMAWS has systems that claude test doesn't."""
    prs_paws = parse_prs(PAWS)
    prs_claude = parse_prs(CLAUDE)
    diffs = compare_prs(prs_paws, prs_claude)

    # PAWSOVERMAWS has more group sets than claude test
    removed = [d for d in diffs if d[0] == REMOVED]
    assert len(removed) > 0  # PAWSOVERMAWS has things claude test doesn't


# ─── Edge cases ──────────────────────────────────────────────────

class TestComparisonEdgeCases:

    def test_format_empty_diffs(self):
        """No diffs should produce 'identical' message."""
        lines = format_comparison([])
        text = "\n".join(lines)
        assert "identical" in text.lower()

    def test_format_no_filepaths(self):
        """Without filepaths, no A:/B: header."""
        diffs = [(ADDED, "Cat", "Name", "detail")]
        lines = format_comparison(diffs)
        assert not any("A:" in l for l in lines)

    def test_format_same_entries(self):
        """SAME entries should use = prefix."""
        diffs = [(SAME, "File", "Sections", "26 -> 26")]
        lines = format_comparison(diffs)
        text = "\n".join(lines)
        assert "= Sections" in text
        assert "0 added, 0 removed, 0 changed" in text

    def test_compare_empty_prs(self):
        """Comparing two empty PRS objects."""
        from quickprs.prs_parser import PRSFile
        prs_a = PRSFile(sections=[], file_size=6)
        prs_b = PRSFile(sections=[], file_size=6)
        diffs = compare_prs(prs_a, prs_b)
        # Should not crash, should have at least the SAME sections entry
        assert any(d[1] == "File" for d in diffs)

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_compare_shows_section_diff(self):
        """Files with different named sections should show section diffs."""
        diffs = compare_prs_files(PAWS, CLAUDE)
        section_diffs = [d for d in diffs if d[1] == "Section"]
        # PAWS has sections claude doesn't (CAlertOpts, etc.)
        assert len(section_diffs) > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_compare_group_set_content_change(self):
        """Modified group set should show CHANGED with TG diff."""
        from copy import deepcopy
        prs_a = parse_prs(PAWS)
        prs_b = deepcopy(prs_a)
        # Add a talkgroup to an existing set
        new_gset = make_group_set("PSERN PD", [
            (9999, "EXTRA", "EXTRA TALKGROUP"),
        ])
        add_group_set(prs_b, new_gset)
        diffs = compare_prs(prs_a, prs_b)
        group_diffs = [d for d in diffs if d[1] == "Group Set"
                       and d[2] == "PSERN PD"]
        assert len(group_diffs) > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_compare_trunk_set_content_change(self):
        """Modified trunk set should show CHANGED with freq diff."""
        from copy import deepcopy
        prs_a = parse_prs(PAWS)
        prs_b = deepcopy(prs_a)
        new_tset = make_trunk_set("PSERN", [(999.0125, 999.0125)])
        add_trunk_set(prs_b, new_tset)
        diffs = compare_prs(prs_a, prs_b)
        trunk_diffs = [d for d in diffs if d[1] == "Trunk Set"
                       and d[2] == "PSERN"]
        assert len(trunk_diffs) > 0

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_compare_size_difference(self):
        """Files of different sizes should show size change."""
        diffs = compare_prs_files(PAWS, CLAUDE)
        size_diffs = [d for d in diffs if d[2] == "Size"]
        assert len(size_diffs) == 1
        assert "46,822" in size_diffs[0][3]
        assert "9,652" in size_diffs[0][3]

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_compare_iden_set_diff(self):
        """IDEN sets that differ should show active element counts."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)
        iden_diffs = [d for d in diffs if d[1] == "IDEN Set"]
        # PAWS has more IDEN sets than claude
        assert len(iden_diffs) > 0

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_compare_system_config_names(self):
        """System config comparison should find config long names."""
        prs_paws = parse_prs(PAWS)
        prs_claude = parse_prs(CLAUDE)
        diffs = compare_prs(prs_paws, prs_claude)
        config_diffs = [d for d in diffs if d[1] == "System Config"]
        assert len(config_diffs) > 0
