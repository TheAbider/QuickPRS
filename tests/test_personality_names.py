"""The personality name and user name are stored twice: in the
CPersonality header and among the document fields after the options.  RPM
writes the same values in both; edit --name, fleet and clone-personality
used to change only the header."""

from pathlib import Path

import pytest

from quickprs import archive
from quickprs.builder import create_blank_prs
from quickprs.cli import run_cli
from quickprs.injector import edit_personality
from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.record_types import parse_personality_section

TESTDATA = Path(__file__).parent / "testdata"


def _names(prs):
    """((header file name, document name), (header saved-by, document
    user name))."""
    p = parse_personality_section(
        prs.get_section_by_class("CPersonality").raw)
    fields = archive.document_from_prs(prs).root.parts[6]
    name, pos = archive.read_cstring(fields, 0)
    user, _ = archive.read_cstring(fields, pos + 2)
    return (p.filename, name), (p.saved_by, user)


def test_rpm_files_hold_the_same_values_twice():
    files = sorted(TESTDATA.rglob("*.PRS"))
    if not files:
        pytest.skip("Test PRS data not available")
    for f in files:
        (h_name, d_name), (h_user, d_user) = _names(parse_prs(f))
        assert h_name == d_name and h_user == d_user, f.name


def test_edit_personality_sets_both():
    prs = parse_prs_bytes(create_blank_prs("OLD.PRS", "old").to_bytes())
    assert edit_personality(prs, filename="NEW.PRS", saved_by="me")
    back = parse_prs_bytes(prs.to_bytes())
    assert _names(back) == (("NEW.PRS", "NEW.PRS"), ("me", "me"))
    assert archive.check(back) == []


def test_longest_names_fit_and_longer_ones_are_refused():
    """The header's name/value block has a one-byte length."""
    prs = parse_prs_bytes(create_blank_prs("OLD.PRS").to_bytes())
    long_name = "x" * 200 + ".PRS"
    edit_personality(prs, filename=long_name)
    assert _names(parse_prs_bytes(prs.to_bytes()))[0] == (long_name,
                                                          long_name)
    before = prs.to_bytes()
    with pytest.raises(ValueError, match="too long"):
        edit_personality(prs, filename="x" * 300 + ".PRS")
    assert prs.to_bytes() == before


def test_cli_edit_name(tmp_path):
    path = tmp_path / "radio.PRS"
    path.write_bytes(create_blank_prs("radio.PRS").to_bytes())
    assert run_cli(["edit", str(path), "--name", "Patrol.PRS",
                    "--author", "Dispatch"]) == 0
    assert _names(parse_prs(path)) == (("Patrol.PRS", "Patrol.PRS"),
                                       ("Dispatch", "Dispatch"))


def test_clone_personality_name():
    from quickprs.cloner import clone_personality
    source = parse_prs_bytes(create_blank_prs("SRC.PRS").to_bytes())
    clone = clone_personality(source, {"name": "Unit 7"})
    assert _names(parse_prs_bytes(clone.to_bytes()))[0] == (
        "Unit 7.PRS", "Unit 7.PRS")


def test_fleet_unit_names(tmp_path):
    from quickprs.fleet import _build_unit_prs
    config = tmp_path / "base.ini"
    config.write_text("[personality]\nname = Base.PRS\n", encoding="utf-8")
    prs = _build_unit_prs(config, 1001, "Engine 3", None)
    assert _names(parse_prs_bytes(prs.to_bytes()))[0] == (
        "Engine 3.PRS", "Engine 3.PRS")
