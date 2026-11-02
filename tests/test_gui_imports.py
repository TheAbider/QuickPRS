"""The GUI's import paths: the RadioReference paste and API panel, the
Import Wizard, the System Wizard and the P25 System Database dialog.

Built on a hidden Tk window like test_gui_smoke.py; message boxes are
patched.  Personalities come from create_blank_prs, so no RPM-saved test
file is needed.
"""

from pathlib import Path
from unittest import mock

import pytest

tk = pytest.importorskip("tkinter")

from quickprs import archive  # noqa: E402
from quickprs.builder import create_blank_prs  # noqa: E402

# A RadioReference trunked system page (example IDs), with a conventional
# frequency table under it
PAGE = """System Name:    Test Regional System (TESTRS)
Location:    Various, WA
County:    Statewide
System Type:    Project 25 Phase II
System Voice:    APCO-25 Common Air Interface Exclusive
System ID:    Sysid: 3AB WACN: 5A1B2

Sites and Frequencies
RFSS    Site    Name    County    Freqs
1 (1)    001 (1)    Hill Top    King    851.0125c    852.2625    853.5125
1 (1)    002 (2)    Mt. Oso    Pierce    851.5125c    852.7625    854.4875

Talkgroups

Test Agency
DEC     HEX     Mode     Alpha Tag    Description    Tag
5001    1389    T    PD DISP    Police Dispatch    Law Dispatch
5002    138a    T    PD TAC1    Police Tac 1    Law Tac
5003    138b    T    FD DISP    Fire Dispatch    Fire Dispatch

Frequency    License    Type    Tone    Alpha Tag    Description    Mode    Tag
155.76000    KQD949    BM    136.5 PL    LE D1    Law Dispatch    FMN    Law Dispatch
"""


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    from quickprs.gui import settings as gui_settings
    monkeypatch.setattr(gui_settings, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr(gui_settings, "SETTINGS_FILE",
                        tmp_path / "cfg" / "settings.json")
    top = tk.Toplevel(tk_root)
    top.withdraw()
    from quickprs.gui.app import QuickPRSApp
    with mock.patch("quickprs.gui.app.messagebox"):
        application = QuickPRSApp(top)
        application._set_document(create_blank_prs("t.PRS"),
                                  tmp_path / "t.PRS")
        yield application
    top.destroy()


def systems(prs):
    doc = archive.document_from_prs(prs)
    return [o.cls for o in doc.list("systems").items if o is not None]


def paste_inject(app, page=PAGE):
    """Parse ``page`` in the paste panel and inject it, answering yes to
    every question.  Returns the messagebox mock."""
    panel = app.import_panel
    panel._paste_clear()
    panel.paste_text.insert("1.0", page)
    panel._parse_full_page()
    with mock.patch("quickprs.gui.import_panel.messagebox") as mb, \
            mock.patch.object(type(panel), "_show_inject_confirm",
                              return_value=True), \
            mock.patch.object(app, "validate"):
        mb.askyesno.return_value = True
        panel._paste_inject()
    return mb


# ── a failed import leaves nothing behind ─────────────────────────────

def test_paste_inject_that_fails_part_way_leaves_nothing(app):
    """The P25 system goes in, then the conventional channels fail (their
    set name is taken): the P25 system comes out again."""
    from quickprs.injector import _safe_add_conv_set, make_conv_set
    _safe_add_conv_set(app.prs, make_conv_set("TESTRS", [
        {"short_name": "OLD", "tx_freq": 155.0, "rx_freq": 155.0}]))
    before = app.prs.to_bytes()
    mb = paste_inject(app)
    assert "already exists" in mb.showerror.call_args[0][1]
    assert "Nothing was added" in mb.showerror.call_args[0][1]
    assert app.prs.to_bytes() == before
    assert app.modified is False
    assert not app._undo_stack.can_undo()


def test_paste_inject(app):
    mb = paste_inject(app)
    mb.showerror.assert_not_called()
    assert systems(app.prs).count("CP25TrkSystem") == 1
    assert app.modified is True and app._undo_stack.can_undo()


# ── the WAN entry, set references and talkgroups of a panel import ───

def wan_entries(prs):
    from quickprs.injector import _wan_list
    from quickprs.record_types import P25TrkWanEntry
    out = []
    for item in _wan_list(archive.document_from_prs(prs)).items:
        if item is not None:
            entry, _ = P25TrkWanEntry.parse(item.parts[0], 0)
            out.append((entry.wan_name.strip(), entry.wacn,
                        entry.system_id))
    return out


def p25_systems(prs):
    """(short name, trunk set, group set, WAN name) of each P25 system."""
    from quickprs.injector import (
        _system_obj_names, _system_obj_refs, _system_obj_wan_name)
    doc = archive.document_from_prs(prs)
    out = []
    for obj in doc.list("systems").items:
        if obj is not None and obj.cls == "CP25TrkSystem":
            refs = dict(_system_obj_refs(obj))
            out.append((_system_obj_names(obj)[0].strip(), refs,
                        _system_obj_wan_name(obj).strip()))
    return out


def test_paste_inject_writes_the_wacn_and_names_the_wan_entry(app):
    """RPM names each WAN entry after its system and stores the WACN
    (systems on one WACN each have an entry); the panel wrote WACN 0 and
    named the entry after the WACN, so a second system on the same WACN
    got none."""
    paste_inject(app)
    second = (PAGE.replace("(TESTRS)", "(TESTR2)")
              .replace("Sysid: 3AB", "Sysid: 3AC"))
    paste_inject(app, second)
    assert wan_entries(app.prs) == [("TESTRS", 0x5A1B2, 0x3AB),
                                    ("TESTR2", 0x5A1B2, 0x3AC)]
    assert [wan for _, _, wan in p25_systems(app.prs)] == ["TESTRS",
                                                           "TESTR2"]


PAGE_TG_ONLY = """System Name:    Tg Only System (TGONLY)
System Type:    Project 25 Phase I
System ID:    Sysid: 3AC WACN: 5A1B3

DEC     HEX     Mode     Alpha Tag    Description    Tag
6001    1771    D    PD DISP    Police Dispatch    Law Dispatch
"""

PAGE_FREQ_ONLY = """System Name:    Freq Only System (FRQONLY)
System Type:    Project 25 Phase I
System ID:    Sysid: 3AD WACN: 5A1B4

RFSS    Site    Name    County    Freqs
1 (1)    001 (1)    Hill Top    King    851.0125c    852.2625    853.5125
"""


@pytest.mark.parametrize("page, trunk, group", [
    (PAGE_TG_ONLY, "", "TGONLY"),
    (PAGE_FREQ_ONLY, "FRQONLY", ""),
])
def test_paste_inject_names_only_the_sets_it_makes(app, page, trunk, group):
    from quickprs.validation import ERROR, validate_prs
    paste_inject(app, page)
    [(name, refs, _)] = p25_systems(app.prs)
    assert (refs["trunk sets"], refs["group sets"]) == (trunk, group)
    assert not [m for sev, m in validate_prs(app.prs)
                if sev == ERROR and "doesn't exist" in m]


def test_api_inject_keeps_untagged_talkgroups(app):
    """The count said 3/3 selected; the talkgroup with no service tag was
    left out of the import."""
    from quickprs.radioreference import (
        RRSite, RRSiteFreq, RRSystem, RRTalkgroup)
    panel = app.import_panel
    system = RRSystem(
        sid=1, name="Api Test System (APITST)",
        system_type="Project 25 Phase I", sysid="3AB", wacn="5A1B9",
        talkgroups=[
            RRTalkgroup(dec_id=5001, alpha_tag="PD DISP", mode="D",
                        description="Police Dispatch", tag="Law Dispatch",
                        category="Police", category_id=10),
            RRTalkgroup(dec_id=5003, alpha_tag="MISC 1", mode="D",
                        description="Misc", tag="", category="Police",
                        category_id=10),
        ],
        sites=[RRSite(site_id=1, site_number="001", name="Hill", rfss=1,
                      freqs=[RRSiteFreq(freq=851.0125, use="c"),
                             RRSiteFreq(freq=852.2625)])])
    panel._on_fetch_complete(system, None)
    assert panel.tg_count_label.cget("text") == "2/2 talkgroups selected"
    panel.api_set_name.set("APITST")
    with mock.patch("quickprs.gui.import_panel.messagebox") as mb, \
            mock.patch.object(type(panel), "_show_inject_confirm",
                              return_value=True), \
            mock.patch.object(app, "validate"):
        mb.askyesno.return_value = True
        panel._api_inject()
        mb.showerror.assert_not_called()
    from quickprs.record_types import (
        parse_group_section, parse_sets_from_sections)
    sets = parse_sets_from_sections(
        app.prs.get_section_by_class("CP25GroupSet").raw,
        app.prs.get_section_by_class("CP25Group").raw, parse_group_section)
    [gset] = [g for g in sets if g.name == "APITST"]
    assert [g.group_id for g in gset.groups] == [5001, 5003]
    assert wan_entries(app.prs) == [("APITST", 0x5A1B9, 0x3AB)]


def _api_inject(app, system, set_name):
    panel = app.import_panel
    panel._on_fetch_complete(system, None)
    panel.api_set_name.set(set_name)
    with mock.patch("quickprs.gui.import_panel.messagebox") as mb,             mock.patch.object(type(panel), "_show_inject_confirm",
                              return_value=True),             mock.patch.object(app, "validate"):
        mb.askyesno.return_value = True
        panel._api_inject()
    return mb


def test_api_inject_names_only_the_sets_it_makes(app):
    from quickprs.radioreference import RRSystem, RRTalkgroup
    mb = _api_inject(app, RRSystem(
        sid=1, name="Api (APITST)", system_type="Project 25 Phase I",
        sysid="3AB", wacn="5A1B9", talkgroups=[RRTalkgroup(
            dec_id=5001, alpha_tag="PD", mode="D", description="PD",
            tag="Law Dispatch", category="Police", category_id=10)]),
        "APITST")
    mb.showerror.assert_not_called()
    [(_, refs, _)] = p25_systems(app.prs)
    assert (refs["trunk sets"], refs["group sets"]) == ("", "APITST")


def test_api_inject_that_fails_part_way_leaves_nothing(app):
    from quickprs.radioreference import RRSystem, RRTalkgroup
    panel = app.import_panel
    panel._on_fetch_complete(RRSystem(
        sid=1, name="Api (APITST)", system_type="Project 25 Phase I",
        sysid="3AB", wacn="5A1B9", talkgroups=[RRTalkgroup(
            dec_id=5001, alpha_tag="PD", mode="D", description="PD",
            tag="Law Dispatch", category="Police", category_id=10)]), None)
    panel.api_set_name.set("APITST")
    before = app.prs.to_bytes()

    def half_then_fail(prs, config, **sets):
        from quickprs.injector import _safe_add_group_set, make_group_set
        _safe_add_group_set(prs, make_group_set("HALF", [(1, "A", "A")]))
        raise ValueError("disk full")

    with mock.patch("quickprs.gui.import_panel.messagebox") as mb, \
            mock.patch.object(type(panel), "_show_inject_confirm",
                              return_value=True), \
            mock.patch("quickprs.gui.import_panel.add_p25_trunked_system",
                       half_then_fail):
        mb.askyesno.return_value = True
        panel._api_inject()
        assert "Nothing was added" in mb.showerror.call_args[0][1]
    assert app.prs.to_bytes() == before


def test_wizard_clipboard_import_that_fails_part_way(app):
    from quickprs.gui import import_wizard
    wizard = import_wizard.ImportWizard(app.root, app)
    try:
        before = app.prs.to_bytes()
        wizard._clip_text.insert("1.0", "DEC\tHEX\tMode\tAlpha Tag\t"
                                 "Description\tTag\n"
                                 "7001\t1b59\tT\tPD\tPolice\tLaw\n")

        def half_then_fail(set_name, tgs):
            from quickprs.injector import _safe_add_group_set, make_group_set
            _safe_add_group_set(app.prs, make_group_set("HALF", [(1, "A",
                                                                  "A")]))
            raise ValueError("disk full")

        with mock.patch.object(import_wizard, "_ask_set_name",
                               return_value="CLIP"), \
                mock.patch.object(wizard, "_inject_talkgroups",
                                  half_then_fail), \
                mock.patch.object(import_wizard, "messagebox") as mb:
            wizard._import_clipboard()
        assert "Nothing was imported" in mb.showerror.call_args[0][1]
        assert app.prs.to_bytes() == before
    finally:
        wizard.destroy()
