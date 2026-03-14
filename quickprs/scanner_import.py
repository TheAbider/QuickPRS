"""Scanner format import — convert channel lists from popular scanner formats.

Supports:
  - Uniden Sentinel CSV export
  - CHIRP CSV export
  - SDRTrunk CSV export (channel list)
  - SDRTrunk talkgroup CSV import
  - DSD+ frequency list import (one freq per line in Hz)
  - RadioLog CSV import
  - Auto-detection by examining CSV headers

Each importer returns a list of dicts compatible with make_conv_channel():
    {short_name, tx_freq, rx_freq, tx_tone, rx_tone, long_name, system_name}

Talkgroup importers return a list of dicts:
    {group_id, short_name, long_name}
"""

import csv
from pathlib import Path


# ─── Header signatures for auto-detection ─────────────────────────────

# Uniden Sentinel exports have columns like:
#   System,Department,Channel,Frequency,Modulation,Tone,...
_UNIDEN_MARKERS = {"system", "department", "channel", "frequency"}

# CHIRP exports have columns like:
#   Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,...
_CHIRP_MARKERS = {"location", "name", "frequency", "duplex", "offset"}

# SDRTrunk exports (channel list) — similar to generic
_SDRTRUNK_MARKERS = {"channel", "frequency", "protocol", "system"}


def detect_scanner_format(filepath):
    """Auto-detect scanner CSV format by examining headers.

    Returns: 'uniden', 'chirp', 'sdrtrunk', or 'unknown'
    """
    filepath = Path(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return 'unknown'
    except (FileNotFoundError, PermissionError, UnicodeDecodeError):
        return 'unknown'

    header_lower = {h.strip().lower() for h in header}

    # Check CHIRP first (more specific — has 'duplex' and 'offset')
    if _CHIRP_MARKERS.issubset(header_lower):
        return 'chirp'

    # Check Uniden (has 'department')
    if _UNIDEN_MARKERS.issubset(header_lower):
        return 'uniden'

    # Check SDRTrunk (has 'protocol')
    if 'protocol' in header_lower and 'frequency' in header_lower:
        return 'sdrtrunk'

    return 'unknown'


def import_uniden_csv(filepath):
    """Import channels from Uniden scanner CSV export.

    Uniden CSV format (from Sentinel software):
    System,Department,Channel,Frequency,Modulation,Tone,...

    Returns list of dicts with keys: short_name, tx_freq, rx_freq,
    tx_tone, rx_tone, long_name, system_name
    """
    filepath = Path(filepath)
    channels = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower(): v.strip()
                         for k, v in row.items() if k}

            freq_str = (row_lower.get('frequency', '') or
                        row_lower.get('freq', ''))
            if not freq_str:
                continue
            try:
                freq = float(freq_str)
            except ValueError:
                continue
            if freq <= 0:
                continue

            # Channel name: prefer Channel column, fall back to Department
            ch_name = (row_lower.get('channel', '') or
                       row_lower.get('name', '') or
                       row_lower.get('department', ''))
            if not ch_name:
                ch_name = f"{freq:.4f}"

            system_name = row_lower.get('system', '')
            department = row_lower.get('department', '')

            # Tone handling — Uniden uses various column names
            tone = row_lower.get('tone', '') or row_lower.get('ctcss', '')

            # Build long name from system + department + channel
            parts = [p for p in [department, ch_name] if p]
            long_name = ' '.join(parts)

            channels.append({
                'short_name': ch_name[:8].upper(),
                'tx_freq': freq,
                'rx_freq': freq,  # Uniden exports typically RX-only
                'tx_tone': tone,
                'rx_tone': tone,
                'long_name': long_name[:16].upper(),
                'system_name': system_name,
            })

    return channels


def import_chirp_csv(filepath):
    """Import channels from CHIRP CSV export.

    CHIRP CSV format:
    Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,
    DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,...

    Duplex: '', '+', '-', 'split', 'off'
    Tone: '', 'Tone', 'TSQL', 'DTCS', 'Cross'

    Returns list of dicts compatible with make_conv_channel().
    """
    filepath = Path(filepath)
    channels = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower(): v.strip()
                         for k, v in row.items() if k}

            freq_str = row_lower.get('frequency', '')
            if not freq_str:
                continue
            try:
                freq = float(freq_str)
            except ValueError:
                continue
            if freq <= 0:
                continue

            name = row_lower.get('name', '') or f"{freq:.4f}"

            # Calculate TX/RX from duplex and offset
            duplex = row_lower.get('duplex', '')
            offset_str = row_lower.get('offset', '0')
            try:
                offset = float(offset_str)
            except ValueError:
                offset = 0.0

            rx_freq = freq
            if duplex == '+':
                tx_freq = freq + offset
            elif duplex == '-':
                tx_freq = freq - offset
            elif duplex.lower() == 'split':
                tx_freq = offset  # offset IS the TX freq in split mode
            elif duplex.lower() == 'off':
                tx_freq = freq  # RX only, but set TX=RX for simplex
            else:
                tx_freq = freq  # simplex

            # Tone handling
            tone_mode = row_lower.get('tone', '')
            tx_tone = ''
            rx_tone = ''

            if tone_mode in ('Tone', 'TSQL'):
                rtone = row_lower.get('rtonefreq', '')
                ctone = row_lower.get('ctonefreq', '')
                if tone_mode == 'Tone':
                    tx_tone = rtone
                elif tone_mode == 'TSQL':
                    tx_tone = ctone
                    rx_tone = ctone
            elif tone_mode == 'DTCS':
                dtcs = row_lower.get('dtcscode', '')
                if dtcs:
                    tx_tone = f"D{dtcs}"
                    rx_tone = f"D{dtcs}"

            # Comment as long name
            comment = row_lower.get('comment', '')
            long_name = comment if comment else name

            channels.append({
                'short_name': name[:8].upper(),
                'tx_freq': tx_freq,
                'rx_freq': rx_freq,
                'tx_tone': tx_tone,
                'rx_tone': rx_tone,
                'long_name': long_name[:16].upper(),
                'system_name': '',
            })

    return channels


def import_sdrtrunk_csv(filepath):
    """Import channels from SDRTrunk CSV export.

    SDRTrunk format varies, but typically:
    System,Channel,Frequency,Protocol,...

    Returns list of dicts compatible with make_conv_channel().
    """
    filepath = Path(filepath)
    channels = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower(): v.strip()
                         for k, v in row.items() if k}

            freq_str = (row_lower.get('frequency', '') or
                        row_lower.get('freq', ''))
            if not freq_str:
                continue
            try:
                freq = float(freq_str)
            except ValueError:
                continue
            if freq <= 0:
                continue

            ch_name = (row_lower.get('channel', '') or
                       row_lower.get('name', '') or
                       f"{freq:.4f}")
            system_name = row_lower.get('system', '')

            channels.append({
                'short_name': ch_name[:8].upper(),
                'tx_freq': freq,
                'rx_freq': freq,
                'tx_tone': '',
                'rx_tone': '',
                'long_name': ch_name[:16].upper(),
                'system_name': system_name,
            })

    return channels


def import_scanner_csv(filepath, fmt=None):
    """Import channels from a scanner CSV file.

    Auto-detects format if fmt is None or 'auto'.

    Args:
        filepath: path to the CSV file
        fmt: 'uniden', 'chirp', 'sdrtrunk', or 'auto'/None

    Returns:
        list of channel dicts compatible with make_conv_channel()

    Raises:
        ValueError: if format cannot be detected or file is invalid
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if fmt is None or fmt == 'auto':
        fmt = detect_scanner_format(filepath)

    if fmt == 'uniden':
        return import_uniden_csv(filepath)
    elif fmt == 'chirp':
        return import_chirp_csv(filepath)
    elif fmt == 'sdrtrunk':
        return import_sdrtrunk_csv(filepath)
    else:
        raise ValueError(
            f"Cannot detect scanner format for {filepath.name}. "
            "Use --format to specify: uniden, chirp, sdrtrunk")


# ─── DSD+ frequency list import ──────────────────────────────────────

def import_dsd_freqs(filepath):
    """Import frequencies from DSD+ frequency list (one freq per line in Hz).

    DSD+ and SDR# use simple text files with one frequency per line,
    specified in Hz (e.g., 851012500 for 851.0125 MHz).

    Lines starting with '#' are treated as comments. Blank lines are
    skipped. Values can optionally have a trailing comment after whitespace.

    Returns list of dicts with keys: short_name, tx_freq, rx_freq,
    tx_tone, rx_tone, long_name, system_name.
    Frequencies are converted from Hz to MHz.
    """
    filepath = Path(filepath)
    channels = []
    idx = 0

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Allow trailing comments or labels after whitespace
            parts = line.split()
            freq_str = parts[0]

            # Remove any commas (some formats use 851,012,500)
            freq_str = freq_str.replace(',', '')

            try:
                freq_hz = float(freq_str)
            except ValueError:
                continue
            if freq_hz <= 0:
                continue

            freq_mhz = freq_hz / 1e6
            name = f"F{idx + 1}"

            channels.append({
                'short_name': name[:8].upper(),
                'tx_freq': freq_mhz,
                'rx_freq': freq_mhz,
                'tx_tone': '',
                'rx_tone': '',
                'long_name': f"{freq_mhz:.4f}",
                'system_name': '',
            })
            idx += 1

    return channels


# ─── SDRTrunk talkgroup CSV import ────────────────────────────────────

def import_sdrtrunk_tgs(filepath):
    """Import talkgroups from SDRTrunk talkgroup CSV export.

    SDRTrunk talkgroup CSV format:
    Decimal,Hex,Alpha Tag,Mode,Description,Tag,Category

    Returns list of dicts with keys: group_id, short_name, long_name.
    """
    filepath = Path(filepath)
    talkgroups = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower(): v.strip()
                         for k, v in row.items() if k}

            # Get talkgroup ID (decimal)
            id_str = row_lower.get('decimal', '')
            if not id_str:
                continue
            try:
                group_id = int(id_str)
            except ValueError:
                continue
            if group_id <= 0:
                continue

            # Short name from Alpha Tag
            alpha = row_lower.get('alpha tag', '') or f"TG{group_id}"
            # Long name from Description, fall back to Alpha Tag
            desc = row_lower.get('description', '') or alpha

            talkgroups.append({
                'group_id': group_id,
                'short_name': alpha[:8].upper(),
                'long_name': desc[:16].upper(),
            })

    return talkgroups


# ─── RadioLog CSV import ─────────────────────────────────────────────

def import_radiolog(filepath):
    """Import from RadioLog CSV format (common logging tool).

    RadioLog CSV format (varies, but common columns):
    Date,Time,Frequency,Mode,Description,...

    Returns list of dicts compatible with make_conv_channel().
    """
    filepath = Path(filepath)
    channels = []
    seen_freqs = set()

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower(): v.strip()
                         for k, v in row.items() if k}

            freq_str = (row_lower.get('frequency', '') or
                        row_lower.get('freq', ''))
            if not freq_str:
                continue

            # Clean up frequency string
            freq_str = freq_str.replace(',', '').replace(' ', '')
            # Handle MHz vs Hz
            try:
                freq = float(freq_str)
            except ValueError:
                continue
            if freq <= 0:
                continue

            # If frequency looks like Hz (> 1000), convert to MHz
            if freq > 1000:
                freq = freq / 1e6

            # Skip duplicate frequencies
            freq_key = round(freq, 4)
            if freq_key in seen_freqs:
                continue
            seen_freqs.add(freq_key)

            desc = (row_lower.get('description', '') or
                    row_lower.get('name', '') or
                    row_lower.get('channel', '') or
                    f"{freq:.4f}")

            channels.append({
                'short_name': desc[:8].upper(),
                'tx_freq': freq,
                'rx_freq': freq,
                'tx_tone': '',
                'rx_tone': '',
                'long_name': desc[:16].upper(),
                'system_name': '',
            })

    return channels
