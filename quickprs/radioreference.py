"""RadioReference integration via SOAP API.

Uses the RadioReference.com Web Service (SOAP/XML) to fetch:
  - P25 trunked system details (WACN, SysID, type, location)
  - Talkgroup categories and talkgroups (ID, name, mode, encryption)
  - Site details with frequencies, NACs, RFSSs
  - Channel identifiers (base freq, spacing, bandwidth, FDMA/TDMA)

Requires:
  - Active RadioReference premium subscription ($30/6mo)
  - Developer app key (free, from radioreference.com/account/api)
  - Python zeep library (pip install zeep)

Reference:
  WSDL: https://api.radioreference.com/soap2/?wsdl&v=latest
  Docs: https://wiki.radioreference.com/index.php/RadioReference.com_Web_Service3.1
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict

logger = logging.getLogger("quickprs")

try:
    from zeep import Client
    HAS_ZEEP = True
except ImportError:
    HAS_ZEEP = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_SCRAPING = True
except ImportError:
    HAS_SCRAPING = False


# ─── Data classes ────────────────────────────────────────────────────

@dataclass
class RRTalkgroup:
    """A talkgroup from RadioReference."""
    dec_id: int             # decimal talkgroup ID
    hex_id: str = ""        # hex talkgroup ID
    alpha_tag: str = ""     # short name (e.g., "SEA PD D")
    description: str = ""   # long description
    mode: str = ""          # T=Trunked, D=Digital, TE=Encrypted, etc.
    encrypted: int = 0      # 0=clear, 1=mixed, 2=full encryption
    tag: str = ""           # service tag (Law Dispatch, Fire Tac, etc.)
    category: str = ""      # agency/jurisdiction category
    category_id: int = 0    # category ID for grouping


@dataclass
class RRSiteFreq:
    """A single frequency at a site."""
    freq: float             # MHz
    lcn: int = 0            # logical channel number
    use: str = ""           # "a" = alternate, "c" = control, "d" = data
    color_code: int = 0


@dataclass
class RRSite:
    """A site (tower) in a trunked system."""
    site_id: int
    site_number: str = ""   # e.g., "025"
    name: str = ""
    rfss: int = 0
    nac: str = ""           # hex NAC string
    lat: float = 0.0
    lon: float = 0.0
    range_miles: float = 0.0
    county: str = ""
    freqs: List[RRSiteFreq] = field(default_factory=list)


@dataclass
class RRSystem:
    """A complete trunked radio system from RadioReference."""
    sid: int                # RadioReference system ID (URL number)
    name: str = ""
    system_type: str = ""   # "Project 25 Phase II", etc.
    sysid: str = ""         # P25 System ID hex string (e.g., "3AB")
    wacn: str = ""          # WACN hex string (e.g., "BEE00")
    nac: str = ""           # default NAC
    voice: str = ""
    city: str = ""
    state: str = ""
    county: str = ""

    categories: Dict[int, str] = field(default_factory=dict)  # cat_id -> name
    talkgroups: List[RRTalkgroup] = field(default_factory=list)
    sites: List[RRSite] = field(default_factory=list)
    conv_channels: list = field(default_factory=list)  # ConvChannelData list


# ─── Service tags (RadioReference standard categories) ───────────────

SERVICE_TAGS = {
    1: "Law Dispatch",
    2: "Law Tac",
    3: "Law Talk",
    4: "Fire Dispatch",
    5: "Fire-Tac",
    6: "Fire-Talk",
    7: "EMS Dispatch",
    8: "EMS-Tac",
    9: "EMS-Talk",
    10: "Hospital",
    11: "Emergency Ops",
    12: "Military",
    13: "Media",
    14: "Schools",
    15: "Security",
    16: "Utilities",
    17: "Multi-Dispatch",
    18: "Multi-Tac",
    19: "Multi-Talk",
    20: "Interop",
    21: "Data",
    22: "Public Works",
    23: "Transportation",
    24: "Corrections",
    25: "Business",
    26: "Other",
    27: "Aircraft",
    28: "Railroad",
    29: "Federal",
    30: "Deprecated",
    33: "Ham",
}

# ─── Mode codes (RadioReference talkgroup mode designations) ──────────
# A=Analog, D=Digital (FDMA), T=TDMA
# Lowercase e=periodic encryption, uppercase E=full encryption

MODE_CODES = {
    "A":  ("Analog", False),
    "Ae": ("Analog", "partial"),
    "AE": ("Analog", "full"),
    "D":  ("Digital", False),
    "De": ("Digital", "partial"),
    "DE": ("Digital", "full"),
    "T":  ("TDMA", False),
    "Te": ("TDMA", "partial"),
    "TE": ("TDMA", "full"),
    "M":  ("Mixed", False),
    "E":  ("Encrypted", "full"),
}

# Group modes for filter UI
MODE_GROUPS = {
    "Analog": {"A", "Ae", "AE"},
    "Digital": {"D", "De", "DE"},
    "TDMA": {"T", "Te", "TE"},
}

ENCRYPTION_LEVELS = {
    "Clear": {False},
    "Partial": {"partial"},
    "Full": {"full"},
}


# ─── SOAP API Client ────────────────────────────────────────────────

WSDL_URL = "https://api.radioreference.com/soap2/?wsdl&v=15&s=rpc"


class RadioReferenceAPI:
    """Client for RadioReference SOAP API.

    Usage:
        api = RadioReferenceAPI(username, password, app_key)
        system = api.get_system(11628)  # PSERN
        # system.talkgroups, system.sites, system.categories populated
    """

    def __init__(self, username, password, app_key):
        if not HAS_ZEEP:
            raise ImportError("zeep is required: pip install zeep")

        try:
            self.client = Client(WSDL_URL)
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to RadioReference API — "
                f"check internet connection ({e})") from e

        auth_type = self.client.get_type('ns0:authInfo')
        self.auth = auth_type(
            username=username,
            password=password,
            appKey=app_key,
            version='15',
            style='rpc',
        )

    def get_system(self, sid):
        """Fetch complete system details, talkgroups, and sites.

        Args:
            sid: RadioReference system ID (number from URL)

        Returns:
            RRSystem with all data populated
        """
        system = self._get_details(sid)
        system.categories = self._get_categories(sid)
        system.talkgroups = self._get_talkgroups(sid, system.categories)
        system.sites = self._get_sites(sid)
        return system

    def _get_details(self, sid):
        """Fetch system-level details."""
        try:
            result = self.client.service.getTrsDetails(sid, self.auth)
        except Exception as e:
            err_str = str(e).lower()
            if 'auth' in err_str or 'login' in err_str or 'denied' in err_str:
                raise ConnectionError(
                    "Authentication failed — check username, password, "
                    "and API key") from e
            raise ConnectionError(
                f"API request failed for SID {sid}: {e}") from e

        sysid = ""
        wacn = ""
        if hasattr(result, 'sysid') and result.sysid:
            sysid = str(result.sysid).strip()
        if hasattr(result, 'wacn') and result.wacn:
            wacn = str(result.wacn).strip()

        return RRSystem(
            sid=sid,
            name=getattr(result, 'sName', ''),
            system_type=getattr(result, 'sTypeName', ''),
            sysid=sysid,
            wacn=wacn,
            voice=getattr(result, 'sVoice', ''),
            city=getattr(result, 'sCity', ''),
            state=getattr(result, 'sState', ''),
            county=getattr(result, 'sCounty', ''),
        )

    def _get_categories(self, sid):
        """Fetch talkgroup categories."""
        cats = {}
        try:
            result = self.client.service.getTrsTalkgroupCats(sid, self.auth)
            if result:
                for cat in result:
                    cat_id = getattr(cat, 'tgCid', 0)
                    cat_name = getattr(cat, 'tgCName', '')
                    if cat_id and cat_name:
                        cats[cat_id] = cat_name
        except Exception as e:
            logger.warning("Failed to fetch talkgroup categories for SID %s: %s", sid, e)
        return cats

    def _get_talkgroups(self, sid, categories):
        """Fetch all talkgroups for a system."""
        talkgroups = []
        try:
            # tgCid=0, tgTag=0, tgDec=0 means "all"
            result = self.client.service.getTrsTalkgroups(
                sid, 0, 0, 0, self.auth)
            if result:
                for tg in result:
                    dec_id = getattr(tg, 'tgDec', 0)
                    cat_id = getattr(tg, 'tgCid', 0)
                    tag_val = getattr(tg, 'tgTag', 0)

                    talkgroups.append(RRTalkgroup(
                        dec_id=int(dec_id) if dec_id else 0,
                        alpha_tag=getattr(tg, 'tgAlpha', ''),
                        description=getattr(tg, 'tgDescr', ''),
                        mode=getattr(tg, 'tgMode', ''),
                        encrypted=int(getattr(tg, 'enc', 0) or 0),
                        tag=SERVICE_TAGS.get(int(tag_val) if tag_val else 0, ''),
                        category=categories.get(cat_id, ''),
                        category_id=cat_id,
                    ))
        except Exception as e:
            logger.warning("Failed to fetch talkgroups for SID %s: %s", sid, e)
        return talkgroups

    def _get_sites(self, sid):
        """Fetch all sites with frequencies."""
        sites = []
        try:
            result = self.client.service.getTrsSites(sid, self.auth)
            if result:
                for site in result:
                    freqs = []
                    site_freqs = getattr(site, 'siteFreqs', None)
                    if site_freqs:
                        for sf in site_freqs:
                            freq_mhz = float(getattr(sf, 'freq', 0) or 0)
                            if freq_mhz > 0:
                                freqs.append(RRSiteFreq(
                                    freq=freq_mhz,
                                    lcn=int(getattr(sf, 'lcn', 0) or 0),
                                    use=getattr(sf, 'use', ''),
                                    color_code=int(
                                        getattr(sf, 'colorCode', 0) or 0),
                                ))

                    nac_val = getattr(site, 'nac', '')
                    sites.append(RRSite(
                        site_id=int(getattr(site, 'siteId', 0) or 0),
                        site_number=str(getattr(site, 'siteNumber', '')),
                        name=getattr(site, 'siteDescr', ''),
                        rfss=int(getattr(site, 'rfss', 0) or 0),
                        nac=str(nac_val) if nac_val else '',
                        lat=float(getattr(site, 'lat', 0) or 0),
                        lon=float(getattr(site, 'lon', 0) or 0),
                        range_miles=float(getattr(site, 'range', 0) or 0),
                        county=getattr(site, 'siteCt', ''),
                        freqs=freqs,
                    ))
        except Exception as e:
            logger.warning("Failed to fetch sites for SID %s: %s", sid, e)
        return sites


# ─── HTML Fallback Scraper ───────────────────────────────────────────
# Attempts to scrape system-level info (WACN, SysID, type) from
# the public HTML page. Talkgroups are AJAX-loaded and NOT available
# via simple GET scraping — use the SOAP API for those.

class RadioReferenceScraper:
    """Fallback scraper for basic system info (no premium required).

    Only fetches system-level metadata from static HTML.
    Talkgroups and detailed site data require the SOAP API.
    """

    BASE_URL = "https://www.radioreference.com"

    def __init__(self):
        if not HAS_SCRAPING:
            raise ImportError(
                "requests and beautifulsoup4 required: "
                "pip install requests beautifulsoup4")

    def get_system_info(self, sid):
        """Scrape basic system info from public HTML.

        Args:
            sid: System ID (number from URL)

        Returns:
            RRSystem with basic fields (name, type, sysid, wacn)
            but NO talkgroups or site frequencies
        """
        url = f"{self.BASE_URL}/db/sid/{sid}"
        try:
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 (KHTML, like Gecko) '
                               'Chrome/120.0.0.0 Safari/537.36'),
            })
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to RadioReference — check internet connection")
        except requests.exceptions.Timeout:
            raise ConnectionError(
                f"RadioReference request timed out for SID {sid}")
        except requests.exceptions.HTTPError as e:
            raise ConnectionError(
                f"RadioReference returned HTTP {e.response.status_code} for SID {sid}")

        soup = BeautifulSoup(resp.text, 'html.parser')
        system = RRSystem(sid=sid)

        # System name from page title or h1
        title = soup.find('h1')
        if title:
            system.name = title.get_text(strip=True)

        # Parse the system info table
        for row in soup.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)

                if 'system type' in label:
                    system.system_type = value
                elif 'system id' in label or 'sysid' in label:
                    system.sysid = value
                elif 'wacn' in label:
                    system.wacn = value
                elif 'system voice' in label:
                    system.voice = value
                elif 'nac' in label:
                    system.nac = value
                elif label == 'city':
                    system.city = value
                elif label == 'state':
                    system.state = value
                elif label == 'county':
                    system.county = value

        return system


# ─── URL parser ──────────────────────────────────────────────────────

def parse_rr_url(url):
    """Extract system ID from a RadioReference URL.

    Handles:
        https://www.radioreference.com/db/sid/11628
        https://radioreference.com/db/sid/11628/sites
        radioreference.com/db/sid/11628

    Returns:
        int system ID, or None if not parseable
    """
    match = re.search(r'/db/sid/(\d+)', url)
    if match:
        return int(match.group(1))
    # Try bare number
    try:
        return int(url.strip())
    except ValueError:
        return None


# ─── Talkgroup name generation ───────────────────────────────────────

def make_short_name(alpha_tag, max_len=8):
    """Generate an 8-char short name from a RadioReference alpha tag.

    Uses the PAWSOVERMAWS abbreviation patterns:
      - Strip common suffixes (Dispatch -> D, Tac -> T)
      - Keep first meaningful chars
      - Uppercase
    """
    name = alpha_tag.strip().upper()

    # Common abbreviations
    replacements = [
        ('DISPATCH', 'D'),
        ('TACTICAL', 'T'),
        ('OPERATIONS', 'OPS'),
        ('DEPARTMENT', 'DEPT'),
        ('SHERIFF', 'SO'),
        ('POLICE', 'PD'),
        ('COUNTY', 'CO'),
        ('DISTRICT', 'DIST'),
        ('EMERGENCY', 'EMRG'),
        ('MEDICAL', 'MED'),
        ('SERVICES', 'SVC'),
        ('COMMUNICATIONS', 'COM'),
        ('INTEROP', 'IOP'),
    ]

    for long, short in replacements:
        name = name.replace(long, short)

    # Collapse multiple spaces
    name = ' '.join(name.split())

    if len(name) <= max_len:
        return name

    # Try removing vowels from middle of words
    words = name.split()
    if len(words) > 1:
        shortened = []
        for w in words:
            if len(w) > 3:
                shortened.append(w[0] + ''.join(
                    c for c in w[1:] if c not in 'AEIOU'))
            else:
                shortened.append(w)
        name = ' '.join(shortened)

    return name[:max_len].rstrip()


def make_set_name(system_name, max_len=8):
    """Generate an 8-char set name from a system name.

    Extracts parenthesized acronyms when available:
      "California Radio Interoperable System (CRIS)" -> "CRIS"
      "Puget Sound Emergency Radio Network (PSERN)" -> "PSERN"

    Falls back to make_short_name() if no usable acronym found.
    """
    if not system_name:
        return ""

    # Check for parenthesized acronym at end of name
    match = re.search(r'\(([A-Z0-9][A-Z0-9 /-]{0,7})\)\s*$', system_name)
    if match:
        acronym = match.group(1).strip()
        if 0 < len(acronym) <= max_len:
            return acronym

    return make_short_name(system_name, max_len)


def make_long_name(description, alpha_tag, max_len=16):
    """Generate a 16-char long name from description or alpha tag.

    Always prefers description (truncated if needed) over alpha tag.
    This prevents short names from being repeated as long names.
    """
    if description:
        return description.upper()[:max_len]
    if alpha_tag:
        return alpha_tag.upper()[:max_len]
    return ""


# ─── P25 Frequency / IDEN functions (canonical source: iden_library.py) ──
# Re-exported here for backward compatibility. All callers that import
# these names from radioreference will continue to work unchanged.

from .iden_library import (                        # noqa: F401
    P25_BANDS,
    detect_p25_band,
    calculate_tx_freq,
    build_standard_iden_entries,
    _standard_800_iden,
    _standard_700_iden,
    _standard_900_iden,
    _derive_iden_from_freqs,
)


# ─── System builder ──────────────────────────────────────────────────

def build_injection_data(rr_system, selected_categories=None,
                         selected_tags=None):
    """Convert RadioReference data to QuickPRS injection-ready structures.

    Args:
        rr_system: RRSystem from API/scraper
        selected_categories: set of category IDs to include (None = all)
        selected_tags: set of service tag names to include (None = all)

    Returns:
        dict with keys:
            'system_name': str (8-char abbreviated)
            'wacn': str
            'sysid': str
            'talkgroups': list of (group_id, short_name, long_name) tuples
            'frequencies': list of (tx_freq, rx_freq) tuples
            'sites': list of site info dicts
    """
    # Filter talkgroups
    tgs = rr_system.talkgroups
    if selected_categories is not None:
        tgs = [tg for tg in tgs if tg.category_id in selected_categories]
    if selected_tags is not None:
        tgs = [tg for tg in tgs if tg.tag in selected_tags]

    # Build talkgroup tuples
    talkgroups = []
    for tg in tgs:
        if tg.dec_id <= 0 or tg.dec_id > 65535:
            continue
        short = make_short_name(tg.alpha_tag)
        long = make_long_name(tg.description, tg.alpha_tag)
        talkgroups.append((tg.dec_id, short, long))

    # Collect unique frequencies from all sites
    freq_set = set()
    for site in rr_system.sites:
        for sf in site.freqs:
            if sf.freq > 0:
                freq_set.add(round(sf.freq, 5))

    # Sort frequencies and apply TX offsets
    rx_freqs_sorted = sorted(freq_set)
    frequencies = [(calculate_tx_freq(f), f) for f in rx_freqs_sorted]

    # Build site info
    sites_info = []
    for site in rr_system.sites:
        sites_info.append({
            'name': site.name,
            'site_number': site.site_number,
            'rfss': site.rfss,
            'nac': site.nac,
            'freqs': [(sf.freq, sf.use) for sf in site.freqs],
        })

    # Generate IDEN table entries from frequencies
    iden_entries = build_standard_iden_entries(
        rx_freqs_sorted, rr_system.system_type)

    return {
        'system_name': make_set_name(rr_system.name),
        'full_name': rr_system.name,
        'wacn': rr_system.wacn,
        'sysid': rr_system.sysid,
        'system_type': rr_system.system_type,
        'talkgroups': talkgroups,
        'frequencies': frequencies,
        'sites': sites_info,
        'iden_entries': iden_entries,
    }


# ─── Enhanced CC builder ─────────────────────────────────────────────

def build_ecc_from_sites(sites, sys_id, system_type="",
                         base_freq_hz=0, spacing_hz=0,
                         max_entries=30):
    """Build Enhanced CC entries from selected site control channels.

    For each site, extracts control channel frequencies (use='c') and
    converts them to P25 channel references using the WAN band plan.

    Args:
        sites: list of RRSite objects
        sys_id: P25 System ID (integer)
        system_type: e.g. "Project 25 Phase II" for TDMA detection
        base_freq_hz: WAN base frequency; 0 = auto-detect
        spacing_hz: WAN channel spacing; 0 = auto-detect
        max_entries: firmware limit (XG-100P = 30)

    Returns:
        list of (entry_type, system_id, channel_ref1, channel_ref2) tuples
    """
    from .record_types import detect_wan_config

    # Collect control channel frequencies from selected sites
    cc_freqs = []
    for site in sites:
        site_ccs = [sf.freq for sf in site.freqs if sf.use == "c"]
        if not site_ccs:
            # If no freqs marked as control, use first freq from site
            if site.freqs:
                site_ccs = [site.freqs[0].freq]
        cc_freqs.extend(site_ccs)

    if not cc_freqs:
        return []

    # Deduplicate (same control channel at multiple sites)
    seen = set()
    unique_freqs = []
    for f in cc_freqs:
        key = round(f, 5)
        if key not in seen:
            seen.add(key)
            unique_freqs.append(f)

    # Auto-detect WAN config if not provided
    if not base_freq_hz or not spacing_hz:
        spacing_hz, base_freq_hz = detect_wan_config(
            unique_freqs, system_type)

    is_tdma = "Phase II" in system_type if system_type else False
    entry_type = 4 if is_tdma else 3

    entries = []
    for freq_mhz in unique_freqs:
        freq_hz = int(round(freq_mhz * 1_000_000))
        ch_num = round((freq_hz - base_freq_hz) / spacing_hz)
        if ch_num < 0:
            continue
        # For FDMA: ch1 = ch2 = channel_ref
        # For TDMA: ch1 = ch2 (simplified — exact TDMA encoding TBD)
        entries.append((entry_type, sys_id, ch_num, ch_num))

    # Cap at firmware limit
    return entries[:max_entries]


# ─── Full-page paste parser ───────────────────────────────────────────
# Parses talkgroup, frequency, and system data from a full
# RadioReference page dump (Ctrl+A, Ctrl+C in the browser).

def parse_full_page(text):
    """Parse a full RadioReference page paste into an RRSystem.

    Extracts system metadata, all talkgroups (across multiple category
    sections), and all site frequencies from a full page copy-paste.

    Args:
        text: full page text from Ctrl+A, Ctrl+C on a RadioReference
              trunked system page

    Returns:
        RRSystem with name, sysid, wacn, talkgroups, sites populated
    """
    system = RRSystem(sid=0)
    lines = text.strip().splitlines()

    # Extract system metadata
    for line in lines:
        line_s = line.strip()

        # System Name
        if line_s.startswith('System Name:'):
            system.name = line_s.split(':', 1)[1].strip()
        # System Type
        elif line_s.startswith('System Type:'):
            system.system_type = line_s.split(':', 1)[1].strip()
        # System ID line: "System ID:    Sysid: 9D2 WACN: BEE00"
        elif line_s.startswith('System ID:'):
            rest = line_s.split(':', 1)[1]
            sid_match = re.search(r'Sysid:\s*(\S+)', rest, re.I)
            wacn_match = re.search(r'WACN:\s*(\S+)', rest, re.I)
            if sid_match:
                system.sysid = sid_match.group(1)
            if wacn_match:
                system.wacn = wacn_match.group(1)
        elif line_s.startswith('Location:'):
            system.city = line_s.split(':', 1)[1].strip()
        elif line_s.startswith('County:'):
            system.county = line_s.split(':', 1)[1].strip()
        elif line_s.startswith('System Voice:'):
            system.voice = line_s.split(':', 1)[1].strip()
        elif line_s.startswith('NAC:'):
            system.nac = line_s.split(':', 1)[1].strip()

    # Extract talkgroups
    system.talkgroups = parse_pasted_talkgroups(text)

    # Try parsing individual sites first (table with RFSS/Site/Name/County)
    system.sites = parse_pasted_sites(text)

    # Fallback: extract flat frequency list if no site table found
    if not system.sites:
        freqs = parse_pasted_frequencies(text)
        if freqs:
            system.sites = [RRSite(
                site_id=0, name="All Sites",
                freqs=[RRSiteFreq(freq=f) for f, _ in freqs])]

    # Also try parsing conventional channels (works alongside trunked data)
    system.conv_channels = parse_pasted_conv_channels(text)

    return system


def parse_pasted_sites(text):
    """Parse individual sites from a RadioReference page paste.

    Handles the sites table format:
        RFSS    Site    Name    County    Freqs
        1 (1)    001 (1)    Pine Hill    El Dorado    769.40625c    770.65625c ...

    Returns list of RRSite objects with county and frequencies.
    """
    sites = []
    lines = text.strip().splitlines()
    in_site_section = False
    site_id_counter = 1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        # Detect sites header line
        if ('rfss' in lower and 'site' in lower and
                ('name' in lower or 'county' in lower or 'freq' in lower)):
            in_site_section = True
            continue

        # Talkgroups section starts — stop parsing sites
        if in_site_section and ('dec' in lower and 'hex' in lower):
            in_site_section = False
            continue

        if not in_site_section:
            continue

        # Try to parse a site line
        # Format: "1 (1)    001 (1)    Pine Hill    El Dorado    769.40625c ..."
        # Split on 2+ spaces or tabs
        if '\t' in stripped:
            parts = [p.strip() for p in stripped.split('\t') if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r'\s{2,}', stripped)
                     if p.strip()]

        if len(parts) < 3:
            continue

        # First part should be RFSS like "1 (1)" or just "1"
        rfss_match = re.match(r'^(\d+)\s*(?:\([0-9A-Fa-f]+\))?$', parts[0])
        if not rfss_match:
            # Might be end of sites section
            if not any(c.isdigit() and '.' in p
                       for p in parts for c in p):
                in_site_section = False
            continue

        rfss = int(rfss_match.group(1))

        # Second part: site number "001 (1)" or "001"
        site_match = re.match(
            r'^(\d+)\s*(?:\([0-9A-Fa-f]+\))?$', parts[1])
        if not site_match:
            continue
        site_number = site_match.group(1)

        # Remaining parts: name, county, then frequencies
        # Find where frequencies start (a part that looks like a freq)
        freq_start_idx = None
        for i in range(2, len(parts)):
            # Check if this part contains a frequency
            if re.match(r'^\d{2,4}\.\d{2,6}c?$', parts[i]):
                freq_start_idx = i
                break

        # Separate text parts (name, county, maybe NAC) from freq parts
        text_parts = []
        freq_parts = []
        nac = ""
        if freq_start_idx is None:
            text_parts = parts[2:]
            freq_parts = []
        else:
            text_parts = parts[2:freq_start_idx]
            freq_parts = parts[freq_start_idx:]

        # Check for NAC in text_parts: a 1-3 char hex string (e.g., "3AB")
        # P25 NACs are 12-bit (0x000-0xFFF), so 1-3 hex digits.
        # NAC appears after county, before frequencies.
        # Require at least one hex letter to avoid matching pure numbers
        # or short county names.
        if (len(text_parts) >= 3 and
                re.match(r'^[0-9A-Fa-f]{1,3}$', text_parts[-1]) and
                not re.match(r'^\d+$', text_parts[-1])):
            # Last text part is hex NAC (not pure decimal)
            nac = text_parts[-1].upper()
            text_parts = text_parts[:-1]

        if len(text_parts) == 0:
            name = ""
            county = ""
        elif len(text_parts) == 1:
            name = text_parts[0]
            county = ""
        else:
            # Last text part is county, rest is name
            county = text_parts[-1]
            name = " ".join(text_parts[:-1])

        # Parse frequency values
        site_freqs = []
        for f_str in freq_parts:
            f_clean = f_str.rstrip('c')
            use = "c" if f_str.endswith('c') else ""
            try:
                freq_val = float(f_clean)
                if 25.0 < freq_val < 1300.0:
                    site_freqs.append(RRSiteFreq(
                        freq=round(freq_val, 5), use=use))
            except ValueError:
                continue

        # Also check if name has embedded frequencies
        # (happens when parsing isn't perfect)
        if not site_freqs and name:
            for match in re.finditer(r'(\d{2,4}\.\d{2,6})c?', name):
                freq_val = round(float(match.group(1)), 5)
                if 25.0 < freq_val < 1300.0:
                    use = "c" if match.group(0).endswith('c') else ""
                    site_freqs.append(RRSiteFreq(freq=freq_val, use=use))

        sites.append(RRSite(
            site_id=site_id_counter,
            site_number=site_number,
            name=name.strip(" -"),
            rfss=rfss,
            nac=nac,
            county=county,
            freqs=site_freqs,
        ))
        site_id_counter += 1

    return sites


def parse_pasted_talkgroups(text):
    """Parse talkgroups from text pasted from RadioReference.

    Handles full page pastes with multiple category sections, each with
    its own header line:
        Mutual Aid
        DEC     HEX     Mode     Alpha Tag    Description    Tag
        50001    c351    T    LAW1CA    Law 1 - Statewide    Interop
        ...
        California Highway Patrol - Southern Division
        DEC     HEX     Mode     Alpha Tag    Description    Tag
        800    320    TE    SO BLK    Black - Central Los Angeles    Law Dispatch

    Also handles tab-separated values and simpler formats.

    Returns:
        list of RRTalkgroup objects
    """
    talkgroups = []
    lines = text.strip().splitlines()

    current_category = ""
    col_map = None
    in_tg_section = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        # Detect talkgroup header lines (can appear multiple times)
        if ('dec' in lower and
                ('alpha' in lower or 'tag' in lower or 'hex' in lower)):
            col_map = _detect_columns(stripped)
            in_tg_section = True
            continue

        # If we're in a talkgroup section, try to parse data lines
        if in_tg_section:
            tg = _parse_tg_line(stripped, col_map)
            if tg:
                if current_category and not tg.category:
                    tg.category = current_category
                talkgroups.append(tg)
                continue

            # A non-talkgroup line in a TG section could be a new
            # category name or end of section
            # Check if it's a category name (text line before next header)
            next_is_header = False
            for j in range(i + 1, min(i + 3, len(lines))):
                nl = lines[j].strip().lower()
                if 'dec' in nl and 'hex' in nl:
                    next_is_header = True
                    break
            if next_is_header:
                current_category = stripped.rstrip(' \u00a0')
                in_tg_section = False
                continue

            # Check if this line is a category name at the end
            # (no more TG data follows immediately)
            if not stripped[0].isdigit():
                # Might be section end or category header
                # Look ahead for more TG data
                has_more_tgs = False
                for j in range(i + 1, min(i + 5, len(lines))):
                    nl = lines[j].strip()
                    if nl and nl[0].isdigit():
                        has_more_tgs = True
                        break
                    if 'dec' in nl.lower() and 'hex' in nl.lower():
                        has_more_tgs = True
                        break
                if not has_more_tgs:
                    in_tg_section = False
                # This might be a category line for next section
                if not has_more_tgs or next_is_header:
                    current_category = stripped.rstrip(' \u00a0')

        else:
            # Not in a TG section — check if this is a category name
            # (text line before a TG header)
            for j in range(i + 1, min(i + 3, len(lines))):
                nl = lines[j].strip().lower()
                if 'dec' in nl and 'hex' in nl:
                    current_category = stripped.rstrip(' \u00a0')
                    break

    # If we found nothing with header-based parsing, try headerless
    # fallback: parse any line starting with a number as a talkgroup
    if not talkgroups:
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0].isdigit():
                tg = _parse_tg_line(stripped, None)
                if tg:
                    talkgroups.append(tg)

    return talkgroups


def _detect_columns(header):
    """Detect column order from a header line.

    Returns dict with format type and ordered column list.
    """
    if '\t' in header:
        cols = [c.strip().lower() for c in header.split('\t')]
        return {'format': 'tsv', 'cols': cols}

    # Split header on 2+ spaces to get ordered column names
    parts = re.split(r'\s{2,}', header.strip())
    cols = []
    for part in parts:
        p = part.strip().lower()
        if 'dec' in p:
            cols.append('dec')
        elif 'hex' in p:
            cols.append('hex')
        elif 'mode' in p:
            cols.append('mode')
        elif 'alpha' in p:
            cols.append('alpha')
        elif 'description' in p or 'descr' in p:
            cols.append('description')
        elif p == 'tag' or 'service' in p:
            cols.append('tag')
        elif 'category' in p or 'cat' in p:
            cols.append('category')
        else:
            cols.append(p)

    return {'format': 'multisep', 'cols': cols}


def _parse_tg_line(line, col_map):
    """Parse a single talkgroup line.

    Returns RRTalkgroup or None.
    """
    cols = col_map.get('cols', []) if col_map else []

    # Split based on format
    if '\t' in line:
        parts = [p.strip() for p in line.split('\t')]
    else:
        parts = re.split(r'\s{2,}', line.strip())

    if not parts or len(parts) < 2:
        return None

    # If we have column names from a header, map by position
    if cols:
        return _parse_tg_with_cols(parts, cols)

    # Fallback: best-effort
    return _parse_tg_parts(parts)


def _parse_tg_with_cols(parts, cols):
    """Parse talkgroup data using known column order."""
    tg = RRTalkgroup(dec_id=0)

    for i, col in enumerate(cols):
        if i >= len(parts):
            break
        val = parts[i].strip()

        if 'dec' in col:
            try:
                tg.dec_id = int(val)
            except ValueError:
                return None
        elif 'hex' in col:
            tg.hex_id = val
        elif 'mode' in col:
            tg.mode = val
        elif 'alpha' in col:
            tg.alpha_tag = val
        elif 'description' in col or 'descr' in col:
            tg.description = val
        elif col == 'tag' or 'service' in col:
            tg.tag = val
        elif 'category' in col or 'cat' in col:
            tg.category = val

    if tg.dec_id <= 0:
        return None
    return tg


def _parse_tg_parts(parts):
    """Parse talkgroup from a list of string parts (best-effort).

    Expected formats:
        [dec, hex, mode, alpha_tag, description, tag, category]
        [dec, alpha_tag, description]
        [dec, alpha_tag]
    """
    if not parts:
        return None

    # First part should be decimal ID
    try:
        dec_id = int(parts[0])
    except ValueError:
        return None

    if dec_id <= 0:
        return None

    tg = RRTalkgroup(dec_id=dec_id)

    if len(parts) >= 7:
        # Full RR format: DEC HEX Mode Alpha Description Tag Category
        tg.hex_id = parts[1]
        tg.mode = parts[2]
        tg.alpha_tag = parts[3]
        tg.description = parts[4]
        tg.tag = parts[5]
        tg.category = parts[6]
    elif len(parts) >= 5:
        # Might be DEC HEX Mode Alpha Description
        if _looks_like_hex(parts[1]) and len(parts[2]) <= 3:
            tg.hex_id = parts[1]
            tg.mode = parts[2]
            tg.alpha_tag = parts[3]
            tg.description = parts[4] if len(parts) > 4 else ""
            tg.tag = parts[5] if len(parts) > 5 else ""
        else:
            tg.alpha_tag = parts[1]
            tg.description = parts[2]
            tg.tag = parts[3] if len(parts) > 3 else ""
    elif len(parts) >= 3:
        tg.alpha_tag = parts[1]
        tg.description = parts[2]
    elif len(parts) >= 2:
        tg.alpha_tag = parts[1]

    return tg


def _looks_like_hex(s):
    """Check if string looks like a hex value (e.g., '08FF')."""
    try:
        if len(s) <= 6:
            int(s, 16)
            return any(c in 'abcdefABCDEF' for c in s) or len(s) >= 3
    except ValueError:
        pass
    return False


def parse_pasted_frequencies(text):
    """Parse frequencies from text pasted from RadioReference.

    Handles the RadioReference sites table format with multiple
    frequencies per line (some with 'c' suffix for control channels):
        1 (1)    001 (1)    Pine Hill    El Dorado    769.40625c    770.65625c    773.30625c

    Also handles simple one-per-line formats:
        851.00625
        851.00625  c

    Returns:
        list of (tx_freq, rx_freq) tuples in MHz
    """
    freqs = []
    seen = set()

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Skip header lines
        lower = line.lower()
        if lower.startswith('rfss') or lower.startswith('frequency'):
            continue

        # Find ALL frequencies in the line (handles multiple per line)
        # Pattern matches: 769.40625, 769.40625c, 151.1975c
        for match in re.finditer(r'(\d{2,4}\.\d{2,6})c?', line):
            freq = round(float(match.group(1)), 5)
            if 25.0 < freq < 1300.0 and freq not in seen:
                seen.add(freq)
                freqs.append((freq, freq))

    return freqs


# ─── Conventional channel paste parser ──────────────────────────────
# Parses conventional (non-trunked) frequencies from RadioReference
# conventional frequency search results or manual lists.

@dataclass
class ConvChannelData:
    """Parsed conventional channel data from RadioReference."""
    freq: float             # MHz
    name: str = ""          # channel/licensee name
    tone: str = ""          # CTCSS/DCS tone string (e.g., "156.7", "D023")
    mode: str = ""          # FM, NFM, AM, P25, DMR, etc.
    description: str = ""   # description/notes
    tx_freq: float = 0.0    # TX freq (0 = same as freq / simplex)
    tx_tone: str = ""       # TX tone


def parse_pasted_conv_channels(text):
    """Parse conventional channels from pasted RadioReference data.

    Handles multiple formats:
    1. RadioReference conventional freq search results:
       Frequency    License    Type    Tone    Alpha Tag    Description    Mode    Tag
       155.76000    KQD949    BM    136.5 PL    LE D1    Law Dispatch    FMN    Law Dispatch

    2. Simple frequency lists:
       155.76000
       462.5625  250.3

    3. Tab-separated or multi-space-separated data

    Returns:
        list of ConvChannelData objects
    """
    channels = []
    lines = text.strip().splitlines()
    col_map = None
    seen_freqs = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        # Detect header line (conventional freq tables)
        if ('frequency' in lower and
                ('tone' in lower or 'alpha' in lower or
                 'license' in lower or 'mode' in lower)):
            col_map = _detect_conv_columns(stripped)
            continue

        # Skip non-data lines
        if lower.startswith('rfss') or lower.startswith('system'):
            continue

        # Try to parse as a conventional channel
        ch = _parse_conv_line(stripped, col_map)
        if ch and ch.freq not in seen_freqs:
            seen_freqs.add(ch.freq)
            channels.append(ch)

    return channels


def _detect_conv_columns(header):
    """Detect column positions from a conventional freq header line."""
    if '\t' in header:
        cols = [c.strip().lower() for c in header.split('\t')]
    else:
        cols = [c.strip().lower()
                for c in re.split(r'\s{2,}', header.strip())]

    mapped = []
    for col in cols:
        if 'freq' in col:
            mapped.append('freq')
        elif 'license' in col or 'callsign' in col:
            mapped.append('license')
        elif col == 'type':
            mapped.append('type')
        elif 'tone' in col:
            mapped.append('tone')
        elif 'alpha' in col:
            mapped.append('alpha')
        elif 'description' in col or 'descr' in col:
            mapped.append('description')
        elif 'mode' in col:
            mapped.append('mode')
        elif col == 'tag' or 'service' in col:
            mapped.append('tag')
        elif 'input' in col:
            mapped.append('input')
        else:
            mapped.append(col)

    return mapped


def _parse_conv_line(line, col_map):
    """Parse a single conventional channel line.

    Returns ConvChannelData or None.
    """
    if '\t' in line:
        parts = [p.strip() for p in line.split('\t')]
    else:
        parts = [p.strip() for p in re.split(r'\s{2,}', line)]

    if not parts:
        return None

    # If we have column mapping, use it
    if col_map and len(parts) >= 2:
        ch = ConvChannelData(freq=0.0)
        for j, col in enumerate(col_map):
            if j >= len(parts):
                break
            val = parts[j].strip()
            if col == 'freq':
                try:
                    ch.freq = round(float(val), 5)
                except ValueError:
                    return None
            elif col == 'alpha':
                ch.name = val
            elif col == 'description':
                ch.description = val
            elif col == 'tone':
                # Parse tone: "136.5 PL" -> "136.5", "D023 N" -> "D023"
                tone_match = re.match(
                    r'([\d.]+)\s*(?:PL)?|(D\d{3})\s*(?:N)?', val)
                if tone_match:
                    ch.tone = tone_match.group(1) or tone_match.group(2)
            elif col == 'mode':
                ch.mode = val
            elif col == 'input':
                try:
                    ch.tx_freq = round(float(val), 5)
                except ValueError:
                    pass

        if ch.freq <= 0 or ch.freq > 1300:
            return None
        return ch

    # Fallback: first part should be a frequency
    try:
        freq = round(float(parts[0]), 5)
    except ValueError:
        return None

    if freq <= 25 or freq > 1300:
        return None

    ch = ConvChannelData(freq=freq)

    # Try to extract tone from second part
    if len(parts) >= 2:
        tone_match = re.match(
            r'^([\d.]+)\s*(?:PL)?$|^(D\d{3})\s*(?:N)?$', parts[1])
        if tone_match:
            ch.tone = tone_match.group(1) or tone_match.group(2)
        else:
            ch.name = parts[1]

    if len(parts) >= 3:
        if not ch.name:
            ch.name = parts[2]
        else:
            ch.description = parts[2]

    return ch


def conv_channels_to_set_data(channels):
    """Convert ConvChannelData list to dicts for make_conv_set().

    Generates short_name (8-char) and long_name (16-char) from the channel
    data. If no name is available, generates from frequency.

    Args:
        channels: list of ConvChannelData objects

    Returns:
        list of dicts with keys: short_name, tx_freq, rx_freq, tx_tone,
        rx_tone, long_name
    """
    result = []
    for ch in channels:
        # Generate names from available data
        if ch.name:
            short = ch.name[:8].upper()
        else:
            # Format freq as name: "155.7600" or "462.562"
            short = f"{ch.freq:.4f}"[:8]

        if ch.description:
            long = ch.description[:16].upper()
        elif ch.name:
            long = ch.name[:16].upper()
        else:
            long = short

        # TX freq: use explicit tx_freq if set, else same as RX (simplex)
        tx_freq = ch.tx_freq if ch.tx_freq > 0 else ch.freq

        result.append({
            'short_name': short,
            'tx_freq': tx_freq,
            'rx_freq': ch.freq,
            'tx_tone': ch.tone,
            'rx_tone': ch.tone,  # same tone for TX and RX by default
            'long_name': long,
        })
    return result
