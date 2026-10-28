"""The CSV files `template-csv` writes are read by inject and fleet.

The templates put '#' comment lines under the header, which the readers
took as data: the frequencies and units readers failed on them ("could
not convert string to float: '# Example: 806.0125'") and the channels
reader imported the comment as a channel.
"""

from quickprs.cli import (
    cmd_template_csv, _parse_freq_csv, _parse_tgs_csv, _parse_conv_csv,
)
from quickprs.fleet import _parse_units_csv


def _template(tmp_path, kind, rows):
    path = tmp_path / f"{kind}.csv"
    assert cmd_template_csv(kind, str(path)) == 0
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(row + "\n" for row in rows)
    return path


def test_frequencies(tmp_path):
    path = _template(tmp_path, "frequencies",
                     ["806.0125,851.0125", "", "806.5125,851.5125"])
    assert _parse_freq_csv(path) == [(806.0125, 851.0125),
                                     (806.5125, 851.5125)]


def test_talkgroups(tmp_path):
    path = _template(tmp_path, "talkgroups",
                     ["1000,PD DISP,Police Dispatch,false,true"])
    assert _parse_tgs_csv(path) == [
        (1000, "PD DISP", "Police Dispatch", False, True)]


def test_channels(tmp_path):
    path = _template(tmp_path, "channels",
                     ["SIMPLEX,146.520,146.520,,,Simplex"])
    assert [c["short_name"] for c in _parse_conv_csv(path)] == ["SIMPLEX"]


def test_units(tmp_path):
    path = _template(tmp_path, "units", ["1001,UNIT-1001,1234"])
    assert _parse_units_csv(path) == [
        {"unit_id": 1001, "name": "UNIT-1001", "password": "1234"}]
