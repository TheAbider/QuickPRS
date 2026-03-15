"""Frequency and tone reference tools for radio programming.

Provides CTCSS/DCS tone tables, repeater offset calculations,
frequency-to-channel identification, and tone validation utilities.
Useful as a quick reference when programming radios.
"""

# ─── CTCSS Tones (Standard EIA/TIA-603) ─────────────────────────────

CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
    94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9,
    171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
]

# ─── Standard DCS Codes ─────────────────────────────────────────────

DCS_CODES = [
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74,
    114, 115, 116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162,
    165, 172, 174, 205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325, 331, 332, 343,
    346, 351, 356, 364, 365, 371, 411, 412, 413, 423, 431, 432, 445, 446,
    452, 454, 455, 462, 464, 465, 466, 503, 506, 516, 523, 526, 532, 546,
    565, 606, 612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723, 731,
    732, 734, 743, 754,
]

# ─── Service channel tables ─────────────────────────────────────────

# FRS channels 1-22 (MHz)
_FRS_FREQS = {
    1: 462.5625, 2: 462.5875, 3: 462.6125, 4: 462.6375,
    5: 462.6625, 6: 462.6875, 7: 462.7125,
    8: 467.5625, 9: 467.5875, 10: 467.6125, 11: 467.6375,
    12: 467.6625, 13: 467.6875, 14: 467.7125,
    15: 462.5500, 16: 462.5750, 17: 462.6000, 18: 462.6250,
    19: 462.6500, 20: 462.6750, 21: 462.7000, 22: 462.7250,
}

# GMRS channels (same frequencies as FRS, different power/use)
_GMRS_FREQS = dict(_FRS_FREQS)

# MURS channels (MHz)
_MURS_FREQS = {
    1: 151.820, 2: 151.880, 3: 151.940,
    4: 154.570, 5: 154.600,
}

# Marine VHF common channels (simplex only, MHz)
_MARINE_FREQS = {
    6: 156.300, 9: 156.450, 10: 156.500,
    12: 156.600, 13: 156.650, 14: 156.700,
    16: 156.800, 22: 157.100, 67: 156.375,
    68: 156.425, 69: 156.475, 70: 156.525,
    71: 156.575, 72: 156.625, 78: 156.925,
}

# NOAA Weather Radio channels (MHz)
_NOAA_FREQS = {
    1: 162.400, 2: 162.425, 3: 162.450, 4: 162.475,
    5: 162.500, 6: 162.525, 7: 162.550,
}

# Build reverse lookup: freq -> (service, channel)
_FREQ_TO_CHANNEL = {}
for _ch, _f in _FRS_FREQS.items():
    _FREQ_TO_CHANNEL[round(_f, 4)] = ("FRS", _ch)
for _ch, _f in _GMRS_FREQS.items():
    # GMRS shares frequencies with FRS; store as GMRS too
    key = round(_f, 4)
    if key in _FREQ_TO_CHANNEL:
        _FREQ_TO_CHANNEL[key] = ("FRS/GMRS", _ch)
    else:
        _FREQ_TO_CHANNEL[key] = ("GMRS", _ch)
for _ch, _f in _MURS_FREQS.items():
    _FREQ_TO_CHANNEL[round(_f, 4)] = ("MURS", _ch)
for _ch, _f in _MARINE_FREQS.items():
    _FREQ_TO_CHANNEL[round(_f, 4)] = ("Marine VHF", _ch)
for _ch, _f in _NOAA_FREQS.items():
    _FREQ_TO_CHANNEL[round(_f, 4)] = ("NOAA", _ch)


# ─── Public API ──────────────────────────────────────────────────────

def calculate_repeater_offset(freq_mhz):
    """Calculate standard repeater offset for a frequency.

    Returns (offset_mhz, direction) tuple where direction is '+' or '-'.

    Standard offsets:
    - 2m (144-148 MHz): +/- 0.6 MHz (output below 147 = +, above = -)
    - 220 (222-225 MHz): -1.6 MHz
    - 70cm (420-450 MHz): +/- 5.0 MHz (output below 445 = +, above = -)
    - 900 (902-928 MHz): -12.0 MHz (input higher than output)

    Returns None if frequency is not in a standard repeater band.
    """
    if 144.0 <= freq_mhz <= 148.0:
        direction = "+" if freq_mhz < 147.0 else "-"
        return (0.6, direction)
    elif 222.0 <= freq_mhz <= 225.0:
        return (1.6, "-")
    elif 420.0 <= freq_mhz <= 450.0:
        direction = "+" if freq_mhz < 445.0 else "-"
        return (5.0, direction)
    elif 902.0 <= freq_mhz <= 928.0:
        return (12.0, "-")
    return None


def freq_to_channel(freq_mhz):
    """Convert frequency to channel number for known services.

    Args:
        freq_mhz: frequency in MHz

    Returns:
        (service, channel_num) tuple, or None if not a known channel.
        service is one of: 'FRS', 'FRS/GMRS', 'GMRS', 'MURS',
        'Marine VHF', 'NOAA'
    """
    key = round(freq_mhz, 4)
    return _FREQ_TO_CHANNEL.get(key)


def channel_to_freq(service, channel_num):
    """Convert service + channel number to frequency.

    Args:
        service: 'FRS', 'GMRS', 'MURS', 'Marine' or 'Marine VHF', 'NOAA'
        channel_num: integer channel number

    Returns:
        frequency in MHz, or None if not a valid channel.
    """
    service_upper = service.upper().strip()
    table = None
    if service_upper in ("FRS", "FRS/GMRS"):
        table = _FRS_FREQS
    elif service_upper == "GMRS":
        table = _GMRS_FREQS
    elif service_upper == "MURS":
        table = _MURS_FREQS
    elif service_upper in ("MARINE", "MARINE VHF"):
        table = _MARINE_FREQS
    elif service_upper == "NOAA":
        table = _NOAA_FREQS
    if table is None:
        return None
    return table.get(channel_num)


def validate_ctcss_tone(tone_str):
    """Check if a string represents a valid CTCSS or DCS tone.

    Accepts:
    - CTCSS: "100.0", "141.3", etc. (must match standard tone list)
    - DCS: "D023N", "D023I", "023", "23" (octal DCS code)

    Returns:
        (tone_type, value) tuple:
        - ('CTCSS', 100.0) for valid CTCSS
        - ('DCS', 23) for valid DCS (normal polarity)
        - ('DCS_I', 23) for inverted DCS
        - None if not valid
    """
    tone_str = tone_str.strip()
    if not tone_str:
        return None

    # Try DCS format: D023N, D023I, or bare number
    if tone_str.upper().startswith("D") and len(tone_str) >= 4:
        code_part = tone_str[1:-1] if tone_str[-1].upper() in ("N", "I") else tone_str[1:]
        polarity = tone_str[-1].upper() if tone_str[-1].upper() in ("N", "I") else "N"
        try:
            code = int(code_part)
            if code in DCS_CODES:
                return ("DCS_I" if polarity == "I" else "DCS", code)
        except ValueError:
            pass

    # Try CTCSS (float)
    try:
        val = float(tone_str)
        if val in CTCSS_TONES:
            return ("CTCSS", val)
        # Check if it could be a DCS code entered as integer
        if val == int(val) and int(val) in DCS_CODES:
            return ("DCS", int(val))
        return None
    except ValueError:
        pass

    return None


def nearest_ctcss(freq):
    """Find the nearest standard CTCSS tone to a given frequency.

    Args:
        freq: frequency in Hz (float)

    Returns:
        (nearest_tone, difference) tuple where difference is
        freq - nearest_tone.
    """
    best = CTCSS_TONES[0]
    best_diff = abs(freq - best)
    for tone in CTCSS_TONES[1:]:
        diff = abs(freq - tone)
        if diff < best_diff:
            best = tone
            best_diff = diff
    return (best, freq - best)


def format_ctcss_table():
    """Format CTCSS tones as a text table.

    Returns list of formatted lines.
    """
    lines = ["CTCSS Tones (EIA/TIA-603 Standard)", "=" * 50]
    # 5 columns
    cols = 5
    rows = (len(CTCSS_TONES) + cols - 1) // cols
    for r in range(rows):
        parts = []
        for c in range(cols):
            idx = c * rows + r
            if idx < len(CTCSS_TONES):
                parts.append(f"{CTCSS_TONES[idx]:>6.1f} Hz")
            else:
                parts.append(" " * 10)
        lines.append("  ".join(parts))
    lines.append(f"\nTotal: {len(CTCSS_TONES)} standard tones")
    return lines


def format_dcs_table():
    """Format DCS codes as a text table.

    Returns list of formatted lines.
    """
    lines = ["DCS Codes (Standard)", "=" * 60]
    # 8 columns
    cols = 8
    rows = (len(DCS_CODES) + cols - 1) // cols
    for r in range(rows):
        parts = []
        for c in range(cols):
            idx = c * rows + r
            if idx < len(DCS_CODES):
                parts.append(f"D{DCS_CODES[idx]:03d}N")
            else:
                parts.append("     ")
        lines.append("  ".join(parts))
    lines.append(f"\nTotal: {len(DCS_CODES)} standard codes")
    return lines


def format_repeater_offset(freq_mhz):
    """Format repeater offset info for a frequency as text lines.

    Returns list of strings.
    """
    result = calculate_repeater_offset(freq_mhz)
    if result is None:
        return [f"{freq_mhz:.4f} MHz: not in a standard repeater band"]

    offset, direction = result
    if direction == "+":
        input_freq = freq_mhz + offset
    else:
        input_freq = freq_mhz - offset

    # Determine band name
    if 144.0 <= freq_mhz <= 148.0:
        band = "2m (144-148 MHz)"
    elif 222.0 <= freq_mhz <= 225.0:
        band = "1.25m (222-225 MHz)"
    elif 420.0 <= freq_mhz <= 450.0:
        band = "70cm (420-450 MHz)"
    elif 902.0 <= freq_mhz <= 928.0:
        band = "33cm (902-928 MHz)"
    else:
        band = "unknown"

    return [
        f"Output (RX): {freq_mhz:.4f} MHz",
        f"Input  (TX): {input_freq:.4f} MHz",
        f"Offset:      {direction}{offset:.1f} MHz",
        f"Band:        {band}",
    ]


def format_channel_id(freq_mhz):
    """Identify a frequency as a known service channel.

    Returns list of strings.
    """
    result = freq_to_channel(freq_mhz)
    if result is None:
        return [f"{freq_mhz:.4f} MHz: not a recognized service channel"]

    service, ch_num = result
    return [f"{freq_mhz:.4f} MHz = {service} Channel {ch_num}"]


# ─── Frequency Band Allocations ───────────────────────────────────

_BAND_ALLOCATIONS = [
    # (low, high, service, band_name, notes)
    (26.965, 27.405, "CB Radio", "11m", "Citizens Band, 40 channels"),
    (29.7, 50.0, "VHF Low Band", "VHF Low", "Public safety, business"),
    (50.0, 54.0, "Amateur", "6m", "Amateur Radio"),
    (72.0, 76.0, "Auxillary Services", "VHF", "Radio control, telemetry"),
    (108.0, 117.975, "Aeronautical", "VHF Air Nav", "Navigation aids (VOR, ILS)"),
    (118.0, 136.975, "Aeronautical", "VHF Air", "Aircraft communications"),
    (137.0, 144.0, "Federal/Military", "VHF Federal", "Military, federal government"),
    (144.0, 148.0, "Amateur", "2m", "Amateur Radio"),
    (148.0, 150.8, "Federal/Military", "VHF Federal", "Military land mobile"),
    (150.8, 154.0, "Public Safety", "VHF High", "Police, fire, EMS"),
    (154.0, 156.0, "Business", "VHF High", "Business, industrial"),
    (156.0, 157.425, "Marine", "VHF Marine", "Maritime mobile"),
    (157.45, 161.575, "Public Safety", "VHF High", "Public safety, utilities"),
    (161.575, 162.0, "Business", "VHF High", "Paging, business"),
    (162.0, 174.0, "Federal/Government", "VHF High", "Federal, weather radio"),
    (174.0, 216.0, "Broadcasting", "VHF TV", "Television channels 7-13"),
    (216.0, 222.0, "Federal/Maritime", "1.25m", "Maritime, federal"),
    (222.0, 225.0, "Amateur", "1.25m", "Amateur Radio"),
    (225.0, 400.0, "Federal/Military", "UHF Military", "Military aviation, satellites"),
    (400.0, 406.0, "Federal", "UHF Federal", "Meteorological aids"),
    (406.0, 420.0, "Federal", "UHF Federal", "Government, land mobile"),
    (420.0, 450.0, "Amateur", "70cm", "Amateur Radio"),
    (450.0, 470.0, "Business/Public Safety", "UHF", "UHF land mobile"),
    (470.0, 512.0, "Public Safety", "UHF T-Band", "T-Band public safety (select cities)"),
    (746.0, 806.0, "Public Safety", "700 MHz", "FirstNet, public safety broadband"),
    (806.0, 824.0, "Public Safety/SMR", "800 MHz", "Public safety, trunked systems"),
    (824.0, 849.0, "Cellular", "800 MHz Cellular", "Cellular mobile transmit"),
    (849.0, 869.0, "Public Safety/SMR", "800 MHz", "Public safety, SMR"),
    (869.0, 894.0, "Cellular", "800 MHz Cellular", "Cellular base transmit"),
    (894.0, 902.0, "Public Safety/SMR", "900 MHz", "SMR, narrowband PCS"),
    (902.0, 928.0, "Amateur", "33cm", "Amateur Radio"),
    (929.0, 960.0, "Paging/Federal", "900 MHz", "Paging, federal"),
]

# Known service frequencies (exact matches for specific services)
_KNOWN_SERVICES = {
    # FRS/GMRS (462-467 MHz range handled by channel lookup)
    # MURS (151-154 MHz range handled by channel lookup)
    # NOAA Weather Radio
    162.400: ("NOAA Weather Radio", "WX1"),
    162.425: ("NOAA Weather Radio", "WX2"),
    162.450: ("NOAA Weather Radio", "WX3"),
    162.475: ("NOAA Weather Radio", "WX4"),
    162.500: ("NOAA Weather Radio", "WX5"),
    162.525: ("NOAA Weather Radio", "WX6"),
    162.550: ("NOAA Weather Radio", "WX7"),
    # Common public safety / interop
    155.475: ("Public Safety", "National calling/distress"),
    156.800: ("Marine VHF", "Channel 16 - Distress/calling"),
    121.500: ("Aeronautical", "Emergency/distress"),
    243.000: ("Military", "Emergency/distress (UHF)"),
}


def calculate_all_offsets(freq_mhz):
    """Calculate all possible repeater input frequencies for a given output.

    Returns list of (input_freq, offset, band, standard) tuples.
    Each entry describes a possible repeater pairing.

    Covers amateur, GMRS, and commercial bands with standard offsets.
    """
    results = []

    # 2m band (144-148 MHz)
    if 144.0 <= freq_mhz <= 148.0:
        for direction, sign in [("+", 1), ("-", -1)]:
            input_f = freq_mhz + sign * 0.6
            if 144.0 <= input_f <= 148.0:
                results.append((
                    round(input_f, 4), 0.6, "2m",
                    f"{direction}0.6 MHz (standard amateur)"
                ))
        # Non-standard 1 MHz offset (some areas)
        for direction, sign in [("+", 1), ("-", -1)]:
            input_f = freq_mhz + sign * 1.0
            if 144.0 <= input_f <= 148.0:
                results.append((
                    round(input_f, 4), 1.0, "2m",
                    f"{direction}1.0 MHz (non-standard)"
                ))

    # 1.25m band (222-225 MHz)
    if 222.0 <= freq_mhz <= 225.0:
        input_f = freq_mhz - 1.6
        if 222.0 <= input_f <= 225.0:
            results.append((
                round(input_f, 4), 1.6, "1.25m",
                "-1.6 MHz (standard amateur)"
            ))

    # 70cm band (420-450 MHz)
    if 420.0 <= freq_mhz <= 450.0:
        for direction, sign in [("+", 1), ("-", -1)]:
            input_f = freq_mhz + sign * 5.0
            if 420.0 <= input_f <= 450.0:
                results.append((
                    round(input_f, 4), 5.0, "70cm",
                    f"{direction}5.0 MHz (standard amateur)"
                ))

    # GMRS repeater pairs (462.550-462.725 output, +5.0 MHz input)
    if 462.5500 <= freq_mhz <= 462.7250:
        input_f = freq_mhz + 5.0
        results.append((
            round(input_f, 4), 5.0, "GMRS",
            "+5.0 MHz (standard GMRS)"
        ))

    # 33cm band (902-928 MHz)
    if 902.0 <= freq_mhz <= 928.0:
        input_f = freq_mhz - 12.0
        if 902.0 <= input_f <= 928.0:
            results.append((
                round(input_f, 4), 12.0, "33cm",
                "-12.0 MHz (standard amateur)"
            ))
        # Also try +25 MHz (some areas)
        input_f = freq_mhz + 25.0
        if 902.0 <= input_f <= 928.0:
            results.append((
                round(input_f, 4), 25.0, "33cm",
                "+25.0 MHz (non-standard)"
            ))

    # 800 MHz commercial/public safety (+/- 45 MHz)
    if 806.0 <= freq_mhz <= 869.0:
        for direction, sign in [("+", 1), ("-", -1)]:
            input_f = freq_mhz + sign * 45.0
            if 806.0 <= input_f <= 869.0:
                results.append((
                    round(input_f, 4), 45.0, "800 MHz",
                    f"{direction}45.0 MHz (commercial/public safety)"
                ))

    return results


def identify_service(freq_mhz):
    """Identify what radio service a frequency belongs to.

    Returns dict with: service, band, allocation, notes
    Returns None if frequency is not in any known allocation.

    Services include: Amateur, GMRS, FRS, MURS, Marine, NOAA, Business,
    Public Safety, Federal, Aeronautical, etc.
    """
    result = {
        "frequency": freq_mhz,
        "service": "Unknown",
        "band": "Unknown",
        "allocation": "Not in known allocation table",
        "notes": "",
    }

    # Check known service channel tables first
    ch_info = freq_to_channel(freq_mhz)
    if ch_info:
        service, ch_num = ch_info
        result["service"] = service
        result["notes"] = f"Channel {ch_num}"

    # Check known exact frequencies
    key = round(freq_mhz, 4)
    if key in _KNOWN_SERVICES:
        svc, note = _KNOWN_SERVICES[key]
        result["service"] = svc
        result["notes"] = note

    # Find band allocation
    for low, high, svc, band, notes in _BAND_ALLOCATIONS:
        if low <= freq_mhz <= high:
            result["band"] = band
            result["allocation"] = f"{low:.3f}-{high:.3f} MHz: {svc}"
            if not result["notes"]:
                result["notes"] = notes
            # If we haven't identified a specific service yet, use the band
            if result["service"] == "Unknown":
                result["service"] = svc
            break

    return result


def check_frequency_conflicts(freq_list):
    """Check a list of frequencies for potential interference issues.

    Args:
        freq_list: list of frequencies in MHz

    Returns list of warning strings for:
    - Frequencies too close together (< 12.5 kHz for narrowband,
      < 25 kHz for wideband)
    - Harmonics that land on other frequencies in the list
    - Potential intermod products (2A-B, A+B-C patterns)
    """
    warnings = []
    freqs = sorted(freq_list)

    if len(freqs) < 2:
        return warnings

    # Check for too-close frequencies (with 0.01 kHz tolerance for float math)
    for i in range(len(freqs) - 1):
        spacing_khz = (freqs[i + 1] - freqs[i]) * 1000.0
        if spacing_khz < 12.5 - 0.01:
            warnings.append(
                f"Spacing conflict: {freqs[i]:.4f} and {freqs[i+1]:.4f} MHz "
                f"are only {spacing_khz:.1f} kHz apart "
                f"(minimum 12.5 kHz for narrowband)"
            )
        elif spacing_khz < 25.0 - 0.01:
            warnings.append(
                f"Tight spacing: {freqs[i]:.4f} and {freqs[i+1]:.4f} MHz "
                f"are only {spacing_khz:.1f} kHz apart "
                f"(may conflict in wideband mode)"
            )

    # Check for harmonic conflicts (2nd and 3rd harmonics)
    freq_set = set(round(f, 4) for f in freqs)
    for f in freqs:
        for harmonic in [2, 3]:
            h_freq = round(f * harmonic, 4)
            if h_freq in freq_set:
                warnings.append(
                    f"Harmonic conflict: {f:.4f} MHz harmonic {harmonic} "
                    f"= {h_freq:.4f} MHz (also in frequency list)"
                )

    # Check for two-signal intermod products (2A-B)
    for i in range(len(freqs)):
        for j in range(len(freqs)):
            if i == j:
                continue
            intermod = round(2 * freqs[i] - freqs[j], 4)
            if intermod in freq_set and intermod != round(freqs[i], 4):
                warnings.append(
                    f"Intermod product: 2x{freqs[i]:.4f} - {freqs[j]:.4f} "
                    f"= {intermod:.4f} MHz (hits another frequency)"
                )

    # Deduplicate warnings
    return list(dict.fromkeys(warnings))


def format_service_id(freq_mhz):
    """Format frequency identification as text lines.

    Returns list of strings with service identification details.
    """
    info = identify_service(freq_mhz)
    lines = [f"Frequency: {freq_mhz:.4f} MHz"]
    lines.append(f"Service:   {info['service']}")
    lines.append(f"Band:      {info['band']}")
    lines.append(f"Allocation: {info['allocation']}")
    if info['notes']:
        lines.append(f"Notes:     {info['notes']}")
    return lines


def format_all_offsets(freq_mhz):
    """Format all possible repeater offsets for a frequency.

    Returns list of strings.
    """
    results = calculate_all_offsets(freq_mhz)
    if not results:
        return [f"{freq_mhz:.4f} MHz: no standard repeater offsets found"]

    lines = [f"Possible repeater pairs for {freq_mhz:.4f} MHz output:"]
    lines.append("-" * 60)
    for input_freq, offset, band, standard in results:
        lines.append(
            f"  Input: {input_freq:.4f} MHz  "
            f"({standard})"
        )
    return lines


def format_conflict_check(freq_list):
    """Format frequency conflict check results.

    Args:
        freq_list: list of frequencies in MHz

    Returns list of strings.
    """
    warnings = check_frequency_conflicts(freq_list)
    lines = [f"Checking {len(freq_list)} frequencies for conflicts..."]
    if not warnings:
        lines.append("No conflicts found.")
    else:
        lines.append(f"Found {len(warnings)} potential issue(s):")
        for w in warnings:
            lines.append(f"  - {w}")
    return lines


# ─── Frequency Spectrum Map ────────────────────────────────────────

# Band definitions for frequency mapping
_FREQ_MAP_BANDS = [
    ("VHF Low", 29.7, 50.0),
    ("VHF", 136.0, 174.0),
    ("UHF", 400.0, 512.0),
    ("700 MHz", 746.0, 806.0),
    ("800 MHz", 806.0, 870.0),
    ("900 MHz", 894.0, 960.0),
]

# Short band aliases for CLI --band filter
_BAND_ALIASES = {
    "vhf": ("VHF Low", "VHF"),
    "uhf": ("UHF",),
    "700": ("700 MHz",),
    "800": ("800 MHz",),
    "900": ("900 MHz",),
    "all": None,  # None = show all
}


def _classify_freq(freq_mhz):
    """Classify a frequency into a band name."""
    for band_name, low, high in _FREQ_MAP_BANDS:
        if low <= freq_mhz <= high:
            return band_name
    return "Other"


def generate_freq_map(prs, band=None):
    """Generate a text-based frequency spectrum map from a PRS file.

    Shows all frequencies in use grouped by band, with channel/set names.

    Args:
        prs: parsed PRSFile
        band: optional band filter ('vhf', 'uhf', '700', '800', '900', 'all')
              None or 'all' shows all bands.

    Returns:
        list of formatted strings for display
    """
    from .record_types import (
        parse_trunk_channel_section,
        parse_conv_channel_section, parse_sets_from_sections,
    )

    # Determine which bands to show
    allowed_bands = None
    if band and band.lower() in _BAND_ALIASES:
        allowed_bands = _BAND_ALIASES[band.lower()]
    # allowed_bands = None means show all

    # Collect all frequencies with metadata
    # Each entry: (freq_mhz, label, freq_type)
    # freq_type: 'simplex', 'trunk', 'repeater'
    entries = []

    # Parse trunk sets
    data_sec = prs.get_section_by_class("CTrunkChannel")
    set_sec = prs.get_section_by_class("CTrunkSet")
    if data_sec and set_sec:
        trunk_sets = parse_sets_from_sections(
            set_sec.raw, data_sec.raw, parse_trunk_channel_section)
        for ts in trunk_sets:
            for ch in ts.channels:
                if ch.rx_freq > 0:
                    entries.append((ch.rx_freq, ts.name, "trunk"))

    # Parse conv sets
    data_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if data_sec and set_sec:
        conv_sets = parse_sets_from_sections(
            set_sec.raw, data_sec.raw, parse_conv_channel_section)
        for cs in conv_sets:
            for ch in cs.channels:
                if ch.rx_freq > 0:
                    # Determine type
                    if abs(ch.tx_freq - ch.rx_freq) < 0.001:
                        ftype = "simplex"
                    else:
                        ftype = "repeater"
                    # Build label
                    tone_info = ""
                    if ch.tx_tone:
                        tone_info = f" (CTCSS {ch.tx_tone})"
                    elif ch.rx_tone:
                        tone_info = f" (CTCSS {ch.rx_tone})"
                    label = f"{ch.short_name}{tone_info}"
                    entries.append((ch.rx_freq, label, ftype))

    if not entries:
        return ["No frequencies found in this personality."]

    # Group by band
    band_entries = {}
    for freq, label, ftype in entries:
        band_name = _classify_freq(freq)
        if allowed_bands is not None and band_name not in allowed_bands:
            continue
        band_entries.setdefault(band_name, []).append((freq, label, ftype))

    if not band_entries:
        return [f"No frequencies found in the '{band}' band."]

    # Sort entries within each band by frequency
    for b in band_entries:
        band_entries[b].sort(key=lambda x: x[0])

    # Find the display width needed
    max_line_width = 56

    # Build output with box drawing
    lines = []

    # Top border
    lines.append(f"+{'=' * (max_line_width - 2)}+")

    band_order = [b for b, _, _ in _FREQ_MAP_BANDS if b in band_entries]
    # Add "Other" if present
    if "Other" in band_entries:
        band_order.append("Other")

    for bi, band_name in enumerate(band_order):
        items = band_entries[band_name]

        # Find band range for display
        band_low = None
        band_high = None
        for bname, low, high in _FREQ_MAP_BANDS:
            if bname == band_name:
                band_low = low
                band_high = high
                break

        if band_low and band_high:
            header = f" {band_name} ({band_low:.0f}-{band_high:.0f} MHz)"
        else:
            header = f" {band_name}"

        # Band header
        lines.append(f"|{header:<{max_line_width - 2}}|")
        lines.append(f"|{'-' * (max_line_width - 2)}|")

        # Deduplicate frequencies (show unique freq+label combos)
        seen = set()
        for freq, label, ftype in items:
            key = (round(freq, 4), label)
            if key in seen:
                continue
            seen.add(key)

            # Choose bar style based on type
            bar = {"trunk": "////", "repeater": "####",
                   "simplex": "===="}. get(ftype, "====")

            # Format type label
            type_label = {"trunk": "trunk", "repeater": "rptr",
                          "simplex": "simplex"}.get(ftype, "")

            if ftype == "trunk":
                detail = f"{label} ({type_label})"
            else:
                # Conv channels already have tone info in label
                if type_label and f"({type_label})" not in label:
                    detail = f"{label} ({type_label})"
                else:
                    detail = label

            freq_str = f"{freq:>10.4f}"
            content = f" {freq_str} {bar} {detail}"
            # Truncate if too long
            max_content = max_line_width - 2
            if len(content) > max_content:
                content = content[:max_content - 3] + "..."
            lines.append(f"|{content:<{max_line_width - 2}}|")

        # Separator between bands (not after last)
        if bi < len(band_order) - 1:
            lines.append(f"|{'=' * (max_line_width - 2)}|")

    # Bottom border
    lines.append(f"+{'=' * (max_line_width - 2)}+")

    # Summary
    total_freqs = len(set(round(f, 4) for f, _, _ in entries
                         if allowed_bands is None
                         or _classify_freq(f) in allowed_bands))
    bands_shown = len(band_order)
    lines.append("")
    lines.append(f"Total: {total_freqs} unique frequencies "
                 f"across {bands_shown} band(s)")

    # Legend
    lines.append("")
    lines.append("Legend: ==== simplex  #### repeater  //// trunked")

    return lines
