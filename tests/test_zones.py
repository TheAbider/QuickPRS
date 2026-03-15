"""Tests for zone planning module."""

import csv
import os
import tempfile
import pytest
from pathlib import Path

from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.zones import (
    Zone, plan_zones, format_zone_plan, validate_zone_plan,
    export_zone_plan_csv, format_zone_plan_csv,
    MAX_CHANNELS_PER_ZONE, MAX_ZONES,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── Zone dataclass ────────────────────────────────────────────────

class TestZoneDataclass:
    """Test the Zone dataclass."""

    def test_zone_creation(self):
        """Zone can be created with name and channels."""
        z = Zone(name="Test Zone", channels=[("SET1", 0), ("SET1", 1)])
        assert z.name == "Test Zone"
        assert len(z.channels) == 2

    def test_zone_is_full(self):
        """Zone reports full at 48 channels."""
        z = Zone(name="Full", channels=[(f"S", i) for i in range(48)])
        assert z.is_full()

    def test_zone_not_full(self):
        """Zone reports not full below 48."""
        z = Zone(name="Partial", channels=[("S", 0)])
        assert not z.is_full()

    def test_zone_remaining(self):
        """remaining() returns correct count."""
        z = Zone(name="Test", channels=[("S", i) for i in range(10)])
        assert z.remaining() == 38

    def test_zone_remaining_full(self):
        """remaining() returns 0 when full."""
        z = Zone(name="Full", channels=[("S", i) for i in range(48)])
        assert z.remaining() == 0

    def test_zone_remaining_over_capacity(self):
        """remaining() returns 0 when over capacity."""
        z = Zone(name="Over", channels=[("S", i) for i in range(60)])
        assert z.remaining() == 0

    def test_max_channels_constant(self):
        """MAX_CHANNELS should be 48."""
        assert Zone.MAX_CHANNELS == 48
        assert MAX_CHANNELS_PER_ZONE == 48


# ─── plan_zones ─────────────────────────────────────────────────────

class TestPlanZones:
    """Test zone planning strategies."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_auto_strategy_paws(self):
        """Auto strategy produces zones from PAWSOVERMAWS."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="auto")
        assert isinstance(zones, list)
        # PAWS has conv and group sets, so should have zones
        assert len(zones) > 0

    @pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
    def test_auto_strategy_claude(self):
        """Auto strategy produces zones from claude test."""
        prs = cached_parse_prs(CLAUDE)
        zones = plan_zones(prs, strategy="auto")
        assert isinstance(zones, list)

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_by_set_strategy(self):
        """by_set strategy produces zones."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="by_set")
        assert isinstance(zones, list)
        assert len(zones) > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_combined_strategy(self):
        """combined strategy merges all channels."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="combined")
        assert isinstance(zones, list)
        # All channels should fit in at least one zone
        if zones:
            total = sum(len(z.channels) for z in zones)
            assert total > 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_manual_strategy_empty(self):
        """manual strategy returns empty plan."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="manual")
        assert zones == []

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_unknown_strategy_raises(self):
        """Unknown strategy should raise ValueError."""
        prs = cached_parse_prs(PAWS)
        with pytest.raises(ValueError, match="Unknown zone strategy"):
            plan_zones(prs, strategy="nonexistent")

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_zones_respect_48_limit(self):
        """All auto-generated zones should have <= 48 channels."""
        prs = cached_parse_prs(PAWS)
        for strategy in ("auto", "by_set", "combined"):
            zones = plan_zones(prs, strategy=strategy)
            for z in zones:
                assert len(z.channels) <= 48, \
                    f"Zone '{z.name}' has {len(z.channels)} channels " \
                    f"(strategy={strategy})"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_zone_names_max_16_chars(self):
        """Auto zone names should be <= 16 chars."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="auto")
        for z in zones:
            assert len(z.name) <= 16, \
                f"Zone name '{z.name}' is {len(z.name)} chars"

    def test_blank_prs(self):
        """Plan zones on blank PRS runs without error."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        zones = plan_zones(prs, strategy="auto")
        # Blank PRS may have a default conv set
        assert isinstance(zones, list)


# ─── format_zone_plan ───────────────────────────────────────────────

class TestFormatZonePlan:
    """Test zone plan text formatting."""

    def test_format_empty(self):
        """Formatting empty plan shows message."""
        lines = format_zone_plan([])
        assert len(lines) == 1
        assert "No zones" in lines[0]

    def test_format_with_zones(self):
        """Formatting zones produces readable output."""
        zones = [
            Zone(name="Zone 1", channels=[("SET1", 0), ("SET1", 1)]),
            Zone(name="Zone 2", channels=[("SET2", 0)]),
        ]
        lines = format_zone_plan(zones)
        assert any("Zone Plan" in l for l in lines)
        assert any("Zone 1" in l for l in lines)
        assert any("Zone 2" in l for l in lines)

    def test_format_shows_counts(self):
        """Format should show channel counts."""
        zones = [
            Zone(name="Test", channels=[("S", i) for i in range(10)]),
        ]
        lines = format_zone_plan(zones)
        text = "\n".join(lines)
        assert "10/48" in text

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_format_from_prs(self):
        """Format zone plan from real PRS data."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="auto")
        lines = format_zone_plan(zones)
        assert len(lines) > 0
        assert any("Zone Plan" in l for l in lines)


# ─── validate_zone_plan ─────────────────────────────────────────────

class TestValidateZonePlan:
    """Test zone plan validation."""

    def test_valid_plan(self):
        """A normal plan should have no errors."""
        zones = [
            Zone(name="Zone 1", channels=[("S", i) for i in range(10)]),
        ]
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert len(errors) == 0

    def test_too_many_channels(self):
        """Exceeding 48 channels produces error."""
        zones = [
            Zone(name="Big", channels=[("S", i) for i in range(60)]),
        ]
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert len(errors) == 1
        assert "60" in errors[0][1]

    def test_too_many_zones(self):
        """Exceeding 50 zones produces error."""
        zones = [Zone(name=f"Z{i}", channels=[("S", 0)])
                 for i in range(51)]
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert any("51" in e[1] for e in errors)

    def test_empty_zone_warning(self):
        """Empty zone produces warning."""
        zones = [Zone(name="Empty", channels=[])]
        issues = validate_zone_plan(zones)
        warnings = [i for i in issues if i[0] == "warning"]
        assert any("empty" in w[1].lower() for w in warnings)

    def test_long_name_warning(self):
        """Zone name > 16 chars produces warning."""
        zones = [Zone(name="A" * 20,
                      channels=[("S", 0)])]
        issues = validate_zone_plan(zones)
        warnings = [i for i in issues if i[0] == "warning"]
        assert any("16" in w[1] for w in warnings)

    def test_duplicate_name_warning(self):
        """Duplicate zone names produce warning."""
        zones = [
            Zone(name="Same", channels=[("S", 0)]),
            Zone(name="Same", channels=[("S", 1)]),
        ]
        issues = validate_zone_plan(zones)
        warnings = [i for i in issues if i[0] == "warning"]
        assert any("Duplicate" in w[1] for w in warnings)

    def test_exactly_48_no_error(self):
        """Exactly 48 channels should not produce error."""
        zones = [Zone(name="Full",
                      channels=[("S", i) for i in range(48)])]
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert len(errors) == 0

    def test_exactly_50_zones_no_error(self):
        """Exactly 50 zones should not produce error."""
        zones = [Zone(name=f"Z{i}", channels=[("S", 0)])
                 for i in range(50)]
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert len(errors) == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_prs_auto_plan_validates(self):
        """Auto plan from real PRS should validate cleanly."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="auto")
        issues = validate_zone_plan(zones)
        errors = [i for i in issues if i[0] == "error"]
        assert len(errors) == 0


# ─── CSV export ──────────────────────────────────────────────────────

class TestZoneCSVExport:
    """Test zone plan CSV export."""

    def test_export_to_file(self):
        """export_zone_plan_csv writes valid CSV."""
        zones = [
            Zone(name="Zone 1", channels=[("SET1", 0), ("SET1", 1)]),
            Zone(name="Zone 2", channels=[("SET2", 0)]),
        ]
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False,
                                          mode='w') as f:
            path = f.name
        try:
            export_zone_plan_csv(zones, path)
            with open(path, 'r', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
            # Header + 3 data rows
            assert len(rows) == 4
            assert rows[0] == ["zone_number", "zone_name",
                                "set_name", "channel_index"]
            assert rows[1][1] == "Zone 1"
            assert rows[3][1] == "Zone 2"
        finally:
            os.unlink(path)

    def test_format_csv_string(self):
        """format_zone_plan_csv returns CSV text."""
        zones = [
            Zone(name="Test", channels=[("S", 0)]),
        ]
        text = format_zone_plan_csv(zones)
        assert "zone_number" in text
        assert "Test" in text

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_export_from_prs(self):
        """Export zone plan from real PRS to CSV."""
        prs = cached_parse_prs(PAWS)
        zones = plan_zones(prs, strategy="auto")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False,
                                          mode='w') as f:
            path = f.name
        try:
            export_zone_plan_csv(zones, path)
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "zone_number" in content
        finally:
            os.unlink(path)


# ─── CLI integration ────────────────────────────────────────────────

class TestZonesCLI:
    """Test the zones CLI command."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_zones_auto(self, capsys):
        """zones command with auto strategy."""
        from quickprs.cli import run_cli
        result = run_cli(["zones", str(PAWS)])
        assert result == 0
        out = capsys.readouterr().out
        assert "Zone Plan" in out or "No zones" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_zones_by_set(self, capsys):
        """zones command with by_set strategy."""
        from quickprs.cli import run_cli
        result = run_cli(["zones", str(PAWS), "--strategy", "by_set"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_zones_combined(self, capsys):
        """zones command with combined strategy."""
        from quickprs.cli import run_cli
        result = run_cli(["zones", str(PAWS), "--strategy", "combined"])
        assert result == 0

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_zones_manual(self, capsys):
        """zones command with manual strategy returns empty."""
        from quickprs.cli import run_cli
        result = run_cli(["zones", str(PAWS), "--strategy", "manual"])
        assert result == 0
        out = capsys.readouterr().out
        assert "No zones" in out

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_cli_zones_export(self, capsys):
        """zones --export writes CSV."""
        from quickprs.cli import run_cli
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            result = run_cli(["zones", str(PAWS), "--export", path])
            assert result == 0
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "zone_number" in content
        finally:
            os.unlink(path)

    def test_cli_zones_nonexistent_file(self):
        """zones on nonexistent file should fail."""
        from quickprs.cli import run_cli
        result = run_cli(["zones", "nonexistent.PRS"])
        assert result == 1
