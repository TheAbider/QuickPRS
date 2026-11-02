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


# ── System Wizard and P25 System Database ────────────────────────────

def trk_settings(prs):
    """(sys_flags, home unit ID, IDEN set) of each P25 trunked system."""
    import struct
    doc = archive.document_from_prs(prs)
    out = []
    for obj in doc.list("systems").items:
        if obj is None or obj.cls != "CP25TrkSystem":
            continue
        data = obj.parts[0]
        _, pos = archive.read_cstring(data, 0)
        pos += 1 + 2 + 42
        _, pos = archive.read_cstring(data, pos)      # long name
        flags = data[pos:pos + 15]
        pos += 15
        _, pos = archive.read_cstring(data, pos)      # trunk set
        _, pos = archive.read_cstring(data, pos)      # talkgroup set
        home = struct.unpack_from("<I", data, pos + 12)[0]
        iden = archive.read_cstring(obj.parts[2], 4)[0]
        out.append((flags, home, iden))
    return out


SETTINGS = {"home_unit_id": 12345, "tdma_capable": True,
            "adaptive_filter": True}


def test_iden_set_for_template():
    from quickprs.injector import (
        _safe_add_iden_set, _set_names, iden_set_for_template,
        make_iden_set)
    prs = create_blank_prs("t.PRS")
    new, name = iden_set_for_template(prs, "800-TDMA")
    assert new is not None and name == new.name
    _safe_add_iden_set(prs, new)
    # the same band again: shared, nothing to add
    assert iden_set_for_template(prs, "800-TDMA") == (None, name)
    # the default name taken by a set with other entries: numbered
    other = create_blank_prs("u.PRS")
    _safe_add_iden_set(other, make_iden_set(name, [
        {"base_freq_hz": 136_000_000, "chan_spacing_hz": 12500}]))
    again, again_name = iden_set_for_template(other, "800-TDMA")
    assert again is not None and again_name == name[:7] + "2"
    _safe_add_iden_set(other, again)
    assert _set_names(other, "IDEN sets") == [name, again_name]
    assert iden_set_for_template(other, "no-such-band") == (None, "")


def test_database_adds_two_systems_on_one_band():
    """PSERN then WSP (both 800 MHz Phase II): the second failed with
    "IDEN set '8TDMA' already exists" and left a stray system."""
    from quickprs.gui.system_wizard import _add_system_from_database
    from quickprs.injector import _set_names
    from quickprs.record_types import build_sys_flags
    from quickprs.system_database import get_system_by_name
    prs = create_blank_prs("t.PRS")
    for name in ("PSERN", "WSP"):
        _add_system_from_database(prs, get_system_by_name(name),
                                  settings=SETTINGS)
    [iden] = _set_names(prs, "IDEN sets")
    assert trk_settings(prs) == [(build_sys_flags(SETTINGS), 12345, iden)] * 2


def _wizard(app, freqs="", tgs="", source="manual"):
    from quickprs.gui.system_wizard import SystemWizard
    wizard = SystemWizard(app.root, app)
    wizard.source.set(source)
    wizard.sys_name.set("WIZ")
    wizard.sys_long_name.set("WIZARD SYSTEM")
    wizard.sys_id.set("939")
    wizard.sys_wacn.set("781824")
    wizard.sys_band.set("800")
    wizard.sys_type.set("Phase II")
    wizard.freq_text = freqs
    wizard.tg_text = tgs
    return wizard


def _finish(wizard, answer=True):
    from quickprs.gui import system_wizard
    with mock.patch.object(system_wizard, "messagebox") as mb:
        mb.askyesno.return_value = answer
        wizard._finish()
    return mb


def test_wizard_applies_settings_and_shares_the_iden_set(app):
    from quickprs.injector import _set_names
    from quickprs.record_types import build_sys_flags
    app.settings.update(SETTINGS)
    mb = _finish(_wizard(app, tgs="100,PD,Police"))
    mb.showerror.assert_not_called()
    wizard = _wizard(app, tgs="200,FD,Fire")
    wizard.sys_name.set("WIZ2")
    mb = _finish(wizard)
    mb.showerror.assert_not_called()
    [iden] = _set_names(app.prs, "IDEN sets")
    flags = build_sys_flags(app.settings)
    assert flags != bytes(15)
    assert trk_settings(app.prs) == [(flags, 12345, iden)] * 2


def test_wizard_warns_about_unverified_ids(app):
    from quickprs.system_database import get_system_by_name
    wizard = _wizard(app, source="database")
    wizard.selected_system = get_system_by_name("WSP")      # unverified
    before = app.prs.to_bytes()
    mb = _finish(wizard, answer=False)
    assert "Add it anyway?" in mb.askyesno.call_args[0][1]
    assert app.prs.to_bytes() == before
    wizard.selected_system = get_system_by_name("PSERN")    # verified
    mb = _finish(wizard)
    mb.askyesno.assert_not_called()
    assert len(trk_settings(app.prs)) == 1


def test_wizard_back_keeps_the_typed_text(app):
    wizard = _wizard(app)
    try:
        wizard._show_step(2)
        wizard._freq_text_widget.insert("1.0", "851.0125")
        wizard._prev_step()
        assert wizard.freq_text == "851.0125"
        wizard._show_step(2)
        assert wizard._freq_text_widget.get("1.0", "end").strip() == (
            "851.0125")
        wizard._show_step(3)
        wizard._tg_text_widget.insert("1.0", "100,PD")
        wizard._prev_step()
        assert wizard.tg_text == "100,PD"
    finally:
        wizard.destroy()


def test_wizard_reads_control_marks_units_and_tabs(app):
    wizard = _wizard(app, freqs="\n".join([
        "851.0125c", "851.5125,c", "806.0125\t851.0125", "852.2625 MHz",
        "# a comment", "Hill Top", "851.0125 852.0 853.0"]),
        tgs="\n".join(["100\tPD DISP\tPolice Dispatch", "200; FD",
                       "PD,100"]))
    from quickprs.iden_library import calculate_tx_freq
    assert wizard._parse_freqs() == [
        (calculate_tx_freq(851.0125), 851.0125),
        (calculate_tx_freq(851.5125), 851.5125),
        (806.0125, 851.0125),
        (calculate_tx_freq(852.2625), 852.2625)]
    assert wizard.freq_skipped == ["Hill Top", "851.0125 852.0 853.0"]
    assert wizard._parse_talkgroups() == [
        (100, "PD DISP", "Police Dispatch"), (200, "FD", "FD")]
    assert wizard.tg_skipped == ["PD,100"]
    wizard.destroy()


def test_database_dialog_and_import_wizard_apply_settings(app):
    """Both ways of adding a system from the database: the P25 System
    Database dialog wrote home unit ID 0 and no flags; the Import
    Wizard's database tab wrote the flags but unit 0."""
    from quickprs.gui import import_wizard, system_wizard
    from quickprs.record_types import build_sys_flags
    app.settings.update(SETTINGS)
    dialog = system_wizard.SystemDatabaseDialog.__new__(
        system_wizard.SystemDatabaseDialog)
    dialog.app = app
    dialog._tree = mock.Mock(selection=lambda: ["PSERN"])
    with mock.patch.object(system_wizard, "messagebox") as mb:
        mb.askyesno.return_value = True
        dialog._add_system()
        mb.showerror.assert_not_called()
    wizard = import_wizard.ImportWizard(app.root, app)
    try:
        wizard._db_tree.selection_set("WSP")       # listed already
        with mock.patch.object(import_wizard, "messagebox") as mb:
            mb.askyesno.return_value = True
            wizard._import_from_database()
            mb.showerror.assert_not_called()
    finally:
        wizard.destroy()
    flags = build_sys_flags(app.settings)
    assert [(f, home) for f, home, _ in trk_settings(app.prs)] == [
        (flags, 12345), (flags, 12345)]


# ── Import Wizard ─────────────────────────────────────────────────────

def conv_sets(prs):
    from quickprs.record_types import (
        parse_conv_channel_section, parse_sets_from_sections)
    return parse_sets_from_sections(
        prs.get_section_by_class("CConvSet").raw,
        prs.get_section_by_class("CConvChannel").raw,
        parse_conv_channel_section)


def group_sets(prs):
    from quickprs.record_types import (
        parse_group_section, parse_sets_from_sections)
    return parse_sets_from_sections(
        prs.get_section_by_class("CP25GroupSet").raw,
        prs.get_section_by_class("CP25Group").raw, parse_group_section)


@pytest.fixture
def wizard(app):
    from quickprs.gui.import_wizard import ImportWizard
    w = ImportWizard(app.root, app)
    yield w
    w.destroy()


def test_templates_keep_their_flags(app, wizard):
    """NOAA went in with TX on, FRS and MURS wideband: the wizard copied
    the names, frequencies and tones but not the flags."""
    from quickprs.gui import import_wizard
    from quickprs.templates import get_template_channels
    for name in ("noaa", "frs", "murs", "gmrs"):
        wizard._template_vars[name].set(True)
    with mock.patch.object(import_wizard, "messagebox"):
        wizard._import_templates()
    sets = {cs.name: cs.channels for cs in conv_sets(app.prs)}
    for name in ("noaa", "frs", "murs", "gmrs"):
        want = get_template_channels(name)
        got = sets[name.upper()]
        assert [c.tx for c in got] == [w.get("tx", True) for w in want]
        assert [c.narrowband for c in got] == [
            w.get("narrowband", False) for w in want]
    assert not any(c.tx for c in sets["NOAA"])
    assert all(c.narrowband for c in sets["FRS"])


def test_quickprs_csv_sets_go_in_as_they_are(app, wizard, tmp_path):
    """A talkgroup CSV's sets were merged into one, with TX off and scan
    on for every talkgroup."""
    from quickprs.csv_export import export_group_sets
    from quickprs.gui import import_wizard
    from quickprs.injector import make_group_set
    police = make_group_set("POLICE", [(100, "PD", "Police")])
    police.groups[0].tx = True
    fire = make_group_set("FIRE", [(200, "FD", "Fire")])
    fire.groups[0].scan = False
    path = tmp_path / "groups.csv"
    export_group_sets(str(path), [police, fire])
    wizard._file_path_var.set(str(path))
    wizard._file_format_var.set("quickprs")
    with mock.patch.object(import_wizard, "messagebox") as mb,             mock.patch.object(import_wizard, "_ask_set_name",
                              return_value="MERGED") as ask:
        mb.askyesno.return_value = True
        wizard._import_file()
        mb.showerror.assert_not_called()
        ask.assert_not_called()             # two sets: their own names
    sets = {g.name: g.groups for g in group_sets(app.prs)}
    assert [(g.group_id, g.tx, g.scan) for g in sets["POLICE"]] == [
        (100, True, True)]
    assert [(g.group_id, g.tx, g.scan) for g in sets["FIRE"]] == [
        (200, False, False)]


def test_quickprs_csv_lone_set_takes_a_name(app, wizard, tmp_path):
    from quickprs.csv_export import export_conv_sets
    from quickprs.gui import import_wizard
    from quickprs.injector import make_conv_set
    path = tmp_path / "conv.csv"
    export_conv_sets(str(path), [make_conv_set("MURS", [
        {"short_name": "MURS 1", "tx_freq": 151.82, "narrowband": True}])])
    wizard._file_path_var.set(str(path))
    wizard._file_format_var.set("quickprs")
    with mock.patch.object(import_wizard, "messagebox") as mb, \
            mock.patch.object(import_wizard, "_ask_set_name",
                              return_value="MYMURS"):
        wizard._import_file()
        mb.showerror.assert_not_called()
    [cs] = [c for c in conv_sets(app.prs) if c.name == "MYMURS"]
    assert [(c.short_name, c.narrowband) for c in cs.channels] == [
        ("MURS 1", True)]
    from quickprs.injector import systems_using_set
    assert systems_using_set(app.prs, "conv", "MYMURS") == ["MYMURS"]


def test_a_file_after_a_quickprs_csv(app, wizard, tmp_path):
    """The next file's import must not bring the CSV's sets back."""
    from quickprs.csv_export import export_group_sets
    from quickprs.gui import import_wizard
    from quickprs.injector import make_group_set
    csv_path = tmp_path / "groups.csv"
    export_group_sets(str(csv_path), [
        make_group_set("POLICE", [(100, "PD", "Police")])])
    freqs = tmp_path / "freqs.txt"
    freqs.write_text("155760000\n")              # a DSD+ list, in Hz
    with mock.patch.object(import_wizard, "messagebox") as mb, \
            mock.patch.object(import_wizard, "_ask_set_name",
                              side_effect=["POLICE", "FREQS"]):
        for path, fmt in ((csv_path, "quickprs"), (freqs, "dsd+")):
            wizard._file_path_var.set(str(path))
            wizard._file_format_var.set(fmt)
            wizard._import_file()
        mb.showerror.assert_not_called()
    [freq_set] = [c for c in conv_sets(app.prs) if c.name == "FREQS"]
    assert [c.rx_freq for c in freq_set.channels] == [155.76]


def test_quickprs_csv_trunk_sets(app, wizard, tmp_path):
    """Trunk CSVs (and P25 conventional ones) were "No importable data"."""
    from quickprs.csv_export import export_trunk_sets
    from quickprs.gui import import_wizard
    from quickprs.injector import _set_names, make_trunk_set
    path = tmp_path / "trunk.csv"
    export_trunk_sets(str(path), [make_trunk_set("TRK", [
        (806.0125, 851.0125)])])
    wizard._file_path_var.set(str(path))
    wizard._file_format_var.set("quickprs")
    with mock.patch.object(import_wizard, "messagebox") as mb, \
            mock.patch.object(import_wizard, "_ask_set_name",
                              return_value="TRK"):
        wizard._import_file()
        mb.showerror.assert_not_called()
        mb.showinfo.assert_not_called()
    assert _set_names(app.prs, "trunk sets") == ["TRK"]


def test_quickprs_csv_set_name_taken_imports_nothing(app, wizard,
                                                     tmp_path):
    from quickprs.csv_export import export_group_sets
    from quickprs.gui import import_wizard
    from quickprs.injector import _safe_add_group_set, make_group_set
    _safe_add_group_set(app.prs, make_group_set("FIRE", [(9, "X", "X")]))
    before = app.prs.to_bytes()
    path = tmp_path / "groups.csv"
    export_group_sets(str(path), [
        make_group_set("POLICE", [(100, "PD", "Police")]),
        make_group_set("FIRE", [(200, "FD", "Fire")])])
    wizard._file_path_var.set(str(path))
    wizard._file_format_var.set("quickprs")
    with mock.patch.object(import_wizard, "messagebox") as mb,             mock.patch.object(import_wizard, "_ask_set_name",
                              return_value="MERGED"):
        mb.askyesno.return_value = True
        wizard._import_file()
        assert "Nothing was imported" in mb.showerror.call_args[0][1]
    assert app.prs.to_bytes() == before


def test_clipboard_import_takes_what_is_in_the_box(app, wizard):
    """Preview one paste, replace it, press Import: the first was
    imported."""
    from quickprs.gui import import_wizard
    header = "DEC\tHEX\tMode\tAlpha Tag\tDescription\tTag\n"
    wizard._clip_text.insert("1.0", header + "7001\t1b59\tT\tA\tA\tLaw\n")
    wizard._preview_clipboard()
    wizard._clip_text.delete("1.0", "end")
    wizard._clip_text.insert("1.0", header + "8001\t1f41\tT\tB\tB\tLaw\n")
    with mock.patch.object(import_wizard, "_ask_set_name",
                           return_value="CLIP"), \
            mock.patch.object(import_wizard, "messagebox"):
        wizard._import_clipboard()
    [clip] = [g for g in group_sets(app.prs) if g.name == "CLIP"]
    assert [g.group_id for g in clip.groups] == [8001]
