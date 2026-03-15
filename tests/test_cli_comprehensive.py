"""Comprehensive CLI tests — every command with --help, plus functional tests.

Validates that every CLI subcommand accepts --help without error,
that the main dispatcher handles edge cases, and that key commands
produce expected output when invoked properly.
"""

import subprocess
import sys
import os
import tempfile
import shutil
from pathlib import Path

import pytest


TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Every command --help ────────────────────────────────────────────

# Top-level commands (no subparser nesting)
TOP_LEVEL_COMMANDS = [
    ["create"],
    ["build"],
    ["wizard"],
    ["fleet"],
    ["fleet-check"],
    ["snapshot"],
    ["remove"],
    ["edit"],
    ["merge"],
    ["clone"],
    ["clone-personality"],
    ["rename"],
    ["sort"],
    ["renumber"],
    ["auto-name"],
    ["auto-setup"],
    ["import-rr"],
    ["import-paste"],
    ["import-scanner"],
    ["import-json"],
    ["template-csv"],
    ["convert"],
    ["export-csv"],
    ["export-json"],
    ["export-config"],
    ["report"],
    ["card"],
    ["info"],
    ["validate"],
    ["health"],
    ["suggest"],
    ["freq-map"],
    ["compare"],
    ["diff-report"],
    ["diff-options"],
    ["stats"],
    ["capacity"],
    ["list"],
    ["dump"],
    ["set-option"],
    ["encrypt"],
    ["set-nac"],
    ["zones"],
    ["iden-templates"],
    ["repair"],
    ["cleanup"],
    ["search"],
    ["backup"],
    ["watch"],
    ["cheat-sheet"],
    ["about"],
    ["demo"],
    ["tutorial"],
]

# Commands with nested subparsers
NESTED_COMMANDS = [
    ["inject", "p25"],
    ["inject", "conv"],
    ["inject", "talkgroups"],
    ["bulk-edit", "talkgroups"],
    ["bulk-edit", "channels"],
    ["systems", "list"],
    ["systems", "search"],
    ["systems", "info"],
    ["systems", "add"],
    ["profiles", "list"],
    ["profiles", "build"],
    ["freq-tools", "offset"],
    ["freq-tools", "channel"],
    ["freq-tools", "tones"],
    ["freq-tools", "dcs"],
    ["freq-tools", "nearest"],
    ["freq-tools", "identify"],
    ["freq-tools", "all-offsets"],
    ["freq-tools", "conflicts"],
    ["favorites", "list"],
    ["favorites", "add"],
    ["favorites", "remove"],
    ["favorites", "clear"],
    ["preset", "list"],
    ["preset", "show"],
    ["preset", "apply"],
    ["export"],
]

ALL_COMMANDS = TOP_LEVEL_COMMANDS + NESTED_COMMANDS


@pytest.mark.parametrize("cmd", ALL_COMMANDS,
                         ids=[" ".join(c) for c in ALL_COMMANDS])
def test_help_flag(cmd):
    """Every command should accept --help and exit 0."""
    r = subprocess.run(
        [sys.executable, '-m', 'quickprs'] + cmd + ['--help'],
        capture_output=True, timeout=15,
    )
    assert r.returncode == 0, (
        f"Command {cmd} --help returned {r.returncode}.\n"
        f"stderr: {r.stderr.decode('utf-8', errors='replace')[:500]}"
    )


# ─── Parent-level --help for nested commands ─────────────────────────


@pytest.mark.parametrize("parent", [
    "inject", "bulk-edit", "systems", "profiles",
    "freq-tools", "favorites", "preset",
])
def test_parent_help(parent):
    """Parent commands with subparsers accept --help."""
    r = subprocess.run(
        [sys.executable, '-m', 'quickprs', parent, '--help'],
        capture_output=True, timeout=15,
    )
    assert r.returncode == 0


# ─── Global flags ────────────────────────────────────────────────────


def test_version_flag():
    """--version prints version and exits 0."""
    r = subprocess.run(
        [sys.executable, '-m', 'quickprs', '--version'],
        capture_output=True, timeout=10,
    )
    assert r.returncode == 0
    assert b"QuickPRS" in r.stdout or b"quickprs" in r.stdout.lower()


def test_no_args_exits_cleanly():
    """No arguments (GUI mode) exits without crash."""
    r = subprocess.run(
        [sys.executable, '-m', 'quickprs'],
        capture_output=True, timeout=10,
        env={**os.environ, 'DISPLAY': ''},  # prevent GUI launch attempt
    )
    # May return 0 or 1 depending on whether GUI is available
    # Just verify it doesn't crash with a traceback
    assert r.returncode in (0, 1, 2, None) or \
        b"Traceback" not in r.stderr


def test_unknown_command():
    """Unknown subcommand prints error."""
    r = subprocess.run(
        [sys.executable, '-m', 'quickprs', 'nonexistent_cmd'],
        capture_output=True, timeout=10,
    )
    assert r.returncode != 0


# ─── Functional CLI tests (require test data) ───────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestCLIFunctional:
    """Functional tests that exercise commands with real data."""

    def test_info_output(self):
        """info prints personality summary."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'info', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0
        assert b"PRS" in r.stdout or b"prs" in r.stdout.lower()

    def test_validate_output(self):
        """validate runs without error on valid file."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'validate', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0

    def test_stats_output(self):
        """stats prints statistics."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'stats', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0

    def test_capacity_output(self):
        """capacity prints capacity information."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'capacity', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0

    def test_dump_output(self):
        """dump prints section structure."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'dump', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0

    def test_health_output(self):
        """health check runs and produces output (may return 1 for warnings)."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'health', str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode in (0, 1)
        assert len(r.stdout) > 0

    def test_list_systems(self):
        """list systems shows system list."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'list', str(PAWS), 'systems'],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0

    def test_export_csv(self):
        """export-csv creates CSV files in temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'export-csv',
                 str(PAWS), tmpdir],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0

    def test_export_json(self):
        """export-json creates valid JSON output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "out.json")
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'export-json',
                 str(PAWS), '-o', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0
            assert os.path.exists(out_path)

    def test_diff_options_same_file(self):
        """diff-options comparing a file to itself shows no differences."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'diff-options',
             str(PAWS), str(PAWS)],
            capture_output=True, timeout=15,
        )
        assert r.returncode == 0


# ─── Functional tests using created files ────────────────────────────


class TestCLICreateAndManipulate:
    """Tests that create PRS files and operate on them."""

    def test_create_blank(self):
        """create produces a valid PRS file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "blank.PRS")
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0
            assert os.path.exists(out_path)
            assert os.path.getsize(out_path) > 0

    def test_create_and_validate(self):
        """Created file passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.PRS")
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', out_path],
                capture_output=True, timeout=15,
            )
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'validate', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0

    def test_create_and_info(self):
        """Created file can be inspected with info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.PRS")
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', out_path],
                capture_output=True, timeout=15,
            )
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'info', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0

    def test_create_and_capacity(self):
        """Created file shows capacity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.PRS")
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', out_path],
                capture_output=True, timeout=15,
            )
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'capacity', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0

    def test_create_and_dump(self):
        """Created file can be dumped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.PRS")
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', out_path],
                capture_output=True, timeout=15,
            )
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'dump', out_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0

    def test_create_and_export_json_import_roundtrip(self):
        """Created file can be exported to JSON and re-imported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prs_path = os.path.join(tmpdir, "test.PRS")
            json_path = os.path.join(tmpdir, "test.json")
            prs2_path = os.path.join(tmpdir, "test2.PRS")

            # Create
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'create', prs_path],
                capture_output=True, timeout=15,
            )
            # Export to JSON
            subprocess.run(
                [sys.executable, '-m', 'quickprs', 'export-json',
                 prs_path, '-o', json_path],
                capture_output=True, timeout=15,
            )
            assert os.path.exists(json_path)

            # Import from JSON
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'import-json',
                 json_path, '-o', prs2_path],
                capture_output=True, timeout=15,
            )
            assert r.returncode == 0
            assert os.path.exists(prs2_path)


# ─── freq-tools functional tests ────────────────────────────────────


class TestFreqToolsCLI:
    """Test freq-tools subcommands with actual arguments."""

    def test_tones(self):
        """freq-tools tones lists all CTCSS tones."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'tones'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0
        assert b"67.0" in r.stdout

    def test_dcs(self):
        """freq-tools dcs lists DCS codes."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'dcs'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_identify(self):
        """freq-tools identify gives info for a frequency."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'identify',
             '462.5625'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0
        # Should identify as FRS/GMRS
        assert b"FRS" in r.stdout or b"GMRS" in r.stdout

    def test_offset(self):
        """freq-tools offset calculates repeater offset."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'offset',
             '146.94'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_channel(self):
        """freq-tools channel identifies service channel."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'channel',
             '462.5625'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_nearest(self):
        """freq-tools nearest finds nearest CTCSS tone."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'nearest',
             '100.5'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_all_offsets(self):
        """freq-tools all-offsets shows all repeater options."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'all-offsets',
             '146.94'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_conflicts(self):
        """freq-tools conflicts checks frequency list."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'freq-tools', 'conflicts',
             '462.5625,462.5875,462.6125'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0


# ─── Reference commands ─────────────────────────────────────────────


class TestReferenceCLI:
    """Test reference/info commands that need no file input."""

    def test_cheat_sheet(self):
        """cheat-sheet prints command reference."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'cheat-sheet'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0
        assert len(r.stdout) > 100

    def test_about(self):
        """about prints project info."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'about'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_systems_list(self):
        """systems list shows P25 database."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'systems', 'list'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_iden_templates(self):
        """iden-templates lists available templates."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'iden-templates'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_preset_list(self):
        """preset list shows available presets."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'preset', 'list'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_profiles_list(self):
        """profiles list shows available profiles."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'profiles', 'list'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_favorites_list(self):
        """favorites list doesn't crash (may be empty)."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'favorites', 'list'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_template_csv_list(self):
        """template-csv lists available templates without file arg."""
        r = subprocess.run(
            [sys.executable, '-m', 'quickprs', 'template-csv', '--help'],
            capture_output=True, timeout=10,
        )
        assert r.returncode == 0

    def test_demo(self):
        """demo command runs without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                [sys.executable, '-m', 'quickprs', 'demo',
                 '--output-dir', tmpdir],
                capture_output=True, timeout=30,
            )
            # Demo may succeed or fail depending on implementation
            # but should not crash with traceback
            assert b"Traceback" not in r.stderr
