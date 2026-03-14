"""Tests for fleet.py — batch PRS generation for radio fleets."""

import struct
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.fleet import (
    build_fleet, set_home_unit_id,
    _parse_units_csv, _is_p25_trunk_config, _patch_home_unit_id,
)
from quickprs.config_builder import build_from_config
from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.validation import validate_prs, ERROR
from quickprs.record_types import (
    is_system_config_data, parse_system_long_name,
)
from quickprs.option_maps import extract_platform_config
from quickprs.binary_io import read_lps

TESTDATA = Path(__file__).parent / "testdata"
PATROL_INI = TESTDATA / "example_patrol.ini"
UNITS_CSV = TESTDATA / "test_units.csv"


# ─── Helpers ─────────────────────────────────────────────────────────

def _write_csv(tmp_path, content, name="units.csv"):
    """Write CSV content to a temp file and return the path."""
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)


def _write_config(tmp_path, content, name="test.ini"):
    """Write INI content to a temp file and return the path."""
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)


def _read_home_unit_ids(prs):
    """Read all HomeUnitID values from all P25 trunked system configs.

    Returns list of (long_name, [uid1, uid2, uid3]) for each system.
    """
    results = []
    for sec in prs.sections:
        if sec.class_name:
            continue
        if not is_system_config_data(sec.raw):
            continue
        if not _is_p25_trunk_config(sec.raw):
            continue

        long_name = parse_system_long_name(sec.raw)
        uids = _extract_three_uids(sec.raw)
        if uids:
            results.append((long_name, uids))
    return results


def _extract_three_uids(raw):
    """Extract the 3 HomeUnitID uint32 values from a P25 trunk config."""
    try:
        pos = 44
        _, pos = read_lps(raw, pos)   # long_name
        pos += 15                      # sys_flags
        _, pos = read_lps(raw, pos)   # trunk_set
        _, pos = read_lps(raw, pos)   # group_set
        pos += 12                      # 12 zeros

        uid1 = struct.unpack_from('<I', raw, pos)[0]
        pos += 4   # HomeUnitID
        pos += 12  # SYSTEM_BLOCK4
        pos += 6   # 6 zeros
        pos += 2   # uint16(15)
        pos += 4   # system_id
        _, pos = read_lps(raw, pos)   # wan_name_1
        pos += 44                      # WAN_CONFIG
        _, pos = read_lps(raw, pos)   # wan_name_2

        uid2 = struct.unpack_from('<I', raw, pos)[0]
        uid3 = struct.unpack_from('<I', raw, pos + 4 + 5)[0]

        return [uid1, uid2, uid3]
    except (IndexError, ValueError, struct.error):
        return None


# ─── CSV Parsing ──────────────────────────────────────────────────────

class TestParseUnitsCsv:
    """Test _parse_units_csv."""

    def test_parse_standard_csv(self, tmp_path):
        path = _write_csv(tmp_path, "unit_id,name,password\n1001,A,1234\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 1
        assert units[0]['unit_id'] == 1001
        assert units[0]['name'] == 'A'
        assert units[0]['password'] == '1234'

    def test_parse_multiple_rows(self, tmp_path):
        path = _write_csv(tmp_path,
                          "unit_id,name,password\n"
                          "1001,A,1234\n"
                          "1002,B,5678\n"
                          "1003,C,9012\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 3
        assert [u['unit_id'] for u in units] == [1001, 1002, 1003]

    def test_parse_no_name_column(self, tmp_path):
        path = _write_csv(tmp_path, "unit_id\n1001\n1002\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 2
        assert units[0]['name'] == ''
        assert units[0]['password'] == ''

    def test_parse_no_password_column(self, tmp_path):
        path = _write_csv(tmp_path, "unit_id,name\n1001,A\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 1
        assert units[0]['password'] == ''

    def test_parse_skips_blank_rows(self, tmp_path):
        path = _write_csv(tmp_path,
                          "unit_id,name,password\n"
                          "1001,A,1234\n"
                          ",,\n"
                          "1002,B,5678\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 2

    def test_parse_missing_unit_id_column(self, tmp_path):
        path = _write_csv(tmp_path, "name,password\nA,1234\n")
        with pytest.raises(ValueError, match="missing required 'unit_id'"):
            _parse_units_csv(Path(path))

    def test_parse_invalid_unit_id(self, tmp_path):
        path = _write_csv(tmp_path, "unit_id\nabc\n")
        with pytest.raises(ValueError, match="invalid unit_id"):
            _parse_units_csv(Path(path))

    def test_parse_empty_csv(self, tmp_path):
        path = _write_csv(tmp_path, "unit_id,name,password\n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 0

    def test_parse_whitespace_in_fields(self, tmp_path):
        path = _write_csv(tmp_path,
                          "unit_id, name, password\n"
                          " 1001 , A , 1234 \n")
        units = _parse_units_csv(Path(path))
        assert len(units) == 1
        assert units[0]['unit_id'] == 1001
        assert units[0]['name'] == 'A'
        assert units[0]['password'] == '1234'

    def test_parse_testdata_csv(self):
        """Parse the real test CSV in testdata/."""
        units = _parse_units_csv(UNITS_CSV)
        assert len(units) == 3
        assert units[0]['unit_id'] == 1001
        assert units[0]['name'] == 'UNIT-1001'
        assert units[0]['password'] == '1234'
        assert units[2]['unit_id'] == 1003
        assert units[2]['password'] == '5678'

    def test_parse_bom_csv(self, tmp_path):
        """UTF-8 BOM should be handled transparently."""
        content = "\ufeffunit_id,name\n1001,A\n"
        path = _write_csv(tmp_path, content)
        units = _parse_units_csv(Path(path))
        assert len(units) == 1
        assert units[0]['unit_id'] == 1001


# ─── set_home_unit_id ─────────────────────────────────────────────────

class TestSetHomeUnitId:
    """Test set_home_unit_id on built PRS files."""

    def test_sets_unit_id_on_patrol_config(self):
        prs = build_from_config(str(PATROL_INI))
        count = set_home_unit_id(prs, 12345)
        assert count == 1  # patrol has one P25 system

        # Verify all 3 positions have the new value
        uids = _read_home_unit_ids(prs)
        assert len(uids) == 1
        name, ids = uids[0]
        assert ids == [12345, 12345, 12345]

    def test_sets_different_values(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 99999)
        uids = _read_home_unit_ids(prs)
        assert uids[0][1] == [99999, 99999, 99999]

    def test_sets_zero(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 0)
        uids = _read_home_unit_ids(prs)
        assert uids[0][1] == [0, 0, 0]

    def test_sets_max_uint32(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 0xFFFFFFFF)
        uids = _read_home_unit_ids(prs)
        assert uids[0][1] == [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]

    def test_modified_prs_validates_clean(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 42000)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert errors == []

    def test_modified_prs_roundtrips(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 55555)
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_unit_id_survives_roundtrip(self):
        prs = build_from_config(str(PATROL_INI))
        set_home_unit_id(prs, 77777)
        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        uids = _read_home_unit_ids(prs2)
        assert uids[0][1] == [77777, 77777, 77777]

    def test_filter_by_system_name(self, tmp_path):
        """When system_name is given, only that system is modified."""
        prs = build_from_config(str(PATROL_INI))
        # PSERN SEATTLE is the long name
        count = set_home_unit_id(prs, 11111, system_name="PSERN SEATTLE")
        assert count == 1
        uids = _read_home_unit_ids(prs)
        assert uids[0][1] == [11111, 11111, 11111]

    def test_filter_by_wrong_name_changes_nothing(self):
        prs = build_from_config(str(PATROL_INI))
        count = set_home_unit_id(prs, 11111, system_name="NONEXISTENT")
        assert count == 0
        uids = _read_home_unit_ids(prs)
        assert uids[0][1] == [0, 0, 0]  # default is 0

    def test_does_not_modify_conv_systems(self, tmp_path):
        """Conv system config sections should not be touched."""
        config = (
            "[personality]\nname = Conv Only.PRS\n\n"
            "[channels.MURS]\ntemplate = murs\n"
        )
        path = _write_config(tmp_path, config)
        prs = build_from_config(path)
        count = set_home_unit_id(prs, 12345)
        assert count == 0


# ─── build_fleet ──────────────────────────────────────────────────────

class TestBuildFleet:
    """Test the full fleet build pipeline."""

    def test_build_three_units(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        assert len(results) == 3
        assert all(ok for _, _, ok, _ in results)

        # Verify files exist
        for filepath, _, ok, _ in results:
            assert Path(filepath).exists()

    def test_output_filenames_from_name_column(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        filenames = [Path(fp).name for fp, _, _, _ in results]
        assert "UNIT-1001.PRS" in filenames
        assert "UNIT-1002.PRS" in filenames
        assert "UNIT-1003.PRS" in filenames

    def test_output_filenames_without_name_column(self, tmp_path):
        csv_path = _write_csv(tmp_path,
                              "unit_id\n1001\n1002\n",
                              name="no_name.csv")
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), csv_path, str(out_dir))

        filenames = [Path(fp).name for fp, _, _, _ in results]
        assert "unit_1001.PRS" in filenames
        assert "unit_1002.PRS" in filenames

    def test_each_file_has_correct_unit_id(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        for filepath, unit_id, ok, _ in results:
            assert ok
            prs = parse_prs(filepath)
            uids = _read_home_unit_ids(prs)
            assert len(uids) == 1
            _, ids = uids[0]
            assert ids == [unit_id, unit_id, unit_id], \
                f"Unit ID mismatch in {filepath}: expected {unit_id}, got {ids}"

    def test_each_file_validates_clean(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        for filepath, _, ok, _ in results:
            assert ok
            prs = parse_prs(filepath)
            issues = validate_prs(prs)
            errors = [m for s, m in issues if s == ERROR]
            assert errors == [], \
                f"Validation errors in {filepath}: {errors}"

    def test_each_file_roundtrips(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        for filepath, _, ok, _ in results:
            assert ok
            raw1 = Path(filepath).read_bytes()
            prs = parse_prs_bytes(raw1)
            raw2 = prs.to_bytes()
            assert raw1 == raw2, f"Roundtrip failed for {filepath}"

    def test_creates_output_directory(self, tmp_path):
        out_dir = tmp_path / "new" / "nested" / "dir"
        assert not out_dir.exists()
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))
        assert out_dir.exists()
        assert len(results) == 3

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            build_fleet("nonexistent.ini", str(UNITS_CSV),
                        str(tmp_path / "out"))

    def test_missing_csv_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Units CSV not found"):
            build_fleet(str(PATROL_INI), "nonexistent.csv",
                        str(tmp_path / "out"))

    def test_empty_csv_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, "unit_id,name,password\n")
        with pytest.raises(ValueError, match="no data rows"):
            build_fleet(str(PATROL_INI), csv_path, str(tmp_path / "out"))

    def test_password_set_correctly(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        # Unit 1001 should have password 1234
        for filepath, unit_id, ok, _ in results:
            if unit_id == 1001:
                prs = parse_prs(filepath)
                config = extract_platform_config(prs)
                if config:
                    misc = config.get("miscConfig", {})
                    assert misc.get("password") == "1234"
                break

    def test_password_differs_per_unit(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        passwords = {}
        for filepath, unit_id, ok, _ in results:
            prs = parse_prs(filepath)
            config = extract_platform_config(prs)
            if config:
                misc = config.get("miscConfig", {})
                passwords[unit_id] = misc.get("password", "")

        # Units 1001 and 1002 have "1234", unit 1003 has "5678"
        assert passwords.get(1001) == "1234"
        assert passwords.get(1002) == "1234"
        assert passwords.get(1003) == "5678"

    def test_no_password_column(self, tmp_path):
        csv_path = _write_csv(tmp_path, "unit_id,name\n1001,A\n1002,B\n")
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), csv_path, str(out_dir))

        assert len(results) == 2
        assert all(ok for _, _, ok, _ in results)

    def test_no_name_column(self, tmp_path):
        csv_path = _write_csv(tmp_path, "unit_id,password\n1001,9999\n")
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), csv_path, str(out_dir))

        assert len(results) == 1
        assert results[0][1] == 1001
        assert Path(results[0][0]).name == "unit_1001.PRS"

    def test_unit_id_only(self, tmp_path):
        """Minimal CSV with just unit_id column."""
        csv_path = _write_csv(tmp_path, "unit_id\n5000\n5001\n5002\n")
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), csv_path, str(out_dir))

        assert len(results) == 3
        assert all(ok for _, _, ok, _ in results)
        for filepath, uid, ok, _ in results:
            prs = parse_prs(filepath)
            uids = _read_home_unit_ids(prs)
            assert uids[0][1] == [uid, uid, uid]

    def test_large_unit_ids(self, tmp_path):
        """Large but valid unit IDs (no 0xFFFF in LE bytes)."""
        csv_path = _write_csv(tmp_path,
                              "unit_id\n1000000\n9999999\n")
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), csv_path, str(out_dir))

        assert len(results) == 2
        assert all(ok for _, _, ok, _ in results)

        for filepath, uid, ok, _ in results:
            prs = parse_prs(filepath)
            uids = _read_home_unit_ids(prs)
            assert uids[0][1] == [uid, uid, uid]

    def test_ffff_unit_id_corrupts_section_parsing(self, tmp_path):
        """Unit IDs whose LE bytes contain 0xFFFF break PRS section parsing.

        This is an inherent PRS format limitation — 0xFFFF is the section
        marker. Values like 0x00FFFFFF (16777215) and 0xFFFFFFFF (4294967295)
        produce 0xFFFF in their little-endian representation.
        The raw bytes roundtrip fine, but the parser sees false section
        boundaries, producing more sections than the original.
        """
        prs = build_from_config(str(PATROL_INI))
        orig_sections = len(prs.sections)
        set_home_unit_id(prs, 0xFFFFFFFF)
        raw = prs.to_bytes()
        prs2 = parse_prs_bytes(raw)
        # Parser sees false 0xFFFF markers and creates extra sections
        assert len(prs2.sections) > orig_sections

    def test_result_tuples_format(self, tmp_path):
        out_dir = tmp_path / "fleet"
        results = build_fleet(str(PATROL_INI), str(UNITS_CSV), str(out_dir))

        for result in results:
            assert len(result) == 4
            filepath, unit_id, success, error_msg = result
            assert isinstance(filepath, str)
            assert isinstance(unit_id, int)
            assert isinstance(success, bool)
            assert success is True
            assert error_msg is None


# ─── CLI Integration ──────────────────────────────────────────────────

class TestFleetCLI:
    """Test the fleet command via run_cli."""

    def test_fleet_command_succeeds(self, tmp_path):
        from quickprs.cli import run_cli
        out_dir = tmp_path / "fleet"
        rc = run_cli([
            "fleet", str(PATROL_INI),
            "--units", str(UNITS_CSV),
            "-o", str(out_dir),
        ])
        assert rc == 0

    def test_fleet_missing_config(self, tmp_path):
        from quickprs.cli import run_cli
        rc = run_cli([
            "fleet", "nonexistent.ini",
            "--units", str(UNITS_CSV),
            "-o", str(tmp_path / "out"),
        ])
        assert rc == 1

    def test_fleet_missing_csv(self, tmp_path):
        from quickprs.cli import run_cli
        rc = run_cli([
            "fleet", str(PATROL_INI),
            "--units", "nonexistent.csv",
            "-o", str(tmp_path / "out"),
        ])
        assert rc == 1

    def test_fleet_creates_files(self, tmp_path):
        from quickprs.cli import run_cli
        out_dir = tmp_path / "fleet"
        run_cli([
            "fleet", str(PATROL_INI),
            "--units", str(UNITS_CSV),
            "-o", str(out_dir),
        ])
        files = list(out_dir.glob("*.PRS"))
        assert len(files) == 3

    def test_fleet_default_output_dir(self, tmp_path, monkeypatch):
        """Without -o, uses fleet_output/ in cwd."""
        from quickprs.cli import run_cli
        monkeypatch.chdir(tmp_path)
        rc = run_cli([
            "fleet", str(PATROL_INI),
            "--units", str(UNITS_CSV),
        ])
        assert rc == 0
        default_dir = tmp_path / "fleet_output"
        assert default_dir.exists()
        files = list(default_dir.glob("*.PRS"))
        assert len(files) == 3


# ─── P25 Trunk Detection ─────────────────────────────────────────────

class TestIsP25TrunkConfig:
    """Test the _is_p25_trunk_config helper."""

    def test_patrol_has_trunk_config(self):
        prs = build_from_config(str(PATROL_INI))
        trunk_count = 0
        for sec in prs.sections:
            if sec.class_name:
                continue
            if not is_system_config_data(sec.raw):
                continue
            if _is_p25_trunk_config(sec.raw):
                trunk_count += 1
        assert trunk_count == 1

    def test_conv_only_has_no_trunk_config(self, tmp_path):
        config = "[channels.MURS]\ntemplate = murs\n"
        path = _write_config(tmp_path, config)
        prs = build_from_config(path)
        for sec in prs.sections:
            if sec.class_name:
                continue
            if is_system_config_data(sec.raw):
                assert not _is_p25_trunk_config(sec.raw)


# ─── Multi-System Configs ────────────────────────────────────────────

class TestFleetMultiSystem:
    """Fleet with configs that have multiple P25 systems."""

    def test_two_p25_systems(self, tmp_path):
        config = (
            "[personality]\nname = DUAL.PRS\n\n"
            "[system.SYS1]\ntype = p25_trunked\n"
            "long_name = SYSTEM ONE\nsystem_id = 100\n\n"
            "[system.SYS1.frequencies]\n1 = 851.0125,806.0125\n\n"
            "[system.SYS1.talkgroups]\n1 = 1,DISP,Dispatch\n\n"
            "[system.SYS2]\ntype = p25_trunked\n"
            "long_name = SYSTEM TWO\nsystem_id = 200\n\n"
            "[system.SYS2.frequencies]\n1 = 852.0125,807.0125\n\n"
            "[system.SYS2.talkgroups]\n1 = 2,TAC,Tactical\n"
        )
        ini_path = _write_config(tmp_path, config)
        csv_path = _write_csv(tmp_path,
                              "unit_id,name\n2001,DUAL-2001\n2002,DUAL-2002\n")
        out_dir = tmp_path / "fleet"

        results = build_fleet(ini_path, csv_path, str(out_dir))
        assert len(results) == 2
        assert all(ok for _, _, ok, _ in results)

        # Each file should have BOTH systems with the same unit_id
        for filepath, uid, ok, _ in results:
            prs = parse_prs(filepath)
            uids = _read_home_unit_ids(prs)
            assert len(uids) == 2, \
                f"Expected 2 P25 systems in {filepath}, got {len(uids)}"
            for name, ids in uids:
                assert ids == [uid, uid, uid], \
                    f"UID mismatch in {filepath} system '{name}'"

    def test_mixed_p25_and_conv(self, tmp_path):
        """P25 systems get UID, conv systems are untouched."""
        config = (
            "[personality]\nname = MIXED.PRS\n\n"
            "[system.PSERN]\ntype = p25_trunked\n"
            "long_name = PSERN\nsystem_id = 892\n\n"
            "[system.PSERN.frequencies]\n1 = 851.0125,806.0125\n\n"
            "[system.PSERN.talkgroups]\n1 = 1,DISP,Dispatch\n\n"
            "[channels.MURS]\ntemplate = murs\n"
        )
        ini_path = _write_config(tmp_path, config)
        csv_path = _write_csv(tmp_path, "unit_id\n3001\n")
        out_dir = tmp_path / "fleet"

        results = build_fleet(ini_path, csv_path, str(out_dir))
        assert len(results) == 1
        assert results[0][2] is True

        prs = parse_prs(results[0][0])
        uids = _read_home_unit_ids(prs)
        assert len(uids) == 1  # only the P25 system
        assert uids[0][1] == [3001, 3001, 3001]
