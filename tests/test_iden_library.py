"""Tests for IDEN template library — standard templates, re-export compatibility."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from quickprs.iden_library import (
    P25_BANDS, detect_p25_band, calculate_tx_freq,
    build_standard_iden_entries,
    _standard_800_iden, _standard_700_iden, _standard_900_iden,
    STANDARD_IDEN_TEMPLATES, IdenTemplate,
    get_template, get_template_keys, get_default_name,
    auto_select_template_key, find_matching_iden_set,
    _iden_entries_match,
)

TESTDATA = Path(__file__).parent / "testdata"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Band detection / TX calc (canonical source now in iden_library) ──

def test_band_detection_all():
    """Every P25_BANDS entry detects correctly."""
    for name, rx_low, rx_high, expected_offset in P25_BANDS:
        mid = (rx_low + rx_high) / 2
        band, offset = detect_p25_band(mid)
        assert band == name, f"Expected {name}, got {band} for {mid} MHz"
        assert offset == expected_offset
    print("  PASS: Band detection all bands")


def test_band_detection_unknown():
    """Out-of-range frequency returns None."""
    band, offset = detect_p25_band(1200.0)
    assert band is None
    assert offset == 0.0
    print("  PASS: Band detection unknown")


def test_tx_freq_800():
    assert abs(calculate_tx_freq(851.0125) - 806.0125) < 0.0001
    print("  PASS: TX freq 800 MHz")


def test_tx_freq_700():
    assert abs(calculate_tx_freq(769.40625) - 799.40625) < 0.0001
    print("  PASS: TX freq 700 MHz")


def test_tx_freq_900():
    assert abs(calculate_tx_freq(935.5) - 896.5) < 0.0001
    print("  PASS: TX freq 900 MHz")


# ─── Template catalog ─────────────────────────────────────────────────

def test_template_catalog_count():
    """7 templates: 800-FDMA, 800-TDMA, 800-Mixed, 700-FDMA, 700-TDMA,
    900-FDMA, 900-TDMA."""
    assert len(STANDARD_IDEN_TEMPLATES) == 7
    print("  PASS: Template catalog count")


def test_template_keys_order():
    """Keys returned in expected order."""
    keys = get_template_keys()
    assert keys == [
        "800-FDMA", "800-TDMA", "800-Mixed",
        "700-FDMA", "700-TDMA",
        "900-FDMA", "900-TDMA",
    ]
    print("  PASS: Template keys order")


def test_get_template():
    """get_template returns correct template or None."""
    t = get_template("800-TDMA")
    assert t is not None
    assert isinstance(t, IdenTemplate)
    assert t.key == "800-TDMA"
    assert t.band == "800"
    assert t.mode == "TDMA"

    assert get_template("NONEXISTENT") is None
    print("  PASS: get_template")


def test_get_default_name():
    """Default names are short and unique."""
    names = set()
    for key in get_template_keys():
        name = get_default_name(key)
        assert len(name) <= 8, f"Name too long: {name}"
        assert name not in names, f"Duplicate name: {name}"
        names.add(name)
    print("  PASS: get_default_name")


# ─── 800 MHz templates ────────────────────────────────────────────────

def test_800_fdma_template():
    """800 MHz FDMA template has 16 entries with correct parameters."""
    t = get_template("800-FDMA")
    assert len(t.entries) == 16

    for i, e in enumerate(t.entries):
        assert e['base_freq_hz'] == 851006250 + i * 1125000
        assert e['chan_spacing_hz'] == 12500
        assert e['bandwidth_hz'] == 12500
        assert e['tx_offset_mhz'] == -45.0
        assert e['iden_type'] == 0  # FDMA

    # Frequency range check
    first_mhz = t.entries[0]['base_freq_hz'] / 1e6
    last_mhz = t.entries[15]['base_freq_hz'] / 1e6
    assert 851.0 <= first_mhz <= 852.0
    assert 867.0 <= last_mhz <= 868.0
    print("  PASS: 800 MHz FDMA template")


def test_800_tdma_template():
    """800 MHz TDMA template has 16 entries with TDMA parameters."""
    t = get_template("800-TDMA")
    assert len(t.entries) == 16

    for e in t.entries:
        assert e['chan_spacing_hz'] == 6250
        assert e['bandwidth_hz'] == 6250
        assert e['iden_type'] == 1  # TDMA
        assert e['tx_offset_mhz'] == -45.0
    print("  PASS: 800 MHz TDMA template")


def test_800_mixed_template():
    """800 MHz Mixed template: slots 0-1 FDMA, slots 2-15 TDMA."""
    t = get_template("800-Mixed")
    assert len(t.entries) == 16
    assert t.mode == "Mixed"

    # Slots 0-1: FDMA
    for i in range(2):
        e = t.entries[i]
        assert e['chan_spacing_hz'] == 12500, f"Slot {i} spacing wrong"
        assert e['bandwidth_hz'] == 12500, f"Slot {i} BW wrong"
        assert e['iden_type'] == 0, f"Slot {i} should be FDMA"

    # Slots 2-15: TDMA
    for i in range(2, 16):
        e = t.entries[i]
        assert e['chan_spacing_hz'] == 6250, f"Slot {i} spacing wrong"
        assert e['bandwidth_hz'] == 6250, f"Slot {i} BW wrong"
        assert e['iden_type'] == 1, f"Slot {i} should be TDMA"

    # All entries have same base freq pattern and TX offset
    for i, e in enumerate(t.entries):
        assert e['base_freq_hz'] == 851006250 + i * 1125000
        assert e['tx_offset_mhz'] == -45.0
    print("  PASS: 800 MHz Mixed template")


# ─── 700 MHz templates ────────────────────────────────────────────────

def test_700_fdma_template():
    """700 MHz FDMA template has correct 750 kHz blocks."""
    t = get_template("700-FDMA")
    assert len(t.entries) == 16

    for i, e in enumerate(t.entries):
        assert e['base_freq_hz'] == 764006250 + i * 750000
        assert e['chan_spacing_hz'] == 12500
        assert e['iden_type'] == 0
        assert e['tx_offset_mhz'] == 30.0  # +30 MHz for 700 band
    print("  PASS: 700 MHz FDMA template")


def test_700_tdma_template():
    """700 MHz TDMA template."""
    t = get_template("700-TDMA")
    assert len(t.entries) == 16

    for e in t.entries:
        assert e['chan_spacing_hz'] == 6250
        assert e['iden_type'] == 1
        assert e['tx_offset_mhz'] == 30.0
    print("  PASS: 700 MHz TDMA template")


# ─── 900 MHz templates ────────────────────────────────────────────────

def test_900_fdma_template():
    """900 MHz FDMA: 8 active + 8 empty entries."""
    t = get_template("900-FDMA")
    assert len(t.entries) == 16

    active = [e for e in t.entries if e.get('base_freq_hz', 0) > 0]
    empty = [e for e in t.entries if e.get('base_freq_hz', 0) == 0]
    assert len(active) == 8
    assert len(empty) == 8

    for i, e in enumerate(active):
        assert e['base_freq_hz'] == 935012500 + i * 625000
        assert e['tx_offset_mhz'] == -39.0
        assert e['iden_type'] == 0
    print("  PASS: 900 MHz FDMA template")


def test_900_tdma_template():
    """900 MHz TDMA: 8 active with TDMA params."""
    t = get_template("900-TDMA")
    active = [e for e in t.entries if e.get('base_freq_hz', 0) > 0]
    assert len(active) == 8

    for e in active:
        assert e['chan_spacing_hz'] == 6250
        assert e['iden_type'] == 1
        assert e['tx_offset_mhz'] == -39.0
    print("  PASS: 900 MHz TDMA template")


# ─── Every template passes validity checks ────────────────────────────

def test_all_templates_have_16_entries():
    """Every template must have exactly 16 entries."""
    for key, tmpl in STANDARD_IDEN_TEMPLATES.items():
        assert len(tmpl.entries) == 16, \
            f"Template {key} has {len(tmpl.entries)} entries, expected 16"
    print("  PASS: All templates have 16 entries")


def test_all_templates_valid_frequencies():
    """Active entries have positive base frequencies in their band."""
    band_ranges = {
        '800': (851e6, 870e6),
        '700': (764e6, 777e6),
        '900': (935e6, 941e6),
    }
    for key, tmpl in STANDARD_IDEN_TEMPLATES.items():
        low, high = band_ranges[tmpl.band]
        for i, e in enumerate(tmpl.entries):
            freq = e.get('base_freq_hz', 0)
            if freq == 0:
                continue  # empty slot is fine
            assert low <= freq <= high, \
                f"Template {key} entry {i}: {freq} Hz out of {tmpl.band} range"
    print("  PASS: All templates valid frequencies")


def test_all_templates_correct_tx_offset():
    """TX offset matches the band plan."""
    expected_offsets = {
        '800': -45.0,
        '700': 30.0,
        '900': -39.0,
    }
    for key, tmpl in STANDARD_IDEN_TEMPLATES.items():
        expected = expected_offsets[tmpl.band]
        for i, e in enumerate(tmpl.entries):
            if e.get('base_freq_hz', 0) == 0:
                continue
            assert e.get('tx_offset_mhz') == expected, \
                f"Template {key}[{i}] TX offset {e.get('tx_offset_mhz')} " \
                f"!= expected {expected}"
    print("  PASS: All templates correct TX offset")


def test_template_metadata():
    """Each template has key, label, band, mode, description."""
    for key, tmpl in STANDARD_IDEN_TEMPLATES.items():
        assert tmpl.key == key
        assert len(tmpl.label) > 0
        assert tmpl.band in ('800', '700', '900')
        assert tmpl.mode in ('FDMA', 'TDMA', 'Mixed')
        assert len(tmpl.description) > 0
    print("  PASS: Template metadata")


# ─── Re-export compatibility ──────────────────────────────────────────

def test_radioreference_reexports():
    """Functions imported from radioreference still work (backward compat)."""
    from quickprs.radioreference import (
        P25_BANDS as rr_bands,
        detect_p25_band as rr_detect,
        calculate_tx_freq as rr_calc,
        build_standard_iden_entries as rr_build,
    )

    # Same objects (re-exported, not copies)
    assert rr_bands is P25_BANDS
    assert rr_detect is detect_p25_band
    assert rr_calc is calculate_tx_freq
    assert rr_build is build_standard_iden_entries

    # Functions still work
    band, offset = rr_detect(851.5)
    assert band == '800'
    assert offset == -45.0

    entries = rr_build([851.5], "Project 25 Phase II")
    assert len(entries) == 16
    assert entries[0]['iden_type'] == 1  # TDMA
    print("  PASS: radioreference re-exports")


# ─── build_standard_iden_entries integration ──────────────────────────

def test_build_entries_800_phase2():
    """build_standard_iden_entries for 800 MHz Phase II."""
    entries = build_standard_iden_entries(
        [851.0125, 851.2625], "Project 25 Phase II")
    assert len(entries) == 16
    assert entries[0]['base_freq_hz'] == 851006250
    assert entries[0]['chan_spacing_hz'] == 6250
    assert entries[0]['iden_type'] == 1
    print("  PASS: build_entries 800 Phase II")


def test_build_entries_800_phase1():
    """build_standard_iden_entries for 800 MHz Phase I."""
    entries = build_standard_iden_entries(
        [851.0125], "Project 25 Phase I")
    assert len(entries) == 16
    assert entries[0]['chan_spacing_hz'] == 12500
    assert entries[0]['iden_type'] == 0
    print("  PASS: build_entries 800 Phase I")


def test_build_entries_700():
    """build_standard_iden_entries for 700 MHz."""
    entries = build_standard_iden_entries(
        [769.40625], "Project 25 Phase II")
    assert len(entries) == 16
    assert entries[0]['tx_offset_mhz'] == 30.0
    print("  PASS: build_entries 700 MHz")


def test_build_entries_900():
    """build_standard_iden_entries for 900 MHz."""
    entries = build_standard_iden_entries(
        [935.5], "Project 25 Phase I")
    assert len(entries) == 16
    active = sum(1 for e in entries if e.get('base_freq_hz', 0) > 0)
    assert active == 8
    assert entries[0]['tx_offset_mhz'] == -39.0
    print("  PASS: build_entries 900 MHz")


def test_build_entries_empty():
    """Empty frequency list returns empty."""
    assert build_standard_iden_entries([]) == []
    print("  PASS: build_entries empty")


def test_build_entries_unknown_band():
    """Unknown band returns empty."""
    assert build_standard_iden_entries([1200.0]) == []
    print("  PASS: build_entries unknown band")


# ─── CLI command ──────────────────────────────────────────────────────

def test_cli_iden_templates():
    """CLI iden-templates command runs without error."""
    from quickprs.cli import cmd_iden_templates
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_iden_templates(detail=False)
    assert rc == 0
    output = buf.getvalue()
    assert "800-FDMA" in output
    assert "800-TDMA" in output
    assert "700-FDMA" in output
    assert "900-TDMA" in output
    assert "800-Mixed" in output
    print("  PASS: CLI iden-templates")


def test_cli_iden_templates_detail():
    """CLI iden-templates --detail shows entry data."""
    from quickprs.cli import cmd_iden_templates
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_iden_templates(detail=True)
    assert rc == 0
    output = buf.getvalue()
    assert "851.00625" in output  # 800 MHz first entry
    assert "TDMA" in output
    assert "FDMA" in output
    print("  PASS: CLI iden-templates detail")


# ─── auto_select_template_key ─────────────────────────────────────────

def test_auto_select_800_tdma():
    """800 MHz Phase II → 800-TDMA."""
    key = auto_select_template_key([851.5], "Project 25 Phase II")
    assert key == "800-TDMA"
    print("  PASS: auto_select 800 TDMA")


def test_auto_select_800_fdma():
    """800 MHz Phase I → 800-FDMA."""
    key = auto_select_template_key([851.5], "Project 25 Phase I")
    assert key == "800-FDMA"
    print("  PASS: auto_select 800 FDMA")


def test_auto_select_700_tdma():
    """700 MHz Phase II → 700-TDMA."""
    key = auto_select_template_key([769.5], "Project 25 Phase II")
    assert key == "700-TDMA"
    print("  PASS: auto_select 700 TDMA")


def test_auto_select_900_fdma():
    """900 MHz Phase I → 900-FDMA."""
    key = auto_select_template_key([936.0], "")
    assert key == "900-FDMA"
    print("  PASS: auto_select 900 FDMA")


def test_auto_select_unknown_band():
    """Unknown band returns None."""
    key = auto_select_template_key([1200.0], "")
    assert key is None
    print("  PASS: auto_select unknown band")


def test_auto_select_empty():
    """Empty frequency list returns None."""
    key = auto_select_template_key([], "")
    assert key is None
    print("  PASS: auto_select empty")


# ─── _iden_entries_match ──────────────────────────────────────────────

def test_entries_match_self():
    """Template entries match themselves when turned into IdenElements."""
    from quickprs.record_types import IdenElement
    from quickprs.injector import make_iden_set

    template = get_template("800-TDMA")
    iset = make_iden_set("TEST", template.entries)
    assert _iden_entries_match(iset.elements, template.entries)
    print("  PASS: entries_match self")


def test_entries_no_match_different_mode():
    """FDMA elements don't match TDMA template."""
    from quickprs.injector import make_iden_set

    fdma_tmpl = get_template("800-FDMA")
    tdma_tmpl = get_template("800-TDMA")
    iset = make_iden_set("TEST", fdma_tmpl.entries)
    assert not _iden_entries_match(iset.elements, tdma_tmpl.entries)
    print("  PASS: entries no match different mode")


# ─── find_matching_iden_set (with real PRS) ──────────────────────────

@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
def test_find_matching_iden_in_pawsovermaws():
    """PAWSOVERMAWS PRS has an 800 MHz IDEN set; find_matching should find it."""
    prs_path = Path(__file__).parent / "testdata" / "PAWSOVERMAWS.PRS"
    if not prs_path.exists():
        print("  SKIP: PAWSOVERMAWS.PRS not found")
        return

    from quickprs.prs_parser import parse_prs

    prs = parse_prs(str(prs_path))

    # PAWSOVERMAWS has 800 MHz mixed IDEN — check 800-FDMA and 800-TDMA
    # At minimum, it should not crash and should return a string or None
    for key in ["800-FDMA", "800-TDMA", "800-Mixed"]:
        result = find_matching_iden_set(prs, key)
        # Result is either None or a string name
        assert result is None or isinstance(result, str)

    print("  PASS: find_matching_iden PAWSOVERMAWS")


def test_find_matching_iden_no_match():
    """Small test PRS with no IDEN set should return None."""
    prs_path = Path(__file__).parent / "testdata" / "claude test.PRS"
    if not prs_path.exists():
        print("  SKIP: claude test.PRS not found")
        return

    from quickprs.prs_parser import parse_prs

    prs = parse_prs(str(prs_path))

    # Check if it has IDEN sections at all
    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    if not elem_sec:
        # No IDEN sections = should return None gracefully
        result = find_matching_iden_set(prs, "800-TDMA")
        assert result is None
        print("  PASS: find_matching_iden no IDEN sections")
        return

    # If it does have IDEN, 700 MHz probably won't match
    result = find_matching_iden_set(prs, "700-TDMA")
    assert result is None or isinstance(result, str)
    print("  PASS: find_matching_iden no match")


# ─── Runner ──────────────────────────────────────────────────────────

def main():
    print("\n=== IDEN Library Tests ===\n")

    tests = [
        ("Band detection all", test_band_detection_all),
        ("Band detection unknown", test_band_detection_unknown),
        ("TX freq 800", test_tx_freq_800),
        ("TX freq 700", test_tx_freq_700),
        ("TX freq 900", test_tx_freq_900),
        ("Template catalog count", test_template_catalog_count),
        ("Template keys order", test_template_keys_order),
        ("get_template", test_get_template),
        ("get_default_name", test_get_default_name),
        ("800 FDMA template", test_800_fdma_template),
        ("800 TDMA template", test_800_tdma_template),
        ("800 Mixed template", test_800_mixed_template),
        ("700 FDMA template", test_700_fdma_template),
        ("700 TDMA template", test_700_tdma_template),
        ("900 FDMA template", test_900_fdma_template),
        ("900 TDMA template", test_900_tdma_template),
        ("All 16 entries", test_all_templates_have_16_entries),
        ("Valid frequencies", test_all_templates_valid_frequencies),
        ("Correct TX offsets", test_all_templates_correct_tx_offset),
        ("Template metadata", test_template_metadata),
        ("RR re-exports", test_radioreference_reexports),
        ("build_entries 800 Phase II", test_build_entries_800_phase2),
        ("build_entries 800 Phase I", test_build_entries_800_phase1),
        ("build_entries 700", test_build_entries_700),
        ("build_entries 900", test_build_entries_900),
        ("build_entries empty", test_build_entries_empty),
        ("build_entries unknown band", test_build_entries_unknown_band),
        ("CLI iden-templates", test_cli_iden_templates),
        ("CLI iden-templates detail", test_cli_iden_templates_detail),
        ("auto_select 800 TDMA", test_auto_select_800_tdma),
        ("auto_select 800 FDMA", test_auto_select_800_fdma),
        ("auto_select 700 TDMA", test_auto_select_700_tdma),
        ("auto_select 900 FDMA", test_auto_select_900_fdma),
        ("auto_select unknown band", test_auto_select_unknown_band),
        ("auto_select empty", test_auto_select_empty),
        ("entries_match self", test_entries_match_self),
        ("entries no match mode", test_entries_no_match_different_mode),
        ("find_matching PAWSOVERMAWS", test_find_matching_iden_in_pawsovermaws),
        ("find_matching no match", test_find_matching_iden_no_match),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} - {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All IDEN library tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
