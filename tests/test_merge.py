"""Tests for PRS file merging and template-based injection."""

import pytest
import shutil
from pathlib import Path

from quickprs.cli import (
    run_cli, cmd_merge, cmd_inject_conv, cmd_create,
)
from quickprs.prs_parser import parse_prs
from quickprs.validation import validate_prs, ERROR, WARNING
from quickprs.injector import merge_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
CONV_CSV = TESTDATA / "test_conv_channels.csv"


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


def _count_systems(prs, class_name):
    """Count system header sections of a given class."""
    return len(prs.get_sections_by_class(class_name))


def _get_system_names(prs, class_name):
    """Get short names of systems of a given class."""
    from quickprs.record_types import parse_system_short_name
    names = set()
    for sec in prs.get_sections_by_class(class_name):
        name = parse_system_short_name(sec.raw)
        if name:
            names.add(name)
    return names


def _count_group_sets(prs):
    from quickprs.cli import _parse_group_sets
    return _parse_group_sets(prs)


def _count_trunk_sets(prs):
    from quickprs.cli import _parse_trunk_sets
    return _parse_trunk_sets(prs)


def _count_conv_sets(prs):
    from quickprs.cli import _parse_conv_sets
    return _parse_conv_sets(prs)


# ─── merge_prs function ──────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestMergePrsFunction:
    """Test the merge_prs() injector function directly."""

    def test_merge_into_blank(self, tmp_path):
        """Merge PAWSOVERMAWS into a blank PRS — all systems copied."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats = merge_prs(target, source)

        assert stats['p25_added'] > 0
        assert stats['p25_skipped'] == 0

    def test_merge_returns_stats(self, tmp_path):
        """merge_prs should return a stats dict."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats = merge_prs(target, source)

        assert 'p25_added' in stats
        assert 'p25_skipped' in stats
        assert 'conv_added' in stats
        assert 'conv_skipped' in stats

    def test_merge_systems_only(self, tmp_path):
        """Merge with include_channels=False should only add P25 systems."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats = merge_prs(target, source,
                          include_systems=True, include_channels=False)

        assert stats['conv_added'] == 0
        assert stats['conv_skipped'] == 0

    def test_merge_channels_only(self, tmp_path):
        """Merge with include_systems=False should only add conv systems."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats = merge_prs(target, source,
                          include_systems=False, include_channels=True)

        assert stats['p25_added'] == 0
        assert stats['p25_skipped'] == 0

    def test_merge_skips_duplicates(self, tmp_path):
        """Merging same source twice should skip on second merge."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats1 = merge_prs(target, source)
        first_added = stats1['p25_added'] + stats1['conv_added']
        assert first_added > 0

        # Merge again — all should be skipped
        stats2 = merge_prs(target, source)
        assert stats2['p25_added'] == 0
        assert stats2['conv_added'] == 0
        second_skipped = stats2['p25_skipped'] + stats2['conv_skipped']
        assert second_skipped > 0

    def test_merge_nothing_disabled(self, tmp_path):
        """Merge with both disabled should do nothing."""
        blank_path = _create_blank(tmp_path)
        target = parse_prs(blank_path)
        source = parse_prs(str(PAWS))

        stats = merge_prs(target, source,
                          include_systems=False, include_channels=False)

        assert stats['p25_added'] == 0
        assert stats['conv_added'] == 0
        assert stats['p25_skipped'] == 0
        assert stats['conv_skipped'] == 0


# ─── cmd_merge CLI ────────────────────────────────────────────────────


class TestCmdMerge:
    """Test the merge CLI command."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_basic(self, capsys, tmp_path):
        """Basic merge should succeed and print summary."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_merge(target, str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "Merged" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_reports_counts(self, capsys, tmp_path):
        """Merge should report added/skipped counts."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_merge(target, str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "added" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_output_flag(self, capsys, tmp_path):
        """Merge with -o should write to separate file."""
        target = _create_blank(tmp_path, "target.PRS")
        out_file = str(tmp_path / "merged.PRS")
        result = cmd_merge(target, str(PAWS), output=out_file)
        assert result == 0
        assert Path(out_file).exists()

    @pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
    def test_merge_into_paws(self, capsys, tmp_path):
        """Merge claude test into PAWSOVERMAWS."""
        target = _copy_prs(PAWS, tmp_path, "target.PRS")
        result = cmd_merge(target, str(CLAUDE))
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_systems_only_flag(self, capsys, tmp_path):
        """--systems flag should only merge P25 systems."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_merge(target, str(PAWS),
                           include_systems=True, include_channels=False)
        assert result == 0
        prs = parse_prs(target)
        # Should have P25 systems but no conv from PAWS
        p25_names = _get_system_names(prs, "CP25TrkSystem")
        assert len(p25_names) > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_channels_only_flag(self, capsys, tmp_path):
        """--channels flag should only merge conv systems."""
        target = _create_blank(tmp_path, "target.PRS")
        result = cmd_merge(target, str(PAWS),
                           include_systems=False, include_channels=True)
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_duplicate_skip(self, capsys, tmp_path):
        """Merging source with existing systems should skip duplicates."""
        target = _copy_prs(PAWS, tmp_path, "target.PRS")
        result = cmd_merge(target, str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        assert "skipped" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_validates_clean(self, capsys, tmp_path):
        """Merged file should validate with no errors."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))
        prs = parse_prs(target)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_roundtrip(self, capsys, tmp_path):
        """Merged file should roundtrip through parse/write."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))
        raw1 = Path(target).read_bytes()
        prs = parse_prs(target)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_via_run_cli(self, capsys, tmp_path):
        """merge subcommand should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["merge", target, str(PAWS)])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_all_flag_via_cli(self, capsys, tmp_path):
        """merge --all should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["merge", target, str(PAWS), "--all"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_systems_flag_via_cli(self, capsys, tmp_path):
        """merge --systems should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["merge", target, str(PAWS), "--systems"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_channels_flag_via_cli(self, capsys, tmp_path):
        """merge --channels should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["merge", target, str(PAWS), "--channels"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_output_flag_via_cli(self, capsys, tmp_path):
        """merge -o flag should work via run_cli."""
        target = _create_blank(tmp_path, "target.PRS")
        out_file = str(tmp_path / "out.PRS")
        result = run_cli(["merge", target, str(PAWS), "-o", out_file])
        assert result == 0
        assert Path(out_file).exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_missing_target(self, capsys):
        """merge with missing target should return 1."""
        result = run_cli(["merge", "nonexistent.PRS", str(PAWS)])
        assert result == 1

    def test_merge_missing_source(self, capsys, tmp_path):
        """merge with missing source should return 1."""
        target = _create_blank(tmp_path, "target.PRS")
        result = run_cli(["merge", target, "nonexistent.PRS"])
        assert result == 1


# ─── Merge data integrity ────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestMergeDataIntegrity:
    """Verify that merged data is structurally correct."""

    def test_merged_trunk_sets_present(self, capsys, tmp_path):
        """After merging PAWS into blank, trunk sets should exist."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))
        prs = parse_prs(target)
        sets = _count_trunk_sets(prs)
        assert len(sets) > 0
        names = {s.name for s in sets}
        assert "PSERN" in names

    def test_merged_group_sets_present(self, capsys, tmp_path):
        """After merging PAWS into blank, group sets should exist."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))
        prs = parse_prs(target)
        sets = _count_group_sets(prs)
        assert len(sets) > 0

    def test_merged_conv_sets_present(self, capsys, tmp_path):
        """After merging PAWS into blank, conv sets should exist."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))
        prs = parse_prs(target)
        sets = _count_conv_sets(prs)
        # Blank PRS has 1 conv set, PAWS adds more
        assert len(sets) > 1

    def test_double_roundtrip(self, capsys, tmp_path):
        """Merged file should survive two parse/write roundtrips."""
        target = _create_blank(tmp_path, "target.PRS")
        cmd_merge(target, str(PAWS))

        # First roundtrip
        prs1 = parse_prs(target)
        raw1 = prs1.to_bytes()

        # Write and re-read
        from quickprs.prs_writer import write_prs
        target2 = str(tmp_path / "rt2.PRS")
        write_prs(prs1, target2)

        # Second roundtrip
        prs2 = parse_prs(target2)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_merge_preserves_target_data(self, capsys, tmp_path):
        """Merging into PAWS should preserve its existing systems."""
        target = _copy_prs(PAWS, tmp_path, "target.PRS")
        prs_before = parse_prs(str(PAWS))
        p25_before = _get_system_names(prs_before, "CP25TrkSystem")

        cmd_merge(target, str(CLAUDE))

        prs_after = parse_prs(target)
        p25_after = _get_system_names(prs_after, "CP25TrkSystem")

        # All original systems should still be present
        for name in p25_before:
            assert name in p25_after

    def test_merge_file_grows(self, capsys, tmp_path):
        """Merged file should be larger than blank."""
        target = _create_blank(tmp_path, "target.PRS")
        orig_size = Path(target).stat().st_size
        cmd_merge(target, str(PAWS))
        new_size = Path(target).stat().st_size
        assert new_size > orig_size


# ─── Template injection via CLI ──────────────────────────────────────


class TestTemplateInjection:
    """Test inject conv --template via CLI."""

    def test_inject_murs_template(self, capsys, tmp_path):
        """Inject MURS template should succeed."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "MURS", template="murs")
        assert result == 0
        out = capsys.readouterr().out
        assert "5 channels" in out
        assert "template 'murs'" in out

    def test_inject_gmrs_template(self, capsys, tmp_path):
        """Inject GMRS template should succeed."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "GMRS", template="gmrs")
        assert result == 0
        out = capsys.readouterr().out
        assert "22 channels" in out

    def test_inject_frs_template(self, capsys, tmp_path):
        """Inject FRS template should succeed."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "FRS", template="frs")
        assert result == 0

    def test_inject_marine_template(self, capsys, tmp_path):
        """Inject marine template should succeed."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "MARINE", template="marine")
        assert result == 0

    def test_inject_noaa_template(self, capsys, tmp_path):
        """Inject NOAA template should succeed."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "NOAA", template="noaa")
        assert result == 0
        out = capsys.readouterr().out
        assert "7 channels" in out

    def test_inject_template_validates_clean(self, capsys, tmp_path):
        """Template-injected file should validate with no errors."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", template="murs")
        prs = parse_prs(prs_file)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

    def test_inject_template_roundtrip(self, capsys, tmp_path):
        """Template-injected file should roundtrip cleanly."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", template="murs")
        raw1 = Path(prs_file).read_bytes()
        prs = parse_prs(prs_file)
        raw2 = prs.to_bytes()
        assert raw1 == raw2

    def test_inject_template_channels_correct(self, capsys, tmp_path):
        """Template channels should have correct frequencies."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "NOAA", template="noaa")
        prs = parse_prs(prs_file)
        sets = _count_conv_sets(prs)
        noaa = [s for s in sets if s.name == "NOAA"]
        assert len(noaa) == 1
        assert len(noaa[0].channels) == 7
        # Check first frequency
        assert abs(noaa[0].channels[0].tx_freq - 162.400) < 0.001

    def test_inject_template_output_flag(self, capsys, tmp_path):
        """Template inject with -o should write to separate file."""
        prs_file = _create_blank(tmp_path, "input.PRS")
        out_file = str(tmp_path / "output.PRS")
        result = cmd_inject_conv(prs_file, "MURS", template="murs",
                                 output=out_file)
        assert result == 0
        assert Path(out_file).exists()

    def test_inject_unknown_template(self, capsys, tmp_path):
        """Unknown template should return 1."""
        prs_file = _create_blank(tmp_path)
        result = cmd_inject_conv(prs_file, "BAD", template="nonexistent")
        assert result == 1

    def test_inject_template_via_run_cli(self, capsys, tmp_path):
        """inject conv --template should work via run_cli."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "MURS",
            "--template", "murs",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "5 channels" in out

    def test_inject_gmrs_via_run_cli(self, capsys, tmp_path):
        """inject conv --template gmrs via run_cli."""
        prs_file = _create_blank(tmp_path)
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "GMRS",
            "--template", "gmrs",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "22 channels" in out

    def test_inject_template_with_output_via_cli(self, capsys, tmp_path):
        """inject conv --template -o via run_cli."""
        prs_file = _create_blank(tmp_path)
        out_file = str(tmp_path / "out.PRS")
        result = run_cli([
            "inject", prs_file, "conv",
            "--name", "NOAA",
            "--template", "noaa",
            "-o", out_file,
        ])
        assert result == 0
        assert Path(out_file).exists()

    def test_csv_and_template_mutually_exclusive(self, tmp_path):
        """--channels-csv and --template should be mutually exclusive."""
        prs_file = _create_blank(tmp_path)
        # argparse should reject both at once
        with pytest.raises(SystemExit):
            run_cli([
                "inject", prs_file, "conv",
                "--name", "TEST",
                "--channels-csv", str(CONV_CSV),
                "--template", "murs",
            ])

    def test_inject_all_templates_validate(self, capsys, tmp_path):
        """Every template should produce a valid PRS file."""
        from quickprs.templates import get_template_names
        for tmpl_name in get_template_names():
            prs_file = _create_blank(tmp_path, f"{tmpl_name}.PRS")
            name = tmpl_name[:8].upper()
            result = cmd_inject_conv(prs_file, name, template=tmpl_name)
            assert result == 0, f"Template '{tmpl_name}' injection failed"
            prs = parse_prs(prs_file)
            issues = validate_prs(prs)
            errors = [m for s, m in issues if s == ERROR]
            assert errors == [], \
                f"Template '{tmpl_name}' validation errors: {errors}"

    def test_inject_all_templates_roundtrip(self, capsys, tmp_path):
        """Every template should roundtrip cleanly."""
        from quickprs.templates import get_template_names
        for tmpl_name in get_template_names():
            prs_file = _create_blank(tmp_path, f"rt_{tmpl_name}.PRS")
            name = tmpl_name[:8].upper()
            cmd_inject_conv(prs_file, name, template=tmpl_name)
            raw1 = Path(prs_file).read_bytes()
            prs = parse_prs(prs_file)
            raw2 = prs.to_bytes()
            assert raw1 == raw2, \
                f"Template '{tmpl_name}' roundtrip failed"

    def test_multiple_templates_same_file(self, capsys, tmp_path):
        """Injecting multiple templates into same file should work."""
        prs_file = _create_blank(tmp_path)
        cmd_inject_conv(prs_file, "MURS", template="murs")
        cmd_inject_conv(prs_file, "NOAA", template="noaa")
        cmd_inject_conv(prs_file, "GMRS", template="gmrs")

        prs = parse_prs(prs_file)
        sets = _count_conv_sets(prs)
        names = {s.name for s in sets}
        assert "MURS" in names
        assert "NOAA" in names
        assert "GMRS" in names

        # Validate
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors: {errors}"

        # Roundtrip
        raw1 = Path(prs_file).read_bytes()
        raw2 = prs.to_bytes()
        assert raw1 == raw2
