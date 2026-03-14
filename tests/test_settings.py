"""Tests for the settings module — load, save, recent files, defaults."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from quickprs.gui.settings import (
    load_settings, save_settings, add_recent_file, get_recent_files,
    DEFAULTS, MAX_RECENT_FILES, SETTINGS_FILE, SETTINGS_DIR,
)


# ─── DEFAULTS ────────────────────────────────────────────────────────

class TestDefaults:

    def test_defaults_has_required_keys(self):
        """All expected keys are present in DEFAULTS."""
        required = [
            "home_unit_id", "default_nac", "max_scan_talkgroups",
            "scan_enabled_default", "tx_enabled_default",
            "auto_backup", "auto_validate",
            "recent_files", "roaming_mode", "power_level",
        ]
        for key in required:
            assert key in DEFAULTS, f"Missing key: {key}"

    def test_defaults_types(self):
        assert isinstance(DEFAULTS["home_unit_id"], int)
        assert isinstance(DEFAULTS["default_nac"], int)
        assert isinstance(DEFAULTS["max_scan_talkgroups"], int)
        assert isinstance(DEFAULTS["scan_enabled_default"], bool)
        assert isinstance(DEFAULTS["recent_files"], list)

    def test_max_scan_default_is_127(self):
        """127 is the safe maximum (128 breaks scanning)."""
        assert DEFAULTS["max_scan_talkgroups"] == 127

    def test_nac_default_is_zero(self):
        assert DEFAULTS["default_nac"] == 0

    def test_max_recent_files(self):
        assert MAX_RECENT_FILES == 10


# ─── load_settings / save_settings ───────────────────────────────────

class TestLoadSave:

    def test_load_returns_defaults_when_no_file(self):
        """When settings file doesn't exist, return DEFAULTS."""
        with mock.patch("quickprs.gui.settings.SETTINGS_FILE",
                        Path("/nonexistent/settings.json")):
            settings = load_settings()
        assert settings["home_unit_id"] == DEFAULTS["home_unit_id"]
        assert settings["max_scan_talkgroups"] == 127

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            with mock.patch("quickprs.gui.settings.SETTINGS_FILE", path), \
                 mock.patch("quickprs.gui.settings.SETTINGS_DIR", Path(d)):
                settings = {"home_unit_id": 12345, "default_nac": 100}
                save_settings(settings)

                loaded = load_settings()
                assert loaded["home_unit_id"] == 12345
                assert loaded["default_nac"] == 100

    def test_load_merges_with_defaults(self):
        """Saved file with missing keys should get defaults filled in."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            # Write a minimal settings file
            path.write_text('{"home_unit_id": 999}', encoding='utf-8')

            with mock.patch("quickprs.gui.settings.SETTINGS_FILE", path):
                loaded = load_settings()
            assert loaded["home_unit_id"] == 999
            # Missing keys should come from DEFAULTS
            assert loaded["max_scan_talkgroups"] == 127
            assert loaded["auto_backup"] is True

    def test_load_handles_corrupted_json(self):
        """Corrupted JSON file should return defaults, not crash."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{bad json!!!", encoding='utf-8')

            with mock.patch("quickprs.gui.settings.SETTINGS_FILE", path):
                loaded = load_settings()
            assert loaded == dict(DEFAULTS)

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = Path(d) / "nested" / "dir"
            path = subdir / "settings.json"
            with mock.patch("quickprs.gui.settings.SETTINGS_FILE", path), \
                 mock.patch("quickprs.gui.settings.SETTINGS_DIR", subdir):
                save_settings({"test": True})
            assert path.exists()

    def test_save_preserves_unknown_keys(self):
        """Settings dict may have keys not in DEFAULTS — preserve them."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            with mock.patch("quickprs.gui.settings.SETTINGS_FILE", path), \
                 mock.patch("quickprs.gui.settings.SETTINGS_DIR", Path(d)):
                save_settings({"custom_key": "custom_value"})

                raw = json.loads(path.read_text(encoding='utf-8'))
                assert raw["custom_key"] == "custom_value"


# ─── add_recent_file / get_recent_files ──────────────────────────────

class TestRecentFiles:

    def _mock_settings(self, d):
        """Return mocks for settings file in temp dir."""
        path = Path(d) / "settings.json"
        return (
            mock.patch("quickprs.gui.settings.SETTINGS_FILE", path),
            mock.patch("quickprs.gui.settings.SETTINGS_DIR", Path(d)),
        )

    def test_add_recent_file_basic(self):
        with tempfile.TemporaryDirectory() as d:
            m1, m2 = self._mock_settings(d)
            with m1, m2:
                settings = dict(DEFAULTS)
                add_recent_file(settings, "/some/file.prs")
                assert settings["recent_files"][0] == "/some/file.prs"

    def test_add_recent_moves_to_top(self):
        with tempfile.TemporaryDirectory() as d:
            m1, m2 = self._mock_settings(d)
            with m1, m2:
                settings = dict(DEFAULTS)
                settings["recent_files"] = ["/a.prs", "/b.prs", "/c.prs"]
                add_recent_file(settings, "/b.prs")
                assert settings["recent_files"][0] == "/b.prs"
                assert len(settings["recent_files"]) == 3

    def test_add_recent_limits_to_max(self):
        with tempfile.TemporaryDirectory() as d:
            m1, m2 = self._mock_settings(d)
            with m1, m2:
                settings = dict(DEFAULTS)
                settings["recent_files"] = [f"/file{i}.prs"
                                            for i in range(MAX_RECENT_FILES)]
                add_recent_file(settings, "/new.prs")
                assert len(settings["recent_files"]) == MAX_RECENT_FILES
                assert settings["recent_files"][0] == "/new.prs"

    def test_get_recent_filters_nonexistent(self):
        settings = {
            "recent_files": ["/nonexistent/a.prs", "/nonexistent/b.prs"]
        }
        result = get_recent_files(settings)
        assert result == []  # none exist on disk

    def test_get_recent_returns_existing(self):
        with tempfile.TemporaryDirectory() as d:
            real_file = Path(d) / "test.prs"
            real_file.write_bytes(b'\xff\xff')
            settings = {
                "recent_files": [str(real_file), "/nonexistent/b.prs"]
            }
            result = get_recent_files(settings)
            assert len(result) == 1
            assert result[0] == str(real_file)

    def test_get_recent_empty(self):
        settings = {"recent_files": []}
        assert get_recent_files(settings) == []

    def test_get_recent_missing_key(self):
        settings = {}
        assert get_recent_files(settings) == []
