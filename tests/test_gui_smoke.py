"""Smoke tests that build the real GUI on a hidden Tk window.

Nothing here opens a visible window or runs the event loop; message boxes
are patched.  These tests exist because the app once crashed on start
(a missing argument in the welcome screen) and no test constructed it.
"""

import shutil
from pathlib import Path
from unittest import mock

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


@pytest.fixture(scope="module")
def tk_root():
    """One Tk interpreter for the module: creating many in one process
    fails now and then on Windows ("Tcl wasn't installed properly")."""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    """A QuickPRSApp on a hidden window, with settings in tmp_path."""
    from quickprs.gui import settings as gui_settings
    monkeypatch.setattr(gui_settings, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr(gui_settings, "SETTINGS_FILE",
                        tmp_path / "cfg" / "settings.json")
    top = tk.Toplevel(tk_root)
    top.withdraw()
    from quickprs.gui.app import QuickPRSApp
    with mock.patch("quickprs.gui.app.messagebox"):
        application = QuickPRSApp(top)
        yield application
    top.destroy()


def _change(app, label):
    """A real edit through the app, as the GUI makes one."""
    from quickprs.injector import edit_personality
    app.save_undo_snapshot(label)
    edit_personality(app.prs, saved_by=label)
    app.mark_modified()


def test_app_starts(app):
    assert app.prs is None
    assert "QuickPRS" in app.root.title()


def test_open_resets_undo_history(app, tmp_path):
    from quickprs.builder import create_blank_prs
    from quickprs.prs_writer import write_prs
    a, b = tmp_path / "a.PRS", tmp_path / "b.PRS"
    write_prs(create_blank_prs("a.PRS"), a)
    write_prs(create_blank_prs("b.PRS"), b)

    app._open_path(a, confirmed=True)
    _change(app, "edit A")
    assert app._undo_stack.can_undo()
    app._open_path(b, confirmed=True)
    # Undo history belonged to A; undoing must not put A's bytes into B
    assert not app._undo_stack.can_undo()
    assert app.prs_path == b
    assert app.modified is False


def test_failed_save_stops_close(app, tmp_path):
    from quickprs.builder import create_blank_prs
    app._set_document(create_blank_prs("x.PRS"), tmp_path / "x.PRS")
    app.modified = True
    with mock.patch("quickprs.gui.app.messagebox") as mb, \
            mock.patch("quickprs.gui.app.write_prs",
                       side_effect=PermissionError("locked")):
        mb.askyesnocancel.return_value = True        # "Save first"
        assert app._confirm_discard("close") is False
        mb.showerror.assert_called()


def test_keys_ignored_in_text_fields(app):
    calls = []
    handler = app._unless_typing(lambda: calls.append(1))
    entry = tk.Entry(app.root)
    tree_event = mock.Mock(widget=app.root)
    entry_event = mock.Mock(widget=entry)
    assert handler(entry_event) is None and calls == []
    assert handler(tree_event) == "break" and calls == [1]


def test_selected_pairs_are_exact(app):
    """Selecting TG 100 in set A must not select TG 100 in set B."""
    pv = app.personality_view
    tree = pv.tree
    a = tree.insert("", "end", text="A")
    b = tree.insert("", "end", text="B")
    pv._item_meta[a] = {"name": "SET A"}
    pv._item_meta[b] = {"name": "SET B"}
    t1 = tree.insert(a, "end", text="100")
    t2 = tree.insert(b, "end", text="200")
    pairs = pv._selected_tg_pairs([(t1, {"group_id": 100}),
                                   (t2, {"group_id": 200})])
    assert pairs == {("SET A", 100), ("SET B", 200)}


@pytest.mark.skipif(not PAWS.exists(), reason="PAWSOVERMAWS.PRS not available")
def test_open_real_file_and_refresh(app, tmp_path):
    copy = tmp_path / "p.PRS"
    shutil.copy(PAWS, copy)
    app._open_path(copy, confirmed=True)
    assert app.prs is not None
    assert app.personality_view.tree.get_children()


def test_wizard_rejects_out_of_range_talkgroups():
    from quickprs.gui.system_wizard import SystemWizard
    bad = SystemWizard._bad_talkgroup_ids(None, [(70000, "X", "X"),
                                                 (5, "Y", "Y"),
                                                 (0, "Z", "Z")])
    assert bad == [70000, 0]


def test_import_wizard_injects_into_blank(app):
    """The import wizard's helpers used config fields that do not exist
    and the non-creating group adder, so every import failed."""
    from quickprs import archive
    from quickprs.builder import create_blank_prs
    from quickprs.gui.import_wizard import ImportWizard
    app.prs = create_blank_prs()
    fake = mock.Mock(app=app)
    ImportWizard._inject_channels(fake, "MURS", [
        {"short_name": "MURS1", "tx_freq": 151.82}])
    ImportWizard._inject_talkgroups(fake, "TGS", [
        {"group_id": 100, "short_name": "TG100", "long_name": "TG 100"}])
    assert archive.check(app.prs) == []


def test_trunk_edit_while_filtered_hits_the_right_channel(app, tmp_path):
    """The search's filter mode detaches rows that do not match, so a
    row's place among its visible siblings is not its channel's place in
    the set: editing the second channel while the first was hidden changed
    the first."""
    from quickprs import injector
    from quickprs.builder import create_blank_prs
    from quickprs.prs_writer import write_prs
    from quickprs.record_types import P25TrkSystemConfig
    prs = create_blank_prs("trunk.PRS")
    injector.add_p25_trunked_system(
        prs, P25TrkSystemConfig(system_name="CITY", long_name="CITY",
                                trunk_set_name="CITY", group_set_name="CITY",
                                wan_name="CITY"),
        trunk_set=injector.make_trunk_set("CITY", [
            (806.0125, 851.0125), (806.5125, 851.5125),
            (807.0125, 852.0125)]),
        group_set=injector.make_group_set("CITY", [(1, "TG", "TG")]))
    path = tmp_path / "trunk.PRS"
    write_prs(prs, path)
    app._open_path(path, confirmed=True)

    pv = app.personality_view
    pv._filter_mode.set(True)
    pv.search_var.set("851.5125")          # only the second channel shows
    iid, meta = next((i, m) for i, m in pv._item_meta.items()
                     if m.get("type") == "trunk_channel"
                     and m.get("rx") == 851.5125)
    assert pv.tree.index(iid) == 0         # first among visible rows
    with mock.patch("quickprs.gui.personality_view.messagebox"):
        pv._commit_inline_edit(iid, meta, "806.525", 16)

    from quickprs.record_types import parse_trunk_channel_section
    channels = next(s for s in injector._parse_section_data(
        app.prs.get_section_by_class("CTrunkChannel"),
        parse_trunk_channel_section,
        injector._get_first_count(app.prs, "CTrunkSet"))
        if s.name == "CITY").channels
    assert [c.tx_freq for c in channels] == [806.0125, 806.525, 807.0125]


def _p25_conv_personality(tmp_path):
    from quickprs import injector
    from quickprs.builder import create_blank_prs
    from quickprs.prs_writer import write_prs
    from quickprs.record_types import P25ConvSystemConfig
    prs = create_blank_prs("p25c.PRS")
    injector.add_p25_conv_set(prs, injector.make_p25_conv_set("P25C", [
        {"short_name": "TAC 1", "tx_freq": 154.43, "nac_tx": 0x3AB}]))
    injector.add_p25_conv_system(prs, P25ConvSystemConfig(
        system_name="P25C", long_name="P25 CONV", conv_set_name="P25C"))
    injector._safe_add_iden_set(prs, injector.make_iden_set(
        "SPARE", [{"base_freq_hz": 851_012_500}]))
    injector._safe_add_iden_set(prs, injector.make_iden_set(
        "KEEP", [{"base_freq_hz": 762_006_250}]))
    path = tmp_path / "p25c.PRS"
    write_prs(prs, path)
    return path


def test_p25_conv_set_csv_export(app, tmp_path):
    """The P25 conv set menu offered Export to CSV, and the file came out
    empty; it is now P25_CONV_SET.csv, which import-csv reads."""
    from quickprs.csv_import import import_csv
    app._open_path(_p25_conv_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    meta = next(m for m in pv._item_meta.values()
                if m.get("type") == "p25_conv_set")
    out = tmp_path / "out.csv"
    with mock.patch("quickprs.gui.personality_view.filedialog") as fd, \
            mock.patch("quickprs.gui.personality_view.messagebox"):
        fd.asksaveasfilename.return_value = str(out)
        pv._export_set_csv("p25_conv_set", "P25C", meta["set_data"])
    kind, sets = import_csv(out)
    assert kind == "p25conv"
    assert [(c.short_name, c.nac_tx) for c in sets[0].channels] == [
        ("TAC 1", 0x3AB)]


def test_delete_iden_set_keeps_the_file_readable(app, tmp_path):
    from quickprs import archive
    from quickprs.prs_parser import parse_prs_bytes
    app._open_path(_p25_conv_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    pv._delete_iden_set(app.prs, "SPARE")
    back = parse_prs_bytes(app.prs.to_bytes())
    assert archive.check(back) == []
    names = [archive.read_cstring(o.parts[1], 0)[0] for o in
             archive.document_from_prs(back).list("IDEN sets").items]
    assert names == ["KEEP"]


def test_api_fetch_result_is_handled_on_the_main_thread(app):
    """The fetch thread called Tk (winfo_toplevel().after) itself; Tk may
    only be called from the main thread.  The result now comes back
    through a queue the main thread polls."""
    import threading
    import time
    from quickprs.gui import import_panel as ip
    from quickprs.radioreference import RRSystem

    panel = app.import_panel
    seen = {}

    class FakeAPI:
        def __init__(self, *args):
            seen["api_thread"] = threading.current_thread()

        def get_system(self, sid):
            return RRSystem(sid=sid, name="FAKE")

    def complete(system, error):
        seen["thread"] = threading.current_thread()
        seen["result"] = (system.name if system else None, error)

    panel.url_var.set("https://www.radioreference.com/db/sid/11628")
    panel.user_var.set("u")
    panel.pass_var.set("p")
    panel.key_var.set("k")
    with mock.patch.object(ip, "RadioReferenceAPI", FakeAPI), \
            mock.patch.object(ip, "HAS_ZEEP", True), \
            mock.patch.object(panel, "_on_fetch_complete", complete), \
            mock.patch.object(panel, "winfo_toplevel",
                              side_effect=AssertionError("Tk call")):
        panel._fetch()
        deadline = time.time() + 5
        while "result" not in seen and time.time() < deadline:
            app.root.update()
            time.sleep(0.02)
    assert seen["result"] == ("FAKE", None)
    assert seen["thread"] is threading.main_thread()
    assert seen["api_thread"] is not threading.main_thread()


def _gui_personality(tmp_path, name="gui.PRS"):
    """Two talkgroup sets, two channel sets and a trunk set."""
    from quickprs import injector
    from quickprs.builder import create_blank_prs
    from quickprs.prs_writer import write_prs
    from quickprs.record_types import P25TrkSystemConfig
    prs = create_blank_prs(name)
    src = injector.make_group_set("SRC", [(100, "PD SEC", "PD SECURE"),
                                          (200, "FIRE", "FIRE DISPATCH")])
    tg = src.groups[0]
    tg.tx, tg.encrypted, tg.key_id, tg.priority_tg, tg.scan = (
        True, True, 5, True, False)
    injector.add_p25_trunked_system(
        prs, P25TrkSystemConfig(system_name="CITY", long_name="CITY",
                                trunk_set_name="CITY", group_set_name="SRC",
                                wan_name="CITY"),
        trunk_set=injector.make_trunk_set("CITY", [
            (806.0125, 851.0125), (806.5125, 851.5125),
            (807.0125, 852.0125)]),
        group_set=src)
    injector.add_group_set(prs, injector.make_group_set(
        "DST", [(300, "OTHER", "OTHER")]))
    injector.add_conv_set(prs, injector.make_conv_set("CSRC", [
        {"short_name": "A", "tx_freq": 151.625},
        {"short_name": "B", "tx_freq": 462.5625, "tx_tone": "250.3",
         "rx_tone": "250.3", "narrowband": True, "scan": False}]))
    injector.add_conv_set(prs, injector.make_conv_set("CDST", [
        {"short_name": "Z", "tx_freq": 154.57}]))
    path = tmp_path / name
    write_prs(prs, path)
    return path


def _rows(pv, kind, **match):
    return [(iid, m) for iid, m in pv._item_meta.items()
            if m.get("type") == kind
            and all(m.get(k) == v for k, v in match.items())]


def _sets(prs, data_cls, set_cls, parser):
    from quickprs import injector
    return {s.name: s for s in injector._parse_section_data(
        prs.get_section_by_class(data_cls), parser,
        injector._get_first_count(prs, set_cls))}


def test_pasted_talkgroup_keeps_its_settings(app, tmp_path):
    """Paste rebuilt talkgroups from ID and names: TX, scan, encryption,
    key and priority went back to defaults."""
    from quickprs.record_types import parse_group_section
    app._open_path(_gui_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    iid, _ = _rows(pv, "talkgroup", group_id=100)[0]
    pv.tree.selection_set(iid)
    pv._on_copy(None)
    pv._paste_talkgroups(app.prs, "DST")
    sets = _sets(app.prs, "CP25Group", "CP25GroupSet", parse_group_section)
    source = next(g for g in sets["SRC"].groups if g.group_id == 100)
    pasted = next(g for g in sets["DST"].groups if g.group_id == 100)
    assert pasted == source
    assert (pasted.tx, pasted.encrypted, pasted.key_id, pasted.scan) == (
        True, True, 5, False)


def test_pasted_channel_is_the_one_copied(app, tmp_path):
    """Paste looked the channel up by its place at paste time, so after
    the source set changed it pasted another channel."""
    from quickprs import injector
    from quickprs.record_types import parse_conv_channel_section
    app._open_path(_gui_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    iid, _ = _rows(pv, "conv_channel", name="B")[0]
    pv.tree.selection_set(iid)
    pv._on_copy(None)
    # the source set changes before the paste: B moves to place 0
    injector.reorder_conv_channel(app.prs, "CSRC", 1, 0)
    pv._paste_conv_channels(app.prs, "CDST")
    sets = _sets(app.prs, "CConvChannel", "CConvSet",
                 parse_conv_channel_section)
    pasted = sets["CDST"].channels[-1]
    assert pasted.short_name == "B"
    assert (pasted.tx_tone, pasted.narrowband, pasted.scan) == (
        "250.3", True, False)


def test_channels_paste_into_another_file(app, tmp_path):
    from quickprs.record_types import parse_conv_channel_section
    app._open_path(_gui_personality(tmp_path, "one.PRS"), confirmed=True)
    pv = app.personality_view
    iid, _ = _rows(pv, "conv_channel", name="B")[0]
    pv.tree.selection_set(iid)
    pv._on_copy(None)
    (tmp_path / "other").mkdir()
    app._open_path(_gui_personality(tmp_path / "other", "two.PRS"),
                   confirmed=True)
    # this file's CSRC holds A where the copied B was
    from quickprs import injector
    injector.reorder_conv_channel(app.prs, "CSRC", 1, 0)
    pv._paste_conv_channels(app.prs, "CDST")
    sets = _sets(app.prs, "CConvChannel", "CConvSet",
                 parse_conv_channel_section)
    assert [c.short_name for c in sets["CDST"].channels] == ["Z", "B"]


def test_trunk_drag_while_filtered_moves_the_right_channels(app, tmp_path):
    """Drag-reorder took channel indexes from the rows' places among the
    visible rows."""
    from quickprs.record_types import parse_trunk_channel_section
    app._open_path(_gui_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    pv._filter_mode.set(True)
    pv.search_var.set("852.0125")          # only the third channel shows
    third, _ = _rows(pv, "trunk_channel", rx=852.0125)[0]
    first, _ = _rows(pv, "trunk_channel", rx=851.0125)[0]
    set_iid = pv.tree.parent(third)
    with mock.patch("quickprs.gui.personality_view.messagebox"):
        pv._reorder_trunk_channels(set_iid, third, first)
    sets = _sets(app.prs, "CTrunkChannel", "CTrunkSet",
                 parse_trunk_channel_section)
    assert [c.rx_freq for c in sets["CITY"].channels] == [
        852.0125, 851.0125, 851.5125]


def _viewer(tk_root, prs_a, prs_b):
    from quickprs.gui.diff_viewer import DiffViewer
    viewer = DiffViewer(tk_root, prs_a, prs_b)
    viewer.withdraw()
    tops = [viewer.tree_b.item(i, "text")
            for i in viewer.tree_b.get_children()]
    rows = {viewer.tree_b.item(i, "text"):
            [(viewer.tree_b.item(c, "text"),
              viewer.tree_b.item(c, "values")[0])
             for c in viewer.tree_b.get_children(i)]
            for i in viewer.tree_b.get_children()}
    summary = viewer._summary.cget("text")
    viewer.destroy()
    return tops, rows, summary


def test_diff_viewer_shows_every_kind_of_difference(tk_root):
    """It drew only talkgroup and trunk set rows from compare_prs, so a
    file differing in a channel tone, an IDEN element or a system ID read
    as 'No differences found.'"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_compare_changes import _personality
    base = _personality()
    for changed, section, words in [
        ({"conv_tone": "141.3"}, "Conv Set", "rx_tone"),
        ({"iden_base": 851_006_250}, "IDEN Set", "base_freq_hz"),
        ({"system_id": 940}, "P25 Trunked", "system settings differ"),
        ({"nac": 0x3AB}, "P25 Conv Set", "nac_tx"),
    ]:
        tops, rows, summary = _viewer(tk_root, base, _personality(**changed))
        assert section in tops, (changed, tops)
        assert any(words in detail for _, detail in rows[section]), rows
        assert summary != "No differences found."


def test_diff_viewer_identical(tk_root):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_compare_changes import _personality
    tops, _, summary = _viewer(tk_root, _personality(), _personality())
    assert summary == "No differences found."
    assert len(tops) == 1 and tops[0].startswith("Systems")


def _editor_window(app, category="GPS Settings"):
    before = set(app.root.winfo_children())
    app.personality_view._show_xml_editor(category)
    return next(w for w in app.root.winfo_children()
                if w not in before and isinstance(w, tk.Toplevel))


def _button(widget, text):
    for child in widget.winfo_children():
        try:
            if child.cget("text") == text:
                return child
        except tk.TclError:
            pass
        found = _button(child, text)
        if found is not None:
            return found
    return None


def _first(widget, kind):
    for child in widget.winfo_children():
        if isinstance(child, kind):
            return child
        found = _first(child, kind)
        if found is not None:
            return found
    return None


def _options_personality(tmp_path):
    from quickprs.builder import create_blank_prs
    from quickprs.option_maps import set_platform_option
    from quickprs.prs_writer import write_prs
    prs = create_blank_prs("opts.PRS")
    set_platform_option(prs, "gps", "gpsMode", "ON")
    path = tmp_path / "opts.PRS"
    write_prs(prs, path)
    return path


def test_option_editor_save_can_be_undone(app, tmp_path):
    """The option editors changed the personality without an undo
    snapshot."""
    app._open_path(_options_personality(tmp_path), confirmed=True)
    assert not app._undo_stack.can_undo()
    win = _editor_window(app)
    _first(win, ttk.Checkbutton).invoke()       # change one setting
    _button(win, "Save").invoke()
    assert app._undo_stack.can_undo()


def test_option_editor_after_undo_does_not_write(app, tmp_path):
    """An editor kept the personality it opened on; after Undo replaced
    it, Save wrote into an object nothing used and said 'Saved'."""
    app._open_path(_options_personality(tmp_path), confirmed=True)
    _change(app, "something")
    current = app.prs
    win = _editor_window(app)
    with mock.patch("quickprs.gui.app.messagebox"):
        app.undo_injection()
    assert app.prs is not current
    before = app.prs.to_bytes()
    with mock.patch("quickprs.gui.personality_view.messagebox") as mb:
        _button(win, "Save").invoke()
        mb.showwarning.assert_called_once()
    assert app.prs.to_bytes() == before



def test_snapshot_without_a_change_leaves_no_undo_step(app, tmp_path):
    """A dialog cancelled, an Apply that changed nothing, or an operation
    that failed after the snapshot left an undo step that changed nothing
    (and cleared the redo history)."""
    from quickprs.builder import create_blank_prs
    from quickprs.prs_writer import write_prs
    path = tmp_path / "a.PRS"
    write_prs(create_blank_prs("a.PRS"), path)
    app._open_path(path, confirmed=True)
    _change(app, "first")
    with mock.patch("quickprs.gui.app.messagebox"):
        app.undo_injection()
    assert app._undo_stack.can_redo()
    app.save_undo_snapshot("cancelled")      # nothing changes after it
    app.mark_modified()
    assert not app._undo_stack.can_undo()
    assert app._undo_stack.can_redo()


def test_moving_the_last_channel_down_leaves_no_undo_step(app, tmp_path):
    app._open_path(_gui_personality(tmp_path), confirmed=True)
    pv = app.personality_view
    with mock.patch("quickprs.gui.personality_view.messagebox"):
        pv._move_trunk_channel("CITY", 2, +1)     # already last
    assert not app._undo_stack.can_undo()
    with mock.patch("quickprs.gui.personality_view.messagebox"):
        pv._move_trunk_channel("CITY", 1, +1)
    assert app._undo_stack.can_undo()


def test_system_from_database_can_be_undone(app, tmp_path):
    """The database dialog set app.modified itself instead of calling
    mark_modified(), so the change never became an undo step (and the
    size and statistics shown went stale)."""
    from quickprs.builder import create_blank_prs
    from quickprs.gui.system_wizard import SystemDatabaseDialog
    from quickprs.prs_writer import write_prs
    path = tmp_path / "db.PRS"
    write_prs(create_blank_prs("db.PRS"), path)
    app._open_path(path, confirmed=True)
    before = app.prs.to_bytes()
    dialog = SystemDatabaseDialog(app.root, app)
    dialog.withdraw()
    dialog._tree.selection_set("PSERN")
    with mock.patch("quickprs.gui.system_wizard.messagebox") as mb:
        mb.askyesno.return_value = True
        dialog._add_system()
    dialog.destroy()
    assert app.prs.to_bytes() != before
    assert app._undo_stack.can_undo()
    with mock.patch("quickprs.gui.app.messagebox"):
        app.undo_injection()
    assert app.prs.to_bytes() == before
