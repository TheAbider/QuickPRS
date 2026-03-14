"""One-click P25 system setup from RadioReference data.

Wraps build_injection_data(), the injector functions, and ECC builder
into a single call that fully configures a radio personality from a
RadioReference system.

Usage:
    from quickprs.auto_setup import auto_setup_from_rr

    summary = auto_setup_from_rr(prs, rr_system)
    # prs is now fully configured with all system components
"""

import logging

logger = logging.getLogger("quickprs")


def auto_setup_from_rr(prs, rr_system, selected_categories=None,
                       selected_tags=None):
    """Fully automatic P25 system setup from RadioReference data.

    Does EVERYTHING:
    1. Builds injection data from RR system (talkgroups, frequencies)
    2. Creates trunk frequency set from all sites
    3. Creates talkgroup set with smart naming
    4. Creates IDEN set with auto-detected parameters
    5. Creates ECC entries from site control channels
    6. Creates the P25TrkSystemConfig with all fields
    7. Injects everything with proper WAN config
    8. Returns summary of what was created

    Args:
        prs: PRSFile object to inject into
        rr_system: RRSystem from RadioReference API or scraper
        selected_categories: set of category IDs to include (None = all)
        selected_tags: set of service tag names to include (None = all)

    Returns:
        dict with summary:
            'system_name': short name used
            'full_name': full system name
            'talkgroups': int count
            'frequencies': int count
            'sites': int count
            'ecc_entries': int count
            'iden_entries': int count
            'warnings': list of warning strings
    """
    from .radioreference import (
        build_injection_data, build_ecc_from_sites,
        make_set_name,
    )
    from .injector import (
        add_p25_trunked_system,
        make_trunk_set, make_group_set, make_iden_set,
    )
    from .record_types import P25TrkSystemConfig, EnhancedCCEntry
    from .validation import validate_prs, ERROR, WARNING

    warnings = []

    # Step 1: Build injection data (talkgroups, frequencies, IDEN)
    data = build_injection_data(rr_system, selected_categories,
                                selected_tags)
    set_name = data['system_name']
    if not set_name:
        set_name = make_set_name(f"SID{rr_system.sid}")

    # Step 2: Create trunk frequency set
    trunk_set = None
    if data['frequencies']:
        trunk_set = make_trunk_set(set_name, data['frequencies'])
    else:
        warnings.append("No frequencies found — trunk set not created")

    # Step 3: Create talkgroup set
    group_set = None
    if data['talkgroups']:
        group_set = make_group_set(set_name, data['talkgroups'])
    else:
        warnings.append("No talkgroups found — group set not created")

    # Step 4: Create IDEN set
    iden_set = None
    iden_count = 0
    if data.get('iden_entries'):
        iden_set = make_iden_set(set_name[:5], data['iden_entries'])
        iden_count = len(data['iden_entries'])

    # Step 5: Build ECC entries from control channels
    ecc_entries = []
    ecc_list = []
    if rr_system.sites:
        sysid_int = 0
        if data['sysid']:
            try:
                sysid_int = int(data['sysid'], 16)
            except (ValueError, TypeError):
                sysid_int = 0

        # Auto-detect WAN config for ECC
        wan_base = 851_006_250
        wan_spacing = 6250
        if data.get('iden_entries'):
            first_iden = data['iden_entries'][0]
            wan_base = first_iden.get('base_freq_hz', wan_base)
            wan_spacing = first_iden.get('chan_spacing_hz', wan_spacing)

        ecc_list = build_ecc_from_sites(
            rr_system.sites,
            sysid_int,
            system_type=rr_system.system_type or "",
            base_freq_hz=wan_base,
            spacing_hz=wan_spacing,
        )

        for entry_type, sys_id, ch1, ch2 in ecc_list:
            ecc_entries.append(EnhancedCCEntry(
                entry_type=entry_type,
                system_id=sys_id,
                channel_ref1=ch1,
                channel_ref2=ch2,
            ))

    # Step 6: Build system config
    sysid_int = 0
    if data['sysid']:
        try:
            sysid_int = int(data['sysid'], 16)
        except (ValueError, TypeError):
            sysid_int = 0

    wacn_int = 0
    if data['wacn']:
        try:
            wacn_int = int(data['wacn'], 16)
        except (ValueError, TypeError):
            wacn_int = 0

    wan_base = 851_006_250
    wan_spacing = 6250
    if data.get('iden_entries'):
        first_iden = data['iden_entries'][0]
        wan_base = first_iden.get('base_freq_hz', wan_base)
        wan_spacing = first_iden.get('chan_spacing_hz', wan_spacing)

    long_name = (data.get('full_name') or set_name)[:16].upper()

    config = P25TrkSystemConfig(
        system_name=set_name,
        long_name=long_name,
        trunk_set_name=set_name if trunk_set else "",
        group_set_name=set_name if group_set else "",
        wan_name=set_name,
        system_id=sysid_int,
        wacn=wacn_int,
        iden_set_name=set_name[:5] if iden_set else "",
        wan_base_freq_hz=wan_base,
        wan_chan_spacing_hz=wan_spacing,
        ecc_entries=ecc_entries,
    )

    # Step 7: Inject everything
    add_p25_trunked_system(prs, config,
                           trunk_set=trunk_set,
                           group_set=group_set,
                           iden_set=iden_set)

    # Validation
    issues = validate_prs(prs)
    val_errors = [(s, m) for s, m in issues if s == ERROR]
    val_warnings = [(s, m) for s, m in issues if s == WARNING]

    if val_errors:
        for _, msg in val_errors:
            warnings.append(f"Validation error: {msg}")

    return {
        'system_name': set_name,
        'full_name': rr_system.name or set_name,
        'sysid': data['sysid'],
        'wacn': data['wacn'],
        'talkgroups': len(data['talkgroups']),
        'frequencies': len(data['frequencies']),
        'sites': len(rr_system.sites),
        'ecc_entries': len(ecc_entries),
        'iden_entries': iden_count,
        'validation_errors': len(val_errors),
        'validation_warnings': len(val_warnings),
        'warnings': warnings,
    }
