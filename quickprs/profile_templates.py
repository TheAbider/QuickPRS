"""Pre-built radio profile templates for common use cases.

Unlike channel templates (which add individual channels to an existing
personality), profile templates create complete personalities with
systems, channels, and options configured for a specific use case.

Available profiles:
    scanner_basic  - Basic scanner with NOAA and Marine channels
    public_safety  - Public safety interoperability setup
    ham_portable   - Amateur radio portable with calling freqs
    gmrs_family    - GMRS/FRS family radio setup
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
