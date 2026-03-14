"""Config-file-based PRS builder.

Builds a complete PRS personality from a single INI-style configuration
file. This is the "define everything in one place" approach — one config
file specifies systems, channels, talkgroups, and radio options.

Config format uses configparser (stdlib) with the following sections:

    [personality]           — file metadata (name, author)
    [system.<name>]         — P25 trunked or conventional system
    [system.<name>.frequencies]  — trunk frequencies for P25 systems
    [system.<name>.talkgroups]   — talkgroups for P25 systems
    [channels.<name>]       — conventional channel groups (template or inline)
    [options]               — radio options (dot-separated XML paths)

Usage:
    prs = build_from_config("config.ini")
"""

import configparser
import logging
import re

logger = logging.getLogger("quickprs")


class ConfigError(Exception):
    """Raised when the config file has invalid or missing data."""
    pass


def build_from_config(config_path):
    """Build a complete PRS file from a config file.

    Parses the INI file, creates a blank PRS, then injects systems,
    channels, and options as specified.

    Args:
        config_path: path to the .ini config file

    Returns:
        PRSFile object

    Raises:
        ConfigError: if required fields are missing or invalid
        FileNotFoundError: if config_path doesn't exist
    """
    from pathlib import Path

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    cfg = configparser.ConfigParser(
        interpolation=None,     # no % interpolation
        comment_prefixes=('#', ';'),
        inline_comment_prefixes=('#', ';'),
    )
    # Preserve case in keys (configparser lowercases by default)
    cfg.optionxform = str
    cfg.read(str(path), encoding='utf-8')

    # Build the PRS
    prs = _build_personality(cfg)
    _inject_systems(cfg, prs)
    _inject_channels(cfg, prs)
    _apply_options(cfg, prs)

    return prs


def _build_personality(cfg):
    """Create the blank PRS with personality metadata."""
    from .builder import create_blank_prs

    name = "New Personality.PRS"
    author = ""

    if cfg.has_section('personality'):
        name = cfg.get('personality', 'name', fallback=name)
        author = cfg.get('personality', 'author', fallback=author)

    return create_blank_prs(filename=name, saved_by=author)


def _get_system_sections(cfg):
    """Find all system.* section groups.

    Returns dict mapping system name -> {
        'config': section dict,
        'frequencies': list of (tx, rx) tuples or None,
        'talkgroups': list of (id, short, long) tuples or None,
    }
    """
    systems = {}

    for section_name in cfg.sections():
        # Match system.<name> but NOT system.<name>.frequencies or .talkgroups
        m = re.match(r'^system\.([^.]+)$', section_name)
        if m:
            sys_name = m.group(1)
            systems[sys_name] = {
                'config': dict(cfg.items(section_name)),
                'frequencies': None,
                'talkgroups': None,
            }

    # Now attach sub-sections
    for section_name in cfg.sections():
        m = re.match(r'^system\.([^.]+)\.frequencies$', section_name)
        if m:
            sys_name = m.group(1)
            if sys_name not in systems:
                raise ConfigError(
                    f"[{section_name}] has no parent [system.{sys_name}]")
            systems[sys_name]['frequencies'] = _parse_freq_lines(
                cfg, section_name)

        m = re.match(r'^system\.([^.]+)\.talkgroups$', section_name)
        if m:
            sys_name = m.group(1)
            if sys_name not in systems:
                raise ConfigError(
                    f"[{section_name}] has no parent [system.{sys_name}]")
            systems[sys_name]['talkgroups'] = _parse_tg_lines(
                cfg, section_name)

    return systems


def _parse_freq_lines(cfg, section_name):
    """Parse frequency lines from a config section.

    Each key=value line in the section is treated as a frequency pair.
    Format: tx_freq,rx_freq (or just tx_freq for simplex).
    The key names are ignored (configparser requires unique keys, so
    we use the values only).

    Returns list of (tx_freq, rx_freq) tuples.
    """
    freqs = []
    for key, value in cfg.items(section_name):
        # The key might be a number or 'freq1', etc. Use the value.
        # But configparser stores "key = value", so if the user writes
        # "851.0125,806.0125" it becomes key="851.0125,806.0125" value=""
        # or the user can write "1 = 851.0125,806.0125"
        line = value if value else key
        parts = line.split(',')
        try:
            tx = float(parts[0].strip())
            rx = float(parts[1].strip()) if len(parts) > 1 else tx
            freqs.append((tx, rx))
        except (ValueError, IndexError) as e:
            raise ConfigError(
                f"[{section_name}]: invalid frequency line '{line}': {e}")
    return freqs


def _parse_tg_lines(cfg, section_name):
    """Parse talkgroup lines from a config section.

    Format: id,short_name,long_name
    Returns list of (id, short_name, long_name) tuples.
    """
    tgs = []
    for key, value in cfg.items(section_name):
        line = value if value else key
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            raise ConfigError(
                f"[{section_name}]: need at least id,short_name: '{line}'")
        try:
            gid = int(parts[0])
        except ValueError:
            raise ConfigError(
                f"[{section_name}]: invalid talkgroup id '{parts[0]}'")
        short = parts[1][:8]
        long_name = parts[2][:16] if len(parts) > 2 else short
        tgs.append((gid, short, long_name))
    return tgs


def _inject_systems(cfg, prs):
    """Inject all P25 trunked systems from config."""
    from .injector import (
        add_p25_trunked_system,
        make_trunk_set, make_group_set, make_iden_set,
    )
    from .record_types import P25TrkSystemConfig

    systems = _get_system_sections(cfg)

    for sys_name, sys_data in systems.items():
        config = sys_data['config']
        sys_type = config.get('type', 'p25_trunked').lower()

        if sys_type != 'p25_trunked':
            continue

        # Required fields
        short_name = config.get('short_name', sys_name)[:8]
        long_name = config.get('long_name', short_name)[:16]

        try:
            system_id = int(config.get('system_id', '0'))
        except ValueError:
            raise ConfigError(
                f"[system.{sys_name}]: invalid system_id")

        wacn = int(config.get('wacn', '0'))

        # Build trunk set from frequencies
        trunk_set = None
        if sys_data['frequencies']:
            trunk_set = make_trunk_set(short_name, sys_data['frequencies'])

        # Build group set from talkgroups
        group_set = None
        if sys_data['talkgroups']:
            group_set = make_group_set(
                short_name, sys_data['talkgroups'])

        # IDEN parameters — auto-detect from frequencies if not specified
        has_explicit_iden = 'iden_base' in config
        if has_explicit_iden:
            iden_base = int(config['iden_base'])
            iden_spacing = int(config.get('iden_spacing', '12500'))
            iden_set = make_iden_set(short_name[:5], [{
                'base_freq_hz': iden_base,
                'chan_spacing_hz': iden_spacing,
                'bandwidth_hz': iden_spacing // 2,
                'iden_type': 0,
            }])
        elif sys_data['frequencies']:
            from .injector import auto_iden_from_frequencies
            iden_set, descriptions = auto_iden_from_frequencies(
                sys_data['frequencies'], set_name=short_name[:5])
            if iden_set:
                # Extract base/spacing from first active element
                iden_base = 851012500
                iden_spacing = 12500
                for elem in iden_set.elements:
                    if elem.base_freq_hz > 0:
                        iden_base = elem.base_freq_hz
                        iden_spacing = elem.chan_spacing_hz
                        break
                logger.info("Auto-detected IDEN for %s: %s",
                            sys_name, "; ".join(descriptions))
            else:
                iden_base = 851012500
                iden_spacing = 12500
                iden_set = make_iden_set(short_name[:5], [{
                    'base_freq_hz': iden_base,
                    'chan_spacing_hz': iden_spacing,
                    'bandwidth_hz': iden_spacing // 2,
                    'iden_type': 0,
                }])
        else:
            iden_base = 851012500
            iden_spacing = 12500
            iden_set = make_iden_set(short_name[:5], [{
                'base_freq_hz': iden_base,
                'chan_spacing_hz': iden_spacing,
                'bandwidth_hz': iden_spacing // 2,
                'iden_type': 0,
            }])

        # Build system config
        p25_config = P25TrkSystemConfig(
            system_name=short_name,
            long_name=long_name,
            trunk_set_name=short_name if trunk_set else "",
            group_set_name=short_name if group_set else "",
            wan_name=short_name,
            system_id=system_id,
            wacn=wacn,
            iden_set_name=short_name[:5] if iden_set else "",
            wan_base_freq_hz=iden_base,
            wan_chan_spacing_hz=iden_spacing,
        )

        add_p25_trunked_system(prs, p25_config,
                               trunk_set=trunk_set,
                               group_set=group_set,
                               iden_set=iden_set)


def _get_channel_sections(cfg):
    """Find all channels.* sections.

    Returns dict mapping channel group name -> section dict.
    """
    channels = {}
    for section_name in cfg.sections():
        m = re.match(r'^channels\.([^.]+)$', section_name)
        if m:
            ch_name = m.group(1)
            channels[ch_name] = dict(cfg.items(section_name))
    return channels


def _parse_inline_channels(section_dict):
    """Parse inline channel definitions from a channels section.

    Lines that look like channel data (contain a frequency) are parsed.
    Format: short_name,tx_freq,rx_freq,tx_tone,rx_tone,long_name

    Returns list of channel dicts.
    """
    channels = []
    for key, value in section_dict.items():
        if key == 'template':
            continue
        # Try to parse as channel data
        line = value if value else key
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            continue
        try:
            # Minimum: short_name, tx_freq
            short = parts[0][:8]
            tx = float(parts[1])
            rx = float(parts[2]) if len(parts) > 2 and parts[2] else tx
            tx_tone = parts[3] if len(parts) > 3 else ''
            rx_tone = parts[4] if len(parts) > 4 else ''
            long_name = parts[5][:16] if len(parts) > 5 else short
            channels.append({
                'short_name': short,
                'tx_freq': tx,
                'rx_freq': rx,
                'tx_tone': tx_tone,
                'rx_tone': rx_tone,
                'long_name': long_name,
            })
        except (ValueError, IndexError):
            continue
    return channels


def _inject_channels(cfg, prs):
    """Inject all conventional channel groups from config."""
    from .injector import add_conv_system, make_conv_set
    from .record_types import ConvSystemConfig
    from .templates import get_template_channels

    channel_groups = _get_channel_sections(cfg)

    for group_name, section_dict in channel_groups.items():
        template = section_dict.get('template', '').strip()

        if template:
            # Use built-in template
            try:
                channels_data = get_template_channels(template)
            except ValueError as e:
                raise ConfigError(
                    f"[channels.{group_name}]: {e}")
        else:
            # Parse inline channels
            channels_data = _parse_inline_channels(section_dict)
            if not channels_data:
                raise ConfigError(
                    f"[channels.{group_name}]: no channels found "
                    f"(specify 'template' or inline channel lines)")

        short_name = group_name[:8]
        conv_set = make_conv_set(short_name, channels_data)
        config = ConvSystemConfig(
            system_name=short_name,
            long_name=short_name,
            conv_set_name=short_name,
        )
        add_conv_system(prs, config, conv_set=conv_set)


def _apply_options(cfg, prs):
    """Apply radio options from the [options] section.

    Options use dot-separated paths matching the platformConfig XML
    structure. For example:
        gps.gpsMode = ON
        bluetooth.btMode = OFF
        misc.password = 1234

    These map to XML attributes like:
        <platformConfig><gps gpsMode="ON" /><bluetooth btMode="OFF" />...
    """
    if not cfg.has_section('options'):
        return

    # Collect and validate options first
    options = list(cfg.items('options'))
    if not options:
        return

    for key, value in options:
        parts = key.split('.')
        if len(parts) < 2:
            raise ConfigError(
                f"[options]: key '{key}' must be dot-separated "
                f"(e.g., gps.gpsMode)")

    from .option_maps import (
        extract_platform_config, config_to_xml, write_platform_config,
    )

    # Get current platform config (may not exist in blank PRS)
    config = extract_platform_config(prs)
    if config is None:
        # Blank PRS has no platformConfig — nothing to modify
        logger.debug("No platformConfig found, skipping options")
        return

    # Apply each option
    for key, value in options:
        parts = key.split('.')

        # Navigate into the config dict
        target = config
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        target[parts[-1]] = value

    # Write back
    xml_str = config_to_xml(config)
    write_platform_config(prs, xml_str)
