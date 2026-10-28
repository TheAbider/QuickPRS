"""GitHub issue #1: conventional sets after padded gaps, and P25
conventional sets in CSV export/import.

Some RPM files hold a few extra bytes between a conventional set's 60-byte
block and the next set (13 and 12 bytes in the reported file).  The
parser used to stop after the first set, so later sets vanished from the
GUI and from CONV_SET.csv.
"""

import csv

import pytest

from quickprs import archive, injector
from quickprs.builder import create_blank_prs
from quickprs.csv_export import export_conv_sets, export_p25_conv_sets
from quickprs.csv_import import import_csv
from quickprs.prs_parser import parse_prs_bytes
from quickprs.record_types import (
    parse_sets_from_sections, parse_conv_channel_section,
)

PAD_A = bytes.fromhex("0c") + b"EXTRA FIELD1"      # 13 bytes, string-like
PAD_B = bytes(12)                                  # 12 zero bytes


def _conv_sets(prs):
    return parse_sets_from_sections(
        prs.get_section_by_class("CConvSet").raw,
        prs.get_section_by_class("CConvChannel").raw,
        parse_conv_channel_section)


def _channels(prefix, n, base):
    return [{"short_name": f"{prefix}{i}", "tx_freq": base + i * 0.0125,
             "long_name": f"{prefix} CHAN {i}"} for i in range(n)]


@pytest.fixture
def padded():
    """A personality with three conventional sets where the first two are
    followed by extra bytes, the way the reported RPM file was."""
    prs = create_blank_prs()
    injector.add_conv_set(prs, injector.make_conv_set(
        "SET_A", _channels("A", 4, 151.0)))
    injector.add_conv_set(prs, injector.make_conv_set(
        "SET_B", _channels("B", 3, 152.0)))
    doc = archive.document_from_prs(prs)
    sets = doc.list("conv sets").items
    sets[0].parts[1] += PAD_A          # after "Conv 1"
    sets[1].parts[1] += PAD_B          # after SET_A
    return parse_prs_bytes(archive.serialize(doc))


def test_all_padded_sets_parse(padded):
    sets = _conv_sets(padded)
    assert [s.name for s in sets] == ["Conv 1", "SET_A", "SET_B"]
    assert [len(s.channels) for s in sets] == [1, 4, 3]
    assert sets[0].padding == PAD_A
    assert sets[1].padding == PAD_B
    assert sets[2].padding == b""


def test_padded_file_is_consistent_and_round_trips(padded):
    data = padded.to_bytes()
    assert archive.check_bytes(data) == []
    doc, rep = archive.read_document(data, lenient=False)
    assert archive.serialize(doc) == data
    assert [pad for _, pad in rep.padding] == [PAD_A, PAD_B]


def test_csv_export_has_every_set(padded, tmp_path):
    out = tmp_path / "CONV_SET.csv"
    export_conv_sets(out, _conv_sets(padded))
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["Set"] for r in rows} == {"Conv 1", "SET_A", "SET_B"}
    assert len(rows) == 8


def test_edits_keep_the_padding(padded):
    injector.add_conv_set(padded, injector.make_conv_set(
        "SET_C", _channels("C", 2, 153.0)))
    injector.rename_conv_set(padded, "SET_A", "SET_AA")
    assert archive.check(padded) == []
    data = padded.to_bytes()
    assert PAD_A in data and data.count(bytes(12)) >= 1
    sets = _conv_sets(padded)
    assert [s.name for s in sets] == ["Conv 1", "SET_AA", "SET_B", "SET_C"]
    assert sets[0].padding == PAD_A and sets[1].padding == PAD_B


# ─── P25 conventional CSV ────────────────────────────────────────────

@pytest.fixture
def p25conv():
    prs = create_blank_prs()
    injector.add_p25_conv_set(prs, injector.make_p25_conv_set("DIG", [
        {"short_name": "DIG 1", "tx_freq": 155.1, "nac_tx": 0x293,
         "long_name": "DIGITAL ONE"},
        {"short_name": "DIG 2", "tx_freq": 155.2, "rx_freq": 155.25,
         "nac_tx": 0x123, "nac_rx": 0xF7E, "tx": False, "scan": False},
    ]))
    assert archive.check(prs) == []
    return prs


def test_p25_conv_csv_round_trip(p25conv, tmp_path):
    out = tmp_path / "P25_CONV_SET.csv"
    export_p25_conv_sets(out, injector.get_p25_conv_sets(p25conv))
    kind, sets = import_csv(out)
    assert kind == "p25conv"
    (pset,) = sets
    assert pset.name == "DIG"
    got = [(c.short_name, round(c.tx_freq, 5), round(c.rx_freq, 5),
            c.nac_tx, c.nac_rx, c.tx, c.rx, c.scan, c.long_name)
           for c in pset.channels]
    assert got == [
        ("DIG 1", 155.1, 155.1, 0x293, 0x293, True, True, True,
         "DIGITAL ONE"),
        ("DIG 2", 155.2, 155.25, 0x123, 0xF7E, False, True, False, "DIG 2"),
    ]


def test_p25_conv_csv_not_taken_for_analog(tmp_path):
    """A P25 conventional CSV also has ShortName/TxFreq/RxFreq, so the NAC
    columns must decide before the analog check does."""
    out = tmp_path / "x.csv"
    out.write_text("Set,ShortName,TxFreq,RxFreq,TxNAC,RxNAC\n"
                   "D,CH1,155.1,155.1,293,293\n")
    assert import_csv(out)[0] == "p25conv"


def test_analog_conv_csv_still_analog(tmp_path):
    out = tmp_path / "x.csv"
    out.write_text("Set,ShortName,TxFreq,RxFreq,TxTone,RxTone,LongName\n"
                   "A,CH1,151.82,151.82,,,MURS 1\n")
    assert import_csv(out)[0] == "conv"


def test_import_p25_conv_into_blank(p25conv, tmp_path):
    """Importing P25 conventional sets creates the first set list."""
    out = tmp_path / "P25_CONV_SET.csv"
    export_p25_conv_sets(out, injector.get_p25_conv_sets(p25conv))
    _, sets = import_csv(out)
    prs = create_blank_prs()
    for s in sets:
        injector.add_p25_conv_set(prs, s)
    assert archive.check(prs) == []
    assert [s.name for s in injector.get_p25_conv_sets(prs)] == ["DIG"]


def test_bad_nac_rejected():
    with pytest.raises(ValueError):
        injector.make_p25_conv_channel("X", 155.0, nac_tx=0x1000)
