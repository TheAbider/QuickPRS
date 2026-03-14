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
