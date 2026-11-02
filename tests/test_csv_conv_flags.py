"""CONV_SET.csv carries each channel's TX, RX, scan and narrowband flags:
export-csv then import-csv made receive-only channels transmit and
narrowband channels wide."""

from quickprs.csv_export import export_conv_sets
from quickprs.csv_import import import_csv, import_conv_csv
from quickprs.injector import make_conv_set


def _flags(cset):
    return [(c.short_name, c.tx, c.rx, c.scan, c.narrowband)
            for c in cset.channels]


def test_round_trip_keeps_the_flags(tmp_path):
    cset = make_conv_set("MIX", [
        {"short_name": "NOAA 1", "tx_freq": 162.55, "tx": False},
        {"short_name": "FRS 1", "tx_freq": 462.5625, "narrowband": True},
        {"short_name": "QUIET", "tx_freq": 155.0, "scan": False},
        {"short_name": "PLAIN", "tx_freq": 156.0},
    ])
    cset.channels[3].rx = False
    path = tmp_path / "CONV_SET.csv"
    export_conv_sets(str(path), [cset])
    kind, [back] = import_csv(str(path))
    assert kind == "conv"
    assert _flags(back) == [
        ("NOAA 1", False, True, True, False),
        ("FRS 1", True, True, True, True),
        ("QUIET", True, True, False, False),
        ("PLAIN", True, False, True, False)]


def test_files_without_the_flag_columns(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("Set,ShortName,TxFreq,RxFreq,TxTone,RxTone,LongName\n"
                    "OLD,CH1,155.00000,155.00000,,,CH1\n")
    [cset] = import_conv_csv(str(path))
    assert _flags(cset) == [("CH1", True, True, True, False)]


def test_tx_and_rx_as_the_frequencies(tmp_path):
    """Without TxFreq and RxFreq columns, TX and RX are the frequencies."""
    path = tmp_path / "plain.csv"
    path.write_text("Name,TX,RX,Scan\nCH1,151.82,151.82,N\n")
    [cset] = import_conv_csv(str(path))
    ch = cset.channels[0]
    assert (ch.tx_freq, ch.rx_freq) == (151.82, 151.82)
    assert (ch.tx, ch.rx, ch.scan) == (True, True, False)
