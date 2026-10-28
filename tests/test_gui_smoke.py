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
    app.save_undo_snapshot("edit A")
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
