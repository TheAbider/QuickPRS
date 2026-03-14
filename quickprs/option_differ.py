"""Option-level diff for PRS files.

Compares radio options between two PRS files at a semantic level:
1. Binary option sections (CAccessoryDevice, CAlertOpts, CGenRadioOpts)
2. XML <platformConfig> (audio, battery, GPS, bluetooth, display, etc.)

Usage:
    from quickprs.option_differ import diff_options, format_option_diff
    diffs = diff_options(prs_a, prs_b)
    print(format_option_diff(diffs))
"""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

logger = logging.getLogger("quickprs")

from .prs_parser import parse_prs
from .option_maps import (
    OPTION_MAPS, XML_FIELD_INDEX, OOR_ALERT_VALUES,
    extract_platform_xml, extract_blob_preamble,
    extract_section_data, read_field,
    format_button_function, format_button_name,
    format_short_menu_name, format_switch_function,
)


@dataclass
class OptionDiff:
    """A single option field difference between two PRS files."""
    category: str        # e.g. "Audio Settings", "Accessory Device Options"
    field_name: str      # human-readable RPM field name
    old_value: str       # value in file A
    new_value: str       # value in file B
    source: str          # "xml" or "binary"
    xml_path: str = ""   # e.g. "audioConfig.speakerMode"


def diff_options(prs_a, prs_b):
    """Compare all radio options between two PRS files.

    Returns a list of OptionDiff objects for every field that differs.
    """
    diffs = []
    diffs.extend(_diff_blob_preamble(prs_a, prs_b))
    diffs.extend(_diff_platform_config(prs_a, prs_b))
    diffs.extend(_diff_binary_sections(prs_a, prs_b))
    return diffs


def diff_options_from_files(path_a, path_b):
    """Compare two PRS files by path. Convenience wrapper."""
    prs_a = parse_prs(path_a)
    prs_b = parse_prs(path_b)
    return diff_options(prs_a, prs_b)


# ─── Blob preamble diff ─────────────────────────────────────────────

def _diff_blob_preamble(prs_a, prs_b):
    """Diff the Repeated OOR Alert Interval between two PRS files."""
    diffs = []
    bp_a = extract_blob_preamble(prs_a)
    bp_b = extract_blob_preamble(prs_b)

    if bp_a is None or bp_b is None:
        return diffs

    if bp_a.oor_alert_interval != bp_b.oor_alert_interval:
        diffs.append(OptionDiff(
            "Alert Options", "Repeated OOR Alert Interval",
            OOR_ALERT_VALUES.get(bp_a.oor_alert_interval,
                                 str(bp_a.oor_alert_interval)),
            OOR_ALERT_VALUES.get(bp_b.oor_alert_interval,
                                 str(bp_b.oor_alert_interval)),
            "binary",
        ))

    return diffs


# ─── XML platformConfig diff ────────────────────────────────────────

def _diff_platform_config(prs_a, prs_b):
    """Diff the <platformConfig> XML between two PRS files."""
    diffs = []

    xml_a = extract_platform_xml(prs_a)
    xml_b = extract_platform_xml(prs_b)

    if xml_a is None and xml_b is None:
        return diffs
    if xml_a is None:
        diffs.append(OptionDiff(
            "Platform Config", "platformConfig",
            "(not present)", "(present)", "xml"))
        return diffs
    if xml_b is None:
        diffs.append(OptionDiff(
            "Platform Config", "platformConfig",
            "(present)", "(not present)", "xml"))
        return diffs

    if xml_a == xml_b:
        return diffs

    # Parse both and do attribute-level comparison
    try:
        root_a = ET.fromstring(xml_a)
        root_b = ET.fromstring(xml_b)
    except ET.ParseError:
        diffs.append(OptionDiff(
            "Platform Config", "XML Parse",
            "(parse error)", "(parse error)", "xml"))
        return diffs

    _diff_elements(root_a, root_b, "", diffs)
    return diffs


def _diff_elements(elem_a, elem_b, path, diffs):
    """Recursively diff two XML elements."""
    current_path = f"{path}/{elem_a.tag}" if path else elem_a.tag

    # Compare attributes
    all_attrs = set(elem_a.attrib) | set(elem_b.attrib)
    for attr in sorted(all_attrs):
        val_a = elem_a.get(attr, "(missing)")
        val_b = elem_b.get(attr, "(missing)")
        if val_a != val_b:
            # Skip trivially equivalent values (empty vs "0" for extraData/delay)
            if attr in ("extraData", "delay"):
                if {val_a, val_b} <= {"", "0", "0.0"}:
                    continue
            # Look up display name from XML field catalog
            field_def = _find_xml_field(elem_a.tag, attr, elem_a)
            if field_def:
                display = _format_field_display(
                    field_def, elem_a, elem_b)
                category = field_def.category
                # Apply display_map for friendly values
                if field_def.display_map:
                    val_a = field_def.display_map.get(val_a, val_a)
                    val_b = field_def.display_map.get(val_b, val_b)
                elif field_def.field_type == "onoff":
                    val_a = "Enabled" if val_a == "ON" else (
                        "Disabled" if val_a == "OFF" else val_a)
                    val_b = "Enabled" if val_b == "ON" else (
                        "Disabled" if val_b == "OFF" else val_b)
            else:
                display, category, val_a, val_b = _format_unknown_diff(
                    elem_a, attr, val_a, val_b)

            diffs.append(OptionDiff(
                category=category,
                field_name=display,
                old_value=val_a,
                new_value=val_b,
                source="xml",
                xml_path=f"{current_path}@{attr}",
            ))

    # Match child elements by tag + distinguishing attributes
    children_a = _group_children(elem_a)
    children_b = _group_children(elem_b)

    all_keys = set(children_a) | set(children_b)
    for key in sorted(all_keys):
        child_a = children_a.get(key)
        child_b = children_b.get(key)
        if child_a is not None and child_b is not None:
            _diff_elements(child_a, child_b, current_path, diffs)
        elif child_a is not None:
            diffs.append(OptionDiff(
                _guess_category(elem_a.tag), f"Element {key}",
                "(present)", "(missing)", "xml",
                xml_path=f"{current_path}/{key}"))
        else:
            diffs.append(OptionDiff(
                _guess_category(elem_b.tag), f"Element {key}",
                "(missing)", "(present)", "xml",
                xml_path=f"{current_path}/{key}"))


def _format_field_display(field_def, elem_a, elem_b):
    """Build contextual display name for a cataloged field.

    For progButton/accessoryButton, prepend the button name.
    For shortMenuItem, prepend the slot position.
    """
    tag = elem_a.tag
    base = field_def.display_name

    if tag in ("progButton", "accessoryButton"):
        btn_name = elem_a.get("buttonName", "")
        friendly = format_button_name(btn_name)
        if base == "Function":
            return friendly
        return f"{friendly} ({base})"

    if tag == "shortMenuItem":
        pos = elem_a.get("position", "?")
        if base == "Menu Item":
            return f"Slot {pos}"
        return f"Slot {pos} ({base})"

    return base


def _format_unknown_diff(elem, attr, val_a, val_b):
    """Format display for a diff that isn't in the XML field catalog."""
    tag = elem.tag
    category = _guess_category(tag)

    # Prog button: show button name + friendly function
    if tag == "progButton" or tag == "accessoryButton":
        btn_name = elem.get("buttonName", "")
        display = format_button_name(btn_name)
        if attr == "function":
            val_a = format_button_function(val_a)
            val_b = format_button_function(val_b)
            return display, category, val_a, val_b
        display = f"{display} ({attr})"
        return display, category, val_a, val_b

    # Prog buttons container: switch functions
    if tag == "progButtons":
        if "Func" in attr or "Function" in attr:
            display = attr.replace("_", " ")
            if "Function" not in attr:
                display = display.replace("Func", "Function")
            val_a = format_switch_function(val_a)
            val_b = format_switch_function(val_b)
            return display, category, val_a, val_b
        display = attr.replace("_", " ")
        return display, category, val_a, val_b

    # Short menu item
    if tag == "shortMenuItem":
        pos = elem.get("position", "?")
        if attr == "name":
            display = f"Slot {pos}"
            val_a = format_short_menu_name(val_a)
            val_b = format_short_menu_name(val_b)
            return display, category, val_a, val_b
        display = f"Slot {pos} ({attr})"
        return display, category, val_a, val_b

    # Default: tag.attr
    return f"{tag}.{attr}", category, val_a, val_b


def _group_children(elem):
    """Group child elements by a unique key (tag + distinguishing attribs)."""
    groups = {}
    counts = {}
    for child in elem:
        tag = child.tag
        # Use distinguishing attributes for disambiguation
        key_parts = [tag]
        for attr in ("buttonName", "name", "micType", "position"):
            val = child.get(attr)
            if val is not None:
                key_parts.append(f"{attr}={val}")
                break
        else:
            # No distinguishing attr — use occurrence index
            counts[tag] = counts.get(tag, 0) + 1
            if counts[tag] > 1:
                key_parts.append(f"#{counts[tag]}")

        key = ":".join(key_parts)
        groups[key] = child
    return groups


def _find_xml_field(tag, attr, elem):
    """Look up an XmlFieldDef for a given element tag and attribute."""
    # Direct match
    key = (tag, attr)
    if key in XML_FIELD_INDEX:
        return XML_FIELD_INDEX[key]

    # Try with microphone qualification
    mic_type = elem.get("micType", "")
    if mic_type:
        qualified = f"audioConfig/microphone[@micType='{mic_type}']"
        key = (qualified, attr)
        if key in XML_FIELD_INDEX:
            return XML_FIELD_INDEX[key]

    return None


def _guess_category(tag):
    """Guess the RPM option category from an XML element tag."""
    categories = {
        "audioConfig": "Audio Settings",
        "microphone": "Audio Settings",
        "miscConfig": "Misc Settings",
        "gpsConfig": "GPS Settings",
        "bluetoothConfig": "Bluetooth Settings",
        "accessoryConfig": "Accessory Options",
        "manDownConfig": "Accessory Options",
        "progButtons": "Programmable Buttons",
        "progButton": "Programmable Buttons",
        "accessoryButtons": "Accessory Buttons",
        "accessoryButton": "Accessory Buttons",
        "shortMenu": "Short Menu",
        "shortMenuItem": "Short Menu",
        "TimeDateCfg": "Clock Settings",
    }
    return categories.get(tag, "Platform Config")


# ─── Binary section diff ────────────────────────────────────────────

def _diff_binary_sections(prs_a, prs_b):
    """Diff binary option sections (CAccessoryDevice, CAlertOpts, etc.)."""
    diffs = []

    for class_name, opt_map in OPTION_MAPS.items():
        sec_a = prs_a.get_section_by_class(class_name)
        sec_b = prs_b.get_section_by_class(class_name)

        if sec_a is None and sec_b is None:
            continue
        if sec_a is None:
            diffs.append(OptionDiff(
                opt_map.display_name, f"{class_name} section",
                "(not present)", "(present)", "binary"))
            continue
        if sec_b is None:
            diffs.append(OptionDiff(
                opt_map.display_name, f"{class_name} section",
                "(present)", "(not present)", "binary"))
            continue

        data_a = extract_section_data(sec_a)
        data_b = extract_section_data(sec_b)

        if data_a is None or data_b is None:
            continue

        # Compare mapped fields
        for field_def in opt_map.fields:
            val_a = read_field(data_a, field_def)
            val_b = read_field(data_b, field_def)
            if val_a != val_b:
                diffs.append(OptionDiff(
                    category=opt_map.display_name,
                    field_name=f"{field_def.display_name} (binary)",
                    old_value=str(val_a),
                    new_value=str(val_b),
                    source="binary",
                ))

        # Report unmapped byte changes (within declared data_size only)
        compare_len = opt_map.data_size
        if compare_len == 0:
            compare_len = min(len(data_a), len(data_b))
        else:
            compare_len = min(compare_len, len(data_a), len(data_b))
        mapped_offsets = set()
        for f in opt_map.fields:
            for i in range(f.size):
                mapped_offsets.add(f.offset + i)

        unmapped_changes = []
        for i in range(compare_len):
            if i not in mapped_offsets and data_a[i] != data_b[i]:
                unmapped_changes.append(
                    f"  byte[{i}]: 0x{data_a[i]:02x} -> 0x{data_b[i]:02x}")

        if unmapped_changes:
            diffs.append(OptionDiff(
                category=opt_map.display_name,
                field_name="Unmapped byte changes",
                old_value="",
                new_value="\n".join(unmapped_changes),
                source="binary",
            ))

    return diffs


# ─── Raw byte diff (for unmapped analysis) ───────────────────────────

@dataclass
class ByteDiff:
    """A single byte difference within a section."""
    offset: int          # byte offset within data payload
    data_offset: int     # absolute offset including header
    old_byte: int
    new_byte: int


def diff_section_bytes(prs_a, prs_b, class_name):
    """Raw byte-level diff of a named section's data payload.

    Returns list of ByteDiff objects. Useful for reverse-engineering
    unmapped sections.
    """
    sec_a = prs_a.get_section_by_class(class_name)
    sec_b = prs_b.get_section_by_class(class_name)

    if sec_a is None or sec_b is None:
        return []

    data_a = extract_section_data(sec_a)
    data_b = extract_section_data(sec_b)

    if data_a is None or data_b is None:
        return []

    diffs = []
    min_len = min(len(data_a), len(data_b))
    from .record_types import parse_class_header
    try:
        _, _, _, header_size = parse_class_header(sec_a.raw, 0)
    except Exception as e:
        logger.debug("Could not parse header for binary diff: %s", e)
        header_size = 0

    for i in range(min_len):
        if data_a[i] != data_b[i]:
            diffs.append(ByteDiff(
                offset=i,
                data_offset=header_size + i,
                old_byte=data_a[i],
                new_byte=data_b[i],
            ))

    return diffs


# ─── Formatting ──────────────────────────────────────────────────────

def format_option_diff(diffs, filepath_a="", filepath_b=""):
    """Format option diffs as human-readable text.

    Returns a list of lines.
    """
    lines = []

    if filepath_a or filepath_b:
        lines.append(f"A: {filepath_a}")
        lines.append(f"B: {filepath_b}")
        lines.append("")

    if not diffs:
        lines.append("No option differences found.")
        return lines

    # Group by category
    categories = {}
    for d in diffs:
        categories.setdefault(d.category, []).append(d)

    for cat in sorted(categories):
        lines.append(f"--- {cat} ---")
        for d in categories[cat]:
            src = f" [{d.source}]" if d.source else ""
            if "\n" in d.new_value:
                # Multi-line (unmapped bytes)
                lines.append(f"  ~ {d.field_name}{src}:")
                for sub in d.new_value.split("\n"):
                    lines.append(f"    {sub}")
            else:
                lines.append(
                    f"  ~ {d.field_name}: {d.old_value} -> {d.new_value}{src}")
        lines.append("")

    lines.append(f"Total: {len(diffs)} difference(s)")
    return lines
