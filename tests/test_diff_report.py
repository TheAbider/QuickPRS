"""Tests for the personality change report module."""

import pytest
import tempfile
from pathlib import Path

from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.diff_report import (
    generate_diff_report,
    generate_diff_report_from_files,
    format_change_summary,
)
from quickprs.comparison import detailed_comparison

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── generate_diff_report ───────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_diff_report_identical():
    """Report for identical files should show 'No changes detected'."""
    prs = cached_parse_prs(CLAUDE)
    original_bytes = prs.to_bytes()
    report = generate_diff_report(original_bytes, prs)
    assert "No changes detected" in report
    assert "PERSONALITY CHANGE REPORT" in report


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_diff_report_after_injection():
    """Report should show changes after adding a group set."""
    from quickprs.injector import add_group_set, make_group_set

    prs = cached_parse_prs(CLAUDE)
    original_bytes = prs.to_bytes()

    new_gset = make_group_set("DIFFTEST", [
        (100, "DIFF 1", "DIFF GROUP ONE"),
        (200, "DIFF 2", "DIFF GROUP TWO"),
    ])
    add_group_set(prs, new_gset)

    report = generate_diff_report(original_bytes, prs)
    assert "PERSONALITY CHANGE REPORT" in report
    assert "No changes detected" not in report
    # Should mention changes in the summary
    assert "Summary:" in report


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_diff_report_contains_size_info():
    """Report should include file size information."""
    prs = cached_parse_prs(CLAUDE)
    original_bytes = prs.to_bytes()
    report = generate_diff_report(original_bytes, prs)
    assert "Before:" in report
    assert "After:" in report
    assert "bytes" in report


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_diff_report_output_to_file():
    """Report can be written to a file."""
    prs = cached_parse_prs(CLAUDE)
    original_bytes = prs.to_bytes()

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                      mode='w') as f:
        tmp_path = f.name

    try:
        report = generate_diff_report(original_bytes, prs, output=tmp_path)
        assert Path(tmp_path).exists()
        content = Path(tmp_path).read_text(encoding='utf-8')
        assert "PERSONALITY CHANGE REPORT" in content
        assert report == content
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(),
                     reason="Test PRS data not available")
def test_diff_report_from_files():
    """generate_diff_report_from_files should work with file paths."""
    report = generate_diff_report_from_files(PAWS, CLAUDE)
    assert "PERSONALITY CHANGE REPORT" in report
    # Different files should show changes
    assert "Summary:" in report


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(),
                     reason="Test PRS data not available")
def test_diff_report_from_files_output():
    """generate_diff_report_from_files writes to file when output given."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                      mode='w') as f:
        tmp_path = f.name

    try:
        report = generate_diff_report_from_files(PAWS, CLAUDE,
                                                  output=tmp_path)
        content = Path(tmp_path).read_text(encoding='utf-8')
        assert "PERSONALITY CHANGE REPORT" in content
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─── format_change_summary ──────────────────────────────────────────


def test_format_change_summary_no_changes():
    """Empty detail dict should produce 'No changes' summary."""
    detail = {
        'systems_a_only': [],
        'systems_b_only': [],
        'systems_both': [],
        'talkgroup_diffs': {},
        'freq_diffs': {},
        'conv_diffs': {},
        'option_diffs': [],
    }
    result = format_change_summary(detail)
    assert result == "No changes."


def test_format_change_summary_systems_added():
    """Summary should mention added systems."""
    detail = {
        'systems_a_only': [],
        'systems_b_only': ['NEW SYSTEM'],
        'systems_both': [],
        'talkgroup_diffs': {},
        'freq_diffs': {},
        'conv_diffs': {},
        'option_diffs': [],
    }
    result = format_change_summary(detail)
    assert "1 system(s) added" in result


def test_format_change_summary_talkgroups():
    """Summary should mention talkgroup changes."""
    detail = {
        'systems_a_only': [],
        'systems_b_only': [],
        'systems_both': [],
        'talkgroup_diffs': {
            'SYS1': {
                'added': [(100, 'TG1', 'Talkgroup 1')],
                'removed': [],
            }
        },
        'freq_diffs': {},
        'conv_diffs': {},
        'option_diffs': [],
    }
    result = format_change_summary(detail)
    assert "1 talkgroup(s) added" in result


def test_format_change_summary_options_changed():
    """Summary should mention option changes."""
    detail = {
        'systems_a_only': [],
        'systems_b_only': [],
        'systems_both': [],
        'talkgroup_diffs': {},
        'freq_diffs': {},
        'conv_diffs': {},
        'option_diffs': [('gps.mode', 'OFF', 'ON'),
                         ('audio.volume', '5', '10')],
    }
    result = format_change_summary(detail)
    assert "2 option(s) changed" in result


def test_format_change_summary_multiple_changes():
    """Summary with multiple change types should list all."""
    detail = {
        'systems_a_only': ['OLD SYS'],
        'systems_b_only': ['NEW SYS'],
        'systems_both': [],
        'talkgroup_diffs': {
            'SYS1': {
                'added': [(100, 'TG1', 'TG One')],
                'removed': [(200, 'TG2', 'TG Two'), (300, 'TG3', 'TG Three')],
            }
        },
        'freq_diffs': {
            'SET1': {
                'added': [851.0125],
                'removed': [],
            }
        },
        'conv_diffs': {},
        'option_diffs': [('gps.mode', 'OFF', 'ON')],
    }
    result = format_change_summary(detail)
    assert "Summary:" in result
    assert "1 system(s) added" in result
    assert "1 system(s) removed" in result
    assert "1 talkgroup(s) added" in result
    assert "2 talkgroup(s) removed" in result
    assert "1 frequency(ies) added" in result
    assert "1 option(s) changed" in result


# ─── CLI diff-report command ─────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_cli_diff_report(capsys):
    """CLI diff-report command should produce output."""
    from quickprs.cli import run_cli
    result = run_cli(["diff-report", str(CLAUDE), str(CLAUDE)])
    assert result == 0
    out = capsys.readouterr().out
    assert "PERSONALITY CHANGE REPORT" in out
    assert "No changes detected" in out


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(),
                     reason="Test PRS data not available")
def test_cli_diff_report_different_files(capsys):
    """CLI diff-report with different files should show changes."""
    from quickprs.cli import run_cli
    result = run_cli(["diff-report", str(PAWS), str(CLAUDE)])
    assert result == 0
    out = capsys.readouterr().out
    assert "PERSONALITY CHANGE REPORT" in out
    assert "Summary:" in out


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_cli_diff_report_output_file(capsys):
    """CLI diff-report should support -o flag."""
    from quickprs.cli import run_cli

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                      mode='w') as f:
        tmp_path = f.name

    try:
        result = run_cli(["diff-report", str(CLAUDE), str(CLAUDE),
                           "-o", tmp_path])
        assert result == 0
        assert Path(tmp_path).exists()
        content = Path(tmp_path).read_text(encoding='utf-8')
        assert "PERSONALITY CHANGE REPORT" in content
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_cli_diff_report_missing_file(capsys):
    """CLI diff-report with missing file should return error."""
    from quickprs.cli import run_cli
    result = run_cli(["diff-report", "nonexistent.PRS", "also_missing.PRS"])
    assert result == 1


# ─── CLI rename command ──────────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_cli_rename_missing_set(capsys):
    """CLI rename with nonexistent set should return error."""
    from quickprs.cli import run_cli
    import tempfile, shutil

    with tempfile.NamedTemporaryFile(suffix=".PRS", delete=False) as f:
        tmp_path = f.name
        shutil.copy2(CLAUDE, tmp_path)

    try:
        result = run_cli(["rename", tmp_path, "--set", "NONEXISTENT",
                           "--pattern", "X", "--replace", "Y"])
        assert result == 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─── CLI sort command ────────────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_cli_sort_missing_set(capsys):
    """CLI sort with nonexistent set should return error."""
    from quickprs.cli import run_cli
    import tempfile, shutil

    with tempfile.NamedTemporaryFile(suffix=".PRS", delete=False) as f:
        tmp_path = f.name
        shutil.copy2(CLAUDE, tmp_path)

    try:
        result = run_cli(["sort", tmp_path, "--set", "NONEXISTENT",
                           "--key", "name"])
        assert result == 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)
