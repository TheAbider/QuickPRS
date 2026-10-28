"""Pre-built channel templates for common US radio services.

Provides ready-to-use conventional channel data for MURS, GMRS, FRS,
Marine VHF, NOAA Weather Radio, National Interoperability, and
Public Safety simplex frequencies. Each function returns a list of
dicts compatible with make_conv_set() / make_conv_channel().
"""

# Template registry — maps template name to its function
TEMPLATE_REGISTRY = {}


def _register(name):
    """Decorator to register a template function."""
    def decorator(func):
        TEMPLATE_REGISTRY[name] = func
        return func
    return decorator


def get_template_names():
    """Return sorted list of available template names."""
    return sorted(TEMPLATE_REGISTRY.keys())


def get_template_channels(name):
    """Return channel data for a named template.

    Args:
        name: template name (e.g., 'murs', 'gmrs', 'frs', 'marine', 'noaa')

    Returns:
        list of channel dicts with keys: short_name, tx_freq, long_name
        (and optionally rx_freq, tx_tone, rx_tone)

    Raises:
        ValueError: if template name is not recognized
    """
    key = name.lower()
    if key not in TEMPLATE_REGISTRY:
        available = ", ".join(get_template_names())
        raise ValueError(
            f"Unknown template '{name}'. Available: {available}")
    return TEMPLATE_REGISTRY[key]()


@_register('murs')
def get_murs_channels():
    """Return MURS (Multi-Use Radio Service) channel data.

    5 channels, license-free, 2W max. Channels 1-3 are 11.25 kHz
    bandwidth, channels 4-5 are 20 kHz bandwidth.
    FCC Part 95 Subpart J.
    """
    return [
        {'short_name': 'MURS 1', 'tx_freq': 151.820,
         'long_name': 'MURS Channel 1'},
        {'short_name': 'MURS 2', 'tx_freq': 151.880,
         'long_name': 'MURS Channel 2'},
        {'short_name': 'MURS 3', 'tx_freq': 151.940,
         'long_name': 'MURS Channel 3'},
        {'short_name': 'MURS 4', 'tx_freq': 154.570,
         'long_name': 'MURS Channel 4'},
        {'short_name': 'MURS 5', 'tx_freq': 154.600,
         'long_name': 'MURS Channel 5'},
    ]


@_register('gmrs')
def get_gmrs_channels():
    """Return GMRS (General Mobile Radio Service) channel data.

    22 channels per FCC Part 95 Subpart E.
    Channels 1-7: 462 MHz simplex (shared with FRS, 5W GMRS / 2W FRS)
    Channels 8-14: 467 MHz repeater inputs (0.5W)
    Channels 15-22: 462 MHz simplex (GMRS only, 50W)
    Repeater outputs for channels 15R-22R on 462 MHz.
    """
    channels = []

    # Channels 1-7: 462 MHz simplex (shared with FRS)
    ch1_7_freqs = [
        462.5625, 462.5875, 462.6125, 462.6375,
        462.6625, 462.6875, 462.7125,
    ]
    for i, freq in enumerate(ch1_7_freqs, 1):
        channels.append({
            'short_name': f'GMRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'GMRS Channel {i}',
        })

    # Channels 8-14: 467 MHz (FRS/GMRS interstitial, 0.5W)
    ch8_14_freqs = [
        467.5625, 467.5875, 467.6125, 467.6375,
        467.6625, 467.6875, 467.7125,
    ]
    for i, freq in enumerate(ch8_14_freqs, 8):
        channels.append({
            'short_name': f'GMRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'GMRS Channel {i}',
        })

    # Channels 15-22: 462 MHz (GMRS only, higher power)
    ch15_22_freqs = [
        462.5500, 462.5750, 462.6000, 462.6250,
        462.6500, 462.6750, 462.7000, 462.7250,
    ]
    for i, freq in enumerate(ch15_22_freqs, 15):
        channels.append({
            'short_name': f'GMRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'GMRS Channel {i}',
        })

    return channels


@_register('frs')
def get_frs_channels():
    """Return FRS (Family Radio Service) channel data.

    22 channels per FCC Part 95 Subpart B.
    Channels 1-7: 462 MHz (shared with GMRS, 2W)
    Channels 8-14: 467 MHz (shared with GMRS, 0.5W)
    Channels 15-22: 462 MHz (2W, shared with GMRS)
    All simplex, license-free.
    """
    channels = []

    # Channels 1-7: 462 MHz simplex
    ch1_7_freqs = [
        462.5625, 462.5875, 462.6125, 462.6375,
        462.6625, 462.6875, 462.7125,
    ]
    for i, freq in enumerate(ch1_7_freqs, 1):
        channels.append({
            'short_name': f'FRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'FRS Channel {i}',
        })

    # Channels 8-14: 467 MHz
    ch8_14_freqs = [
        467.5625, 467.5875, 467.6125, 467.6375,
        467.6625, 467.6875, 467.7125,
    ]
    for i, freq in enumerate(ch8_14_freqs, 8):
        channels.append({
            'short_name': f'FRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'FRS Channel {i}',
        })

    # Channels 15-22: 462 MHz
    ch15_22_freqs = [
        462.5500, 462.5750, 462.6000, 462.6250,
        462.6500, 462.6750, 462.7000, 462.7250,
    ]
    for i, freq in enumerate(ch15_22_freqs, 15):
        channels.append({
            'short_name': f'FRS {i:2d}',
            'tx_freq': freq,
            'long_name': f'FRS Channel {i}',
        })

    return channels


@_register('marine')
def get_marine_channels():
    """Return Marine VHF channel data.

    Common marine channels per ITU-R M.1084 / FCC Part 80.
    Includes calling/distress (16), secondary calling (9),
    and common recreational/commercial channels.
    Simplex channels use the same TX/RX frequency.
    Duplex channels have a 4.6 MHz offset (ship TX on low, coast RX on high).
    """
    return [
        # Distress, Safety, Calling
        {'short_name': 'MAR 16', 'tx_freq': 156.800,
         'long_name': 'Distress/Call'},
        {'short_name': 'MAR  9', 'tx_freq': 156.450,
         'long_name': 'Secondary Call'},
        # Bridge-to-bridge
        {'short_name': 'MAR 13', 'tx_freq': 156.650,
         'long_name': 'Bridge-Bridge'},
        {'short_name': 'MAR 67', 'tx_freq': 156.375,
         'long_name': 'Bridge-Bridge 2'},
        # Recreational/non-commercial
        {'short_name': 'MAR 68', 'tx_freq': 156.425,
         'long_name': 'Non-Commercial'},
        {'short_name': 'MAR 69', 'tx_freq': 156.475,
         'long_name': 'Non-Commercial'},
        {'short_name': 'MAR 71', 'tx_freq': 156.575,
         'long_name': 'Non-Commercial'},
        {'short_name': 'MAR 72', 'tx_freq': 156.625,
         'long_name': 'Non-Commercial'},
        {'short_name': 'MAR 78', 'tx_freq': 156.925,
         'long_name': 'Non-Commercial'},
        # Commercial / port operations
        {'short_name': 'MAR  6', 'tx_freq': 156.300,
         'long_name': 'Ship-Ship Safety'},
        {'short_name': 'MAR 10', 'tx_freq': 156.500,
         'long_name': 'Vessel Traffic'},
        {'short_name': 'MAR 12', 'tx_freq': 156.600,
         'long_name': 'Vessel Traffic'},
        {'short_name': 'MAR 14', 'tx_freq': 156.700,
         'long_name': 'Vessel Traffic'},
        {'short_name': 'MAR 70', 'tx_freq': 156.525,
         'long_name': 'DSC Calling'},
        # Coast Guard
        {'short_name': 'MAR 22', 'tx_freq': 157.100,
         'long_name': 'USCG Liaison'},
    ]


@_register('noaa')
@_register('weather')
def get_noaa_channels():
    """Return NOAA Weather Radio channels.

    7 frequencies used by NWS for continuous weather broadcasts.
    Receive-only (no transmit). All simplex.
    Also registered as 'weather' alias.
    """
    freqs = [162.400, 162.425, 162.450, 162.475,
             162.500, 162.525, 162.550]
    channels = []
    for i, freq in enumerate(freqs, 1):
        channels.append({
            'short_name': f'WX {i}',
            'tx_freq': freq,
            'long_name': f'NOAA Weather {i}',
            'tx': False,
        })
    return channels


@_register('interop')
def get_interop_channels():
    """Return the national public safety interoperability channels.

    Values as the NIFOG publishes them (checked against RadioReference's
    National Interoperability page; the current NIFOG from CISA wins any
    disagreement).  All use 156.7 Hz CTCSS and narrowband FM unless noted:

    - VHF, simplex: VCALL10 155.7525, VTAC11 151.1375, VTAC12 154.4525,
      VTAC13 158.7375, VTAC14 159.4725 MHz
    - UHF repeater pairs (radio transmits 5 MHz up) and their direct
      ("D") simplex channels: UCALL40 453.2125, UTAC41 453.4625,
      UTAC42 453.7125, UTAC43 453.8625 MHz
    - 800 MHz repeater pairs (radio transmits 45 MHz down; wide FM) and
      direct channels: 8CALL90 851.0125, 8TAC91-94 851.5125-853.0125 MHz
      (the rebanded frequencies; 866-868 MHz is the pre-rebanding plan)

    The 700 MHz channels (7CALL50, 7TAC51-56) are P25 digital (NAC 293),
    which an analog conventional set cannot carry; add them as a P25
    conventional set (P25_CONV_SET.csv import) instead.
    """
    def ch(name, rx, tx=None, long_name="", narrowband=True):
        return {'short_name': name, 'tx_freq': tx if tx else rx,
                'rx_freq': rx, 'long_name': long_name,
                'tx_tone': '156.7', 'rx_tone': '156.7',
                'narrowband': narrowband}

    channels = [
        ch('VCALL10', 155.7525, long_name='VHF Call'),
        ch('VTAC11', 151.1375, long_name='VHF Tactical 11'),
        ch('VTAC12', 154.4525, long_name='VHF Tactical 12'),
        ch('VTAC13', 158.7375, long_name='VHF Tactical 13'),
        ch('VTAC14', 159.4725, long_name='VHF Tactical 14'),
    ]
    for name, out, label in (('UCALL40', 453.2125, 'UHF Call'),
                             ('UTAC41', 453.4625, 'UHF Tactical 41'),
                             ('UTAC42', 453.7125, 'UHF Tactical 42'),
                             ('UTAC43', 453.8625, 'UHF Tactical 43')):
        channels.append(ch(name, out, tx=round(out + 5.0, 4),
                           long_name=f'{name} Repeater'))
        channels.append(ch(name + 'D', out, long_name=f'{name} Direct'))
    for name, out, label in (('8CALL90', 851.0125, '800 Call'),
                             ('8TAC91', 851.5125, '800 Tactical 91'),
                             ('8TAC92', 852.0125, '800 Tactical 92'),
                             ('8TAC93', 852.5125, '800 Tactical 93'),
                             ('8TAC94', 853.0125, '800 Tactical 94')):
        channels.append(ch(name, out, tx=round(out - 45.0, 4),
                           long_name=f'{name} Repeater',
                           narrowband=False))
        channels.append(ch(name + 'D', out, long_name=f'{name} Direct'))
    return channels


@_register('public_safety')
def get_public_safety_channels():
    """Return common public safety simplex frequencies.

    Standard VHF/UHF simplex frequencies used by fire, EMS,
    and law enforcement for on-scene operations. All simplex.
    """
    return [
        # VHF public safety
        {'short_name': 'PS VHF1', 'tx_freq': 155.3400,
         'long_name': 'PS Simplex 1'},
        {'short_name': 'PS VHF2', 'tx_freq': 155.3475,
         'long_name': 'PS Simplex 2'},
        {'short_name': 'PS VHF3', 'tx_freq': 155.3550,
         'long_name': 'PS Simplex 3'},
        {'short_name': 'PS VHF4', 'tx_freq': 155.3625,
         'long_name': 'PS Simplex 4'},
        {'short_name': 'FIRE VH', 'tx_freq': 154.2800,
         'long_name': 'Fire Simplex'},
        {'short_name': 'FIRE V2', 'tx_freq': 154.2650,
         'long_name': 'Fire Simplex 2'},
        {'short_name': 'EMS VHF', 'tx_freq': 155.3700,
         'long_name': 'EMS Simplex'},
        # UHF public safety
        {'short_name': 'PS UHF1', 'tx_freq': 453.0375,
         'long_name': 'PS UHF Simplex1'},
        {'short_name': 'PS UHF2', 'tx_freq': 453.0875,
         'long_name': 'PS UHF Simplex2'},
        {'short_name': 'PS UHF3', 'tx_freq': 453.1375,
         'long_name': 'PS UHF Simplex3'},
    ]
