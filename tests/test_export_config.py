"""Tests for export_config and profile_templates features."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.config_builder import (
    build_from_config, export_config, ConfigError,
    _build_template_cache, _detect_template, _flatten_config,
)
from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.json_io import prs_to_dict
from quickprs.validation import validate_prs, ERROR
from quickprs.profile_templates import (
    list_profile_templates, get_profile_template,
    build_from_profile, PROFILE_TEMPLATES,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"
PATROL_INI = TESTDATA / "example_patrol.ini"
SCANNER_INI = TESTDATA / "example_scanner.ini"


# ─── Export Config: basic functionality ────────────────────────────

class TestExportConfigBasic:
    """Test export_config produces valid INI files."""

    def test_export_blank_prs(self, tmp_path):
        """Export a blank PRS to config."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "blank.ini"
        result = export_config(prs, str(out))
        assert Path(result).exists()
        content = Path(result).read_text(encoding='utf-8')
        assert "[personality]" in content

    def test_export_has_header_comment(self, tmp_path):
        """Exported config has header comments."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "blank.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "# QuickPRS configuration file" in content
        assert "quickprs build" in content

    def test_export_has_source_path(self, tmp_path):
        """Exported config includes source path when provided."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs(filename="TEST.PRS")
        out = tmp_path / "test.ini"
        export_config(prs, str(out), source_path="C:/radio/TEST.PRS")
        content = out.read_text(encoding='utf-8')
        assert "TEST.PRS" in content

    def test_export_personality_name(self, tmp_path):
        """Exported config has correct personality name."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs(filename="MY RADIO.PRS", saved_by="Tester")
        out = tmp_path / "test.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "MY RADIO.PRS" in content
        assert "author = Tester" in content

    def test_export_returns_path(self, tmp_path):
        """export_config returns the output path."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "result.ini"
        result = export_config(prs, str(out))
        assert result == str(out)


# ─── Export Config: built configs ──────────────────────────────────

class TestExportBuiltConfigs:
    """Export configs that were built from INI files."""

    def test_export_patrol(self, tmp_path):
        """Export a patrol config PRS."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[personality]" in content
        assert "PATROL RADIO.PRS" in content

    def test_export_patrol_has_system(self, tmp_path):
        """Exported patrol config has P25 system section."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[system." in content
        assert "type = p25_trunked" in content

    def test_export_patrol_has_frequencies(self, tmp_path):
        """Exported patrol config has frequency section."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert ".frequencies]" in content
        assert "851.0125" in content

    def test_export_patrol_has_talkgroups(self, tmp_path):
        """Exported patrol config has talkgroup section."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert ".talkgroups]" in content

    def test_export_patrol_has_channel_templates(self, tmp_path):
        """Exported patrol config detects MURS template."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "template = murs" in content

    def test_export_patrol_has_noaa_template(self, tmp_path):
        """Exported patrol config detects NOAA template."""
        prs = build_from_config(str(PATROL_INI))
        out = tmp_path / "patrol_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "template = noaa" in content or "template = weather" in content

    def test_export_scanner(self, tmp_path):
        """Export scanner config PRS."""
        prs = build_from_config(str(SCANNER_INI))
        out = tmp_path / "scanner_export.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[personality]" in content
        assert "SCANNER.PRS" in content


# ─── Export Config: PAWSOVERMAWS ───────────────────────────────────

class TestExportPawsovermaws:
    """Export the gold-standard PAWSOVERMAWS personality."""

    @pytest.fixture
    def paws_prs(self):
        if not PAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")
        return parse_prs(PAWS)

    def test_paws_exports(self, paws_prs, tmp_path):
        """PAWSOVERMAWS exports without error."""
        out = tmp_path / "paws.ini"
        result = export_config(paws_prs, str(out), source_path=str(PAWS))
        assert Path(result).exists()

    def test_paws_has_personality(self, paws_prs, tmp_path):
        """Exported PAWS config has personality section."""
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[personality]" in content
        assert "PAWSOVERMAWS.PRS" in content

    def test_paws_has_systems(self, paws_prs, tmp_path):
        """Exported PAWS config has P25 systems."""
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "type = p25_trunked" in content

    def test_paws_has_frequencies(self, paws_prs, tmp_path):
        """Exported PAWS config has trunk frequencies."""
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert ".frequencies]" in content

    def test_paws_has_talkgroups(self, paws_prs, tmp_path):
        """Exported PAWS config has talkgroups."""
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert ".talkgroups]" in content

    def test_paws_has_conv_sets(self, paws_prs, tmp_path):
        """Exported PAWS config has conventional channel sections."""
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[channels." in content

    def test_paws_parseable_ini(self, paws_prs, tmp_path):
        """Exported PAWS config is valid INI that configparser can read."""
        import configparser
        out = tmp_path / "paws.ini"
        export_config(paws_prs, str(out))
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.optionxform = str
        cfg.read(str(out), encoding='utf-8')
        assert cfg.has_section("personality")


# ─── Round-trip: export -> rebuild -> compare ──────────────────────

class TestExportRoundtrip:
    """Export a PRS to config, rebuild from config, verify data matches."""

    def test_patrol_roundtrip_systems(self, tmp_path):
        """Patrol config round-trips: systems match."""
        prs1 = build_from_config(str(PATROL_INI))
        d1 = prs_to_dict(prs1)

        # Export to config
        ini = tmp_path / "patrol_rt.ini"
        export_config(prs1, str(ini))

        # Rebuild from exported config
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        # Compare system counts by type
        p25_1 = [s for s in d1['systems'] if s['type'] == 'P25Trunked']
        p25_2 = [s for s in d2['systems'] if s['type'] == 'P25Trunked']
        assert len(p25_1) == len(p25_2)

    def test_patrol_roundtrip_trunk_freqs(self, tmp_path):
        """Patrol config round-trips: trunk frequencies match."""
        prs1 = build_from_config(str(PATROL_INI))
        d1 = prs_to_dict(prs1)

        ini = tmp_path / "patrol_rt.ini"
        export_config(prs1, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        # Compare trunk set channel counts
        for ts1 in d1.get('trunk_sets', []):
            name = ts1['name'].strip()
            ts2_list = [t for t in d2.get('trunk_sets', [])
                        if t['name'].strip() == name]
            if ts2_list:
                assert len(ts1['channels']) == len(ts2_list[0]['channels'])

    def test_patrol_roundtrip_talkgroups(self, tmp_path):
        """Patrol config round-trips: talkgroup counts match."""
        prs1 = build_from_config(str(PATROL_INI))
        d1 = prs_to_dict(prs1)

        ini = tmp_path / "patrol_rt.ini"
        export_config(prs1, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        for gs1 in d1.get('group_sets', []):
            name = gs1['name'].strip()
            gs2_list = [g for g in d2.get('group_sets', [])
                        if g['name'].strip() == name]
            if gs2_list:
                assert len(gs1['groups']) == len(gs2_list[0]['groups'])

    def test_patrol_roundtrip_conv_sets(self, tmp_path):
        """Patrol config round-trips: conv set counts match."""
        prs1 = build_from_config(str(PATROL_INI))
        d1 = prs_to_dict(prs1)

        ini = tmp_path / "patrol_rt.ini"
        export_config(prs1, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        # Compare conv set counts (excluding default Conv 1)
        cs1 = [c for c in d1.get('conv_sets', [])
               if c['name'].strip() != 'Conv 1']
        cs2 = [c for c in d2.get('conv_sets', [])
               if c['name'].strip() != 'Conv 1']
        assert len(cs1) == len(cs2)

    def test_patrol_roundtrip_validates(self, tmp_path):
        """Round-tripped patrol config validates cleanly."""
        prs1 = build_from_config(str(PATROL_INI))
        ini = tmp_path / "patrol_rt.ini"
        export_config(prs1, str(ini))
        prs2 = build_from_config(str(ini))

        errors = [(s, m) for s, m in validate_prs(prs2) if s == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_scanner_roundtrip_systems(self, tmp_path):
        """Scanner config round-trips: P25 system count matches."""
        prs1 = build_from_config(str(SCANNER_INI))
        d1 = prs_to_dict(prs1)

        ini = tmp_path / "scanner_rt.ini"
        export_config(prs1, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        p25_1 = [s for s in d1['systems'] if s['type'] == 'P25Trunked']
        p25_2 = [s for s in d2['systems'] if s['type'] == 'P25Trunked']
        assert len(p25_1) == len(p25_2)

    @pytest.fixture
    def paws_prs(self):
        if not PAWS.exists():
            pytest.skip("PAWSOVERMAWS.PRS not found")
        return parse_prs(PAWS)

    def test_paws_roundtrip_exports_and_rebuilds(self, paws_prs, tmp_path):
        """PAWSOVERMAWS export -> rebuild produces valid PRS."""
        ini = tmp_path / "paws_rt.ini"
        export_config(paws_prs, str(ini))
        prs2 = build_from_config(str(ini))
        assert prs2 is not None
        raw = prs2.to_bytes()
        assert len(raw) > 100

    def test_paws_roundtrip_system_count(self, paws_prs, tmp_path):
        """PAWSOVERMAWS round-trip preserves named P25 system count.

        PAWSOVERMAWS has chained inline systems (some sharing sets)
        and one empty-name system. These don't round-trip perfectly
        through INI config, so we only compare named systems.
        """
        d1 = prs_to_dict(paws_prs)
        ini = tmp_path / "paws_rt.ini"
        export_config(paws_prs, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        # Count only named systems (non-empty name)
        p25_1 = [s for s in d1.get('systems', [])
                 if s['type'] == 'P25Trunked' and s.get('name', '').strip()]
        p25_2 = [s for s in d2.get('systems', [])
                 if s['type'] == 'P25Trunked' and s.get('name', '').strip()]
        assert len(p25_1) == len(p25_2)

    def test_paws_roundtrip_freq_counts(self, paws_prs, tmp_path):
        """PAWSOVERMAWS round-trip preserves trunk freq counts per set."""
        d1 = prs_to_dict(paws_prs)
        ini = tmp_path / "paws_rt.ini"
        export_config(paws_prs, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        for ts1 in d1.get('trunk_sets', []):
            name = ts1['name'].strip()
            ts2_list = [t for t in d2.get('trunk_sets', [])
                        if t['name'].strip() == name]
            if ts2_list:
                assert (len(ts1['channels']) == len(ts2_list[0]['channels'])), \
                    f"Trunk set {name}: {len(ts1['channels'])} vs " \
                    f"{len(ts2_list[0]['channels'])}"

    def test_paws_roundtrip_tg_counts(self, paws_prs, tmp_path):
        """PAWSOVERMAWS round-trip preserves talkgroup counts per set."""
        d1 = prs_to_dict(paws_prs)
        ini = tmp_path / "paws_rt.ini"
        export_config(paws_prs, str(ini))
        prs2 = build_from_config(str(ini))
        d2 = prs_to_dict(prs2)

        for gs1 in d1.get('group_sets', []):
            name = gs1['name'].strip()
            gs2_list = [g for g in d2.get('group_sets', [])
                        if g['name'].strip() == name]
            if gs2_list:
                assert (len(gs1['groups']) == len(gs2_list[0]['groups'])), \
                    f"Group set {name}: {len(gs1['groups'])} vs " \
                    f"{len(gs2_list[0]['groups'])}"


# ─── Template detection ───────────────────────────────────────────

class TestTemplateDetection:
    """Test the template matching logic."""

    def test_build_template_cache(self):
        """Template cache includes known templates."""
        cache = _build_template_cache()
        assert 'murs' in cache
        assert 'noaa' in cache
        assert 'gmrs' in cache

    def test_detect_murs(self):
        """MURS channels are detected as murs template."""
        from quickprs.templates import get_template_channels
        channels = get_template_channels('murs')
        cache = _build_template_cache()
        ch_dicts = [{'tx_freq': ch['tx_freq']} for ch in channels]
        result = _detect_template(ch_dicts, cache)
        assert result == 'murs'

    def test_detect_noaa(self):
        """NOAA channels are detected as noaa or weather template."""
        from quickprs.templates import get_template_channels
        channels = get_template_channels('noaa')
        cache = _build_template_cache()
        ch_dicts = [{'tx_freq': ch['tx_freq']} for ch in channels]
        result = _detect_template(ch_dicts, cache)
        assert result in ('noaa', 'weather')

    def test_detect_gmrs_or_frs(self):
        """GMRS channels match gmrs or frs (identical frequencies)."""
        from quickprs.templates import get_template_channels
        channels = get_template_channels('gmrs')
        cache = _build_template_cache()
        ch_dicts = [{'tx_freq': ch['tx_freq']} for ch in channels]
        result = _detect_template(ch_dicts, cache)
        # GMRS and FRS have identical frequencies, either match is valid
        assert result in ('gmrs', 'frs')

    def test_detect_custom_no_match(self):
        """Custom channels do not match any template."""
        cache = _build_template_cache()
        custom = [{'tx_freq': 462.123}, {'tx_freq': 462.456}]
        result = _detect_template(custom, cache)
        assert result is None

    def test_detect_empty(self):
        """Empty channel list returns None."""
        cache = _build_template_cache()
        assert _detect_template([], cache) is None


# ─── Config flattening ─────────────────────────────────────────────

class TestFlattenConfig:
    """Test the _flatten_config helper."""

    def test_flat_dict(self):
        result = _flatten_config({'a': '1', 'b': '2'})
        assert ('a', '1') in result
        assert ('b', '2') in result

    def test_nested_dict(self):
        result = _flatten_config({'gps': {'mode': 'ON', 'interval': '30'}})
        assert ('gps.mode', 'ON') in result
        assert ('gps.interval', '30') in result

    def test_deeply_nested(self):
        result = _flatten_config({'a': {'b': {'c': 'val'}}})
        assert ('a.b.c', 'val') in result

    def test_empty_dict(self):
        result = _flatten_config({})
        assert result == []


# ─── CLI: export-config ────────────────────────────────────────────

class TestCLIExportConfig:
    """Test the export-config CLI subcommand."""

    def test_cli_export_config_patrol(self, tmp_path, capsys):
        """CLI export-config on a built patrol PRS."""
        from quickprs.cli import cmd_build, cmd_export_config
        prs_path = str(tmp_path / "patrol.PRS")
        cmd_build(str(PATROL_INI), output=prs_path)
        capsys.readouterr()  # clear output

        ini_path = str(tmp_path / "patrol_out.ini")
        result = cmd_export_config(prs_path, output=ini_path)
        assert result == 0
        assert Path(ini_path).exists()
        out = capsys.readouterr().out
        assert "Exported config" in out

    def test_cli_export_config_default_output(self, tmp_path, capsys):
        """CLI export-config uses .ini extension by default."""
        from quickprs.cli import cmd_build, cmd_export_config
        prs_path = str(tmp_path / "test.PRS")
        cmd_build(str(PATROL_INI), output=prs_path)
        capsys.readouterr()

        result = cmd_export_config(prs_path)
        assert result == 0
        assert (tmp_path / "test.ini").exists()

    def test_cli_export_config_missing_file(self, capsys):
        """CLI export-config on missing file returns 1."""
        from quickprs.cli import cmd_export_config
        result = cmd_export_config("/nonexistent/file.PRS")
        assert result == 1

    def test_cli_export_config_via_run_cli(self, tmp_path, capsys):
        """Test export-config via run_cli()."""
        from quickprs.cli import cmd_build, run_cli
        prs_path = str(tmp_path / "test.PRS")
        cmd_build(str(PATROL_INI), output=prs_path)
        capsys.readouterr()

        ini_path = str(tmp_path / "output.ini")
        result = run_cli(["export-config", prs_path, "-o", ini_path])
        assert result == 0
        assert Path(ini_path).exists()


# ─── Profile Templates: listing ───────────────────────────────────

class TestProfileTemplatesListing:
    """Test profile template listing."""

    def test_list_returns_tuples(self):
        profiles = list_profile_templates()
        assert len(profiles) > 0
        for name, desc in profiles:
            assert isinstance(name, str)
            assert isinstance(desc, str)

    def test_list_has_all_profiles(self):
        profiles = list_profile_templates()
        names = [name for name, desc in profiles]
        assert 'scanner_basic' in names
        assert 'public_safety' in names
        assert 'ham_portable' in names
        assert 'gmrs_family' in names

    def test_list_sorted(self):
        profiles = list_profile_templates()
        names = [name for name, desc in profiles]
        assert names == sorted(names)


# ─── Profile Templates: get ───────────────────────────────────────

class TestProfileTemplatesGet:
    """Test getting individual profile templates."""

    def test_get_scanner_basic(self):
        p = get_profile_template('scanner_basic')
        assert 'noaa' in p['templates']
        assert 'marine' in p['templates']

    def test_get_case_insensitive(self):
        p = get_profile_template('SCANNER_BASIC')
        assert 'noaa' in p['templates']

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile_template('nonexistent_profile')

    def test_get_ham_portable_has_custom_channels(self):
        p = get_profile_template('ham_portable')
        assert len(p['custom_channels']) == 3
        freqs = [ch['tx_freq'] for ch in p['custom_channels']]
        assert 146.520 in freqs


# ─── Profile Templates: build ─────────────────────────────────────

class TestProfileTemplatesBuild:
    """Test building PRS files from profile templates."""

    def test_build_scanner_basic(self):
        prs = build_from_profile('scanner_basic')
        assert prs is not None
        raw = prs.to_bytes()
        assert len(raw) > 100

    def test_build_scanner_roundtrips(self):
        prs = build_from_profile('scanner_basic')
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2

    def test_build_scanner_validates(self):
        prs = build_from_profile('scanner_basic')
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_build_scanner_has_noaa(self):
        prs = build_from_profile('scanner_basic')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        noaa = [c for c in csets if c['name'].strip() == 'NOAA']
        assert len(noaa) == 1
        assert len(noaa[0]['channels']) == 7

    def test_build_scanner_has_marine(self):
        prs = build_from_profile('scanner_basic')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        marine = [c for c in csets if c['name'].strip() == 'MARINE']
        assert len(marine) == 1

    def test_build_public_safety(self):
        prs = build_from_profile('public_safety')
        assert prs is not None
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_build_public_safety_has_interop(self):
        prs = build_from_profile('public_safety')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        interop = [c for c in csets if c['name'].strip() == 'INTEROP']
        assert len(interop) == 1

    def test_build_ham_portable(self):
        prs = build_from_profile('ham_portable')
        assert prs is not None
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_build_ham_portable_has_murs(self):
        prs = build_from_profile('ham_portable')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        murs = [c for c in csets if c['name'].strip() == 'MURS']
        assert len(murs) == 1

    def test_build_ham_portable_has_custom(self):
        prs = build_from_profile('ham_portable')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        custom = [c for c in csets if c['name'].strip() == 'CUSTOM']
        assert len(custom) == 1
        assert len(custom[0]['channels']) == 3

    def test_build_ham_portable_custom_freqs(self):
        prs = build_from_profile('ham_portable')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        custom = [c for c in csets if c['name'].strip() == 'CUSTOM'][0]
        freqs = [ch['tx_freq'] for ch in custom['channels']]
        assert any(abs(f - 146.520) < 0.001 for f in freqs)
        assert any(abs(f - 446.000) < 0.001 for f in freqs)
        assert any(abs(f - 144.390) < 0.001 for f in freqs)

    def test_build_gmrs_family(self):
        prs = build_from_profile('gmrs_family')
        assert prs is not None
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0

    def test_build_gmrs_family_has_all_templates(self):
        prs = build_from_profile('gmrs_family')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        names = [c['name'].strip() for c in csets]
        assert 'GMRS' in names
        assert 'FRS' in names
        assert 'NOAA' in names

    def test_build_gmrs_channel_count(self):
        prs = build_from_profile('gmrs_family')
        d = prs_to_dict(prs)
        csets = d.get('conv_sets', [])
        gmrs = [c for c in csets if c['name'].strip() == 'GMRS']
        assert len(gmrs[0]['channels']) == 22

    def test_build_custom_filename(self):
        prs = build_from_profile('scanner_basic', filename="MYSCANNER.PRS")
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "MYSCANNER.PRS"

    def test_build_default_filename(self):
        prs = build_from_profile('scanner_basic')
        from quickprs.record_types import parse_personality_section
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "SCANNER_BASIC.PRS"

    def test_build_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            build_from_profile('nonexistent_profile')


# ─── Profile Templates: all profiles build and validate ────────────

class TestAllProfilesBuild:
    """Parameterized: build from every profile and validate."""

    @pytest.mark.parametrize("profile_name",
                             sorted(PROFILE_TEMPLATES.keys()))
    def test_profile_builds(self, profile_name):
        prs = build_from_profile(profile_name)
        assert prs is not None

    @pytest.mark.parametrize("profile_name",
                             sorted(PROFILE_TEMPLATES.keys()))
    def test_profile_validates(self, profile_name):
        prs = build_from_profile(profile_name)
        errors = [(s, m) for s, m in validate_prs(prs) if s == ERROR]
        assert len(errors) == 0, f"{profile_name}: {errors}"

    @pytest.mark.parametrize("profile_name",
                             sorted(PROFILE_TEMPLATES.keys()))
    def test_profile_roundtrips(self, profile_name):
        prs = build_from_profile(profile_name)
        raw1 = prs.to_bytes()
        prs2 = parse_prs_bytes(raw1)
        raw2 = prs2.to_bytes()
        assert raw1 == raw2


# ─── CLI: profiles ─────────────────────────────────────────────────

class TestCLIProfiles:
    """Test the CLI profiles subcommand."""

    def test_cli_profiles_list(self, capsys):
        from quickprs.cli import cmd_profiles
        result = cmd_profiles("list")
        assert result == 0
        out = capsys.readouterr().out
        assert "scanner_basic" in out
        assert "ham_portable" in out

    def test_cli_profiles_build(self, tmp_path, capsys):
        from quickprs.cli import cmd_profiles
        out_path = str(tmp_path / "scanner.PRS")
        result = cmd_profiles("build", "scanner_basic", output=out_path)
        assert result == 0
        assert Path(out_path).exists()
        out = capsys.readouterr().out
        assert "Built:" in out

    def test_cli_profiles_build_unknown(self, capsys):
        from quickprs.cli import cmd_profiles
        result = cmd_profiles("build", "nonexistent")
        assert result == 1

    def test_cli_profiles_build_no_name(self, capsys):
        from quickprs.cli import cmd_profiles
        result = cmd_profiles("build")
        assert result == 1

    def test_cli_profiles_build_all(self, tmp_path, capsys):
        """Build all profiles via CLI."""
        from quickprs.cli import cmd_profiles
        for name in sorted(PROFILE_TEMPLATES.keys()):
            out_path = str(tmp_path / f"{name}.PRS")
            result = cmd_profiles("build", name, output=out_path)
            assert result == 0, f"Profile {name} failed"
            capsys.readouterr()

    def test_cli_profiles_list_via_run_cli(self, capsys):
        from quickprs.cli import run_cli
        result = run_cli(["profiles", "list"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Available profile templates" in out

    def test_cli_profiles_build_via_run_cli(self, tmp_path, capsys):
        from quickprs.cli import run_cli
        out_path = str(tmp_path / "ham.PRS")
        result = run_cli(["profiles", "build", "ham_portable",
                          "-o", out_path])
        assert result == 0
        assert Path(out_path).exists()

    def test_cli_profiles_build_default_output(self, tmp_path, capsys,
                                                monkeypatch):
        """Default output is profile name as PRS."""
        from quickprs.cli import cmd_profiles
        monkeypatch.chdir(tmp_path)
        result = cmd_profiles("build", "scanner_basic")
        assert result == 0
        assert (tmp_path / "SCANNER_BASIC.PRS").exists()


# ─── Export blank PRS ──────────────────────────────────────────────

class TestExportBlankPRS:
    """Export a blank PRS and verify the config is minimal."""

    def test_blank_has_personality(self, tmp_path):
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "blank.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[personality]" in content
        assert "name = New Personality.PRS" in content

    def test_blank_skips_default_conv(self, tmp_path):
        """Default Conv 1 set with 1 channel is skipped in export."""
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "blank.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        # Should not have [channels.Conv 1] since it's the default
        assert "[channels.Conv" not in content

    def test_blank_no_systems(self, tmp_path):
        from quickprs.builder import create_blank_prs
        prs = create_blank_prs()
        out = tmp_path / "blank.ini"
        export_config(prs, str(out))
        content = out.read_text(encoding='utf-8')
        assert "[system." not in content
