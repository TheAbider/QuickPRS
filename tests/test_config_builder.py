"""Tests for config_builder.py — build PRS from INI config files."""

import configparser
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.config_builder import (
    build_from_config, ConfigError,
    _get_system_sections, _get_channel_sections,
    _parse_freq_lines, _parse_tg_lines, _parse_inline_channels,
)
from quickprs.prs_parser import parse_prs_bytes
from quickprs.validation import validate_prs, ERROR, WARNING
from quickprs.json_io import prs_to_dict

TESTDATA = Path(__file__).parent / "testdata"
PATROL_INI = TESTDATA / "example_patrol.ini"
SCANNER_INI = TESTDATA / "example_scanner.ini"


# ─── Helpers ─────────────────────────────────────────────────────────

def _write_config(tmp_path, content, name="test.ini"):
    """Write INI content to a temp file and return the path."""
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)


def _build(tmp_path, content, name="test.ini"):
    """Build PRS from inline INI config content."""
    path = _write_config(tmp_path, content, name)
    return build_from_config(path)


def _prs_systems(prs):
    """Get system names from a PRS via JSON export."""
    d = prs_to_dict(prs)
    return d.get('systems', [])


def _prs_conv_sets(prs):
    """Get conv set info from a PRS via JSON export."""
    d = prs_to_dict(prs)
    return d.get('conv_sets', [])


def _prs_trunk_sets(prs):
    """Get trunk set info from a PRS via JSON export."""
    d = prs_to_dict(prs)
    return d.get('trunk_sets', [])


def _prs_group_sets(prs):
    """Get group set info from a PRS via JSON export."""
    d = prs_to_dict(prs)
    return d.get('group_sets', [])


# ─── Build from example configs ─────────────────────────────────────

class TestBuildPatrol:
    """Build from the example patrol config."""

    def test_patrol_builds_without_error(self):
        prs = build_from_config(str(PATROL_INI))
        assert prs is not None

    def test_patrol_roundtrips(self):
        prs = build_from_config(str(PATROL_INI))
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_patrol_validates_clean(self):
        prs = build_from_config(str(PATROL_INI))
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_patrol_personality_name(self):
        prs = build_from_config(str(PATROL_INI))
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "PATROL RADIO.PRS"

    def test_patrol_personality_author(self):
        prs = build_from_config(str(PATROL_INI))
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.saved_by == "QuickPRS"

    def test_patrol_has_p25_system(self):
        prs = build_from_config(str(PATROL_INI))
        systems = _prs_systems(prs)
        p25_systems = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25_systems) == 1
        assert p25_systems[0]['name'] == 'PSERN'

    def test_patrol_p25_long_name(self):
        prs = build_from_config(str(PATROL_INI))
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked'][0]
        assert p25['long_name'] == 'PSERN SEATTLE'

    def test_patrol_trunk_frequencies(self):
        prs = build_from_config(str(PATROL_INI))
        tsets = _prs_trunk_sets(prs)
        psern = [t for t in tsets if t['name'].strip() == 'PSERN']
        assert len(psern) == 1
        assert len(psern[0]['channels']) == 5

    def test_patrol_trunk_freq_values(self):
        prs = build_from_config(str(PATROL_INI))
        tsets = _prs_trunk_sets(prs)
        psern = [t for t in tsets if t['name'].strip() == 'PSERN'][0]
        ch0 = psern['channels'][0]
        assert abs(ch0['tx_freq'] - 851.0125) < 0.001
        assert abs(ch0['rx_freq'] - 806.0125) < 0.001

    def test_patrol_talkgroups(self):
        prs = build_from_config(str(PATROL_INI))
        gsets = _prs_group_sets(prs)
        psern = [g for g in gsets if g['name'].strip() == 'PSERN']
        assert len(psern) == 1
        assert len(psern[0]['groups']) == 5

    def test_patrol_talkgroup_values(self):
        prs = build_from_config(str(PATROL_INI))
        gsets = _prs_group_sets(prs)
        psern = [g for g in gsets if g['name'].strip() == 'PSERN'][0]
        # First TG
        tg0 = psern['groups'][0]
        assert tg0['id'] == 1
        assert tg0['short_name'].strip() == 'DISP N'

    def test_patrol_has_murs_channels(self):
        prs = build_from_config(str(PATROL_INI))
        csets = _prs_conv_sets(prs)
        murs = [c for c in csets if c['name'].strip() == 'MURS']
        assert len(murs) == 1
        assert len(murs[0]['channels']) == 5

    def test_patrol_has_noaa_channels(self):
        prs = build_from_config(str(PATROL_INI))
        csets = _prs_conv_sets(prs)
        noaa = [c for c in csets if c['name'].strip() == 'NOAA']
        assert len(noaa) == 1
        assert len(noaa[0]['channels']) == 7

    def test_patrol_has_custom_channels(self):
        prs = build_from_config(str(PATROL_INI))
        csets = _prs_conv_sets(prs)
        custom = [c for c in csets if c['name'].strip() == 'CUSTOM']
        assert len(custom) == 1
        assert len(custom[0]['channels']) == 2

    def test_patrol_custom_channel_tones(self):
        prs = build_from_config(str(PATROL_INI))
        csets = _prs_conv_sets(prs)
        custom = [c for c in csets if c['name'].strip() == 'CUSTOM'][0]
        ch0 = custom['channels'][0]
        assert ch0['short_name'].strip() == 'CH 1'
        assert ch0['tx_tone'] == '100.0'
        assert ch0['rx_tone'] == '100.0'

    def test_patrol_custom_channel_duplex(self):
        prs = build_from_config(str(PATROL_INI))
        csets = _prs_conv_sets(prs)
        custom = [c for c in csets if c['name'].strip() == 'CUSTOM'][0]
        ch1 = custom['channels'][1]
        assert abs(ch1['tx_freq'] - 462.5875) < 0.001
        assert abs(ch1['rx_freq'] - 467.5875) < 0.001

    def test_patrol_conv_system_count(self):
        prs = build_from_config(str(PATROL_INI))
        systems = _prs_systems(prs)
        conv = [s for s in systems if s['type'] == 'Conventional']
        # blank PRS has Conv 1 default + MURS + NOAA + CUSTOM = 4
        assert len(conv) == 4


class TestBuildScanner:
    """Build from the example scanner config."""

    def test_scanner_builds_without_error(self):
        prs = build_from_config(str(SCANNER_INI))
        assert prs is not None

    def test_scanner_roundtrips(self):
        prs = build_from_config(str(SCANNER_INI))
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_scanner_validates_clean(self):
        prs = build_from_config(str(SCANNER_INI))
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_scanner_has_two_p25_systems(self):
        prs = build_from_config(str(SCANNER_INI))
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25) == 2

    def test_scanner_p25_system_names(self):
        prs = build_from_config(str(SCANNER_INI))
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        names = [s['name'].strip() for s in p25]
        long_names = [s.get('long_name', '').strip() for s in p25]
        # First system gets header name; second may derive from long_name
        assert 'KCSO' in names or 'KING CO' in names
        assert any('SEATTLE' in n for n in names + long_names)

    def test_scanner_kcso_freqs(self):
        prs = build_from_config(str(SCANNER_INI))
        tsets = _prs_trunk_sets(prs)
        kcso = [t for t in tsets if t['name'].strip() == 'KCSO']
        assert len(kcso) == 1
        assert len(kcso[0]['channels']) == 3

    def test_scanner_spd_talkgroups(self):
        prs = build_from_config(str(SCANNER_INI))
        gsets = _prs_group_sets(prs)
        spd = [g for g in gsets if g['name'].strip() == 'SPD']
        assert len(spd) == 1
        assert len(spd[0]['groups']) == 3

    def test_scanner_has_noaa(self):
        prs = build_from_config(str(SCANNER_INI))
        csets = _prs_conv_sets(prs)
        noaa = [c for c in csets if c['name'].strip() == 'NOAA']
        assert len(noaa) == 1
        assert len(noaa[0]['channels']) == 7

    def test_scanner_personality_name(self):
        prs = build_from_config(str(SCANNER_INI))
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "SCANNER.PRS"


# ─── Templates only (no P25) ─────────────────────────────────────────

class TestTemplatesOnly:
    """Build with only template channels, no P25."""

    def test_templates_only_builds(self, tmp_path):
        config = """\
[personality]
name = TEMPLATES.PRS

[channels.MURS]
template = murs

[channels.GMRS]
template = gmrs

[channels.FRS]
template = frs

[channels.MARINE]
template = marine

[channels.NOAA]
template = noaa
"""
        prs = _build(tmp_path, config)
        assert prs is not None

    def test_templates_only_roundtrips(self, tmp_path):
        config = """\
[personality]
name = TEMPLATES.PRS

[channels.MURS]
template = murs

[channels.GMRS]
template = gmrs
"""
        prs = _build(tmp_path, config)
        raw1 = prs.to_bytes()
        raw2 = parse_prs_bytes(raw1).to_bytes()
        assert raw1 == raw2

    def test_templates_only_validates(self, tmp_path):
        config = """\
[personality]
name = TEMPLATES.PRS

[channels.MURS]
template = murs
"""
        prs = _build(tmp_path, config)
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_templates_only_no_p25(self, tmp_path):
        config = """\
[personality]
name = TEMPLATES.PRS

[channels.MURS]
template = murs
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25) == 0

    def test_templates_all_five(self, tmp_path):
        config = """\
[personality]
name = TEMPLATES.PRS

[channels.MURS]
template = murs

[channels.GMRS]
template = gmrs

[channels.FRS]
template = frs

[channels.MARINE]
template = marine

[channels.NOAA]
template = noaa
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        # Default Conv 1 + 5 templates = 6
        names = [c['name'].strip() for c in csets]
        assert 'MURS' in names
        assert 'GMRS' in names
        assert 'FRS' in names
        assert 'MARINE' in names
        assert 'NOAA' in names

    def test_murs_channel_count(self, tmp_path):
        config = """\
[channels.MURS]
template = murs
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        murs = [c for c in csets if c['name'].strip() == 'MURS']
        assert len(murs[0]['channels']) == 5

    def test_gmrs_channel_count(self, tmp_path):
        config = """\
[channels.GMRS]
template = gmrs
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        gmrs = [c for c in csets if c['name'].strip() == 'GMRS']
        assert len(gmrs[0]['channels']) == 22

    def test_noaa_channel_count(self, tmp_path):
        config = """\
[channels.NOAA]
template = noaa
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        noaa = [c for c in csets if c['name'].strip() == 'NOAA']
        assert len(noaa[0]['channels']) == 7


# ─── P25 only (no templates) ─────────────────────────────────────────

class TestP25Only:
    """Build with only P25 systems, no template channels."""

    def test_p25_only_builds(self, tmp_path):
        config = """\
[personality]
name = P25ONLY.PRS

[system.TEST]
type = p25_trunked
system_id = 100
long_name = TEST SYSTEM

[system.TEST.frequencies]
1 = 851.0125,806.0125
2 = 851.0375,806.0375

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
2 = 2,TAC 1,Tactical 1
"""
        prs = _build(tmp_path, config)
        assert prs is not None

    def test_p25_only_roundtrips(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.frequencies]
1 = 851.0125,806.0125

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        raw1 = prs.to_bytes()
        raw2 = parse_prs_bytes(raw1).to_bytes()
        assert raw1 == raw2

    def test_p25_only_validates(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.frequencies]
1 = 851.0125,806.0125

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_p25_only_has_system(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.frequencies]
1 = 851.0125,806.0125

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25) == 1
        assert p25[0]['name'].strip() == 'TEST'

    def test_p25_no_conv_templates(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        # Only the default Conv 1 from blank PRS
        assert len(csets) == 1

    def test_p25_system_id(self, tmp_path):
        """P25 system with specific system_id builds cleanly."""
        config = """\
[system.MYNET]
type = p25_trunked
system_id = 42

[system.MYNET.talkgroups]
1 = 100,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25) == 1
        # system_id is stored in WAN entries, not always in the system dict
        d = prs_to_dict(prs)
        wan = d.get('wan_entries', [])
        if wan:
            sids = [e.get('system_id', 0) for e in wan]
            assert 42 in sids

    def test_p25_without_freqs(self, tmp_path):
        """P25 system with no frequencies section — should still build."""
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        tsets = _prs_trunk_sets(prs)
        # No trunk set should be created for this system
        test_tsets = [t for t in tsets if t['name'].strip() == 'TEST']
        assert len(test_tsets) == 0

    def test_p25_without_talkgroups(self, tmp_path):
        """P25 system with no talkgroups section — should still build."""
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.frequencies]
1 = 851.0125,806.0125
"""
        prs = _build(tmp_path, config)
        gsets = _prs_group_sets(prs)
        test_gsets = [g for g in gsets if g['name'].strip() == 'TEST']
        assert len(test_gsets) == 0


# ─── Options section ─────────────────────────────────────────────────

class TestOptionsSection:
    """Test applying options from the [options] section."""

    def test_empty_options_no_crash(self, tmp_path):
        """Empty [options] section should not crash."""
        config = """\
[personality]
name = OPTS.PRS

[options]
"""
        prs = _build(tmp_path, config)
        assert prs is not None

    def test_no_options_section_ok(self, tmp_path):
        """Config without [options] should work fine."""
        config = """\
[personality]
name = NOOPTS.PRS
"""
        prs = _build(tmp_path, config)
        assert prs is not None

    def test_options_validates(self, tmp_path):
        """Config with options still validates."""
        config = """\
[personality]
name = OPTS.PRS

[channels.MURS]
template = murs
"""
        prs = _build(tmp_path, config)
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0


# ─── Error handling ───────────────────────────────────────────────────

class TestErrorHandling:
    """Test error cases in config parsing."""

    def test_missing_config_file(self):
        with pytest.raises(FileNotFoundError):
            build_from_config("/nonexistent/path/config.ini")

    def test_invalid_frequency(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.frequencies]
1 = not_a_number
"""
        with pytest.raises(ConfigError, match="invalid frequency"):
            _build(tmp_path, config)

    def test_invalid_talkgroup_id(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.talkgroups]
1 = abc,DISP,Dispatch
"""
        with pytest.raises(ConfigError, match="invalid talkgroup id"):
            _build(tmp_path, config)

    def test_talkgroup_missing_short_name(self, tmp_path):
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100

[system.TEST.talkgroups]
1 = 100
"""
        with pytest.raises(ConfigError, match="need at least"):
            _build(tmp_path, config)

    def test_orphan_frequencies_section(self, tmp_path):
        """Frequencies section without parent system."""
        config = """\
[system.ORPHAN.frequencies]
1 = 851.0125,806.0125
"""
        with pytest.raises(ConfigError, match="no parent"):
            _build(tmp_path, config)

    def test_orphan_talkgroups_section(self, tmp_path):
        """Talkgroups section without parent system."""
        config = """\
[system.ORPHAN.talkgroups]
1 = 1,DISP,Dispatch
"""
        with pytest.raises(ConfigError, match="no parent"):
            _build(tmp_path, config)

    def test_invalid_template_name(self, tmp_path):
        config = """\
[channels.FAKE]
template = nonexistent_template
"""
        with pytest.raises(ConfigError, match="Unknown template"):
            _build(tmp_path, config)

    def test_channels_no_template_no_data(self, tmp_path):
        config = """\
[channels.EMPTY]
"""
        with pytest.raises(ConfigError, match="no channels found"):
            _build(tmp_path, config)

    def test_bad_option_key_format(self, tmp_path):
        config = """\
[options]
singlekey = value
"""
        # Single-part key (no dot) should raise
        with pytest.raises(ConfigError, match="must be dot-separated"):
            _build(tmp_path, config)


# ─── Inline channels ─────────────────────────────────────────────────

class TestInlineChannels:
    """Test inline channel definitions (not templates)."""

    def test_inline_simplex(self, tmp_path):
        config = """\
[channels.SIMP]
1 = CH 1,462.5625,462.5625,,,Simplex 1
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        simp = [c for c in csets if c['name'].strip() == 'SIMP']
        assert len(simp) == 1
        ch = simp[0]['channels'][0]
        assert abs(ch['tx_freq'] - 462.5625) < 0.001
        assert abs(ch['rx_freq'] - 462.5625) < 0.001

    def test_inline_duplex(self, tmp_path):
        config = """\
[channels.DUP]
1 = RPT 1,462.5625,467.5625,100.0,100.0,Repeater 1
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        dup = [c for c in csets if c['name'].strip() == 'DUP']
        ch = dup[0]['channels'][0]
        assert abs(ch['tx_freq'] - 462.5625) < 0.001
        assert abs(ch['rx_freq'] - 467.5625) < 0.001
        assert ch['tx_tone'] == '100.0'
        assert ch['rx_tone'] == '100.0'

    def test_inline_multiple_channels(self, tmp_path):
        config = """\
[channels.MULT]
1 = CH 1,462.5625,462.5625,,,Channel 1
2 = CH 2,462.5875,462.5875,,,Channel 2
3 = CH 3,462.6125,462.6125,,,Channel 3
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        mult = [c for c in csets if c['name'].strip() == 'MULT']
        assert len(mult[0]['channels']) == 3

    def test_inline_no_tones(self, tmp_path):
        """Channels without tone specifications."""
        config = """\
[channels.BARE]
1 = CH 1,462.5625,462.5625,,,Bare Ch
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        bare = [c for c in csets if c['name'].strip() == 'BARE']
        ch = bare[0]['channels'][0]
        # Empty tones — may be absent or empty string in JSON export
        assert ch.get('tx_tone', '') == ''
        assert ch.get('rx_tone', '') == ''

    def test_inline_short_name_truncation(self, tmp_path):
        """Short names over 8 chars get truncated."""
        config = """\
[channels.TRUNC]
1 = LONGERNAME,462.5625,462.5625,,,A Long Name
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        trunc = [c for c in csets if c['name'].strip() == 'TRUNC']
        ch = trunc[0]['channels'][0]
        assert len(ch['short_name'].strip()) <= 8


# ─── Personality metadata ─────────────────────────────────────────────

class TestPersonalityMetadata:
    """Test personality section configuration."""

    def test_default_personality(self, tmp_path):
        """No [personality] section uses defaults."""
        config = """\
[channels.MURS]
template = murs
"""
        prs = _build(tmp_path, config)
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "New Personality.PRS"

    def test_custom_name(self, tmp_path):
        config = """\
[personality]
name = MY RADIO.PRS
"""
        prs = _build(tmp_path, config)
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "MY RADIO.PRS"

    def test_custom_author(self, tmp_path):
        config = """\
[personality]
author = TestAuthor
"""
        prs = _build(tmp_path, config)
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.saved_by == "TestAuthor"


# ─── Frequency parsing ───────────────────────────────────────────────

class TestFreqParsing:
    """Test _parse_freq_lines helper."""

    def test_tx_rx_pair(self, tmp_path):
        config = """\
[system.T.frequencies]
1 = 851.0125,806.0125
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        freqs = _parse_freq_lines(cfg, 'system.T.frequencies')
        assert len(freqs) == 1
        assert abs(freqs[0][0] - 851.0125) < 0.0001
        assert abs(freqs[0][1] - 806.0125) < 0.0001

    def test_simplex_freq(self, tmp_path):
        """Single frequency (no comma) should use same for TX/RX."""
        config = """\
[system.T.frequencies]
1 = 462.5625
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        freqs = _parse_freq_lines(cfg, 'system.T.frequencies')
        assert abs(freqs[0][0] - 462.5625) < 0.0001
        assert abs(freqs[0][1] - 462.5625) < 0.0001

    def test_multiple_freqs(self, tmp_path):
        config = """\
[system.T.frequencies]
1 = 851.0125,806.0125
2 = 851.0375,806.0375
3 = 851.0625,806.0625
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        freqs = _parse_freq_lines(cfg, 'system.T.frequencies')
        assert len(freqs) == 3


# ─── Talkgroup parsing ──────────────────────────────────────────────

class TestTGParsing:
    """Test _parse_tg_lines helper."""

    def test_basic_tg(self, tmp_path):
        config = """\
[system.T.talkgroups]
1 = 100,DISP,Dispatch
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        tgs = _parse_tg_lines(cfg, 'system.T.talkgroups')
        assert tgs == [(100, 'DISP', 'Dispatch')]

    def test_tg_no_long_name(self, tmp_path):
        """Missing long name defaults to short name."""
        config = """\
[system.T.talkgroups]
1 = 100,DISP
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        tgs = _parse_tg_lines(cfg, 'system.T.talkgroups')
        assert tgs[0] == (100, 'DISP', 'DISP')

    def test_tg_truncation(self, tmp_path):
        """Short name > 8 chars and long name > 16 chars get truncated."""
        config = """\
[system.T.talkgroups]
1 = 100,VERYLONGNAMEHERE,A Very Long Description Name Here
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        tgs = _parse_tg_lines(cfg, 'system.T.talkgroups')
        assert len(tgs[0][1]) <= 8
        assert len(tgs[0][2]) <= 16


# ─── CLI integration ─────────────────────────────────────────────────

class TestCLIBuild:
    """Test the CLI build subcommand."""

    def test_cli_build_patrol(self, tmp_path, capsys):
        from quickprs.cli import cmd_build
        out_path = str(tmp_path / "patrol.PRS")
        result = cmd_build(str(PATROL_INI), output=out_path)
        assert result == 0
        assert Path(out_path).exists()
        out = capsys.readouterr().out
        assert "Built:" in out

    def test_cli_build_scanner(self, tmp_path, capsys):
        from quickprs.cli import cmd_build
        out_path = str(tmp_path / "scanner.PRS")
        result = cmd_build(str(SCANNER_INI), output=out_path)
        assert result == 0
        assert Path(out_path).exists()

    def test_cli_build_missing_config(self, capsys):
        from quickprs.cli import cmd_build
        result = cmd_build("/nonexistent/config.ini")
        assert result == 1

    def test_cli_build_default_output(self, tmp_path, capsys):
        """Default output is same name with .PRS extension."""
        from quickprs.cli import cmd_build
        import shutil
        ini_path = tmp_path / "myradio.ini"
        shutil.copy2(PATROL_INI, ini_path)
        result = cmd_build(str(ini_path))
        assert result == 0
        assert (tmp_path / "myradio.PRS").exists()

    def test_cli_build_via_run_cli(self, tmp_path, capsys):
        """Test via run_cli() argument parsing."""
        from quickprs.cli import run_cli
        out_path = str(tmp_path / "output.PRS")
        result = run_cli([
            "build", str(PATROL_INI), "-o", out_path,
        ])
        assert result == 0
        assert Path(out_path).exists()

    def test_cli_build_config_error(self, tmp_path, capsys):
        """Config error should return 1."""
        from quickprs.cli import cmd_build
        config = """\
[channels.BAD]
"""
        path = tmp_path / "bad.ini"
        path.write_text(config)
        result = cmd_build(str(path))
        assert result == 1
        err = capsys.readouterr().err
        assert "Config error" in err

    def test_cli_build_shows_section_count(self, tmp_path, capsys):
        from quickprs.cli import cmd_build
        out_path = str(tmp_path / "out.PRS")
        cmd_build(str(PATROL_INI), output=out_path)
        out = capsys.readouterr().out
        assert "Sections:" in out

    def test_cli_build_shows_size(self, tmp_path, capsys):
        from quickprs.cli import cmd_build
        out_path = str(tmp_path / "out.PRS")
        cmd_build(str(PATROL_INI), output=out_path)
        out = capsys.readouterr().out
        assert "Size:" in out


# ─── Roundtrip: build -> export-json -> compare ──────────────────────

class TestRoundtripJson:
    """Build from config, export to JSON, and verify values match."""

    def test_patrol_json_roundtrip_systems(self):
        prs = build_from_config(str(PATROL_INI))
        d = prs_to_dict(prs)
        systems = d['systems']
        # Should have both P25 and conv systems
        types = {s['type'] for s in systems}
        assert 'P25Trunked' in types
        assert 'Conventional' in types

    def test_patrol_json_trunk_freqs(self):
        prs = build_from_config(str(PATROL_INI))
        d = prs_to_dict(prs)
        tsets = d['trunk_sets']
        psern = [t for t in tsets if t['name'].strip() == 'PSERN'][0]
        # Verify first and last freq
        assert abs(psern['channels'][0]['tx_freq'] - 851.0125) < 0.001
        assert abs(psern['channels'][4]['tx_freq'] - 851.1125) < 0.001

    def test_patrol_json_talkgroup_ids(self):
        prs = build_from_config(str(PATROL_INI))
        d = prs_to_dict(prs)
        gsets = d['group_sets']
        psern = [g for g in gsets if g['name'].strip() == 'PSERN'][0]
        ids = sorted(g['id'] for g in psern['groups'])
        assert ids == [1, 2, 3, 10, 20]

    def test_scanner_json_two_p25_systems(self):
        prs = build_from_config(str(SCANNER_INI))
        d = prs_to_dict(prs)
        p25 = [s for s in d['systems'] if s['type'] == 'P25Trunked']
        assert len(p25) == 2

    def test_scanner_json_different_system_ids(self):
        prs = build_from_config(str(SCANNER_INI))
        d = prs_to_dict(prs)
        # System IDs are stored in WAN entries
        wan = d.get('wan_entries', [])
        sids = {e.get('system_id', 0) for e in wan}
        assert 1100 in sids
        assert 892 in sids


# ─── Edge cases ───────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_config_builds_blank(self, tmp_path):
        """Completely empty config builds a blank PRS."""
        config = ""
        prs = _build(tmp_path, config)
        assert prs is not None
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_personality_only_builds(self, tmp_path):
        """Config with only [personality] section."""
        config = """\
[personality]
name = MINIMAL.PRS
author = Test
"""
        prs = _build(tmp_path, config)
        assert prs is not None

    def test_system_name_truncation(self, tmp_path):
        """System short name > 8 chars gets truncated."""
        config = """\
[system.VERYLONGNAME]
type = p25_trunked
system_id = 100

[system.VERYLONGNAME.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25[0]['name'].strip()) <= 8

    def test_channel_group_name_truncation(self, tmp_path):
        """Channel group name > 8 chars gets truncated."""
        config = """\
[channels.LONGCHANNELNAME]
template = murs
"""
        prs = _build(tmp_path, config)
        csets = _prs_conv_sets(prs)
        # The set name should be truncated to 8 chars
        for c in csets:
            assert len(c['name'].strip()) <= 8

    def test_wacn_parameter(self, tmp_path):
        """WACN parameter is passed through."""
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100
wacn = 781824

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        # Build succeeds — WACN is stored in WAN section
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_iden_parameters(self, tmp_path):
        """Custom IDEN base/spacing parameters."""
        config = """\
[system.TEST]
type = p25_trunked
system_id = 100
iden_base = 769006250
iden_spacing = 6250

[system.TEST.talkgroups]
1 = 1,DISP,Dispatch
"""
        prs = _build(tmp_path, config)
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_multiple_p25_systems(self, tmp_path):
        """Multiple P25 systems in one config."""
        config = """\
[system.SYS1]
type = p25_trunked
system_id = 100

[system.SYS1.talkgroups]
1 = 1,TG1,Talkgroup 1

[system.SYS2]
type = p25_trunked
system_id = 200

[system.SYS2.talkgroups]
1 = 10,TG10,Talkgroup 10
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        assert len(p25) == 2

    def test_mixed_p25_and_conv(self, tmp_path):
        """Mix of P25 and conventional channels."""
        config = """\
[system.TRUNK]
type = p25_trunked
system_id = 100

[system.TRUNK.talkgroups]
1 = 1,DISP,Dispatch

[channels.MURS]
template = murs

[channels.LOCAL]
1 = RPT 1,462.5625,467.5625,100.0,100.0,Local Rpt 1
"""
        prs = _build(tmp_path, config)
        systems = _prs_systems(prs)
        p25 = [s for s in systems if s['type'] == 'P25Trunked']
        conv = [s for s in systems if s['type'] == 'Conventional']
        assert len(p25) == 1
        assert len(conv) >= 2  # default Conv 1 + MURS + LOCAL

    def test_comments_ignored(self, tmp_path):
        """Comments in config are properly ignored."""
        config = """\
# This is a comment
[personality]
name = COMMENTED.PRS
; This is also a comment
author = Test
"""
        prs = _build(tmp_path, config)
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "COMMENTED.PRS"

    def test_case_preserved_in_names(self, tmp_path):
        """Verify case is preserved in personality names."""
        config = """\
[personality]
name = My Radio.PRS
author = John Doe
"""
        prs = _build(tmp_path, config)
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "My Radio.PRS"
        assert p.saved_by == "John Doe"


# ─── Internal parsing helpers ─────────────────────────────────────────

class TestInternalHelpers:
    """Test internal parsing helper functions."""

    def test_get_system_sections(self, tmp_path):
        config = """\
[system.SYS1]
type = p25_trunked
system_id = 100

[system.SYS1.frequencies]
1 = 851.0125,806.0125

[system.SYS1.talkgroups]
1 = 1,DISP,Dispatch

[system.SYS2]
type = p25_trunked
system_id = 200
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        systems = _get_system_sections(cfg)
        assert 'SYS1' in systems
        assert 'SYS2' in systems
        assert systems['SYS1']['frequencies'] is not None
        assert systems['SYS1']['talkgroups'] is not None
        assert systems['SYS2']['frequencies'] is None
        assert systems['SYS2']['talkgroups'] is None

    def test_get_channel_sections(self, tmp_path):
        config = """\
[channels.MURS]
template = murs

[channels.CUSTOM]
1 = CH 1,462.5625,462.5625,,,Custom 1
"""
        path = _write_config(tmp_path, config)
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(path)
        channels = _get_channel_sections(cfg)
        assert 'MURS' in channels
        assert 'CUSTOM' in channels
        assert channels['MURS']['template'] == 'murs'

    def test_parse_inline_channels_dict(self):
        section = {
            '1': 'CH 1,462.5625,462.5625,100.0,100.0,Custom 1',
            '2': 'CH 2,462.5875,467.5875,,,Custom 2',
        }
        channels = _parse_inline_channels(section)
        assert len(channels) == 2
        assert channels[0]['short_name'] == 'CH 1'
        assert abs(channels[0]['tx_freq'] - 462.5625) < 0.001
        assert channels[0]['tx_tone'] == '100.0'
        assert channels[1]['tx_tone'] == ''

    def test_parse_inline_skips_template_key(self):
        section = {
            'template': 'murs',
            '1': 'CH 1,462.5625,462.5625,,,Custom 1',
        }
        channels = _parse_inline_channels(section)
        assert len(channels) == 1  # template key skipped
