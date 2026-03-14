"""Standard IDEN template library for P25 channel identifier sets.

P25 IDEN tables map logical channel numbers to frequencies. The radio uses
these to tune when the control channel assigns a voice channel. Parameters
are derived from FCC band plans (public data).

Templates cover every standard combination:
  800 MHz / 700 MHz / 900 MHz  x  FDMA / TDMA
  Plus a mixed-mode 800 MHz FDMA+TDMA template.
"""

from dataclasses import dataclass, field
from typing import Dict, List


# ─── P25 Frequency Band Definitions ──────────────────────────────────
# Public FCC band plan data — no copyright issues.
# TX offsets are standardized per band for P25 trunked systems.

P25_BANDS = [
    # (name, rx_low, rx_high, tx_offset_mhz)
    ('700',       764.0,  776.0,   30.0),
    ('700_upper', 794.0,  806.0,  -30.0),
    ('800',       851.0,  869.0,  -45.0),
    ('900',       935.0,  940.0,  -39.0),
    ('VHF',       136.0,  174.0,    0.0),
    ('UHF',       380.0,  512.0,    0.0),
]


def detect_p25_band(freq_mhz):
    """Determine which P25 band a frequency falls in.

    Returns (band_name, tx_offset_mhz) or (None, 0.0).
    """
    for name, rx_low, rx_high, offset in P25_BANDS:
        if rx_low <= freq_mhz <= rx_high:
            return name, offset
    return None, 0.0


def calculate_tx_freq(rx_freq_mhz):
    """Calculate TX frequency from RX (downlink) frequency.

    RadioReference lists downlink (RX) frequencies. The radio needs
    both TX and RX. TX offset is determined by the frequency band:
      700 MHz: +30 MHz  (TX 794-806, RX 764-776)
      800 MHz: -45 MHz  (TX 806-824, RX 851-869)
      900 MHz: -39 MHz  (TX 896-901, RX 935-940)
      VHF/UHF: 0 (simplex or system-specific)
    """
    _, offset = detect_p25_band(rx_freq_mhz)
    return round(rx_freq_mhz + offset, 6)


# ─── Standard P25 IDEN Table Generation ──────────────────────────────

def build_standard_iden_entries(frequencies, system_type=""):
    """Generate IDEN table entries from frequencies and system type.

    Uses standard P25 channel plans based on the frequency band.
    Returns list of dicts suitable for make_iden_set().
    """
    if not frequencies:
        return []

    is_tdma = "Phase II" in system_type
    spacing = 6250 if is_tdma else 12500
    bw = 6250 if is_tdma else 12500
    iden_type = 1 if is_tdma else 0

    # Find the band from the first frequency
    rx_freq = frequencies[0] if isinstance(frequencies[0], (int, float)) \
        else frequencies[0][0]
    band_name, tx_offset = detect_p25_band(rx_freq)

    if not band_name:
        return []

    # tx_offset is MHz (float32 in binary), e.g. -45.0, +30.0
    tx_offset_mhz = tx_offset

    if band_name == '800':
        return _standard_800_iden(spacing, bw, tx_offset_mhz, iden_type)
    elif band_name in ('700', '700_upper'):
        return _standard_700_iden(spacing, bw, tx_offset_mhz, iden_type)
    elif band_name == '900':
        return _standard_900_iden(spacing, bw, tx_offset_mhz, iden_type)
    else:
        return _derive_iden_from_freqs(
            frequencies, spacing, bw, tx_offset_mhz, iden_type)


def _standard_800_iden(spacing, bw, tx_offset_mhz, iden_type):
    """Standard 800 MHz rebanded IDEN table (16 entries).

    Covers 851.00625 - 867.88125 MHz in 1.125 MHz blocks.
    This is the standard table used by PSERN, BEE00, and all
    standard 800 MHz rebanded P25 systems.
    """
    return [
        {
            'base_freq_hz': 851006250 + i * 1125000,
            'chan_spacing_hz': spacing,
            'bandwidth_hz': bw,
            'tx_offset_mhz': tx_offset_mhz,
            'iden_type': iden_type,
        }
        for i in range(16)
    ]


def _standard_700_iden(spacing, bw, tx_offset_mhz, iden_type):
    """Standard 700 MHz P25 IDEN table (16 entries).

    Covers 764-776 MHz range in 750 kHz blocks.
    """
    return [
        {
            'base_freq_hz': 764006250 + i * 750000,
            'chan_spacing_hz': spacing,
            'bandwidth_hz': bw,
            'tx_offset_mhz': tx_offset_mhz,
            'iden_type': iden_type,
        }
        for i in range(16)
    ]


def _standard_900_iden(spacing, bw, tx_offset_mhz, iden_type):
    """Standard 900 MHz P25 IDEN table (8 active entries)."""
    entries = [
        {
            'base_freq_hz': 935012500 + i * 625000,
            'chan_spacing_hz': spacing,
            'bandwidth_hz': bw,
            'tx_offset_mhz': tx_offset_mhz,
            'iden_type': iden_type,
        }
        for i in range(8)
    ]
    # Pad to 16 with empty entries
    while len(entries) < 16:
        entries.append({
            'base_freq_hz': 0, 'chan_spacing_hz': 0,
            'bandwidth_hz': 0, 'tx_offset': 0, 'iden_type': 0,
        })
    return entries


def _derive_iden_from_freqs(frequencies, spacing, bw, tx_offset_mhz, iden_type):
    """Derive IDEN entries from a frequency list (fallback for unknown bands)."""
    rx_freqs = sorted(set(
        f if isinstance(f, (int, float)) else f[0]
        for f in frequencies
    ))

    if not rx_freqs:
        return []

    min_freq_hz = int(rx_freqs[0] * 1_000_000)
    max_freq_hz = int(rx_freqs[-1] * 1_000_000)
    range_hz = max_freq_hz - min_freq_hz

    if range_hz == 0:
        return [{
            'base_freq_hz': min_freq_hz,
            'chan_spacing_hz': spacing, 'bandwidth_hz': bw,
            'tx_offset_mhz': tx_offset_mhz, 'iden_type': iden_type,
        }]

    num_blocks = min(16, max(1, range_hz // 500_000 + 1))
    block_size = range_hz // num_blocks

    entries = []
    for i in range(num_blocks):
        base_hz = min_freq_hz + i * block_size
        base_hz = (base_hz // spacing) * spacing + (spacing // 2)
        entries.append({
            'base_freq_hz': base_hz,
            'chan_spacing_hz': spacing, 'bandwidth_hz': bw,
            'tx_offset_mhz': tx_offset_mhz, 'iden_type': iden_type,
        })

    # Pad to 16
    while len(entries) < 16:
        entries.append({
            'base_freq_hz': 0, 'chan_spacing_hz': 0,
            'bandwidth_hz': 0, 'tx_offset': 0, 'iden_type': 0,
        })
    return entries


# ─── IDEN Template Definitions ────────────────────────────────────────

@dataclass
class IdenTemplate:
    """A standard IDEN template for a frequency band + mode combination."""
    key: str                    # lookup key (e.g. "800-TDMA")
    label: str                  # display name (e.g. "800 MHz TDMA (Phase II)")
    band: str                   # band name from P25_BANDS
    mode: str                   # "FDMA", "TDMA", or "Mixed"
    description: str            # user-facing description
    entries: List[dict] = field(default_factory=list)


def _build_templates():
    """Build the complete template catalog."""
    templates = {}

    # 800 MHz FDMA (Phase I)
    t = IdenTemplate(
        key="800-FDMA",
        label="800 MHz FDMA (Phase I)",
        band="800", mode="FDMA",
        description="Standard 800 MHz rebanded, 12.5 kHz FDMA. "
                    "16 entries covering 851-868 MHz.",
        entries=_standard_800_iden(12500, 12500, -45.0, 0),
    )
    templates[t.key] = t

    # 800 MHz TDMA (Phase II)
    t = IdenTemplate(
        key="800-TDMA",
        label="800 MHz TDMA (Phase II)",
        band="800", mode="TDMA",
        description="Standard 800 MHz rebanded, 6.25 kHz TDMA. "
                    "16 entries covering 851-868 MHz.",
        entries=_standard_800_iden(6250, 6250, -45.0, 1),
    )
    templates[t.key] = t

    # 800 MHz Mixed (FDMA slots 0-1 + TDMA slots 2-15)
    # Like BEE00 in PAWSOVERMAWS — systems with both Phase I and Phase II
    fdma_entries = _standard_800_iden(12500, 12500, -45.0, 0)
    tdma_entries = _standard_800_iden(6250, 6250, -45.0, 1)
    mixed_entries = fdma_entries[:2] + tdma_entries[2:]
    t = IdenTemplate(
        key="800-Mixed",
        label="800 MHz Mixed FDMA+TDMA",
        band="800", mode="Mixed",
        description="800 MHz with FDMA (slots 0-1) and TDMA (slots 2-15). "
                    "For systems using both Phase I and Phase II.",
        entries=mixed_entries,
    )
    templates[t.key] = t

    # 700 MHz FDMA
    t = IdenTemplate(
        key="700-FDMA",
        label="700 MHz FDMA (Phase I)",
        band="700", mode="FDMA",
        description="Standard 700 MHz, 12.5 kHz FDMA. "
                    "16 entries covering 764-776 MHz, TX +30 MHz.",
        entries=_standard_700_iden(12500, 12500, 30.0, 0),
    )
    templates[t.key] = t

    # 700 MHz TDMA
    t = IdenTemplate(
        key="700-TDMA",
        label="700 MHz TDMA (Phase II)",
        band="700", mode="TDMA",
        description="Standard 700 MHz, 6.25 kHz TDMA. "
                    "16 entries covering 764-776 MHz, TX +30 MHz.",
        entries=_standard_700_iden(6250, 6250, 30.0, 1),
    )
    templates[t.key] = t

    # 900 MHz FDMA
    t = IdenTemplate(
        key="900-FDMA",
        label="900 MHz FDMA (Phase I)",
        band="900", mode="FDMA",
        description="Standard 900 MHz, 12.5 kHz FDMA. "
                    "8 active entries (935-939 MHz), TX -39 MHz.",
        entries=_standard_900_iden(12500, 12500, -39.0, 0),
    )
    templates[t.key] = t

    # 900 MHz TDMA
    t = IdenTemplate(
        key="900-TDMA",
        label="900 MHz TDMA (Phase II)",
        band="900", mode="TDMA",
        description="Standard 900 MHz, 6.25 kHz TDMA. "
                    "8 active entries (935-939 MHz), TX -39 MHz.",
        entries=_standard_900_iden(6250, 6250, -39.0, 1),
    )
    templates[t.key] = t

    return templates


# Module-level template catalog — built once on import
STANDARD_IDEN_TEMPLATES: Dict[str, IdenTemplate] = _build_templates()


def get_template(key):
    """Get a template by key. Returns None if not found."""
    return STANDARD_IDEN_TEMPLATES.get(key)


def get_template_keys():
    """Get all available template keys in display order."""
    return list(STANDARD_IDEN_TEMPLATES.keys())


def get_default_name(key):
    """Suggest a default IDEN set name for a template key.

    Returns a 5-char name like "8TDMA" or "7FDMA".
    """
    names = {
        "800-FDMA": "8FDMA",
        "800-TDMA": "8TDMA",
        "800-Mixed": "8MIX",
        "700-FDMA": "7FDMA",
        "700-TDMA": "7TDMA",
        "900-FDMA": "9FDMA",
        "900-TDMA": "9TDMA",
    }
    return names.get(key, key[:5])


def auto_select_template_key(frequencies, system_type=""):
    """Pick the best IDEN template key based on frequencies and system type.

    Returns template key (e.g. "800-TDMA") or None if no match.
    """
    if not frequencies:
        return None

    rx_freq = frequencies[0] if isinstance(frequencies[0], (int, float)) \
        else frequencies[0][0]
    band_name, _ = detect_p25_band(rx_freq)
    if not band_name:
        return None

    # Normalize band names
    if band_name == '700_upper':
        band_name = '700'

    is_tdma = "Phase II" in (system_type or "")
    mode = "TDMA" if is_tdma else "FDMA"

    key = f"{band_name}-{mode}"
    if key in STANDARD_IDEN_TEMPLATES:
        return key

    return None


def find_matching_iden_set(prs, template_key):
    """Check if PRS already has an IDEN set matching a standard template.

    Compares base frequencies, spacing, bandwidth, and type against
    the template entries. Returns the IDEN set name if found, None otherwise.
    """
    from .record_types import parse_class_header, parse_iden_section

    template = get_template(template_key)
    if not template:
        return None

    elem_sec = prs.get_section_by_class("CDefaultIdenElem")
    set_sec = prs.get_section_by_class("CIdenDataSet")
    if not elem_sec or not set_sec:
        return None

    # Get first_count from the set section
    _, _, _, data_start = parse_class_header(set_sec.raw, 0)
    if data_start + 2 <= len(set_sec.raw):
        first_count = int.from_bytes(
            set_sec.raw[data_start:data_start + 2], 'little')
    else:
        return None

    # Parse existing IDEN sets
    _, _, _, elem_data_start = parse_class_header(elem_sec.raw, 0)
    existing = parse_iden_section(
        elem_sec.raw, elem_data_start, len(elem_sec.raw), first_count)

    # Compare each existing set against the template
    template_entries = template.entries
    for iset in existing:
        if _iden_entries_match(iset.elements, template_entries):
            return iset.name

    return None


def _iden_entries_match(elements, template_entries):
    """Check if IDEN elements match a template's entries.

    Compares base_freq, spacing, bandwidth, and iden_type for non-empty slots.
    """
    if len(elements) != len(template_entries):
        return False

    for elem, tmpl in zip(elements, template_entries):
        t_base = tmpl.get('base_freq_hz', 0)
        t_spacing = tmpl.get('chan_spacing_hz', 0)
        t_bw = tmpl.get('bandwidth_hz', 0)
        t_type = tmpl.get('iden_type', 0)

        # Both empty = match
        if elem.base_freq_hz == 0 and t_base == 0:
            continue

        # One empty, one not = no match
        if (elem.base_freq_hz == 0) != (t_base == 0):
            return False

        # Compare all key fields
        if (elem.base_freq_hz != t_base or
                elem.chan_spacing_hz != t_spacing or
                elem.bandwidth_hz != t_bw or
                elem.iden_type != t_type):
            return False

    return True
