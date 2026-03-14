"""Tests for CLI set-option and batch (multi-file) operations."""

import pytest
import shutil
import tempfile
from pathlib import Path

from quickprs.cli import run_cli, cmd_info, cmd_validate, cmd_set_option
from quickprs.prs_parser import parse_prs
from quickprs.option_maps import (
    extract_platform_config, extract_platform_xml,
    find_platform_xml_location, set_platform_option,
    list_platform_options, SECTION_MAP,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"
NEW_RADIO = TESTDATA / "every option" / "new radio - xg 100 portable .PRS"


def _copy_prs(src, tmp_path, name="test.PRS"):
    """Copy a PRS file to tmp_path for modification."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


# ─── set_platform_option (option_maps.py) ────────────────────────────


class TestSetPlatformOption:
    """Test the set_platform_option function directly."""

    def test_set_gps_mode(self, tmp_path):
        """Set gpsConfig.gpsMode from ON to OFF."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'ON'

        set_platform_option(prs, 'gps', 'gpsMode', 'OFF')
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'OFF'

    def test_set_gps_type(self, tmp_path):
        """Set gpsConfig.type to EXTERNAL_GPS."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'gps', 'type', 'EXTERNAL_GPS')
        config = extract_platform_config(prs)
        assert config['gpsConfig']['type'] == 'EXTERNAL_GPS'

    def test_set_misc_password(self, tmp_path):
        """Set miscConfig.password to a numeric string."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'misc', 'password', '1234')
        config = extract_platform_config(prs)
        assert config['miscConfig']['password'] == '1234'

    def test_set_bluetooth_mode(self, tmp_path):
        """Toggle bluetoothConfig.btMode."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'bluetooth', 'btMode', 'ON')
        config = extract_platform_config(prs)
        assert config['bluetoothConfig']['btMode'] == 'ON'

    def test_set_audio_cct_timer(self, tmp_path):
        """Set audioConfig.cctTimer."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'audio', 'cctTimer', '60')
        config = extract_platform_config(prs)
        assert config['audioConfig']['cctTimer'] == '60'

    def test_set_timedate_zone(self, tmp_path):
        """Set TimeDateCfg.zone."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'timedate', 'zone', 'EST')
        config = extract_platform_config(prs)
        assert config['TimeDateCfg']['zone'] == 'EST'

    def test_set_display_brightness(self, tmp_path):
        """Set miscConfig.topFpIntensity via display section alias."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'display', 'topFpIntensity', '7')
        config = extract_platform_config(prs)
        assert config['miscConfig']['topFpIntensity'] == '7'

    def test_set_mandown_sensitivity(self, tmp_path):
        """Set manDownConfig.sensitivity."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'mandown', 'sensitivity', '3')
        config = extract_platform_config(prs)
        assert config['manDownConfig']['sensitivity'] == '3'

    def test_set_accessory_ptt_mode(self, tmp_path):
        """Set accessoryConfig.pttMode."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'accessory', 'pttMode', 'ANY')
        config = extract_platform_config(prs)
        assert config['accessoryConfig']['pttMode'] == 'ANY'

    def test_set_option_xml_element_name(self, tmp_path):
        """Use XML element name directly instead of friendly name."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'gpsConfig', 'gpsMode', 'OFF')
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'OFF'

    def test_set_option_no_xml_auto_creates(self):
        """Setting an option on a file without XML should auto-create it."""
        prs = parse_prs(str(CLAUDE))
        result = set_platform_option(prs, 'gps', 'gpsMode', 'ON')
        assert result is True
        # Verify XML was created
        config = extract_platform_config(prs)
        assert config is not None
        assert config['gpsConfig']['gpsMode'] == 'ON'

    def test_set_option_bad_section_raises(self, tmp_path):
        """Setting an option with invalid section should raise."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        with pytest.raises(ValueError, match="not found"):
            set_platform_option(prs, 'nonexistent', 'foo', 'bar')

    def test_xml_length_prefix_updated(self, tmp_path):
        """Verify uint16 LE length prefix is updated when XML changes."""
        import struct
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)

        # Set a value that changes the XML length
        set_platform_option(prs, 'bluetooth', 'friendlyName',
                            'A_VERY_LONG_NAME_FOR_TESTING')

        loc = find_platform_xml_location(prs)
        sec = prs.sections[loc[0]]
        xml_start = loc[1]
        xml_str = extract_platform_xml(prs)
        xml_len = len(xml_str.encode('ascii'))
        stored_len = struct.unpack('<H', sec.raw[xml_start-2:xml_start])[0]
        assert stored_len == xml_len

    def test_set_option_roundtrip(self, tmp_path):
        """Modify, save, reload, verify the change persists."""
        from quickprs.prs_writer import write_prs

        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'gps', 'gpsMode', 'OFF')
        write_prs(prs, path)

        prs2 = parse_prs(path)
        config = extract_platform_config(prs2)
        assert config['gpsConfig']['gpsMode'] == 'OFF'

    def test_multiple_set_options(self, tmp_path):
        """Set multiple options sequentially."""
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        set_platform_option(prs, 'gps', 'gpsMode', 'OFF')
        set_platform_option(prs, 'audio', 'speakerMode', 'OFF')
        set_platform_option(prs, 'timedate', 'zone', 'PST')

        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'OFF'
        assert config['audioConfig']['speakerMode'] == 'OFF'
        assert config['TimeDateCfg']['zone'] == 'PST'

    def test_new_radio_baseline(self, tmp_path):
        """Set option on the new radio baseline file."""
        path = _copy_prs(NEW_RADIO, tmp_path)
        prs = parse_prs(path)
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'ON'

        set_platform_option(prs, 'gps', 'gpsMode', 'OFF')
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'OFF'


# ─── list_platform_options ───────────────────────────────────────────


class TestListPlatformOptions:
    """Test the list_platform_options function."""

    def test_list_returns_options(self):
        """List should return options for a file with XML."""
        prs = parse_prs(str(PAWS))
        opts = list_platform_options(prs)
        assert len(opts) > 0
        # Each tuple is (friendly, element, attr, value)
        for friendly, element, attr, val in opts:
            assert isinstance(friendly, str)
            assert isinstance(attr, str)

    def test_list_empty_for_no_xml(self):
        """List should return [] for a file without XML."""
        prs = parse_prs(str(CLAUDE))
        opts = list_platform_options(prs)
        assert opts == []

    def test_list_contains_gps(self):
        """List should include GPS settings."""
        prs = parse_prs(str(PAWS))
        opts = list_platform_options(prs)
        gps_attrs = [attr for f, e, attr, v in opts if 'gps' in f]
        assert 'gpsMode' in gps_attrs

    def test_list_contains_audio(self):
        """List should include audio settings."""
        prs = parse_prs(str(PAWS))
        opts = list_platform_options(prs)
        audio_attrs = [attr for f, e, attr, v in opts if 'audio' in f]
        assert 'speakerMode' in audio_attrs

    def test_list_contains_bluetooth(self):
        """List should include bluetooth settings."""
        prs = parse_prs(str(PAWS))
        opts = list_platform_options(prs)
        bt_attrs = [attr for f, e, attr, v in opts if 'bluetooth' in f]
        assert 'btMode' in bt_attrs

    def test_list_contains_timedate(self):
        """List should include time/date settings."""
        prs = parse_prs(str(PAWS))
        opts = list_platform_options(prs)
        td_attrs = [attr for f, e, attr, v in opts if 'timedate' in f]
        assert 'zone' in td_attrs


# ─── cmd_set_option (cli.py) ─────────────────────────────────────────


class TestCmdSetOption:
    """Test the set-option CLI command."""

    def test_list_flag(self, capsys, tmp_path):
        """--list should print options and return 0."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path, list_opts=True)
        assert result == 0
        out = capsys.readouterr().out
        assert 'gpsMode' in out
        assert 'speakerMode' in out

    def test_list_no_xml(self, capsys):
        """--list on file without XML should return 1."""
        result = cmd_set_option(str(CLAUDE), list_opts=True)
        assert result == 1

    def test_read_option(self, capsys, tmp_path):
        """Reading an option should print section.attr = value."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path, option_path='gps.gpsMode')
        assert result == 0
        out = capsys.readouterr().out
        assert 'gps.gpsMode = ON' in out

    def test_set_option(self, capsys, tmp_path):
        """Setting an option should modify and save."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path, option_path='gps.gpsMode',
                                value='OFF')
        assert result == 0
        out = capsys.readouterr().out
        assert 'Set gps.gpsMode = OFF' in out

        # Verify it was saved
        prs = parse_prs(path)
        config = extract_platform_config(prs)
        assert config['gpsConfig']['gpsMode'] == 'OFF'

    def test_set_option_to_output(self, capsys, tmp_path):
        """Setting with -o should write to a different file."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        dst = str(tmp_path / "dest.PRS")
        result = cmd_set_option(src, option_path='gps.gpsMode',
                                value='OFF', output=dst)
        assert result == 0

        # Source unchanged, dest has new value
        prs_src = parse_prs(src)
        assert extract_platform_config(prs_src)['gpsConfig']['gpsMode'] == 'ON'
        prs_dst = parse_prs(dst)
        assert extract_platform_config(prs_dst)['gpsConfig']['gpsMode'] == 'OFF'

    def test_bad_option_path(self, capsys, tmp_path):
        """Invalid option path should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path, option_path='nodotshere')
        assert result == 1

    def test_bad_section(self, capsys, tmp_path):
        """Invalid section should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path, option_path='bad.attr',
                                value='foo')
        assert result == 1

    def test_no_xml_auto_creates(self, capsys, tmp_path):
        """Setting on file without XML should auto-create default XML."""
        path = _copy_prs(CLAUDE, tmp_path)
        result = cmd_set_option(path, option_path='gps.gpsMode',
                                value='ON')
        assert result == 0
        # Verify XML was created and option was set
        prs = parse_prs(path)
        config = extract_platform_config(prs)
        assert config is not None
        assert config['gpsConfig']['gpsMode'] == 'ON'

    def test_no_option_no_list(self, capsys, tmp_path):
        """No option path and no --list should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_set_option(path)
        assert result == 1


# ─── run_cli set-option dispatch ─────────────────────────────────────


class TestRunCliSetOption:
    """Test set-option via run_cli dispatcher."""

    def test_dispatch_list(self, capsys, tmp_path):
        """run_cli set-option --list should work."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["set-option", path, "--list"])
        assert result == 0
        out = capsys.readouterr().out
        assert 'gpsMode' in out

    def test_dispatch_read(self, capsys, tmp_path):
        """run_cli set-option <file> gps.gpsMode (read)."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["set-option", path, "gps.gpsMode"])
        assert result == 0
        out = capsys.readouterr().out
        assert 'gps.gpsMode' in out

    def test_dispatch_set(self, capsys, tmp_path):
        """run_cli set-option <file> gps.gpsMode OFF (set)."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["set-option", path, "gps.gpsMode", "OFF"])
        assert result == 0
        out = capsys.readouterr().out
        assert 'Set gps.gpsMode = OFF' in out

    def test_dispatch_with_output(self, capsys, tmp_path):
        """run_cli set-option with -o flag."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        dst = str(tmp_path / "output.PRS")
        result = run_cli(["set-option", src, "gps.gpsMode", "OFF",
                          "-o", dst])
        assert result == 0
        assert Path(dst).exists()


# ─── Multi-file info and validate ────────────────────────────────────


class TestMultiFileInfo:
    """Test info command with multiple files."""

    def test_single_file(self, capsys):
        """Single file should work as before."""
        result = run_cli(["info", str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "PAWSOVERMAWS.PRS" in out

    def test_two_files(self, capsys):
        """Two files should produce output for both."""
        result = run_cli(["info", str(PAWS), str(NEW_RADIO)])
        assert result == 0
        out = capsys.readouterr().out
        assert "PAWSOVERMAWS.PRS" in out
        assert "Processed 2 files" in out

    def test_multi_with_missing(self, capsys):
        """Multi-file with a missing file should still process others."""
        result = run_cli(["info", str(PAWS), "nonexistent.PRS",
                          str(NEW_RADIO)])
        assert result == 1  # error exit code
        out = capsys.readouterr().out
        assert "PAWSOVERMAWS.PRS" in out
        assert "Processed 3 files" in out


class TestMultiFileValidate:
    """Test validate command with multiple files."""

    def test_single_file(self, capsys):
        """Single file should work as before."""
        result = run_cli(["validate", str(NEW_RADIO)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Validating" in out

    def test_two_files(self, capsys):
        """Two files should produce batch summary."""
        result = run_cli(["validate", str(PAWS), str(NEW_RADIO)])
        # Both should pass (no errors, only warnings/info)
        out = capsys.readouterr().out
        assert "Batch validate:" in out
        assert "2 passed" in out

    def test_multi_with_missing(self, capsys):
        """Missing file in batch should report error."""
        result = run_cli(["validate", str(PAWS), "nonexistent.PRS"])
        assert result == 1
        out = capsys.readouterr().out
        assert "Batch validate:" in out
        assert "1 errors" in out

    def test_three_files(self, capsys):
        """Three valid files should all pass."""
        result = run_cli(["validate", str(PAWS), str(NEW_RADIO),
                          str(CLAUDE)])
        out = capsys.readouterr().out
        assert "Batch validate:" in out
        assert "3 passed" in out


# ─── SECTION_MAP coverage ───────────────────────────────────────────


class TestSectionMap:
    """Test that SECTION_MAP covers all expected sections."""

    def test_all_sections_present(self):
        """All friendly section names should map to XML elements."""
        expected = ['gps', 'misc', 'audio', 'bluetooth', 'timedate',
                    'accessory', 'mandown', 'display']
        for name in expected:
            assert name in SECTION_MAP

    def test_display_maps_to_miscconfig(self):
        """Display should be an alias for miscConfig."""
        assert SECTION_MAP['display'] == 'miscConfig'

    def test_gps_maps_to_gpsconfig(self):
        """GPS should map to gpsConfig."""
        assert SECTION_MAP['gps'] == 'gpsConfig'

    def test_timedate_maps_to_timedatecfg(self):
        """Timedate should map to TimeDateCfg (case-sensitive)."""
        assert SECTION_MAP['timedate'] == 'TimeDateCfg'
