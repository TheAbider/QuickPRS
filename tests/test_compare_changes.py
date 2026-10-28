"""compare reports changes inside sets and systems, not only sets added or
removed: a changed frequency, tone, talkgroup name, NAC or system setting
used to come out as "Files are identical" with exit code 0."""

import pytest

from quickprs import injector
from quickprs.builder import create_blank_prs
from quickprs.cli import cmd_compare
from quickprs.comparison import compare_prs, format_comparison, SAME
from quickprs.prs_parser import parse_prs_bytes
from quickprs.record_types import P25TrkSystemConfig


def _personality(conv_rx=155.76, conv_tone="136.5", conv_narrow=False,
                 tg_name="PD DISP", tg_scan=True, trunk_tx=806.0125,
                 iden_base=851_012_500, nac=0x293, system_id=939,
                 gps=None):
    """The same small personality every time, with one value changed."""
    prs = create_blank_prs()
    injector.add_conv_set(prs, injector.make_conv_set("CONV", [
        {"short_name": "LE D1", "tx_freq": 155.76, "rx_freq": conv_rx,
         "tx_tone": conv_tone, "rx_tone": conv_tone,
         "narrowband": conv_narrow},
        {"short_name": "FIRE D1", "tx_freq": 154.28},
    ]))
    injector.add_p25_conv_set(prs, injector.make_p25_conv_set("P25C", [
        {"short_name": "TAC 1", "tx_freq": 154.43, "nac_tx": nac}]))
    gset = injector.make_group_set("CITY", [
        (100, tg_name, "PD DISPATCH"), (200, "FIRE", "FIRE DISPATCH")])
    gset.groups[0].scan = tg_scan
    injector.add_p25_trunked_system(
        prs,
        P25TrkSystemConfig(system_name="CITY", long_name="CITY P25",
                           trunk_set_name="CITY", group_set_name="CITY",
                           wan_name="CITY", system_id=system_id),
        trunk_set=injector.make_trunk_set(
            "CITY", [(trunk_tx, 851.0125), (806.5125, 851.5125)]),
        group_set=gset,
        iden_set=injector.make_iden_set("CITY", [
            {"base_freq_hz": iden_base, "tx_offset_mhz": -45.0}]))
    if gps:
        from quickprs.option_maps import set_platform_option
        set_platform_option(prs, "gps", "gpsMode", gps)
    return parse_prs_bytes(prs.to_bytes())


def _changes(**changed):
    return [d for d in compare_prs(_personality(), _personality(**changed))
            if d[0] != SAME]


def test_same_personality_is_identical():
    assert _changes() == []


@pytest.mark.parametrize("changed, category, name, words", [
    ({"conv_rx": 155.775}, "Conv Set", "CONV", ["LE D1", "rx_freq"]),
    ({"conv_tone": "141.3"}, "Conv Set", "CONV", ["tx_tone", "rx_tone"]),
    ({"conv_narrow": True}, "Conv Set", "CONV", ["narrowband"]),
    ({"tg_name": "PD MAIN"}, "Group Set", "CITY", ["100 PD MAIN",
                                                   "group_name"]),
    ({"tg_scan": False}, "Group Set", "CITY", ["100 PD DISP", "scan"]),
    ({"trunk_tx": 806.0250}, "Trunk Set", "CITY",
     ["+1: 806.02500/851.01250", "-1: 806.01250/851.01250"]),
    ({"iden_base": 851_006_250}, "IDEN Set", "CITY", ["#0", "base_freq_hz"]),
    ({"nac": 0x3AB}, "P25 Conv Set", "P25C", ["TAC 1", "nac_tx"]),
    ({"system_id": 940}, "P25 Trunked", "CITY", ["system settings differ"]),
    ({"gps": "OFF"}, "Radio Options", None, ["differs"]),
])
def test_change_is_reported(changed, category, name, words):
    hits = [d for d in _changes(**changed) if d[1] == category
            and (name is None or d[2] == name)]
    assert hits, _changes(**changed)
    text = " ".join(d[3] for d in hits)
    for word in words:
        assert word in text


def test_compare_exits_1_on_a_changed_channel(tmp_path, capsys):
    a, b = tmp_path / "a.PRS", tmp_path / "b.PRS"
    a.write_bytes(_personality().to_bytes())
    b.write_bytes(_personality(conv_rx=155.775).to_bytes())
    assert cmd_compare(str(a), str(b)) == 1
    out = capsys.readouterr().out
    assert "identical" not in out.lower()
    assert "LE D1 (rx_freq)" in out


def test_identical_files_exit_0(tmp_path, capsys):
    a, b = tmp_path / "a.PRS", tmp_path / "b.PRS"
    a.write_bytes(_personality().to_bytes())
    b.write_bytes(_personality().to_bytes())
    assert cmd_compare(str(a), str(b)) == 0
    assert "identical" in capsys.readouterr().out.lower()


def test_long_change_lists_are_shortened():
    """A change line names three items, then counts the rest."""
    from quickprs.comparison import _listed
    assert _listed(["a", "b", "c", "d", "e"]) == "a, b, c and 2 more"
    lines = format_comparison(_changes(conv_rx=155.775))
    assert any("LE D1" in line for line in lines)
