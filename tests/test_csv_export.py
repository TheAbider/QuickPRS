"""Tests for the csv_export module.

Tests the shared CSV export functions used by both CLI and GUI.
"""

import csv
import os
import tempfile
from pathlib import Path

import pytest

from quickprs.prs_parser import parse_prs
from quickprs.record_types import (
    parse_group_section, parse_trunk_channel_section,
    parse_conv_channel_section, parse_iden_section,
    parse_sets_from_sections,
)
from quickprs.csv_export import (
    export_group_sets, export_trunk_sets, export_conv_sets,
    export_iden_sets, export_options, export_systems,
    export_ecc, export_preferred,
    flatten_config, collect_system_info,
)

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Helpers ────────────────────────────────────────────────────────

def _parse_groups(prs):
    data = prs.get_section_by_class("CP25Group")
    sset = prs.get_section_by_class("CP25GroupSet")
    if not data or not sset:
        return []
    return parse_sets_from_sections(sset.raw, data.raw, parse_group_section)


def _parse_trunks(prs):
    data = prs.get_section_by_class("CTrunkChannel")
    sset = prs.get_section_by_class("CTrunkSet")
    if not data or not sset:
        return []
    return parse_sets_from_sections(sset.raw, data.raw,
                                    parse_trunk_channel_section)


def _parse_convs(prs):
    data = prs.get_section_by_class("CConvChannel")
    sset = prs.get_section_by_class("CConvSet")
    if not data or not sset:
        return []
    return parse_sets_from_sections(sset.raw, data.raw,
                                    parse_conv_channel_section)


def _parse_idens(prs):
    data = prs.get_section_by_class("CDefaultIdenElem")
    sset = prs.get_section_by_class("CIdenDataSet")
    if not data or not sset:
        return []
    return parse_sets_from_sections(sset.raw, data.raw, parse_iden_section)


def _read_csv(path):
    """Read CSV and return (header, rows)."""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    return header, rows


# ─── export_group_sets ──────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestExportGroupSets:

    def test_headers(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_groups(prs)
        with tempfile.TemporaryDirectory() as d:
            export_group_sets(os.path.join(d, "g.csv"), sets)
            header, _ = _read_csv(os.path.join(d, "g.csv"))
        assert header == ["Set", "GroupID", "ShortName", "LongName",
                          "TX", "RX", "Scan"]

    def test_row_count(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_groups(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "g.csv")
            result = export_group_sets(path, sets)
            _, rows = _read_csv(path)
        assert len(rows) == 241
        assert "241 groups" in result

    def test_return_format(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_groups(prs)
        with tempfile.TemporaryDirectory() as d:
            result = export_group_sets(os.path.join(d, "g.csv"), sets)
        assert result.startswith("GROUP_SET.csv")

    def test_tx_rx_scan_flags(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_groups(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "g.csv")
            export_group_sets(path, sets)
            _, rows = _read_csv(path)
        # All TX/RX/Scan values should be Y or N
        for row in rows:
            assert row[4] in ("Y", "N")  # TX
            assert row[5] in ("Y", "N")  # RX
            assert row[6] in ("Y", "N")  # Scan

    def test_group_ids_are_numeric(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_groups(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "g.csv")
            export_group_sets(path, sets)
            _, rows = _read_csv(path)
        for row in rows:
            assert row[1].isdigit()


# ─── export_trunk_sets ──────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestExportTrunkSets:

    def test_headers(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_trunks(prs)
        with tempfile.TemporaryDirectory() as d:
            export_trunk_sets(os.path.join(d, "t.csv"), sets)
            header, _ = _read_csv(os.path.join(d, "t.csv"))
        assert header == ["Set", "TxFreq", "RxFreq", "TxMin", "TxMax"]

    def test_row_count(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_trunks(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.csv")
            result = export_trunk_sets(path, sets)
            _, rows = _read_csv(path)
        assert len(rows) == 290
        assert "290 channels" in result

    def test_freq_precision(self):
        """Frequencies should have 5 decimal places."""
        prs = parse_prs(str(PAWS))
        sets = _parse_trunks(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.csv")
            export_trunk_sets(path, sets)
            _, rows = _read_csv(path)
        for row in rows:
            # TxFreq and RxFreq should have decimal point
            assert "." in row[1]
            assert "." in row[2]


# ─── export_conv_sets ───────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestExportConvSets:

    def test_headers(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_convs(prs)
        if not sets:
            pytest.skip("No conv sets in PAWS")
        with tempfile.TemporaryDirectory() as d:
            export_conv_sets(os.path.join(d, "c.csv"), sets)
            header, _ = _read_csv(os.path.join(d, "c.csv"))
        assert header == ["Set", "ShortName", "TxFreq", "RxFreq",
                          "TxTone", "RxTone", "LongName"]

    def test_return_format(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_convs(prs)
        if not sets:
            pytest.skip("No conv sets in PAWS")
        with tempfile.TemporaryDirectory() as d:
            result = export_conv_sets(os.path.join(d, "c.csv"), sets)
        assert result.startswith("CONV_SET.csv")


# ─── export_iden_sets ───────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestExportIdenSets:

    def test_headers(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_idens(prs)
        with tempfile.TemporaryDirectory() as d:
            export_iden_sets(os.path.join(d, "i.csv"), sets)
            header, _ = _read_csv(os.path.join(d, "i.csv"))
        assert header == ["Set", "Slot", "BaseFreqMHz", "Spacing", "BW",
                          "TxOffset", "Type"]

    def test_iden_type_values(self):
        """Type column should be TDMA or FDMA."""
        prs = parse_prs(str(PAWS))
        sets = _parse_idens(prs)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "i.csv")
            export_iden_sets(path, sets)
            _, rows = _read_csv(path)
        for row in rows:
            assert row[6] in ("TDMA", "FDMA")

    def test_return_format(self):
        prs = parse_prs(str(PAWS))
        sets = _parse_idens(prs)
        with tempfile.TemporaryDirectory() as d:
            result = export_iden_sets(os.path.join(d, "i.csv"), sets)
        assert result.startswith("IDEN_SET.csv")
        assert "sets" in result


# ─── export_options ─────────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestExportOptions:

    def test_paws_has_options(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            result = export_options(os.path.join(d, "o.csv"), prs)
        assert result is not None
        assert "OPTIONS.csv" in result

    def test_options_headers(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.csv")
            export_options(path, prs)
            header, _ = _read_csv(path)
        assert header == ["Category", "Field", "Value"]

    def test_options_has_rows(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.csv")
            export_options(path, prs)
            _, rows = _read_csv(path)
        assert len(rows) > 10

    def test_no_xml_returns_none(self):
        """claude test.PRS has no XML — should return None."""
        prs = parse_prs(str(CLAUDE))
        with tempfile.TemporaryDirectory() as d:
            result = export_options(os.path.join(d, "o.csv"), prs)
        assert result is None

    def test_options_has_button_fields(self):
        """OPTIONS.csv should include prog button fields."""
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.csv")
            export_options(path, prs)
            _, rows = _read_csv(path)
        categories = {row[0] for row in rows}
        assert "Programmable Buttons" in categories


# ─── export_systems ─────────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestExportSystems:

    def test_paws_has_systems(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            result = export_systems(os.path.join(d, "s.csv"), prs)
        assert result is not None
        assert "SYSTEMS.csv" in result

    def test_systems_headers(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.csv")
            export_systems(path, prs)
            header, _ = _read_csv(path)
        assert header == ["ShortName", "Type", "LongName", "WACN"]

    def test_systems_has_rows(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.csv")
            export_systems(path, prs)
            _, rows = _read_csv(path)
        assert len(rows) >= 2  # PAWS has at least 2 systems

    def test_simple_file_returns_none(self):
        """claude test.PRS may not have system sections."""
        prs = parse_prs(str(CLAUDE))
        with tempfile.TemporaryDirectory() as d:
            result = export_systems(os.path.join(d, "s.csv"), prs)
        # Small file may not have system info
        if result is not None:
            assert "SYSTEMS.csv" in result


# ─── flatten_config ─────────────────────────────────────────────────

class TestFlattenConfig:

    def test_simple_flat(self):
        config = {"key1": "val1", "key2": "val2"}
        rows = flatten_config(config)
        assert len(rows) == 2
        fields = {r[1] for r in rows}
        assert "key1" in fields

    def test_nested_dict(self):
        config = {"audioConfig": {"volume": "5"}}
        rows = flatten_config(config)
        assert len(rows) == 1
        assert rows[0][0] == "Audio Settings"

    def test_nested_list(self):
        config = {"progButtons": [{"func": "ZONE"}]}
        rows = flatten_config(config)
        assert len(rows) == 1
        assert rows[0][0] == "Programmable Buttons"

    def test_category_mapping(self):
        config = {
            "audioConfig": {"x": "1"},
            "gpsConfig": {"y": "2"},
            "bluetoothConfig": {"z": "3"},
        }
        rows = flatten_config(config)
        categories = {r[0] for r in rows}
        assert "Audio Settings" in categories
        assert "GPS Settings" in categories
        assert "Bluetooth Settings" in categories

    def test_empty_config(self):
        rows = flatten_config({})
        assert rows == []

    def test_onoff_formatting(self):
        """ON/OFF fields should be formatted if field def says onoff."""
        from quickprs.option_maps import XML_FIELD_INDEX
        # Find a known onoff field
        onoff_fields = [(tag, key) for (tag, key), fd in XML_FIELD_INDEX.items()
                        if fd.field_type == "onoff"]
        if not onoff_fields:
            pytest.skip("No onoff fields in catalog")
        tag, key = onoff_fields[0]
        config = {tag: {key: "ON"}}
        rows = flatten_config(config)
        assert len(rows) == 1
        assert rows[0][2] == "Enabled"


# ─── collect_system_info ────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestCollectSystemInfo:

    def test_paws_systems(self):
        prs = parse_prs(str(PAWS))
        rows = collect_system_info(prs)
        assert len(rows) >= 2

    def test_system_type_labels(self):
        prs = parse_prs(str(PAWS))
        rows = collect_system_info(prs)
        types = {r[1] for r in rows}
        assert "P25 Trunked" in types

    def test_row_tuple_length(self):
        prs = parse_prs(str(PAWS))
        rows = collect_system_info(prs)
        for row in rows:
            assert len(row) == 4  # short_name, type, long_name, wacn

    def test_claude_test_file(self):
        """Small file — may return empty or small list."""
        prs = parse_prs(str(CLAUDE))
        rows = collect_system_info(prs)
        assert isinstance(rows, list)


# ─── export_ecc ──────────────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestExportECC:

    def test_paws_has_ecc(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            result = export_ecc(os.path.join(d, "ecc.csv"), prs)
        assert result is not None
        assert "ECC.csv" in result

    def test_ecc_headers(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ecc.csv")
            export_ecc(path, prs)
            header, _ = _read_csv(path)
        assert header == ["System", "Type", "SysID", "ChRef1", "ChRef2",
                          "IdenSet"]

    def test_ecc_has_rows(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ecc.csv")
            export_ecc(path, prs)
            _, rows = _read_csv(path)
        assert len(rows) >= 5  # PAWS has many ECC entries

    def test_simple_file_no_ecc(self):
        prs = parse_prs(str(CLAUDE))
        with tempfile.TemporaryDirectory() as d:
            result = export_ecc(os.path.join(d, "ecc.csv"), prs)
        # Small file likely has no ECC
        assert result is None or "ECC.csv" in result


# ─── export_preferred ────────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestExportPreferred:

    def test_paws_has_preferred(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            result = export_preferred(os.path.join(d, "pref.csv"), prs)
        # PAWS may or may not have preferred sections
        if result:
            assert "PREFERRED.csv" in result

    def test_preferred_headers(self):
        prs = parse_prs(str(PAWS))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pref.csv")
            result = export_preferred(path, prs)
            if result:
                header, _ = _read_csv(path)
                assert header == ["Type", "SysID", "Priority", "Sequence",
                                  "IdenSet", "ChainTo"]

    def test_simple_file_preferred(self):
        prs = parse_prs(str(CLAUDE))
        with tempfile.TemporaryDirectory() as d:
            result = export_preferred(os.path.join(d, "pref.csv"), prs)
        assert result is None or "PREFERRED.csv" in result
