"""Tests for HTML report generation."""

import os
import tempfile
import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.reports import generate_html_report

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


class TestReportGeneration:
    """Test the HTML report generator."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_returns_html_string(self):
        """generate_html_report should return a non-empty HTML string."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert isinstance(html, str)
        assert len(html) > 100
        assert html.startswith("<!DOCTYPE html>")

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_html_structure(self):
        """Report should have proper HTML structure."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs, source_path=str(PAWS))
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html
        assert "<style>" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_summary(self):
        """Report should contain a summary section."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs, source_path=str(PAWS))
        assert "Summary" in html
        assert "File Size" in html
        assert "Sections" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_source_path(self):
        """Report should show the source file path."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs, source_path=str(PAWS))
        assert "PAWSOVERMAWS" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_talkgroups(self):
        """PAWSOVERMAWS report should contain talkgroup data."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "Group Sets" in html
        assert "talkgroups" in html
        # Should have TG ID column headers
        assert "Short Name" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_trunk_sets(self):
        """PAWSOVERMAWS report should contain trunk frequency data."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "Trunk Sets" in html
        assert "frequencies" in html
        assert "TX Freq" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_conv_sets(self):
        """PAWSOVERMAWS report should contain conv channel data."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "Conv Sets" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_iden_sets(self):
        """PAWSOVERMAWS report should contain IDEN set data."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "IDEN Sets" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_radio_options(self):
        """Report should show platformConfig radio options."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "Radio Options" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_contains_capacity(self):
        """Report should include a capacity summary."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        assert "Capacity Summary" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_writes_to_file(self):
        """Report should write to file when filepath is given."""
        prs = parse_prs(PAWS)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        try:
            html = generate_html_report(prs, filepath=path,
                                         source_path=str(PAWS))
            assert os.path.exists(path)
            content = Path(path).read_text(encoding="utf-8")
            assert content == html
            assert len(content) > 100
        finally:
            os.unlink(path)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_tg_counts_match(self):
        """Report should show correct TG counts."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        # The report should mention talkgroup counts somewhere
        from quickprs.record_types import (
            parse_group_section, parse_sets_from_sections,
        )
        grp_sec = prs.get_section_by_class("CP25Group")
        set_sec = prs.get_section_by_class("CP25GroupSet")
        if grp_sec and set_sec:
            sets = parse_sets_from_sections(
                set_sec.raw, grp_sec.raw, parse_group_section)
            total = sum(len(gs.groups) for gs in sets)
            assert str(total) in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_freq_counts_match(self):
        """Report should show correct frequency counts."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        from quickprs.record_types import (
            parse_trunk_channel_section, parse_sets_from_sections,
        )
        ch_sec = prs.get_section_by_class("CTrunkChannel")
        set_sec = prs.get_section_by_class("CTrunkSet")
        if ch_sec and set_sec:
            sets = parse_sets_from_sections(
                set_sec.raw, ch_sec.raw, parse_trunk_channel_section)
            total = sum(len(ts.channels) for ts in sets)
            assert str(total) in html

    def test_report_for_blank_prs(self):
        """Report should work for a blank/minimal PRS file."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        html = generate_html_report(prs)
        assert "<!DOCTYPE html>" in html
        assert "Summary" in html
        # Blank PRS has no talkgroup section headers (h2)
        assert "0 talkgroups" not in html

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_report_for_claude_test(self):
        """Report should work for the claude test PRS."""
        prs = parse_prs(CLAUDE)
        html = generate_html_report(prs, source_path=str(CLAUDE))
        assert "<!DOCTYPE html>" in html
        assert "Summary" in html

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_report_html_escaping(self):
        """Report should HTML-escape any special characters."""
        prs = parse_prs(PAWS)
        html = generate_html_report(prs)
        # Ensure the HTML is well-formed (no unescaped < or > in data)
        assert "<script>" not in html


class TestReportCLI:
    """Test the CLI report command."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_report_command(self, capsys):
        """report subcommand should generate an HTML file."""
        from quickprs.cli import run_cli
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = run_cli(["report", str(PAWS), "-o", out_path])
            assert result == 0
            out = capsys.readouterr().out
            assert "Report written to" in out
            content = Path(out_path).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
        finally:
            os.unlink(out_path)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_report_default_output(self, capsys):
        """report without -o should create .html next to .PRS."""
        from quickprs.cli import run_cli
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy PRS to temp dir
            import shutil
            src = str(PAWS)
            dst = os.path.join(tmpdir, "TEST.PRS")
            shutil.copy2(src, dst)
            result = run_cli(["report", dst])
            assert result == 0
            expected_html = os.path.join(tmpdir, "TEST.html")
            assert os.path.exists(expected_html)
            content = Path(expected_html).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content

    def test_cli_report_nonexistent_file(self):
        """report on nonexistent file should fail."""
        from quickprs.cli import run_cli
        result = run_cli(["report", "nonexistent.PRS"])
        assert result == 1
