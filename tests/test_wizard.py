"""Tests for the interactive wizard and CSV template generator."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.cli import run_cli, cmd_template_csv, cmd_wizard
from quickprs.wizard import (
    run_wizard, _input, _input_yn, _read_multiline,
    _collect_p25_system, _collect_templates,
    _build_ini_content,
)


# ─── CSV Template Generator: cmd_template_csv ─────────────────────────


class TestTemplateCsvFrequencies:
    """Test frequency template generation."""

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "freqs.csv")
        result = cmd_template_csv("frequencies", output=out)
        assert result == 0
        assert Path(out).exists()

    def test_has_headers(self, tmp_path):
        out = str(tmp_path / "freqs.csv")
        cmd_template_csv("frequencies", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "tx_freq,rx_freq" in content

    def test_has_example(self, tmp_path):
        out = str(tmp_path / "freqs.csv")
        cmd_template_csv("frequencies", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "851.0125" in content

    def test_default_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = cmd_template_csv("frequencies")
        assert result == 0
        assert (tmp_path / "freqs.csv").exists()


class TestTemplateCsvTalkgroups:
    """Test talkgroup template generation."""

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "tgs.csv")
        result = cmd_template_csv("talkgroups", output=out)
        assert result == 0
        assert Path(out).exists()

    def test_has_headers(self, tmp_path):
        out = str(tmp_path / "tgs.csv")
        cmd_template_csv("talkgroups", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "id,short_name,long_name" in content

    def test_has_tx_scan_columns(self, tmp_path):
        out = str(tmp_path / "tgs.csv")
        cmd_template_csv("talkgroups", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "tx" in content
        assert "scan" in content

    def test_has_example(self, tmp_path):
        out = str(tmp_path / "tgs.csv")
        cmd_template_csv("talkgroups", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "PD DISP" in content


class TestTemplateCsvChannels:
    """Test channel template generation."""

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "channels.csv")
        result = cmd_template_csv("channels", output=out)
        assert result == 0
        assert Path(out).exists()

    def test_has_headers(self, tmp_path):
        out = str(tmp_path / "channels.csv")
        cmd_template_csv("channels", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "short_name" in content
        assert "tx_freq" in content
        assert "rx_freq" in content
        assert "tx_tone" in content
        assert "rx_tone" in content
        assert "long_name" in content

    def test_has_example(self, tmp_path):
        out = str(tmp_path / "channels.csv")
        cmd_template_csv("channels", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "RPT IN" in content


class TestTemplateCsvUnits:
    """Test units template generation."""

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "units.csv")
        result = cmd_template_csv("units", output=out)
        assert result == 0
        assert Path(out).exists()

    def test_has_headers(self, tmp_path):
        out = str(tmp_path / "units.csv")
        cmd_template_csv("units", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "unit_id" in content
        assert "name" in content
        assert "password" in content

    def test_has_example(self, tmp_path):
        out = str(tmp_path / "units.csv")
        cmd_template_csv("units", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "UNIT-1001" in content


class TestTemplateCsvConfig:
    """Test config.ini template generation."""

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "config.ini")
        result = cmd_template_csv("config", output=out)
        assert result == 0
        assert Path(out).exists()

    def test_has_personality_section(self, tmp_path):
        out = str(tmp_path / "config.ini")
        cmd_template_csv("config", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "[personality]" in content

    def test_has_system_example(self, tmp_path):
        out = str(tmp_path / "config.ini")
        cmd_template_csv("config", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "system_id" in content

    def test_has_channel_example(self, tmp_path):
        out = str(tmp_path / "config.ini")
        cmd_template_csv("config", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "template = murs" in content

    def test_has_options_example(self, tmp_path):
        out = str(tmp_path / "config.ini")
        cmd_template_csv("config", output=out)
        content = Path(out).read_text(encoding='utf-8')
        assert "gps.gpsMode" in content

    def test_default_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = cmd_template_csv("config")
        assert result == 0
        assert (tmp_path / "config.ini").exists()


class TestTemplateCsvErrors:
    """Test error handling for template-csv."""

    def test_unknown_type_returns_1(self, tmp_path, capsys):
        result = cmd_template_csv("badtype")
        assert result == 1
        err = capsys.readouterr().err
        assert "unknown template type" in err.lower()

    def test_creates_parent_dirs(self, tmp_path):
        out = str(tmp_path / "subdir" / "deep" / "freqs.csv")
        result = cmd_template_csv("frequencies", output=out)
        assert result == 0
        assert Path(out).exists()


class TestTemplateCsvCLI:
    """Test template-csv via run_cli dispatcher."""

    def test_cli_frequencies(self, tmp_path, capsys):
        out = str(tmp_path / "f.csv")
        result = run_cli(["template-csv", "frequencies", "-o", out])
        assert result == 0
        assert Path(out).exists()

    def test_cli_talkgroups(self, tmp_path, capsys):
        out = str(tmp_path / "t.csv")
        result = run_cli(["template-csv", "talkgroups", "-o", out])
        assert result == 0

    def test_cli_channels(self, tmp_path, capsys):
        out = str(tmp_path / "c.csv")
        result = run_cli(["template-csv", "channels", "-o", out])
        assert result == 0

    def test_cli_units(self, tmp_path, capsys):
        out = str(tmp_path / "u.csv")
        result = run_cli(["template-csv", "units", "-o", out])
        assert result == 0

    def test_cli_config(self, tmp_path, capsys):
        out = str(tmp_path / "c.ini")
        result = run_cli(["template-csv", "config", "-o", out])
        assert result == 0

    def test_cli_prints_created(self, tmp_path, capsys):
        out = str(tmp_path / "f.csv")
        run_cli(["template-csv", "frequencies", "-o", out])
        stdout = capsys.readouterr().out
        assert "Created template:" in stdout

    def test_cli_no_output_flag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        result = run_cli(["template-csv", "frequencies"])
        assert result == 0
        assert (tmp_path / "freqs.csv").exists()


# ─── Wizard helper functions ──────────────────────────────────────────


class TestInputHelper:
    """Test _input helper."""

    def test_returns_user_input(self):
        with patch('builtins.input', return_value="hello"):
            result = _input("prompt")
        assert result == "hello"

    def test_returns_default_on_empty(self):
        with patch('builtins.input', return_value=""):
            result = _input("prompt", default="fallback")
        assert result == "fallback"

    def test_strips_whitespace(self):
        with patch('builtins.input', return_value="  trimmed  "):
            result = _input("prompt")
        assert result == "trimmed"

    def test_eof_exits(self):
        with patch('builtins.input', side_effect=EOFError):
            with pytest.raises(SystemExit):
                _input("prompt")

    def test_keyboard_interrupt_exits(self):
        with patch('builtins.input', side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit):
                _input("prompt")

    def test_empty_no_default_returns_empty(self):
        with patch('builtins.input', return_value=""):
            result = _input("prompt")
        assert result == ""


class TestInputYnHelper:
    """Test _input_yn helper."""

    def test_yes(self):
        with patch('builtins.input', return_value="y"):
            result = _input_yn("continue?")
        assert result is True

    def test_no(self):
        with patch('builtins.input', return_value="n"):
            result = _input_yn("continue?")
        assert result is False

    def test_default_false(self):
        with patch('builtins.input', return_value=""):
            result = _input_yn("continue?", default=False)
        assert result is False

    def test_default_true(self):
        with patch('builtins.input', return_value=""):
            result = _input_yn("continue?", default=True)
        assert result is True

    def test_yes_uppercase(self):
        with patch('builtins.input', return_value="YES"):
            result = _input_yn("continue?")
        assert result is True

    def test_no_uppercase(self):
        with patch('builtins.input', return_value="NO"):
            result = _input_yn("continue?")
        assert result is False


class TestReadMultiline:
    """Test _read_multiline helper."""

    def test_reads_lines(self):
        with patch('builtins.input', side_effect=["line1", "line2", ""]):
            result = _read_multiline("Enter lines:")
        assert result == ["line1", "line2"]

    def test_empty_input(self):
        with patch('builtins.input', side_effect=[""]):
            result = _read_multiline("Enter lines:")
        assert result == []

    def test_strips_lines(self):
        with patch('builtins.input', side_effect=["  spaced  ", ""]):
            result = _read_multiline("Enter:")
        assert result == ["spaced"]

    def test_eof_stops_reading(self):
        with patch('builtins.input', side_effect=["line1", EOFError]):
            result = _read_multiline("Enter:")
        assert result == ["line1"]


# ─── Wizard INI builder ───────────────────────────────────────────────


class TestBuildIniContent:
    """Test _build_ini_content helper."""

    def test_personality_section(self):
        ini = _build_ini_content("TEST.PRS", [], [], {})
        assert "[personality]" in ini
        assert "name = TEST.PRS" in ini

    def test_p25_system(self):
        systems = [{
            'short_name': 'PSERN',
            'long_name': 'PSERN SEATTLE',
            'system_id': 892,
            'wacn': 781824,
            'frequencies': [(851.0125, 806.0125)],
            'talkgroups': [(1, 'DISP', 'Dispatch')],
        }]
        ini = _build_ini_content("T.PRS", systems, [], {})
        assert "[system.PSERN]" in ini
        assert "system_id = 892" in ini
        assert "wacn = 781824" in ini
        assert "[system.PSERN.frequencies]" in ini
        assert "851.0125,806.0125" in ini
        assert "[system.PSERN.talkgroups]" in ini
        assert "1,DISP,Dispatch" in ini

    def test_template_channels(self):
        ini = _build_ini_content("T.PRS", [], ["murs", "noaa"], {})
        assert "[channels.MURS]" in ini
        assert "template = murs" in ini
        assert "[channels.NOAA]" in ini
        assert "template = noaa" in ini

    def test_options(self):
        opts = {'gps.gpsMode': 'ON', 'misc.password': '1234'}
        ini = _build_ini_content("T.PRS", [], [], opts)
        assert "[options]" in ini
        assert "gps.gpsMode = ON" in ini
        assert "misc.password = 1234" in ini

    def test_no_wacn_if_zero(self):
        systems = [{
            'short_name': 'TEST',
            'long_name': 'TEST',
            'system_id': 100,
            'wacn': 0,
            'frequencies': [],
            'talkgroups': [],
        }]
        ini = _build_ini_content("T.PRS", systems, [], {})
        assert "wacn" not in ini

    def test_no_freq_section_if_empty(self):
        systems = [{
            'short_name': 'TEST',
            'long_name': 'TEST',
            'system_id': 100,
            'wacn': 0,
            'frequencies': [],
            'talkgroups': [(1, 'TG', 'Talkgroup')],
        }]
        ini = _build_ini_content("T.PRS", systems, [], {})
        assert "[system.TEST.frequencies]" not in ini
        assert "[system.TEST.talkgroups]" in ini

    def test_no_tg_section_if_empty(self):
        systems = [{
            'short_name': 'TEST',
            'long_name': 'TEST',
            'system_id': 100,
            'wacn': 0,
            'frequencies': [(851.0, 806.0)],
            'talkgroups': [],
        }]
        ini = _build_ini_content("T.PRS", systems, [], {})
        assert "[system.TEST.frequencies]" in ini
        assert "[system.TEST.talkgroups]" not in ini

    def test_no_options_section_if_empty(self):
        ini = _build_ini_content("T.PRS", [], [], {})
        assert "[options]" not in ini

    def test_author_is_wizard(self):
        ini = _build_ini_content("T.PRS", [], [], {})
        assert "author = QuickPRS Wizard" in ini


# ─── Collect helpers ──────────────────────────────────────────────────


class TestCollectP25System:
    """Test _collect_p25_system."""

    def test_full_system(self):
        inputs = [
            "PSERN",          # short_name
            "PSERN SEATTLE",  # long_name
            "892",            # system_id
            "781824",         # wacn
            "851.0125,806.0125",  # freq 1
            "",               # end freqs
            "1,DISP,Dispatch",   # tg 1
            "",               # end tgs
        ]
        with patch('builtins.input', side_effect=inputs):
            result = _collect_p25_system()
        assert result is not None
        assert result['short_name'] == 'PSERN'
        assert result['system_id'] == 892
        assert len(result['frequencies']) == 1
        assert len(result['talkgroups']) == 1

    def test_empty_name_returns_none(self):
        with patch('builtins.input', return_value=""):
            result = _collect_p25_system()
        assert result is None

    def test_invalid_system_id_defaults_zero(self):
        inputs = [
            "TEST",   # short_name
            "TEST",   # long_name
            "abc",    # invalid system_id
            "0",      # wacn
            "",       # end freqs
            "",       # end tgs
        ]
        with patch('builtins.input', side_effect=inputs):
            result = _collect_p25_system()
        assert result['system_id'] == 0

    def test_truncates_short_name(self):
        inputs = [
            "VERYLONGNAME",  # > 8 chars
            "LONG NAME HERE",
            "100",
            "0",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = _collect_p25_system()
        assert len(result['short_name']) <= 8

    def test_skips_invalid_freq(self):
        inputs = [
            "TEST",
            "TEST",
            "100",
            "0",
            "not_a_freq",       # invalid
            "851.0125,806.0125",  # valid
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = _collect_p25_system()
        assert len(result['frequencies']) == 1

    def test_skips_invalid_talkgroup(self):
        inputs = [
            "TEST",
            "TEST",
            "100",
            "0",
            "",
            "badline",          # invalid
            "1,DISP,Dispatch",  # valid
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = _collect_p25_system()
        assert len(result['talkgroups']) == 1


class TestCollectTemplates:
    """Test _collect_templates."""

    def test_valid_templates(self):
        with patch('builtins.input', return_value="murs,noaa"):
            result = _collect_templates()
        assert result == ['murs', 'noaa']

    def test_empty_input(self):
        with patch('builtins.input', return_value=""):
            result = _collect_templates()
        assert result == []

    def test_filters_invalid(self):
        with patch('builtins.input', return_value="murs,invalid,noaa"):
            result = _collect_templates()
        assert result == ['murs', 'noaa']

    def test_case_insensitive(self):
        with patch('builtins.input', return_value="MURS,NOAA"):
            result = _collect_templates()
        assert result == ['murs', 'noaa']


# ─── Full wizard run ──────────────────────────────────────────────────


class TestRunWizard:
    """Test the full wizard flow with mocked input."""

    def test_minimal_wizard(self, tmp_path):
        """Wizard with just a name and no systems/templates/options."""
        out = str(tmp_path / "MINIMAL.PRS")
        inputs = [
            "MINIMAL.PRS",   # personality name
            out,             # output file
            "n",             # add P25? no
            "",              # no templates
            "",              # no GPS
            "",              # no password
            "",              # no timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_wizard_with_templates(self, tmp_path):
        """Wizard with template channels."""
        out = str(tmp_path / "TMPL.PRS")
        inputs = [
            "TMPL.PRS",     # personality name
            out,            # output file
            "n",            # add P25? no
            "murs,noaa",    # templates
            "",             # no GPS
            "",             # no password
            "",             # no timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()

    def test_wizard_with_p25(self, tmp_path):
        """Wizard with a P25 system."""
        out = str(tmp_path / "P25.PRS")
        inputs = [
            "P25.PRS",              # personality name
            out,                    # output file
            "y",                    # add P25? yes
            "TEST",                 # short_name
            "TEST SYS",             # long_name
            "100",                  # system_id
            "0",                    # wacn
            "851.0125,806.0125",    # freq
            "",                     # end freqs
            "1,DISP,Dispatch",      # tg
            "",                     # end tgs
            "n",                    # add another P25? no
            "",                     # no templates
            "",                     # no GPS
            "",                     # no password
            "",                     # no timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()

    def test_wizard_with_options(self, tmp_path):
        """Wizard with GPS and password."""
        out = str(tmp_path / "OPTS.PRS")
        inputs = [
            "OPTS.PRS",     # personality name
            out,            # output file
            "n",            # no P25
            "murs",         # templates
            "ON",           # GPS on
            "1234",         # password
            "PST",          # timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()

    def test_wizard_appends_prs(self, tmp_path):
        """Wizard appends .PRS if not present."""
        out = str(tmp_path / "NOPRS")
        inputs = [
            "NOPRS",        # name without .PRS
            out,            # output file
            "n",            # no P25
            "",             # no templates
            "",             # no GPS
            "",             # no password
            "",             # no timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0

    def test_wizard_output_prints_created(self, tmp_path, capsys):
        """Wizard prints creation message."""
        out = str(tmp_path / "MSG.PRS")
        inputs = [
            "MSG.PRS",
            out,
            "n",
            "",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            run_wizard()
        stdout = capsys.readouterr().out
        assert "Created:" in stdout
        assert "Validation:" in stdout
        assert "Done!" in stdout

    def test_wizard_creates_parent_dirs(self, tmp_path):
        """Wizard creates parent directories if needed."""
        out = str(tmp_path / "sub" / "dir" / "DEEP.PRS")
        inputs = [
            "DEEP.PRS",
            out,
            "n",
            "",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()

    def test_wizard_full_personality(self, tmp_path):
        """Complete personality with P25, templates, and options."""
        out = str(tmp_path / "FULL.PRS")
        inputs = [
            "FULL.PRS",
            out,
            "y",                    # add P25
            "PSERN",                # short name
            "PSERN SEATTLE",        # long name
            "892",                  # system id
            "781824",               # wacn
            "851.0125,806.0125",    # freq 1
            "851.0375,806.0375",    # freq 2
            "",                     # end freqs
            "1,DISP N,Dispatch N",  # tg 1
            "2,TAC 1,Tactical 1",   # tg 2
            "",                     # end tgs
            "n",                    # no more P25
            "murs,noaa",            # templates
            "ON",                   # GPS
            "5678",                 # password
            "EST",                  # timezone
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_wizard()
        assert result == 0
        assert Path(out).exists()
        # Verify it's a valid PRS
        from quickprs.prs_parser import parse_prs
        prs = parse_prs(out)
        assert len(prs.sections) > 0


class TestWizardCLI:
    """Test wizard via CLI dispatcher."""

    def test_cli_wizard_dispatch(self, tmp_path, capsys):
        """run_cli dispatches to wizard command."""
        out = str(tmp_path / "CLI.PRS")
        inputs = [
            "CLI.PRS",
            out,
            "n",
            "",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_cli(["wizard"])
        assert result == 0

    def test_cli_wizard_modify_flag(self, tmp_path, capsys):
        """--modify flag is accepted."""
        out = str(tmp_path / "MOD.PRS")
        inputs = [
            "MOD.PRS",
            out,
            "n",
            "",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            result = run_cli(["wizard", "--modify", "dummy.PRS"])
        assert result == 0


# ─── Wizard validates output ──────────────────────────────────────────


class TestWizardValidation:
    """Test that wizard-generated PRS files are valid."""

    def test_minimal_validates(self, tmp_path):
        """Minimal wizard output passes validation."""
        out = str(tmp_path / "VAL.PRS")
        inputs = [
            "VAL.PRS",
            out,
            "n",
            "murs",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            run_wizard()

        from quickprs.prs_parser import parse_prs
        from quickprs.validation import validate_prs, ERROR
        prs = parse_prs(out)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_p25_validates(self, tmp_path):
        """P25 wizard output passes validation."""
        out = str(tmp_path / "P25V.PRS")
        inputs = [
            "P25V.PRS",
            out,
            "y",
            "TEST",
            "TEST SYS",
            "100",
            "0",
            "851.0125,806.0125",
            "",
            "1,DISP,Dispatch",
            "",
            "n",
            "",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            run_wizard()

        from quickprs.prs_parser import parse_prs
        from quickprs.validation import validate_prs, ERROR
        prs = parse_prs(out)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_wizard_roundtrips(self, tmp_path):
        """Wizard output roundtrips through parse/write."""
        out = str(tmp_path / "RT.PRS")
        inputs = [
            "RT.PRS",
            out,
            "n",
            "murs",
            "",
            "",
            "",
        ]
        with patch('builtins.input', side_effect=inputs):
            run_wizard()

        from quickprs.prs_parser import parse_prs, parse_prs_bytes
        prs = parse_prs(out)
        raw1 = prs.to_bytes()
        raw2 = parse_prs_bytes(raw1).to_bytes()
        assert raw1 == raw2
