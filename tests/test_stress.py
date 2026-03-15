"""Comprehensive stress test — exercises every CLI command end-to-end.

Verifies that no command crashes with a traceback. Every command should either
return 0 (success) or a controlled error code (1), never an unhandled exception.
"""

import csv
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from quickprs.cli import (
    run_cli, cmd_info, cmd_validate, cmd_export_csv, cmd_compare, cmd_dump,
    cmd_diff_options, cmd_iden_templates, cmd_create, cmd_inject_p25,
    cmd_inject_conv, cmd_inject_talkgroups, cmd_merge, cmd_clone,
    cmd_clone_personality, cmd_renumber, cmd_auto_name, cmd_export_json,
    cmd_import_json, cmd_build, cmd_export_config, cmd_profiles, cmd_fleet,
    cmd_remove, cmd_edit, cmd_set_option, cmd_repair, cmd_capacity,
    cmd_report, cmd_zones, cmd_stats, cmd_card, cmd_list,
    cmd_bulk_edit_talkgroups, cmd_bulk_edit_channels, cmd_encrypt, cmd_set_nac,
    cmd_rename, cmd_sort, cmd_freq_tools, cmd_systems, cmd_cleanup,
    cmd_search, cmd_template_csv, cmd_backup, cmd_diff_report,
    cmd_import_scanner,
)
from quickprs.prs_parser import parse_prs
from quickprs.builder import create_blank_prs
from quickprs.prs_writer import write_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
FREQS_CSV = TESTDATA / "test_freqs.csv"
TGS_CSV = TESTDATA / "test_tgs.csv"
CONV_CSV = TESTDATA / "test_conv_channels.csv"
EXAMPLE_INI = TESTDATA / "example_patrol.ini"
UNITS_CSV = TESTDATA / "test_units.csv"


# ─── Helpers ─────────────────────────────────────────────────────────


def _copy_prs(src, dest_dir, name="work.PRS"):
    """Copy a PRS file and return the copy's path string."""
    dst = Path(dest_dir) / name
    shutil.copy2(src, dst)
    return str(dst)


def _make_blank(dest_dir, name="blank.PRS"):
    """Create a minimal blank PRS file and return its path string."""
    out = Path(dest_dir) / name
    prs = create_blank_prs(filename=name, saved_by="test")
    out.write_bytes(prs.to_bytes())
    return str(out)


def _make_populated(dest_dir, name="populated.PRS"):
    """Create a PRS with a P25 system + conv channels and return its path."""
    blank = _make_blank(dest_dir, name)
    cmd_inject_p25(
        blank, "TEST", sysid=100,
        freqs_csv=str(FREQS_CSV),
        tgs_csv=str(TGS_CSV),
    )
    cmd_inject_conv(blank, "MURS", template="murs")
    return blank


def _make_tgs_csv(dest_dir, count=10, filename="gen_tgs.csv"):
    """Generate a talkgroups CSV with N entries."""
    path = Path(dest_dir) / filename
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["id", "short_name", "long_name", "tx", "scan"])
        for i in range(1, count + 1):
            writer.writerow([i * 100, f"TG{i:04d}", f"Talkgroup {i}", "N", "Y"])
    return str(path)


def _make_freqs_csv(dest_dir, count=5, filename="gen_freqs.csv"):
    """Generate a frequencies CSV with N entries."""
    path = Path(dest_dir) / filename
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["tx_freq", "rx_freq"])
        for i in range(count):
            freq = 851.0125 + (i * 0.025)
            writer.writerow([f"{freq:.4f}", f"{freq:.4f}"])
    return str(path)


def _make_conv_csv(dest_dir, count=5, filename="gen_conv.csv"):
    """Generate a conventional channels CSV."""
    path = Path(dest_dir) / filename
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["short_name", "tx_freq", "rx_freq",
                          "tx_tone", "rx_tone", "long_name"])
        for i in range(1, count + 1):
            freq = 462.5625 + (i * 0.025)
            writer.writerow([
                f"CH{i}", f"{freq:.4f}", f"{freq:.4f}",
                "100.0", "100.0", f"Channel {i}",
            ])
    return str(path)


def _make_units_csv(dest_dir, count=3, filename="gen_units.csv"):
    """Generate a units CSV for fleet builds."""
    path = Path(dest_dir) / filename
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["unit_id", "name", "password"])
        for i in range(1, count + 1):
            writer.writerow([1000 + i, f"UNIT{i}", f"{1000 + i}"])
    return str(path)


# ═════════════════════════════════════════════════════════════════════
# Test: Every CLI command exercised end-to-end
# ═════════════════════════════════════════════════════════════════════


class TestEveryCliCommand:
    """Exercise every CLI command to verify no crashes."""

    # ─── create ──────────────────────────────────────────────────────

    def test_create_blank(self, tmp_path, capsys):
        """create: should produce a valid PRS file."""
        out = str(tmp_path / "new.PRS")
        rc = cmd_create(out, name="TEST.PRS", author="Tester")
        assert rc == 0
        assert Path(out).exists()
        prs = parse_prs(out)
        assert len(prs.sections) > 0

    def test_create_no_name(self, tmp_path, capsys):
        """create: should default name from filename."""
        out = str(tmp_path / "auto.PRS")
        rc = cmd_create(out)
        assert rc == 0
        assert Path(out).exists()

    # ─── inject p25 ──────────────────────────────────────────────────

    def test_inject_p25_full(self, tmp_path, capsys):
        """inject p25: with freqs + tgs into blank PRS."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_p25(
            prs_file, "PSERN", sysid=892,
            long_name="PSERN SEATTLE",
            wacn=781824,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Injected" in out

    def test_inject_p25_no_data(self, tmp_path, capsys):
        """inject p25: without freqs or tgs — should still work."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_p25(prs_file, "BARE", sysid=1)
        assert rc == 0

    def test_inject_p25_explicit_iden(self, tmp_path, capsys):
        """inject p25: with explicit IDEN params."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_p25(
            prs_file, "IDENX", sysid=50,
            iden_base=851012500, iden_spacing=12500,
        )
        assert rc == 0

    # ─── inject conv ─────────────────────────────────────────────────

    def test_inject_conv_template(self, tmp_path, capsys):
        """inject conv: from built-in template."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_conv(prs_file, "MURS", template="murs")
        assert rc == 0
        out = capsys.readouterr().out
        assert "Injected conv system" in out

    def test_inject_conv_csv(self, tmp_path, capsys):
        """inject conv: from CSV file."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_conv(
            prs_file, "CUSTOM",
            channels_csv=str(CONV_CSV),
        )
        assert rc == 0

    def test_inject_conv_all_templates(self, tmp_path, capsys):
        """inject conv: every built-in template should work."""
        from quickprs.templates import get_template_names
        for tmpl in get_template_names():
            prs_file = _make_blank(tmp_path, f"{tmpl}.PRS")
            rc = cmd_inject_conv(prs_file, tmpl[:8].upper(), template=tmpl)
            assert rc == 0, f"Template '{tmpl}' failed"

    def test_inject_conv_no_source_error(self, tmp_path, capsys):
        """inject conv: no CSV or template should return error."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_conv(prs_file, "EMPTY")
        assert rc == 1

    # ─── inject talkgroups ───────────────────────────────────────────

    def test_inject_talkgroups(self, tmp_path, capsys):
        """inject talkgroups: add TGs to existing group set."""
        prs_file = _make_populated(tmp_path)
        extra_tgs = _make_tgs_csv(tmp_path, count=5, filename="extra.csv")
        rc = cmd_inject_talkgroups(prs_file, "TEST", extra_tgs)
        assert rc == 0

    # ─── import-scanner ──────────────────────────────────────────────

    def test_import_scanner_chirp(self, tmp_path, capsys):
        """import-scanner: CHIRP CSV should import."""
        chirp_csv = TESTDATA / "test_chirp.csv"
        if not chirp_csv.exists():
            pytest.skip("test_chirp.csv not available")
        prs_file = _make_blank(tmp_path)
        rc = cmd_import_scanner(prs_file, str(chirp_csv), name="CHIRP")
        assert rc == 0

    def test_import_scanner_uniden(self, tmp_path, capsys):
        """import-scanner: Uniden CSV should import."""
        uniden_csv = TESTDATA / "test_uniden.csv"
        if not uniden_csv.exists():
            pytest.skip("test_uniden.csv not available")
        prs_file = _make_blank(tmp_path)
        rc = cmd_import_scanner(prs_file, str(uniden_csv), name="UNIDEN")
        assert rc == 0

    # ─── merge ───────────────────────────────────────────────────────

    def test_merge_two_prs(self, tmp_path, capsys):
        """merge: source systems should appear in target."""
        target = _make_blank(tmp_path, "target.PRS")
        source = _make_populated(tmp_path, "source.PRS")
        output = str(tmp_path / "merged.PRS")
        rc = cmd_merge(target, source, output=output)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Merged" in out

    def test_merge_systems_only(self, tmp_path, capsys):
        """merge: with systems-only flag."""
        target = _make_blank(tmp_path, "t2.PRS")
        source = _make_populated(tmp_path, "s2.PRS")
        rc = cmd_merge(target, source, include_systems=True,
                       include_channels=False)
        assert rc == 0

    # ─── clone ───────────────────────────────────────────────────────

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_clone_system(self, tmp_path, capsys):
        """clone: clone a system between files."""
        target = _make_blank(tmp_path, "clone_target.PRS")
        source = _copy_prs(PAWS, tmp_path, "clone_source.PRS")
        output = str(tmp_path / "cloned.PRS")
        rc = cmd_clone(target, source, "PSERN SEATTLE", output=output)
        assert rc == 0

    # ─── clone-personality ───────────────────────────────────────────

    def test_clone_personality_exact(self, tmp_path, capsys):
        """clone-personality: exact copy (no modifications)."""
        src = _make_populated(tmp_path, "src.PRS")
        out = str(tmp_path / "clone_exact.PRS")
        rc = cmd_clone_personality(src, out)
        assert rc == 0
        assert Path(out).exists()

    def test_clone_personality_with_mods(self, tmp_path, capsys):
        """clone-personality: with name change and set removal."""
        src = _make_populated(tmp_path, "src2.PRS")
        out = str(tmp_path / "clone_mod.PRS")
        rc = cmd_clone_personality(
            src, out, name="MODIFIED",
            remove_sets=["MURS"],
        )
        assert rc == 0

    # ─── remove ──────────────────────────────────────────────────────

    def test_remove_conv_set(self, tmp_path, capsys):
        """remove: remove a conv set."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_remove(prs_file, "conv-set", "MURS")
        assert rc == 0

    def test_remove_nonexistent_error(self, tmp_path, capsys):
        """remove: removing nonexistent set should return 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_remove(prs_file, "group-set", "NOPE")
        assert rc == 1

    def test_remove_unknown_type_error(self, tmp_path, capsys):
        """remove: unknown remove type returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_remove(prs_file, "unknown-type", "X")
        assert rc == 1

    # ─── edit ────────────────────────────────────────────────────────

    def test_edit_name(self, tmp_path, capsys):
        """edit: rename personality."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_edit(prs_file, name="NEW NAME.PRS")
        assert rc == 0

    def test_edit_author(self, tmp_path, capsys):
        """edit: change author."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_edit(prs_file, author="New Author")
        assert rc == 0

    def test_edit_no_changes_error(self, tmp_path, capsys):
        """edit: no changes specified returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_edit(prs_file)
        assert rc == 1

    # ─── info ────────────────────────────────────────────────────────

    def test_info_blank(self, tmp_path, capsys):
        """info: on blank PRS should not crash."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_info(prs_file)
        assert rc == 0

    def test_info_populated(self, tmp_path, capsys):
        """info: on populated PRS should show systems."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_info(prs_file)
        assert rc == 0
        out = capsys.readouterr().out
        assert "TEST" in out

    def test_info_detail(self, tmp_path, capsys):
        """info: with --detail flag should not crash."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_info(prs_file, detail=True)
        assert rc == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_info_real_file(self, capsys):
        """info: on real PAWS file."""
        rc = cmd_info(str(PAWS), detail=True)
        assert rc == 0

    # ─── validate ────────────────────────────────────────────────────

    def test_validate_blank(self, tmp_path, capsys):
        """validate: blank PRS should pass."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_validate(prs_file)
        assert rc in (0, 1)  # may have warnings

    def test_validate_populated(self, tmp_path, capsys):
        """validate: populated PRS should not crash."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_validate(prs_file)
        assert rc in (0, 1)

    # ─── export-csv ──────────────────────────────────────────────────

    def test_export_csv(self, tmp_path, capsys):
        """export-csv: should create CSV files."""
        prs_file = _make_populated(tmp_path)
        out_dir = str(tmp_path / "csv_out")
        rc = cmd_export_csv(prs_file, out_dir)
        assert rc == 0
        assert os.path.isdir(out_dir)

    # ─── export-json / import-json ───────────────────────────────────

    def test_export_import_json_roundtrip(self, tmp_path, capsys):
        """export-json + import-json: roundtrip should not crash."""
        prs_file = _make_populated(tmp_path)
        json_out = str(tmp_path / "export.json")
        rc = cmd_export_json(prs_file, output=json_out)
        assert rc == 0
        assert Path(json_out).exists()

        prs_out = str(tmp_path / "reimported.PRS")
        rc = cmd_import_json(json_out, output=prs_out)
        assert rc == 0
        assert Path(prs_out).exists()

    def test_export_json_compact(self, tmp_path, capsys):
        """export-json: compact mode."""
        prs_file = _make_populated(tmp_path)
        json_out = str(tmp_path / "compact.json")
        rc = cmd_export_json(prs_file, output=json_out, compact=True)
        assert rc == 0

    # ─── export (third-party formats) ────────────────────────────────

    def test_export_chirp(self, tmp_path, capsys):
        """export chirp: should produce CSV."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "chirp.csv")
        rc = run_cli(["export", prs_file, "chirp", "-o", out])
        assert rc == 0

    def test_export_sdrtrunk(self, tmp_path, capsys):
        """export sdrtrunk: should produce CSV."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "sdr.csv")
        rc = run_cli(["export", prs_file, "sdrtrunk", "-o", out])
        assert rc == 0

    def test_export_dsd(self, tmp_path, capsys):
        """export dsd: should produce freq list."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "freqs.txt")
        rc = run_cli(["export", prs_file, "dsd", "-o", out])
        assert rc == 0

    def test_export_markdown(self, tmp_path, capsys):
        """export markdown: should produce .md file."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "doc.md")
        rc = run_cli(["export", prs_file, "markdown", "-o", out])
        assert rc == 0

    def test_export_uniden(self, tmp_path, capsys):
        """export uniden: should produce CSV."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "uniden.csv")
        rc = run_cli(["export", prs_file, "uniden", "-o", out])
        assert rc == 0

    # ─── export-config ───────────────────────────────────────────────

    def test_export_config(self, tmp_path, capsys):
        """export-config: should create INI file."""
        prs_file = _make_populated(tmp_path)
        ini_out = str(tmp_path / "config.ini")
        rc = cmd_export_config(prs_file, output=ini_out)
        assert rc == 0
        assert Path(ini_out).exists()

    # ─── build ───────────────────────────────────────────────────────

    def test_build_from_ini(self, tmp_path, capsys):
        """build: from example INI config."""
        if not EXAMPLE_INI.exists():
            pytest.skip("Example INI not available")
        out = str(tmp_path / "built.PRS")
        rc = cmd_build(str(EXAMPLE_INI), output=out)
        assert rc == 0
        assert Path(out).exists()

    def test_build_missing_config_error(self, tmp_path, capsys):
        """build: missing config should return 1."""
        rc = cmd_build(str(tmp_path / "nope.ini"))
        assert rc == 1

    # ─── profiles ────────────────────────────────────────────────────

    def test_profiles_list(self, capsys):
        """profiles list: should show available profiles."""
        rc = cmd_profiles("list")
        assert rc == 0
        out = capsys.readouterr().out
        assert "scanner_basic" in out.lower() or "profile" in out.lower()

    def test_profiles_build(self, tmp_path, capsys):
        """profiles build: should create PRS from profile."""
        out = str(tmp_path / "scanner.PRS")
        rc = cmd_profiles("build", "scanner_basic", output=out)
        assert rc == 0
        assert Path(out).exists()

    def test_profiles_build_unknown_error(self, capsys):
        """profiles build: unknown profile should return 1."""
        rc = cmd_profiles("build", "nonexistent_profile_xyz")
        assert rc == 1

    # ─── fleet ───────────────────────────────────────────────────────

    def test_fleet_build(self, tmp_path, capsys):
        """fleet: should create per-unit PRS files."""
        if not EXAMPLE_INI.exists():
            pytest.skip("Example INI not available")
        units = _make_units_csv(tmp_path)
        out_dir = str(tmp_path / "fleet_out")
        rc = cmd_fleet(str(EXAMPLE_INI), units, output_dir=out_dir)
        assert rc == 0
        assert Path(out_dir).exists()

    def test_fleet_missing_config_error(self, tmp_path, capsys):
        """fleet: missing config should return 1."""
        units = _make_units_csv(tmp_path)
        rc = cmd_fleet(str(tmp_path / "nope.ini"), units)
        assert rc == 1

    # ─── compare ─────────────────────────────────────────────────────

    def test_compare_identical(self, tmp_path, capsys):
        """compare: same file should show no differences."""
        prs_file = _make_blank(tmp_path)
        copy = _copy_prs(Path(prs_file), tmp_path, "copy.PRS")
        rc = cmd_compare(prs_file, copy)
        assert rc == 0

    def test_compare_different(self, tmp_path, capsys):
        """compare: different files should show changes."""
        blank = _make_blank(tmp_path, "a.PRS")
        populated = _make_populated(tmp_path, "b.PRS")
        rc = cmd_compare(blank, populated)
        assert rc in (0, 1)  # 1 if differences found

    def test_compare_detail(self, tmp_path, capsys):
        """compare --detail: should not crash."""
        blank = _make_blank(tmp_path, "c.PRS")
        populated = _make_populated(tmp_path, "d.PRS")
        rc = cmd_compare(blank, populated, detail=True)
        assert rc in (0, 1)

    # ─── dump ────────────────────────────────────────────────────────

    def test_dump_all_sections(self, tmp_path, capsys):
        """dump: list all sections."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_dump(prs_file)
        assert rc == 0

    def test_dump_single_section(self, tmp_path, capsys):
        """dump: single section with hex."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_dump(prs_file, section_idx=0, hex_bytes=64)
        assert rc == 0

    def test_dump_invalid_section(self, tmp_path, capsys):
        """dump: invalid section index returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_dump(prs_file, section_idx=999)
        assert rc == 1

    # ─── diff-options ────────────────────────────────────────────────

    def test_diff_options(self, tmp_path, capsys):
        """diff-options: between two files."""
        a = _make_blank(tmp_path, "opt_a.PRS")
        b = _make_blank(tmp_path, "opt_b.PRS")
        rc = cmd_diff_options(a, b)
        assert rc == 0

    def test_diff_options_raw(self, tmp_path, capsys):
        """diff-options --raw: with raw byte diffs."""
        a = _make_blank(tmp_path, "raw_a.PRS")
        b = _make_blank(tmp_path, "raw_b.PRS")
        rc = cmd_diff_options(a, b, raw=True)
        assert rc == 0

    # ─── iden-templates ──────────────────────────────────────────────

    def test_iden_templates(self, capsys):
        """iden-templates: list should not crash."""
        rc = cmd_iden_templates()
        assert rc == 0

    def test_iden_templates_detail(self, capsys):
        """iden-templates --detail: should show entries."""
        rc = cmd_iden_templates(detail=True)
        assert rc == 0

    # ─── set-option ──────────────────────────────────────────────────

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_set_option_list(self, tmp_path, capsys):
        """set-option --list: should show options."""
        prs_file = _copy_prs(PAWS, tmp_path)
        rc = cmd_set_option(prs_file, list_opts=True)
        assert rc == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_set_option_read(self, tmp_path, capsys):
        """set-option: read a value."""
        prs_file = _copy_prs(PAWS, tmp_path)
        rc = cmd_set_option(prs_file, option_path="gps.gpsMode")
        assert rc == 0

    def test_set_option_no_xml_error(self, tmp_path, capsys):
        """set-option --list: on file without XML returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_set_option(prs_file, list_opts=True)
        assert rc == 1

    def test_set_option_no_path_error(self, tmp_path, capsys):
        """set-option: no option path returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_set_option(prs_file)
        assert rc == 1

    # ─── repair ──────────────────────────────────────────────────────

    def test_repair_valid_file(self, tmp_path, capsys):
        """repair: valid file should say no issues."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_repair(prs_file)
        assert rc == 0
        out = capsys.readouterr().out
        assert "already valid" in out or "No structural" in out

    def test_repair_salvage(self, tmp_path, capsys):
        """repair --salvage: should not crash on valid file."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_repair(prs_file, salvage=True)
        assert rc == 0

    def test_repair_output(self, tmp_path, capsys):
        """repair: with output file."""
        prs_file = _make_populated(tmp_path)
        out = str(tmp_path / "repaired.PRS")
        rc = cmd_repair(prs_file, output=out)
        assert rc == 0

    # ─── capacity ────────────────────────────────────────────────────

    def test_capacity(self, tmp_path, capsys):
        """capacity: should show usage report."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_capacity(prs_file)
        assert rc == 0

    # ─── report ──────────────────────────────────────────────────────

    def test_report(self, tmp_path, capsys):
        """report: should generate HTML."""
        prs_file = _make_populated(tmp_path)
        html_out = str(tmp_path / "report.html")
        rc = cmd_report(prs_file, output=html_out)
        assert rc == 0
        assert Path(html_out).exists()

    # ─── zones ───────────────────────────────────────────────────────

    def test_zones_auto(self, tmp_path, capsys):
        """zones: auto strategy."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_zones(prs_file)
        assert rc == 0

    def test_zones_by_set(self, tmp_path, capsys):
        """zones: by_set strategy."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_zones(prs_file, strategy="by_set")
        assert rc == 0

    def test_zones_export(self, tmp_path, capsys):
        """zones: export to CSV."""
        prs_file = _make_populated(tmp_path)
        csv_out = str(tmp_path / "zones.csv")
        rc = cmd_zones(prs_file, export=csv_out)
        assert rc == 0

    # ─── stats ───────────────────────────────────────────────────────

    def test_stats(self, tmp_path, capsys):
        """stats: should show statistics."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_stats(prs_file)
        assert rc == 0

    # ─── card ────────────────────────────────────────────────────────

    def test_card(self, tmp_path, capsys):
        """card: should generate summary card HTML."""
        prs_file = _make_populated(tmp_path)
        html_out = str(tmp_path / "card.html")
        rc = cmd_card(prs_file, output=html_out)
        assert rc == 0
        assert Path(html_out).exists()

    # ─── list ────────────────────────────────────────────────────────

    def test_list_systems(self, tmp_path, capsys):
        """list systems: should show systems."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_list(prs_file, "systems")
        assert rc == 0

    def test_list_talkgroups(self, tmp_path, capsys):
        """list talkgroups: should show TGs."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_list(prs_file, "talkgroups")
        assert rc == 0

    def test_list_channels(self, tmp_path, capsys):
        """list channels: should show conv channels."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_list(prs_file, "channels")
        assert rc == 0

    def test_list_frequencies(self, tmp_path, capsys):
        """list frequencies: should show trunk freqs."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_list(prs_file, "frequencies")
        assert rc == 0

    def test_list_sets(self, tmp_path, capsys):
        """list sets: should show all set types."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_list(prs_file, "sets")
        assert rc == 0

    def test_list_options(self, tmp_path, capsys):
        """list options: should not crash (may show nothing on blank)."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_list(prs_file, "options")
        assert rc == 0

    def test_list_unknown_type_error(self, tmp_path, capsys):
        """list: unknown type returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_list(prs_file, "bogus")
        assert rc == 1

    # ─── bulk-edit talkgroups ────────────────────────────────────────

    def test_bulk_edit_tg_enable_scan(self, tmp_path, capsys):
        """bulk-edit talkgroups: enable scan."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_bulk_edit_talkgroups(prs_file, "TEST", enable_scan=True)
        assert rc == 0

    def test_bulk_edit_tg_disable_tx(self, tmp_path, capsys):
        """bulk-edit talkgroups: disable TX."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_bulk_edit_talkgroups(prs_file, "TEST", disable_tx=True)
        assert rc == 0

    def test_bulk_edit_tg_prefix(self, tmp_path, capsys):
        """bulk-edit talkgroups: add prefix."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_bulk_edit_talkgroups(prs_file, "TEST", prefix="PD ")
        assert rc == 0

    # ─── bulk-edit channels ──────────────────────────────────────────

    def test_bulk_edit_ch_set_tone(self, tmp_path, capsys):
        """bulk-edit channels: set tone."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_bulk_edit_channels(prs_file, "MURS", set_tone="100.0")
        assert rc == 0

    def test_bulk_edit_ch_clear_tones(self, tmp_path, capsys):
        """bulk-edit channels: clear tones."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_bulk_edit_channels(prs_file, "MURS", clear_tones=True)
        assert rc == 0

    # ─── encrypt ─────────────────────────────────────────────────────

    def test_encrypt_all(self, tmp_path, capsys):
        """encrypt: enable encryption on all TGs."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_encrypt(prs_file, "TEST", encrypt_all=True, key_id=1)
        assert rc == 0

    def test_encrypt_single_tg(self, tmp_path, capsys):
        """encrypt: encrypt single TG."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_encrypt(prs_file, "TEST", tg_id=100, key_id=1)
        assert rc == 0

    def test_encrypt_decrypt(self, tmp_path, capsys):
        """encrypt --decrypt: remove encryption."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_encrypt(prs_file, "TEST", encrypt_all=True, decrypt=True)
        assert rc == 0

    def test_encrypt_no_target_error(self, tmp_path, capsys):
        """encrypt: no --tg or --all returns 1."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_encrypt(prs_file, "TEST")
        assert rc == 1

    # ─── rename ──────────────────────────────────────────────────────

    def test_rename_talkgroups(self, tmp_path, capsys):
        """rename: regex rename on talkgroup short names."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_rename(prs_file, "TEST", "^DISP$", "DSP",
                        set_type="group", field="short_name")
        assert rc == 0

    def test_rename_no_match(self, tmp_path, capsys):
        """rename: no matching pattern returns 0."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_rename(prs_file, "TEST", "ZZZZZ", "YYYY",
                        set_type="group")
        assert rc == 0

    # ─── sort ────────────────────────────────────────────────────────

    def test_sort_conv_by_freq(self, tmp_path, capsys):
        """sort: conv set by frequency."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_sort(prs_file, "MURS", set_type="conv",
                      key="frequency")
        assert rc == 0

    def test_sort_conv_by_name(self, tmp_path, capsys):
        """sort: conv set by name."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_sort(prs_file, "MURS", set_type="conv", key="name")
        assert rc == 0

    def test_sort_group_by_id(self, tmp_path, capsys):
        """sort: group set by ID."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_sort(prs_file, "TEST", set_type="group", key="id")
        assert rc == 0

    def test_sort_reverse(self, tmp_path, capsys):
        """sort: reverse order."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_sort(prs_file, "MURS", set_type="conv",
                      key="name", reverse=True)
        assert rc == 0

    def test_sort_nonexistent_set_error(self, tmp_path, capsys):
        """sort: nonexistent set returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_sort(prs_file, "NOPE", set_type="conv", key="name")
        assert rc == 1

    # ─── renumber ────────────────────────────────────────────────────

    def test_renumber_conv(self, tmp_path, capsys):
        """renumber: renumber conv channels."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_renumber(prs_file, set_name="MURS", start=10)
        assert rc == 0

    def test_renumber_no_match_error(self, tmp_path, capsys):
        """renumber: set not found returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_renumber(prs_file, set_name="NOPE")
        assert rc == 1

    # ─── auto-name ───────────────────────────────────────────────────

    def test_auto_name(self, tmp_path, capsys):
        """auto-name: generate short names from long names."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_auto_name(prs_file, "TEST", style="compact")
        assert rc == 0

    def test_auto_name_not_found_error(self, tmp_path, capsys):
        """auto-name: set not found returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_auto_name(prs_file, "NOPE")
        assert rc == 1

    # ─── freq-tools ──────────────────────────────────────────────────

    def test_freq_tools_offset(self, capsys):
        """freq-tools offset: should show repeater offset info."""
        rc = cmd_freq_tools("offset", freq=146.94)
        assert rc == 0

    def test_freq_tools_channel(self, capsys):
        """freq-tools channel: should identify service."""
        rc = cmd_freq_tools("channel", freq=462.5625)
        assert rc == 0

    def test_freq_tools_tones(self, capsys):
        """freq-tools tones: list CTCSS tones."""
        rc = cmd_freq_tools("tones")
        assert rc == 0

    def test_freq_tools_dcs(self, capsys):
        """freq-tools dcs: list DCS codes."""
        rc = cmd_freq_tools("dcs")
        assert rc == 0

    def test_freq_tools_nearest(self, capsys):
        """freq-tools nearest: find closest CTCSS tone."""
        rc = cmd_freq_tools("nearest", freq=100.5)
        assert rc == 0

    def test_freq_tools_identify(self, capsys):
        """freq-tools identify: identify a frequency."""
        rc = cmd_freq_tools("identify", freq=462.5625)
        assert rc == 0

    def test_freq_tools_all_offsets(self, capsys):
        """freq-tools all-offsets: show all offsets."""
        rc = cmd_freq_tools("all-offsets", freq=146.94)
        assert rc == 0

    def test_freq_tools_conflicts(self, capsys):
        """freq-tools conflicts: check frequency conflicts."""
        rc = cmd_freq_tools("conflicts",
                            freq_list=[462.5625, 462.5875, 462.6125])
        assert rc == 0

    def test_freq_tools_unknown_error(self, capsys):
        """freq-tools: unknown subcommand returns 1."""
        rc = cmd_freq_tools("bogus")
        assert rc == 1

    # ─── systems database ────────────────────────────────────────────

    def test_systems_list(self, capsys):
        """systems list: should show database entries."""
        rc = cmd_systems("list")
        assert rc == 0

    def test_systems_search(self, capsys):
        """systems search: should search by name."""
        rc = cmd_systems("search", query="seattle")
        assert rc == 0

    def test_systems_search_no_query_error(self, capsys):
        """systems search: no query returns 1."""
        rc = cmd_systems("search")
        assert rc == 1

    def test_systems_add(self, tmp_path, capsys):
        """systems add: add known system to PRS."""
        prs_file = _make_blank(tmp_path)
        # Try PSERN which should be in the database
        rc = cmd_systems("add", filepath=prs_file, system_name="PSERN")
        assert rc == 0

    def test_systems_info(self, capsys):
        """systems info: show system details."""
        rc = cmd_systems("info", system_name="PSERN")
        assert rc == 0

    def test_systems_unknown_cmd_error(self, capsys):
        """systems: unknown subcommand returns 1."""
        rc = cmd_systems("bogus")
        assert rc == 1

    # ─── cleanup ─────────────────────────────────────────────────────

    def test_cleanup_check(self, tmp_path, capsys):
        """cleanup --check: report duplicates."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_cleanup(prs_file, check=True)
        assert rc == 0

    def test_cleanup_fix(self, tmp_path, capsys):
        """cleanup --fix: show what would be removed."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_cleanup(prs_file, fix=True)
        assert rc == 0

    def test_cleanup_remove_unused(self, tmp_path, capsys):
        """cleanup --remove-unused: report unreferenced sets."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_cleanup(prs_file, remove_unused=True)
        assert rc == 0

    # ─── search ──────────────────────────────────────────────────────

    def test_search_freq(self, tmp_path, capsys):
        """search --freq: search by frequency across files."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_search([prs_file], freq=851.0125)
        assert rc == 0

    def test_search_tg(self, tmp_path, capsys):
        """search --tg: search by talkgroup ID."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_search([prs_file], tg=100)
        assert rc == 0

    def test_search_name(self, tmp_path, capsys):
        """search --name: search by name."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_search([prs_file], name="DISP")
        assert rc == 0

    def test_search_no_criteria_error(self, tmp_path, capsys):
        """search: no search criteria returns 1."""
        prs_file = _make_populated(tmp_path)
        rc = cmd_search([prs_file])
        assert rc == 1

    # ─── template-csv ────────────────────────────────────────────────

    def test_template_csv_frequencies(self, tmp_path, capsys):
        """template-csv frequencies: generate blank CSV template."""
        out = str(tmp_path / "freqs.csv")
        rc = cmd_template_csv("frequencies", output=out)
        assert rc == 0
        assert Path(out).exists()

    def test_template_csv_talkgroups(self, tmp_path, capsys):
        """template-csv talkgroups."""
        out = str(tmp_path / "tgs.csv")
        rc = cmd_template_csv("talkgroups", output=out)
        assert rc == 0

    def test_template_csv_channels(self, tmp_path, capsys):
        """template-csv channels."""
        out = str(tmp_path / "ch.csv")
        rc = cmd_template_csv("channels", output=out)
        assert rc == 0

    def test_template_csv_units(self, tmp_path, capsys):
        """template-csv units."""
        out = str(tmp_path / "units.csv")
        rc = cmd_template_csv("units", output=out)
        assert rc == 0

    def test_template_csv_config(self, tmp_path, capsys):
        """template-csv config."""
        out = str(tmp_path / "config.ini")
        rc = cmd_template_csv("config", output=out)
        assert rc == 0

    def test_template_csv_unknown_error(self, capsys):
        """template-csv: unknown type returns 1."""
        rc = cmd_template_csv("bogus")
        assert rc == 1

    # ─── backup ──────────────────────────────────────────────────────

    def test_backup_create(self, tmp_path, capsys):
        """backup: create a backup."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_backup(prs_file)
        assert rc == 0

    def test_backup_list(self, tmp_path, capsys):
        """backup --list: list backups."""
        prs_file = _make_blank(tmp_path)
        cmd_backup(prs_file)  # create one first
        rc = cmd_backup(prs_file, list_backups=True)
        assert rc == 0

    def test_backup_restore(self, tmp_path, capsys):
        """backup --restore: restore from backup."""
        prs_file = _make_blank(tmp_path)
        cmd_backup(prs_file)  # create backup
        rc = cmd_backup(prs_file, restore=True)
        assert rc == 0

    def test_backup_nonexistent_error(self, tmp_path, capsys):
        """backup: nonexistent file returns 1."""
        rc = cmd_backup(str(tmp_path / "nope.PRS"))
        assert rc == 1

    # ─── diff-report ─────────────────────────────────────────────────

    def test_diff_report_stdout(self, tmp_path, capsys):
        """diff-report: print to stdout."""
        a = _make_blank(tmp_path, "diff_a.PRS")
        b = _make_populated(tmp_path, "diff_b.PRS")
        rc = cmd_diff_report(a, b)
        assert rc == 0

    def test_diff_report_to_file(self, tmp_path, capsys):
        """diff-report: write to file."""
        a = _make_blank(tmp_path, "diff_c.PRS")
        b = _make_populated(tmp_path, "diff_d.PRS")
        out = str(tmp_path / "changes.txt")
        rc = cmd_diff_report(a, b, output=out)
        assert rc == 0

    # ─── set-nac ─────────────────────────────────────────────────────

    def test_set_nac_invalid_hex_error(self, tmp_path, capsys):
        """set-nac: invalid hex value returns 1."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_set_nac(prs_file, "TEST", nac="ZZZZ")
        assert rc == 1


# ═════════════════════════════════════════════════════════════════════
# Edge case / stress tests
# ═════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Test boundary conditions and error handling."""

    # ─── Missing file handling ───────────────────────────────────────

    def test_info_missing_file(self, capsys):
        """info: missing file returns 1 via run_cli."""
        rc = run_cli(["info", "nonexistent_file.PRS"])
        assert rc == 1

    def test_validate_missing_file(self, capsys):
        """validate: missing file returns 1."""
        rc = run_cli(["validate", "nonexistent_file.PRS"])
        assert rc == 1

    def test_dump_missing_file(self, capsys):
        """dump: missing file returns 1."""
        rc = run_cli(["dump", "nonexistent_file.PRS"])
        assert rc == 1

    def test_capacity_missing_file(self, capsys):
        """capacity: missing file returns 1."""
        rc = run_cli(["capacity", "nonexistent_file.PRS"])
        assert rc == 1

    def test_repair_missing_file(self, capsys):
        """repair: missing file returns 1."""
        rc = run_cli(["repair", "nonexistent_file.PRS"])
        assert rc == 1

    # ─── Unicode in names ────────────────────────────────────────────

    def test_create_unicode_name(self, tmp_path, capsys):
        """create: Unicode name should be handled gracefully."""
        out = str(tmp_path / "unicode.PRS")
        rc = cmd_create(out, name="Caf\u00e9 Radio.PRS")
        assert rc == 0

    def test_inject_unicode_system_name(self, tmp_path, capsys):
        """inject p25: Unicode system name should not crash."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_p25(prs_file, "CAF\u00c9", sysid=1)
        assert rc == 0

    def test_edit_unicode_author(self, tmp_path, capsys):
        """edit: Unicode author should not crash."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_edit(prs_file, author="Ren\u00e9")
        assert rc == 0

    # ─── Empty string handling ───────────────────────────────────────

    def test_create_empty_name(self, tmp_path, capsys):
        """create: empty name should use filename default."""
        out = str(tmp_path / "empty.PRS")
        rc = cmd_create(out, name="")
        assert rc == 0

    def test_inject_p25_empty_long_name(self, tmp_path, capsys):
        """inject p25: empty long_name should default to short name."""
        prs_file = _make_blank(tmp_path)
        rc = cmd_inject_p25(prs_file, "BARE", sysid=1, long_name="")
        assert rc == 0

    # ─── Large data handling ─────────────────────────────────────────

    def test_inject_many_talkgroups(self, tmp_path, capsys):
        """inject p25: inject 500 talkgroups (may have scan limit warning)."""
        prs_file = _make_blank(tmp_path)
        tgs = _make_tgs_csv(tmp_path, count=500)
        rc = cmd_inject_p25(
            prs_file, "BIG", sysid=1, tgs_csv=tgs,
        )
        # rc=1 is expected: >127 scan-enabled TGs triggers validation error
        assert rc in (0, 1)
        # File should still be written
        assert Path(prs_file).stat().st_size > 1000

    def test_inject_many_frequencies(self, tmp_path, capsys):
        """inject p25: inject 100 frequencies."""
        prs_file = _make_blank(tmp_path)
        freqs = _make_freqs_csv(tmp_path, count=100)
        rc = cmd_inject_p25(
            prs_file, "FREQ", sysid=1, freqs_csv=freqs,
        )
        assert rc == 0

    def test_inject_many_conv_channels(self, tmp_path, capsys):
        """inject conv: inject 200 conventional channels."""
        prs_file = _make_blank(tmp_path)
        channels = _make_conv_csv(tmp_path, count=200)
        rc = cmd_inject_conv(prs_file, "BIGCONV", channels_csv=channels)
        assert rc == 0

    # ─── Multiple systems in one file ────────────────────────────────

    def test_multiple_p25_systems(self, tmp_path, capsys):
        """inject: add 5 P25 systems to one file."""
        prs_file = _make_blank(tmp_path)
        for i in range(5):
            name = f"SYS{i}"[:8]
            tgs = _make_tgs_csv(tmp_path, count=10,
                                filename=f"tgs_{i}.csv")
            freqs = _make_freqs_csv(tmp_path, count=5,
                                    filename=f"freqs_{i}.csv")
            rc = cmd_inject_p25(
                prs_file, name, sysid=100 + i,
                tgs_csv=tgs, freqs_csv=freqs,
            )
            assert rc == 0

        # Verify with info
        rc = cmd_info(prs_file)
        assert rc == 0
        out = capsys.readouterr().out
        assert "SYS0" in out
        assert "SYS4" in out

    def test_multiple_conv_systems(self, tmp_path, capsys):
        """inject: add multiple conv systems."""
        prs_file = _make_blank(tmp_path)
        for tmpl in ["murs", "noaa", "frs"]:
            rc = cmd_inject_conv(prs_file, tmpl[:8].upper(), template=tmpl)
            assert rc == 0

        rc = cmd_info(prs_file)
        assert rc == 0
        out = capsys.readouterr().out
        assert "MURS" in out
        assert "NOAA" in out

    # ─── Output to different paths ───────────────────────────────────

    def test_inject_to_output_file(self, tmp_path, capsys):
        """inject: output to different file preserves original."""
        prs_file = _make_blank(tmp_path, "original.PRS")
        original_size = Path(prs_file).stat().st_size
        out = str(tmp_path / "output.PRS")
        rc = cmd_inject_conv(prs_file, "MURS", template="murs", output=out)
        assert rc == 0
        # Original should be unchanged
        assert Path(prs_file).stat().st_size == original_size
        # Output should be larger
        assert Path(out).stat().st_size > original_size

    # ─── Chained operations ──────────────────────────────────────────

    def test_full_workflow(self, tmp_path, capsys):
        """Full workflow: create -> inject -> edit -> export -> compare."""
        # Step 1: Create blank
        prs_file = str(tmp_path / "workflow.PRS")
        rc = cmd_create(prs_file, name="WORKFLOW.PRS", author="Test")
        assert rc == 0

        # Step 2: Inject P25 system
        rc = cmd_inject_p25(
            prs_file, "WKFLOW", sysid=42,
            freqs_csv=str(FREQS_CSV),
            tgs_csv=str(TGS_CSV),
        )
        assert rc == 0

        # Step 3: Inject conv channels
        rc = cmd_inject_conv(prs_file, "MURS", template="murs")
        assert rc == 0

        # Step 4: Edit metadata
        rc = cmd_edit(prs_file, name="EDITED.PRS", author="Editor")
        assert rc == 0

        # Step 5: Bulk edit
        rc = cmd_bulk_edit_talkgroups(prs_file, "WKFLOW", enable_scan=True)
        assert rc == 0

        # Step 6: Sort
        rc = cmd_sort(prs_file, "MURS", set_type="conv", key="name")
        assert rc == 0

        # Step 7: Rename
        rc = cmd_rename(prs_file, "WKFLOW", "^DISP$", "DSP",
                        set_type="group")
        assert rc == 0

        # Step 8: Validate
        rc = cmd_validate(prs_file)
        assert rc in (0, 1)

        # Step 9: Export JSON
        json_out = str(tmp_path / "workflow.json")
        rc = cmd_export_json(prs_file, output=json_out)
        assert rc == 0

        # Step 10: Export CSV
        csv_dir = str(tmp_path / "workflow_csv")
        rc = cmd_export_csv(prs_file, csv_dir)
        assert rc == 0

        # Step 11: Clone personality
        clone_out = str(tmp_path / "clone.PRS")
        rc = cmd_clone_personality(prs_file, clone_out, name="CLONE")
        assert rc == 0

        # Step 12: Compare original and clone
        rc = cmd_compare(prs_file, clone_out)
        assert rc in (0, 1)

        # Step 13: Info on final result
        rc = cmd_info(prs_file, detail=True)
        assert rc == 0

        # Step 14: Capacity check
        rc = cmd_capacity(prs_file)
        assert rc == 0

        # Step 15: Stats
        rc = cmd_stats(prs_file)
        assert rc == 0

        # Step 16: Zones
        rc = cmd_zones(prs_file)
        assert rc == 0

        # Step 17: Cleanup check
        rc = cmd_cleanup(prs_file, check=True)
        assert rc == 0

        # Step 18: Search
        rc = cmd_search([prs_file], name="MURS")
        assert rc == 0

        # Step 19: Report
        html_out = str(tmp_path / "report.html")
        rc = cmd_report(prs_file, output=html_out)
        assert rc == 0

        # Step 20: Card
        card_out = str(tmp_path / "card.html")
        rc = cmd_card(prs_file, output=card_out)
        assert rc == 0

        # Step 21: Diff report
        rc = cmd_diff_report(prs_file, clone_out)
        assert rc == 0

        # Step 22: Backup
        rc = cmd_backup(prs_file)
        assert rc == 0

        # Step 23: Remove a system
        rc = cmd_remove(prs_file, "conv-set", "MURS")
        assert rc == 0

        # Step 24: Repair (should find no issues)
        rc = cmd_repair(prs_file)
        assert rc == 0


# ═════════════════════════════════════════════════════════════════════
# Test: run_cli dispatcher for every command
# ═════════════════════════════════════════════════════════════════════


class TestRunCliDispatcher:
    """Verify the CLI argument parser routes to every command correctly."""

    def test_version(self):
        """--version should exit with 0."""
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0

    def test_no_args_returns_none(self):
        """No args returns None (GUI mode)."""
        result = run_cli([])
        assert result is None

    def test_create_via_cli(self, tmp_path, capsys):
        """create via run_cli."""
        out = str(tmp_path / "cli_create.PRS")
        rc = run_cli(["create", out, "--name", "CLI TEST"])
        assert rc == 0

    def test_info_via_cli(self, tmp_path, capsys):
        """info via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["info", prs_file])
        assert rc == 0

    def test_validate_via_cli(self, tmp_path, capsys):
        """validate via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["validate", prs_file])
        assert rc in (0, 1)

    def test_dump_via_cli(self, tmp_path, capsys):
        """dump via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["dump", prs_file])
        assert rc == 0

    def test_list_via_cli(self, tmp_path, capsys):
        """list via run_cli."""
        prs_file = _make_populated(tmp_path)
        rc = run_cli(["list", prs_file, "systems"])
        assert rc == 0

    def test_capacity_via_cli(self, tmp_path, capsys):
        """capacity via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["capacity", prs_file])
        assert rc == 0

    def test_stats_via_cli(self, tmp_path, capsys):
        """stats via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["stats", prs_file])
        assert rc == 0

    def test_zones_via_cli(self, tmp_path, capsys):
        """zones via run_cli."""
        prs_file = _make_populated(tmp_path)
        rc = run_cli(["zones", prs_file])
        assert rc == 0

    def test_cleanup_via_cli(self, tmp_path, capsys):
        """cleanup via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["cleanup", prs_file, "--check"])
        assert rc == 0

    def test_freq_tools_via_cli(self, capsys):
        """freq-tools via run_cli."""
        rc = run_cli(["freq-tools", "tones"])
        assert rc == 0

    def test_systems_via_cli(self, capsys):
        """systems via run_cli."""
        rc = run_cli(["systems", "list"])
        assert rc == 0

    def test_iden_templates_via_cli(self, capsys):
        """iden-templates via run_cli."""
        rc = run_cli(["iden-templates"])
        assert rc == 0

    def test_profiles_via_cli(self, capsys):
        """profiles via run_cli."""
        rc = run_cli(["profiles", "list"])
        assert rc == 0

    def test_template_csv_via_cli(self, tmp_path, capsys):
        """template-csv via run_cli."""
        out = str(tmp_path / "tmpl.csv")
        rc = run_cli(["template-csv", "frequencies", "-o", out])
        assert rc == 0

    def test_export_json_via_cli(self, tmp_path, capsys):
        """export-json via run_cli."""
        prs_file = _make_blank(tmp_path)
        out = str(tmp_path / "out.json")
        rc = run_cli(["export-json", prs_file, "-o", out])
        assert rc == 0

    def test_export_csv_via_cli(self, tmp_path, capsys):
        """export-csv via run_cli."""
        prs_file = _make_blank(tmp_path)
        out_dir = str(tmp_path / "csv_dir")
        rc = run_cli(["export-csv", prs_file, out_dir])
        assert rc == 0

    def test_compare_via_cli(self, tmp_path, capsys):
        """compare via run_cli."""
        a = _make_blank(tmp_path, "a.PRS")
        b = _make_blank(tmp_path, "b.PRS")
        rc = run_cli(["compare", a, b])
        assert rc == 0

    def test_diff_options_via_cli(self, tmp_path, capsys):
        """diff-options via run_cli."""
        a = _make_blank(tmp_path, "do_a.PRS")
        b = _make_blank(tmp_path, "do_b.PRS")
        rc = run_cli(["diff-options", a, b])
        assert rc == 0

    def test_report_via_cli(self, tmp_path, capsys):
        """report via run_cli."""
        prs_file = _make_blank(tmp_path)
        out = str(tmp_path / "rpt.html")
        rc = run_cli(["report", prs_file, "-o", out])
        assert rc == 0

    def test_card_via_cli(self, tmp_path, capsys):
        """card via run_cli."""
        prs_file = _make_blank(tmp_path)
        out = str(tmp_path / "card.html")
        rc = run_cli(["card", prs_file, "-o", out])
        assert rc == 0

    def test_backup_via_cli(self, tmp_path, capsys):
        """backup via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["backup", prs_file])
        assert rc == 0

    def test_repair_via_cli(self, tmp_path, capsys):
        """repair via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["repair", prs_file])
        assert rc == 0

    def test_inject_conv_via_cli(self, tmp_path, capsys):
        """inject conv via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["inject", prs_file, "conv", "--template", "murs"])
        assert rc == 0

    def test_inject_p25_via_cli(self, tmp_path, capsys):
        """inject p25 via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli([
            "inject", prs_file, "p25",
            "--name", "CLIPRS", "--sysid", "42",
        ])
        assert rc == 0

    def test_remove_via_cli(self, tmp_path, capsys):
        """remove via run_cli."""
        prs_file = _make_populated(tmp_path)
        rc = run_cli(["remove", prs_file, "conv-set", "MURS"])
        assert rc == 0

    def test_edit_via_cli(self, tmp_path, capsys):
        """edit via run_cli."""
        prs_file = _make_blank(tmp_path)
        rc = run_cli(["edit", prs_file, "--name", "EDITED.PRS"])
        assert rc == 0

    def test_rename_via_cli(self, tmp_path, capsys):
        """rename via run_cli."""
        prs_file = _make_populated(tmp_path)
        rc = run_cli([
            "rename", prs_file,
            "--set", "TEST",
            "--pattern", "^DISP$",
            "--replace", "DSP",
        ])
        assert rc == 0

    def test_sort_via_cli(self, tmp_path, capsys):
        """sort via run_cli."""
        prs_file = _make_populated(tmp_path)
        rc = run_cli([
            "sort", prs_file,
            "--set", "MURS",
            "--key", "name",
        ])
        assert rc == 0

    def test_build_via_cli(self, tmp_path, capsys):
        """build via run_cli."""
        if not EXAMPLE_INI.exists():
            pytest.skip("Example INI not available")
        out = str(tmp_path / "built.PRS")
        rc = run_cli(["build", str(EXAMPLE_INI), "-o", out])
        assert rc == 0

    def test_export_config_via_cli(self, tmp_path, capsys):
        """export-config via run_cli."""
        prs_file = _make_blank(tmp_path)
        out = str(tmp_path / "cfg.ini")
        rc = run_cli(["export-config", prs_file, "-o", out])
        assert rc == 0

    def test_diff_report_via_cli(self, tmp_path, capsys):
        """diff-report via run_cli."""
        a = _make_blank(tmp_path, "dr_a.PRS")
        b = _make_blank(tmp_path, "dr_b.PRS")
        rc = run_cli(["diff-report", a, b])
        assert rc == 0

    def test_multi_file_info(self, tmp_path, capsys):
        """info with multiple files."""
        a = _make_blank(tmp_path, "m1.PRS")
        b = _make_blank(tmp_path, "m2.PRS")
        rc = run_cli(["info", a, b])
        assert rc == 0

    def test_multi_file_validate(self, tmp_path, capsys):
        """validate with multiple files."""
        a = _make_blank(tmp_path, "v1.PRS")
        b = _make_blank(tmp_path, "v2.PRS")
        rc = run_cli(["validate", a, b])
        assert rc in (0, 1)

    def test_multi_file_capacity(self, tmp_path, capsys):
        """capacity with multiple files."""
        a = _make_blank(tmp_path, "c1.PRS")
        b = _make_blank(tmp_path, "c2.PRS")
        rc = run_cli(["capacity", a, b])
        assert rc == 0
