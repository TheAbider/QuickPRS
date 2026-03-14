"""Tests for personality statistics and summary card features."""

import os
import tempfile
import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from quickprs.validation import compute_statistics, format_statistics
from quickprs.reports import generate_summary_card

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── compute_statistics ─────────────────────────────────────────────

class TestComputeStatistics:
    """Test statistics computation."""

    def test_returns_dict(self):
        """compute_statistics returns a dict."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        assert isinstance(stats, dict)

    def test_has_required_keys(self):
        """Statistics dict contains all required keys."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        required = ['systems', 'channels', 'freq_bands',
                     'talkgroup_analysis', 'channel_types',
                     'ctcss_tones', 'file_info']
        for key in required:
            assert key in stats, f"Missing key: {key}"

    def test_systems_count(self):
        """Systems count is populated."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        sys_info = stats['systems']
        assert sys_info['total'] >= 0
        assert 'p25_trunked' in sys_info
        assert 'conventional' in sys_info
        assert 'p25_conv' in sys_info
        assert 'names' in sys_info

    def test_paws_has_systems(self):
        """PAWSOVERMAWS should have systems."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        assert stats['systems']['total'] > 0

    def test_channels_count(self):
        """Channel counts add up correctly."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        ch = stats['channels']
        assert ch['total'] == (ch['talkgroups'] + ch['trunk_freqs']
                               + ch['conv_channels'])

    def test_freq_bands_populated(self):
        """Frequency bands dict is populated for PAWS."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        # PAWS has trunk frequencies and conv channels
        bands = stats['freq_bands']
        # Should have at least one band
        if stats['channels']['trunk_freqs'] + \
                stats['channels']['conv_channels'] > 0:
            assert len(bands) > 0

    def test_freq_band_classification(self):
        """Frequencies are classified into known bands."""
        from quickprs.validation import _classify_band
        assert _classify_band(155.0) == "VHF"
        assert _classify_band(460.0) == "UHF"
        assert _classify_band(770.0) == "700 MHz"
        assert _classify_band(850.0) == "800 MHz"
        assert _classify_band(900.0) == "900 MHz"
        assert _classify_band(50.0) == "Low Band"
        assert "Other" in _classify_band(1200.0)

    def test_talkgroup_analysis(self):
        """Talkgroup analysis fields are populated."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        tg = stats['talkgroup_analysis']
        assert 'total' in tg
        assert 'tx_enabled' in tg
        assert 'scan_enabled' in tg
        assert 'encrypted' in tg
        assert 'priority' in tg

    def test_tg_analysis_consistency(self):
        """TG analysis counts should be <= total."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        tg = stats['talkgroup_analysis']
        assert tg['tx_enabled'] <= tg['total']
        assert tg['scan_enabled'] <= tg['total']
        assert tg['encrypted'] <= tg['total']
        assert tg['priority'] <= tg['total']

    def test_channel_types(self):
        """Channel types dict has simplex and duplex."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        ct = stats['channel_types']
        assert 'simplex' in ct
        assert 'duplex' in ct
        assert ct['simplex'] >= 0
        assert ct['duplex'] >= 0

    def test_ctcss_tones(self):
        """CTCSS tones dict is populated."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        tones = stats['ctcss_tones']
        assert isinstance(tones, dict)

    def test_file_info(self):
        """File info has size and section count."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        fi = stats['file_info']
        assert fi['size_bytes'] > 0
        assert fi['sections'] > 0

    def test_claude_test_file(self):
        """Statistics work on claude test PRS."""
        prs = parse_prs(CLAUDE)
        stats = compute_statistics(prs)
        assert isinstance(stats, dict)
        assert stats['file_info']['size_bytes'] > 0

    def test_blank_prs(self):
        """Statistics work on blank PRS."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        stats = compute_statistics(prs)
        # Blank PRS may have a default conv system
        assert isinstance(stats, dict)
        assert 'systems' in stats
        assert 'channels' in stats


# ─── format_statistics ──────────────────────────────────────────────

class TestFormatStatistics:
    """Test statistics text formatting."""

    def test_returns_lines(self):
        """format_statistics returns list of strings."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_header_with_filename(self):
        """Header shows filename when given."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats, filename="TEST.PRS")
        assert any("TEST.PRS" in l for l in lines)

    def test_header_without_filename(self):
        """Header works without filename."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats)
        assert any("Radio Statistics" in l for l in lines)

    def test_contains_systems(self):
        """Output contains system information."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats)
        text = "\n".join(lines)
        assert "Systems" in text

    def test_contains_channels(self):
        """Output contains channel information."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats)
        text = "\n".join(lines)
        assert "Total Channels" in text

    def test_contains_file_info(self):
        """Output contains file size information."""
        prs = parse_prs(PAWS)
        stats = compute_statistics(prs)
        lines = format_statistics(stats)
        text = "\n".join(lines)
        assert "bytes" in text

    def test_blank_prs_format(self):
        """Formatting works on blank PRS."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        stats = compute_statistics(prs)
        lines = format_statistics(stats, filename="BLANK.PRS")
        assert len(lines) > 0


# ─── Stats CLI ──────────────────────────────────────────────────────

class TestStatsCLI:
    """Test the stats CLI command."""

    def test_cli_stats(self, capsys):
        """stats command produces output."""
        from quickprs.cli import run_cli
        result = run_cli(["stats", str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Radio Statistics" in out

    def test_cli_stats_claude(self, capsys):
        """stats command works on claude test."""
        from quickprs.cli import run_cli
        result = run_cli(["stats", str(CLAUDE)])
        assert result == 0

    def test_cli_stats_nonexistent(self):
        """stats on nonexistent file should fail."""
        from quickprs.cli import run_cli
        result = run_cli(["stats", "nonexistent.PRS"])
        assert result == 1


# ─── Summary Card ───────────────────────────────────────────────────

class TestSummaryCard:
    """Test summary card generation."""

    def test_returns_html(self):
        """generate_summary_card returns HTML string."""
        prs = parse_prs(PAWS)
        html = generate_summary_card(prs)
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_structure(self):
        """Card has proper HTML structure."""
        prs = parse_prs(PAWS)
        html = generate_summary_card(prs, source_path=str(PAWS))
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html
        assert "<style>" in html

    def test_contains_personality_name(self):
        """Card shows personality name."""
        prs = parse_prs(PAWS)
        html = generate_summary_card(prs, source_path=str(PAWS))
        assert "Quick Reference" in html

    def test_contains_systems(self):
        """Card shows system information."""
        prs = parse_prs(PAWS)
        html = generate_summary_card(prs)
        assert "Systems" in html

    def test_contains_channels_section(self):
        """Card should have channel or talkgroup data."""
        prs = parse_prs(PAWS)
        html = generate_summary_card(prs)
        # Should have either TX talkgroups or conventional channels
        assert "TX Talkgroups" in html or "Conventional" in html or \
               "Summary" in html

    def test_writes_to_file(self):
        """Card writes to file when filepath given."""
        prs = parse_prs(PAWS)
        with tempfile.NamedTemporaryFile(suffix=".html",
                                          delete=False) as f:
            path = f.name
        try:
            html = generate_summary_card(prs, filepath=path,
                                           source_path=str(PAWS))
            assert os.path.exists(path)
            content = Path(path).read_text(encoding="utf-8")
            assert content == html
        finally:
            os.unlink(path)

    def test_claude_test(self):
        """Card works on claude test PRS."""
        prs = parse_prs(CLAUDE)
        html = generate_summary_card(prs, source_path=str(CLAUDE))
        assert "<!DOCTYPE html>" in html

    def test_blank_prs(self):
        """Card works on blank PRS."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        html = generate_summary_card(prs)
        assert "<!DOCTYPE html>" in html
        assert "Summary" in html

    def test_card_compact(self):
        """Card should be significantly smaller than full report."""
        prs = parse_prs(PAWS)
        card = generate_summary_card(prs)
        from quickprs.reports import generate_html_report
        report = generate_html_report(prs)
        # Card should be smaller than the full report
        assert len(card) < len(report)


# ─── Card CLI ───────────────────────────────────────────────────────

class TestCardCLI:
    """Test the card CLI command."""

    def test_cli_card(self, capsys):
        """card command generates HTML file."""
        from quickprs.cli import run_cli
        with tempfile.NamedTemporaryFile(suffix=".html",
                                          delete=False) as f:
            out_path = f.name
        try:
            result = run_cli(["card", str(PAWS), "-o", out_path])
            assert result == 0
            out = capsys.readouterr().out
            assert "Summary card written to" in out
            content = Path(out_path).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
        finally:
            os.unlink(out_path)

    def test_cli_card_default_output(self, capsys):
        """card without -o creates _card.html next to PRS."""
        from quickprs.cli import run_cli
        with tempfile.TemporaryDirectory() as tmpdir:
            import shutil
            dst = os.path.join(tmpdir, "TEST.PRS")
            shutil.copy2(str(PAWS), dst)
            result = run_cli(["card", dst])
            assert result == 0
            expected = os.path.join(tmpdir, "TEST_card.html")
            assert os.path.exists(expected)
            content = Path(expected).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content

    def test_cli_card_nonexistent(self):
        """card on nonexistent file should fail."""
        from quickprs.cli import run_cli
        result = run_cli(["card", "nonexistent.PRS"])
        assert result == 1
