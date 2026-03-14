"""Local JSON cache for parsed RadioReference data.

Stores parsed system data in ~/.quickprs/cache/ as JSON files.
Allows re-loading previously parsed systems without re-pasting.
No RadioReference-copyrighted data is redistributed — this is
local user data only.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("quickprs")

from .radioreference import RRSystem, RRTalkgroup, RRSite, RRSiteFreq


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

    data = {
        'cached_at': datetime.now().isoformat(),
        'source': source,
        'sid': system.sid,
        'name': system.name,
        'system_type': system.system_type,
        'sysid': system.sysid,
        'wacn': system.wacn,
        'nac': system.nac,
        'voice': system.voice,
        'city': system.city,
        'state': system.state,
        'county': system.county,
        'talkgroups': [
            {
                'dec_id': tg.dec_id,
                'hex_id': tg.hex_id,
                'alpha_tag': tg.alpha_tag,
                'description': tg.description,
                'mode': tg.mode,
                'encrypted': tg.encrypted,
                'tag': tg.tag,
                'category': tg.category,
                'category_id': tg.category_id,
            }
            for tg in system.talkgroups
        ],
        'sites': [
            {
                'site_id': site.site_id,
                'site_number': site.site_number,
                'name': site.name,
                'rfss': site.rfss,
                'nac': site.nac,
                'county': getattr(site, 'county', ''),
                'lat': getattr(site, 'lat', 0.0),
                'lon': getattr(site, 'lon', 0.0),
                'range_miles': getattr(site, 'range_miles', 0.0),
                'freqs': [
                    {'freq': sf.freq, 'lcn': sf.lcn, 'use': sf.use}
                    for sf in site.freqs
                ],
            }
            for site in system.sites
        ],
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    return filepath


def load_system(filepath):
    """Load an RRSystem from a cache JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    system = RRSystem(
        sid=data.get('sid', 0),
        name=data.get('name', ''),
        system_type=data.get('system_type', ''),
        sysid=data.get('sysid', ''),
        wacn=data.get('wacn', ''),
        nac=data.get('nac', ''),
        voice=data.get('voice', ''),
        city=data.get('city', ''),
        state=data.get('state', ''),
        county=data.get('county', ''),
    )

    system.talkgroups = [
        RRTalkgroup(
            dec_id=tg['dec_id'],
            hex_id=tg.get('hex_id', ''),
            alpha_tag=tg.get('alpha_tag', ''),
            description=tg.get('description', ''),
            mode=tg.get('mode', ''),
            encrypted=tg.get('encrypted', 0),
            tag=tg.get('tag', ''),
            category=tg.get('category', ''),
            category_id=tg.get('category_id', 0),
        )
        for tg in data.get('talkgroups', [])
    ]

    system.sites = [
        RRSite(
            site_id=site['site_id'],
            site_number=site.get('site_number', ''),
            name=site.get('name', ''),
            rfss=site.get('rfss', 0),
            nac=site.get('nac', ''),
            county=site.get('county', ''),
            lat=float(site.get('lat', 0.0)),
            lon=float(site.get('lon', 0.0)),
            range_miles=float(site.get('range_miles', 0.0)),
            freqs=[
                RRSiteFreq(
                    freq=sf['freq'],
                    lcn=sf.get('lcn', 0),
                    use=sf.get('use', ''),
                )
                for sf in site.get('freqs', [])
            ],
        )
        for site in data.get('sites', [])
    ]

    return system


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
