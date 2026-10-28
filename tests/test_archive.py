"""Tests for the MFC CArchive layer (quickprs/archive.py).

RPM loads a personality with CArchive, which rejects a class tag that does
not name the class it expects and reads every list by its WORD count.  These
tests check that every file QuickPRS writes keeps both right, and that the
reader follows RPM-saved files exactly.
"""

import struct
from pathlib import Path

import pytest

from quickprs import archive, injector
from quickprs.archive import Obj, ObjList
from quickprs.builder import create_blank_prs
from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.record_types import (
    P25TrkSystemConfig, ConvSystemConfig, P25ConvSystemConfig,
    list_system_configs,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
RPM_FILES = sorted([p for p in (PAWS, CLAUDE) if p.exists()] +
                   list((TESTDATA / "every option").glob("*.PRS")))


def _sets(n_groups=2, name="G"):
    return injector.make_group_set(
        name, [(100 + i, f"TG{i}", f"TALKGROUP {i}") for i in range(n_groups)])


# ─── Reading RPM-saved files ─────────────────────────────────────────

@pytest.mark.skipif(not RPM_FILES, reason="RPM test files not available")
@pytest.mark.parametrize("path", RPM_FILES, ids=lambda p: p.name[:40])
def test_rpm_file_round_trips_through_tree(path):
    """Reading an RPM file into the tree and writing it back regenerates
    every header, tag and count byte for byte."""
    data = path.read_bytes()
    for lenient in (False, True):
        doc, _ = archive.read_document(data, lenient=lenient)
        assert archive.serialize(doc) == data


@pytest.mark.skipif(not RPM_FILES, reason="RPM test files not available")
@pytest.mark.parametrize("path", RPM_FILES, ids=lambda p: p.name[:40])
def test_rpm_file_is_consistent(path):
    assert archive.check_bytes(path.read_bytes()) == []


@pytest.mark.skipif(not PAWS.exists(), reason="PAWSOVERMAWS.PRS not available")
def test_paws_class_indices():
    """The indices RPM used (seen in the file's tags) are the ones the map
    counting gives: one index per class and per object."""
    _, rep = archive.read_document(PAWS.read_bytes())
    idx = rep.class_index
    assert idx["CTrunkSet"] == 104
    assert idx["CTrunkChannel"] == 106
    assert idx["CConvSet"] == 403          # 106 + 290 channels + 6 sets + 1
    assert idx["CConvChannel"] == 405
    assert idx["CP25GroupSet"] == 655
    assert idx["CP25Group"] == 657
    assert idx["CIdenDataSet"] == 905      # 657 + 241 groups + 6 sets + 1
    assert idx["CDefaultIdenElem"] == 907
    assert len(rep.tags) == 859


@pytest.mark.skipif(not PAWS.exists(), reason="PAWSOVERMAWS.PRS not available")
def test_paws_list_counts():
    doc = archive.document_from_prs(parse_prs(PAWS))
    counts = {name: len(doc.list(name).items) for name in (
        "systems", "trunk sets", "conv sets", "options", "group sets",
        "P25 conv sets", "IDEN sets")}
    assert counts == {"systems": 13, "trunk sets": 7, "conv sets": 3,
                      "options": 33, "group sets": 7, "P25 conv sets": 0,
                      "IDEN sets": 3}


def test_serializer_tags_and_counts():
    """First object of a class gets a header, later ones a tag naming the
    class index; lists carry their count."""
    root = Obj("CPersonality", [
        b"\x00" * 0,
        ObjList("things", [Obj("CTrunkSet", [b"A"]),
                           Obj("CTrunkSet", [b"B"]),
                           None]),
    ])
    out = archive.serialize(archive.Document(root))
    hdr = struct.pack("<HHH", 0xFFFF, 133, 12) + b"CPersonality"
    assert out.startswith(hdr)
    rest = out[len(hdr):]
    assert rest[:2] == b"\x03\x00"                      # count 3
    trunk_hdr = struct.pack("<HHH", 0xFFFF, 100, 9) + b"CTrunkSet"
    assert rest[2:2 + len(trunk_hdr)] == trunk_hdr      # new class, index 3
    after = rest[2 + len(trunk_hdr):]
    assert after[:1] == b"A"
    assert after[1:3] == struct.pack("<H", 0x8000 | 3)  # tag for class 3
    assert after[3:4] == b"B"
    assert after[4:6] == b"\x00\x00"                    # NULL object


# ─── Every edit keeps the archive consistent ─────────────────────────

def _check_clean(prs):
    assert archive.check(prs) == []
    # and the strict reader (stored counts only) follows it too
    archive.read_document(prs.to_bytes(), lenient=False)


@pytest.fixture
def p25_blank():
    """A blank personality with one P25 system and its three sets."""
    prs = create_blank_prs()
    config = P25TrkSystemConfig(
        system_name="SYS", long_name="SYSTEM", trunk_set_name="SYS",
        group_set_name="SYS", wan_name="SYS", system_id=892, wacn=781824,
        iden_set_name="SYS")
    injector.add_p25_trunked_system(
        prs, config,
        trunk_set=injector.make_trunk_set(
            "SYS", [(851.0125, 806.0125), (851.5125, 806.5125)]),
        group_set=_sets(2, "SYS"),
        iden_set=injector.make_iden_set("SYS", [
            {"base_freq_hz": 851012500, "chan_spacing_hz": 12500,
             "bandwidth_hz": 12500, "tx_offset_mhz": -45.0,
             "iden_type": 0}]))
    _check_clean(prs)
    return prs


def test_blank_is_consistent():
    _check_clean(create_blank_prs())


def test_add_talkgroups_keeps_tags(p25_blank):
    injector.add_talkgroups(p25_blank, "SYS", _sets(5, "X").groups)
    _check_clean(p25_blank)


def test_add_and_remove_sets(p25_blank):
    injector.add_group_set(p25_blank, _sets(4, "MORE"))
    injector.add_trunk_set(p25_blank, injector.make_trunk_set(
        "MORE", [(852.0125, 807.0125)]))
    injector.add_conv_set(p25_blank, injector.make_conv_set(
        "MURS", [{"short_name": "MURS1", "tx_freq": 151.82}]))
    _check_clean(p25_blank)
    doc = archive.document_from_prs(p25_blank)
    assert len(doc.list("group sets").items) == 2
    assert len(doc.list("trunk sets").items) == 2
    assert len(doc.list("conv sets").items) == 2
    assert injector.remove_group_set(p25_blank, "MORE")
    assert injector.remove_trunk_set(p25_blank, "MORE")
    assert injector.remove_conv_set(p25_blank, "MURS")
    _check_clean(p25_blank)


def test_remove_last_set_leaves_empty_list(p25_blank):
    assert injector.remove_trunk_set(p25_blank, "SYS")
    _check_clean(p25_blank)
    doc = archive.document_from_prs(p25_blank)
    assert doc.list("trunk sets").items == []


def test_add_systems_of_every_type(p25_blank):
    injector.add_p25_trunked_system(p25_blank, P25TrkSystemConfig(
        system_name="TWO", long_name="SECOND", wan_name="TWO"))
    injector.add_conv_system(p25_blank, ConvSystemConfig(
        system_name="CONV2", long_name="CONV TWO", conv_set_name="Conv 1"))
    injector.add_p25_conv_system(p25_blank, P25ConvSystemConfig(
        system_name="P25C", long_name="P25 CONV", conv_set_name="Conv 1"))
    _check_clean(p25_blank)
    found = [(r.class_name, r.short_name)
             for r in list_system_configs(p25_blank)]
    assert found == [("CConvSystem", "Conv 1"), ("CP25TrkSystem", "SYS"),
                     ("CP25TrkSystem", "TWO"), ("CConvSystem", "CONV2"),
                     ("CP25ConvSystem", "P25C")]


def test_remove_system(p25_blank):
    assert injector.remove_system_by_class(p25_blank, "CConvSystem") == 1
    _check_clean(p25_blank)
    assert [r.short_name for r in list_system_configs(p25_blank)] == ["SYS"]


def test_wan_entries_follow_systems(p25_blank):
    injector.add_p25_trunked_system(p25_blank, P25TrkSystemConfig(
        system_name="TWO", wan_name="TWO", wacn=1, system_id=2))
    doc = archive.document_from_prs(p25_blank)
    assert len(doc.option("CP25tWanOpts").lists()[0].items) == 2
    assert injector.remove_wan_entry(p25_blank, "TWO")
    _check_clean(p25_blank)


def test_talkgroup_65535_survives(p25_blank):
    """A talkgroup ID of 65535 puts FF FF in the data; the group list must
    still parse in full (the splitter used to cut it there)."""
    from quickprs.record_types import parse_sets_from_sections, \
        parse_group_section
    injector.add_talkgroups(p25_blank, "SYS", [
        injector.make_p25_group(65535, "ALL", "ALL CALL"),
        injector.make_p25_group(7, "SEVEN", "SEVEN")])
    _check_clean(p25_blank)
    reparsed = parse_prs_bytes(p25_blank.to_bytes())
    sets = parse_sets_from_sections(
        reparsed.get_section_by_class("CP25GroupSet").raw,
        reparsed.get_section_by_class("CP25Group").raw, parse_group_section)
    ids = [g.group_id for g in sets[0].groups]
    assert ids == [100, 101, 65535, 7]


# ─── Repair ──────────────────────────────────────────────────────────

def test_repair_fixes_stale_tags_and_counts(p25_blank):
    data = bytearray(p25_blank.to_bytes())
    _, rep = archive.read_document(bytes(data))
    for t in rep.tags:
        struct.pack_into("<H", data, t.offset, 0x8000 | (t.value + 5))
    groups = next(c for c in rep.counts if c.name == "group sets")
    struct.pack_into("<H", data, groups.offset, 9)
    broken = parse_prs_bytes(bytes(data))
    problems = archive.check(broken)
    assert len(problems) == len(rep.tags) + 1
    assert archive.repair(broken)
    assert broken.to_bytes() == p25_blank.to_bytes()


def test_unreadable_file_raises_walkerror():
    with pytest.raises(archive.WalkError):
        archive.read_document(b"\xff\xff\x00\x00\x02\x00XX")
