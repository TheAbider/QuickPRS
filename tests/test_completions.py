"""Tests for shell tab-completion script generation."""

import pytest

from quickprs.completions import (
    generate_bash_completion,
    generate_powershell_completion,
    SUBCOMMANDS,
    INJECT_TYPES,
    BULK_EDIT_TYPES,
    FREQ_TOOLS_TYPES,
    TEMPLATE_NAMES,
    SCANNER_FORMATS,
    SET_TYPES,
    LIST_TYPES,
    OPTION_SECTIONS,
    OPTION_PATHS,
    _SUBCOMMAND_FLAGS,
    _INJECT_FLAGS,
    _BULK_EDIT_FLAGS,
)
from quickprs.cli import run_cli


# ═══════════════════════════════════════════════════════════════════
# Data integrity — constants match what cli.py actually defines
# ═══════════════════════════════════════════════════════════════════


class TestCompletionConstants:
    """Verify completion data matches CLI definitions."""

    def test_subcommands_non_empty(self):
        assert len(SUBCOMMANDS) > 25

    def test_inject_types(self):
        assert set(INJECT_TYPES) == {"p25", "conv", "talkgroups"}

    def test_bulk_edit_types(self):
        assert set(BULK_EDIT_TYPES) == {"talkgroups", "channels"}

    def test_freq_tools_types(self):
        assert set(FREQ_TOOLS_TYPES) == {
            "offset", "channel", "tones", "dcs", "nearest"
        }

    def test_template_names(self):
        assert set(TEMPLATE_NAMES) == {
            "murs", "gmrs", "frs", "marine", "noaa"
        }

    def test_scanner_formats(self):
        assert set(SCANNER_FORMATS) == {
            "uniden", "chirp", "sdrtrunk", "auto"
        }

    def test_set_types(self):
        assert set(SET_TYPES) == {
            "system", "trunk-set", "group-set", "conv-set"
        }

    def test_list_types(self):
        assert set(LIST_TYPES) == {
            "systems", "talkgroups", "channels",
            "frequencies", "sets", "options",
        }

    def test_option_sections_cover_section_map(self):
        from quickprs.option_maps import SECTION_MAP
        for friendly in SECTION_MAP:
            assert friendly in OPTION_SECTIONS, \
                f"SECTION_MAP key '{friendly}' not in OPTION_SECTIONS"

    def test_option_paths_format(self):
        """Every option path should be section.attribute format."""
        for path in OPTION_PATHS:
            parts = path.split(".")
            assert len(parts) == 2, f"Bad option path: {path}"
            assert parts[0] in OPTION_SECTIONS, \
                f"Unknown section in path: {path}"

    def test_every_subcommand_has_flag_entry(self):
        """Every subcommand should have an entry in _SUBCOMMAND_FLAGS."""
        for cmd in SUBCOMMANDS:
            assert cmd in _SUBCOMMAND_FLAGS, \
                f"Subcommand '{cmd}' missing from _SUBCOMMAND_FLAGS"

    def test_inject_flags_cover_all_types(self):
        for t in INJECT_TYPES:
            assert t in _INJECT_FLAGS

    def test_bulk_edit_flags_cover_all_types(self):
        for t in BULK_EDIT_TYPES:
            assert t in _BULK_EDIT_FLAGS

    def test_no_duplicate_subcommands(self):
        assert len(SUBCOMMANDS) == len(set(SUBCOMMANDS))


# ═══════════════════════════════════════════════════════════════════
# Bash completion script
# ═══════════════════════════════════════════════════════════════════


class TestBashCompletion:
    """Test bash completion script generation."""

    @pytest.fixture
    def bash_script(self):
        return generate_bash_completion()

    def test_returns_string(self, bash_script):
        assert isinstance(bash_script, str)

    def test_non_empty(self, bash_script):
        assert len(bash_script) > 500

    def test_has_function_definition(self, bash_script):
        assert "_quickprs_complete()" in bash_script

    def test_has_complete_command(self, bash_script):
        assert "complete -F _quickprs_complete quickprs" in bash_script

    def test_has_install_comment(self, bash_script):
        assert 'eval "$(quickprs --completion bash)"' in bash_script

    def test_contains_all_subcommands(self, bash_script):
        for cmd in SUBCOMMANDS:
            assert cmd in bash_script, f"Subcommand '{cmd}' not in script"

    def test_contains_inject_types(self, bash_script):
        for t in INJECT_TYPES:
            assert t in bash_script

    def test_contains_template_names(self, bash_script):
        for t in TEMPLATE_NAMES:
            assert t in bash_script

    def test_contains_scanner_formats(self, bash_script):
        for f in SCANNER_FORMATS:
            assert f in bash_script

    def test_contains_set_types(self, bash_script):
        for t in SET_TYPES:
            assert t in bash_script

    def test_contains_list_types(self, bash_script):
        for t in LIST_TYPES:
            assert t in bash_script

    def test_contains_option_paths(self, bash_script):
        for p in OPTION_PATHS:
            assert p in bash_script

    def test_contains_version_flag(self, bash_script):
        assert "--version" in bash_script

    def test_contains_completion_flag(self, bash_script):
        assert "--completion" in bash_script

    def test_file_extension_completion(self, bash_script):
        assert "PRS" in bash_script

    def test_compgen_used(self, bash_script):
        assert "compgen" in bash_script

    def test_compreply_used(self, bash_script):
        assert "COMPREPLY" in bash_script

    def test_valid_bash_syntax_braces(self, bash_script):
        """Opening/closing braces should balance."""
        assert bash_script.count("{") == bash_script.count("}")

    def test_case_blocks_terminated(self, bash_script):
        """Each case block should have matching esac."""
        assert bash_script.count("case") == bash_script.count("esac")

    def test_subcommand_flags_appear(self, bash_script):
        """Flags for subcommands with flags should appear."""
        assert "--detail" in bash_script
        assert "--salvage" in bash_script
        assert "--compact" in bash_script
        assert "--raw" in bash_script

    def test_inject_flag_cases(self, bash_script):
        """Inject sub-subcommand flags should appear."""
        assert "--sysid" in bash_script
        assert "--channels-csv" in bash_script
        assert "--tgs-csv" in bash_script

    def test_bulk_edit_flag_cases(self, bash_script):
        """Bulk-edit sub-subcommand flags should appear."""
        assert "--enable-scan" in bash_script
        assert "--set-tone" in bash_script
        assert "--clear-tones" in bash_script


# ═══════════════════════════════════════════════════════════════════
# PowerShell completion script
# ═══════════════════════════════════════════════════════════════════


class TestPowerShellCompletion:
    """Test PowerShell completion script generation."""

    @pytest.fixture
    def ps_script(self):
        return generate_powershell_completion()

    def test_returns_string(self, ps_script):
        assert isinstance(ps_script, str)

    def test_non_empty(self, ps_script):
        assert len(ps_script) > 500

    def test_has_register_completer(self, ps_script):
        assert "Register-ArgumentCompleter" in ps_script

    def test_has_native_flag(self, ps_script):
        assert "-Native" in ps_script

    def test_has_command_name(self, ps_script):
        assert "quickprs" in ps_script
        assert "QuickPRS" in ps_script

    def test_has_install_comment(self, ps_script):
        assert "Invoke-Expression" in ps_script

    def test_contains_all_subcommands(self, ps_script):
        for cmd in SUBCOMMANDS:
            assert f"'{cmd}'" in ps_script

    def test_contains_inject_types(self, ps_script):
        for t in INJECT_TYPES:
            assert f"'{t}'" in ps_script

    def test_contains_template_names(self, ps_script):
        for t in TEMPLATE_NAMES:
            assert f"'{t}'" in ps_script

    def test_contains_scanner_formats(self, ps_script):
        for f in SCANNER_FORMATS:
            assert f"'{f}'" in ps_script

    def test_contains_set_types(self, ps_script):
        for t in SET_TYPES:
            assert f"'{t}'" in ps_script

    def test_contains_list_types(self, ps_script):
        for t in LIST_TYPES:
            assert f"'{t}'" in ps_script

    def test_contains_option_paths(self, ps_script):
        for p in OPTION_PATHS:
            assert f"'{p}'" in ps_script

    def test_completion_result_class(self, ps_script):
        assert "CompletionResult" in ps_script

    def test_word_to_complete_param(self, ps_script):
        assert "$wordToComplete" in ps_script

    def test_subcommand_flags_appear(self, ps_script):
        assert "'--detail'" in ps_script
        assert "'--salvage'" in ps_script
        assert "'--compact'" in ps_script

    def test_inject_flag_entries(self, ps_script):
        assert "'--sysid'" in ps_script
        assert "'--channels-csv'" in ps_script

    def test_bulk_edit_flag_entries(self, ps_script):
        assert "'--enable-scan'" in ps_script
        assert "'--set-tone'" in ps_script

    def test_prs_file_completion(self, ps_script):
        assert "*.PRS" in ps_script


# ═══════════════════════════════════════════════════════════════════
# CLI --completion flag integration
# ═══════════════════════════════════════════════════════════════════


class TestCompletionCLI:
    """Test the --completion CLI flag end-to-end."""

    def test_completion_bash(self, capsys):
        result = run_cli(["--completion", "bash"])
        assert result == 0
        out = capsys.readouterr().out
        assert "_quickprs_complete" in out
        assert "complete -F" in out

    def test_completion_powershell(self, capsys):
        result = run_cli(["--completion", "powershell"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Register-ArgumentCompleter" in out

    def test_completion_invalid_shell(self):
        """Invalid shell name should cause argparse error."""
        with pytest.raises(SystemExit):
            run_cli(["--completion", "zsh"])

    def test_completion_with_subcommand(self, capsys):
        """--completion should work even with a subcommand present."""
        # When --completion is given, it takes priority
        result = run_cli(["--completion", "bash"])
        assert result == 0

    def test_no_completion_flag_returns_none(self):
        """Without --completion, no-subcommand should return None (GUI)."""
        result = run_cli([])
        assert result is None
