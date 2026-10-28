"""Built-in list of common US P25 trunked radio systems.

A searchable starting point (name, area, band, phase) for setting up a
system.  The System IDs and WACNs here are NOT verified: they do not come
from any authoritative source (the FCC's licensing database does not
publish P25 System IDs or WACNs) and several are known to be wrong.
Only entries marked ``verified`` were checked, against a personality
saved by RPM for a radio on that system.  Confirm every ID on
RadioReference (or with the system's administrator) before a radio is
programmed with it: a wrong System ID or WACN keeps the radio off the
system.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class P25System:
    """A known P25 trunked radio system."""
    name: str               # short identifier (e.g., "PSERN")
    long_name: str          # full system name
    location: str           # city/region, state
    state: str              # 2-letter state code
    system_id: int          # P25 System ID (decimal)
    wacn: int               # Wide Area Communication Network ID
    band: str               # frequency band ("700", "800", "700/800", "900")
    system_type: str        # "Phase I" or "Phase II"
    description: str = ""   # brief description of coverage/purpose
    verified: bool = False  # IDs checked against an RPM-saved personality


def unverified_warning(system):
    """Warning text for an entry whose IDs nobody checked, else ''."""
    if system.verified:
        return ""
    return (f"System ID {system.system_id} and WACN {system.wacn:#x} for "
            f"{system.name} are unverified; confirm both on RadioReference "
            f"before programming a radio.")


# ─── System Database ─────────────────────────────────────────────────
# All data from public sources: FCC ULS database, NTIA records,
# RadioReference wiki (public/non-premium content).

SYSTEMS: List[P25System] = [
    # ─── Washington State ────────────────────────────────────────────
    P25System(
        name="PSERN",
        long_name="Puget Sound Emergency Radio Network",
        location="Seattle Metro, WA",
        state="WA",
        # 939 (0x3AB) / WACN BEE00 as RPM saved them for a radio on PSERN
        system_id=939,
        wacn=781824,
        verified=True,
        band="800",
        system_type="Phase II",
        description="King County regional public safety, replaces KCERS",
    ),
    P25System(
        name="KCERS",
        long_name="King County Emergency Radio System",
        location="King County, WA",
        state="WA",
        system_id=940,
        wacn=781824,
        band="800",
        system_type="Phase I",
        description="Legacy King County system, transitioning to PSERN",
    ),
    P25System(
        name="WSP",
        long_name="Washington State Patrol",
        location="Statewide, WA",
        state="WA",
        system_id=830,
        wacn=781824,
        band="800",
        system_type="Phase II",
        description="Washington State Patrol statewide system",
    ),

    # ─── California ──────────────────────────────────────────────────
    P25System(
        name="LAPD",
        long_name="Los Angeles Police Department",
        location="Los Angeles, CA",
        state="CA",
        system_id=773,
        wacn=781312,
        band="700/800",
        system_type="Phase II",
        description="City of Los Angeles public safety",
    ),
    P25System(
        name="CHP",
        long_name="California Highway Patrol",
        location="Statewide, CA",
        state="CA",
        system_id=11,
        wacn=781312,
        band="800",
        system_type="Phase I",
        description="CHP statewide trunked system",
    ),
    P25System(
        name="SDRCS",
        long_name="San Diego Regional Communications System",
        location="San Diego, CA",
        state="CA",
        system_id=346,
        wacn=781312,
        band="800",
        system_type="Phase II",
        description="San Diego County regional public safety",
    ),
    P25System(
        name="EBRCSA",
        long_name="East Bay Regional Communications System Authority",
        location="East Bay, CA",
        state="CA",
        system_id=109,
        wacn=781312,
        band="800",
        system_type="Phase II",
        description="Alameda/Contra Costa County public safety",
    ),

    # ─── New York ────────────────────────────────────────────────────
    P25System(
        name="NYPD",
        long_name="New York Police Department",
        location="New York City, NY",
        state="NY",
        system_id=679,
        wacn=781056,
        band="800",
        system_type="Phase I",
        description="NYPD citywide trunked radio system",
    ),
    P25System(
        name="NYSP",
        long_name="New York State Police",
        location="Statewide, NY",
        state="NY",
        system_id=168,
        wacn=781056,
        band="800",
        system_type="Phase I",
        description="New York State Police statewide system",
    ),

    # ─── Texas ───────────────────────────────────────────────────────
    P25System(
        name="HCTRA",
        long_name="Harris County TRUNKED Radio Authority",
        location="Houston, TX",
        state="TX",
        system_id=484,
        wacn=781568,
        band="800",
        system_type="Phase II",
        description="Harris County / Houston metro public safety",
    ),
    P25System(
        name="DFW",
        long_name="Dallas/Fort Worth Metroplex",
        location="Dallas/Fort Worth, TX",
        state="TX",
        system_id=14,
        wacn=781568,
        band="800",
        system_type="Phase II",
        description="North Central Texas regional system",
    ),
    P25System(
        name="SARRCS",
        long_name="San Antonio Regional Radio Communications System",
        location="San Antonio, TX",
        state="TX",
        system_id=583,
        wacn=781568,
        band="800",
        system_type="Phase II",
        description="San Antonio and Bexar County public safety",
    ),

    # ─── Illinois ────────────────────────────────────────────────────
    P25System(
        name="STARCOM",
        long_name="STARCOM21",
        location="Statewide, IL",
        state="IL",
        system_id=583,
        wacn=781088,
        band="700/800",
        system_type="Phase II",
        description="Illinois statewide public safety radio system",
    ),
    P25System(
        name="CPD",
        long_name="Chicago Police Department",
        location="Chicago, IL",
        state="IL",
        system_id=200,
        wacn=781088,
        band="800",
        system_type="Phase I",
        description="City of Chicago police radio system",
    ),

    # ─── Arizona ─────────────────────────────────────────────────────
    P25System(
        name="TOPAZ",
        long_name="TOPAZ Regional Wireless Cooperative",
        location="Phoenix Metro, AZ",
        state="AZ",
        system_id=773,
        wacn=781280,
        band="800",
        system_type="Phase II",
        description="Phoenix metro area regional public safety",
    ),

    # ─── Florida ─────────────────────────────────────────────────────
    P25System(
        name="SLERS",
        long_name="State Law Enforcement Radio System",
        location="Statewide, FL",
        state="FL",
        system_id=40,
        wacn=781504,
        band="800",
        system_type="Phase II",
        description="Florida statewide law enforcement system",
    ),
    P25System(
        name="MDPD",
        long_name="Miami-Dade Police Department",
        location="Miami-Dade, FL",
        state="FL",
        system_id=109,
        wacn=781504,
        band="800",
        system_type="Phase II",
        description="Miami-Dade County public safety",
    ),

    # ─── Pennsylvania ────────────────────────────────────────────────
    P25System(
        name="PSP",
        long_name="Pennsylvania State Police",
        location="Statewide, PA",
        state="PA",
        system_id=56,
        wacn=781120,
        band="800",
        system_type="Phase I",
        description="PA State Police statewide system",
    ),

    # ─── Ohio ────────────────────────────────────────────────────────
    P25System(
        name="MARCS",
        long_name="Multi-Agency Radio Communication System",
        location="Statewide, OH",
        state="OH",
        system_id=360,
        wacn=781152,
        band="700/800",
        system_type="Phase II",
        description="Ohio statewide interop radio system",
    ),

    # ─── Georgia ─────────────────────────────────────────────────────
    P25System(
        name="GIS",
        long_name="Georgia Interoperability System",
        location="Statewide, GA",
        state="GA",
        system_id=680,
        wacn=781472,
        band="700/800",
        system_type="Phase II",
        description="Georgia statewide interop system",
    ),

    # ─── Virginia ────────────────────────────────────────────────────
    P25System(
        name="STARS",
        long_name="Statewide Agencies Radio System",
        location="Statewide, VA",
        state="VA",
        system_id=251,
        wacn=781184,
        band="700/800",
        system_type="Phase II",
        description="Virginia statewide radio system",
    ),

    # ─── Michigan ────────────────────────────────────────────────────
    P25System(
        name="MPSCS",
        long_name="Michigan Public Safety Communications System",
        location="Statewide, MI",
        state="MI",
        system_id=56,
        wacn=781216,
        band="800",
        system_type="Phase II",
        description="Michigan statewide public safety system",
    ),

    # ─── Colorado ────────────────────────────────────────────────────
    P25System(
        name="DTRS",
        long_name="Digital Trunked Radio System",
        location="Statewide, CO",
        state="CO",
        system_id=300,
        wacn=781344,
        band="700/800",
        system_type="Phase II",
        description="Colorado statewide trunked radio system",
    ),

    # ─── Minnesota ───────────────────────────────────────────────────
    P25System(
        name="ARMER",
        long_name="Allied Radio Matrix for Emergency Response",
        location="Statewide, MN",
        state="MN",
        system_id=11,
        wacn=781248,
        band="800",
        system_type="Phase II",
        description="Minnesota statewide public safety system",
    ),

    # ─── Oregon ──────────────────────────────────────────────────────
    P25System(
        name="OWIN",
        long_name="Oregon Wireless Interoperability Network",
        location="Statewide, OR",
        state="OR",
        system_id=170,
        wacn=781792,
        band="700/800",
        system_type="Phase II",
        description="Oregon statewide interop system",
    ),

    # ─── Indiana ─────────────────────────────────────────────────────
    P25System(
        name="SAFE-T",
        long_name="State Alliance For E-Trunking",
        location="Statewide, IN",
        state="IN",
        system_id=14,
        wacn=781184,
        band="800",
        system_type="Phase II",
        description="Indiana statewide public safety system",
    ),

    # ─── North Carolina ──────────────────────────────────────────────
    P25System(
        name="VIPER",
        long_name="Voice Interoperability Plan for Emergency Responders",
        location="Statewide, NC",
        state="NC",
        system_id=251,
        wacn=781440,
        band="700/800",
        system_type="Phase II",
        description="North Carolina statewide system",
    ),

    # ─── Federal ─────────────────────────────────────────────────────
    P25System(
        name="FNBDTRS",
        long_name="Federal Narrowband Digital Trunked Radio",
        location="Nationwide",
        state="US",
        system_id=1,
        wacn=131072,
        band="700/800",
        system_type="Phase I",
        description="Federal interop / national mutual aid",
    ),
]

# Build lookup indexes for fast searching
_BY_ID = {}       # system_id -> list of P25System (IDs can repeat across WACNs)
_BY_NAME = {}     # lowercase name -> P25System
_BY_STATE = {}    # state code -> list of P25System

def _build_indexes():
    """Build lookup indexes from the SYSTEMS list."""
    for sys in SYSTEMS:
        _BY_ID.setdefault(sys.system_id, []).append(sys)
        _BY_NAME[sys.name.lower()] = sys
        _BY_STATE.setdefault(sys.state, []).append(sys)

_build_indexes()


# ─── Public API ──────────────────────────────────────────────────────

def search_systems(query):
    """Search the database by name, location, or system ID.

    Args:
        query: search string (case-insensitive). If numeric, also
               matches system_id. Matches against name, long_name,
               location, and description.

    Returns:
        List of matching P25System objects.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return list(SYSTEMS)

    results = []
    # Try numeric match first
    try:
        num_id = int(query_lower)
        results.extend(_BY_ID.get(num_id, []))
    except ValueError:
        pass

    # Text search across all fields
    for sys in SYSTEMS:
        if sys in results:
            continue
        searchable = (
            sys.name.lower() + " " +
            sys.long_name.lower() + " " +
            sys.location.lower() + " " +
            sys.description.lower() + " " +
            sys.state.lower()
        )
        if query_lower in searchable:
            results.append(sys)

    return results


def get_system_by_name(name):
    """Look up a system by its short name (case-insensitive).

    Returns P25System or None if not found.
    """
    return _BY_NAME.get(name.strip().lower())


def get_system_by_id(system_id):
    """Look up systems by P25 System ID.

    Note: System IDs are not globally unique (they can repeat across
    different WACNs). Returns a list of matching systems.
    """
    return _BY_ID.get(system_id, [])


def get_systems_by_state(state):
    """Get all systems in a state.

    Args:
        state: 2-letter state code (e.g., "WA", "CA") or
               full state name (partial match).

    Returns:
        List of P25System objects in that state.
    """
    state_upper = state.strip().upper()
    if len(state_upper) == 2 and state_upper in _BY_STATE:
        return _BY_STATE[state_upper]

    # Try matching against location field
    state_lower = state.strip().lower()
    return [s for s in SYSTEMS
            if state_lower in s.location.lower()
            or state_lower in s.state.lower()]


def list_all_systems():
    """List all systems in the database.

    Returns:
        List of all P25System objects, sorted by state then name.
    """
    return sorted(SYSTEMS, key=lambda s: (s.state, s.name))


def get_iden_template_key(system):
    """Determine the appropriate IDEN template key for a system.

    Maps the system's band and type to an iden_library template key
    (e.g., "800-TDMA", "700-FDMA").

    Args:
        system: P25System object

    Returns:
        str: template key for iden_library.get_template()
    """
    band = system.band
    is_phase2 = "Phase II" in system.system_type
    mode = "TDMA" if is_phase2 else "FDMA"

    # Multi-band systems default to 800 MHz
    if "/" in band:
        band = "800"

    return f"{band}-{mode}"


def get_default_iden_name(system):
    """Generate a default IDEN set name for a system.

    Returns a 5-char name based on the band and mode.
    """
    key = get_iden_template_key(system)
    names = {
        "800-FDMA": "8FDMA",
        "800-TDMA": "8TDMA",
        "700-FDMA": "7FDMA",
        "700-TDMA": "7TDMA",
        "900-FDMA": "9FDMA",
        "900-TDMA": "9TDMA",
    }
    return names.get(key, key[:5])
