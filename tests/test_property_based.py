"""Property-based tests exercising core operations with wide input ranges.

Tests make_p25_group, identify_service, template channels, and
frequency-related functions across many parameter combinations to
ensure robust handling of edge cases and boundary conditions.
"""

import pytest

from quickprs.injector import (
    make_p25_group, make_conv_channel, make_conv_set, make_trunk_channel,
    make_trunk_set, make_group_set, make_iden_set,
)
from quickprs.freq_tools import (
    identify_service, freq_to_channel, channel_to_freq,
    calculate_repeater_offset, check_frequency_conflicts,
    validate_ctcss_tone, nearest_ctcss, format_ctcss_table,
    format_dcs_table, format_service_id, format_all_offsets,
    CTCSS_TONES, DCS_CODES,
)
from quickprs.templates import get_template_channels, get_template_names
from quickprs.record_types import (
    P25Group, TrunkChannel, ConvChannel, ConvSet, TrunkSet,
    P25GroupSet, IdenElement, IdenDataSet,
)


# ─── P25 Group combinatorial ────────────────────────────────────────


@pytest.mark.parametrize("group_id", [1, 100, 1000, 10000, 65535])
@pytest.mark.parametrize("name_len", [1, 4, 8])
@pytest.mark.parametrize("tx", [True, False])
@pytest.mark.parametrize("scan", [True, False])
def test_make_group_all_combos(group_id, name_len, tx, scan):
    """make_p25_group produces valid P25Group for all input combos."""
    name = "A" * name_len
    g = make_p25_group(group_id, name, tx=tx, scan=scan)
    assert g.group_id == group_id
    assert len(g.group_name) <= 8
    assert g.tx == tx
    assert g.scan == scan
    data = g.to_bytes()
    assert len(data) > 0


@pytest.mark.parametrize("group_id", [0, 1, 32767, 32768, 65534, 65535])
def test_p25_group_id_boundary(group_id):
    """P25 group ID boundaries (uint16 range)."""
    g = make_p25_group(group_id, "TGTEST")
    assert g.group_id == group_id
    data = g.to_bytes()
    parsed, _ = P25Group.parse(data, 0)
    assert parsed.group_id == group_id


@pytest.mark.parametrize("name", [
    "A", "AB", "ABCDEFGH",  # 1, 2, max 8
    "12345678",  # numeric
    "SP ACE",  # space in name
    "A-B.C_D",  # special chars
])
def test_p25_group_name_variety(name):
    """Various valid short names roundtrip through P25Group."""
    g = make_p25_group(100, name)
    assert g.group_name == name[:8]
    data = g.to_bytes()
    parsed, _ = P25Group.parse(data, 0)
    assert parsed.group_name == name[:8]


@pytest.mark.parametrize("long_name", [
    "", "A", "ABCDEFGHIJKLMNOP",  # empty, 1-char, max 16
    "Long Name Here!",  # 16 chars exactly
])
def test_p25_group_long_name(long_name):
    """P25 group long names truncate and roundtrip correctly."""
    g = make_p25_group(42, "SHORT", long_name=long_name)
    assert len(g.long_name) <= 16
    data = g.to_bytes()
    parsed, _ = P25Group.parse(data, 0)
    assert parsed.long_name == g.long_name


@pytest.mark.parametrize("name", [
    "ABCDEFGHIJ",  # 10 chars, exceeds 8
    "TOOLONGNAME123",  # 14 chars
    "A" * 20,
])
def test_p25_group_name_truncation(name):
    """Names longer than 8 are truncated silently."""
    g = make_p25_group(1, name)
    assert len(g.group_name) == 8
    assert g.group_name == name[:8]


@pytest.mark.parametrize("rx", [True, False])
@pytest.mark.parametrize("calls", [True, False])
@pytest.mark.parametrize("alert", [True, False])
def test_p25_group_bool_flags_roundtrip(rx, calls, alert):
    """Boolean flags survive roundtrip through to_bytes/parse."""
    g = P25Group(
        group_name="TEST", group_id=100, long_name="TEST",
        rx=rx, calls=calls, alert=alert,
        scan_list_member=True, scan=True, backlight=True, tx=False,
    )
    data = g.to_bytes()
    parsed, _ = P25Group.parse(data, 0)
    assert parsed.rx == rx
    assert parsed.calls == calls
    assert parsed.alert == alert


# ─── Frequency identification ────────────────────────────────────────


@pytest.mark.parametrize("freq", [
    30.0, 50.0, 146.52, 155.0, 300.0, 462.5625, 770.0, 851.0, 935.0, 960.0
])
def test_identify_service_all_bands(freq):
    """identify_service returns valid structure for all band frequencies."""
    result = identify_service(freq)
    assert 'service' in result
    assert 'band' in result
    assert 'allocation' in result
    assert 'notes' in result
    assert 'frequency' in result
    assert result['frequency'] == freq


@pytest.mark.parametrize("freq", [
    462.5625, 462.5875, 462.6125, 462.6375,
    462.6625, 462.6875, 462.7125,  # FRS/GMRS 1-7
])
def test_identify_service_frs_gmrs(freq):
    """FRS/GMRS frequencies are identified correctly."""
    result = identify_service(freq)
    assert "FRS" in result['service'] or "GMRS" in result['service']


@pytest.mark.parametrize("freq", [
    151.820, 151.880, 151.940, 154.570, 154.600
])
def test_identify_service_murs(freq):
    """MURS frequencies are identified correctly."""
    result = identify_service(freq)
    assert "MURS" in result['service']


@pytest.mark.parametrize("freq", [
    156.800, 156.450, 156.650, 156.375, 156.425
])
def test_identify_service_marine(freq):
    """Marine VHF frequencies are identified correctly."""
    result = identify_service(freq)
    assert "Marine" in result['service']


@pytest.mark.parametrize("freq", [
    162.400, 162.425, 162.450, 162.475, 162.500, 162.525, 162.550
])
def test_identify_service_noaa(freq):
    """NOAA weather frequencies are identified correctly."""
    result = identify_service(freq)
    assert "NOAA" in result['service']


@pytest.mark.parametrize("freq", [0.001, 1.0, 10000.0, 99999.0])
def test_identify_service_extreme_freqs(freq):
    """Extreme frequencies don't crash; may return Unknown."""
    result = identify_service(freq)
    assert isinstance(result, dict)
    assert 'service' in result


@pytest.mark.parametrize("freq,expected_service,expected_ch", [
    (462.5625, "FRS/GMRS", 1),
    (151.820, "MURS", 1),
    (156.800, "Marine VHF", 16),
    (162.400, "NOAA", 1),
])
def test_freq_to_channel(freq, expected_service, expected_ch):
    """freq_to_channel maps known frequencies to correct channels."""
    result = freq_to_channel(freq)
    assert result is not None
    service, ch = result
    assert service == expected_service
    assert ch == expected_ch


@pytest.mark.parametrize("freq", [100.0, 200.0, 500.0, 1000.0])
def test_freq_to_channel_unknown(freq):
    """Frequencies not in any channel table return None."""
    result = freq_to_channel(freq)
    assert result is None


# ─── Repeater offset ────────────────────────────────────────────────


@pytest.mark.parametrize("freq,expected_offset,expected_dir", [
    (146.52, 0.6, "+"),
    (147.36, 0.6, "-"),
    (223.5, 1.6, "-"),
    (440.0, 5.0, "+"),
    (449.0, 5.0, "-"),
    (927.0, 12.0, "-"),
])
def test_repeater_offset_known_bands(freq, expected_offset, expected_dir):
    """Standard repeater offsets for known bands."""
    result = calculate_repeater_offset(freq)
    assert result is not None
    offset, direction = result
    assert offset == expected_offset
    assert direction == expected_dir


@pytest.mark.parametrize("freq", [30.0, 160.0, 300.0, 500.0, 1000.0])
def test_repeater_offset_no_standard(freq):
    """Frequencies outside standard repeater bands return None."""
    result = calculate_repeater_offset(freq)
    assert result is None


# ─── Frequency conflict detection ────────────────────────────────────


def test_conflict_empty_list():
    """Empty freq list produces no warnings."""
    assert check_frequency_conflicts([]) == []


def test_conflict_single_freq():
    """Single frequency produces no warnings."""
    assert check_frequency_conflicts([146.52]) == []


def test_conflict_well_spaced():
    """Well-spaced frequencies produce no spacing warnings."""
    freqs = [146.0, 147.0, 148.0]
    warnings = check_frequency_conflicts(freqs)
    spacing_warnings = [w for w in warnings if "Spacing" in w or "Tight" in w]
    assert len(spacing_warnings) == 0


def test_conflict_too_close():
    """Frequencies 5 kHz apart trigger spacing conflict."""
    freqs = [146.0, 146.005]
    warnings = check_frequency_conflicts(freqs)
    assert any("Spacing conflict" in w for w in warnings)


def test_conflict_tight_spacing():
    """Frequencies 15 kHz apart trigger tight spacing warning."""
    freqs = [146.0, 146.015]
    warnings = check_frequency_conflicts(freqs)
    assert any("Tight spacing" in w for w in warnings)


@pytest.mark.parametrize("n_freqs", [2, 5, 10, 20])
def test_conflict_check_doesnt_crash(n_freqs):
    """Conflict check handles various list sizes without crashing."""
    freqs = [146.0 + i * 0.025 for i in range(n_freqs)]
    result = check_frequency_conflicts(freqs)
    assert isinstance(result, list)


# ─── Template names and channels ────────────────────────────────────


@pytest.mark.parametrize("template", [
    "murs", "gmrs", "frs", "marine", "noaa", "interop",
    "public_safety", "weather",
])
def test_template_names_valid(template):
    """Every template returns channels with valid name lengths."""
    channels = get_template_channels(template)
    assert len(channels) > 0
    for ch in channels:
        assert len(ch['short_name']) <= 8, \
            f"Template '{template}': short_name '{ch['short_name']}' > 8 chars"
        if 'long_name' in ch and ch['long_name']:
            assert len(ch['long_name']) <= 16, \
                f"Template '{template}': long_name '{ch['long_name']}' > 16 chars"


@pytest.mark.parametrize("template", [
    "murs", "gmrs", "frs", "marine", "noaa", "interop",
    "public_safety", "weather",
])
def test_template_channels_have_freq(template):
    """Every template channel has a positive tx_freq."""
    channels = get_template_channels(template)
    for ch in channels:
        assert ch['tx_freq'] > 0


@pytest.mark.parametrize("template", [
    "murs", "gmrs", "frs", "marine", "noaa", "interop",
    "public_safety", "weather",
])
def test_template_make_conv_set(template):
    """Every template can be built into a ConvSet via make_conv_set."""
    channels = get_template_channels(template)
    conv_set = make_conv_set(template[:8].upper(), channels)
    assert isinstance(conv_set, ConvSet)
    assert len(conv_set.channels) == len(channels)
    for ch in conv_set.channels:
        assert len(ch.short_name) <= 8


def test_all_templates_discoverable():
    """get_template_names returns a sorted list with known templates."""
    names = get_template_names()
    assert isinstance(names, list)
    assert len(names) >= 7
    for expected in ['murs', 'gmrs', 'frs', 'marine', 'noaa', 'interop']:
        assert expected in names


def test_template_unknown_raises():
    """Requesting a nonexistent template raises ValueError."""
    with pytest.raises(ValueError, match="Unknown template"):
        get_template_channels("nonexistent_radio_service")


# ─── Conventional channel construction ──────────────────────────────


@pytest.mark.parametrize("freq", [
    30.0, 50.0, 146.52, 155.340, 440.0, 462.5625, 851.0, 935.0
])
def test_make_conv_channel_various_freqs(freq):
    """make_conv_channel works across the full frequency range."""
    ch = make_conv_channel("TEST", freq)
    assert ch.tx_freq == freq
    assert ch.rx_freq == freq  # simplex default
    data = ch.to_bytes()
    assert len(data) == ch.byte_size()


@pytest.mark.parametrize("tx_tone,rx_tone", [
    ("", ""),
    ("67.0", "67.0"),
    ("100.0", "100.0"),
    ("250.3", "250.3"),
    ("D023", "D023"),
    ("156.7", ""),
    ("", "156.7"),
])
def test_make_conv_channel_tones(tx_tone, rx_tone):
    """CTCSS/DCS tones are stored correctly in conv channels."""
    ch = make_conv_channel("TONE", 146.52, tx_tone=tx_tone, rx_tone=rx_tone)
    assert ch.tx_tone == tx_tone
    assert ch.rx_tone == rx_tone


@pytest.mark.parametrize("short_name", [
    "A", "AB", "ABCDEFGH", "TOOLONG!", "WAYTOOLONG"
])
def test_make_conv_channel_name_truncation(short_name):
    """Conv channel short names are truncated to 8 chars."""
    ch = make_conv_channel(short_name, 146.52)
    assert len(ch.short_name) <= 8


# ─── Trunk channel construction ─────────────────────────────────────


@pytest.mark.parametrize("tx,rx", [
    (851.0, 851.0),
    (851.0, 806.0),
    (935.0, 935.0),
    (770.0, 800.0),
])
def test_make_trunk_channel(tx, rx):
    """Trunk channels accept various TX/RX pairs."""
    ch = make_trunk_channel(tx, rx)
    assert ch.tx_freq == tx
    assert ch.rx_freq == rx
    data = ch.to_bytes()
    assert len(data) == TrunkChannel.RECORD_SIZE


def test_make_trunk_channel_simplex():
    """Trunk channel defaults to simplex (rx = tx)."""
    ch = make_trunk_channel(851.0)
    assert ch.rx_freq == 851.0


# ─── Trunk set construction ─────────────────────────────────────────


@pytest.mark.parametrize("n_freqs", [1, 2, 5, 10])
def test_make_trunk_set_various_sizes(n_freqs):
    """Trunk sets work with various numbers of frequencies."""
    freqs = [(851.0 + i * 0.025, 806.0 + i * 0.025) for i in range(n_freqs)]
    ts = make_trunk_set("TRUNK", freqs)
    assert isinstance(ts, TrunkSet)
    assert len(ts.channels) == n_freqs
    assert ts.name == "TRUNK"


def test_make_trunk_set_name_truncation():
    """Trunk set names longer than 8 are truncated."""
    freqs = [(851.0, 806.0)]
    ts = make_trunk_set("TOOLONGNAME", freqs)
    assert len(ts.name) == 8


# ─── Group set construction ─────────────────────────────────────────


@pytest.mark.parametrize("n_groups", [1, 5, 10, 50])
def test_make_group_set_various_sizes(n_groups):
    """Group sets work with various numbers of talkgroups."""
    tgs = [(i, f"TG{i:04d}", f"Talkgroup {i}") for i in range(1, n_groups + 1)]
    gs = make_group_set("GRPSET", tgs)
    assert isinstance(gs, P25GroupSet)
    assert len(gs.groups) == n_groups


@pytest.mark.parametrize("tx_default", [True, False])
@pytest.mark.parametrize("scan_default", [True, False])
def test_make_group_set_defaults(tx_default, scan_default):
    """Group set tx/scan defaults propagate to all groups."""
    tgs = [(100, "TG100", "Talkgroup 100")]
    gs = make_group_set("TEST", tgs, tx_default=tx_default,
                        scan_default=scan_default)
    for g in gs.groups:
        assert g.tx == tx_default
        assert g.scan == scan_default


# ─── IDEN set construction ──────────────────────────────────────────


def test_make_iden_set_basic():
    """IDEN set creates 16-slot set with entries."""
    entries = [
        {'base_freq_hz': 851000000, 'chan_spacing_hz': 12500,
         'bandwidth_hz': 6250, 'iden_type': 0},
    ]
    iset = make_iden_set("BEE00", entries)
    assert isinstance(iset, IdenDataSet)
    assert len(iset.elements) == 16  # always padded to 16
    assert iset.elements[0].base_freq_hz == 851000000


def test_make_iden_set_all_16_slots():
    """IDEN set with all 16 slots filled."""
    entries = [
        {'base_freq_hz': 851000000 + i * 1000000}
        for i in range(16)
    ]
    iset = make_iden_set("FULL16", entries)
    assert len(iset.elements) == 16
    for i, elem in enumerate(iset.elements):
        assert elem.base_freq_hz == 851000000 + i * 1000000


def test_make_iden_set_empty():
    """IDEN set with no entries still has 16 empty slots."""
    iset = make_iden_set("EMPTY", [])
    assert len(iset.elements) == 16
    for elem in iset.elements:
        assert elem.is_empty()


@pytest.mark.parametrize("tx_offset_mhz", [-45.0, -30.0, 0.0, 30.0, 45.0])
def test_iden_element_tx_offset(tx_offset_mhz):
    """IDEN element tx_offset_mhz roundtrips through float32 encoding."""
    elem = IdenElement()
    elem.tx_offset_mhz = tx_offset_mhz
    recovered = elem.tx_offset_mhz
    assert abs(recovered - tx_offset_mhz) < 0.01


# ─── CTCSS/DCS tone tables ──────────────────────────────────────────


def test_ctcss_tones_sorted():
    """CTCSS tones are in ascending order."""
    for i in range(len(CTCSS_TONES) - 1):
        assert CTCSS_TONES[i] < CTCSS_TONES[i + 1]


def test_ctcss_tones_count():
    """Standard CTCSS has 50 tones."""
    assert len(CTCSS_TONES) == 50


def test_dcs_codes_sorted():
    """DCS codes are in ascending order."""
    for i in range(len(DCS_CODES) - 1):
        assert DCS_CODES[i] < DCS_CODES[i + 1]


def test_dcs_codes_count():
    """Standard DCS has 104 codes."""
    assert len(DCS_CODES) == 104


@pytest.mark.parametrize("tone", CTCSS_TONES)
def test_ctcss_tone_range(tone):
    """All CTCSS tones are in valid range (67.0 - 254.1 Hz)."""
    assert 60.0 <= tone <= 260.0


@pytest.mark.parametrize("code", DCS_CODES)
def test_dcs_code_range(code):
    """All DCS codes are 3-digit octal (23-754)."""
    assert 23 <= code <= 754


# ─── ConvChannel flag roundtrip ─────────────────────────────────────


@pytest.mark.parametrize("narrowband", [True, False])
@pytest.mark.parametrize("tx", [True, False])
@pytest.mark.parametrize("scan", [True, False])
@pytest.mark.parametrize("rx", [True, False])
def test_conv_channel_flags_roundtrip(narrowband, tx, scan, rx):
    """ConvChannel boolean flags survive to_bytes/parse roundtrip."""
    ch = ConvChannel(
        short_name="FLAGTST",
        tx_freq=146.52, rx_freq=146.52,
        narrowband=narrowband, tx=tx, scan=scan, rx=rx,
    )
    data = ch.to_bytes()
    parsed, _ = ConvChannel.parse(data, 0)
    assert parsed.narrowband == narrowband
    assert parsed.tx == tx
    assert parsed.scan == scan
    assert parsed.rx == rx


# ─── TrunkChannel roundtrip ─────────────────────────────────────────


@pytest.mark.parametrize("tx_freq", [136.0, 400.0, 851.0, 870.0])
@pytest.mark.parametrize("rx_freq", [136.0, 400.0, 806.0, 870.0])
def test_trunk_channel_roundtrip(tx_freq, rx_freq):
    """TrunkChannel roundtrips through to_bytes/parse."""
    ch = TrunkChannel(tx_freq=tx_freq, rx_freq=rx_freq)
    data = ch.to_bytes()
    parsed, _ = TrunkChannel.parse(data, 0)
    assert abs(parsed.tx_freq - tx_freq) < 0.0001
    assert abs(parsed.rx_freq - rx_freq) < 0.0001


# ─── IdenElement roundtrip ──────────────────────────────────────────


@pytest.mark.parametrize("spacing", [6250, 12500, 25000])
@pytest.mark.parametrize("bandwidth", [6250, 12500])
@pytest.mark.parametrize("iden_type", [0, 1])
def test_iden_element_roundtrip(spacing, bandwidth, iden_type):
    """IdenElement roundtrips through to_bytes/parse."""
    elem = IdenElement(
        chan_spacing_hz=spacing, bandwidth_hz=bandwidth,
        base_freq_hz=851000000, iden_type=iden_type,
    )
    data = elem.to_bytes()
    parsed, _ = IdenElement.parse(data, 0)
    assert parsed.chan_spacing_hz == spacing
    assert parsed.bandwidth_hz == bandwidth
    assert parsed.iden_type == iden_type
    assert parsed.base_freq_hz == 851000000


# ─── channel_to_freq reverse lookup ────────────────────────────────


@pytest.mark.parametrize("service,ch,expected", [
    ("FRS", 1, 462.5625),
    ("FRS", 22, 462.7250),
    ("GMRS", 1, 462.5625),
    ("GMRS", 15, 462.5500),
    ("MURS", 1, 151.820),
    ("MURS", 5, 154.600),
    ("NOAA", 1, 162.400),
    ("NOAA", 7, 162.550),
    ("Marine", 16, 156.800),
    ("Marine VHF", 9, 156.450),
])
def test_channel_to_freq_known(service, ch, expected):
    """channel_to_freq returns correct frequency for known channels."""
    result = channel_to_freq(service, ch)
    assert result is not None
    assert abs(result - expected) < 0.001


@pytest.mark.parametrize("service,ch", [
    ("FRS", 0),
    ("FRS", 23),
    ("MURS", 0),
    ("MURS", 6),
    ("NOAA", 0),
    ("NOAA", 8),
    ("UNKNOWN_SERVICE", 1),
])
def test_channel_to_freq_invalid(service, ch):
    """Invalid service/channel combos return None."""
    result = channel_to_freq(service, ch)
    assert result is None


@pytest.mark.parametrize("service", ["frs", "FRS", " FRS ", "Frs"])
def test_channel_to_freq_case_insensitive(service):
    """channel_to_freq is case-insensitive and strips whitespace."""
    result = channel_to_freq(service, 1)
    assert result is not None


# ─── validate_ctcss_tone ────────────────────────────────────────────


@pytest.mark.parametrize("tone", CTCSS_TONES)
def test_validate_ctcss_tone_all_standard(tone):
    """All standard CTCSS tones validate successfully."""
    result = validate_ctcss_tone(str(tone))
    assert result is not None
    assert result[0] == "CTCSS"
    assert result[1] == tone


@pytest.mark.parametrize("code", [23, 71, 155, 411, 754])
def test_validate_dcs_code_normal(code):
    """DCS codes with D prefix and N suffix validate."""
    result = validate_ctcss_tone(f"D{code:03d}N")
    assert result is not None
    assert result[0] == "DCS"
    assert result[1] == code


@pytest.mark.parametrize("code", [23, 71, 155])
def test_validate_dcs_code_inverted(code):
    """DCS codes with I suffix validate as DCS_I."""
    result = validate_ctcss_tone(f"D{code:03d}I")
    assert result is not None
    assert result[0] == "DCS_I"
    assert result[1] == code


@pytest.mark.parametrize("invalid", ["", "abc", "999.9", "D999N", "0.0"])
def test_validate_ctcss_tone_invalid(invalid):
    """Invalid tone strings return None."""
    result = validate_ctcss_tone(invalid)
    assert result is None


def test_validate_ctcss_tone_whitespace():
    """Leading/trailing whitespace is stripped."""
    result = validate_ctcss_tone("  100.0  ")
    assert result is not None
    assert result[0] == "CTCSS"


@pytest.mark.parametrize("code", [23, 71, 155])
def test_validate_bare_dcs_integer(code):
    """Bare integer DCS codes validate."""
    result = validate_ctcss_tone(str(code))
    assert result is not None
    assert result[1] == code


# ─── nearest_ctcss ──────────────────────────────────────────────────


@pytest.mark.parametrize("freq,expected_nearest", [
    (67.0, 67.0),   # exact match
    (100.0, 100.0),  # exact match
    (68.0, 67.0),    # between 67.0 and 69.3
    (254.1, 254.1),  # last tone, exact
    (260.0, 254.1),  # above range, nearest is last
    (60.0, 67.0),    # below range, nearest is first
])
def test_nearest_ctcss(freq, expected_nearest):
    """nearest_ctcss finds the correct nearest tone."""
    nearest, diff = nearest_ctcss(freq)
    assert nearest == expected_nearest


@pytest.mark.parametrize("tone", CTCSS_TONES)
def test_nearest_ctcss_exact_match(tone):
    """Exact CTCSS tones have zero difference."""
    nearest, diff = nearest_ctcss(tone)
    assert nearest == tone
    assert abs(diff) < 0.001


# ─── Formatting functions ───────────────────────────────────────────


def test_format_ctcss_table():
    """CTCSS table formatter returns non-empty output."""
    lines = format_ctcss_table()
    assert len(lines) > 5
    assert "CTCSS" in lines[0]


def test_format_dcs_table():
    """DCS table formatter returns non-empty output."""
    lines = format_dcs_table()
    assert len(lines) > 5


@pytest.mark.parametrize("freq", [146.52, 462.5625, 851.0])
def test_format_service_id(freq):
    """format_service_id returns formatted lines."""
    lines = format_service_id(freq)
    assert len(lines) >= 3
    assert "Frequency" in lines[0]


@pytest.mark.parametrize("freq", [146.94, 440.0, 851.0])
def test_format_all_offsets(freq):
    """format_all_offsets returns output for repeater frequencies."""
    lines = format_all_offsets(freq)
    assert len(lines) >= 1


# ─── P25Group middle/tail property setters ──────────────────────────


def test_p25_group_middle_setter():
    """Setting middle via property decodes all fields."""
    g = P25Group(group_name="TEST", group_id=100, long_name="Test")
    middle = bytearray(12)
    # audio_file = 42 at bytes 0-1
    middle[0] = 42
    middle[1] = 0
    # audio_profile = 0x0A at byte 2
    middle[2] = 0x0A
    g.middle = bytes(middle)
    assert g.audio_file == 42
    assert g.audio_profile == 0x0A


def test_p25_group_tail_setter():
    """Setting tail via property decodes all fields."""
    g = P25Group(group_name="TEST", group_id=100, long_name="Test")
    g.tail = bytes([1, 1, 2, 1])
    assert g.use_group_id is True
    assert g.encrypted is True
    assert g.tg_type == 2
    assert g.suppress is True


def test_p25_group_middle_wrong_length():
    """Middle block with wrong length raises ValueError."""
    g = P25Group(group_name="TEST", group_id=100, long_name="Test")
    with pytest.raises(ValueError, match="12 bytes"):
        g.middle = b'\x00' * 10


def test_p25_group_tail_wrong_length():
    """Tail block with wrong length raises ValueError."""
    g = P25Group(group_name="TEST", group_id=100, long_name="Test")
    with pytest.raises(ValueError, match="4 bytes"):
        g.tail = b'\x00' * 3


# ─── ConvChannel detailed flag tests ────────────────────────────────


@pytest.mark.parametrize("flag0", [True, False])
@pytest.mark.parametrize("calls", [True, False])
@pytest.mark.parametrize("alert", [True, False])
@pytest.mark.parametrize("scan_list_member", [True, False])
def test_conv_channel_extended_flags(flag0, calls, alert, scan_list_member):
    """Extended ConvChannel boolean flags survive roundtrip."""
    ch = ConvChannel(
        short_name="FLAGS",
        tx_freq=146.52, rx_freq=146.52,
        flag0=flag0, calls=calls, alert=alert,
        scan_list_member=scan_list_member,
    )
    data = ch.to_bytes()
    parsed, _ = ConvChannel.parse(data, 0)
    assert parsed.flag0 == flag0
    assert parsed.calls == calls
    assert parsed.alert == alert
    assert parsed.scan_list_member == scan_list_member


# ─── Multi-channel ConvSet serialization ────────────────────────────


@pytest.mark.parametrize("n_channels", [1, 2, 5, 10, 25])
def test_conv_set_various_sizes(n_channels):
    """ConvSet serializes correctly with various channel counts."""
    channels = [
        ConvChannel(
            short_name=f"CH{i:04d}",
            tx_freq=146.0 + i * 0.0125,
            rx_freq=146.0 + i * 0.0125,
        )
        for i in range(n_channels)
    ]
    cs = ConvSet(name="MULTI", channels=channels)
    data = cs.channels_to_bytes()
    assert len(data) > 0
    # Each channel + separators between them
    meta = cs.metadata_to_bytes()
    assert len(meta) > 0


# ─── P25GroupSet with various group counts ──────────────────────────


@pytest.mark.parametrize("n_groups", [1, 5, 10, 50, 100])
def test_p25_group_set_serialization(n_groups):
    """P25GroupSet serializes groups with various counts."""
    groups = [
        P25Group(
            group_name=f"TG{i:04d}",
            group_id=i,
            long_name=f"Talkgroup {i}",
        )
        for i in range(1, n_groups + 1)
    ]
    gs = P25GroupSet(name="BIGSET", groups=groups)
    assert len(gs.groups) == n_groups


# ─── TrunkSet metadata serialization ────────────────────────────────


@pytest.mark.parametrize("tx_min,tx_max", [
    (136.0, 870.0),
    (806.0, 870.0),
    (851.0, 869.0),
    (0.0, 0.0),
])
def test_trunk_set_band_limits(tx_min, tx_max):
    """TrunkSet band limit values serialize correctly."""
    ts = TrunkSet(
        name="LIMITS",
        channels=[TrunkChannel(851.0, 806.0)],
        tx_min=tx_min, tx_max=tx_max,
        rx_min=tx_min, rx_max=tx_max,
    )
    meta = ts.metadata_to_bytes()
    assert len(meta) > 0


# ─── Cross-validation: template freqs match service ID ──────────────


@pytest.mark.parametrize("template", ["murs", "gmrs", "frs", "noaa"])
def test_template_freqs_identifiable(template):
    """Frequencies from templates are identified by identify_service."""
    channels = get_template_channels(template)
    for ch in channels:
        result = identify_service(ch['tx_freq'])
        assert result['service'] != "Unknown", \
            f"Template '{template}' freq {ch['tx_freq']} not identified"


# ─── Harmonic and intermod edge cases ────────────────────────────────


def test_harmonic_detection():
    """Frequency conflict checker detects harmonics."""
    # 146.0 * 3 = 438.0 — if both in list, should detect
    freqs = [146.0, 438.0]
    warnings = check_frequency_conflicts(freqs)
    harmonic_warnings = [w for w in warnings if "Harmonic" in w]
    assert len(harmonic_warnings) > 0


def test_intermod_detection():
    """Frequency conflict checker detects intermod products."""
    # 2 * 146.0 - 145.0 = 147.0; if 147.0 is also in list, detected
    freqs = [145.0, 146.0, 147.0]
    warnings = check_frequency_conflicts(freqs)
    intermod_warnings = [w for w in warnings if "Intermod" in w]
    assert len(intermod_warnings) > 0


def test_no_conflicts_well_separated():
    """Well-separated frequencies produce no warnings at all."""
    freqs = [146.0, 440.0, 851.0]
    warnings = check_frequency_conflicts(freqs)
    assert len(warnings) == 0


@pytest.mark.parametrize("freq_list", [
    [146.52],
    [],
    [100.0, 200.0, 300.0],
    [462.5625, 462.5875, 462.6125, 462.6375, 462.6625, 462.6875, 462.7125],
])
def test_conflict_check_returns_list(freq_list):
    """check_frequency_conflicts always returns a list."""
    result = check_frequency_conflicts(freq_list)
    assert isinstance(result, list)
