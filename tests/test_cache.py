"""Tests for cache.py — local JSON cache for RadioReference data."""

import json
import pytest
from pathlib import Path

from quickprs.cache import (
    save_system, load_system, list_cached_systems, delete_cached_system,
)
from quickprs.radioreference import RRSystem, RRTalkgroup, RRSite, RRSiteFreq


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Override CACHE_DIR to use a temp directory."""
    monkeypatch.setattr('quickprs.cache.CACHE_DIR', tmp_path)
    return tmp_path


def _make_test_system():
    """Build a minimal RRSystem for testing."""
    system = RRSystem(
        sid=11628,
        name="PSERN",
        system_type="Project 25 Phase II",
        sysid="37C",
        wacn="BEE00",
        nac="37C",
        voice="FDMA/TDMA",
        city="Seattle",
        state="Washington",
        county="King",
    )
    system.talkgroups = [
        RRTalkgroup(
            dec_id=2303, hex_id="8FF",
            alpha_tag="ALG PD 1", description="Algona PD Tac 1",
            mode="D", encrypted=0,
            tag="Law Dispatch", category="Law Enforcement",
            category_id=1,
        ),
        RRTalkgroup(
            dec_id=2304, hex_id="900",
            alpha_tag="ALG PD 2", description="Algona PD Tac 2",
            mode="D", encrypted=0,
            tag="Law Tac", category="Law Enforcement",
            category_id=1,
        ),
    ]
    system.sites = [
        RRSite(
            site_id=1, site_number="001",
            name="Seattle Downtown",
            rfss=1, nac="37C",
            county="King", lat=47.6, lon=-122.3,
            range_miles=15.0,
            freqs=[
                RRSiteFreq(freq=851.8875, lcn=1, use="a"),
                RRSiteFreq(freq=851.2625, lcn=2, use="a"),
            ],
        ),
    ]
    return system


class TestCacheRoundtrip:

    def test_save_and_load(self, tmp_cache):
        """Save a system, load it back, verify all fields."""
        system = _make_test_system()
        path = save_system(system, source="test")
        assert path.exists()
        assert path.suffix == ".json"

        loaded = load_system(path)
        assert loaded.sid == 11628
        assert loaded.name == "PSERN"
        assert loaded.system_type == "Project 25 Phase II"
        assert loaded.sysid == "37C"
        assert loaded.wacn == "BEE00"
        assert loaded.city == "Seattle"
        assert loaded.state == "Washington"

    def test_talkgroups_survive_roundtrip(self, tmp_cache):
        system = _make_test_system()
        path = save_system(system)
        loaded = load_system(path)

        assert len(loaded.talkgroups) == 2
        tg = loaded.talkgroups[0]
        assert tg.dec_id == 2303
        assert tg.hex_id == "8FF"
        assert tg.alpha_tag == "ALG PD 1"
        assert tg.description == "Algona PD Tac 1"
        assert tg.mode == "D"
        assert tg.encrypted == 0
        assert tg.tag == "Law Dispatch"
        assert tg.category == "Law Enforcement"

    def test_sites_survive_roundtrip(self, tmp_cache):
        system = _make_test_system()
        path = save_system(system)
        loaded = load_system(path)

        assert len(loaded.sites) == 1
        site = loaded.sites[0]
        assert site.site_id == 1
        assert site.name == "Seattle Downtown"
        assert site.rfss == 1
        assert site.county == "King"
        assert abs(site.lat - 47.6) < 0.01
        assert abs(site.lon - (-122.3)) < 0.01

        assert len(site.freqs) == 2
        assert abs(site.freqs[0].freq - 851.8875) < 0.001
        assert site.freqs[0].lcn == 1

    def test_save_creates_valid_json(self, tmp_cache):
        system = _make_test_system()
        path = save_system(system)

        with open(path, 'r') as f:
            data = json.load(f)

        assert 'cached_at' in data
        assert data['source'] == 'paste'
        assert data['sid'] == 11628
        assert len(data['talkgroups']) == 2
        assert len(data['sites']) == 1


class TestCacheListing:

    def test_list_empty(self, tmp_cache):
        results = list_cached_systems()
        assert results == []

    def test_list_after_save(self, tmp_cache):
        system = _make_test_system()
        save_system(system)

        results = list_cached_systems()
        assert len(results) == 1
        filepath, name, cached_at, tg_count = results[0]
        assert name == "PSERN"
        assert tg_count == 2
        assert cached_at != ""

    def test_list_multiple(self, tmp_cache):
        sys1 = _make_test_system()
        sys1.name = "System A"
        save_system(sys1)

        sys2 = _make_test_system()
        sys2.name = "System B"
        sys2.sid = 99999
        save_system(sys2)

        results = list_cached_systems()
        assert len(results) == 2
        names = {r[1] for r in results}
        assert "System A" in names
        assert "System B" in names


class TestCacheDelete:

    def test_delete(self, tmp_cache):
        system = _make_test_system()
        path = save_system(system)
        assert path.exists()

        delete_cached_system(path)
        assert not path.exists()

    def test_delete_nonexistent(self, tmp_cache):
        """Deleting a file that doesn't exist should not raise."""
        delete_cached_system(tmp_cache / "nonexistent.json")


class TestCacheEdgeCases:

    def test_system_with_no_talkgroups(self, tmp_cache):
        system = RRSystem(sid=1, name="EMPTY")
        system.talkgroups = []
        system.sites = []
        path = save_system(system)
        loaded = load_system(path)
        assert loaded.name == "EMPTY"
        assert len(loaded.talkgroups) == 0
        assert len(loaded.sites) == 0

    def test_safe_filename_special_chars(self, tmp_cache):
        """System names with special chars get sanitized."""
        system = RRSystem(sid=1, name="Test/System:Bad<Chars>")
        system.talkgroups = []
        system.sites = []
        path = save_system(system)
        assert path.exists()
        # Filename should not contain /:<>
        assert "/" not in path.name
        assert ":" not in path.name
        assert "<" not in path.name

    def test_safe_filename_empty_name(self, tmp_cache):
        """Empty system name falls back to str(sid)."""
        system = RRSystem(sid=1, name="")
        system.talkgroups = []
        system.sites = []
        path = save_system(system)
        assert path.stem == "1"  # falls back to str(sid)

    def test_corrupted_json_skipped_in_listing(self, tmp_cache):
        """Corrupted JSON files don't crash list_cached_systems."""
        bad_file = tmp_cache / "bad.json"
        bad_file.write_text("not valid json {{{")

        results = list_cached_systems()
        assert len(results) == 0  # bad file skipped

    def test_load_missing_keys_defaults(self, tmp_cache):
        """JSON with missing keys should use defaults, not crash."""
        path = tmp_cache / "minimal.json"
        path.write_text('{"sid": 42, "name": "Minimal"}',
                        encoding='utf-8')
        loaded = load_system(path)
        assert loaded.sid == 42
        assert loaded.name == "Minimal"
        assert loaded.talkgroups == []
        assert loaded.sites == []
        assert loaded.wacn == ""

    def test_load_corrupted_json_raises(self):
        """Corrupted JSON should raise JSONDecodeError."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("{bad json!}", encoding='utf-8')
            with pytest.raises(json.JSONDecodeError):
                load_system(path)

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_system(Path("/nonexistent/cache.json"))

    def test_nac_roundtrip(self, tmp_cache):
        """NAC field should survive cache roundtrip."""
        system = _make_test_system()
        system.nac = "F0A"
        path = save_system(system)
        loaded = load_system(path)
        assert loaded.nac == "F0A"

    def test_source_field(self, tmp_cache):
        """Source field should be preserved in JSON."""
        system = _make_test_system()
        path = save_system(system, source="api")
        raw = json.loads(path.read_text(encoding='utf-8'))
        assert raw["source"] == "api"

    def test_overwrite_same_name(self, tmp_cache):
        """Saving a system with the same name overwrites the cache file."""
        system = _make_test_system()
        path1 = save_system(system)
        system.talkgroups.append(
            RRTalkgroup(dec_id=9999, alpha_tag="NEW"))
        path2 = save_system(system)
        assert path1 == path2
        loaded = load_system(path2)
        assert len(loaded.talkgroups) == 3
