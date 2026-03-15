"""Tests for third-party format export and enhanced scanner imports."""

import csv
import pytest
from pathlib import Path

from quickprs.export_formats import (
    export_chirp_csv, export_uniden_csv, export_sdrtrunk_csv,
    export_dsd_freqs, export_markdown,
)
from quickprs.scanner_import import (
    import_dsd_freqs, import_sdrtrunk_tgs, import_radiolog,
    import_chirp_csv,
)
from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Helpers ──────────────────────────────────────────────────────────

def _create_prs_with_conv(tmp_path):
    """Create a PRS file with conventional channels for testing exports."""
    from quickprs.cli import cmd_create
    from quickprs.injector import add_conv_system, make_conv_set
    from quickprs.record_types import ConvSystemConfig
    from quickprs.prs_writer import write_prs

    prs_file = tmp_path / "export_test.PRS"
    cmd_create(str(prs_file))
    prs = parse_prs(prs_file)

    channels = [
        {'short_name': 'RPT IN', 'tx_freq': 146.24, 'rx_freq': 146.84,
         'tx_tone': '100.0', 'rx_tone': '', 'long_name': 'REPEATER IN'},
        {'short_name': 'SIMPLEX', 'tx_freq': 146.52, 'rx_freq': 146.52,
         'tx_tone': '100.0', 'rx_tone': '100.0', 'long_name': 'SIMPLEX CH'},
        {'short_name': 'NOAA', 'tx_freq': 162.55, 'rx_freq': 162.55,
         'tx_tone': '', 'rx_tone': '', 'long_name': 'NOAA WX'},
        {'short_name': 'DTCS CH', 'tx_freq': 462.5625, 'rx_freq': 462.5625,
         'tx_tone': 'D023', 'rx_tone': 'D023', 'long_name': 'DTCS TEST'},
    ]
    conv_set = make_conv_set("TEST", channels)
    config = ConvSystemConfig(
        system_name="TEST",
        long_name="TEST CONV",
        conv_set_name="TEST",
    )
    add_conv_system(prs, config, conv_set=conv_set)
    write_prs(prs, str(prs_file))
    return prs_file


def _create_prs_with_p25(tmp_path):
    """Create a PRS file with P25 trunked system for testing exports."""
    from quickprs.cli import cmd_create
    from quickprs.injector import (
        add_p25_trunked_system, make_p25_group,
        make_trunk_set, make_group_set,
    )
    from quickprs.record_types import P25TrkSystemConfig, TrunkSet, TrunkChannel
    from quickprs.prs_writer import write_prs

    prs_file = tmp_path / "p25_test.PRS"
    cmd_create(str(prs_file))
    prs = parse_prs(prs_file)

    config = P25TrkSystemConfig(
        system_name="COUNTY", long_name="COUNTY PUBLIC SAFETY",
        trunk_set_name="COUNTY", group_set_name="COUNTY",
        wan_name="COUNTY", system_id=892, wacn=1,
    )
    ts = make_trunk_set("COUNTY", [
        (851.0125, 851.0125),
        (851.2625, 851.2625),
        (851.5125, 851.5125),
    ])
    gs = make_group_set("COUNTY", [
        (100, "PD DISP", "PD DISPATCH"),
        (200, "PD TAC", "PD TACTICAL"),
        (300, "FD DISP", "FD DISPATCH"),
    ])
    add_p25_trunked_system(prs, config, trunk_set=ts, group_set=gs)
    write_prs(prs, str(prs_file))
    return prs_file


# ═══════════════════════════════════════════════════════════════════════
# CHIRP CSV Export
# ═══════════════════════════════════════════════════════════════════════


class TestChirpExport:
    """Test CHIRP CSV export."""

    def test_chirp_export_basic(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        count = export_chirp_csv(prs, out)
        # 4 TEST channels + 1 default "Conv 1" channel = 5
        assert count == 5
        assert out.exists()

    def test_chirp_export_columns(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            required = {"Location", "Name", "Frequency", "Duplex",
                        "Offset", "Tone", "rToneFreq", "cToneFreq",
                        "DtcsCode", "DtcsPolarity", "Mode"}
            assert required.issubset(set(reader.fieldnames))

    def test_chirp_export_duplex_minus(self, tmp_path):
        """RPT IN: TX=146.24, RX=146.84 -> Duplex='-', Offset=0.6."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        rpt = [r for r in rows if r['Name'] == 'RPT IN'][0]
        assert rpt['Duplex'] == '-'
        assert abs(float(rpt['Offset']) - 0.6) < 0.001
        assert abs(float(rpt['Frequency']) - 146.84) < 0.001

    def test_chirp_export_simplex(self, tmp_path):
        """NOAA: TX=RX -> Duplex=''."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        noaa = [r for r in rows if r['Name'] == 'NOAA'][0]
        assert noaa['Duplex'] == ''

    def test_chirp_export_tone_mode(self, tmp_path):
        """RPT IN has TX tone only -> Tone='Tone'."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        rpt = [r for r in rows if r['Name'] == 'RPT IN'][0]
        assert rpt['Tone'] == 'Tone'
        assert rpt['rToneFreq'] == '100.0'

    def test_chirp_export_tsql_mode(self, tmp_path):
        """SIMPLEX has both TX and RX tone -> Tone='TSQL'."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        simplex = [r for r in rows if r['Name'] == 'SIMPLEX'][0]
        assert simplex['Tone'] == 'TSQL'

    def test_chirp_export_dtcs_mode(self, tmp_path):
        """DTCS CH has DCS tone -> Tone='DTCS'."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        dtcs = [r for r in rows if r['Name'] == 'DTCS CH'][0]
        assert dtcs['Tone'] == 'DTCS'
        assert dtcs['DtcsCode'] == '023'

    def test_chirp_export_no_tone(self, tmp_path):
        """NOAA has no tones -> Tone=''."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        noaa = [r for r in rows if r['Name'] == 'NOAA'][0]
        assert noaa['Tone'] == ''

    def test_chirp_export_sequential_locations(self, tmp_path):
        """Location numbers should be sequential starting at 0."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        export_chirp_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        locs = [int(r['Location']) for r in rows]
        assert locs == list(range(len(rows)))

    def test_chirp_export_default_prs(self, tmp_path):
        """Export from default PRS (1 default conv channel)."""
        from quickprs.cli import cmd_create
        prs_file = tmp_path / "default.PRS"
        cmd_create(str(prs_file))
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        count = export_chirp_csv(prs, out)
        assert count == 1  # blank PRS has one default channel

    def test_chirp_export_with_set_filter(self, tmp_path):
        """Filter by set name."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        count = export_chirp_csv(prs, out, sets=["TEST"])
        assert count == 4

    def test_chirp_export_with_nonexistent_set(self, tmp_path):
        """Filtering for nonexistent set returns 0."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "chirp.csv"
        count = export_chirp_csv(prs, out, sets=["NOPE"])
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════
# Uniden CSV Export
# ═══════════════════════════════════════════════════════════════════════


class TestUnidenExport:
    """Test Uniden Sentinel CSV export."""

    def test_uniden_export_basic(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        count = export_uniden_csv(prs, out)
        assert count == 5  # 4 + 1 default
        assert out.exists()

    def test_uniden_export_columns(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        export_uniden_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            required = {"System", "Department", "Channel", "Frequency",
                        "Modulation", "Tone"}
            assert required.issubset(set(reader.fieldnames))

    def test_uniden_export_frequency(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        export_uniden_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        noaa = [r for r in rows if r['Channel'] == 'NOAA'][0]
        assert abs(float(noaa['Frequency']) - 162.55) < 0.001

    def test_uniden_export_tone(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        export_uniden_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        rpt = [r for r in rows if r['Channel'] == 'RPT IN'][0]
        assert rpt['Tone'] == '100.0'

    def test_uniden_export_dcs_code(self, tmp_path):
        """DCS tone should go in Code column, not Tone."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        export_uniden_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        dtcs = [r for r in rows if r['Channel'] == 'DTCS CH'][0]
        assert dtcs['Code'] == '023'
        assert dtcs['Tone'] == ''

    def test_uniden_export_system_name(self, tmp_path):
        """System column should contain set name."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        export_uniden_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Each row's System should match its set name
        systems = {r['System'] for r in rows}
        assert 'TEST' in systems

    def test_uniden_export_default_prs(self, tmp_path):
        from quickprs.cli import cmd_create
        prs_file = tmp_path / "default.PRS"
        cmd_create(str(prs_file))
        prs = parse_prs(prs_file)
        out = tmp_path / "uniden.csv"
        count = export_uniden_csv(prs, out)
        assert count == 1  # blank PRS has one default channel


# ═══════════════════════════════════════════════════════════════════════
# SDRTrunk CSV Export
# ═══════════════════════════════════════════════════════════════════════


class TestSdrtrunkExport:
    """Test SDRTrunk talkgroup CSV export."""

    def test_sdrtrunk_export_basic(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        count = export_sdrtrunk_csv(prs, out)
        assert count == 3
        assert out.exists()

    def test_sdrtrunk_export_columns(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        export_sdrtrunk_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            required = {"Decimal", "Hex", "Alpha Tag", "Mode",
                        "Description", "Tag", "Category"}
            assert required.issubset(set(reader.fieldnames))

    def test_sdrtrunk_export_tg_id(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        export_sdrtrunk_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        ids = [int(r['Decimal']) for r in rows]
        assert 100 in ids
        assert 200 in ids
        assert 300 in ids

    def test_sdrtrunk_export_hex(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        export_sdrtrunk_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        pd_disp = [r for r in rows if r['Decimal'] == '100'][0]
        assert pd_disp['Hex'] == '0064'

    def test_sdrtrunk_export_alpha_tag(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        export_sdrtrunk_csv(prs, out)

        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        tags = [r['Alpha Tag'] for r in rows]
        assert 'PD DISP' in tags

    def test_sdrtrunk_export_default_prs(self, tmp_path):
        """Default PRS has no P25 talkgroups."""
        from quickprs.cli import cmd_create
        prs_file = tmp_path / "default.PRS"
        cmd_create(str(prs_file))
        prs = parse_prs(prs_file)
        out = tmp_path / "talkgroups.csv"
        count = export_sdrtrunk_csv(prs, out)
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════
# DSD+ Frequency Export
# ═══════════════════════════════════════════════════════════════════════


class TestDsdExport:
    """Test DSD+ frequency list export."""

    def test_dsd_export_basic(self, tmp_path):
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "freqs.txt"
        count = export_dsd_freqs(prs, out)
        assert count == 3
        assert out.exists()

    def test_dsd_export_format(self, tmp_path):
        """Each line should be a frequency in Hz."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "freqs.txt"
        export_dsd_freqs(prs, out)

        lines = out.read_text().strip().split('\n')
        assert len(lines) == 3
        for line in lines:
            freq = int(line.strip())
            assert freq > 0

    def test_dsd_export_values(self, tmp_path):
        """Frequencies should be in Hz (MHz * 1e6)."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "freqs.txt"
        export_dsd_freqs(prs, out)

        lines = out.read_text().strip().split('\n')
        freqs = sorted([int(line.strip()) for line in lines])
        assert 851012500 in freqs
        assert 851262500 in freqs
        assert 851512500 in freqs

    def test_dsd_export_sorted_deduped(self, tmp_path):
        """Frequencies should be sorted and unique."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "freqs.txt"
        export_dsd_freqs(prs, out)

        lines = out.read_text().strip().split('\n')
        freqs = [int(line.strip()) for line in lines]
        assert freqs == sorted(set(freqs))

    def test_dsd_export_default_prs(self, tmp_path):
        """Default PRS has no trunk frequencies."""
        from quickprs.cli import cmd_create
        prs_file = tmp_path / "default.PRS"
        cmd_create(str(prs_file))
        prs = parse_prs(prs_file)
        out = tmp_path / "freqs.txt"
        count = export_dsd_freqs(prs, out)
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════
# Markdown Export
# ═══════════════════════════════════════════════════════════════════════


class TestMarkdownExport:
    """Test Markdown export."""

    def test_markdown_export_returns_string(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_markdown_export_writes_file(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        out = tmp_path / "config.md"
        export_markdown(prs, out)
        assert out.exists()
        assert len(out.read_text()) > 0

    def test_markdown_export_has_header(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert md.startswith('#')

    def test_markdown_export_conv_channels(self, tmp_path):
        """Should include conventional channel table."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert 'Conventional Channels' in md
        assert 'RPT IN' in md
        assert 'SIMPLEX' in md
        assert 'NOAA' in md

    def test_markdown_export_talkgroups(self, tmp_path):
        """Should include talkgroup table for P25 systems."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert 'Talkgroups' in md
        assert 'PD DISP' in md

    def test_markdown_export_frequencies(self, tmp_path):
        """Should include trunk frequency table for P25 systems."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert 'Trunk Frequencies' in md
        assert '851.0125' in md

    def test_markdown_export_file_info(self, tmp_path):
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert 'File Information' in md
        assert 'Size' in md

    def test_markdown_export_empty_prs(self, tmp_path):
        """Even empty PRS should produce valid markdown."""
        from quickprs.cli import cmd_create
        prs_file = tmp_path / "empty.PRS"
        cmd_create(str(prs_file))
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        assert '#' in md  # has a header
        assert 'File Information' in md

    def test_markdown_tables_well_formed(self, tmp_path):
        """Table rows should have consistent pipe characters."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        md = export_markdown(prs)
        for line in md.split('\n'):
            if '|' in line and not line.startswith('#'):
                # Table rows start and end with |
                stripped = line.strip()
                assert stripped.startswith('|')
                assert stripped.endswith('|')


# ═══════════════════════════════════════════════════════════════════════
# DSD+ Frequency Import
# ═══════════════════════════════════════════════════════════════════════


class TestDsdImport:
    """Test DSD+ frequency list import."""

    def test_import_dsd_basic(self, tmp_path):
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500\n851262500\n851512500\n")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 3

    def test_import_dsd_frequencies(self, tmp_path):
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500\n")
        channels = import_dsd_freqs(str(dsd))
        assert abs(channels[0]['tx_freq'] - 851.0125) < 0.0001

    def test_import_dsd_comments(self, tmp_path):
        """Lines starting with # should be skipped."""
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("# This is a comment\n851012500\n# Another\n")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 1

    def test_import_dsd_blank_lines(self, tmp_path):
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("\n851012500\n\n851262500\n\n")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 2

    def test_import_dsd_trailing_comments(self, tmp_path):
        """Values with trailing labels after whitespace."""
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500 Site1\n851262500 Site2\n")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 2

    def test_import_dsd_channel_names(self, tmp_path):
        """Channels should get F1, F2, etc. short names."""
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500\n851262500\n")
        channels = import_dsd_freqs(str(dsd))
        assert channels[0]['short_name'] == 'F1'
        assert channels[1]['short_name'] == 'F2'

    def test_import_dsd_empty_file(self, tmp_path):
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 0

    def test_import_dsd_invalid_lines(self, tmp_path):
        """Invalid lines should be skipped."""
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500\nnotanumber\n851262500\n")
        channels = import_dsd_freqs(str(dsd))
        assert len(channels) == 2

    def test_import_dsd_dict_keys(self, tmp_path):
        """Channel dicts should have required keys."""
        dsd = tmp_path / "freqs.txt"
        dsd.write_text("851012500\n")
        channels = import_dsd_freqs(str(dsd))
        required = {'short_name', 'tx_freq', 'rx_freq',
                     'tx_tone', 'rx_tone', 'long_name'}
        assert required.issubset(channels[0].keys())


# ═══════════════════════════════════════════════════════════════════════
# SDRTrunk Talkgroup Import
# ═══════════════════════════════════════════════════════════════════════


class TestSdrtrunkTgImport:
    """Test SDRTrunk talkgroup CSV import."""

    def test_import_sdrtrunk_tgs_basic(self, tmp_path):
        tg_csv = tmp_path / "talkgroups.csv"
        tg_csv.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n"
            "100,0064,PD DISP,D,PD Dispatch,Law Dispatch,County PD\n"
            "200,00C8,FD DISP,D,FD Dispatch,Fire Dispatch,County FD\n")
        tgs = import_sdrtrunk_tgs(str(tg_csv))
        assert len(tgs) == 2

    def test_import_sdrtrunk_tgs_fields(self, tmp_path):
        tg_csv = tmp_path / "talkgroups.csv"
        tg_csv.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n"
            "100,0064,PD DISP,D,PD Dispatch,Law Dispatch,County PD\n")
        tgs = import_sdrtrunk_tgs(str(tg_csv))
        assert tgs[0]['group_id'] == 100
        assert tgs[0]['short_name'] == 'PD DISP'
        assert 'PD DISPATCH' in tgs[0]['long_name']

    def test_import_sdrtrunk_tgs_truncation(self, tmp_path):
        """Short names should be max 8 chars."""
        tg_csv = tmp_path / "talkgroups.csv"
        tg_csv.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n"
            "100,0064,VERY LONG ALPHA TAG,D,Description,Tag,Cat\n")
        tgs = import_sdrtrunk_tgs(str(tg_csv))
        assert len(tgs[0]['short_name']) <= 8
        assert len(tgs[0]['long_name']) <= 16

    def test_import_sdrtrunk_tgs_empty(self, tmp_path):
        tg_csv = tmp_path / "talkgroups.csv"
        tg_csv.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n")
        tgs = import_sdrtrunk_tgs(str(tg_csv))
        assert len(tgs) == 0

    def test_import_sdrtrunk_tgs_invalid_id(self, tmp_path):
        """Non-numeric IDs should be skipped."""
        tg_csv = tmp_path / "talkgroups.csv"
        tg_csv.write_text(
            "Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category\n"
            "abc,0064,Test,D,Test,Tag,Cat\n"
            "100,0064,Valid,D,Valid,Tag,Cat\n")
        tgs = import_sdrtrunk_tgs(str(tg_csv))
        assert len(tgs) == 1


# ═══════════════════════════════════════════════════════════════════════
# RadioLog Import
# ═══════════════════════════════════════════════════════════════════════


class TestRadioLogImport:
    """Test RadioLog CSV import."""

    def test_import_radiolog_basic(self, tmp_path):
        log = tmp_path / "log.csv"
        log.write_text(
            "Date,Time,Frequency,Mode,Description\n"
            "2024-01-01,12:00,460.050,NFM,PD Dispatch\n"
            "2024-01-01,12:05,460.125,NFM,PD Tactical\n")
        channels = import_radiolog(str(log))
        assert len(channels) == 2

    def test_import_radiolog_frequencies(self, tmp_path):
        log = tmp_path / "log.csv"
        log.write_text(
            "Date,Time,Frequency,Mode,Description\n"
            "2024-01-01,12:00,460.050,NFM,PD Dispatch\n")
        channels = import_radiolog(str(log))
        assert abs(channels[0]['tx_freq'] - 460.050) < 0.001

    def test_import_radiolog_hz_conversion(self, tmp_path):
        """Frequencies > 1000 should be treated as Hz."""
        log = tmp_path / "log.csv"
        log.write_text(
            "Date,Time,Frequency,Mode,Description\n"
            "2024-01-01,12:00,460050000,NFM,PD Dispatch\n")
        channels = import_radiolog(str(log))
        assert abs(channels[0]['tx_freq'] - 460.050) < 0.001

    def test_import_radiolog_dedup(self, tmp_path):
        """Duplicate frequencies should be skipped."""
        log = tmp_path / "log.csv"
        log.write_text(
            "Date,Time,Frequency,Mode,Description\n"
            "2024-01-01,12:00,460.050,NFM,First\n"
            "2024-01-01,12:05,460.050,NFM,Duplicate\n"
            "2024-01-01,12:10,460.125,NFM,Second\n")
        channels = import_radiolog(str(log))
        assert len(channels) == 2

    def test_import_radiolog_empty(self, tmp_path):
        log = tmp_path / "log.csv"
        log.write_text("Date,Time,Frequency,Mode,Description\n")
        channels = import_radiolog(str(log))
        assert len(channels) == 0

    def test_import_radiolog_names(self, tmp_path):
        log = tmp_path / "log.csv"
        log.write_text(
            "Date,Time,Frequency,Mode,Description\n"
            "2024-01-01,12:00,460.050,NFM,PD Dispatch\n")
        channels = import_radiolog(str(log))
        assert channels[0]['short_name'] == 'PD DISPA'


# ═══════════════════════════════════════════════════════════════════════
# Round-trip: Export CHIRP -> Import CHIRP -> Compare
# ═══════════════════════════════════════════════════════════════════════


class TestExportImportRoundtrip:
    """Verify CHIRP export -> import produces consistent channel data."""

    def test_chirp_roundtrip_channel_count(self, tmp_path):
        """Export to CHIRP, reimport, verify same number of channels."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        csv_path = tmp_path / "roundtrip.csv"

        # Export (5 = 4 TEST + 1 default)
        count = export_chirp_csv(prs, csv_path)
        assert count == 5

        # Re-import
        channels = import_chirp_csv(str(csv_path))
        assert len(channels) == count

    def test_chirp_roundtrip_channel_names(self, tmp_path):
        """Channel names should survive round-trip."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        csv_path = tmp_path / "roundtrip.csv"

        export_chirp_csv(prs, csv_path)
        channels = import_chirp_csv(str(csv_path))

        names = {ch['short_name'] for ch in channels}
        assert 'RPT IN' in names
        assert 'SIMPLEX' in names
        assert 'NOAA' in names

    def test_chirp_roundtrip_frequencies(self, tmp_path):
        """Frequencies should survive round-trip within tolerance."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        csv_path = tmp_path / "roundtrip.csv"

        export_chirp_csv(prs, csv_path)
        channels = import_chirp_csv(str(csv_path))

        noaa = [ch for ch in channels if ch['short_name'] == 'NOAA'][0]
        assert abs(noaa['rx_freq'] - 162.55) < 0.001
        assert abs(noaa['tx_freq'] - 162.55) < 0.001

    def test_chirp_roundtrip_duplex(self, tmp_path):
        """Duplex offset should survive round-trip."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        csv_path = tmp_path / "roundtrip.csv"

        export_chirp_csv(prs, csv_path)
        channels = import_chirp_csv(str(csv_path))

        rpt_in = [ch for ch in channels if ch['short_name'] == 'RPT IN'][0]
        # Original: TX=146.24, RX=146.84
        assert abs(rpt_in['rx_freq'] - 146.84) < 0.001
        assert abs(rpt_in['tx_freq'] - 146.24) < 0.001

    def test_chirp_roundtrip_tones(self, tmp_path):
        """Tone mode should survive round-trip."""
        prs_file = _create_prs_with_conv(tmp_path)
        prs = parse_prs(prs_file)
        csv_path = tmp_path / "roundtrip.csv"

        export_chirp_csv(prs, csv_path)
        channels = import_chirp_csv(str(csv_path))

        rpt_in = [ch for ch in channels if ch['short_name'] == 'RPT IN'][0]
        assert rpt_in['tx_tone'] == '100.0'

        simplex = [ch for ch in channels
                    if ch['short_name'] == 'SIMPLEX'][0]
        assert simplex['tx_tone'] == '100.0'
        assert simplex['rx_tone'] == '100.0'

    def test_dsd_roundtrip(self, tmp_path):
        """Export DSD+ freqs, reimport, verify same frequency count."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        freq_path = tmp_path / "freqs.txt"

        count = export_dsd_freqs(prs, freq_path)
        channels = import_dsd_freqs(str(freq_path))
        assert len(channels) == count

    def test_dsd_roundtrip_frequencies(self, tmp_path):
        """DSD+ frequencies should survive round-trip within tolerance."""
        prs_file = _create_prs_with_p25(tmp_path)
        prs = parse_prs(prs_file)
        freq_path = tmp_path / "freqs.txt"

        export_dsd_freqs(prs, freq_path)
        channels = import_dsd_freqs(str(freq_path))

        freqs = sorted([ch['tx_freq'] for ch in channels])
        assert abs(freqs[0] - 851.0125) < 0.001


# ═══════════════════════════════════════════════════════════════════════
# CLI Export Commands
# ═══════════════════════════════════════════════════════════════════════


class TestCliExport:
    """Test the export CLI command."""

    def test_cli_export_chirp(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_conv(tmp_path)
        out = tmp_path / "chirp.csv"

        result = run_cli(["export", str(prs_file), "chirp",
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "CHIRP CSV" in out_text

    def test_cli_export_uniden(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_conv(tmp_path)
        out = tmp_path / "uniden.csv"

        result = run_cli(["export", str(prs_file), "uniden",
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "Uniden CSV" in out_text

    def test_cli_export_sdrtrunk(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_p25(tmp_path)
        out = tmp_path / "tgs.csv"

        result = run_cli(["export", str(prs_file), "sdrtrunk",
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "SDRTrunk CSV" in out_text

    def test_cli_export_dsd(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_p25(tmp_path)
        out = tmp_path / "freqs.txt"

        result = run_cli(["export", str(prs_file), "dsd",
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "DSD+" in out_text

    def test_cli_export_markdown(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_conv(tmp_path)
        out = tmp_path / "config.md"

        result = run_cli(["export", str(prs_file), "markdown",
                          "-o", str(out)])
        assert result == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "Markdown" in out_text

    def test_cli_export_with_sets_filter(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        prs_file = _create_prs_with_conv(tmp_path)
        out = tmp_path / "filtered.csv"

        result = run_cli(["export", str(prs_file), "chirp",
                          "-o", str(out), "--sets", "TEST"])
        assert result == 0
        assert out.exists()
        # Verify only TEST set channels were exported (not "Conv 1")
        with open(out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 4

    def test_cli_export_auto_output_name(self, capsys, tmp_path):
        """Without -o, should auto-name the output file."""
        from quickprs.cli import run_cli
        import os
        prs_file = _create_prs_with_conv(tmp_path)

        # cd into tmp_path so auto-named file lands there
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = run_cli(["export", str(prs_file), "chirp"])
            assert result == 0
        finally:
            os.chdir(orig)

    def test_cli_export_nonexistent_file(self, capsys, tmp_path):
        from quickprs.cli import run_cli
        result = run_cli(["export", str(tmp_path / "nope.PRS"), "chirp",
                          "-o", str(tmp_path / "out.csv")])
        assert result == 1


# ═══════════════════════════════════════════════════════════════════════
# Export from real PRS files
# ═══════════════════════════════════════════════════════════════════════


class TestExportRealFiles:
    """Test exports using testdata PRS files."""

    def test_chirp_export_paws(self, tmp_path):
        """Export PAWS PRS to CHIRP CSV — should not crash."""
        if not PAWS.exists():
            pytest.skip("testdata not available")
        prs = cached_parse_prs(PAWS)
        out = tmp_path / "chirp.csv"
        count = export_chirp_csv(prs, out)
        # May be 0 if PAWS has no conv channels — that's fine
        assert count >= 0
        assert out.exists()

    def test_markdown_export_paws(self, tmp_path):
        """Export PAWS PRS to Markdown — should not crash."""
        if not PAWS.exists():
            pytest.skip("testdata not available")
        prs = cached_parse_prs(PAWS)
        md = export_markdown(prs)
        assert '#' in md
        assert 'File Information' in md

    def test_sdrtrunk_export_paws(self, tmp_path):
        """Export PAWS PRS to SDRTrunk — should not crash."""
        if not PAWS.exists():
            pytest.skip("testdata not available")
        prs = cached_parse_prs(PAWS)
        out = tmp_path / "tgs.csv"
        count = export_sdrtrunk_csv(prs, out)
        assert count >= 0

    def test_dsd_export_paws(self, tmp_path):
        """Export PAWS PRS to DSD+ — should not crash."""
        if not PAWS.exists():
            pytest.skip("testdata not available")
        prs = cached_parse_prs(PAWS)
        out = tmp_path / "freqs.txt"
        count = export_dsd_freqs(prs, out)
        assert count >= 0
