"""Tests for CSV import module."""

import pytest
import tempfile
from pathlib import Path

from quickprs.csv_import import (
    import_csv, import_group_csv, import_trunk_csv, import_conv_csv,
)


def _write_csv(content):
    """Write CSV content to a temp file and return path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv',
                                     delete=False, encoding='utf-8')
    f.write(content)
    f.close()
    return Path(f.name)


# ─── Group CSV ───────────────────────────────────────────────────────

def test_import_group_csv_basic():
    path = _write_csv(
        "Set,GroupID,ShortName,LongName,TX,RX,Scan\n"
        "POLICE,100,PD DISP,PD DISPATCH,N,Y,Y\n"
        "POLICE,200,PD TAC1,PD TACTICAL 1,N,Y,Y\n"
        "FIRE,300,FD DISP,FD DISPATCH,N,Y,Y\n"
    )
    sets = import_group_csv(path)
    assert len(sets) == 2  # POLICE and FIRE

    police = [s for s in sets if s.name == "POLICE"][0]
    assert len(police.groups) == 2
    assert police.groups[0].group_id == 100
    assert police.groups[0].group_name == "PD DISP"
    assert police.groups[0].long_name == "PD DISPATCH"
    assert police.groups[0].scan is True
    assert police.groups[0].tx is False

    fire = [s for s in sets if s.name == "FIRE"][0]
    assert len(fire.groups) == 1
    assert fire.groups[0].group_id == 300


def test_import_group_csv_no_set_column():
    """Without Set column, all groups go into one set."""
    path = _write_csv(
        "GroupID,ShortName,LongName\n"
        "100,TG1,TALKGROUP 1\n"
        "200,TG2,TALKGROUP 2\n"
    )
    sets = import_group_csv(path)
    assert len(sets) == 1
    assert len(sets[0].groups) == 2


def test_import_group_csv_radioreference_format():
    """Handle RadioReference-style columns (Dec, Alpha Tag)."""
    path = _write_csv(
        "Dec,Alpha Tag,Description\n"
        "100,PD DISP,Police Dispatch\n"
        "200,FD DISP,Fire Dispatch\n"
    )
    data_type, objects = import_csv(path)
    assert data_type == "groups"
    assert len(objects) == 1
    assert len(objects[0].groups) == 2
    assert objects[0].groups[0].group_id == 100


# ─── Trunk CSV ───────────────────────────────────────────────────────

def test_import_trunk_csv_basic():
    path = _write_csv(
        "Set,TxFreq,RxFreq,TxMin,TxMax\n"
        "PSERN,851.01250,806.01250,136.0,870.0\n"
        "PSERN,851.26250,806.26250,136.0,870.0\n"
    )
    sets = import_trunk_csv(path)
    assert len(sets) == 1
    assert sets[0].name == "PSERN"
    assert len(sets[0].channels) == 2
    assert abs(sets[0].channels[0].tx_freq - 851.0125) < 0.001


def test_import_trunk_csv_auto_detect():
    path = _write_csv(
        "Frequency,TxFreq\n"
        "851.01250,851.01250\n"
        "852.01250,852.01250\n"
    )
    data_type, objects = import_csv(path)
    assert data_type == "trunk"


# ─── Conv CSV ────────────────────────────────────────────────────────

def test_import_conv_csv_basic():
    path = _write_csv(
        "Set,ShortName,TxFreq,RxFreq,TxTone,RxTone,LongName\n"
        "MYZONE,CH 1,462.5625,462.5625,127.3,127.3,CHANNEL ONE\n"
        "MYZONE,CH 2,462.5875,462.5875,,,,\n"
    )
    sets = import_conv_csv(path)
    assert len(sets) == 1
    assert sets[0].name == "MYZONE"
    assert len(sets[0].channels) == 2
    assert sets[0].channels[0].short_name == "CH 1"
    assert sets[0].channels[0].tx_tone == "127.3"


def test_import_conv_csv_auto_detect():
    path = _write_csv(
        "Channel,TxFreq,RxFreq\n"
        "CH1,462.5625,462.5625\n"
    )
    data_type, objects = import_csv(path)
    assert data_type == "conv"


# ─── Edge cases ──────────────────────────────────────────────────────

def test_import_empty_csv():
    path = _write_csv("")
    data_type, objects = import_csv(path)
    assert data_type == "unknown"
    assert len(objects) == 0


def test_import_unknown_format():
    path = _write_csv("Foo,Bar,Baz\n1,2,3\n")
    data_type, objects = import_csv(path)
    assert data_type == "unknown"


def test_import_name_truncation():
    """Names longer than 8/16 chars get truncated."""
    path = _write_csv(
        "GroupID,ShortName,LongName\n"
        "100,TOOLONGNAME,THIS IS WAY TOO LONG FOR SIXTEEN\n"
    )
    sets = import_group_csv(path)
    assert len(sets[0].groups[0].group_name) <= 8
    assert len(sets[0].groups[0].long_name) <= 16


def test_import_nonexistent_file():
    """Importing a missing file should raise ValueError."""
    with pytest.raises(ValueError, match="Cannot read CSV"):
        import_csv(Path("/nonexistent/file.csv"))


def test_import_group_bad_id_skipped():
    """Rows with non-integer group IDs are skipped."""
    path = _write_csv(
        "GroupID,ShortName\n"
        "abc,BAD ROW\n"
        "100,GOOD\n"
    )
    sets = import_group_csv(path)
    assert len(sets) == 1
    assert len(sets[0].groups) == 1
    assert sets[0].groups[0].group_id == 100


def test_import_trunk_bad_freq_skipped():
    """Rows with non-float frequencies are skipped."""
    path = _write_csv(
        "TxFreq,RxFreq\n"
        "abc,def\n"
        "851.01250,806.01250\n"
    )
    sets = import_trunk_csv(path)
    assert len(sets) == 1
    assert len(sets[0].channels) == 1


def test_import_trunk_bad_rx_falls_back():
    """Bad RX freq falls back to TX freq."""
    path = _write_csv(
        "TxFreq,RxFreq\n"
        "851.01250,bad\n"
    )
    sets = import_trunk_csv(path)
    assert abs(sets[0].channels[0].rx_freq - 851.0125) < 0.001


def test_import_conv_no_short_name_skipped():
    """Conv rows with no short name are skipped."""
    path = _write_csv(
        "ShortName,TxFreq\n"
        ",462.5625\n"
        "CH 1,462.5625\n"
    )
    sets = import_conv_csv(path)
    assert len(sets[0].channels) == 1
    assert sets[0].channels[0].short_name == "CH 1"


def test_import_header_only():
    """CSV with header but no data rows returns empty."""
    path = _write_csv("GroupID,ShortName,LongName\n")
    sets = import_group_csv(path)
    assert sets == []


def test_import_group_default_set_name():
    """Without Set column, set name defaults to filename stem."""
    path = _write_csv(
        "GroupID,ShortName\n"
        "100,TG1\n"
    )
    sets = import_group_csv(path)
    assert len(sets) == 1
    # Set name comes from filename stem, uppercased, truncated to 8
    assert len(sets[0].name) <= 8


def test_import_short_rows_skipped():
    """Rows shorter than needed columns are skipped."""
    path = _write_csv(
        "GroupID,ShortName,LongName\n"
        "100\n"
        "200,GOOD,GOOD NAME\n"
    )
    sets = import_group_csv(path)
    assert len(sets[0].groups) == 1
    assert sets[0].groups[0].group_id == 200


def test_import_group_missing_short_name():
    """Missing short name defaults to TG{id}."""
    path = _write_csv(
        "GroupID,ShortName\n"
        "100,\n"
    )
    sets = import_group_csv(path)
    assert sets[0].groups[0].group_name == "TG100"
