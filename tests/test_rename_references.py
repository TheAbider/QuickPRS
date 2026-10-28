"""Renaming a set renames the references to it.

Systems find their trunk, talkgroup, IDEN and channel sets by name, and a
P25 conventional set may name a talkgroup set.  rename_trunk_set,
rename_group_set and rename_conv_set changed only the set, so `edit
--rename-set` left the system naming a set that no longer existed.
"""

import pytest

from quickprs import archive, injector
from quickprs.builder import create_blank_prs
from quickprs.prs_parser import parse_prs_bytes
from quickprs.record_types import (
    P25TrkSystemConfig, ConvSystemConfig, P25ConvSystemConfig,
)
from quickprs.validation import validate_prs, ERROR


def _personality():
    prs = create_blank_prs("refs.PRS")
    injector.add_p25_trunked_system(
        prs,
        P25TrkSystemConfig(system_name="CITY", long_name="CITY P25",
                           trunk_set_name="CITY T", group_set_name="CITY G",
                           wan_name="CITY", iden_set_name="CITY I"),
        trunk_set=injector.make_trunk_set(
            "CITY T", [(806.0125, 851.0125)]),
        group_set=injector.make_group_set("CITY G", [(1, "TG", "TG")]),
        iden_set=injector.make_iden_set(
            "CITY I", [{"base_freq_hz": 851_012_500}]))
    injector.add_conv_system(prs, ConvSystemConfig(
        system_name="LOCAL", long_name="LOCAL", conv_set_name="LOCAL C"),
        conv_set=injector.make_conv_set("LOCAL C", [
            {"short_name": "A", "tx_freq": 151.625}]))
    injector.add_p25_conv_set(prs, injector.make_p25_conv_set(
        "P25 C", [{"short_name": "P", "tx_freq": 154.43}],
        group_set_ref="CITY G"))
    injector.add_p25_conv_system(prs, P25ConvSystemConfig(
        system_name="P25", long_name="P25", conv_set_name="P25 C"))
    return parse_prs_bytes(prs.to_bytes())


def _refs(prs):
    doc = archive.document_from_prs(prs)
    return {injector._system_obj_names(o)[0]: injector._system_obj_refs(o)
            for o in doc.list("systems").items if o is not None}


def _no_dangling(prs):
    back = parse_prs_bytes(prs.to_bytes())
    assert archive.check(back) == []
    errors = [m for s, m in validate_prs(back) if s == ERROR]
    assert not [m for m in errors if "references" in m], errors


@pytest.mark.parametrize("set_type, old, new, system, list_name", [
    ("trunk", "CITY T", "METRO T", "CITY", "trunk sets"),
    ("group", "CITY G", "METRO G", "CITY", "group sets"),
    ("iden", "CITY I", "METRO I", "CITY", "IDEN sets"),
    ("conv", "LOCAL C", "TOWN C", "LOCAL", "conv sets"),
    ("p25conv", "P25 C", "DIG C", "P25", "P25 conv sets"),
])
def test_system_follows_the_rename(set_type, old, new, system, list_name):
    prs = _personality()
    assert injector.rename_set(prs, set_type, old, new) is True
    refs = dict(_refs(prs)[system])
    assert refs[list_name] == new
    _no_dangling(prs)


def test_p25_conv_set_follows_a_talkgroup_set_rename():
    prs = _personality()
    injector.rename_group_set(prs, "CITY G", "METRO G")
    p25 = injector.get_p25_conv_sets(parse_prs_bytes(prs.to_bytes()))
    assert [s.group_set_ref for s in p25] == ["METRO G"]


def test_wrappers_follow_too():
    prs = _personality()
    assert injector.rename_trunk_set(prs, "CITY T", "X1")
    assert injector.rename_group_set(prs, "CITY G", "X2")
    assert injector.rename_conv_set(prs, "LOCAL C", "X3")
    assert injector.rename_iden_set(prs, "CITY I", "X4")
    assert injector.rename_p25_conv_set(prs, "P25 C", "X5")
    refs = _refs(prs)
    assert dict(refs["CITY"]) == {"trunk sets": "X1", "group sets": "X2",
                                  "IDEN sets": "X4"}
    assert dict(refs["LOCAL"]) == {"conv sets": "X3"}
    assert dict(refs["P25"]) == {"P25 conv sets": "X5"}
    _no_dangling(prs)


def test_a_taken_name_is_refused():
    prs = _personality()
    injector.add_conv_set(prs, injector.make_conv_set("TAKEN", [
        {"short_name": "B", "tx_freq": 154.57}]))
    before = prs.to_bytes()
    with pytest.raises(ValueError, match="already exists"):
        injector.rename_set(prs, "conv", "LOCAL C", "TAKEN")
    assert prs.to_bytes() == before


def test_unknown_set_is_false():
    assert injector.rename_set(_personality(), "trunk", "NOPE", "X") is False


def test_systems_using_set():
    prs = _personality()
    assert injector.systems_using_set(prs, "group", "CITY G") == ["CITY"]
    assert injector.systems_using_set(prs, "conv", "LOCAL C") == ["LOCAL"]
    assert injector.systems_using_set(prs, "trunk", "NOPE") == []


def test_cli_renames_iden_and_p25conv(tmp_path):
    from quickprs.cli import run_cli
    path = tmp_path / "refs.PRS"
    path.write_bytes(_personality().to_bytes())
    assert run_cli(["edit", str(path), "--rename-set", "iden", "CITY I",
                    "NEW I"]) == 0
    assert run_cli(["edit", str(path), "--rename-set", "p25conv", "P25 C",
                    "NEW C"]) == 0
    from quickprs.prs_parser import parse_prs
    refs = _refs(parse_prs(path))
    assert dict(refs["CITY"])["IDEN sets"] == "NEW I"
    assert dict(refs["P25"])["P25 conv sets"] == "NEW C"
