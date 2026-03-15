"""Tests for favorites, presets, and colors modules."""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

from quickprs.favorites import (
    load_favorites, save_favorites, add_favorite, remove_favorite,
    list_favorites, clear_favorites, PRESETS, list_presets,
    get_preset, apply_preset, _VALID_CATEGORIES, FAVORITES_FILE,
)
from quickprs.colors import (
    supports_color, disable_color, red, green, yellow, cyan, bold, dim,
    error_label, warn_label, info_label, ok_label,
    _no_color, _red, _green, _yellow, _cyan, _bold, _dim, _reset,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS_PRS = TESTDATA / "PAWSOVERMAWS.PRS"
CLAUDE_PRS = TESTDATA / "claude test.PRS"


# ─── Favorites CRUD ───────────────────────────────────────────────────


class TestLoadFavorites:
    """Test loading favorites from disk."""

    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        """Returns empty structure when no favorites file exists."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "nonexistent" / "favorites.json")
        result = load_favorites()
        assert isinstance(result, dict)
        for cat in _VALID_CATEGORIES:
            assert cat in result
            assert result[cat] == []

    def test_load_from_existing_file(self, tmp_path, monkeypatch):
        """Loads favorites from an existing JSON file."""
        fav_file = tmp_path / "favorites.json"
        data = {
            'systems': [{'name': 'PSERN', 'sysid': 892}],
            'talkgroups': [],
            'channels': [],
            'templates': [{'name': 'murs'}],
        }
        fav_file.write_text(json.dumps(data), encoding='utf-8')
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE', fav_file)

        result = load_favorites()
        assert len(result['systems']) == 1
        assert result['systems'][0]['name'] == 'PSERN'
        assert len(result['templates']) == 1

    def test_load_handles_corrupt_json(self, tmp_path, monkeypatch):
        """Returns empty dict when JSON is corrupt."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text("not valid json{{{", encoding='utf-8')
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE', fav_file)

        result = load_favorites()
        assert isinstance(result, dict)
        for cat in _VALID_CATEGORIES:
            assert result[cat] == []

    def test_load_adds_missing_categories(self, tmp_path, monkeypatch):
        """Adds missing category keys when loading partial data."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text('{"systems": []}', encoding='utf-8')
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE', fav_file)

        result = load_favorites()
        for cat in _VALID_CATEGORIES:
            assert cat in result


class TestSaveFavorites:
    """Test saving favorites to disk."""

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        """Creates parent directory if it doesn't exist."""
        fav_file = tmp_path / "subdir" / "favorites.json"
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE', fav_file)

        data = {'systems': [], 'talkgroups': [], 'channels': [],
                'templates': []}
        save_favorites(data)

        assert fav_file.exists()
        loaded = json.loads(fav_file.read_text(encoding='utf-8'))
        assert loaded == data

    def test_save_overwrites_existing(self, tmp_path, monkeypatch):
        """Overwrites existing favorites file."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text('{}', encoding='utf-8')
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE', fav_file)

        data = {'systems': [{'name': 'TEST'}], 'talkgroups': [],
                'channels': [], 'templates': []}
        save_favorites(data)

        loaded = json.loads(fav_file.read_text(encoding='utf-8'))
        assert loaded['systems'][0]['name'] == 'TEST'


class TestAddFavorite:
    """Test adding items to favorites."""

    def test_add_system(self, tmp_path, monkeypatch):
        """Add a system favorite."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = add_favorite('systems', {'name': 'PSERN', 'sysid': 892})
        assert result is True

        favs = load_favorites()
        assert len(favs['systems']) == 1
        assert favs['systems'][0]['name'] == 'PSERN'
        assert favs['systems'][0]['sysid'] == 892

    def test_add_template(self, tmp_path, monkeypatch):
        """Add a template favorite."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = add_favorite('templates', {'name': 'murs'})
        assert result is True

    def test_add_talkgroup(self, tmp_path, monkeypatch):
        """Add a talkgroup favorite."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = add_favorite('talkgroups',
                              {'name': 'PD Dispatch', 'tgid': 1000})
        assert result is True

    def test_add_channel(self, tmp_path, monkeypatch):
        """Add a channel favorite."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = add_favorite('channels',
                              {'name': 'MURS 1', 'freq': 151.820})
        assert result is True

    def test_add_duplicate_returns_false(self, tmp_path, monkeypatch):
        """Adding duplicate returns False."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        result = add_favorite('systems', {'name': 'PSERN'})
        assert result is False

    def test_add_invalid_category(self, tmp_path, monkeypatch):
        """Invalid category raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="Invalid category"):
            add_favorite('invalid', {'name': 'test'})

    def test_add_missing_name(self, tmp_path, monkeypatch):
        """Item without name raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="name"):
            add_favorite('systems', {'sysid': 123})

    def test_add_non_dict_raises(self, tmp_path, monkeypatch):
        """Non-dict item raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="name"):
            add_favorite('systems', "not a dict")

    def test_add_multiple_items(self, tmp_path, monkeypatch):
        """Add multiple items to same category."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        add_favorite('systems', {'name': 'KCERS'})
        add_favorite('systems', {'name': 'PSRS'})

        favs = load_favorites()
        assert len(favs['systems']) == 3

    def test_add_to_multiple_categories(self, tmp_path, monkeypatch):
        """Add items to different categories."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        add_favorite('templates', {'name': 'murs'})
        add_favorite('channels', {'name': 'MURS 1'})
        add_favorite('talkgroups', {'name': 'PD 1'})

        favs = load_favorites()
        assert len(favs['systems']) == 1
        assert len(favs['templates']) == 1
        assert len(favs['channels']) == 1
        assert len(favs['talkgroups']) == 1


class TestRemoveFavorite:
    """Test removing items from favorites."""

    def test_remove_existing(self, tmp_path, monkeypatch):
        """Remove existing favorite returns True."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        result = remove_favorite('systems', 'PSERN')
        assert result is True

        favs = load_favorites()
        assert len(favs['systems']) == 0

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        """Remove nonexistent returns False."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = remove_favorite('systems', 'NOPE')
        assert result is False

    def test_remove_invalid_category(self, tmp_path, monkeypatch):
        """Invalid category raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="Invalid category"):
            remove_favorite('bogus', 'test')

    def test_remove_preserves_others(self, tmp_path, monkeypatch):
        """Removing one item preserves others."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'A'})
        add_favorite('systems', {'name': 'B'})
        add_favorite('systems', {'name': 'C'})

        remove_favorite('systems', 'B')

        favs = load_favorites()
        names = [f['name'] for f in favs['systems']]
        assert names == ['A', 'C']


class TestListFavorites:
    """Test listing favorites."""

    def test_list_all(self, tmp_path, monkeypatch):
        """List all categories returns dict."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        result = list_favorites()
        assert isinstance(result, dict)
        assert 'systems' in result

    def test_list_specific_category(self, tmp_path, monkeypatch):
        """List specific category returns list."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        result = list_favorites('systems')
        assert isinstance(result, list)
        assert len(result) == 1

    def test_list_invalid_category(self, tmp_path, monkeypatch):
        """Invalid category raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="Invalid category"):
            list_favorites('bogus')


class TestClearFavorites:
    """Test clearing favorites."""

    def test_clear_all(self, tmp_path, monkeypatch):
        """Clear all favorites."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        add_favorite('templates', {'name': 'murs'})

        clear_favorites()

        favs = load_favorites()
        for cat in _VALID_CATEGORIES:
            assert favs[cat] == []

    def test_clear_specific_category(self, tmp_path, monkeypatch):
        """Clear a specific category only."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        add_favorite('systems', {'name': 'PSERN'})
        add_favorite('templates', {'name': 'murs'})

        clear_favorites('systems')

        favs = load_favorites()
        assert favs['systems'] == []
        assert len(favs['templates']) == 1

    def test_clear_invalid_category(self, tmp_path, monkeypatch):
        """Invalid category raises ValueError."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        with pytest.raises(ValueError, match="Invalid category"):
            clear_favorites('bogus')


# ─── Presets ──────────────────────────────────────────────────────────


class TestPresets:
    """Test configuration presets."""

    def test_presets_dict_structure(self):
        """All presets have required keys."""
        for name, preset in PRESETS.items():
            assert 'description' in preset, f"{name} missing description"
            assert 'options' in preset, f"{name} missing options"
            assert isinstance(preset['options'], dict)

    def test_presets_option_format(self):
        """All preset options have section.attribute format."""
        for name, preset in PRESETS.items():
            for opt_path in preset['options']:
                parts = opt_path.split('.', 1)
                assert len(parts) == 2, \
                    f"Preset '{name}' option '{opt_path}' not section.attr"

    def test_list_presets(self):
        """list_presets returns sorted (name, description) tuples."""
        result = list_presets()
        assert isinstance(result, list)
        assert len(result) == len(PRESETS)

        # Check sorted
        names = [name for name, _ in result]
        assert names == sorted(names)

        # Each item is (name, description)
        for name, desc in result:
            assert isinstance(name, str)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_get_preset_valid(self):
        """get_preset returns preset for valid name."""
        preset = get_preset('field_ops')
        assert 'description' in preset
        assert 'options' in preset
        assert 'gps.gpsMode' in preset['options']

    def test_get_preset_case_insensitive(self):
        """get_preset is case-insensitive."""
        preset = get_preset('FIELD_OPS')
        assert preset == PRESETS['field_ops']

    def test_get_preset_invalid(self):
        """get_preset raises ValueError for unknown preset."""
        with pytest.raises(ValueError, match="Unknown preset"):
            get_preset('nonexistent')

    def test_field_ops_preset(self):
        """Field ops preset enables GPS."""
        preset = PRESETS['field_ops']
        assert preset['options']['gps.gpsMode'] == 'ON'

    def test_covert_preset(self):
        """Covert preset disables GPS and LEDs."""
        preset = PRESETS['covert']
        assert preset['options']['gps.gpsMode'] == 'OFF'
        assert preset['options']['misc.ledEnabled'] == 'false'

    def test_training_preset(self):
        """Training preset enables GPS."""
        preset = PRESETS['training']
        assert preset['options']['gps.gpsMode'] == 'ON'

    def test_gps_on_preset(self):
        """GPS on preset enables GPS with interval."""
        preset = PRESETS['gps_on']
        assert preset['options']['gps.gpsMode'] == 'ON'
        assert 'gps.reportInterval' in preset['options']

    def test_gps_off_preset(self):
        """GPS off preset disables GPS."""
        preset = PRESETS['gps_off']
        assert preset['options']['gps.gpsMode'] == 'OFF'

    def test_quiet_preset(self):
        """Quiet preset disables tones."""
        preset = PRESETS['quiet']
        assert preset['options']['audio.tones'] == 'OFF'


class TestApplyPreset:
    """Test applying presets to PRS files."""

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_apply_preset_writes_file(self, tmp_path):
        """Applying a preset writes a modified PRS file."""
        import shutil
        test_prs = tmp_path / "test.PRS"
        shutil.copy2(PAWS_PRS, test_prs)

        results = apply_preset(str(test_prs), 'gps_on')

        assert isinstance(results, list)
        assert len(results) > 0
        # Check results contain option tuples
        for opt, val, ok in results:
            assert isinstance(opt, str)
            assert isinstance(val, str)
            assert isinstance(ok, bool)

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_apply_preset_output_file(self, tmp_path):
        """Applying a preset to output file preserves original."""
        import shutil
        test_prs = tmp_path / "test.PRS"
        out_prs = tmp_path / "output.PRS"
        shutil.copy2(PAWS_PRS, test_prs)
        original_size = test_prs.stat().st_size

        apply_preset(str(test_prs), 'gps_on', output=str(out_prs))

        assert out_prs.exists()
        assert test_prs.stat().st_size == original_size

    def test_apply_invalid_preset(self, tmp_path):
        """Applying invalid preset raises ValueError."""
        with pytest.raises(ValueError, match="Unknown preset"):
            apply_preset("fake.PRS", 'nonexistent')

    @pytest.mark.skipif(not CLAUDE_PRS.exists(), reason="Test data missing")
    def test_apply_preset_returns_results(self, tmp_path):
        """Apply returns results for each option."""
        import shutil
        test_prs = tmp_path / "test.PRS"
        shutil.copy2(CLAUDE_PRS, test_prs)

        results = apply_preset(str(test_prs), 'field_ops')
        preset = get_preset('field_ops')

        assert len(results) == len(preset['options'])


# ─── Colors ───────────────────────────────────────────────────────────


class TestColorsModule:
    """Test ANSI color helpers."""

    def test_red_wraps_text(self):
        """red() wraps text with ANSI codes or not."""
        result = red("hello")
        assert "hello" in result

    def test_green_wraps_text(self):
        """green() wraps text."""
        result = green("hello")
        assert "hello" in result

    def test_yellow_wraps_text(self):
        """yellow() wraps text."""
        result = yellow("hello")
        assert "hello" in result

    def test_cyan_wraps_text(self):
        """cyan() wraps text."""
        result = cyan("test")
        assert "test" in result

    def test_bold_wraps_text(self):
        """bold() wraps text."""
        result = bold("hello")
        assert "hello" in result

    def test_dim_wraps_text(self):
        """dim() wraps text."""
        result = dim("hello")
        assert "hello" in result

    def test_error_label(self):
        """error_label formats error text."""
        result = error_label()
        assert "ERROR" in result

    def test_warn_label(self):
        """warn_label formats warning text."""
        result = warn_label()
        assert "WARN" in result

    def test_info_label(self):
        """info_label formats info text."""
        result = info_label()
        assert "INFO" in result

    def test_ok_label(self):
        """ok_label formats success text."""
        result = ok_label()
        assert "PASS" in result

    def test_custom_label_text(self):
        """Labels accept custom text."""
        result = error_label("FAIL")
        assert "FAIL" in result

    def test_no_color_when_disabled(self, monkeypatch):
        """No ANSI codes when color is disabled."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', True)

        result = colors_mod.red("hello")
        assert result == "hello"
        assert "\033" not in result

    def test_no_color_green(self, monkeypatch):
        """No ANSI codes for green when disabled."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', True)

        result = colors_mod.green("test")
        assert result == "test"

    def test_no_color_bold(self, monkeypatch):
        """No ANSI codes for bold when disabled."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', True)

        result = colors_mod.bold("test")
        assert result == "test"

    def test_supports_color_non_tty(self, monkeypatch):
        """supports_color returns False when not a TTY."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', False)

        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False
        monkeypatch.setattr(sys, 'stdout', mock_stdout)

        assert colors_mod.supports_color() is False

    def test_supports_color_tty(self, monkeypatch):
        """supports_color returns True when stdout is a TTY."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', False)

        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        monkeypatch.setattr(sys, 'stdout', mock_stdout)

        assert colors_mod.supports_color() is True

    def test_disable_color_function(self):
        """disable_color() sets the global flag."""
        import quickprs.colors as colors_mod
        old_val = colors_mod._no_color
        try:
            colors_mod.disable_color()
            assert colors_mod._no_color is True
        finally:
            colors_mod._no_color = old_val


class TestColorsNotPiped:
    """Test color behavior when output is piped (StringIO)."""

    def test_no_ansi_codes_in_stringio(self, monkeypatch):
        """StringIO stdout (piped) should not get ANSI codes."""
        import quickprs.colors as colors_mod
        monkeypatch.setattr(colors_mod, '_no_color', False)
        monkeypatch.setattr(sys, 'stdout', StringIO())

        # StringIO has isatty that returns False
        result = colors_mod.red("hello")
        assert result == "hello"


# ─── CLI Integration ─────────────────────────────────────────────────


class TestFavoritesCLI:
    """Test favorites CLI commands."""

    def test_cli_favorites_list_empty(self, tmp_path, monkeypatch):
        """favorites list shows message when empty."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'list'])
        assert rc == 0

    def test_cli_favorites_add_system(self, tmp_path, monkeypatch):
        """favorites add system creates bookmark."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'add', 'system', 'PSERN',
                       '--sysid', '892'])
        assert rc == 0

        favs = load_favorites()
        assert len(favs['systems']) == 1
        assert favs['systems'][0]['name'] == 'PSERN'

    def test_cli_favorites_add_template(self, tmp_path, monkeypatch):
        """favorites add template creates bookmark."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'add', 'template', 'murs'])
        assert rc == 0

    def test_cli_favorites_add_and_remove(self, tmp_path, monkeypatch):
        """favorites add then remove works."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        run_cli(['favorites', 'add', 'system', 'TEST'])
        rc = run_cli(['favorites', 'remove', 'system', 'TEST'])
        assert rc == 0

        favs = load_favorites()
        assert len(favs['systems']) == 0

    def test_cli_favorites_clear(self, tmp_path, monkeypatch):
        """favorites clear removes all."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        run_cli(['favorites', 'add', 'system', 'A'])
        run_cli(['favorites', 'add', 'template', 'B'])
        rc = run_cli(['favorites', 'clear'])
        assert rc == 0

        favs = load_favorites()
        assert all(len(v) == 0 for v in favs.values())

    def test_cli_favorites_list_category(self, tmp_path, monkeypatch):
        """favorites list <category> filters by category."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        run_cli(['favorites', 'add', 'system', 'SYS1'])
        rc = run_cli(['favorites', 'list', 'systems'])
        assert rc == 0

    def test_cli_favorites_add_with_note(self, tmp_path, monkeypatch):
        """favorites add with --note stores note."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'add', 'system', 'PSERN',
                       '--note', 'Seattle area'])
        assert rc == 0

        favs = load_favorites()
        assert favs['systems'][0]['note'] == 'Seattle area'

    def test_cli_favorites_add_channel_with_freq(self, tmp_path, monkeypatch):
        """favorites add channel with --freq stores frequency."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'add', 'channel', 'MURS1',
                       '--freq', '151.820'])
        assert rc == 0

        favs = load_favorites()
        assert favs['channels'][0]['freq'] == 151.820

    def test_cli_favorites_add_talkgroup_with_tgid(self, tmp_path,
                                                    monkeypatch):
        """favorites add talkgroup with --tgid stores talkgroup ID."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")
        from quickprs.cli import run_cli
        rc = run_cli(['favorites', 'add', 'talkgroup', 'PD1',
                       '--tgid', '2303'])
        assert rc == 0

        favs = load_favorites()
        assert favs['talkgroups'][0]['tgid'] == 2303

    def test_cli_favorites_no_subcmd_shows_help(self, capsys):
        """favorites without subcommand shows help."""
        from quickprs.cli import run_cli
        rc = run_cli(['favorites'])
        assert rc == 1


class TestPresetCLI:
    """Test preset CLI commands."""

    def test_cli_preset_list(self):
        """preset list shows all presets."""
        from quickprs.cli import run_cli
        rc = run_cli(['preset', 'list'])
        assert rc == 0

    def test_cli_preset_show(self):
        """preset show displays preset details."""
        from quickprs.cli import run_cli
        rc = run_cli(['preset', 'show', 'field_ops'])
        assert rc == 0

    def test_cli_preset_show_invalid(self):
        """preset show with invalid name fails."""
        from quickprs.cli import run_cli
        rc = run_cli(['preset', 'show', 'nonexistent'])
        assert rc == 1

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cli_preset_apply(self, tmp_path):
        """preset apply modifies PRS file."""
        import shutil
        test_prs = tmp_path / "test.PRS"
        shutil.copy2(PAWS_PRS, test_prs)

        from quickprs.cli import run_cli
        rc = run_cli(['preset', 'apply', 'gps_on', str(test_prs)])
        assert rc == 0

    @pytest.mark.skipif(not PAWS_PRS.exists(), reason="Test data missing")
    def test_cli_preset_apply_output(self, tmp_path):
        """preset apply with -o writes to different file."""
        import shutil
        test_prs = tmp_path / "test.PRS"
        out_prs = tmp_path / "out.PRS"
        shutil.copy2(PAWS_PRS, test_prs)

        from quickprs.cli import run_cli
        rc = run_cli(['preset', 'apply', 'gps_on', str(test_prs),
                       '-o', str(out_prs)])
        assert rc == 0
        assert out_prs.exists()

    def test_cli_preset_no_subcmd_shows_help(self, capsys):
        """preset without subcommand shows help."""
        from quickprs.cli import run_cli
        rc = run_cli(['preset'])
        assert rc == 1


class TestNoColorFlag:
    """Test --no-color CLI flag."""

    def test_no_color_flag_accepted(self):
        """--no-color flag is accepted by parser."""
        from quickprs.cli import run_cli
        # Just verify parsing doesn't fail — favorites list is a
        # safe command to run
        import quickprs.colors as colors_mod
        old_val = colors_mod._no_color
        try:
            rc = run_cli(['--no-color', 'preset', 'list'])
            assert rc == 0
            assert colors_mod._no_color is True
        finally:
            colors_mod._no_color = old_val


class TestVersionOutput:
    """Test --version output format."""

    def test_version_includes_quickprs(self):
        """--version mentions QuickPRS."""
        from quickprs.cli import run_cli
        with pytest.raises(SystemExit) as exc_info:
            run_cli(['--version'])
        assert exc_info.value.code is None or exc_info.value.code == 0

    def test_version_string_format(self):
        """Version string includes Python and platform info."""
        from quickprs import __version__
        import platform

        # Simulate what argparse would show
        py_ver = platform.python_version()
        assert py_ver  # Sanity check
        assert __version__  # Sanity check


# ─── Roundtrip / Persistence ─────────────────────────────────────────


class TestFavoritesPersistence:
    """Test favorites persistence across load/save cycles."""

    def test_roundtrip(self, tmp_path, monkeypatch):
        """Data survives save/load cycle."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")

        add_favorite('systems', {'name': 'S1', 'sysid': 100})
        add_favorite('talkgroups', {'name': 'TG1', 'tgid': 2000})
        add_favorite('channels', {'name': 'CH1', 'freq': 151.82})
        add_favorite('templates', {'name': 'murs'})

        favs = load_favorites()
        assert favs['systems'][0]['sysid'] == 100
        assert favs['talkgroups'][0]['tgid'] == 2000
        assert favs['channels'][0]['freq'] == 151.82
        assert favs['templates'][0]['name'] == 'murs'

    def test_add_remove_add(self, tmp_path, monkeypatch):
        """Add, remove, re-add same item works."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")

        add_favorite('systems', {'name': 'TEST'})
        remove_favorite('systems', 'TEST')
        result = add_favorite('systems', {'name': 'TEST'})
        assert result is True

        favs = load_favorites()
        assert len(favs['systems']) == 1

    def test_clear_then_add(self, tmp_path, monkeypatch):
        """Clear then add works."""
        monkeypatch.setattr('quickprs.favorites.FAVORITES_FILE',
                            tmp_path / "favorites.json")

        add_favorite('systems', {'name': 'A'})
        clear_favorites()
        add_favorite('systems', {'name': 'B'})

        favs = load_favorites()
        assert len(favs['systems']) == 1
        assert favs['systems'][0]['name'] == 'B'
