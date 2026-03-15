"""Tests for JSON export and import functionality."""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.builder import create_blank_prs
from quickprs.json_io import (
    prs_to_dict, dict_to_json, export_json,
    json_to_dict, dict_to_prs, import_json,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWSOVERMAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE_TEST = TESTDATA / "claude test.PRS"


# ─── Export Tests ────────────────────────────────────────────────────


class TestExportPawsovermaws:
    """Test JSON export of PAWSOVERMAWS.PRS."""

    @pytest.fixture
    def prs(self):
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")
        return parse_prs(PAWSOVERMAWS)

    @pytest.fixture
    def exported(self, prs):
        return prs_to_dict(prs)

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_has_personality(self, exported):
        assert "personality" in exported
        p = exported["personality"]
        assert p["filename"] == "PAWSOVERMAWS.PRS"
        assert p["saved_by"] == "Abider"
        assert p["platform"] == "PC"

    def test_has_systems(self, exported):
        assert "systems" in exported
        systems = exported["systems"]
        assert len(systems) >= 2
        # First P25 system should be PSERN
        p25_systems = [s for s in systems if s["type"] == "P25Trunked"]
        assert len(p25_systems) >= 1
        psern = p25_systems[0]
        assert psern["name"] == "PSERN"
        assert psern["long_name"] == "PSERN SEATTLE"
        assert psern["trunk_set"] == "PSERN"
        assert psern["group_set"] == "PSERN PD"

    def test_p25_system_has_wan_name(self, exported):
        p25 = [s for s in exported["systems"] if s["type"] == "P25Trunked"]
        psern = p25[0]
        assert psern.get("wan_name") == "PSERN"

    def test_has_trunk_sets(self, exported):
        assert "trunk_sets" in exported
        trunk_sets = exported["trunk_sets"]
        assert len(trunk_sets) >= 1
        psern = trunk_sets[0]
        assert psern["name"] == "PSERN"
        assert len(psern["channels"]) >= 10
        # Check frequency values are reasonable
        for ch in psern["channels"]:
            assert 100.0 < ch["tx_freq"] < 1000.0
            assert 100.0 < ch["rx_freq"] < 1000.0

    def test_has_group_sets(self, exported):
        assert "group_sets" in exported
        group_sets = exported["group_sets"]
        assert len(group_sets) >= 1
        # Each group set should have groups with IDs
        for gs in group_sets:
            assert "name" in gs
            assert "groups" in gs
            for g in gs["groups"]:
                assert "id" in g
                assert "short_name" in g

    def test_group_set_has_scan_and_tx(self, exported):
        gs = exported["group_sets"][0]
        for g in gs["groups"]:
            assert "scan" in g
            assert "tx" in g
            assert isinstance(g["scan"], bool)
            assert isinstance(g["tx"], bool)

    def test_has_conv_sets(self, exported):
        assert "conv_sets" in exported
        conv_sets = exported["conv_sets"]
        assert len(conv_sets) >= 1
        for cs in conv_sets:
            assert "name" in cs
            assert "channels" in cs
            for ch in cs["channels"]:
                assert "short_name" in ch
                assert "tx_freq" in ch

    def test_has_iden_sets(self, exported):
        assert "iden_sets" in exported
        iden_sets = exported["iden_sets"]
        assert len(iden_sets) >= 1
        for iset in iden_sets:
            assert "name" in iset
            assert "elements" in iset
            for elem in iset["elements"]:
                assert "base_freq_hz" in elem
                assert "iden_type" in elem
                assert elem["iden_type"] in ("FDMA", "TDMA")

    def test_has_wan_entries(self, exported):
        assert "wan_entries" in exported
        entries = exported["wan_entries"]
        assert len(entries) >= 1
        for e in entries:
            assert "wan_name" in e
            assert "wacn" in e
            assert "system_id" in e

    def test_has_platform_config(self, exported):
        assert "options" in exported
        assert "platform_config" in exported["options"]

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_total_trunk_freqs(self, exported):
        total = sum(len(ts["channels"]) for ts in exported["trunk_sets"])
        assert total >= 100  # PAWSOVERMAWS has ~290 trunk freqs

    @pytest.mark.skipif(not PAWSOVERMAWS.exists(), reason="Test PRS data not available")
    def test_total_talkgroups(self, exported):
        total = sum(len(gs["groups"]) for gs in exported["group_sets"])
        assert total >= 100  # PAWSOVERMAWS has ~241 talkgroups


class TestExportClaudeTest:
    """Test JSON export of claude test.PRS."""

    @pytest.fixture
    def prs(self):
        if not CLAUDE_TEST.exists():
            pytest.skip("claude test.PRS not found")
        return parse_prs(CLAUDE_TEST)

    @pytest.fixture
    def exported(self, prs):
        return prs_to_dict(prs)

    def test_has_personality(self, exported):
        assert "personality" in exported

    def test_has_systems(self, exported):
        assert "systems" in exported
        assert len(exported["systems"]) >= 1

    def test_has_p25_conv_sets(self, exported):
        # claude test has P25 conv sets
        if "p25_conv_sets" in exported:
            for cs in exported["p25_conv_sets"]:
                assert "name" in cs
                assert "channels" in cs

    def test_export_to_file(self, prs, tmp_path):
        out = tmp_path / "claude_test.json"
        export_json(prs, out)
        assert out.exists()
        data = json.loads(out.read_text(encoding='utf-8'))
        assert "personality" in data


class TestExportBlankPRS:
    """Test JSON export of a freshly created blank PRS."""

    @pytest.fixture
    def prs(self):
        return create_blank_prs("blank.PRS", "tester")

    @pytest.fixture
    def exported(self, prs):
        return prs_to_dict(prs)

    def test_personality_metadata(self, exported):
        assert exported["personality"]["filename"] == "blank.PRS"
        assert exported["personality"]["saved_by"] == "tester"

    def test_has_conv_set(self, exported):
        assert "conv_sets" in exported
        assert len(exported["conv_sets"]) == 1
        cs = exported["conv_sets"][0]
        assert cs["name"] == "Conv 1"
        assert len(cs["channels"]) >= 1

    def test_has_system(self, exported):
        assert "systems" in exported
        assert len(exported["systems"]) >= 1


# ─── JSON serialization ─────────────────────────────────────────────


class TestJsonSerialization:
    """Test JSON string formatting."""

    def test_pretty_print(self):
        d = {"a": 1, "b": [1, 2]}
        text = dict_to_json(d)
        assert "\n" in text
        assert "  " in text
        parsed = json.loads(text)
        assert parsed == d

    def test_compact(self):
        d = {"a": 1, "b": [1, 2]}
        text = dict_to_json(d, compact=True)
        assert "\n" not in text
        assert " " not in text
        parsed = json.loads(text)
        assert parsed == d

    def test_unicode(self):
        d = {"name": "Test \u00e9"}
        text = dict_to_json(d)
        parsed = json.loads(text)
        assert parsed["name"] == "Test \u00e9"


# ─── File I/O ────────────────────────────────────────────────────────


class TestFileExport:
    """Test export_json file writing."""

    def test_export_creates_file(self, tmp_path):
        prs = create_blank_prs("test.PRS")
        out = tmp_path / "test.json"
        result = export_json(prs, out)
        assert Path(result).exists()
        data = json.loads(Path(result).read_text(encoding='utf-8'))
        assert "personality" in data

    def test_export_compact(self, tmp_path):
        prs = create_blank_prs("test.PRS")
        out = tmp_path / "test.json"
        export_json(prs, out, compact=True)
        text = out.read_text(encoding='utf-8')
        assert "\n" not in text

    def test_export_pawsovermaws(self, tmp_path):
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")
        prs = parse_prs(PAWSOVERMAWS)
        out = tmp_path / "paws.json"
        export_json(prs, out)
        data = json.loads(out.read_text(encoding='utf-8'))
        assert len(data["trunk_sets"]) >= 1
        assert len(data["group_sets"]) >= 1


# ─── Import Tests ───────────────────────────────────────────────────


class TestImportBlankRoundtrip:
    """Test round-trip: blank PRS -> JSON -> PRS -> JSON."""

    def test_blank_roundtrip_personality(self, tmp_path):
        # Create blank, export to JSON
        prs1 = create_blank_prs("roundtrip.PRS", "tester")
        d1 = prs_to_dict(prs1)

        # Import from dict
        prs2 = dict_to_prs(d1)
        d2 = prs_to_dict(prs2)

        # Personality should match
        assert d2["personality"]["filename"] == "roundtrip.PRS"
        assert d2["personality"]["saved_by"] == "tester"

    def test_blank_roundtrip_conv_sets(self, tmp_path):
        prs1 = create_blank_prs("roundtrip.PRS")
        d1 = prs_to_dict(prs1)

        prs2 = dict_to_prs(d1)
        d2 = prs_to_dict(prs2)

        # Conv sets should survive roundtrip
        assert len(d2.get("conv_sets", [])) >= 1


class TestImportWithData:
    """Test importing JSON with actual system data."""

    def test_import_p25_system(self, tmp_path):
        d = {
            "personality": {
                "filename": "test_import.PRS",
                "saved_by": "test",
            },
            "systems": [
                {
                    "type": "P25Trunked",
                    "name": "TESTSYS",
                    "long_name": "TEST SYSTEM",
                    "trunk_set": "TESTSYS",
                    "group_set": "TESTSYS",
                    "wan_name": "TESTSYS",
                }
            ],
            "trunk_sets": [
                {
                    "name": "TESTSYS",
                    "channels": [
                        {"tx_freq": 851.0125, "rx_freq": 806.0125},
                        {"tx_freq": 851.5125, "rx_freq": 806.5125},
                    ],
                    "tx_min": 767.0, "tx_max": 858.0,
                    "rx_min": 767.0, "rx_max": 858.0,
                }
            ],
            "group_sets": [
                {
                    "name": "TESTSYS",
                    "groups": [
                        {"id": 100, "short_name": "DISP N",
                         "long_name": "Dispatch North",
                         "tx": False, "scan": True},
                        {"id": 200, "short_name": "DISP S",
                         "long_name": "Dispatch South",
                         "tx": True, "scan": True},
                    ],
                }
            ],
            "wan_entries": [
                {"wan_name": "TESTSYS", "wacn": 12345, "system_id": 892}
            ],
        }

        prs = dict_to_prs(d)
        out = tmp_path / "test_import.PRS"
        out.write_bytes(prs.to_bytes())
        assert out.exists()

        # Re-parse and verify
        prs2 = parse_prs(out)
        d2 = prs_to_dict(prs2)

        # Trunk set should have our channels
        trunk_names = [ts["name"] for ts in d2.get("trunk_sets", [])]
        assert "TESTSYS" in trunk_names

        ts = next(ts for ts in d2["trunk_sets"] if ts["name"] == "TESTSYS")
        assert len(ts["channels"]) == 2
        assert abs(ts["channels"][0]["tx_freq"] - 851.0125) < 0.001

        # Group set should have our talkgroups
        group_names = [gs["name"] for gs in d2.get("group_sets", [])]
        assert "TESTSYS" in group_names

        gs = next(gs for gs in d2["group_sets"] if gs["name"] == "TESTSYS")
        assert len(gs["groups"]) == 2
        assert gs["groups"][0]["id"] == 100
        assert gs["groups"][0]["short_name"] == "DISP N"

    def test_import_conv_system(self, tmp_path):
        d = {
            "personality": {"filename": "conv.PRS"},
            "systems": [
                {
                    "type": "Conventional",
                    "name": "MURS",
                    "long_name": "MURS CHANNELS",
                    "conv_set": "MURS",
                }
            ],
            "conv_sets": [
                {
                    "name": "MURS",
                    "channels": [
                        {"short_name": "MURS 1",
                         "tx_freq": 151.820, "rx_freq": 151.820,
                         "long_name": "MURS Channel 1"},
                        {"short_name": "MURS 2",
                         "tx_freq": 151.880, "rx_freq": 151.880,
                         "long_name": "MURS Channel 2"},
                    ],
                }
            ],
        }

        prs = dict_to_prs(d)
        d2 = prs_to_dict(prs)

        conv_names = [cs["name"] for cs in d2.get("conv_sets", [])]
        assert "MURS" in conv_names

        cs = next(cs for cs in d2["conv_sets"] if cs["name"] == "MURS")
        assert len(cs["channels"]) == 2
        assert cs["channels"][0]["short_name"] == "MURS 1"

    def test_import_iden_set(self, tmp_path):
        d = {
            "personality": {"filename": "iden.PRS"},
            "iden_sets": [
                {
                    "name": "BEE00",
                    "elements": [
                        {
                            "chan_spacing_hz": 12500,
                            "bandwidth_hz": 6250,
                            "base_freq_hz": 851006250,
                            "tx_offset_mhz": -45.0,
                            "iden_type": "FDMA",
                        }
                    ],
                }
            ],
        }

        prs = dict_to_prs(d)
        d2 = prs_to_dict(prs)

        assert "iden_sets" in d2
        iden_names = [i["name"] for i in d2["iden_sets"]]
        assert "BEE00" in iden_names

        iset = next(i for i in d2["iden_sets"] if i["name"] == "BEE00")
        assert len(iset["elements"]) >= 1
        assert iset["elements"][0]["base_freq_hz"] == 851006250

    def test_import_preserves_group_tx_scan(self, tmp_path):
        """Verify per-group tx/scan flags survive import."""
        d = {
            "personality": {"filename": "flags.PRS"},
            "group_sets": [
                {
                    "name": "FLAGS",
                    "groups": [
                        {"id": 1, "short_name": "TX ON",
                         "long_name": "TX Enabled",
                         "tx": True, "scan": True},
                        {"id": 2, "short_name": "TX OFF",
                         "long_name": "TX Disabled",
                         "tx": False, "scan": False},
                    ],
                }
            ],
        }

        prs = dict_to_prs(d)
        d2 = prs_to_dict(prs)

        gs = next(gs for gs in d2["group_sets"] if gs["name"] == "FLAGS")
        g1 = next(g for g in gs["groups"] if g["id"] == 1)
        g2 = next(g for g in gs["groups"] if g["id"] == 2)
        assert g1["tx"] is True
        assert g1["scan"] is True
        assert g2["tx"] is False
        assert g2["scan"] is False


class TestImportJsonFile:
    """Test import_json file reading."""

    def test_import_from_file(self, tmp_path):
        # Write JSON file
        d = {
            "personality": {"filename": "file_test.PRS", "saved_by": "test"},
            "conv_sets": [
                {
                    "name": "TEST",
                    "channels": [
                        {"short_name": "CH1", "tx_freq": 146.52,
                         "rx_freq": 146.52, "long_name": "Channel 1"},
                    ],
                }
            ],
        }
        json_path = tmp_path / "input.json"
        json_path.write_text(json.dumps(d), encoding='utf-8')

        prs_path = tmp_path / "output.PRS"
        prs, result_path = import_json(json_path, prs_path)

        assert Path(result_path).exists()
        assert len(prs.sections) > 0

        # Re-parse
        prs2 = parse_prs(prs_path)
        d2 = prs_to_dict(prs2)
        assert d2["personality"]["filename"] == "file_test.PRS"

    def test_import_default_output_path(self, tmp_path):
        d = {"personality": {"filename": "auto.PRS"}}
        json_path = tmp_path / "auto.json"
        json_path.write_text(json.dumps(d), encoding='utf-8')

        prs, result_path = import_json(json_path)
        expected = tmp_path / "auto.PRS"
        assert Path(result_path) == expected
        assert expected.exists()


# ─── Round-trip Tests ────────────────────────────────────────────────


class TestRoundtrip:
    """Test export -> import -> export produces consistent JSON."""

    def test_blank_prs_roundtrip_json(self, tmp_path):
        """Export blank PRS, import, re-export. Compare JSON structure."""
        prs1 = create_blank_prs("roundtrip.PRS", "rt_user")

        # Export to JSON
        json1 = tmp_path / "step1.json"
        export_json(prs1, json1)
        d1 = json.loads(json1.read_text(encoding='utf-8'))

        # Import back to PRS
        prs2, prs_path = import_json(json1, tmp_path / "step2.PRS")

        # Export again
        json2 = tmp_path / "step2.json"
        export_json(prs2, json2)
        d2 = json.loads(json2.read_text(encoding='utf-8'))

        # Key personality fields should match
        assert d2["personality"]["filename"] == d1["personality"]["filename"]
        assert d2["personality"]["saved_by"] == d1["personality"]["saved_by"]

    def test_roundtrip_with_systems(self, tmp_path):
        """Build JSON with systems, import, re-export, verify data."""
        d_orig = {
            "personality": {"filename": "rt.PRS", "saved_by": "test"},
            "trunk_sets": [
                {
                    "name": "SYS1",
                    "channels": [
                        {"tx_freq": 851.0125, "rx_freq": 806.0125},
                        {"tx_freq": 852.0125, "rx_freq": 807.0125},
                    ],
                    "tx_min": 136.0, "tx_max": 870.0,
                    "rx_min": 136.0, "rx_max": 870.0,
                }
            ],
            "group_sets": [
                {
                    "name": "SYS1",
                    "groups": [
                        {"id": 1, "short_name": "TG1",
                         "long_name": "Talkgroup 1",
                         "tx": False, "scan": True},
                    ],
                }
            ],
            "iden_sets": [
                {
                    "name": "BEE00",
                    "elements": [
                        {
                            "chan_spacing_hz": 12500,
                            "bandwidth_hz": 6250,
                            "base_freq_hz": 851006250,
                            "tx_offset_mhz": -45.0,
                            "iden_type": "FDMA",
                        },
                    ],
                }
            ],
        }

        # Write JSON
        json1 = tmp_path / "orig.json"
        json1.write_text(json.dumps(d_orig, indent=2), encoding='utf-8')

        # Import to PRS
        prs, prs_path = import_json(json1, tmp_path / "imported.PRS")

        # Re-export to JSON
        d2 = prs_to_dict(prs)

        # Verify trunk set survived
        ts_names = [ts["name"] for ts in d2.get("trunk_sets", [])]
        assert "SYS1" in ts_names
        ts = next(t for t in d2["trunk_sets"] if t["name"] == "SYS1")
        assert len(ts["channels"]) == 2
        assert abs(ts["channels"][0]["tx_freq"] - 851.0125) < 0.001

        # Verify group set survived
        gs_names = [gs["name"] for gs in d2.get("group_sets", [])]
        assert "SYS1" in gs_names
        gs = next(g for g in d2["group_sets"] if g["name"] == "SYS1")
        assert len(gs["groups"]) == 1
        assert gs["groups"][0]["id"] == 1

        # Verify IDEN set survived
        iden_names = [i["name"] for i in d2.get("iden_sets", [])]
        assert "BEE00" in iden_names

    def test_pawsovermaws_roundtrip_counts(self, tmp_path):
        """Export PAWSOVERMAWS, import, verify data counts are preserved."""
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")

        prs1 = parse_prs(PAWSOVERMAWS)
        d1 = prs_to_dict(prs1)

        # Count original data
        orig_trunk_freqs = sum(
            len(ts["channels"]) for ts in d1.get("trunk_sets", []))
        orig_talkgroups = sum(
            len(gs["groups"]) for gs in d1.get("group_sets", []))
        orig_iden_sets = len(d1.get("iden_sets", []))

        # Import back
        prs2 = dict_to_prs(d1)
        d2 = prs_to_dict(prs2)

        # Trunk freqs should match
        new_trunk_freqs = sum(
            len(ts["channels"]) for ts in d2.get("trunk_sets", []))
        assert new_trunk_freqs == orig_trunk_freqs

        # Talkgroups should match
        new_talkgroups = sum(
            len(gs["groups"]) for gs in d2.get("group_sets", []))
        assert new_talkgroups == orig_talkgroups

        # IDEN sets should match
        new_iden_sets = len(d2.get("iden_sets", []))
        assert new_iden_sets == orig_iden_sets


# ─── CLI Integration ────────────────────────────────────────────────


class TestCLI:
    """Test CLI subcommands for export-json and import-json."""

    def test_export_json_cli(self, tmp_path):
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")

        from quickprs.cli import run_cli
        out = tmp_path / "cli_export.json"
        result = run_cli(["export-json", str(PAWSOVERMAWS),
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding='utf-8'))
        assert "personality" in data
        assert "trunk_sets" in data

    def test_export_json_compact(self, tmp_path):
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")

        from quickprs.cli import run_cli
        out = tmp_path / "compact.json"
        result = run_cli(["export-json", str(PAWSOVERMAWS),
                          "-o", str(out), "--compact"])
        assert result == 0
        text = out.read_text(encoding='utf-8')
        assert "\n" not in text

    def test_import_json_cli(self, tmp_path):
        # First export
        if not PAWSOVERMAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")

        from quickprs.cli import run_cli
        json_out = tmp_path / "for_import.json"
        run_cli(["export-json", str(PAWSOVERMAWS), "-o", str(json_out)])

        # Then import
        prs_out = tmp_path / "imported.PRS"
        result = run_cli(["import-json", str(json_out),
                          "-o", str(prs_out)])
        assert result == 0
        assert prs_out.exists()

        # Verify the imported PRS is valid
        prs = parse_prs(prs_out)
        assert len(prs.sections) > 0

    def test_export_claude_test(self, tmp_path):
        if not CLAUDE_TEST.exists():
            pytest.skip("claude test.PRS not found")

        from quickprs.cli import run_cli
        out = tmp_path / "claude.json"
        result = run_cli(["export-json", str(CLAUDE_TEST),
                          "-o", str(out)])
        assert result == 0
        data = json.loads(out.read_text(encoding='utf-8'))
        assert "personality" in data

    def test_export_blank_prs(self, tmp_path):
        from quickprs.cli import run_cli

        # Create blank PRS
        blank = tmp_path / "blank.PRS"
        run_cli(["create", str(blank)])

        # Export to JSON
        out = tmp_path / "blank.json"
        result = run_cli(["export-json", str(blank), "-o", str(out)])
        assert result == 0
        data = json.loads(out.read_text(encoding='utf-8'))
        assert data["personality"]["filename"] == "blank.PRS"


# ─── Edge Cases ──────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_dict(self):
        """Import minimal dict with just personality."""
        d = {"personality": {"filename": "minimal.PRS"}}
        prs = dict_to_prs(d)
        assert len(prs.sections) > 0
        d2 = prs_to_dict(prs)
        assert d2["personality"]["filename"] == "minimal.PRS"

    def test_missing_personality(self):
        """Import dict with no personality section."""
        d = {}
        prs = dict_to_prs(d)
        assert len(prs.sections) > 0

    def test_json_valid_output(self):
        """Exported JSON must be valid JSON."""
        prs = create_blank_prs("valid.PRS")
        d = prs_to_dict(prs)
        text = dict_to_json(d)
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    def test_compact_and_pretty_produce_same_data(self):
        """Compact and pretty JSON should parse to same dict."""
        prs = create_blank_prs("fmt.PRS")
        d = prs_to_dict(prs)
        pretty = json.loads(dict_to_json(d, compact=False))
        compact = json.loads(dict_to_json(d, compact=True))
        assert pretty == compact

    def test_nonexistent_json_file(self, tmp_path):
        """Import from nonexistent file should raise."""
        with pytest.raises(FileNotFoundError):
            json_to_dict(tmp_path / "nonexistent.json")

    def test_invalid_json(self, tmp_path):
        """Import invalid JSON should raise."""
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json{{{", encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            json_to_dict(bad)

    def test_group_ids_preserved(self):
        """Group IDs should roundtrip exactly."""
        d = {
            "personality": {"filename": "ids.PRS"},
            "group_sets": [
                {
                    "name": "IDS",
                    "groups": [
                        {"id": 65535, "short_name": "MAX",
                         "long_name": "Max ID", "tx": True, "scan": True},
                        {"id": 1, "short_name": "MIN",
                         "long_name": "Min ID", "tx": False, "scan": False},
                    ],
                }
            ],
        }
        prs = dict_to_prs(d)
        d2 = prs_to_dict(prs)
        gs = next(gs for gs in d2["group_sets"] if gs["name"] == "IDS")
        ids = {g["id"] for g in gs["groups"]}
        assert 65535 in ids
        assert 1 in ids

    def test_frequencies_preserved(self):
        """Frequencies should roundtrip to 6 decimal places."""
        d = {
            "personality": {"filename": "freq.PRS"},
            "trunk_sets": [
                {
                    "name": "FREQ",
                    "channels": [
                        {"tx_freq": 851.0125, "rx_freq": 806.0125},
                        {"tx_freq": 851.512500, "rx_freq": 806.512500},
                    ],
                }
            ],
        }
        prs = dict_to_prs(d)
        d2 = prs_to_dict(prs)
        ts = next(ts for ts in d2["trunk_sets"] if ts["name"] == "FREQ")
        assert abs(ts["channels"][0]["tx_freq"] - 851.0125) < 0.0001
        assert abs(ts["channels"][1]["tx_freq"] - 851.5125) < 0.0001
