"""Tests filling remaining coverage gaps.

Categories:
- Negative/error path tests for CLI commands
- Boundary tests for numeric fields (0, max uint16, max uint32)
- Encoding tests for names with special ASCII characters
- Empty/minimal PRS file tests
- Large file tests approaching XG-100P limits
- GUI module import smoke tests
"""

import importlib
import os
import struct
import tempfile
from pathlib import Path

import pytest

from quickprs.binary_io import (
    read_uint8, read_uint16_le, read_uint32_le, read_double_le,
    read_lps, read_bool, read_bytes,
    write_uint8, write_uint16_le, write_uint32_le, write_double_le,
    write_lps, write_bool,
    SECTION_MARKER, FILE_TERMINATOR,
    find_all_ffff, try_read_class_name,
)
from quickprs.prs_parser import parse_prs, parse_prs_bytes, PRSFile, Section
from quickprs.prs_writer import write_prs
from quickprs.cli import run_cli, cmd_info, cmd_validate, cmd_create
from quickprs.builder import create_blank_prs
from quickprs.validation import validate_prs, ERROR, WARNING, INFO, LIMITS
from quickprs.injector import (
    make_p25_group, make_trunk_channel, make_trunk_set,
    make_group_set, make_conv_channel, make_conv_set,
    make_iden_set,
)
from quickprs.record_types import (
    P25Group, P25GroupSet, TrunkChannel, TrunkSet,
    ConvChannel, ConvSet, IdenElement, IdenDataSet,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ═══════════════════════════════════════════════════════════════════
# GUI module import smoke tests
# ═══════════════════════════════════════════════════════════════════


class TestGuiImports:
    """Smoke tests for GUI modules — import without crashing.

    These modules require tkinter, which may not be available in
    headless CI environments. Tests are skipped if tkinter is missing.
    """

    @pytest.fixture(autouse=True)
    def require_tkinter(self):
        try:
            import tkinter
        except ImportError:
            pytest.skip("tkinter not available")

    def test_import_gui_app(self):
        mod = importlib.import_module("quickprs.gui.app")
        assert hasattr(mod, "main")

    def test_import_gui_button_config(self):
        mod = importlib.import_module("quickprs.gui.button_config")
        assert mod is not None

    def test_import_gui_diff_viewer(self):
        mod = importlib.import_module("quickprs.gui.diff_viewer")
        assert mod is not None

    def test_import_gui_import_panel(self):
        mod = importlib.import_module("quickprs.gui.import_panel")
        assert mod is not None

    def test_import_gui_personality_view(self):
        mod = importlib.import_module("quickprs.gui.personality_view")
        assert mod is not None

    def test_import_gui_settings(self):
        mod = importlib.import_module("quickprs.gui.settings")
        assert mod is not None

    def test_gui_init(self):
        mod = importlib.import_module("quickprs.gui")
        assert mod is not None


# ═══════════════════════════════════════════════════════════════════
# CLI negative/error path tests
# ═══════════════════════════════════════════════════════════════════


class TestCliErrors:
    """Error paths in CLI commands."""

    def test_info_nonexistent_file(self, capsys):
        result = run_cli(["info", "does_not_exist.PRS"])
        assert result == 1

    def test_validate_nonexistent_file(self, capsys):
        result = run_cli(["validate", "does_not_exist.PRS"])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_compare_one_file_missing(self, capsys):
        result = run_cli(["compare", str(PAWS), "does_not_exist.PRS"])
        assert result == 1

    def test_compare_both_files_missing(self, capsys):
        result = run_cli(["compare", "a.PRS", "b.PRS"])
        assert result == 1

    def test_dump_nonexistent_file(self, capsys):
        result = run_cli(["dump", "missing.PRS"])
        assert result == 1

    def test_capacity_nonexistent_file(self, capsys):
        result = run_cli(["capacity", "missing.PRS"])
        assert result == 1

    def test_export_csv_nonexistent_file(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cli(["export-csv", "missing.PRS", tmpdir])
            assert result == 1

    def test_export_json_nonexistent_file(self, capsys):
        result = run_cli(["export-json", "missing.PRS"])
        assert result == 1

    def test_import_json_nonexistent_file(self, capsys):
        result = run_cli(["import-json", "missing.json"])
        assert result == 1

    def test_repair_nonexistent_file(self, capsys):
        result = run_cli(["repair", "missing.PRS"])
        assert result == 1

    def test_report_nonexistent_file(self, capsys):
        result = run_cli(["report", "missing.PRS"])
        assert result == 1

    def test_set_option_nonexistent_file(self, capsys):
        result = run_cli(["set-option", "missing.PRS", "gps.gpsMode", "ON"])
        assert result == 1

    def test_remove_nonexistent_file(self, capsys):
        result = run_cli(["remove", "missing.PRS", "system", "PSERN"])
        assert result == 1

    def test_edit_nonexistent_file(self, capsys):
        result = run_cli(["edit", "missing.PRS", "--name", "NEW.PRS"])
        assert result == 1

    def test_list_nonexistent_file(self, capsys):
        result = run_cli(["list", "missing.PRS", "systems"])
        assert result == 1

    def test_inject_no_subcommand(self, capsys):
        """inject without sub-subcommand should show help and return 1."""
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        result = run_cli(["inject", str(CLAUDE)])
        assert result == 1

    def test_bulk_edit_no_subcommand(self, capsys):
        """bulk-edit without sub-subcommand should show help and return 1."""
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        result = run_cli(["bulk-edit", str(CLAUDE)])
        assert result == 1

    def test_remove_invalid_type(self):
        """Invalid remove type should cause argparse error."""
        with pytest.raises(SystemExit):
            run_cli(["remove", "file.PRS", "invalid-type", "NAME"])

    def test_list_invalid_type(self):
        """Invalid list type should cause argparse error."""
        with pytest.raises(SystemExit):
            run_cli(["list", "file.PRS", "invalid-type"])

    def test_unknown_subcommand(self):
        """Unknown subcommand should cause argparse error."""
        with pytest.raises(SystemExit):
            run_cli(["nonexistent-command"])

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_nonexistent_target(self, capsys):
        result = run_cli(["merge", "missing.PRS", str(PAWS)])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_merge_nonexistent_source(self, capsys):
        result = run_cli(["merge", str(PAWS), "missing.PRS"])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_nonexistent_source(self, capsys):
        result = run_cli(["clone", str(PAWS), "missing.PRS", "SYS"])
        assert result == 1

    def test_diff_options_nonexistent_file(self, capsys):
        result = run_cli(["diff-options", "a.PRS", "b.PRS"])
        assert result == 1

    def test_build_nonexistent_config(self, capsys):
        result = run_cli(["build", "nonexistent.ini"])
        assert result == 1

    def test_fleet_nonexistent_config(self, capsys):
        result = run_cli(["fleet", "nonexistent.ini",
                          "--units", "units.csv"])
        assert result == 1

    def test_import_scanner_nonexistent_csv(self, capsys):
        if not CLAUDE.exists():
            pytest.skip("test file not found")
        result = run_cli(["import-scanner", str(CLAUDE),
                          "--csv", "missing.csv"])
        assert result == 1

    def test_import_scanner_nonexistent_prs(self, capsys):
        result = run_cli(["import-scanner", "missing.PRS",
                          "--csv", "some.csv"])
        assert result == 1

    def test_freq_tools_no_subcommand(self, capsys):
        """freq-tools without sub-subcommand should show help."""
        result = run_cli(["freq-tools"])
        assert result == 1

    def test_set_option_invalid_section(self, capsys):
        """set-option with invalid section.attr should error."""
        if not PAWS.exists():
            pytest.skip("test file not found")
        result = run_cli(["set-option", str(PAWS),
                          "nonexistent.attr", "value"])
        assert result == 1

    def test_inject_conv_missing_template(self):
        """inject conv with invalid template should error."""
        with pytest.raises(SystemExit):
            # --channels-csv and --template are mutually exclusive
            # and one is required; providing neither should error
            run_cli(["inject", "file.PRS", "conv"])

    def test_report_on_blank_prs(self, capsys, tmp_path):
        """report on blank PRS should work."""
        blank = tmp_path / "blank.PRS"
        prs = create_blank_prs(filename="blank.PRS")
        blank.write_bytes(prs.to_bytes())
        out = tmp_path / "report.html"
        result = run_cli(["report", str(blank), "-o", str(out)])
        assert result == 0
        assert out.exists()


# ═══════════════════════════════════════════════════════════════════
# CLI with corrupt/invalid data
# ═══════════════════════════════════════════════════════════════════


class TestCliCorruptData:
    """CLI commands on corrupt or minimal data files."""

    def test_info_on_empty_file(self, capsys, tmp_path):
        """info on a zero-byte file should return error."""
        empty = tmp_path / "empty.PRS"
        empty.write_bytes(b"")
        result = run_cli(["info", str(empty)])
        assert result == 1

    def test_validate_on_empty_file(self, capsys, tmp_path):
        """validate on a zero-byte file should return error."""
        empty = tmp_path / "empty.PRS"
        empty.write_bytes(b"")
        result = run_cli(["validate", str(empty)])
        assert result == 1

    def test_info_on_garbage_file(self, capsys, tmp_path):
        """info on random binary data should return error or 0."""
        garbage = tmp_path / "garbage.PRS"
        garbage.write_bytes(b"\x00" * 100)
        result = run_cli(["info", str(garbage)])
        assert result in (0, 1)  # should not crash

    def test_validate_on_garbage_file(self, capsys, tmp_path):
        """validate on random binary data should not crash."""
        garbage = tmp_path / "garbage.PRS"
        garbage.write_bytes(b"\x00" * 100)
        result = run_cli(["validate", str(garbage)])
        assert result in (0, 1)

    def test_dump_on_garbage_file(self, capsys, tmp_path):
        """dump on random binary should not crash."""
        garbage = tmp_path / "garbage.PRS"
        garbage.write_bytes(b"\x00" * 100)
        result = run_cli(["dump", str(garbage)])
        assert result in (0, 1)

    def test_info_on_just_terminator(self, capsys, tmp_path):
        """File that is just a terminator."""
        term = tmp_path / "term.PRS"
        term.write_bytes(FILE_TERMINATOR)
        result = run_cli(["info", str(term)])
        assert result in (0, 1)

    def test_capacity_on_blank_prs(self, capsys, tmp_path):
        """Capacity on a blank PRS (no systems) should work."""
        blank = tmp_path / "blank.PRS"
        prs = create_blank_prs(filename="blank.PRS")
        blank.write_bytes(prs.to_bytes())
        result = run_cli(["capacity", str(blank)])
        assert result == 0

    def test_repair_on_truncated_file(self, capsys, tmp_path):
        """repair on a truncated PRS should not crash."""
        if not PAWS.exists():
            pytest.skip("test file not found")
        data = PAWS.read_bytes()
        truncated = tmp_path / "truncated.PRS"
        truncated.write_bytes(data[:500])
        result = run_cli(["repair", str(truncated), "-o",
                          str(tmp_path / "repaired.PRS")])
        assert result in (0, 1)

    def test_import_json_invalid_json(self, capsys, tmp_path):
        """import-json with invalid JSON should error gracefully."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json content!!!", encoding="utf-8")
        result = run_cli(["import-json", str(bad_json)])
        assert result == 1

    def test_export_json_on_blank_prs(self, capsys, tmp_path):
        """export-json on a blank PRS should work."""
        blank = tmp_path / "blank.PRS"
        prs = create_blank_prs(filename="blank.PRS")
        blank.write_bytes(prs.to_bytes())
        result = run_cli(["export-json", str(blank), "-o",
                          str(tmp_path / "out.json")])
        assert result == 0
        assert (tmp_path / "out.json").exists()


# ═══════════════════════════════════════════════════════════════════
# Boundary tests for numeric fields
# ═══════════════════════════════════════════════════════════════════


class TestNumericBoundaries:
    """Boundary tests for integer read/write at limits."""

    def test_uint8_zero(self):
        raw = write_uint8(0)
        val, _ = read_uint8(raw, 0)
        assert val == 0

    def test_uint8_max(self):
        raw = write_uint8(255)
        val, _ = read_uint8(raw, 0)
        assert val == 255

    def test_uint8_overflow_raises(self):
        with pytest.raises(struct.error):
            write_uint8(256)

    def test_uint8_negative_raises(self):
        with pytest.raises(struct.error):
            write_uint8(-1)

    def test_uint16_zero(self):
        raw = write_uint16_le(0)
        val, _ = read_uint16_le(raw, 0)
        assert val == 0

    def test_uint16_max(self):
        """Max uint16 = 65535 = talkgroup ID limit."""
        raw = write_uint16_le(65535)
        val, _ = read_uint16_le(raw, 0)
        assert val == 65535

    def test_uint16_overflow_raises(self):
        with pytest.raises(struct.error):
            write_uint16_le(65536)

    def test_uint16_negative_raises(self):
        with pytest.raises(struct.error):
            write_uint16_le(-1)

    def test_uint32_zero(self):
        raw = write_uint32_le(0)
        val, _ = read_uint32_le(raw, 0)
        assert val == 0

    def test_uint32_max(self):
        """Max uint32 = 4294967295."""
        raw = write_uint32_le(0xFFFFFFFF)
        val, _ = read_uint32_le(raw, 0)
        assert val == 0xFFFFFFFF

    def test_uint32_overflow_raises(self):
        with pytest.raises(struct.error):
            write_uint32_le(0x100000000)

    def test_uint32_negative_raises(self):
        with pytest.raises(struct.error):
            write_uint32_le(-1)

    def test_double_zero(self):
        raw = write_double_le(0.0)
        val, _ = read_double_le(raw, 0)
        assert val == 0.0

    def test_double_negative_zero(self):
        """IEEE 754 negative zero should roundtrip."""
        raw = write_double_le(-0.0)
        val, _ = read_double_le(raw, 0)
        # -0.0 == 0.0 in Python, but bits differ
        assert val == 0.0

    def test_double_very_small(self):
        """Smallest positive subnormal double."""
        raw = write_double_le(5e-324)
        val, _ = read_double_le(raw, 0)
        assert val == 5e-324

    def test_double_max_frequency(self):
        """Highest conceivable radio frequency: 6 GHz."""
        raw = write_double_le(6000.0)
        val, _ = read_double_le(raw, 0)
        assert abs(val - 6000.0) < 1e-10

    def test_talkgroup_id_boundary_zero(self):
        """Group ID 0 should work."""
        tg = make_p25_group(0, "ZERO", "Zero ID")
        assert tg.group_id == 0

    def test_talkgroup_id_boundary_max(self):
        """Group ID 65535 (max uint16) should work."""
        tg = make_p25_group(65535, "MAX", "Max ID")
        assert tg.group_id == 65535

    def test_trunk_channel_zero_freq(self):
        """Trunk channel at 0.0 MHz."""
        tc = make_trunk_channel(0.0, 0.0)
        assert tc.tx_freq == 0.0

    def test_trunk_channel_max_practical_freq(self):
        """Trunk channel at 870 MHz (XG-100P upper bound)."""
        tc = make_trunk_channel(870.0, 870.0)
        assert tc.tx_freq == 870.0


# ═══════════════════════════════════════════════════════════════════
# Encoding tests — names with special ASCII characters
# ═══════════════════════════════════════════════════════════════════


class TestNameEncoding:
    """Test names with spaces, punctuation, digits, and edge cases."""

    def test_lps_with_spaces(self):
        raw = write_lps("A B C D")
        val, _ = read_lps(raw, 0)
        assert val == "A B C D"

    def test_lps_with_digits(self):
        raw = write_lps("CH 12345")
        val, _ = read_lps(raw, 0)
        assert val == "CH 12345"

    def test_lps_with_punctuation(self):
        raw = write_lps("PD-TAC/1")
        val, _ = read_lps(raw, 0)
        assert val == "PD-TAC/1"

    def test_lps_with_all_printable_ascii(self):
        """All printable ASCII chars should roundtrip."""
        s = "".join(chr(i) for i in range(32, 127))
        raw = write_lps(s)
        val, _ = read_lps(raw, 0)
        assert val == s

    def test_lps_with_parens(self):
        raw = write_lps("PD (TAC)")
        val, _ = read_lps(raw, 0)
        assert val == "PD (TAC)"

    def test_lps_with_ampersand(self):
        raw = write_lps("FIRE&EMS")
        val, _ = read_lps(raw, 0)
        assert val == "FIRE&EMS"

    def test_lps_with_hash(self):
        raw = write_lps("CH #5")
        val, _ = read_lps(raw, 0)
        assert val == "CH #5"

    def test_lps_single_char(self):
        raw = write_lps("A")
        val, _ = read_lps(raw, 0)
        assert val == "A"

    def test_talkgroup_name_8_chars_special(self):
        """8-char short name with mixed chars."""
        tg = make_p25_group(100, "PD-TAC/1", "POLICE TAC 1")
        assert tg.group_name == "PD-TAC/1"

    def test_talkgroup_name_with_spaces(self):
        tg = make_p25_group(200, "PD  TAC", "PD TAC")
        assert tg.group_name == "PD  TAC"

    def test_conv_channel_name_special_chars(self):
        ch = make_conv_channel("CH-5(A)", 462.5625, long_name="Channel 5-A")
        assert ch.short_name == "CH-5(A)"

    def test_conv_set_name_with_digits(self):
        cs = make_conv_set("CH 123", [
            {"short_name": "CH1", "tx_freq": 462.5625},
        ])
        assert cs.name == "CH 123"

    def test_trunk_set_name_all_digits(self):
        ts = make_trunk_set("12345678", [(462.5, 462.5)])
        assert ts.name == "12345678"

    def test_group_set_name_with_hyphen(self):
        gs = make_group_set("PD-MAIN", [(100, "DISP", "Dispatch")])
        assert gs.name == "PD-MAIN"


# ═══════════════════════════════════════════════════════════════════
# Empty/minimal PRS file tests
# ═══════════════════════════════════════════════════════════════════


class TestEmptyPRS:
    """Operations on blank/minimal PRS files."""

    @pytest.fixture
    def blank_prs_path(self, tmp_path):
        """Create a blank PRS file on disk."""
        path = tmp_path / "blank.PRS"
        prs = create_blank_prs(filename="blank.PRS")
        path.write_bytes(prs.to_bytes())
        return path

    def test_blank_prs_creates_valid_file(self, blank_prs_path):
        prs = parse_prs(blank_prs_path)
        assert len(prs.sections) > 0
        assert prs.file_size > 0

    def test_blank_prs_has_cpersonality(self, blank_prs_path):
        prs = parse_prs(blank_prs_path)
        cp = prs.get_section_by_class("CPersonality")
        assert cp is not None

    def test_blank_prs_roundtrips(self, blank_prs_path):
        original = blank_prs_path.read_bytes()
        prs = parse_prs(blank_prs_path)
        rebuilt = prs.to_bytes()
        assert original == rebuilt

    def test_validate_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["validate", str(blank_prs_path)])
        assert result in (0, 1)  # may have warnings but should not crash

    def test_info_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["info", str(blank_prs_path)])
        assert result == 0
        out = capsys.readouterr().out
        assert "blank.PRS" in out

    def test_dump_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["dump", str(blank_prs_path)])
        assert result == 0

    def test_capacity_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["capacity", str(blank_prs_path)])
        assert result == 0

    def test_export_csv_blank_prs(self, capsys, blank_prs_path, tmp_path):
        out_dir = tmp_path / "csv_out"
        result = run_cli(["export-csv", str(blank_prs_path), str(out_dir)])
        assert result == 0

    def test_export_json_blank_prs(self, capsys, blank_prs_path, tmp_path):
        out = tmp_path / "out.json"
        result = run_cli(["export-json", str(blank_prs_path),
                          "-o", str(out)])
        assert result == 0
        assert out.exists()

    def test_list_systems_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "systems"])
        assert result == 0

    def test_list_talkgroups_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "talkgroups"])
        assert result == 0

    def test_list_channels_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "channels"])
        assert result == 0

    def test_list_frequencies_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "frequencies"])
        assert result == 0

    def test_list_sets_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "sets"])
        assert result == 0

    def test_list_options_blank_prs(self, capsys, blank_prs_path):
        result = run_cli(["list", str(blank_prs_path), "options"])
        assert result == 0

    def test_compare_blank_with_self(self, capsys, blank_prs_path):
        result = run_cli(["compare", str(blank_prs_path),
                          str(blank_prs_path)])
        # Comparing a file with itself should show no differences
        assert result == 0

    def test_merge_blank_into_blank(self, capsys, tmp_path):
        """Merging two blank PRS files should produce a valid file."""
        blank1 = tmp_path / "a.PRS"
        blank2 = tmp_path / "b.PRS"
        out = tmp_path / "merged.PRS"
        prs1 = create_blank_prs(filename="a.PRS")
        prs2 = create_blank_prs(filename="b.PRS")
        blank1.write_bytes(prs1.to_bytes())
        blank2.write_bytes(prs2.to_bytes())
        result = run_cli(["merge", str(blank1), str(blank2),
                          "-o", str(out)])
        assert result == 0
        assert out.exists()


# ═══════════════════════════════════════════════════════════════════
# Large file tests — approaching XG-100P limits
# ═══════════════════════════════════════════════════════════════════


class TestLargeData:
    """Tests for operations approaching radio memory limits."""

    def test_many_talkgroups(self):
        """Create group set near the 256 TG-per-set limit."""
        tgs = [(i, f"TG{i:05d}", f"Talkgroup {i}") for i in range(250)]
        gs = make_group_set("LARGE", tgs)
        assert len(gs.groups) == 250
        assert gs.name == "LARGE"

    def test_max_talkgroup_ids(self):
        """Talkgroup IDs at uint16 boundaries."""
        tgs = [
            (0, "ZERO", "ID Zero"),
            (1, "ONE", "ID One"),
            (32767, "HALF", "ID Half"),
            (65535, "MAX", "ID Max"),
        ]
        gs = make_group_set("BOUNDS", tgs)
        assert gs.groups[0].group_id == 0
        assert gs.groups[3].group_id == 65535

    def test_many_trunk_channels(self):
        """Create trunk set near the 500-freq limit."""
        freqs = [(400.0 + i * 0.025, 400.0 + i * 0.025)
                 for i in range(400)]
        ts = make_trunk_set("BIG", freqs)
        assert len(ts.channels) == 400

    def test_many_conv_channels(self):
        """Create conv set with many channels."""
        channels = [
            {"short_name": f"CH{i:03d}", "tx_freq": 462.5 + i * 0.025,
             "long_name": f"Channel {i}"}
            for i in range(100)
        ]
        cs = make_conv_set("BIGCONV", channels)
        assert len(cs.channels) == 100

    def test_iden_set_full_16_entries(self):
        """IDEN set with all 16 entries populated."""
        entries = [
            {"chan_spacing_hz": 12500, "base_freq_hz": 851000000 + i * 500000,
             "bandwidth_hz": 6250, "tx_offset": 0, "iden_type": 0}
            for i in range(16)
        ]
        iden = make_iden_set("FULL16", entries)
        assert len(iden.elements) == 16

    def test_long_short_name_8_chars(self):
        """8-character short name (XG-100P limit)."""
        tg = make_p25_group(100, "ABCDEFGH", "Full 8")
        assert len(tg.group_name) == 8

    def test_long_long_name_16_chars(self):
        """16-character long name (XG-100P limit)."""
        tg = make_p25_group(100, "TEST", "1234567890123456")
        assert len(tg.long_name) == 16

    def test_validate_large_group_set(self):
        """Validation should handle large group sets without crashing."""
        tgs = [(i, f"TG{i:05d}", f"Talkgroup {i}") for i in range(200)]
        gs = make_group_set("LARGE", tgs)
        # validate_group_set should not crash
        from quickprs.validation import validate_group_set
        issues = validate_group_set(gs)
        assert isinstance(issues, list)

    def test_validate_large_trunk_set(self):
        """Validation should handle large trunk sets."""
        freqs = [(400.0 + i * 0.025, 400.0 + i * 0.025)
                 for i in range(300)]
        ts = make_trunk_set("BIG", freqs)
        from quickprs.validation import validate_trunk_set
        issues = validate_trunk_set(ts)
        assert isinstance(issues, list)


# ═══════════════════════════════════════════════════════════════════
# Multi-file batch CLI tests
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestCliBatch:
    """Batch mode CLI tests."""

    @pytest.fixture(autouse=True)
    def require_test_files(self):
        if not CLAUDE.exists() or not PAWS.exists():
            pytest.skip("test files not found")

    def test_info_multiple_files(self, capsys):
        result = run_cli(["info", str(CLAUDE), str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "claude test.PRS" in out
        assert "PAWSOVERMAWS.PRS" in out
        assert "Processed 2 files" in out

    def test_validate_multiple_files(self, capsys):
        result = run_cli(["validate", str(CLAUDE), str(PAWS)])
        assert result in (0, 1)
        out = capsys.readouterr().out
        assert "Batch validate" in out
        assert "2 files" in out

    def test_capacity_multiple_files(self, capsys):
        result = run_cli(["capacity", str(CLAUDE), str(PAWS)])
        assert result == 0

    def test_info_batch_with_missing(self, capsys):
        """Batch info with one missing file should still process others."""
        result = run_cli(["info", str(CLAUDE), "missing.PRS", str(PAWS)])
        assert result == 1  # worst exit code = 1 from missing file
        out = capsys.readouterr().out
        assert "claude test.PRS" in out

    def test_validate_batch_with_missing(self, capsys):
        """Batch validate with one missing should report error count."""
        result = run_cli(["validate", str(CLAUDE), "missing.PRS"])
        assert result == 1
        out = capsys.readouterr().out
        assert "1 errors" in out or "errors" in out


# ═══════════════════════════════════════════════════════════════════
# CLI create and roundtrip tests
# ═══════════════════════════════════════════════════════════════════


class TestCliCreate:
    """Tests for the create subcommand."""

    def test_create_basic(self, capsys, tmp_path):
        out = tmp_path / "new.PRS"
        result = run_cli(["create", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "Created" in out_text

    def test_create_with_name(self, capsys, tmp_path):
        out = tmp_path / "new.PRS"
        result = run_cli(["create", str(out), "--name", "MyRadio.PRS"])
        assert result == 0
        assert out.exists()

    def test_create_with_author(self, capsys, tmp_path):
        out = tmp_path / "new.PRS"
        result = run_cli(["create", str(out), "--author", "TestUser"])
        assert result == 0
        assert out.exists()

    def test_create_roundtrips(self, tmp_path):
        """Created file should roundtrip through parse/write."""
        out = tmp_path / "new.PRS"
        run_cli(["create", str(out)])

        original = out.read_bytes()
        prs = parse_prs(out)
        rebuilt = prs.to_bytes()
        assert original == rebuilt

    def test_create_validates(self, capsys, tmp_path):
        """Created file should pass validation."""
        out = tmp_path / "new.PRS"
        run_cli(["create", str(out)])
        result = run_cli(["validate", str(out)])
        assert result in (0, 1)  # may have info/warnings but shouldn't error

    def test_create_nested_dir(self, capsys, tmp_path):
        """Create should make parent directories."""
        out = tmp_path / "a" / "b" / "new.PRS"
        result = run_cli(["create", str(out)])
        assert result == 0
        assert out.exists()


# ═══════════════════════════════════════════════════════════════════
# PRSFile object tests
# ═══════════════════════════════════════════════════════════════════


class TestPRSFileObject:
    """Tests for PRSFile dataclass methods."""

    def test_empty_prsfile(self):
        prs = PRSFile()
        assert prs.sections == []
        assert prs.to_bytes() == b""

    def test_get_section_by_class_not_found(self):
        prs = PRSFile()
        assert prs.get_section_by_class("NonExistent") is None

    def test_get_sections_by_class_not_found(self):
        prs = PRSFile()
        assert prs.get_sections_by_class("NonExistent") == []

    def test_get_section_by_class_returns_first(self):
        prs = PRSFile(sections=[
            Section(offset=0, raw=b"\xff\xff\x01", class_name="CTest"),
            Section(offset=3, raw=b"\xff\xff\x02", class_name="CTest"),
        ])
        sec = prs.get_section_by_class("CTest")
        assert sec.raw == b"\xff\xff\x01"

    def test_get_sections_by_class_returns_all(self):
        prs = PRSFile(sections=[
            Section(offset=0, raw=b"\xff\xff\x01", class_name="CTest"),
            Section(offset=3, raw=b"\xff\xff\x02", class_name="CTest"),
            Section(offset=6, raw=b"\xff\xff\x03", class_name="COther"),
        ])
        secs = prs.get_sections_by_class("CTest")
        assert len(secs) == 2

    def test_to_bytes_concatenates(self):
        prs = PRSFile(sections=[
            Section(offset=0, raw=b"\x01\x02"),
            Section(offset=2, raw=b"\x03\x04"),
        ])
        assert prs.to_bytes() == b"\x01\x02\x03\x04"

    def test_summary_returns_string(self):
        prs = PRSFile(sections=[
            Section(offset=0, raw=b"\xff\xff", class_name="CTest"),
        ])
        result = prs.summary()
        assert isinstance(result, str)
        assert "CTest" in result
        assert "Sections: 1" in result


# ═══════════════════════════════════════════════════════════════════
# Section marker edge cases
# ═══════════════════════════════════════════════════════════════════


class TestSectionMarkerEdges:
    """Edge cases for section marker detection."""

    def test_find_ffff_single_byte(self):
        """Single 0xFF should not trigger."""
        assert find_all_ffff(b"\xff") == []

    def test_find_ffff_single_ff(self):
        """Single 0xFF in middle should not trigger."""
        assert find_all_ffff(b"\x00\xff\x00") == []

    def test_find_ffff_triple_ff(self):
        """0xFF 0xFF 0xFF should find marker at 0 only (skips by 2)."""
        positions = find_all_ffff(b"\xff\xff\xff")
        assert positions == [0]

    def test_find_ffff_six_ff(self):
        """Six 0xFF bytes: markers at 0, 2, 4."""
        positions = find_all_ffff(b"\xff" * 6)
        assert positions == [0, 2, 4]

    def test_class_name_non_c_prefix(self):
        """Class name not starting with C should be rejected."""
        data = b"\xff\xff\x00\x00\x04\x00Data"
        name, _ = try_read_class_name(data, 0)
        assert name is None

    def test_class_name_with_underscore(self):
        """Class name with underscore should be accepted."""
        data = b"\xff\xff\x00\x00\x07\x00C_Test1"
        name, size = try_read_class_name(data, 0)
        assert name == "C_Test1"
        assert size == 2 + 2 + 2 + 7

    def test_class_name_non_alphanumeric_rejected(self):
        """Class name with special chars should be rejected."""
        data = b"\xff\xff\x00\x00\x06\x00C!Test"
        name, _ = try_read_class_name(data, 0)
        assert name is None

    def test_class_name_empty_rejected(self):
        """Zero-length class name should be rejected."""
        data = b"\xff\xff\x00\x00\x00\x00"
        name, _ = try_read_class_name(data, 0)
        assert name is None


# ═══════════════════════════════════════════════════════════════════
# Bool edge cases
# ═══════════════════════════════════════════════════════════════════


class TestBoolEdges:
    """Edge cases for boolean read/write."""

    def test_read_bool_nonzero_is_true(self):
        """Any nonzero byte should read as True."""
        val, _ = read_bool(b"\x02", 0)
        assert val is True

    def test_read_bool_ff_is_true(self):
        val, _ = read_bool(b"\xff", 0)
        assert val is True

    def test_write_bool_truthy_values(self):
        """Various truthy Python values should write as 0x01."""
        assert write_bool(1) == b"\x01"
        assert write_bool(42) == b"\x01"
        assert write_bool("yes") == b"\x01"

    def test_write_bool_falsy_values(self):
        """Various falsy Python values should write as 0x00."""
        assert write_bool(0) == b"\x00"
        assert write_bool(None) == b"\x00"
        assert write_bool("") == b"\x00"


# ═══════════════════════════════════════════════════════════════════
# Completions module import test
# ═══════════════════════════════════════════════════════════════════


class TestCompletionsModule:
    """Verify completions module loads and has expected attributes."""

    def test_import_completions(self):
        mod = importlib.import_module("quickprs.completions")
        assert hasattr(mod, "generate_bash_completion")
        assert hasattr(mod, "generate_powershell_completion")

    def test_subcommands_not_empty(self):
        from quickprs.completions import SUBCOMMANDS
        assert len(SUBCOMMANDS) > 0

    def test_option_paths_not_empty(self):
        from quickprs.completions import OPTION_PATHS
        assert len(OPTION_PATHS) > 0
