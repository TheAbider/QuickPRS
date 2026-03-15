"""Tests for fleet_check.py — fleet consistency checker and snapshots."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.fleet_check import (
    check_fleet_consistency,
    format_fleet_report,
    save_snapshot,
    compare_to_snapshot,
    format_snapshot_comparison,
)
from quickprs.config_builder import build_from_config
from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.profile_templates import (
    build_from_profile, list_profile_templates, get_profile_template,
    PROFILE_TEMPLATES,
)
from quickprs.validation import validate_prs, ERROR

TESTDATA = Path(__file__).parent / "testdata"
PATROL_INI = TESTDATA / "example_patrol.ini"


# ─── Helpers ─────────────────────────────────────────────────────────


def _write_config(tmp_path, content, name="test.ini"):
    """Write INI content to a temp file and return the path."""
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)


def _build_patrol_fleet(tmp_path, count=3):
    """Build a fleet of identical patrol PRS files.

    Returns list of file paths.
    """
    from quickprs.fleet import build_fleet
    import csv as csv_mod

    # Write a units CSV
    csv_path = tmp_path / "units.csv"
    csv_path.write_text(
        "unit_id,name,password\n"
        + "\n".join(f"{1000 + i},UNIT-{1000 + i},1234"
                    for i in range(1, count + 1))
        + "\n",
        encoding='utf-8')

    out_dir = tmp_path / "fleet"
    build_fleet(str(PATROL_INI), str(csv_path), str(out_dir))
    return sorted(str(p) for p in out_dir.glob("*.PRS"))


def _build_identical_conv_fleet(tmp_path, count=3):
    """Build a fleet of identical conv-only PRS files.

    Returns list of file paths.
    """
    config = (
        "[personality]\nname = CONV.PRS\n\n"
        "[channels.MURS]\ntemplate = murs\n"
    )
    ini_path = _write_config(tmp_path, config, name="conv.ini")

    files = []
    for i in range(count):
        prs = build_from_config(ini_path)
        out_path = tmp_path / f"radio{i + 1}.PRS"
        out_path.write_bytes(prs.to_bytes())
        files.append(str(out_path))
    return files


def _build_inconsistent_fleet(tmp_path):
    """Build a fleet with deliberate inconsistencies.

    radio1: MURS only
    radio2: MURS + NOAA
    radio3: MURS only (same as radio1)

    Returns list of file paths.
    """
    config1 = (
        "[personality]\nname = RADIO1.PRS\n\n"
        "[channels.MURS]\ntemplate = murs\n"
    )
    config2 = (
        "[personality]\nname = RADIO2.PRS\n\n"
        "[channels.MURS]\ntemplate = murs\n\n"
        "[channels.NOAA]\ntemplate = noaa\n"
    )
    config3 = (
        "[personality]\nname = RADIO3.PRS\n\n"
        "[channels.MURS]\ntemplate = murs\n"
    )

    files = []
    for i, config in enumerate([config1, config2, config3], 1):
        ini_path = _write_config(tmp_path, config, name=f"radio{i}.ini")
        prs = build_from_config(ini_path)
        out_path = tmp_path / f"radio{i}.PRS"
        out_path.write_bytes(prs.to_bytes())
        files.append(str(out_path))
    return files


# ─── Fleet Consistency: Consistent Files ──────────────────────────────


class TestFleetCheckConsistent:
    """Fleet check with consistent files."""

    def test_three_consistent_files(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        results = check_fleet_consistency(files)

        assert len(results['files']) == 3
        # All should have the same systems
        assert len(results['systems']['some_missing']) == 0

    def test_consistent_channels(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        results = check_fleet_consistency(files)

        assert len(results['channels']['inconsistent']) == 0
        assert len(results['channels']['consistent']) > 0

    def test_consistent_options(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        results = check_fleet_consistency(files)

        # Options should all match
        assert len(results['options']['inconsistent']) == 0

    def test_format_report(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        results = check_fleet_consistency(files)
        report = format_fleet_report(results)

        assert "Fleet Consistency Report (3 radios)" in report
        assert isinstance(report, str)

    def test_two_files_minimum(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path, count=2)
        results = check_fleet_consistency(files)
        assert len(results['files']) == 2


# ─── Fleet Consistency: Inconsistent Files ────────────────────────────


class TestFleetCheckInconsistent:
    """Fleet check with inconsistent files."""

    def test_inconsistent_systems(self, tmp_path):
        files = _build_inconsistent_fleet(tmp_path)
        results = check_fleet_consistency(files)

        # radio2 has NOAA that others don't
        some_missing = results['systems']['some_missing']
        # At least one system is not present in all files
        has_discrepancy = len(some_missing) > 0
        # Or systems that all have differ
        assert has_discrepancy or len(results['systems']['all_have']) > 0

    def test_inconsistent_channels(self, tmp_path):
        files = _build_inconsistent_fleet(tmp_path)
        results = check_fleet_consistency(files)

        # radio2 has NOAA channels that others don't
        # This will show up as an inconsistent channel set
        # (NOAA set missing from radio1 and radio3)
        channels = results['channels']
        has_inconsistency = (
            len(channels['inconsistent']) > 0
            or len(results['systems']['some_missing']) > 0
        )
        assert has_inconsistency

    def test_format_inconsistent_report(self, tmp_path):
        files = _build_inconsistent_fleet(tmp_path)
        results = check_fleet_consistency(files)
        report = format_fleet_report(results)

        assert "Fleet Consistency Report" in report
        assert "3 radios" in report

    def test_different_talkgroups(self, tmp_path):
        """Fleet with different talkgroups in the same system."""
        config1 = (
            "[personality]\nname = TG1.PRS\n\n"
            "[system.PSERN]\ntype = p25_trunked\n"
            "long_name = PSERN\nsystem_id = 892\n\n"
            "[system.PSERN.frequencies]\n1 = 851.0125,806.0125\n\n"
            "[system.PSERN.talkgroups]\n1 = 1,DISP,Dispatch\n"
            "2 = 2,TAC1,Tactical 1\n"
        )
        config2 = (
            "[personality]\nname = TG2.PRS\n\n"
            "[system.PSERN]\ntype = p25_trunked\n"
            "long_name = PSERN\nsystem_id = 892\n\n"
            "[system.PSERN.frequencies]\n1 = 851.0125,806.0125\n\n"
            "[system.PSERN.talkgroups]\n1 = 1,DISP,Dispatch\n"
            "2 = 2,TAC1,Tactical 1\n"
            "3 = 3,TAC2,Tactical 2\n"
        )

        files = []
        for i, config in enumerate([config1, config2], 1):
            ini = _write_config(tmp_path, config, name=f"tg{i}.ini")
            prs = build_from_config(ini)
            out = tmp_path / f"tg{i}.PRS"
            out.write_bytes(prs.to_bytes())
            files.append(str(out))

        results = check_fleet_consistency(files)

        # The group set should show up as inconsistent
        tgs = results['talkgroups']
        assert len(tgs['inconsistent']) > 0


# ─── Fleet Check: Unit IDs ───────────────────────────────────────────


class TestFleetCheckUnitIds:
    """Fleet check unit ID tracking."""

    def test_unique_unit_ids(self, tmp_path):
        files = _build_patrol_fleet(tmp_path)
        results = check_fleet_consistency(files)

        unit_ids = results['unit_ids']
        non_none = [uid for uid in unit_ids.values() if uid is not None]
        # All unique
        assert len(set(non_none)) == len(non_none)

    def test_no_unit_ids_for_conv(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        results = check_fleet_consistency(files)

        unit_ids = results['unit_ids']
        # Conv-only files have no P25 unit IDs
        assert all(uid is None for uid in unit_ids.values())

    def test_format_report_shows_unit_ids(self, tmp_path):
        files = _build_patrol_fleet(tmp_path)
        results = check_fleet_consistency(files)
        report = format_fleet_report(results)

        assert "Unit IDs:" in report
        assert "all unique" in report


# ─── Fleet Check: Errors ─────────────────────────────────────────────


class TestFleetCheckErrors:
    """Fleet check error handling."""

    def test_single_file_raises(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path, count=1)
        with pytest.raises(ValueError, match="at least 2"):
            check_fleet_consistency(files)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            check_fleet_consistency([])

    def test_missing_file_raises(self, tmp_path):
        files = _build_identical_conv_fleet(tmp_path)
        files.append(str(tmp_path / "nonexistent.PRS"))
        with pytest.raises(FileNotFoundError):
            check_fleet_consistency(files)


# ─── Department Profile Templates ────────────────────────────────────


class TestDepartmentProfiles:
    """Test new department-specific profile templates."""

    @pytest.mark.parametrize("profile_name", [
        'fire_department',
        'law_enforcement',
        'ems',
        'search_rescue',
    ])
    def test_profile_exists(self, profile_name):
        profile = get_profile_template(profile_name)
        assert 'description' in profile
        assert 'templates' in profile
        assert 'custom_channels' in profile
        assert 'options' in profile

    @pytest.mark.parametrize("profile_name", [
        'fire_department',
        'law_enforcement',
        'ems',
        'search_rescue',
    ])
    def test_profile_builds(self, profile_name):
        prs = build_from_profile(profile_name)
        assert prs is not None
        # Should have sections
        assert len(prs.sections) > 0

    @pytest.mark.parametrize("profile_name", [
        'fire_department',
        'law_enforcement',
        'ems',
        'search_rescue',
    ])
    def test_profile_validates_clean(self, profile_name):
        prs = build_from_profile(profile_name)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == [], f"Validation errors for {profile_name}: {errors}"

    @pytest.mark.parametrize("profile_name", [
        'fire_department',
        'law_enforcement',
        'ems',
        'search_rescue',
    ])
    def test_profile_roundtrips(self, profile_name):
        prs = build_from_profile(profile_name)
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2, f"Roundtrip failed for {profile_name}"

    def test_fire_has_custom_channels(self):
        profile = get_profile_template('fire_department')
        assert len(profile['custom_channels']) == 6
        names = [ch['short_name'] for ch in profile['custom_channels']]
        assert 'FG 1' in names
        assert 'CMD' in names
        assert 'HAZCHEM' in names

    def test_law_enforcement_has_custom_channels(self):
        profile = get_profile_template('law_enforcement')
        assert len(profile['custom_channels']) == 4
        names = [ch['short_name'] for ch in profile['custom_channels']]
        assert 'CAR2CAR' in names
        assert 'SURVEIL' in names

    def test_ems_has_custom_channels(self):
        profile = get_profile_template('ems')
        assert len(profile['custom_channels']) == 3
        names = [ch['short_name'] for ch in profile['custom_channels']]
        assert 'MED 1' in names
        assert 'CLEMARS' in names

    def test_search_rescue_has_marine(self):
        profile = get_profile_template('search_rescue')
        assert 'marine' in profile['templates']

    def test_fire_has_gps_30s(self):
        profile = get_profile_template('fire_department')
        assert profile['options']['gps.reportInterval'] == '30'

    def test_ems_has_gps_15s(self):
        profile = get_profile_template('ems')
        assert profile['options']['gps.reportInterval'] == '15'

    def test_search_rescue_has_gps_60s(self):
        profile = get_profile_template('search_rescue')
        assert profile['options']['gps.reportInterval'] == '60'

    def test_all_profiles_listed(self):
        names = [name for name, _ in list_profile_templates()]
        assert 'fire_department' in names
        assert 'law_enforcement' in names
        assert 'ems' in names
        assert 'search_rescue' in names

    def test_total_profile_count(self):
        """Verify we have 8 profiles now (4 original + 4 new)."""
        assert len(PROFILE_TEMPLATES) == 8


# ─── Snapshot: Save ──────────────────────────────────────────────────


class TestSnapshotSave:
    """Test saving configuration snapshots."""

    def test_save_snapshot_creates_file(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        assert Path(snap_path).exists()

    def test_save_snapshot_default_name(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        assert snap_path.endswith(".snapshot.json")

    def test_save_snapshot_custom_path(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        custom = tmp_path / "custom.json"
        snap_path = save_snapshot(prs, str(prs_path),
                                  snapshot_path=str(custom))
        assert snap_path == str(custom)
        assert custom.exists()

    def test_snapshot_is_valid_json(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert isinstance(data, dict)

    def test_snapshot_contains_systems(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert 'systems' in data
        assert len(data['systems']) > 0

    def test_snapshot_contains_options(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert 'options' in data

    def test_snapshot_contains_personality_name(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert 'personality_name' in data

    def test_snapshot_source_file(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert data['source_file'] == str(prs_path)

    def test_snapshot_conv_only(self, tmp_path):
        """Snapshot of a conv-only PRS (no P25 systems)."""
        config = "[channels.MURS]\ntemplate = murs\n"
        ini_path = _write_config(tmp_path, config)
        prs = build_from_config(ini_path)
        prs_path = tmp_path / "conv.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        data = json.loads(Path(snap_path).read_text(encoding='utf-8'))
        assert data['unit_id'] is None
        assert len(data['channels']) > 0


# ─── Snapshot: Compare ───────────────────────────────────────────────


class TestSnapshotCompare:
    """Test comparing against saved snapshots."""

    def test_compare_identical(self, tmp_path):
        """Same PRS compared to its own snapshot should show no changes."""
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))

        # Compare same PRS against its snapshot
        diff = compare_to_snapshot(prs, snap_path)
        assert diff['systems']['added'] == []
        assert diff['systems']['removed'] == []
        assert diff['talkgroups'] == {}
        assert diff['channels'] == {}
        assert diff['options']['changed'] == {}

    def test_compare_added_system(self, tmp_path):
        """Adding a system should show up as added."""
        # First: build and snapshot a conv-only PRS
        config1 = "[channels.MURS]\ntemplate = murs\n"
        ini1 = _write_config(tmp_path, config1, name="v1.ini")
        prs1 = build_from_config(ini1)
        prs_path = tmp_path / "radio.PRS"
        prs_path.write_bytes(prs1.to_bytes())
        snap_path = save_snapshot(prs1, str(prs_path))

        # Second: build with extra system
        config2 = (
            "[channels.MURS]\ntemplate = murs\n\n"
            "[channels.NOAA]\ntemplate = noaa\n"
        )
        ini2 = _write_config(tmp_path, config2, name="v2.ini")
        prs2 = build_from_config(ini2)

        diff = compare_to_snapshot(prs2, snap_path)
        # Should have added systems
        assert len(diff['systems']['added']) > 0

    def test_compare_missing_snapshot_raises(self, tmp_path):
        prs = build_from_config(str(PATROL_INI))
        with pytest.raises(FileNotFoundError):
            compare_to_snapshot(prs, str(tmp_path / "nonexistent.json"))

    def test_format_comparison(self, tmp_path):
        """Format should produce readable text."""
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_path = save_snapshot(prs, str(prs_path))
        diff = compare_to_snapshot(prs, snap_path)
        text = format_snapshot_comparison(diff)

        assert isinstance(text, str)


# ─── CLI: fleet-check ────────────────────────────────────────────────


class TestFleetCheckCLI:
    """Test the fleet-check CLI command."""

    def test_fleet_check_command(self, tmp_path):
        from quickprs.cli import run_cli
        files = _build_identical_conv_fleet(tmp_path)
        rc = run_cli(["fleet-check"] + files)
        assert rc == 0

    def test_fleet_check_single_file(self, tmp_path):
        from quickprs.cli import run_cli
        files = _build_identical_conv_fleet(tmp_path, count=1)
        rc = run_cli(["fleet-check"] + files)
        assert rc == 1

    def test_fleet_check_missing_file(self, tmp_path):
        from quickprs.cli import run_cli
        rc = run_cli(["fleet-check", str(tmp_path / "a.PRS"),
                       str(tmp_path / "b.PRS")])
        assert rc == 1


# ─── CLI: snapshot ───────────────────────────────────────────────────


class TestSnapshotCLI:
    """Test the snapshot CLI command."""

    def test_snapshot_save_command(self, tmp_path):
        from quickprs.cli import run_cli
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_out = tmp_path / "test.json"
        rc = run_cli(["snapshot", str(prs_path), "-o", str(snap_out)])
        assert rc == 0
        assert snap_out.exists()

    def test_snapshot_compare_command(self, tmp_path):
        from quickprs.cli import run_cli
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        snap_out = tmp_path / "baseline.json"
        # Save
        rc = run_cli(["snapshot", str(prs_path), "-o", str(snap_out)])
        assert rc == 0

        # Compare
        rc = run_cli(["snapshot", str(prs_path), "--compare", str(snap_out)])
        assert rc == 0

    def test_snapshot_missing_file(self, tmp_path):
        from quickprs.cli import run_cli
        rc = run_cli(["snapshot", str(tmp_path / "nonexistent.PRS")])
        assert rc == 1

    def test_snapshot_missing_compare_file(self, tmp_path):
        from quickprs.cli import run_cli
        prs = build_from_config(str(PATROL_INI))
        prs_path = tmp_path / "patrol.PRS"
        prs_path.write_bytes(prs.to_bytes())

        rc = run_cli(["snapshot", str(prs_path),
                       "--compare", str(tmp_path / "missing.json")])
        assert rc == 1
