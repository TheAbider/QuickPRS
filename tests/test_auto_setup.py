"""Tests for the auto_setup module (one-click RadioReference setup)."""

import pytest
from pathlib import Path

from quickprs.auto_setup import auto_setup_from_rr
from quickprs.prs_parser import parse_prs

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE = TESTDATA / "claude test.PRS"


class MockSiteFreq:
    """Mock site frequency."""
    def __init__(self, freq, use="a"):
        self.freq = freq
        self.use = use


class MockSite:
    """Mock RadioReference site."""
    def __init__(self, name="Test Site", freqs=None, site_number=1,
                 rfss=1, nac="1A3"):
        self.site_id = 1
        self.name = name
        self.site_number = site_number
        self.rfss = rfss
        self.nac = nac
        self.freqs = freqs or []


class MockTalkgroup:
    """Mock RadioReference talkgroup."""
    def __init__(self, dec_id, alpha_tag="", description="",
                 mode="D", encrypted=0, tag="", category_id=0):
        self.dec_id = dec_id
        self.hex_id = f"{dec_id:04X}"
        self.alpha_tag = alpha_tag
        self.description = description
        self.mode = mode
        self.encrypted = encrypted
        self.tag = tag
        self.category_id = category_id


class MockRRSystem:
    """Mock RadioReference system."""
    def __init__(self, sid=9999, name="Test System", sysid="123",
                 wacn="BEE00", system_type="Project 25 Phase I",
                 talkgroups=None, sites=None):
        self.sid = sid
        self.name = name
        self.sysid = sysid
        self.wacn = wacn
        self.system_type = system_type
        self.city = "Test City"
        self.county = "Test County"
        self.state = "WA"
        self.voice = "FDMA"
        self.nac = ""
        self.talkgroups = talkgroups or []
        self.sites = sites or []
        self.categories = []


# ─── Tests ───────────────────────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestAutoSetup:
    """Test the auto_setup_from_rr function."""

    def _make_basic_system(self):
        """Create a basic mock RR system with talkgroups and sites."""
        talkgroups = [
            MockTalkgroup(100, "PD DISP", "Police Dispatch"),
            MockTalkgroup(200, "FD DISP", "Fire Dispatch"),
            MockTalkgroup(300, "EMS OPS", "EMS Operations"),
        ]

        site_freqs = [
            MockSiteFreq(851.0125, use="c"),  # control channel
            MockSiteFreq(851.2625, use="a"),
            MockSiteFreq(851.5125, use="a"),
        ]
        sites = [MockSite("Downtown", freqs=site_freqs)]

        return MockRRSystem(
            sid=8155, name="PSERN", sysid="9D2", wacn="BEE00",
            talkgroups=talkgroups, sites=sites,
        )

    def test_basic_auto_setup(self):
        """Auto-setup should create system, talkgroups, and frequencies."""
        prs = parse_prs(str(CLAUDE))
        rr_system = self._make_basic_system()

        summary = auto_setup_from_rr(prs, rr_system)

        assert summary['talkgroups'] == 3
        assert summary['frequencies'] == 3
        assert summary['sites'] == 1
        assert summary['system_name'] != ""
        assert summary['full_name'] == "PSERN"

    def test_auto_setup_creates_ecc(self):
        """Auto-setup should create ECC entries from control channels."""
        prs = parse_prs(str(CLAUDE))
        rr_system = self._make_basic_system()

        summary = auto_setup_from_rr(prs, rr_system)

        # At least 1 ECC entry from control channel
        assert summary['ecc_entries'] >= 1

    def test_auto_setup_creates_iden(self):
        """Auto-setup should create IDEN entries."""
        prs = parse_prs(str(CLAUDE))
        rr_system = self._make_basic_system()

        summary = auto_setup_from_rr(prs, rr_system)

        assert summary['iden_entries'] >= 1

    def test_auto_setup_empty_system(self):
        """Auto-setup with no talkgroups/freqs should warn but not crash."""
        prs = parse_prs(str(CLAUDE))
        rr_system = MockRRSystem(name="Empty System")

        summary = auto_setup_from_rr(prs, rr_system)

        assert summary['talkgroups'] == 0
        assert summary['frequencies'] == 0

    def test_auto_setup_no_sites(self):
        """Auto-setup with no sites should still work."""
        prs = parse_prs(str(CLAUDE))
        talkgroups = [MockTalkgroup(100, "TEST", "Test TG")]
        rr_system = MockRRSystem(
            name="No Sites", talkgroups=talkgroups,
            sysid="ABC", wacn="12345",
        )

        summary = auto_setup_from_rr(prs, rr_system)

        assert summary['talkgroups'] == 1
        assert summary['ecc_entries'] == 0
        assert summary['sites'] == 0

    def test_auto_setup_with_categories(self):
        """Auto-setup with category filter should limit talkgroups."""
        prs = parse_prs(str(CLAUDE))
        talkgroups = [
            MockTalkgroup(100, "PD DISP", "Police", category_id=1),
            MockTalkgroup(200, "FD DISP", "Fire", category_id=2),
        ]
        rr_system = MockRRSystem(
            name="Filtered", talkgroups=talkgroups,
            sysid="111", wacn="BEE00",
        )

        # Only include category 1
        summary = auto_setup_from_rr(prs, rr_system,
                                     selected_categories={1})

        assert summary['talkgroups'] == 1

    def test_auto_setup_with_tags(self):
        """Auto-setup with tag filter should limit talkgroups."""
        prs = parse_prs(str(CLAUDE))
        talkgroups = [
            MockTalkgroup(100, "PD DISP", "Police", tag="Law Dispatch"),
            MockTalkgroup(200, "FD DISP", "Fire", tag="Fire Dispatch"),
        ]
        rr_system = MockRRSystem(
            name="Tag Filter", talkgroups=talkgroups,
            sysid="222", wacn="BEE00",
        )

        summary = auto_setup_from_rr(prs, rr_system,
                                     selected_tags={"Fire Dispatch"})

        assert summary['talkgroups'] == 1

    def test_auto_setup_summary_keys(self):
        """Summary should contain all expected keys."""
        prs = parse_prs(str(CLAUDE))
        rr_system = self._make_basic_system()

        summary = auto_setup_from_rr(prs, rr_system)

        expected_keys = {
            'system_name', 'full_name', 'sysid', 'wacn',
            'talkgroups', 'frequencies', 'sites',
            'ecc_entries', 'iden_entries',
            'validation_errors', 'validation_warnings', 'warnings',
        }
        assert expected_keys.issubset(set(summary.keys()))

    def test_auto_setup_multiple_sites(self):
        """Auto-setup with multiple sites should aggregate frequencies."""
        prs = parse_prs(str(CLAUDE))

        site1_freqs = [
            MockSiteFreq(851.0125, use="c"),
            MockSiteFreq(851.2625),
        ]
        site2_freqs = [
            MockSiteFreq(851.5125, use="c"),
            MockSiteFreq(851.7625),
        ]

        rr_system = MockRRSystem(
            name="Multi Site", sysid="333", wacn="BEE00",
            talkgroups=[MockTalkgroup(100, "TEST")],
            sites=[
                MockSite("Site 1", freqs=site1_freqs, site_number=1),
                MockSite("Site 2", freqs=site2_freqs, site_number=2),
            ],
        )

        summary = auto_setup_from_rr(prs, rr_system)

        assert summary['frequencies'] == 4
        assert summary['ecc_entries'] >= 2  # one CC per site
        assert summary['sites'] == 2


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
class TestAutoSetupSysidParsing:
    """Test system ID and WACN parsing edge cases."""

    def test_hex_sysid(self):
        """Hex system ID should be parsed correctly."""
        prs = parse_prs(str(CLAUDE))
        rr_system = MockRRSystem(
            name="Hex Test", sysid="9D2", wacn="BEE00",
            talkgroups=[MockTalkgroup(100, "TEST")],
        )
        summary = auto_setup_from_rr(prs, rr_system)
        assert summary['sysid'] == "9D2"

    def test_empty_sysid(self):
        """Empty system ID should not crash."""
        prs = parse_prs(str(CLAUDE))
        rr_system = MockRRSystem(
            name="Empty SID", sysid="", wacn="",
            talkgroups=[MockTalkgroup(100, "TEST")],
        )
        summary = auto_setup_from_rr(prs, rr_system)
        assert summary is not None

    def test_zero_sysid(self):
        """Zero system ID should not crash."""
        prs = parse_prs(str(CLAUDE))
        rr_system = MockRRSystem(
            name="Zero SID", sysid="0", wacn="0",
            talkgroups=[MockTalkgroup(100, "TEST")],
        )
        summary = auto_setup_from_rr(prs, rr_system)
        assert summary is not None
