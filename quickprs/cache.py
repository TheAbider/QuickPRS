"""Local JSON cache for parsed RadioReference data.

Stores parsed system data in ~/.quickprs/cache/ as JSON files.
Allows re-loading previously parsed systems without re-pasting.
No RadioReference-copyrighted data is redistributed — this is
local user data only.
"""

import dataclasses
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("quickprs")

from .radioreference import (RRSystem, RRTalkgroup, RRSite, RRSiteFreq,
                             ConvChannelData)


CACHE_DIR = Path.home() / '.quickprs' / 'cache'


def get_cache_dir():
    """Get (and create if needed) the cache directory."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def save_system(system, source="paste"):
    """Save an RRSystem to the local cache.

    Returns the cache file path.
    """
    cache_dir = get_cache_dir()

    safe_name = "".join(
        c for c in (system.name or str(system.sid))
        if c.isalnum() or c in ' -_')[:50].strip()
    if not safe_name:
        safe_name = "system"
    filename = f"{safe_name}.json"
    filepath = cache_dir / filename

    # Every field of the system and the records in it (talkgroups, sites
    # and their frequencies, conventional channels, categories)
    data = {'cached_at': datetime.now().isoformat(), 'source': source}
    data.update(dataclasses.asdict(system))

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    return filepath


def load_system(filepath):
    """Load an RRSystem from a cache JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    system = _record(RRSystem, data, sid=data.get('sid', 0))
    system.categories = {int(k): v
                         for k, v in data.get('categories', {}).items()}
    system.talkgroups = [_record(RRTalkgroup, tg)
                         for tg in data.get('talkgroups', [])]
    system.sites = [
        _record(RRSite, site, freqs=[_record(RRSiteFreq, sf)
                                     for sf in site.get('freqs', [])])
        for site in data.get('sites', [])
    ]
    system.conv_channels = [_record(ConvChannelData, ch)
                            for ch in data.get('conv_channels', [])]
    return system


def _record(cls, d, **fixed):
    """A data class from a cached dict: its own keys (others ignored,
    missing ones default) plus ``fixed``."""
    names = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: v for k, v in d.items()
              if k in names and not isinstance(v, (list, dict))}
    kwargs.update(fixed)
    return cls(**kwargs)


def list_cached_systems():
    """List all cached systems.

    Returns list of (filepath, name, cached_at, tg_count) tuples.
    """
    cache_dir = get_cache_dir()
    results = []

    for f in sorted(cache_dir.glob('*.json')):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            results.append((
                f,
                data.get('name', f.stem),
                data.get('cached_at', ''),
                len(data.get('talkgroups', [])),
            ))
        except Exception as e:
            logger.debug("Skipping corrupt cache file %s: %s", f.name, e)
            continue

    return results


def delete_cached_system(filepath):
    """Delete a cached system file."""
    Path(filepath).unlink(missing_ok=True)
