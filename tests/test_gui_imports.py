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
