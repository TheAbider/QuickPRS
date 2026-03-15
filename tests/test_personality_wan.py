"""Tests for CPersonality and CP25TrkWan/CP25tWanOpts record types.

Verifies parse/build roundtrip for:
1. CPersonality section — file metadata (filename, GUID, save info)
2. CP25tWanOpts section — WAN entry count
3. CP25TrkWan section — WAN entries (name + WACN + System ID)
"""

import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs
from quickprs.binary_io import read_uint16_le
import pytest
from quickprs.record_types import (
    Personality, parse_personality_section, build_personality_section,
    P25TrkWanEntry, parse_wan_opts_section, build_wan_opts_section,
    parse_wan_section, build_wan_section,
    WAN_ENTRY_SEP,
    parse_class_header, build_class_header,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE_TEST = TESTDATA / "claude test.PRS"
EVERY_OPT = TESTDATA / "every option"


# ─── CPersonality: PAWSOVERMAWS (saved file) ────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestPersonalityPawsovermaws:
    """CPersonality tests using PAWSOVERMAWS.PRS (saved by RPM)."""

    def setup_method(self):
        self.prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        self.sec = self.prs.get_section_by_class("CPersonality")

    def test_section_exists(self):
        assert self.sec is not None
        assert self.sec.class_name == "CPersonality"

    def test_is_first_section(self):
        assert self.prs.sections[0].class_name == "CPersonality"

    def test_section_size(self):
        assert len(self.sec.raw) == 160

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_parse_filename(self):
        p = parse_personality_section(self.sec.raw)
        assert p.filename == "PAWSOVERMAWS.PRS"

    def test_parse_saved_by(self):
        p = parse_personality_section(self.sec.raw)
        assert p.saved_by == "Abider"

    def test_parse_last_saved_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.last_saved == ""

    def test_parse_version(self):
        p = parse_personality_section(self.sec.raw)
        assert p.version == "0014"

    def test_parse_mystery4_saved(self):
        """Saved files have mystery4 = 00000000."""
        p = parse_personality_section(self.sec.raw)
        assert p.mystery4 == b'\x00\x00\x00\x00'

    def test_parse_version_str(self):
        p = parse_personality_section(self.sec.raw)
        assert p.version_str == "1"

    def test_parse_guid(self):
        p = parse_personality_section(self.sec.raw)
        assert p.guid == "0c0c0c0c-0c0c-0c0c-0c0c-0c0c0c0c0c0c"
        assert len(p.guid) == 36

    def test_parse_platform(self):
        p = parse_personality_section(self.sec.raw)
        assert p.platform == "PC"

    def test_parse_save_date(self):
        p = parse_personality_section(self.sec.raw)
        assert p.save_date == "31-10-2025"

    def test_parse_save_time(self):
        p = parse_personality_section(self.sec.raw)
        assert p.save_time == "09:22:23"

    def test_parse_tz_offset(self):
        p = parse_personality_section(self.sec.raw)
        assert p.tz_offset == "- 08:00"

    def test_parse_footer(self):
        p = parse_personality_section(self.sec.raw)
        assert p.footer == b'\x01\x00\x7e\x00\x0d\x00'
        assert len(p.footer) == 6

    def test_roundtrip(self):
        """Parse then rebuild should produce identical bytes."""
        p = parse_personality_section(self.sec.raw)
        rebuilt = build_personality_section(p)
        assert rebuilt == self.sec.raw


# ─── CPersonality: claude test (unsaved file) ───────────────────────

@pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestPersonalityClaudeTest:
    """CPersonality tests using claude test.PRS (never saved by user)."""

    def setup_method(self):
        self.prs = parse_prs(TESTDATA / "claude test.PRS")
        self.sec = self.prs.get_section_by_class("CPersonality")

    def test_section_exists(self):
        assert self.sec is not None

    def test_section_size(self):
        assert len(self.sec.raw) == 92

    def test_parse_filename(self):
        p = parse_personality_section(self.sec.raw)
        assert p.filename == "claude test.PRS"

    def test_parse_saved_by_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.saved_by == ""

    def test_parse_mystery4_unsaved(self):
        """Unsaved files have mystery4 = 01000000."""
        p = parse_personality_section(self.sec.raw)
        assert p.mystery4 == b'\x01\x00\x00\x00'

    def test_parse_guid_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.guid == ""

    def test_parse_platform_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.platform == ""

    def test_parse_date_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.save_date == ""

    def test_parse_time_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.save_time == ""

    def test_parse_tz_empty(self):
        p = parse_personality_section(self.sec.raw)
        assert p.tz_offset == ""

    def test_parse_footer(self):
        p = parse_personality_section(self.sec.raw)
        assert p.footer == b'\x02\x00\x65\x00\x7e\x00\x03\x00'
        assert len(p.footer) == 8

    def test_roundtrip(self):
        p = parse_personality_section(self.sec.raw)
        rebuilt = build_personality_section(p)
        assert rebuilt == self.sec.raw


# ─── CPersonality: base radio (every option) ────────────────────────

@pytest.mark.skipif(not EVERY_OPT.exists(), reason="Test PRS data not available")
class TestPersonalityBaseRadio:
    """CPersonality tests using the base 'new radio' file."""

    def setup_method(self):
        self.prs = parse_prs(
            TESTDATA / "every option" / "new radio - xg 100 portable .PRS")
        self.sec = self.prs.get_section_by_class("CPersonality")

    def test_section_exists(self):
        assert self.sec is not None

    def test_parse_filename(self):
        p = parse_personality_section(self.sec.raw)
        assert p.filename == "new radio.PRS"

    def test_parse_version(self):
        p = parse_personality_section(self.sec.raw)
        assert p.version == "0014"

    def test_roundtrip(self):
        p = parse_personality_section(self.sec.raw)
        rebuilt = build_personality_section(p)
        assert rebuilt == self.sec.raw


# ─── CPersonality: build from scratch ───────────────────────────────

class TestPersonalityBuild:
    """Test building CPersonality sections from scratch."""

    def test_build_minimal(self):
        """Build a minimal personality and verify structure."""
        p = Personality(filename="test.PRS")
        raw = build_personality_section(p)
        # Should start with class header
        assert raw[:2] == b'\xff\xff'
        assert b'CPersonality' in raw
        assert b'test.PRS' in raw

    def test_build_with_guid(self):
        p = Personality(
            filename="MY_FILE.PRS",
            saved_by="TestUser",
            guid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            platform="PC",
            save_date="01-01-2026",
            save_time="12:00:00",
            tz_offset="+ 00:00",
            mystery4=b'\x00\x00\x00\x00',
        )
        raw = build_personality_section(p)
        # Parse it back
        p2 = parse_personality_section(raw)
        assert p2.filename == "MY_FILE.PRS"
        assert p2.saved_by == "TestUser"
        assert p2.guid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert p2.platform == "PC"
        assert p2.save_date == "01-01-2026"
        assert p2.save_time == "12:00:00"
        assert p2.tz_offset == "+ 00:00"
        assert p2.mystery4 == b'\x00\x00\x00\x00'

    def test_build_roundtrip_custom(self):
        """Build, parse, rebuild should be idempotent."""
        p = Personality(
            filename="roundtrip.PRS",
            saved_by="User",
            version="0014",
            version_str="1",
            footer=b'\x01\x00\x7e\x00\x05\x00',
        )
        raw1 = build_personality_section(p)
        p2 = parse_personality_section(raw1)
        raw2 = build_personality_section(p2)
        assert raw1 == raw2

    def test_header_byte1_is_0x85(self):
        """CPersonality uses byte1=0x85 in its class header."""
        p = Personality(filename="test.PRS")
        raw = build_personality_section(p)
        assert raw[2] == 0x85

    def test_kv_delimiter_is_0x08(self):
        """KV block fields are separated by 0x08 bytes."""
        p = Personality(filename="test.PRS", saved_by="Me")
        raw = build_personality_section(p)
        # KV block starts at offset 19 (after header + length byte)
        kv_len = raw[18]
        kv_block = raw[19:19 + kv_len]
        assert kv_block.count(b'\x08') == 8  # 8 delimiters

    def test_empty_fields_produce_empty_lps(self):
        """Empty guid/platform/date/time/tz become zero-length LPS."""
        p = Personality(filename="test.PRS")
        raw = build_personality_section(p)
        p2 = parse_personality_section(raw)
        assert p2.guid == ""
        assert p2.platform == ""
        assert p2.save_date == ""
        assert p2.save_time == ""
        assert p2.tz_offset == ""


# ─── CPersonality: roundtrip all test files ─────────────────────────

@pytest.mark.skipif(not EVERY_OPT.exists(), reason="Test PRS data not available")
class TestPersonalityAllFiles:
    """CPersonality roundtrip across all test PRS files."""

    def test_roundtrip_all_option_files(self):
        """Every option file should roundtrip its CPersonality section."""
        option_dir = TESTDATA / "every option"
        failures = []
        count = 0
        for f in sorted(option_dir.glob("*.PRS")):
            prs = parse_prs(f)
            sec = prs.get_section_by_class("CPersonality")
            if sec is None:
                continue
            count += 1
            p = parse_personality_section(sec.raw)
            rebuilt = build_personality_section(p)
            if rebuilt != sec.raw:
                failures.append(f.name)
        assert count > 0, "No option files found"
        assert failures == [], f"Roundtrip failed for: {failures}"


# ─── CP25tWanOpts ───────────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestWanOpts:
    """CP25tWanOpts section tests."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_parse_pawsovermaws_count(self):
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CP25tWanOpts")
        assert sec is not None
        count = parse_wan_opts_section(sec.raw)
        assert count == 9

    def test_parse_claude_test_count(self):
        prs = parse_prs(TESTDATA / "claude test.PRS")
        sec = prs.get_section_by_class("CP25tWanOpts")
        assert sec is not None
        count = parse_wan_opts_section(sec.raw)
        assert count == 1

    def test_build_wan_opts(self):
        raw = build_wan_opts_section(5)
        assert b'CP25tWanOpts' in raw
        count = parse_wan_opts_section(raw)
        assert count == 5

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_build_roundtrip_pawsovermaws(self):
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CP25tWanOpts")
        count = parse_wan_opts_section(sec.raw)
        rebuilt = build_wan_opts_section(count)
        assert rebuilt == sec.raw

    def test_build_roundtrip_claude_test(self):
        prs = parse_prs(TESTDATA / "claude test.PRS")
        sec = prs.get_section_by_class("CP25tWanOpts")
        count = parse_wan_opts_section(sec.raw)
        rebuilt = build_wan_opts_section(count)
        assert rebuilt == sec.raw

    def test_section_size(self):
        """CP25tWanOpts is always 20 bytes: header(18) + uint16(count)."""
        raw = build_wan_opts_section(0)
        assert len(raw) == 20

    def test_header_byte1(self):
        raw = build_wan_opts_section(1)
        assert raw[2] == 0x64  # byte1 = 0x64


# ─── CP25TrkWan: PAWSOVERMAWS (9 entries) ───────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestWanSectionPawsovermaws:
    """CP25TrkWan tests using PAWSOVERMAWS.PRS (9 WAN entries)."""

    def setup_method(self):
        self.prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        self.sec = self.prs.get_section_by_class("CP25TrkWan")
        self.entries = parse_wan_section(self.sec.raw)

    def test_section_exists(self):
        assert self.sec is not None

    def test_entry_count(self):
        assert len(self.entries) == 9

    def test_entry_count_matches_opts(self):
        opts_sec = self.prs.get_section_by_class("CP25tWanOpts")
        opts_count = parse_wan_opts_section(opts_sec.raw)
        assert len(self.entries) == opts_count

    def test_first_entry_name(self):
        assert self.entries[0].wan_name.strip() == "PSERN"

    def test_first_entry_wacn(self):
        assert self.entries[0].wacn == 0x000BEE00
        assert self.entries[0].wacn == 781824

    def test_first_entry_system_id(self):
        assert self.entries[0].system_id == 939

    def test_all_entry_names(self):
        expected = ["PSERN", "PSRS", "SS911", "WASP",
                    "NNSS", "SNACC", "C/S NSRS", "N NSRS", "S NSRS"]
        actual = [e.wan_name.strip() for e in self.entries]
        assert actual == expected

    def test_psrs_wacn(self):
        """PSRS shares the same WACN as PSERN (0xBEE00)."""
        psrs = self.entries[1]
        assert psrs.wan_name.strip() == "PSRS"
        assert psrs.wacn == 0x000BEE00

    def test_psrs_system_id(self):
        assert self.entries[1].system_id == 940

    def test_ss911_system_id(self):
        assert self.entries[2].system_id == 487

    def test_wasp_system_id(self):
        assert self.entries[3].system_id == 2508

    def test_nnss_different_wacn(self):
        """NNSS (Nevada) has a different WACN from WA systems."""
        nnss = self.entries[4]
        assert nnss.wan_name.strip() == "NNSS"
        assert nnss.wacn == 0x00058544
        assert nnss.wacn == 361796

    def test_nnss_system_id(self):
        assert self.entries[4].system_id == 15

    def test_snacc_entry(self):
        snacc = self.entries[5]
        assert snacc.wan_name.strip() == "SNACC"
        assert snacc.wacn == 0x000BEE00
        assert snacc.system_id == 1121

    def test_nsrs_entries_share_wacn(self):
        """All three NSRS WANs share the same WACN."""
        cs = self.entries[6]
        n = self.entries[7]
        s = self.entries[8]
        assert cs.wacn == n.wacn == s.wacn == 0x00092738

    def test_cs_nsrs_system_id(self):
        assert self.entries[6].system_id == 555

    def test_n_nsrs_system_id(self):
        assert self.entries[7].system_id == 775

    def test_s_nsrs_system_id(self):
        assert self.entries[8].system_id == 777

    def test_section_roundtrip(self):
        """Parse then rebuild should produce identical bytes."""
        rebuilt = build_wan_section(self.entries)
        assert rebuilt == self.sec.raw

    def test_wan_names_padded_to_8(self):
        """All WAN names should be 8 characters (space-padded)."""
        for entry in self.entries:
            assert len(entry.wan_name) == 8, (
                f"WAN name '{entry.wan_name}' length = {len(entry.wan_name)}")


# ─── CP25TrkWan: claude test (1 entry) ──────────────────────────────

@pytest.mark.skipif(not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestWanSectionClaudeTest:
    """CP25TrkWan tests using claude test.PRS (1 WAN entry)."""

    def setup_method(self):
        self.prs = parse_prs(TESTDATA / "claude test.PRS")
        self.sec = self.prs.get_section_by_class("CP25TrkWan")
        self.entries = parse_wan_section(self.sec.raw)

    def test_entry_count(self):
        assert len(self.entries) == 1

    def test_entry_name(self):
        assert self.entries[0].wan_name.strip() == "WA NETWO"

    def test_entry_wacn(self):
        assert self.entries[0].wacn == 0x00045645
        assert self.entries[0].wacn == 284229

    def test_entry_system_id(self):
        assert self.entries[0].system_id == 291

    def test_section_roundtrip(self):
        rebuilt = build_wan_section(self.entries)
        assert rebuilt == self.sec.raw

    def test_no_separator_for_single_entry(self):
        """Single entry should have no trailing separator."""
        rebuilt = build_wan_section(self.entries)
        # Separator is 31 82 — should not appear after the entry
        data_start = rebuilt.index(b'WA NETWO')
        after_entry = rebuilt[data_start + 8 + 6:]  # name(8) + config(6)
        assert WAN_ENTRY_SEP not in after_entry


# ─── CP25TrkWan: build from scratch ─────────────────────────────────

class TestWanBuild:
    """Test building CP25TrkWan sections from scratch."""

    def test_build_single_entry(self):
        entries = [P25TrkWanEntry(wan_name="TEST", wacn=0xBEE00,
                                  system_id=892)]
        raw = build_wan_section(entries)
        assert b'CP25TrkWan' in raw
        parsed = parse_wan_section(raw)
        assert len(parsed) == 1
        assert parsed[0].wan_name.strip() == "TEST"
        assert parsed[0].wacn == 0xBEE00
        assert parsed[0].system_id == 892

    def test_build_multiple_entries(self):
        entries = [
            P25TrkWanEntry(wan_name="SYS_A", wacn=0x11111, system_id=100),
            P25TrkWanEntry(wan_name="SYS_B", wacn=0x22222, system_id=200),
            P25TrkWanEntry(wan_name="SYS_C", wacn=0x33333, system_id=300),
        ]
        raw = build_wan_section(entries)
        parsed = parse_wan_section(raw)
        assert len(parsed) == 3
        for i, orig in enumerate(entries):
            assert parsed[i].wan_name.strip() == orig.wan_name.strip()
            assert parsed[i].wacn == orig.wacn
            assert parsed[i].system_id == orig.system_id

    def test_build_preserves_separator(self):
        """Multi-entry builds have 31 82 separators between entries."""
        entries = [
            P25TrkWanEntry(wan_name="A", wacn=1, system_id=1),
            P25TrkWanEntry(wan_name="B", wacn=2, system_id=2),
        ]
        raw = build_wan_section(entries)
        assert WAN_ENTRY_SEP in raw

    def test_build_no_separator_after_last(self):
        """Last entry should not be followed by a separator."""
        entries = [
            P25TrkWanEntry(wan_name="A", wacn=1, system_id=1),
            P25TrkWanEntry(wan_name="B", wacn=2, system_id=2),
        ]
        raw = build_wan_section(entries)
        # Find the last B entry
        last_b = raw.rfind(b'B')
        after_b = raw[last_b + 8 + 6:]  # name(8 padded) + config(6)
        assert after_b == b''  # nothing after last entry

    def test_wan_name_auto_padding(self):
        """Short WAN names should be padded to 8 characters."""
        entry = P25TrkWanEntry(wan_name="AB", wacn=0, system_id=0)
        raw = entry.to_bytes()
        # LPS: 08 + "AB      "
        assert raw[0] == 8  # length prefix
        assert raw[1:9] == b'AB      '

    def test_wan_name_truncation(self):
        """WAN names longer than 8 chars should be truncated."""
        entry = P25TrkWanEntry(wan_name="TOOLONGNAME", wacn=0, system_id=0)
        raw = entry.to_bytes()
        assert raw[0] == 8  # still 8-char LPS
        assert raw[1:9] == b'TOOLONGN'

    def test_entry_data_size(self):
        """Entry config data (WACN + SysID) is 6 bytes."""
        entry = P25TrkWanEntry(wan_name="TEST", wacn=0xBEE00, system_id=892)
        raw = entry.to_bytes()
        # LPS(8 chars) = 9 bytes, config = 6 bytes, total = 15
        assert len(raw) == 15

    def test_wacn_encoding(self):
        """WACN should be encoded as uint32 LE."""
        entry = P25TrkWanEntry(wan_name="X", wacn=0x000BEE00, system_id=0)
        raw = entry.to_bytes()
        # WACN starts at offset 9 (after LPS)
        wacn_bytes = raw[9:13]
        assert wacn_bytes == b'\x00\xee\x0b\x00'

    def test_system_id_encoding(self):
        """System ID should be encoded as uint16 LE."""
        entry = P25TrkWanEntry(wan_name="X", wacn=0, system_id=939)
        raw = entry.to_bytes()
        # SysID starts at offset 13
        sysid_bytes = raw[13:15]
        assert sysid_bytes == b'\xab\x03'

    def test_build_idempotent(self):
        """Build, parse, rebuild should be identical."""
        entries = [
            P25TrkWanEntry(wan_name="ALPHA", wacn=0xAAAA, system_id=111),
            P25TrkWanEntry(wan_name="BRAVO", wacn=0xBBBB, system_id=222),
        ]
        raw1 = build_wan_section(entries)
        parsed = parse_wan_section(raw1)
        raw2 = build_wan_section(parsed)
        assert raw1 == raw2

    def test_header_byte1(self):
        """CP25TrkWan uses byte1=0x64."""
        entries = [P25TrkWanEntry(wan_name="X", wacn=0, system_id=0)]
        raw = build_wan_section(entries)
        assert raw[2] == 0x64

    def test_header_class_name(self):
        entries = [P25TrkWanEntry(wan_name="X", wacn=0, system_id=0)]
        raw = build_wan_section(entries)
        assert b'CP25TrkWan' in raw


# ─── P25TrkWanEntry dataclass ────────────────────────────────────────

class TestP25TrkWanEntry:
    """Tests for the P25TrkWanEntry dataclass."""

    def test_default_values(self):
        entry = P25TrkWanEntry()
        assert entry.wan_name == ""
        assert entry.wacn == 0
        assert entry.system_id == 0

    def test_entry_data_size_constant(self):
        assert P25TrkWanEntry.ENTRY_DATA_SIZE == 6

    def test_parse_single_entry(self):
        """Parse a WAN entry from raw bytes."""
        # LPS(8, "PSERN   ") + WACN(00ee0b00) + SysID(ab03)
        raw = b'\x08PSERN   \x00\xee\x0b\x00\xab\x03'
        entry, pos = P25TrkWanEntry.parse(raw, 0)
        assert entry.wan_name == "PSERN   "
        assert entry.wacn == 0x000BEE00
        assert entry.system_id == 939
        assert pos == len(raw)

    def test_to_bytes_from_bytes_roundtrip(self):
        raw = b'\x08PSERN   \x00\xee\x0b\x00\xab\x03'
        entry, _ = P25TrkWanEntry.parse(raw, 0)
        rebuilt = entry.to_bytes()
        assert rebuilt == raw

    def test_to_bytes_pads_short_name(self):
        entry = P25TrkWanEntry(wan_name="ABC", wacn=0, system_id=0)
        raw = entry.to_bytes()
        # Should pad to 8: "ABC     "
        assert raw[1:9] == b'ABC     '

    def test_to_bytes_preserves_full_name(self):
        entry = P25TrkWanEntry(wan_name="C/S NSRS", wacn=0, system_id=0)
        raw = entry.to_bytes()
        assert raw[1:9] == b'C/S NSRS'


# ─── Separator constant ─────────────────────────────────────────────

@pytest.mark.skipif(not PAWS.exists() or not CLAUDE_TEST.exists(), reason="Test PRS data not available")
class TestWanSeparator:
    """Verify the WAN entry separator constant."""

    def test_separator_value(self):
        assert WAN_ENTRY_SEP == b'\x31\x82'

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_separator_in_pawsovermaws(self):
        """PAWSOVERMAWS CP25TrkWan section should contain 8 separators (9 entries)."""
        prs = parse_prs(TESTDATA / "PAWSOVERMAWS.PRS")
        sec = prs.get_section_by_class("CP25TrkWan")
        # Count separators in the raw section data (after header)
        _, _, _, data_start = parse_class_header(sec.raw, 0)
        data = sec.raw[data_start:]
        sep_count = 0
        i = 0
        while i < len(data) - 1:
            if data[i:i + 2] == WAN_ENTRY_SEP:
                sep_count += 1
                i += 2
            else:
                i += 1
        assert sep_count == 8  # 9 entries = 8 separators

    def test_no_separator_in_claude_test(self):
        """claude test has 1 WAN entry, so no separators."""
        prs = parse_prs(TESTDATA / "claude test.PRS")
        sec = prs.get_section_by_class("CP25TrkWan")
        _, _, _, data_start = parse_class_header(sec.raw, 0)
        data = sec.raw[data_start:]
        assert WAN_ENTRY_SEP not in data
