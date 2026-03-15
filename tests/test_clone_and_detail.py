"""Tests for system cloning and detailed comparison features."""

import pytest
import shutil
from pathlib import Path
from copy import deepcopy

from quickprs.cli import (
    run_cli, cmd_merge, cmd_create, cmd_clone, cmd_compare,
)
from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.prs_writer import write_prs
from quickprs.validation import validate_prs, ERROR, WARNING
from quickprs.injector import (
    clone_system, merge_prs, add_group_set, make_group_set,
    add_trunk_set, make_trunk_set,
)
from quickprs.comparison import (
    compare_prs, detailed_comparison, format_detailed_comparison,
    ADDED, REMOVED, CHANGED, SAME,
)
from quickprs.record_types import (
    parse_system_long_name, parse_system_short_name,
    is_system_config_data, parse_sets_from_sections,
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
)


TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Helpers ─────────────────────────────────────────────────────────


def _copy_prs(src, tmp_path, name="work.PRS"):
    """Copy a PRS file to tmp_path and return the new path."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


def _create_blank(tmp_path, name="blank.PRS"):
    """Create a blank PRS file and return its path."""
    out = tmp_path / name
    cmd_create(str(out))
    return str(out)


def _get_config_long_names(prs):
    """Get all system config long names from a PRS."""
    names = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            ln = parse_system_long_name(sec.raw)
            if ln:
                names.append(ln)
    return names


def _parse_group_sets(prs):
    sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, sec.raw, parse_group_section)


def _parse_trunk_sets(prs):
    sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if not sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, sec.raw,
                                    parse_trunk_channel_section)


def _parse_conv_sets(prs):
    sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not sec or not set_sec:
        return []
    return parse_sets_from_sections(set_sec.raw, sec.raw,
                                    parse_conv_channel_section)


# ═══════════════════════════════════════════════════════════════════════
# Feature 1: clone_system
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestCloneSystemFunction:
    """Test the clone_system() injector function directly."""

    def test_clone_psern_into_blank(self, tmp_path):
        """Clone PSERN SEATTLE from PAWSOVERMAWS into a blank PRS."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        result = clone_system(target, source, "PSERN SEATTLE")

        assert result['system'] == "PSERN SEATTLE"
        assert result['trunk_set'] is not None
        assert result['group_set'] is not None

    def test_clone_adds_system_config(self, tmp_path):
        """Cloned system should appear in target config names."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        clone_system(target, source, "PSERN SEATTLE")

        names = _get_config_long_names(target)
        assert "PSERN SEATTLE" in names

    def test_clone_adds_trunk_set(self, tmp_path):
        """Cloned P25 system should have its trunk set in target."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        result = clone_system(target, source, "PSERN SEATTLE")

        if result['trunk_set']:
            trunk_names = {s.name for s in _parse_trunk_sets(target)}
            assert result['trunk_set'] in trunk_names

    def test_clone_adds_group_set(self, tmp_path):
        """Cloned P25 system should have its group set in target."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        result = clone_system(target, source, "PSERN SEATTLE")

        if result['group_set']:
            group_names = {s.name for s in _parse_group_sets(target)}
            assert result['group_set'] in group_names

    def test_clone_skips_existing_system(self, tmp_path):
        """Cloning into a file that already has the system should skip."""
        target = cached_parse_prs(str(PAWS))
        source = cached_parse_prs(str(PAWS))

        result = clone_system(target, source, "PSERN SEATTLE")

        assert result['system'] is None
        assert result['trunk_set'] is None
        assert result['group_set'] is None

    def test_clone_not_found_raises(self, tmp_path):
        """Cloning a nonexistent system should raise ValueError."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        with pytest.raises(ValueError, match="not found"):
            clone_system(target, source, "NONEXISTENT SYSTEM")

    def test_clone_validates_clean(self, tmp_path):
        """Cloned file should validate with no errors."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        clone_system(target, source, "PSERN SEATTLE")

        issues = validate_prs(target)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_clone_roundtrip(self, tmp_path):
        """Cloned file should roundtrip through parse/write."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        clone_system(target, source, "PSERN SEATTLE")

        raw1 = target.to_bytes()
        out_path = str(tmp_path / "cloned.PRS")
        write_prs(target, out_path)
        prs2 = parse_prs(out_path)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_clone_conv_system(self, tmp_path):
        """Clone a conventional system from PAWSOVERMAWS."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        # Find a conv system in PAWS
        conv_names = []
        for sec in source.sections:
            if sec.class_name == "CConvSystem":
                short = parse_system_short_name(sec.raw)
                if short:
                    conv_names.append(short)

        if not conv_names:
            pytest.skip("No conv systems in PAWSOVERMAWS")

        # Find the long name for the first conv system
        conv_long_names = []
        for sec in source.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                ln = parse_system_long_name(sec.raw)
                if ln:
                    conv_long_names.append(ln)

        # Try cloning each conv-related long name until one succeeds
        found = False
        for ln in conv_long_names:
            try:
                result = clone_system(target, source, ln)
                if result['system'] and result.get('conv_set') is not None:
                    found = True
                    break
            except ValueError:
                continue

        if not found:
            pytest.skip("Could not find conv system to clone")

        assert result['system'] is not None

    def test_clone_preserves_target_data(self, tmp_path):
        """Cloning should not remove existing systems from target."""
        target = deepcopy(cached_parse_prs(str(CLAUDE)))
        source = cached_parse_prs(str(PAWS))
        before_names = set(_get_config_long_names(target))

        clone_system(target, source, "PSERN SEATTLE")

        after_names = set(_get_config_long_names(target))
        for name in before_names:
            assert name in after_names

    def test_clone_skips_existing_sets(self, tmp_path):
        """If target already has the trunk/group sets, they should be skipped."""
        # First clone to populate target
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))
        result1 = clone_system(target, source, "PSERN SEATTLE")

        # Remove the system config but keep the sets
        from quickprs.injector import remove_system_config
        remove_system_config(target, "PSERN SEATTLE")

        # Clone again — sets should already exist
        result2 = clone_system(target, source, "PSERN SEATTLE")

        assert result2['system'] == "PSERN SEATTLE"
        # Sets should be None (skipped because they already exist)
        if result1['trunk_set']:
            assert result2['trunk_set'] is None
        if result1['group_set']:
            assert result2['group_set'] is None

    def test_clone_result_keys(self, tmp_path):
        """clone_system result should have all expected keys."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = cached_parse_prs(str(PAWS))

        result = clone_system(target, source, "PSERN SEATTLE")

        assert 'system' in result
        assert 'trunk_set' in result
        assert 'group_set' in result
        assert 'iden_set' in result
        assert 'conv_set' in result


# ─── cmd_clone CLI ───────────────────────────────────────────────────


class TestCmdClone:
    """Test the clone CLI command."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_basic(self, capsys, tmp_path):
        """Basic clone should succeed."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        assert result == 0
        out = capsys.readouterr().out
        assert "Cloned" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_reports_copied_sets(self, capsys, tmp_path):
        """Clone should report which sets were copied."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        assert result == 0
        out = capsys.readouterr().out
        assert "Copied" in out or "Sets already" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_output_flag(self, capsys, tmp_path):
        """Clone with -o should write to separate file."""
        target = _create_blank(tmp_path, "target.PRS")
        out_file = str(tmp_path / "cloned.PRS")
        result = cmd_clone(target, str(PAWS), "PSERN SEATTLE",
                           output=out_file)
        assert result == 0
        assert Path(out_file).exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_into_existing(self, capsys, tmp_path):
        """Clone into file that already has the system should not error."""
        target = _copy_prs(PAWS, tmp_path, "target.PRS")
        result = cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        assert result == 0
        out = capsys.readouterr().out
        assert "already exists" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_not_found(self, capsys, tmp_path):
        """Clone nonexistent system should return 1."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_clone(target, str(PAWS), "NONEXISTENT")
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_validates_clean(self, capsys, tmp_path):
        """Cloned file should validate with no errors."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        prs = parse_prs(target)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_roundtrip(self, capsys, tmp_path):
        """Cloned file should roundtrip cleanly."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        raw1 = Path(target).read_bytes()
        prs = parse_prs(target)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_via_run_cli(self, capsys, tmp_path):
        """clone subcommand should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["clone", target, str(PAWS), "PSERN SEATTLE"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_output_via_run_cli(self, capsys, tmp_path):
        """clone -o flag should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        out_file = str(tmp_path / "out.PRS")
        result = run_cli(["clone", target, str(PAWS),
                          "PSERN SEATTLE", "-o", out_file])
        assert result == 0
        assert Path(out_file).exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_missing_target(self, capsys):
        """clone with missing target should return 1."""
        result = run_cli(["clone", "nonexistent.PRS", str(PAWS),
                          "PSERN SEATTLE"])
        assert result == 1

    def test_clone_missing_source(self, capsys, tmp_path):
        """clone with missing source should return 1."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["clone", target, "nonexistent.PRS",
                          "PSERN SEATTLE"])
        assert result == 1


# ═══════════════════════════════════════════════════════════════════════
# Feature 2: Detailed Comparison
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestDetailedComparison:
    """Test the detailed_comparison() function."""

    def test_identical_files_no_diffs(self):
        """Comparing identical files should show no differences."""
        prs_a = cached_parse_prs(CLAUDE)
        prs_b = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        assert detail['systems_a_only'] == []
        assert detail['systems_b_only'] == []
        assert detail['talkgroup_diffs'] == {}
        assert detail['freq_diffs'] == {}
        assert detail['conv_diffs'] == {}

    def test_different_files_show_systems(self):
        """PAWSOVERMAWS vs claude test should show system differences."""
        prs_paws = cached_parse_prs(PAWS)
        prs_claude = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_paws, prs_claude)

        # PAWS has systems claude test doesn't
        assert len(detail['systems_a_only']) > 0 or \
               len(detail['systems_b_only']) > 0

    def test_systems_both_populated(self):
        """Systems in both files should be listed."""
        prs_paws = cached_parse_prs(PAWS)
        prs_claude = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_paws, prs_claude)

        # systems_both may or may not be empty depending on file contents
        # but the key should exist
        assert 'systems_both' in detail

    def test_result_keys(self):
        """detailed_comparison result should have all expected keys."""
        prs_a = cached_parse_prs(CLAUDE)
        prs_b = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_a, prs_b)

        expected_keys = ['systems_a_only', 'systems_b_only',
                         'systems_both', 'talkgroup_diffs',
                         'freq_diffs', 'conv_diffs', 'option_diffs']
        for key in expected_keys:
            assert key in detail

    def test_talkgroup_diffs_after_add(self):
        """Adding talkgroups should show up in detailed comparison."""
        prs_a = cached_parse_prs(PAWS)
        prs_b = deepcopy(prs_a)

        # Add a talkgroup to an existing group set
        new_gset = make_group_set("PSERN PD", [
            (9999, "EXTRA", "EXTRA TALKGROUP"),
        ])
        add_group_set(prs_b, new_gset)

        detail = detailed_comparison(prs_a, prs_b)

        # Check if any talkgroup diff mentions the PSERN system
        has_tg_diff = False
        for sys_name, diffs in detail['talkgroup_diffs'].items():
            if diffs.get('added') or diffs.get('removed'):
                has_tg_diff = True
                break
        assert has_tg_diff

    def test_freq_diffs_after_add(self):
        """Adding trunk frequencies should show up in detailed comparison."""
        prs_a = cached_parse_prs(PAWS)
        prs_b = deepcopy(prs_a)

        new_tset = make_trunk_set("PSERN", [(999.0125, 999.0125)])
        add_trunk_set(prs_b, new_tset)

        detail = detailed_comparison(prs_a, prs_b)

        assert len(detail['freq_diffs']) > 0

    def test_option_diffs_between_files(self):
        """Different files should show option differences."""
        prs_paws = cached_parse_prs(PAWS)
        prs_claude = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_paws, prs_claude)

        # option_diffs should be a list (may be empty if options are same)
        assert isinstance(detail['option_diffs'], list)


class TestFormatDetailedComparison:
    """Test the format_detailed_comparison() function."""

    def test_format_no_diffs(self):
        """No differences should show 'No differences found'."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': [],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "No differences found" in text

    def test_format_with_systems_a_only(self):
        """Systems only in A should be listed with -."""
        detail = {
            'systems_a_only': ['SYSTEM A'],
            'systems_b_only': [],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "SYSTEM A" in text
        assert "Only in A" in text

    def test_format_with_systems_b_only(self):
        """Systems only in B should be listed with +."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': ['SYSTEM B'],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "SYSTEM B" in text
        assert "Only in B" in text

    def test_format_with_talkgroup_diffs(self):
        """Talkgroup differences should be formatted."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': [],
            'systems_both': ['MYSYS'],
            'talkgroup_diffs': {
                'MYSYS': {
                    'added': [(100, 'TG100', 'TALKGROUP 100')],
                    'removed': [(200, 'TG200', 'TALKGROUP 200')],
                }
            },
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "TG100" in text
        assert "TG200" in text
        assert "+ 100" in text
        assert "- 200" in text

    def test_format_with_freq_diffs(self):
        """Trunk frequency differences should be formatted."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': [],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {
                'PSERN': {
                    'added': [851.0125],
                    'removed': [852.0125],
                }
            },
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "851.01250" in text
        assert "852.01250" in text

    def test_format_with_option_diffs(self):
        """Option differences should be formatted."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': [],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [
                ('gps.gpsMode', 'OFF', 'ON'),
            ],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "gps.gpsMode" in text
        assert "OFF" in text
        assert "ON" in text

    def test_format_with_filepaths(self):
        """File paths should be shown in header."""
        detail = {
            'systems_a_only': [],
            'systems_b_only': [],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [],
        }
        lines = format_detailed_comparison(detail, "a.PRS", "b.PRS")
        text = "\n".join(lines)
        assert "a.PRS" in text
        assert "b.PRS" in text

    def test_format_summary_counts(self):
        """Summary should show correct counts."""
        detail = {
            'systems_a_only': ['SYS1', 'SYS2'],
            'systems_b_only': ['SYS3'],
            'systems_both': [],
            'talkgroup_diffs': {},
            'freq_diffs': {},
            'conv_diffs': {},
            'option_diffs': [('field', 'a', 'b')],
        }
        lines = format_detailed_comparison(detail)
        text = "\n".join(lines)
        assert "2 system(s) only in A" in text
        assert "1 system(s) only in B" in text
        assert "1 option change(s)" in text

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_format_real_files(self):
        """Format detailed comparison between real PRS files."""
        prs_paws = cached_parse_prs(PAWS)
        prs_claude = cached_parse_prs(CLAUDE)
        detail = detailed_comparison(prs_paws, prs_claude)
        lines = format_detailed_comparison(detail, str(PAWS), str(CLAUDE))
        text = "\n".join(lines)
        assert "=== Systems ===" in text
        assert len(lines) > 5


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestCmdCompareDetail:
    """Test the --detail flag for cmd_compare."""

    def test_compare_detail_flag(self, capsys):
        """compare --detail should show detailed output."""
        result = cmd_compare(str(PAWS), str(CLAUDE), detail=True)
        out = capsys.readouterr().out
        assert "=== Systems ===" in out

    def test_compare_no_detail(self, capsys):
        """compare without --detail should not show detailed output."""
        result = cmd_compare(str(PAWS), str(CLAUDE), detail=False)
        out = capsys.readouterr().out
        assert "=== Systems ===" not in out

    def test_compare_detail_identical(self, capsys):
        """compare --detail on identical files should show no differences."""
        result = cmd_compare(str(CLAUDE), str(CLAUDE), detail=True)
        out = capsys.readouterr().out
        assert "No differences found" in out

    def test_compare_detail_via_run_cli(self, capsys):
        """compare --detail should work via run_cli."""
        result = run_cli(["compare", str(PAWS), str(CLAUDE), "--detail"])
        out = capsys.readouterr().out
        assert "=== Systems ===" in out

    def test_compare_without_detail_via_run_cli(self, capsys):
        """compare without --detail via run_cli should not show detail."""
        result = run_cli(["compare", str(PAWS), str(CLAUDE)])
        out = capsys.readouterr().out
        assert "=== Systems ===" not in out


# ─── Clone + Compare integration ─────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestCloneCompareIntegration:
    """Test clone and detailed comparison together."""

    def test_clone_then_compare_shows_addition(self, capsys, tmp_path):
        """After cloning a system, detailed comparison should show it."""
        blank_path = _create_blank(tmp_path, "blank.PRS")
        target_path = str(tmp_path / "cloned.PRS")
        cmd_clone(blank_path, str(PAWS), "PSERN SEATTLE",
                  output=target_path)

        prs_blank = parse_prs(blank_path)
        prs_cloned = parse_prs(target_path)
        detail = detailed_comparison(prs_blank, prs_cloned)

        assert "PSERN SEATTLE" in detail['systems_b_only']

    def test_clone_twice_no_duplicate(self, capsys, tmp_path):
        """Cloning the same system twice should not duplicate it."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        result = cmd_clone(target, str(PAWS), "PSERN SEATTLE")
        assert result == 0

        prs = parse_prs(target)
        names = _get_config_long_names(prs)
        assert names.count("PSERN SEATTLE") == 1
