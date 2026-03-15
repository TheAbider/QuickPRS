"""Interactive text wizard for building a radio personality.

Guides the user through creating a PRS file step by step:
1. Choose: create new or modify existing
2. Personality name, output file
3. Add P25 trunked systems (name, ID, WACN, frequencies, talkgroups)
4. Add conventional channel templates (MURS, GMRS, FRS, etc.)
5. Set radio options (GPS, password, timezone)
6. Validate and save
"""

import sys
from pathlib import Path

from . import __version__
from .templates import get_template_names


def _input(prompt, default=None):
    """Read user input with optional default value.

    Args:
        prompt: text to display
        default: value to use if user presses Enter without typing

    Returns:
        str: user input or default
    """
    if default is not None:
        full = f"{prompt} [{default}]: "
    else:
        full = f"{prompt}: "
    try:
        value = input(full).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1)
    return value if value else (default if default is not None else "")


def _input_yn(prompt, default=False):
    """Yes/no prompt.

    Args:
        prompt: text to display
        default: True for yes, False for no

    Returns:
        bool
    """
    hint = "Y/n" if default else "y/N"
    result = _input(f"{prompt} [{hint}]", "")
    if not result:
        return default
    return result.lower().startswith('y')


def _read_multiline(prompt_msg):
    """Read multiple lines until blank line.

    Args:
        prompt_msg: initial instruction text

    Returns:
        list of non-empty stripped lines
    """
    print(prompt_msg)
    lines = []
    while True:
        try:
            line = input("  ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break
        lines.append(line)
    return lines


def _collect_p25_system():
    """Collect data for one P25 trunked system.

    Returns:
        dict with keys: short_name, system_id, wacn, long_name,
        frequencies (list of (tx, rx) tuples),
        talkgroups (list of (id, short, long) tuples)
    """
    short_name = _input("System short name (8 chars max)", "")[:8]
    if not short_name:
        return None

    long_name = _input("System long name (16 chars max)", short_name)[:16]

    try:
        system_id = int(_input("System ID (decimal)", "0"))
    except ValueError:
        system_id = 0

    try:
        wacn = int(_input("WACN (decimal, 0 to skip)", "0"))
    except ValueError:
        wacn = 0

    # Frequencies
    freq_lines = _read_multiline(
        "Enter trunk frequencies (one per line, tx,rx format, "
        "blank line to finish):")
    frequencies = []
    for line in freq_lines:
        parts = line.split(',')
        try:
            tx = float(parts[0].strip())
            rx = float(parts[1].strip()) if len(parts) > 1 else tx
            frequencies.append((tx, rx))
        except (ValueError, IndexError):
            print(f"  Skipping invalid frequency: {line}")

    # Talkgroups
    tg_lines = _read_multiline(
        "Enter talkgroups (one per line: id,short_name,long_name, "
        "blank to finish):")
    talkgroups = []
    for line in tg_lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            print(f"  Skipping invalid talkgroup: {line}")
            continue
        try:
            gid = int(parts[0])
            short = parts[1][:8]
            long = parts[2][:16] if len(parts) > 2 else short
            talkgroups.append((gid, short, long))
        except ValueError:
            print(f"  Skipping invalid talkgroup: {line}")

    return {
        'short_name': short_name,
        'long_name': long_name,
        'system_id': system_id,
        'wacn': wacn,
        'frequencies': frequencies,
        'talkgroups': talkgroups,
    }


def _collect_templates():
    """Ask user which channel templates to include.

    Returns:
        list of template name strings
    """
    available = get_template_names()
    avail_str = ", ".join(available)
    result = _input(
        f"Enter template names (comma-separated, or blank to skip)\n"
        f"  Available: {avail_str}", "")
    if not result:
        return []

    names = [n.strip().lower() for n in result.split(',')]
    valid = []
    for n in names:
        if n in available:
            valid.append(n)
        else:
            print(f"  Unknown template '{n}', skipping")
    return valid


def _build_ini_content(personality_name, systems, templates, options):
    """Generate INI config content from wizard inputs.

    Args:
        personality_name: PRS filename
        systems: list of system dicts from _collect_p25_system
        templates: list of template name strings
        options: dict of option key -> value

    Returns:
        str: INI file content
    """
    lines = []
    lines.append("[personality]")
    lines.append(f"name = {personality_name}")
    lines.append(f"author = QuickPRS Wizard")
    lines.append("")

    # P25 systems
    for sys_data in systems:
        name = sys_data['short_name']
        lines.append(f"[system.{name}]")
        lines.append("type = p25_trunked")
        lines.append(f"long_name = {sys_data['long_name']}")
        lines.append(f"system_id = {sys_data['system_id']}")
        if sys_data['wacn']:
            lines.append(f"wacn = {sys_data['wacn']}")
        lines.append("")

        if sys_data['frequencies']:
            lines.append(f"[system.{name}.frequencies]")
            for i, (tx, rx) in enumerate(sys_data['frequencies'], 1):
                lines.append(f"{i} = {tx},{rx}")
            lines.append("")

        if sys_data['talkgroups']:
            lines.append(f"[system.{name}.talkgroups]")
            for i, (gid, short, long) in enumerate(
                    sys_data['talkgroups'], 1):
                lines.append(f"{i} = {gid},{short},{long}")
            lines.append("")

    # Template channels
    for tmpl in templates:
        label = tmpl.upper()[:8]
        lines.append(f"[channels.{label}]")
        lines.append(f"template = {tmpl}")
        lines.append("")

    # Options
    if options:
        lines.append("[options]")
        for key, value in options.items():
            lines.append(f"{key} = {value}")
        lines.append("")

    return "\n".join(lines)


def run_wizard(modify_file=None):
    """Run the interactive wizard.

    Args:
        modify_file: if provided, path to existing PRS to modify.
                     Currently only new-file creation is supported;
                     modify_file is reserved for future use.

    Returns:
        0 on success, 1 on error.
    """
    print()
    print(f"QuickPRS Interactive Wizard (v{__version__})")
    print("=" * 40)
    print()

    if modify_file:
        print(f"Modifying: {modify_file}")
        print("Note: modify mode re-builds from scratch on top of "
              "the existing file.")
        print()

    # --- Step 1: Personality ---
    print("--- Step 1: Personality ---")
    name = _input("Personality name", "New Radio.PRS")
    if not name.upper().endswith('.PRS'):
        name += '.PRS'
    output_file = _input("Output file", name)
    print()

    # --- Step 2: P25 Systems ---
    print("--- Step 2: P25 Systems ---")
    systems = []
    while True:
        if not _input_yn("Add a P25 trunked system?", False):
            break
        sys_data = _collect_p25_system()
        if sys_data:
            systems.append(sys_data)
            print(f"  Added system: {sys_data['short_name']}")
        print()
        if not _input_yn("Add another P25 system?", False):
            break
    print()

    # --- Step 3: Conventional Channels ---
    print("--- Step 3: Conventional Channels ---")
    templates = _collect_templates()
    if templates:
        print(f"  Templates: {', '.join(templates)}")
    print()

    # --- Step 4: Radio Options ---
    print("--- Step 4: Radio Options ---")
    options = {}

    gps = _input("Set GPS mode? [ON/off]", "")
    if gps:
        options['gps.gpsMode'] = gps.upper()

    password = _input("Set radio password (blank to skip)", "")
    if password:
        options['misc.password'] = password

    timezone = _input("Set timezone (e.g., PST, EST, UTC, blank to skip)", "")
    if timezone:
        options['display.timeZone'] = timezone.upper()
    print()

    # --- Build ---
    print("--- Building personality... ---")

    ini_content = _build_ini_content(name, systems, templates, options)

    # Write temp INI and build
    import tempfile
    from .config_builder import build_from_config, ConfigError

    try:
        with tempfile.NamedTemporaryFile(
                mode='w', suffix='.ini', delete=False,
                encoding='utf-8') as f:
            f.write(ini_content)
            tmp_ini = f.name

        prs = build_from_config(tmp_ini)
    except ConfigError as e:
        print(f"Error building personality: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            Path(tmp_ini).unlink()
        except OSError:
            pass

    # Write output
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = prs.to_bytes()
    out_path.write_bytes(raw)

    # Validate
    from .validation import validate_prs, ERROR, WARNING
    issues = validate_prs(prs)
    errors = [m for s, m in issues if s == ERROR]
    warnings = [m for s, m in issues if s == WARNING]

    print(f"Created: {out_path} ({len(raw):,} bytes, "
          f"{len(prs.sections)} sections)")
    print(f"Validation: {len(errors)} errors, {len(warnings)} warnings")
    for w in warnings:
        print(f"  WARN: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print()
    print(f"Done! Load {out_path.name} onto your radio using Harris RPM.")

    return 0
