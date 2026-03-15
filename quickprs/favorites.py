"""Favorites / bookmarks and configuration presets.

Lets users bookmark frequently used systems, talkgroups, channels,
and templates for quick access. Also provides named configuration
presets for common radio option profiles.

Storage: ~/.quickprs/favorites.json
"""

import json
from pathlib import Path

from .option_maps import set_platform_option, SECTION_MAP
from .prs_parser import parse_prs
from .prs_writer import write_prs

FAVORITES_FILE = Path.home() / ".quickprs" / "favorites.json"

_VALID_CATEGORIES = ('systems', 'talkgroups', 'channels', 'templates')


def load_favorites():
    """Load favorites from disk.

    Returns:
        dict with keys: systems, talkgroups, channels, templates
    """
    if FAVORITES_FILE.exists():
        try:
            data = json.loads(FAVORITES_FILE.read_text(encoding='utf-8'))
            # Ensure all categories exist
            for cat in _VALID_CATEGORIES:
                if cat not in data:
                    data[cat] = []
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {cat: [] for cat in _VALID_CATEGORIES}


def save_favorites(favorites):
    """Save favorites to disk.

    Args:
        favorites: dict with category keys mapping to lists of items
    """
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_FILE.write_text(
        json.dumps(favorites, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )


def add_favorite(category, item):
    """Add an item to favorites.

    Args:
        category: one of 'systems', 'talkgroups', 'channels', 'templates'
        item: dict with item details (name required, plus optional metadata)

    Returns:
        True if added, False if already exists

    Raises:
        ValueError: if category is invalid or item has no name
    """
    if category not in _VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. "
            f"Valid: {', '.join(_VALID_CATEGORIES)}")
    if not isinstance(item, dict) or 'name' not in item:
        raise ValueError("Item must be a dict with at least a 'name' key")

    favorites = load_favorites()

    # Check for duplicates by name
    for existing in favorites[category]:
        if existing.get('name') == item['name']:
            return False

    favorites[category].append(item)
    save_favorites(favorites)
    return True


def remove_favorite(category, name):
    """Remove an item from favorites by name.

    Args:
        category: one of 'systems', 'talkgroups', 'channels', 'templates'
        name: name of the item to remove

    Returns:
        True if removed, False if not found

    Raises:
        ValueError: if category is invalid
    """
    if category not in _VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. "
            f"Valid: {', '.join(_VALID_CATEGORIES)}")

    favorites = load_favorites()
    original_len = len(favorites[category])
    favorites[category] = [
        item for item in favorites[category]
        if item.get('name') != name
    ]

    if len(favorites[category]) < original_len:
        save_favorites(favorites)
        return True
    return False


def list_favorites(category=None):
    """List all favorites or by category.

    Args:
        category: optional category filter

    Returns:
        dict of {category: [items]} if no category specified,
        list of items if category specified

    Raises:
        ValueError: if category is invalid
    """
    if category is not None and category not in _VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. "
            f"Valid: {', '.join(_VALID_CATEGORIES)}")

    favorites = load_favorites()

    if category:
        return favorites[category]
    return favorites


def clear_favorites(category=None):
    """Clear all favorites or a specific category.

    Args:
        category: optional category to clear (None = clear all)
    """
    if category is not None and category not in _VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. "
            f"Valid: {', '.join(_VALID_CATEGORIES)}")

    favorites = load_favorites()
    if category:
        favorites[category] = []
    else:
        favorites = {cat: [] for cat in _VALID_CATEGORIES}
    save_favorites(favorites)


# ─── Configuration Presets ────────────────────────────────────────────

PRESETS = {
    'field_ops': {
        'description': 'Field operations (GPS on, high power, long timeout)',
        'options': {
            'gps.gpsMode': 'ON',
            'gps.reportInterval': '30',
            'misc.topFpTimeout': '60',
        },
    },
    'covert': {
        'description': 'Covert operations (no GPS, no LED, short timeout)',
        'options': {
            'gps.gpsMode': 'OFF',
            'misc.ledEnabled': 'false',
            'misc.topFpTimeout': '5',
            'misc.topFpIntensity': '1',
        },
    },
    'training': {
        'description': 'Training mode (GPS on, low power)',
        'options': {
            'gps.gpsMode': 'ON',
        },
    },
    'gps_on': {
        'description': 'Enable GPS with 5-second reporting',
        'options': {
            'gps.gpsMode': 'ON',
            'gps.reportInterval': '5',
        },
    },
    'gps_off': {
        'description': 'Disable GPS completely',
        'options': {
            'gps.gpsMode': 'OFF',
        },
    },
    'quiet': {
        'description': 'Quiet mode (tones off, dim display)',
        'options': {
            'audio.tones': 'OFF',
            'misc.topFpIntensity': '1',
        },
    },
}


def list_presets():
    """List available presets.

    Returns:
        list of (name, description) tuples
    """
    return sorted(
        (name, preset['description'])
        for name, preset in PRESETS.items()
    )


def get_preset(name):
    """Get a preset by name.

    Args:
        name: preset name

    Returns:
        preset dict with 'description' and 'options' keys

    Raises:
        ValueError: if preset not found
    """
    key = name.lower()
    if key not in PRESETS:
        available = ', '.join(sorted(PRESETS.keys()))
        raise ValueError(
            f"Unknown preset '{name}'. Available: {available}")
    return PRESETS[key]


def apply_preset(filepath, preset_name, output=None):
    """Apply a named preset to a PRS file.

    Args:
        filepath: input PRS file path
        preset_name: name of the preset to apply
        output: output file path (default: overwrite input)

    Returns:
        list of (option_path, value, success) tuples

    Raises:
        ValueError: if preset not found
    """
    preset = get_preset(preset_name)
    prs = parse_prs(filepath)

    results = []
    for option_path, value in preset['options'].items():
        parts = option_path.split('.', 1)
        if len(parts) != 2:
            results.append((option_path, value, False))
            continue

        section, attr = parts
        xml_element = SECTION_MAP.get(section, section)

        try:
            set_platform_option(prs, xml_element, attr, value)
            results.append((option_path, value, True))
        except Exception:
            results.append((option_path, value, False))

    out_path = output or filepath
    write_prs(prs, out_path)

    return results
