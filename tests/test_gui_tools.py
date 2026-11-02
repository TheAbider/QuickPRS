"""The hex viewer and the radio calculator (GUI audit findings 11, 12)."""

from unittest import mock

import pytest

tk = pytest.importorskip("tkinter")

from quickprs.gui import hex_viewer  # noqa: E402
from quickprs.gui.hex_viewer import HexViewer, byte_at_column  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    yield root
    root.destroy()


def test_byte_at_column():
    # hex part: "00 01 02 03 04 05 06 07  08 ... 0F"
    assert [byte_at_column(c) for c in (0, 1, 2, 3, 21, 22, 23)] == [
        0, 0, 0, 1, 7, 7, 7]
    assert byte_at_column(24) is None                   # the double space
    assert [byte_at_column(c) for c in (25, 26, 46, 47)] == [8, 8, 15, 15]
    assert byte_at_column(48) is None and byte_at_column(49) is None
    # ASCII part: character k is byte k (it was k - 1, and the first
    # character did nothing)
    assert [byte_at_column(50 + k) for k in range(16)] == list(range(16))
    assert byte_at_column(66) is None


def test_lines_line_up(tk_root):
    """The last, short line's ASCII column started one or two characters
    later than a full line's."""
    data = bytes(range(0x41, 0x41 + 16)) + b"QRSTUVWXY"   # 16 + 9 bytes
    for n in range(1, 17):
        viewer = HexViewer(tk_root, data[:16] + data[16:16 + n % 16])
        try:
            lines = viewer._text.get("1.0", "end").splitlines()
            full, short = lines[2], lines[3] if n % 16 else ""
            ascii_col = 10 + hex_viewer.ASCII_START
            assert full[ascii_col:] == "ABCDEFGHIJKLMNOP"
            if short:
                assert short[ascii_col:] == "QRSTUVWXY"[:n]
        finally:
            viewer.destroy()


def test_next_match_keeps_the_found_length(tk_root):
    viewer = HexViewer(tk_root, b"AB..AB..AB")
    try:
        viewer._search_mode.set("hex")
        viewer._search_var.set("0x41 0x42")
        viewer._search()
        assert viewer._search_matches == [0, 4, 8]
        viewer._search_var.set("41")         # edited, not searched again
        with mock.patch.object(viewer, "_highlight_current_match") as hl:
            viewer._next_match()
        hl.assert_called_once_with(2)
    finally:
        viewer.destroy()


@pytest.fixture
def calculator(tk_root):
    from quickprs.gui.calculator import RadioCalculator
    app = mock.Mock()
    calc = RadioCalculator(tk_root, app=app)
    yield calc
    calc.destroy()


def _rpt(calc, text):
    calc._rpt_freq_var.set(text)
    calc._calc_repeater()
    return (calc._last_rpt_result,
            str(calc._rpt_add_btn.cget("state")),
            calc._rpt_result.get("1.0", "end"))


def test_repeater_pairs_the_radio_can_tune(calculator):
    result, state, _ = _rpt(calculator, "146.94")
    assert result["input_freq"] == pytest.approx(146.34)
    assert state == "normal"
    for freq in ("223.94", "927.5"):        # 1.25 m and 33 cm
        result, state, text = _rpt(calculator, freq)
        assert result is None and state == "disabled"
        assert "cannot tune this pair" in text


def test_bad_input_clears_the_last_pair(calculator):
    _rpt(calculator, "146.94")
    result, state, text = _rpt(calculator, "abc")
    assert result is None and state == "disabled"
    assert "valid frequency" in text


def test_add_refuses_a_frequency_outside_the_bands(calculator):
    """The pair can be edited in the form before it is added."""
    from quickprs.gui import calculator as calc_module
    calc = calculator
    _rpt(calc, "146.94")
    conv = mock.Mock()
    conv.name = "RPT"
    calc.app._parse_sets.return_value = {"conv": [conv]}
    calc.app.personality_view._simple_form_dialog.return_value = [
        "RPT", "REPEATER", "927.5", "146.94", "", ""]
    with mock.patch.object(calc_module, "messagebox") as mb:
        calc._add_repeater_pair()
        assert "outside the XG-100P's bands" in mb.showerror.call_args[0][1]
    calc.app.mark_modified.assert_not_called()
