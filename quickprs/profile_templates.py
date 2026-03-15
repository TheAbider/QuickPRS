"""Pre-built radio profile templates for common use cases.

Unlike channel templates (which add individual channels to an existing
personality), profile templates create complete personalities with
systems, channels, and options configured for a specific use case.

Available profiles:
    scanner_basic    - Basic scanner with NOAA and Marine channels
    public_safety    - Public safety interoperability setup
    ham_portable     - Amateur radio portable with calling freqs
    gmrs_family      - GMRS/FRS family radio setup
    fire_department  - Fire department base configuration
    law_enforcement  - Law enforcement base configuration
    ems              - Emergency Medical Services configuration
    search_rescue    - Search and Rescue configuration
"""

import logging

logger = logging.getLogger("quickprs")


PROFILE_TEMPLATES = {
    'scanner_basic': {
        'description': 'Basic scanner setup with common monitoring channels',
        'templates': ['noaa', 'marine'],
        'custom_channels': [],
        'options': {'gps.gpsMode': 'ON'},
    },
    'public_safety': {
        'description': 'Public safety interoperability setup',
        'templates': ['interop', 'public_safety'],
        'custom_channels': [],
        'options': {'gps.gpsMode': 'ON', 'gps.reportInterval': '30'},
    },
    'ham_portable': {
        'description': 'Amateur radio operator portable setup',
        'templates': ['murs'],
        'custom_channels': [
            {'short_name': '2M CALL', 'tx_freq': 146.520,
             'long_name': '2m FM Calling'},
            {'short_name': '70 CALL', 'tx_freq': 446.000,
             'long_name': '70cm FM Calling'},
            {'short_name': '2M APRS', 'tx_freq': 144.390,
             'long_name': 'APRS'},
        ],
        'options': {'gps.gpsMode': 'ON'},
    },
    'gmrs_family': {
        'description': 'GMRS/FRS family radio setup',
        'templates': ['gmrs', 'frs', 'noaa'],
        'custom_channels': [],
        'options': {},
    },
    'fire_department': {
        'description': 'Fire department base configuration',
        'templates': ['interop', 'noaa'],
        'custom_channels': [
            {'short_name': 'FG 1', 'tx_freq': 154.280,
             'long_name': 'Fireground 1'},
            {'short_name': 'FG 2', 'tx_freq': 154.265,
             'long_name': 'Fireground 2'},
            {'short_name': 'FG 3', 'tx_freq': 154.295,
             'long_name': 'Fireground 3'},
            {'short_name': 'FG 4', 'tx_freq': 154.310,
             'long_name': 'Fireground 4'},
            {'short_name': 'CMD', 'tx_freq': 154.340,
             'long_name': 'Command'},
            {'short_name': 'HAZCHEM', 'tx_freq': 155.175,
             'long_name': 'HazMat/Chemical'},
        ],
        'options': {'gps.gpsMode': 'ON', 'gps.reportInterval': '30'},
    },
    'law_enforcement': {
        'description': 'Law enforcement base configuration',
        'templates': ['interop'],
        'custom_channels': [
            {'short_name': 'CAR2CAR', 'tx_freq': 155.475,
             'long_name': 'Car to Car'},
            {'short_name': 'SURVEIL', 'tx_freq': 155.505,
             'long_name': 'Surveillance'},
            {'short_name': 'DET', 'tx_freq': 155.715,
             'long_name': 'Detectives'},
            {'short_name': 'TAC', 'tx_freq': 155.475,
             'long_name': 'Tactical'},
        ],
        'options': {'gps.gpsMode': 'ON'},
    },
    'ems': {
        'description': 'Emergency Medical Services configuration',
        'templates': ['interop', 'noaa'],
        'custom_channels': [
            {'short_name': 'MED 1', 'tx_freq': 155.340,
             'long_name': 'Med Channel 1'},
            {'short_name': 'MED 9', 'tx_freq': 155.400,
             'long_name': 'Med Channel 9'},
            {'short_name': 'CLEMARS', 'tx_freq': 155.205,
             'long_name': 'CLEMARS'},
        ],
        'options': {'gps.gpsMode': 'ON', 'gps.reportInterval': '15'},
    },
    'search_rescue': {
        'description': 'Search and Rescue configuration',
        'templates': ['interop', 'noaa', 'marine'],
        'custom_channels': [
            {'short_name': 'SAR 1', 'tx_freq': 155.160,
             'long_name': 'SAR Primary'},
            {'short_name': 'SAR CMD', 'tx_freq': 155.205,
             'long_name': 'SAR Command'},
        ],
        'options': {'gps.gpsMode': 'ON', 'gps.reportInterval': '60'},
    },
}


def list_profile_templates():
    """List available profile templates.

    Returns:
        list of (name, description) tuples, sorted by name.
    """
    return sorted(
        (name, info['description'])
        for name, info in PROFILE_TEMPLATES.items()
    )


def get_profile_template(name):
    """Get a profile template by name.

    Args:
        name: profile template name (case-insensitive)

    Returns:
        dict with keys: description, templates, custom_channels, options

    Raises:
        ValueError: if profile name is not recognized
    """
    key = name.lower()
    if key not in PROFILE_TEMPLATES:
        available = ", ".join(sorted(PROFILE_TEMPLATES.keys()))
        raise ValueError(
            f"Unknown profile '{name}'. Available: {available}")
    return PROFILE_TEMPLATES[key]


def build_from_profile(profile_name, filename=None):
    """Build a complete PRS from a profile template.

    Creates a blank PRS, then adds all channel templates and custom
    channels defined in the profile. Applies any specified radio options.

    Args:
        profile_name: name of the profile template
        filename: PRS filename (default: derived from profile name)

    Returns:
        PRSFile object

    Raises:
        ValueError: if profile name is not recognized
    """
    from .builder import create_blank_prs
    from .injector import add_conv_system, make_conv_set
    from .record_types import ConvSystemConfig
    from .templates import get_template_channels
    from .option_maps import (
        extract_platform_config, config_to_xml, write_platform_config,
    )

    profile = get_profile_template(profile_name)

    if filename is None:
        filename = f"{profile_name.upper()}.PRS"

    prs = create_blank_prs(filename=filename, saved_by="QuickPRS")

    # Add template channel sets
    for template_name in profile.get('templates', []):
        channels_data = get_template_channels(template_name)
        short_name = template_name.upper()[:8]
        conv_set = make_conv_set(short_name, channels_data)
        config = ConvSystemConfig(
            system_name=short_name,
            long_name=short_name,
            conv_set_name=short_name,
        )
        add_conv_system(prs, config, conv_set=conv_set)

    # Add custom channels as a single set
    custom_channels = profile.get('custom_channels', [])
    if custom_channels:
        conv_set = make_conv_set("CUSTOM", custom_channels)
        config = ConvSystemConfig(
            system_name="CUSTOM",
            long_name="CUSTOM",
            conv_set_name="CUSTOM",
        )
        add_conv_system(prs, config, conv_set=conv_set)

    # Apply radio options
    options = profile.get('options', {})
    if options:
        platform_config = extract_platform_config(prs)
        if platform_config is not None:
            for key, value in options.items():
                parts = key.split('.')
                target = platform_config
                for part in parts[:-1]:
                    if part not in target:
                        target[part] = {}
                    target = target[part]
                target[parts[-1]] = value

            xml_str = config_to_xml(platform_config)
            write_platform_config(prs, xml_str)

    return prs
