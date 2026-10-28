"""--skip-encrypted: leave fully encrypted talkgroups out of a
RadioReference import (the CLI took every talkgroup, mode and encryption
level ignored; only the GUI could filter)."""

import pytest

from quickprs.radioreference import (
    RRSystem, RRSite, RRSiteFreq, RRTalkgroup, build_injection_data,
    is_fully_encrypted,
)


def _tg(dec_id, mode, encrypted=0):
    return RRTalkgroup(dec_id=dec_id, alpha_tag=f"TG {dec_id}",
                       description=f"Talkgroup {dec_id}", mode=mode,
                       encrypted=encrypted)


@pytest.mark.parametrize("mode, encrypted, expected", [
    ("DE", 0, True), ("TE", 0, True), ("AE", 0, True), ("E", 0, True),
    ("De", 0, False), ("Te", 0, False), ("D", 0, False), ("T", 0, False),
    ("A", 0, False), ("", 2, True), ("D", 1, False),
])
def test_is_fully_encrypted(mode, encrypted, expected):
    assert is_fully_encrypted(_tg(1, mode, encrypted)) is expected


def _system():
    return RRSystem(
        sid=1, name="County P25", sysid="3AB", wacn="BEE00",
        talkgroups=[_tg(100, "D"), _tg(200, "DE"), _tg(300, "De"),
                    _tg(400, "TE"), _tg(500, "", encrypted=2)],
        sites=[RRSite(site_id=1, name="Site 1", freqs=[
            RRSiteFreq(freq=851.0125, use="c"),
            RRSiteFreq(freq=851.5125)])])


def test_build_injection_data_skips_and_counts():
    data = build_injection_data(_system(), skip_encrypted=True)
    assert [t[0] for t in data["talkgroups"]] == [100, 300]
    assert data["skipped_encrypted"] == 3


def test_build_injection_data_keeps_all_by_default():
    data = build_injection_data(_system())
    assert len(data["talkgroups"]) == 5
    assert data["skipped_encrypted"] == 0


def test_auto_setup(tmp_path):
    from quickprs.auto_setup import auto_setup_from_rr
    from quickprs.builder import create_blank_prs
    summary = auto_setup_from_rr(create_blank_prs(), _system(),
                                 skip_encrypted=True)
    assert (summary["talkgroups"], summary["skipped_encrypted"]) == (2, 3)


def test_import_paste(tmp_path, capsys):
    from quickprs.builder import create_blank_prs
    from quickprs.cli import cmd_import_paste
    from quickprs.json_io import prs_to_dict
    from quickprs.prs_parser import parse_prs
    path = tmp_path / "radio.PRS"
    path.write_bytes(create_blank_prs().to_bytes())
    paste = tmp_path / "tgs.txt"
    paste.write_text(
        "DEC     HEX     Mode     Alpha Tag    Description    Tag\n"
        "100    064    D    PD DISP    Police Dispatch    Law Dispatch\n"
        "200    0C8    DE    PD SECURE    Police Secure    Law Tac\n"
        "300    12C    De    FD DISP    Fire Dispatch    Fire Dispatch\n",
        encoding="utf-8")
    assert cmd_import_paste(str(path), "COUNTY", 939, tgs_file=str(paste),
                            skip_encrypted=True) == 0
    assert "Left out 1 fully encrypted talkgroups" in capsys.readouterr().out
    groups = next(g for g in prs_to_dict(parse_prs(path))["group_sets"]
                  if g["name"] == "COUNTY")["groups"]
    assert [g["id"] for g in groups] == [100, 300]
