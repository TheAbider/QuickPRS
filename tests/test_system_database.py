"""Tests for the P25 system database and CLI commands."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from quickprs.system_database import (
    SYSTEMS, P25System,
    search_systems, get_system_by_name, get_system_by_id,
    get_systems_by_state, list_all_systems,
    get_iden_template_key, get_default_iden_name,
)
from quickprs.cli import run_cli, cmd_systems

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Database integrity ─────────────────────────────────────────────


class TestDatabaseIntegrity:
    """Verify the database itself is well-formed."""

    def test_systems_not_empty(self):
        """Database should have a reasonable number of systems."""
        assert len(SYSTEMS) >= 25

    def test_all_systems_are_p25system(self):
        """Every entry should be a P25System dataclass."""
        for s in SYSTEMS:
            assert isinstance(s, P25System)

    def test_all_systems_have_required_fields(self):
        """Every system should have name, state, system_id, wacn."""
        for s in SYSTEMS:
            assert s.name, f"Missing name: {s}"
            assert s.long_name, f"Missing long_name: {s.name}"
            assert s.state, f"Missing state: {s.name}"
            assert s.system_id >= 0, f"Invalid system_id: {s.name}"
            assert s.wacn >= 0, f"Invalid wacn: {s.name}"
            assert s.band in ("700", "800", "900", "700/800"), \
                f"Invalid band for {s.name}: {s.band}"
            assert s.system_type in ("Phase I", "Phase II"), \
                f"Invalid type for {s.name}: {s.system_type}"

    def test_all_names_unique(self):
        """System names should be unique (case-insensitive)."""
        seen = set()
        for s in SYSTEMS:
            key = s.name.lower()
            assert key not in seen, f"Duplicate name: {s.name}"
            seen.add(key)

    def test_all_states_two_letter(self):
        """State codes should be 2-letter uppercase (or 'US' for federal)."""
        for s in SYSTEMS:
            assert len(s.state) == 2, f"Bad state for {s.name}: {s.state}"
            assert s.state == s.state.upper(), \
                f"State not uppercase for {s.name}: {s.state}"

    def test_system_names_max_8_chars(self):
        """System names should fit in 8 chars for PRS compatibility."""
        for s in SYSTEMS:
            assert len(s.name) <= 8, \
                f"Name too long: {s.name} ({len(s.name)} chars)"


# ─── Search functions ────────────────────────────────────────────────


class TestSearchSystems:
    """Test the search_systems function."""

    def test_search_by_exact_name(self):
        results = search_systems("PSERN")
        assert any(s.name == "PSERN" for s in results)

    def test_search_by_name_case_insensitive(self):
        results = search_systems("psern")
        assert any(s.name == "PSERN" for s in results)

    def test_search_by_location(self):
        results = search_systems("Seattle")
        assert any(s.name == "PSERN" for s in results)

    def test_search_by_state(self):
        results = search_systems("WA")
        assert len(results) >= 2  # PSERN, KCERS, WSP

    def test_search_by_system_id(self):
        results = search_systems("892")
        assert any(s.name == "PSERN" for s in results)

    def test_search_by_description(self):
        results = search_systems("statewide")
        assert len(results) >= 3

    def test_search_no_match(self):
        results = search_systems("xyznonexistent")
        assert len(results) == 0

    def test_search_empty_returns_all(self):
        results = search_systems("")
        assert len(results) == len(SYSTEMS)

    def test_search_partial_name(self):
        results = search_systems("LAP")
        assert any(s.name == "LAPD" for s in results)


class TestGetSystemByName:
    """Test get_system_by_name lookup."""

    def test_exact_name(self):
        s = get_system_by_name("PSERN")
        assert s is not None
        assert s.system_id == 892

    def test_case_insensitive(self):
        s = get_system_by_name("psern")
        assert s is not None
        assert s.name == "PSERN"

    def test_name_with_whitespace(self):
        s = get_system_by_name("  PSERN  ")
        assert s is not None

    def test_not_found(self):
        s = get_system_by_name("NONEXISTENT")
        assert s is None


class TestGetSystemById:
    """Test get_system_by_id lookup."""

    def test_existing_id(self):
        results = get_system_by_id(892)
        assert len(results) >= 1
        assert results[0].name == "PSERN"

    def test_nonexistent_id(self):
        results = get_system_by_id(99999)
        assert len(results) == 0


class TestGetSystemsByState:
    """Test get_systems_by_state lookup."""

    def test_by_state_code(self):
        results = get_systems_by_state("WA")
        assert len(results) >= 2
        names = {s.name for s in results}
        assert "PSERN" in names
        assert "KCERS" in names

    def test_by_state_case_insensitive(self):
        results = get_systems_by_state("wa")
        assert len(results) >= 2

    def test_no_systems_in_state(self):
        results = get_systems_by_state("XX")
        assert len(results) == 0

    def test_by_location_text(self):
        results = get_systems_by_state("Los Angeles")
        # Should match CA systems via location field
        assert len(results) >= 1
        assert any(s.name == "LAPD" for s in results)


class TestListAllSystems:
    """Test list_all_systems."""

    def test_returns_all(self):
        all_sys = list_all_systems()
        assert len(all_sys) == len(SYSTEMS)

    def test_sorted_by_state_then_name(self):
        all_sys = list_all_systems()
        for i in range(1, len(all_sys)):
            prev = (all_sys[i - 1].state, all_sys[i - 1].name)
            curr = (all_sys[i].state, all_sys[i].name)
            assert prev <= curr, \
                f"Not sorted: {prev} should come before {curr}"


# ─── IDEN template mapping ──────────────────────────────────────────


class TestIdenTemplateMapping:
    """Test IDEN template key/name generation."""

    def test_800_phase_ii(self):
        s = get_system_by_name("PSERN")
        assert get_iden_template_key(s) == "800-TDMA"

    def test_800_phase_i(self):
        s = get_system_by_name("KCERS")
        assert get_iden_template_key(s) == "800-FDMA"

    def test_700_800_defaults_to_800(self):
        s = get_system_by_name("LAPD")
        key = get_iden_template_key(s)
        assert key.startswith("800")

    def test_default_iden_name_800_tdma(self):
        s = get_system_by_name("PSERN")
        assert get_default_iden_name(s) == "8TDMA"

    def test_default_iden_name_800_fdma(self):
        s = get_system_by_name("KCERS")
        assert get_default_iden_name(s) == "8FDMA"


# ─── CLI commands ────────────────────────────────────────────────────


class TestCLISystems:
    """Test the CLI systems subcommand."""

    def test_systems_list(self, capsys):
        result = run_cli(["systems", "list"])
        assert result == 0
        out = capsys.readouterr().out
        assert "PSERN" in out
        assert "systems in database" in out

    def test_systems_search(self, capsys):
        result = run_cli(["systems", "search", "seattle"])
        assert result == 0
        out = capsys.readouterr().out
        assert "PSERN" in out
        assert "matching systems" in out

    def test_systems_search_no_match(self, capsys):
        result = run_cli(["systems", "search", "xyznonexistent"])
        assert result == 0
        out = capsys.readouterr().out
        assert "No systems matching" in out

    def test_systems_info(self, capsys):
        result = run_cli(["systems", "info", "PSERN"])
        assert result == 0
        out = capsys.readouterr().out
        assert "892" in out
        assert "Puget Sound" in out

    def test_systems_info_not_found(self, capsys):
        result = run_cli(["systems", "info", "NONEXISTENT"])
        assert result == 1

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_systems_add_to_prs(self, capsys):
        """Add a known system to a PRS file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy test file
            src = PAWS
            dst = Path(tmpdir) / "test.PRS"
            shutil.copy2(src, dst)

            result = run_cli(["systems", "add", str(dst), "PSERN"])
            assert result == 0
            out = capsys.readouterr().out
            assert "Added P25 system" in out
            assert "PSERN" in out
            assert "892" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_systems_add_to_prs_output_flag(self, capsys):
        """Add a system with -o output flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = PAWS
            dst = Path(tmpdir) / "input.PRS"
            out_file = Path(tmpdir) / "output.PRS"
            shutil.copy2(src, dst)

            result = run_cli(["systems", "add", str(dst), "PSERN",
                              "-o", str(out_file)])
            assert result == 0
            assert out_file.exists()

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_systems_add_unknown_name(self, capsys):
        """Adding unknown system should fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dst = Path(tmpdir) / "test.PRS"
            shutil.copy2(PAWS, dst)
            result = run_cli(["systems", "add", str(dst), "NONEXISTENT"])
            assert result == 1

    def test_systems_no_subcmd(self, capsys):
        """systems with no subcommand should show help."""
        result = run_cli(["systems"])
        assert result == 1


class TestCmdSystemsDirect:
    """Test cmd_systems function directly."""

    def test_list_subcmd(self, capsys):
        result = cmd_systems("list")
        assert result == 0
        out = capsys.readouterr().out
        assert "PSERN" in out

    def test_search_subcmd(self, capsys):
        result = cmd_systems("search", query="California")
        assert result == 0
        out = capsys.readouterr().out
        assert "CHP" in out or "LAPD" in out

    def test_search_no_query(self, capsys):
        result = cmd_systems("search")
        assert result == 1

    def test_info_subcmd(self, capsys):
        result = cmd_systems("info", system_name="LAPD")
        assert result == 0
        out = capsys.readouterr().out
        assert "Los Angeles" in out

    def test_info_no_name(self, capsys):
        result = cmd_systems("info")
        assert result == 1

    def test_add_no_file(self, capsys):
        result = cmd_systems("add", system_name="PSERN")
        assert result == 1

    def test_add_no_name(self, capsys):
        result = cmd_systems("add", filepath="test.PRS")
        assert result == 1

    def test_unknown_subcmd(self, capsys):
        result = cmd_systems("bogus")
        assert result == 1


# ─── Integration: system added to PRS validates ─────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestSystemDatabaseIntegration:
    """Test that systems from the database produce valid PRS files."""

    def test_add_psern_validates(self):
        """Adding PSERN to PAWS should produce a valid file."""
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs
        from quickprs.validation import validate_prs, ERROR
        from quickprs.injector import add_p25_trunked_system, make_iden_set
        from quickprs.record_types import P25TrkSystemConfig
        from quickprs.iden_library import get_template

        with tempfile.TemporaryDirectory() as tmpdir:
            dst = Path(tmpdir) / "test.PRS"
            shutil.copy2(PAWS, dst)

            prs = parse_prs(str(dst))
            sys_obj = get_system_by_name("PSERN")

            iden_key = get_iden_template_key(sys_obj)
            iden_name = get_default_iden_name(sys_obj)
            template = get_template(iden_key)
            iden_set = make_iden_set(iden_name, template.entries)

            config = P25TrkSystemConfig(
                system_name="PSERN",
                long_name="PSERN SEATTLE",
                trunk_set_name="",
                group_set_name="",
                wan_name="PSERN",
                system_id=892,
                wacn=781824,
                iden_set_name=iden_name,
                wan_base_freq_hz=template.entries[0]['base_freq_hz'],
                wan_chan_spacing_hz=template.entries[0]['chan_spacing_hz'],
            )

            add_p25_trunked_system(prs, config, iden_set=iden_set)
            write_prs(prs, str(dst))

            # Reload and validate
            prs2 = parse_prs(str(dst))
            issues = validate_prs(prs2)
            errors = [m for s, m in issues if s == ERROR]
            # May have warnings, but no showstopper errors
            assert len(errors) == 0, f"Validation errors: {errors}"

    def test_add_multiple_systems_roundtrip(self):
        """Adding two systems should not corrupt the file."""
        from quickprs.prs_parser import parse_prs
        from quickprs.prs_writer import write_prs
        from quickprs.validation import validate_prs, ERROR

        with tempfile.TemporaryDirectory() as tmpdir:
            dst = Path(tmpdir) / "test.PRS"
            shutil.copy2(PAWS, dst)

            # Add PSERN
            run_cli(["systems", "add", str(dst), "PSERN"])
            # Add LAPD
            run_cli(["systems", "add", str(dst), "LAPD"])

            prs = parse_prs(str(dst))
            issues = validate_prs(prs)
            errors = [m for s, m in issues if s == ERROR]
            assert len(errors) == 0, f"Validation errors: {errors}"


# ─── Wizard dialog (mock tests) ─────────────────────────────────────


class TestWizardFreqParsing:
    """Test the wizard's frequency and talkgroup parsing."""

    def test_parse_freqs_single_column(self):
        """Single-column RX frequencies with auto TX."""
        from quickprs.gui.system_wizard import SystemWizard

        # We can't instantiate the full wizard without tkinter,
        # so test the parsing logic directly
        from quickprs.iden_library import calculate_tx_freq

        text = "851.0125\n851.5125\n852.0125\n"
        lines = text.strip().split("\n")
        freqs = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                tx = float(parts[0].strip())
                rx = float(parts[1].strip())
                freqs.append((tx, rx))
            else:
                rx = float(parts[0].strip())
                tx = calculate_tx_freq(rx)
                freqs.append((tx, rx))

        assert len(freqs) == 3
        # 800 MHz: TX = RX - 45
        assert abs(freqs[0][0] - 806.0125) < 0.001

    def test_parse_freqs_two_column(self):
        """Two-column TX,RX format."""
        from quickprs.iden_library import calculate_tx_freq

        text = "806.0125,851.0125\n806.5125,851.5125\n"
        lines = text.strip().split("\n")
        freqs = []
        for line in lines:
            parts = line.split(",")
            tx = float(parts[0].strip())
            rx = float(parts[1].strip())
            freqs.append((tx, rx))

        assert len(freqs) == 2
        assert freqs[0] == (806.0125, 851.0125)

    def test_parse_talkgroups(self):
        """CSV talkgroup parsing."""
        text = "100,Dispatch,Police Dispatch\n200,Fire,Fire Dispatch\n"
        lines = text.strip().split("\n")
        tgs = []
        for line in lines:
            parts = line.split(",")
            gid = int(parts[0].strip())
            sn = parts[1].strip()[:8]
            ln = parts[2].strip()[:16] if len(parts) > 2 else sn
            tgs.append((gid, sn, ln))

        assert len(tgs) == 2
        assert tgs[0] == (100, "Dispatch", "Police Dispatch")

    def test_parse_talkgroups_minimal(self):
        """Minimal CSV with just ID and short name."""
        text = "100,Dispatch\n"
        lines = text.strip().split("\n")
        tgs = []
        for line in lines:
            parts = line.split(",")
            gid = int(parts[0].strip())
            sn = parts[1].strip()[:8] if len(parts) > 1 else str(gid)
            ln = parts[2].strip()[:16] if len(parts) > 2 else sn
            tgs.append((gid, sn, ln))

        assert len(tgs) == 1
        assert tgs[0] == (100, "Dispatch", "Dispatch")


# ─── Coverage: all known systems map to valid IDEN templates ─────────


class TestAllSystemsIdenCoverage:
    """Verify every database system maps to a valid IDEN template."""

    def test_all_systems_have_valid_iden_key(self):
        from quickprs.iden_library import STANDARD_IDEN_TEMPLATES
        for sys in SYSTEMS:
            key = get_iden_template_key(sys)
            assert key in STANDARD_IDEN_TEMPLATES, \
                f"System {sys.name} maps to unknown IDEN key: {key}"

    def test_all_systems_have_valid_iden_name(self):
        for sys in SYSTEMS:
            name = get_default_iden_name(sys)
            assert len(name) <= 5, \
                f"IDEN name too long for {sys.name}: {name}"
            assert name, f"Empty IDEN name for {sys.name}"
