"""Option field maps for XG-100P PRS files.

PRS files store radio options in TWO places:
1. Binary sections (CAccessoryDevice, CAlertOpts, CGenRadioOpts) — only present
   when those categories are edited in RPM. Fixed-size byte arrays.
2. XML <platformConfig> — embedded in the big data blob, always present, contains
   all settings as human-readable XML attributes.

Additionally, file metadata (filename, username, GPS coords, OOR alert interval)
is stored in the CProgButtons section or embedded in the data blob before the XML.

This module provides:
- extract_platform_config(prs) — find and parse XML from PRS data blob
- write_platform_config(prs, config) — write modified XML back into PRS
- extract_blob_preamble(prs) — extract file metadata from data blob
- Binary field maps for CAccessoryDevice, CAlertOpts, CGenRadioOpts
- XG-100P factory defaults
"""

import logging
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("quickprs")

from .prs_parser import PRSFile, Section


# ─── Platform Config XML extraction ─────────────────────────────────

_XML_START = b'<platformConfig>'
_XML_END = b'</platformConfig>'


def extract_platform_xml(prs):
    """Find and return the raw <platformConfig> XML string from a PRS file.

    The XML is embedded in a data blob section (usually the big unnamed one
    containing CAccessoryDevice data). Returns the XML string or None.
    """
    full = prs.to_bytes()
    start = full.find(_XML_START)
    if start < 0:
        return None
    end = full.find(_XML_END, start)
    if end < 0:
        return None
    end += len(_XML_END)
    return full[start:end].decode('ascii', errors='replace')


def extract_platform_config(prs):
    """Extract and parse <platformConfig> XML into a structured dict.

    Returns a dict with keys matching XML element names, each containing
    a dict of attribute name -> value. Child elements are nested.
    Returns None if no platformConfig found.
    """
    xml_str = extract_platform_xml(prs)
    if not xml_str:
        return None
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None
    return _element_to_dict(root)


def _element_to_dict(elem):
    """Recursively convert an XML Element to a nested dict.

    Attributes become key-value pairs. Child elements become nested dicts
    or lists of dicts (for repeated elements like <progButton>).
    """
    result = dict(elem.attrib)
    children = {}
    for child in elem:
        tag = child.tag
        child_dict = _element_to_dict(child)
        if tag in children:
            # Multiple children with same tag → list
            if not isinstance(children[tag], list):
                children[tag] = [children[tag]]
            children[tag].append(child_dict)
        else:
            children[tag] = child_dict
    result.update(children)
    return result


def find_platform_xml_location(prs):
    """Find the section index and byte offsets of the platformConfig XML.

    Returns (section_idx, start_within_section, end_within_section) or None.
    """
    for i, sec in enumerate(prs.sections):
        start = sec.raw.find(_XML_START)
        if start >= 0:
            end = sec.raw.find(_XML_END, start)
            if end >= 0:
                end += len(_XML_END)
                return (i, start, end)
    return None


def write_platform_config(prs, new_xml_str):
    """Replace the <platformConfig> XML in the PRS file with new XML.

    Modifies the PRSFile in-place by replacing the XML bytes within
    the section that contains it. Also updates the uint16 LE length
    prefix that sits 2 bytes before the XML start (after the 0xFF marker).

    Returns True if successful.
    """
    loc = find_platform_xml_location(prs)
    if loc is None:
        return False

    sec_idx, start, end = loc
    sec = prs.sections[sec_idx]
    old_raw = sec.raw

    new_xml_bytes = new_xml_str.encode('ascii')
    new_raw = bytearray(old_raw[:start] + new_xml_bytes + old_raw[end:])

    # Update the uint16 LE length prefix at (start - 2)
    if start >= 3 and old_raw[start - 3] == 0xFF:
        struct.pack_into('<H', new_raw, start - 2, len(new_xml_bytes))

    prs.sections[sec_idx] = Section(
        offset=sec.offset,
        raw=bytes(new_raw),
        class_name=sec.class_name,
    )
    return True


def config_to_xml(config, tag='platformConfig'):
    """Convert a config dict back to XML string.

    This is the inverse of extract_platform_config — takes a nested dict
    and produces the XML string that can be written back to the PRS file.
    """
    root = _dict_to_element(config, tag)
    return ET.tostring(root, encoding='unicode')


def _dict_to_element(d, tag):
    """Convert a nested dict back to an XML Element."""
    elem = ET.Element(tag)
    for key, val in d.items():
        if isinstance(val, dict):
            child = _dict_to_element(val, key)
            elem.append(child)
        elif isinstance(val, list):
            for item in val:
                child = _dict_to_element(item, key)
                elem.append(child)
        else:
            elem.set(key, str(val))
    return elem


# ─── Section name mapping for set-option CLI ─────────────────────────

SECTION_MAP = {
    'gps': 'gpsConfig',
    'misc': 'miscConfig',
    'audio': 'audioConfig',
    'bluetooth': 'bluetoothConfig',
    'timedate': 'TimeDateCfg',
    'accessory': 'accessoryConfig',
    'mandown': 'manDownConfig',
    'display': 'miscConfig',  # display options are in miscConfig
}


_DEFAULT_PLATFORM_XML = (
    '<platformConfig>'
    '<gpsConfig gpsMode="OFF" type="INTERNAL_GPS" operationMode="INTERNAL" '
    'mapDatum="DATUM_WGD" positionFormat="LAT_LONG_DMS" '
    'elevationUnits="METERS" northingType="TRUE" gridDigits="SIX" '
    'angularUnits="CARDINAL" reportInterval="5" />'
    '<audioConfig speakerMode="ON" pttMode="ON" noiseCancellation="OFF" '
    'tones="ON" cctTimer="120" />'
    '<bluetoothConfig friendlyName="" btMode="OFF" btAdminMode="OFF" />'
    '<miscConfig password="" maintenancePassword="" topFpMode="BL_ON" '
    'topFpOrient="FRONT" topFpIntensity="5" topFpTimeout="30" '
    'topFpLedColor="GREEN" dateFormat="US_DATE_FORMAT" '
    'p25Optimize="OFF" batteryType="STANDARD" '
    'autoRSSIThreshold="3" ledEnabled="true" />'
    '<TimeDateCfg time="TIME_12_HOUR_FORMAT" zone="EST" '
    'date="US_DATE_FORMAT" />'
    '<accessoryConfig noiseCancellation="ON" micSelectMode="TOP" '
    'pttMode="BOTH" />'
    '<manDownConfig inactivityTime="240" warningTime="30" '
    'sensitivity="0" action="MD_EMERGENCY_CALL" />'
    '</platformConfig>'
)


def _create_default_platform_xml():
    """Return a default platformConfig XML string with sensible defaults."""
    return _DEFAULT_PLATFORM_XML


def _inject_platform_xml(prs, xml_str):
    """Inject platformConfig XML into a PRS file that doesn't have one.

    Adds the XML to the IDEN section trailing data. If the IDEN section
    exists, appends the XML with the proper length prefix. If not,
    returns False.
    """
    from .record_types import (
        parse_class_header, extract_iden_trailing_data,
    )
    from .binary_io import read_uint16_le

    iden_sec = prs.get_section_by_class('CDefaultIdenElem')
    iset_sec = prs.get_section_by_class('CIdenDataSet')
    if not iden_sec or not iset_sec:
        return False

    # Get the first count from the set section
    _, _, _, ds = parse_class_header(iset_sec.raw, 0)
    fc, _ = read_uint16_le(iset_sec.raw, ds)

    # Get existing trailing data
    trailing = extract_iden_trailing_data(iden_sec.raw, fc)

    # Build new trailing data with XML inserted
    xml_bytes = xml_str.encode('ascii')
    # Format: [existing pre-XML padding] + ff + uint16(xml_len) + xml + [post-XML]
    # For a file without XML, the trailing is typically just zeros.
    # We need to: replace the trailing with: padding + xml block + original post-data
    # Simple approach: insert XML at the start of trailing, keeping any
    # existing trailing data (passwords, GUID) after it.

    # Check if trailing already has some structure (non-zero bytes)
    # If it's all zeros, just replace with XML block
    new_trailing = bytearray()
    # 6 zero bytes padding (matching PAWSOVERMAWS pattern)
    new_trailing += b'\x00' * 6
    # FF marker + uint16 XML length
    new_trailing += b'\xff'
    new_trailing += struct.pack('<H', len(xml_bytes))
    # XML content
    new_trailing += xml_bytes
    # Append original trailing data (may contain passwords, GUID)
    new_trailing += trailing

    # Rebuild IDEN section: parse sets, rebuild with new trailing
    from .record_types import parse_iden_section
    _, _, _, cd = parse_class_header(iden_sec.raw, 0)
    sets = parse_iden_section(iden_sec.raw, cd, len(iden_sec.raw), fc)

    from .injector import _build_iden_raw
    byte1, byte2 = iden_sec.raw[2], iden_sec.raw[3]
    new_raw = _build_iden_raw(sets, byte1, byte2,
                              trailing_data=bytes(new_trailing))

    # Replace the section
    for i, s in enumerate(prs.sections):
        if s.class_name == 'CDefaultIdenElem':
            prs.sections[i] = Section(
                offset=s.offset, raw=new_raw,
                class_name='CDefaultIdenElem')
            break

    return True


def set_platform_option(prs, section_name, attr_name, value):
    """Modify a platformConfig XML attribute in the PRS file.

    Finds the XML in the PRS data, modifies the specified attribute,
    and rebuilds the section with the updated XML (including the
    uint16 length prefix).

    Args:
        prs: parsed PRSFile object
        section_name: friendly section name (e.g. 'gps', 'audio')
            or XML element name (e.g. 'gpsConfig', 'audioConfig')
        attr_name: XML attribute name (e.g. 'gpsMode', 'speakerMode')
        value: new value as string

    Returns:
        True if the attribute was modified, False on error.

    Raises:
        ValueError: if no platformConfig found, section unknown,
            or attribute not found in the XML.
    """
    xml_str = extract_platform_xml(prs)
    if xml_str is None:
        # Create a default platformConfig XML and inject it
        xml_str = _create_default_platform_xml()
        if not _inject_platform_xml(prs, xml_str):
            raise ValueError(
                "No platformConfig XML found and unable to create one")

    # Resolve friendly section name to XML element name
    xml_element = SECTION_MAP.get(section_name, section_name)

    # Parse the XML
    root = ET.fromstring(xml_str)

    # Find the target element
    target = root.find(xml_element)
    if target is None:
        valid = [child.tag for child in root]
        raise ValueError(
            f"Section '{xml_element}' not found in platformConfig. "
            f"Available: {', '.join(sorted(set(valid)))}")

    # Check if attribute exists (warn but still set it)
    old_val = target.get(attr_name)
    if old_val is None:
        # Attribute doesn't exist — could be new. Set it anyway but log.
        logger.info("Attribute '%s' not found in <%s>, creating it",
                    attr_name, xml_element)

    # Set the attribute
    target.set(attr_name, str(value))

    # Rebuild XML and write back
    new_xml_str = ET.tostring(root, encoding='unicode')
    if not write_platform_config(prs, new_xml_str):
        raise ValueError("Failed to write updated XML back to PRS file")

    return True


def list_platform_options(prs):
    """List all platformConfig options with their current values.

    Returns a list of (section_friendly, element_name, attr_name, value)
    tuples, sorted by section then attribute name. Returns empty list if
    no platformConfig found.
    """
    xml_str = extract_platform_xml(prs)
    if xml_str is None:
        return []

    root = ET.fromstring(xml_str)

    # Build reverse map: xml_element -> friendly name(s)
    reverse_map = {}
    for friendly, xml_elem in SECTION_MAP.items():
        reverse_map.setdefault(xml_elem, []).append(friendly)

    results = []
    for child in root:
        tag = child.tag
        friendlies = reverse_map.get(tag, [tag])
        friendly = friendlies[0]  # use first friendly name

        # Attributes on this element
        for attr, val in sorted(child.attrib.items()):
            results.append((friendly, tag, attr, val))

        # Nested child elements (like microphone, progButton)
        for sub in child:
            sub_id = ""
            # For elements with identifying attributes, include them
            for id_attr in ('buttonName', 'micType', 'name'):
                if id_attr in sub.attrib:
                    sub_id = f"[{id_attr}={sub.attrib[id_attr]}]"
                    break
            sub_label = f"{sub.tag}{sub_id}"
            for attr, val in sorted(sub.attrib.items()):
                results.append((friendly, f"{tag}/{sub_label}",
                                attr, val))

    return results


# ─── Blob preamble / file metadata ───────────────────────────────────
# The data blob (or CProgButtons section) stores file metadata:
# filename, username, GPS coordinates, and the Repeated OOR Alert Interval.
#
# In simple PRS files (few sections), metadata is embedded in the same
# section as the XML, between the CAccessoryDevice data and <platformConfig>.
# In complex files, CProgButtons is a separate named section.

OOR_ALERT_VALUES = {
    0: "Off",
    1: "Slow",
    2: "Medium",
    3: "Fast",
}


@dataclass
class BlobPreamble:
    """File metadata extracted from the data blob or CProgButtons section."""
    filename: str = ""
    username: str = ""
    oor_alert_interval: int = 0     # 0=Off, 1=Slow, 2=Med, 3=Fast
    gps_doubles: List[float] = field(default_factory=list)
    marker_byte: int = 0            # 0x0e when RPM session had GPS, else 0x00
    raw_metadata: bytes = b""       # full metadata bytes for debugging

    @property
    def oor_display(self):
        """Friendly name for OOR alert interval."""
        return OOR_ALERT_VALUES.get(self.oor_alert_interval,
                                    f"Unknown({self.oor_alert_interval})")


def extract_blob_preamble(prs):
    """Extract file metadata (filename, username, GPS, OOR) from a PRS file.

    Tries CProgButtons section first (complex files), then CT99 section
    tail (minimal files without CProgButtons), then falls back to parsing
    the data blob section that contains the XML.

    Returns a BlobPreamble or None if no metadata found.
    """
    # Strategy 1: CProgButtons standalone section
    for sec in prs.sections:
        if sec.class_name == "CProgButtons":
            return _parse_progbuttons_preamble(sec)

    # Strategy 2: CT99 section tail (minimal PRS files without CProgButtons)
    result = _parse_ct99_preamble(prs)
    if result is not None:
        return result

    # Strategy 3: embedded in the XML-containing section
    loc = find_platform_xml_location(prs)
    if loc is None:
        return None

    sec = prs.sections[loc[0]]
    xml_start = loc[1]

    # The XML-containing section has a class header + section data + metadata + XML
    # Parse the class header to find where section data starts
    from .record_types import parse_class_header
    try:
        _, _, _, data_start = parse_class_header(sec.raw, 0)
    except Exception:
        return None

    # Skip section-specific data (CAccessoryDevice = 8 bytes)
    pos = data_start + 8

    return _parse_metadata_region(sec.raw, pos, xml_start)


# CT99 base structure: 3 blocks of 33 bytes with 2-byte separators between
# blocks 1-2 and 2-3, for a total fixed prefix of 103 bytes.
# Metadata tail (if present) starts at byte 103 of the data region.
_CT99_FIXED_PREFIX = 33 + 2 + 33 + 2 + 33  # = 103


def _parse_ct99_preamble(prs):
    """Extract metadata from the CT99 section tail.

    In minimal PRS files (no CProgButtons, no platformConfig XML), the
    personality metadata (filename, username, band limits) is stored at
    the end of the CT99 section after the 103-byte tone slot prefix.

    Structure: LPS(personality_name) + 00 00 + LPS(username) + metadata_bytes
    """
    from .record_types import parse_class_header

    for sec in prs.sections:
        if sec.class_name != "CT99":
            continue

        try:
            _, _, _, data_start = parse_class_header(sec.raw, 0)
        except Exception:
            return None

        data = sec.raw[data_start:]
        if len(data) <= _CT99_FIXED_PREFIX:
            return None  # no metadata tail

        tail = data[_CT99_FIXED_PREFIX:]
        if len(tail) < 2:
            return None

        pos = 0
        # Filename LPS
        fn_len = tail[pos]
        pos += 1
        if fn_len == 0 or pos + fn_len > len(tail):
            return None
        filename = tail[pos:pos + fn_len].decode('ascii', errors='replace')
        pos += fn_len

        # 2 null separator
        pos += 2

        # Username LPS (may be zero-length)
        if pos >= len(tail):
            return BlobPreamble(filename=filename)
        uname_len = tail[pos]
        pos += 1
        username = tail[pos:pos + uname_len].decode('ascii', errors='replace')
        pos += uname_len

        # Remaining is the standard metadata bytes
        meta = tail[pos:]
        return _parse_metadata_bytes(meta, filename, username)

    return None


def _parse_progbuttons_preamble(sec):
    """Parse CProgButtons section for file metadata."""
    from .record_types import parse_class_header
    try:
        _, _, _, data_start = parse_class_header(sec.raw, 0)
    except Exception:
        return None

    data = sec.raw[data_start:]
    if len(data) < 4:
        return None

    # CProgButtons data: 2 null bytes + filename_LPS + 2 nulls + username_LPS + metadata
    pos = 2  # skip leading 00 00

    # Filename
    if pos >= len(data):
        return None
    fn_len = data[pos]
    pos += 1
    filename = data[pos:pos + fn_len].decode('ascii', errors='replace')
    pos += fn_len

    # 2 null separator
    pos += 2

    # Username
    if pos >= len(data):
        return BlobPreamble(filename=filename)
    uname_len = data[pos]
    pos += 1
    username = data[pos:pos + uname_len].decode('ascii', errors='replace')
    pos += uname_len

    # Metadata region (remaining bytes)
    meta = data[pos:]
    return _parse_metadata_bytes(meta, filename, username)


def _parse_metadata_region(raw, pos, xml_start):
    """Parse embedded metadata between section data and XML."""
    if pos >= xml_start or pos >= len(raw):
        return None

    # Filename LPS
    fn_len = raw[pos]
    pos += 1
    filename = raw[pos:pos + fn_len].decode('ascii', errors='replace')
    pos += fn_len

    # 2 null separator
    pos += 2

    # Username LPS
    if pos >= xml_start:
        return BlobPreamble(filename=filename)
    uname_len = raw[pos]
    pos += 1
    username = raw[pos:pos + uname_len].decode('ascii', errors='replace')
    pos += uname_len

    # Metadata bytes (everything between username end and XML start)
    meta = raw[pos:xml_start]
    return _parse_metadata_bytes(meta, filename, username)


def _parse_metadata_bytes(meta, filename, username):
    """Parse the raw metadata bytes into a BlobPreamble."""
    preamble = BlobPreamble(
        filename=filename,
        username=username,
        raw_metadata=bytes(meta),
    )

    if len(meta) < 2:
        return preamble

    preamble.marker_byte = meta[0]

    # Byte 6: Repeated OOR Alert Interval
    if len(meta) > 6:
        preamble.oor_alert_interval = meta[6]

    # GPS doubles start at byte 2 — note: byte 6 (OOR) overlaps the first
    # double. When GPS is present, OOR is always 0 so the double is valid.
    # When OOR > 0, byte 6 corrupts the first double, so skip GPS entirely.
    gps = []
    if preamble.oor_alert_interval == 0 and len(meta) >= 10:
        offset = 2
        while offset + 8 <= len(meta):
            val = struct.unpack_from('<d', meta, offset)[0]
            if val == 0.0:
                break  # stop at trailing zeros
            gps.append(val)
            offset += 8
            if len(gps) >= 4:
                break
    preamble.gps_doubles = gps

    return preamble


# ─── Binary field maps ───────────────────────────────────────────────

@dataclass
class FieldDef:
    """Definition of a single field within a binary option section."""
    offset: int               # byte offset within data payload
    size: int                 # byte count (1, 2, or 4)
    name: str                 # field identifier
    display_name: str         # human-readable RPM field name
    field_type: str           # 'bool', 'uint8', 'uint16', 'int8', 'enum', 'flags', 'double'
    enum_values: Dict = field(default_factory=dict)  # {int_value: display_label}
    min_val: Optional[int] = None
    max_val: Optional[int] = None
    description: str = ""
    conditional: bool = False  # True if greyed out in RPM by default


@dataclass
class OptionMap:
    """Map for a named binary option section."""
    class_name: str           # e.g. "CAccessoryDevice"
    display_name: str         # e.g. "Accessory Device Options"
    data_size: int            # expected data payload size
    fields: List[FieldDef] = field(default_factory=list)

    @property
    def coverage(self):
        """Fraction of data bytes covered by field definitions."""
        if self.data_size == 0:
            return 0.0
        covered = set()
        for f in self.fields:
            for i in range(f.size):
                covered.add(f.offset + i)
        return len(covered) / self.data_size

    @property
    def unmapped_ranges(self):
        """Return list of (start, end) ranges not covered by fields."""
        mapped = set()
        for f in self.fields:
            for i in range(f.size):
                mapped.add(f.offset + i)
        ranges = []
        start = None
        for i in range(self.data_size):
            if i not in mapped:
                if start is None:
                    start = i
            else:
                if start is not None:
                    ranges.append((start, i))
                    start = None
        if start is not None:
            ranges.append((start, self.data_size))
        return ranges


def read_field(data, field_def):
    """Read a field value from binary data.

    Args:
        data: bytes of the data payload (after class header)
        field_def: FieldDef describing the field

    Returns the value (int, bool, or string for enums).
    """
    off = field_def.offset
    if off + field_def.size > len(data):
        return None

    if field_def.field_type == 'bool':
        return bool(data[off])
    elif field_def.field_type == 'uint8':
        return data[off]
    elif field_def.field_type == 'int8':
        v = data[off]
        return v if v < 128 else v - 256
    elif field_def.field_type == 'uint16':
        return data[off] | (data[off + 1] << 8)
    elif field_def.field_type == 'enum':
        raw = data[off]
        return field_def.enum_values.get(raw, f"UNKNOWN(0x{raw:02x})")
    elif field_def.field_type == 'double':
        if off + 8 > len(data):
            return None
        return struct.unpack_from('<d', data, off)[0]
    elif field_def.field_type == 'flags':
        return data[off]
    elif field_def.field_type == 'ipv4':
        if off + 4 > len(data):
            return None
        return f"{data[off]}.{data[off+1]}.{data[off+2]}.{data[off+3]}"
    return data[off]


def write_field(data, field_def, value):
    """Write a field value into binary data.

    Args:
        data: bytearray of the data payload
        field_def: FieldDef describing the field
        value: the value to write

    Returns the modified bytearray.
    """
    result = bytearray(data)
    off = field_def.offset

    if field_def.field_type == 'bool':
        result[off] = 0x01 if value else 0x00
    elif field_def.field_type in ('uint8', 'flags'):
        result[off] = int(value) & 0xFF
    elif field_def.field_type == 'int8':
        v = int(value)
        result[off] = v & 0xFF
    elif field_def.field_type == 'uint16':
        v = int(value)
        result[off] = v & 0xFF
        result[off + 1] = (v >> 8) & 0xFF
    elif field_def.field_type == 'double':
        struct.pack_into('<d', result, off, float(value))
    elif field_def.field_type == 'enum':
        # Value should be the raw int key
        if isinstance(value, int):
            result[off] = value & 0xFF
        else:
            # Reverse lookup
            for k, v in field_def.enum_values.items():
                if v == value:
                    result[off] = k & 0xFF
                    break
    elif field_def.field_type == 'ipv4':
        parts = str(value).split('.')
        for i, p in enumerate(parts[:4]):
            result[off + i] = int(p) & 0xFF
    return bytes(result)


def extract_section_data(section):
    """Extract the data payload from a named section (after class header).

    Returns bytes of just the data, or None if parsing fails.
    """
    from .record_types import parse_class_header
    try:
        _, _, _, data_start = parse_class_header(section.raw, 0)
        return section.raw[data_start:]
    except Exception as e:
        logger.debug("Failed to extract section data: %s", e)
        return None


# ─── CAccessoryDevice field map (8 data bytes) ──────────────────────
# Fully mapped via cumulative RPM "every option" diff files.
# All transitions confirmed: PTT mode, noise cancel, mic select,
# man-down sensitivity/warning/detection delays.
# Bytes 5-6 are static 0x00 in all 9 test samples (reserved).

ACCESSORY_DEVICE_MAP = OptionMap(
    class_name="CAccessoryDevice",
    display_name="Accessory Device Options",
    data_size=8,
    fields=[
        # Byte 0: PTT Mode — confirmed via "ptt mode - both to any" diff
        FieldDef(
            offset=0, size=1, name="ptt_mode",
            display_name="PTT Mode",
            field_type="enum",
            enum_values={0x00: "Both", 0x01: "Any"},
            description="PTT activation mode for accessories",
        ),
        # Byte 1: Noise Cancellation — confirmed via "noise cancelation - on to off"
        FieldDef(
            offset=1, size=1, name="noise_cancellation",
            display_name="Noise Cancellation",
            field_type="bool",
            description="Accessory noise cancellation on/off",
        ),
        # Byte 2: Mic Selection — confirmed via "Microphone selection - top to bottom"
        FieldDef(
            offset=2, size=1, name="mic_select",
            display_name="Microphone Selection",
            field_type="enum",
            enum_values={0x01: "Top", 0x02: "Bottom"},
            description="Which microphone to use",
        ),
        # Byte 3: Man Down Sensitivity — confirmed via off->low->med->high diffs
        FieldDef(
            offset=3, size=1, name="mandown_sensitivity",
            display_name="Man Down Sensitivity",
            field_type="enum",
            enum_values={0x00: "Off", 0x01: "Low", 0x03: "Medium",
                         0x05: "High"},
            description="Man Down tilt detection sensitivity",
        ),
        # Byte 4: Man Down Warning Delay — 0x1e (30) in all samples,
        #   matches XML manDownConfig warningTime="30"
        FieldDef(
            offset=4, size=1, name="mandown_warning_delay",
            display_name="Man Down Warning Delay",
            field_type="uint8",
            min_val=0, max_val=240,
            description="Seconds of warning before emergency (0-240)",
        ),
        # Bytes 5-6: reserved (0x00 in all 9 test samples)
        FieldDef(offset=5, size=1, name="acc_dev_rsv_5",
                 display_name="AccessoryDevice Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="acc_dev_rsv_6",
                 display_name="AccessoryDevice Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        # Byte 7: Man Down Detection Delay — confirmed via "detection delay 240 to 2"
        #   matches XML manDownConfig inactivityTime="240"
        FieldDef(
            offset=7, size=1, name="mandown_detection_delay",
            display_name="Man Down Detection Delay",
            field_type="uint8",
            min_val=0, max_val=240,
            description="Seconds before man-down alert triggers (0-240)",
        ),
    ],
)


@dataclass
class AccessoryDeviceOpts:
    """Parsed CAccessoryDevice binary section (8 data bytes).

    Fully mapped via cumulative RPM "every option" diff files.
    Maps to RPM Accessory Device Options and Man Down Configuration.
    """
    ptt_mode: int = 0             # 0=Both, 1=Any
    noise_cancellation: bool = True
    mic_select: int = 1           # 1=Top, 2=Bottom
    mandown_sensitivity: int = 0  # 0=Off, 1=Low, 3=Medium, 5=High
    mandown_warning_delay: int = 30   # 0-240 seconds
    reserved_5: int = 0
    reserved_6: int = 0
    mandown_detection_delay: int = 240  # 0-240 seconds

    @classmethod
    def from_bytes(cls, data):
        """Parse from 8 data bytes (after class header)."""
        if len(data) < 8:
            return cls()
        return cls(
            ptt_mode=data[0],
            noise_cancellation=bool(data[1]),
            mic_select=data[2],
            mandown_sensitivity=data[3],
            mandown_warning_delay=data[4],
            reserved_5=data[5],
            reserved_6=data[6],
            mandown_detection_delay=data[7],
        )

    def to_bytes(self):
        """Serialize to 8 data bytes."""
        return bytes([
            self.ptt_mode,
            1 if self.noise_cancellation else 0,
            self.mic_select,
            self.mandown_sensitivity,
            self.mandown_warning_delay,
            self.reserved_5,
            self.reserved_6,
            self.mandown_detection_delay,
        ])


# ─── CAlertOpts field map (19 data bytes) ────────────────────────────
# Class header: ffff 67 00 0a00 "CAlertOpts" (16 bytes) + 19 data = 35 total.
# Confirmed fields via cumulative RPM "every option" diff tests:
#   Byte  6: Ready to Talk Tone (PAWSOVERMAWS=1, 'RTT disabled'=0)
#   Byte 11: Initial OOR Alert Tone ('OOR enabled' changes 0->1)
#   Byte 17: Alternate Alert Tone ('alt alert enabled' changes 0->1)
#   Byte 18: VR Activation Tone ('VR act enabled' changes 0->1)
# Repeated OOR Interval is NOT in CAlertOpts (stored in blob preamble byte 6).
# Bytes 8,9,12,14 are always 0x01 across 8 test samples — likely default-on
# alert booleans for untested RPM checkboxes.

ALERT_OPTS_MAP = OptionMap(
    class_name="CAlertOpts",
    display_name="Alert Options",
    data_size=19,
    fields=[
        # Byte 0: ICall Minimum Ring Volume (greyed by default)
        FieldDef(
            offset=0, size=1, name="icall_min_ring_volume",
            display_name="ICall Min Ring Volume",
            field_type="uint8", min_val=0, max_val=40,
            description="Minimum ring volume for individual calls",
            conditional=True,
        ),
        # Byte 1: Minimum Alert Tone (greyed by default)
        FieldDef(
            offset=1, size=1, name="min_alert_tone",
            display_name="Minimum Alert Tone",
            field_type="uint8", min_val=0, max_val=40,
            description="Minimum alert tone volume level",
            conditional=True,
        ),
        # Byte 2: Maximum Alert Tone (default 0x64 = 100)
        FieldDef(
            offset=2, size=1, name="max_alert_tone",
            display_name="Maximum Alert Tone",
            field_type="uint8", min_val=0, max_val=100,
            description="Maximum alert tone volume level",
            conditional=True,
        ),
        # Bytes 3-5: reserved (0x00 in all 8 test samples)
        FieldDef(offset=3, size=1, name="alert_rsv_3",
                 display_name="AlertOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="alert_rsv_4",
                 display_name="AlertOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="alert_rsv_5",
                 display_name="AlertOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        # Byte 6: Ready to Talk Tone — confirmed via PAWSOVERMAWS (0x01=enabled)
        #   and "RTT enabled to disabled" test file (byte goes 0x01->0x00)
        FieldDef(
            offset=6, size=1, name="ready_to_talk_tone",
            display_name="Ready to Talk Tone",
            field_type="bool",
            description="Play tone when channel is available to transmit",
        ),
        # Byte 7: Receive Alert Tone — 0x00 in all samples (never toggled)
        FieldDef(
            offset=7, size=1, name="receive_alert_tone",
            display_name="Receive Alert Tone",
            field_type="bool",
            description="Alert on incoming call",
            conditional=True,
        ),
        # Byte 8: unknown bool — 0x01 in all 8 test samples (default true)
        FieldDef(
            offset=8, size=1, name="alert_bool_8",
            display_name="Alert Bool 8",
            field_type="bool",
            description="Alert boolean (default true, untoggled in test files)",
        ),
        # Byte 9: unknown bool — 0x01 in all 8 test samples (default true)
        FieldDef(
            offset=9, size=1, name="alert_bool_9",
            display_name="Alert Bool 9",
            field_type="bool",
            description="Alert boolean (default true, untoggled in test files)",
        ),
        # Byte 10: reserved (0x00 in all samples)
        FieldDef(offset=10, size=1, name="alert_rsv_10",
                 display_name="AlertOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        # Byte 11: Initial Out of Range Alert Tone — confirmed via "every option"
        #   diff ("inertial out of range - disabled to enabled" changes byte[11]
        #   0x00->0x01). PAWSOVERMAWS = 0x00 (unchecked).
        FieldDef(
            offset=11, size=1, name="initial_oor_alert_tone",
            display_name="Initial Out of Range Alert Tone",
            field_type="bool",
            description="Alert when radio initially goes out of range",
        ),
        # Byte 12: unknown bool — 0x01 in all 8 test samples (default true)
        FieldDef(
            offset=12, size=1, name="alert_bool_12",
            display_name="Alert Bool 12",
            field_type="bool",
            description="Alert boolean (default true, untoggled in test files)",
        ),
        # Byte 13: reserved (0x00 in all samples)
        FieldDef(offset=13, size=1, name="alert_rsv_13",
                 display_name="AlertOpts Reserved 13", field_type="uint8",
                 min_val=0, max_val=255),
        # Byte 14: unknown bool — 0x01 in all 8 test samples (default true)
        FieldDef(
            offset=14, size=1, name="alert_bool_14",
            display_name="Alert Bool 14",
            field_type="bool",
            description="Alert boolean (default true, untoggled in test files)",
        ),
        # Bytes 15-16: reserved (0x00 in all samples)
        FieldDef(offset=15, size=1, name="alert_rsv_15",
                 display_name="AlertOpts Reserved 15", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="alert_rsv_16",
                 display_name="AlertOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
        # Byte 17: Alternate Alert Tone — confirmed via "alt alert enabled" diff
        FieldDef(
            offset=17, size=1, name="alternate_alert_tone",
            display_name="Alternate Alert Tone",
            field_type="bool",
            description="Use alternate alert tone pattern",
        ),
        # Byte 18: VR Activation Tone — confirmed via "VR act enabled" diff
        FieldDef(
            offset=18, size=1, name="vr_activation_tone",
            display_name="VR Activation Tone",
            field_type="bool",
            description="Play tone on voice recognition activation",
        ),
    ],
)


@dataclass
class AlertOpts:
    """Parsed CAlertOpts binary section (19 data bytes).

    Class header: ffff 6700 0a00 "CAlertOpts" (16 bytes) + 19 data = 35 total.
    Confirmed fields via cumulative RPM "every option" toggle tests.
    Repeated OOR Interval is NOT in this section (stored in blob preamble).
    """
    icall_min_ring_volume: int = 0    # 0-40, conditional
    min_alert_tone: int = 0           # 0-40, conditional
    max_alert_tone: int = 100         # 0-100
    reserved_3: int = 0
    reserved_4: int = 0
    reserved_5: int = 0
    ready_to_talk_tone: bool = False  # confirmed: byte 6
    receive_alert_tone: bool = False  # byte 7 (never toggled in tests)
    alert_bool_8: bool = True         # default true in all samples
    alert_bool_9: bool = True         # default true in all samples
    reserved_10: int = 0
    initial_oor_alert_tone: bool = False  # confirmed: byte 11
    alert_bool_12: bool = True        # default true in all samples
    reserved_13: int = 0
    alert_bool_14: bool = True        # default true in all samples
    reserved_15: int = 0
    reserved_16: int = 0
    alternate_alert_tone: bool = False  # confirmed: byte 17
    vr_activation_tone: bool = False    # confirmed: byte 18

    @classmethod
    def from_bytes(cls, data):
        """Parse from 19 data bytes (after class header)."""
        if len(data) < 19:
            return cls()
        return cls(
            icall_min_ring_volume=data[0],
            min_alert_tone=data[1],
            max_alert_tone=data[2],
            reserved_3=data[3],
            reserved_4=data[4],
            reserved_5=data[5],
            ready_to_talk_tone=bool(data[6]),
            receive_alert_tone=bool(data[7]),
            alert_bool_8=bool(data[8]),
            alert_bool_9=bool(data[9]),
            reserved_10=data[10],
            initial_oor_alert_tone=bool(data[11]),
            alert_bool_12=bool(data[12]),
            reserved_13=data[13],
            alert_bool_14=bool(data[14]),
            reserved_15=data[15],
            reserved_16=data[16],
            alternate_alert_tone=bool(data[17]),
            vr_activation_tone=bool(data[18]),
        )

    def to_bytes(self):
        """Serialize to 19 data bytes."""
        return bytes([
            self.icall_min_ring_volume,
            self.min_alert_tone,
            self.max_alert_tone,
            self.reserved_3,
            self.reserved_4,
            self.reserved_5,
            1 if self.ready_to_talk_tone else 0,
            1 if self.receive_alert_tone else 0,
            1 if self.alert_bool_8 else 0,
            1 if self.alert_bool_9 else 0,
            self.reserved_10,
            1 if self.initial_oor_alert_tone else 0,
            1 if self.alert_bool_12 else 0,
            self.reserved_13,
            1 if self.alert_bool_14 else 0,
            self.reserved_15,
            self.reserved_16,
            1 if self.alternate_alert_tone else 0,
            1 if self.vr_activation_tone else 0,
        ])


# ─── CGenRadioOpts field map (41 data bytes) ────────────────────────
# Maps to the "General Options" dialog in RPM.
# Only present in files where General Options were modified (e.g. PAWSOVERMAWS).
# Bytes 0-12 appear to be boolean/enum fields for General Options checkboxes;
# exact mapping TBD (only one sample file available for diffing).
# Bytes 13-16 confirmed as EDACS LID ranges via RPM screenshot cross-reference.
# Bytes 17-40 include additional fields (IP/P25 LIDs stored in separate unnamed
# section, not here).

GEN_RADIO_OPTS_MAP = OptionMap(
    class_name="CGenRadioOpts",
    display_name="General Radio Options",
    data_size=41,
    fields=[
        FieldDef(
            offset=0, size=1, name="npspac_override",
            display_name="Override Default NPSPAC Channel Assignments",
            field_type="bool",
            description="Override default NPSPAC channel assignments",
        ),
        # Bytes 1-2: General Options dialog booleans — all unchecked in PAWSOVERMAWS
        # Order from dialog may not exactly match byte order
        FieldDef(offset=1, size=1, name="gr_bool_1",
                 display_name="Gen Radio Bool 1", field_type="bool",
                 description="General Options boolean (unchecked in PAWSOVERMAWS)"),
        FieldDef(offset=2, size=1, name="gr_bool_2",
                 display_name="Gen Radio Bool 2", field_type="bool",
                 description="General Options boolean (unchecked in PAWSOVERMAWS)"),
        FieldDef(
            offset=3, size=1, name="noise_cancellation_type",
            display_name="Noise Cancellation Type",
            field_type="enum",
            enum_values={0x00: "Method B", 0x01: "Method A"},
            description="Noise cancellation algorithm method",
        ),
        # Bytes 4-12: General Options dialog booleans — all unchecked in PAWSOVERMAWS
        FieldDef(offset=4, size=1, name="gr_bool_4",
                 display_name="Gen Radio Bool 4", field_type="bool"),
        FieldDef(offset=5, size=1, name="gr_bool_5",
                 display_name="Gen Radio Bool 5", field_type="bool"),
        FieldDef(offset=6, size=1, name="gr_bool_6",
                 display_name="Gen Radio Bool 6", field_type="bool"),
        FieldDef(offset=7, size=1, name="gr_bool_7",
                 display_name="Gen Radio Bool 7", field_type="bool"),
        FieldDef(offset=8, size=1, name="gr_bool_8",
                 display_name="Gen Radio Bool 8", field_type="bool"),
        FieldDef(offset=9, size=1, name="gr_bool_9",
                 display_name="Gen Radio Bool 9", field_type="bool"),
        FieldDef(offset=10, size=1, name="gr_bool_10",
                 display_name="Gen Radio Bool 10", field_type="bool"),
        FieldDef(offset=11, size=1, name="gr_bool_11",
                 display_name="Gen Radio Bool 11", field_type="bool"),
        FieldDef(offset=12, size=1, name="gr_bool_12",
                 display_name="Gen Radio Bool 12", field_type="bool"),

        # EDACS LID range — confirmed via RPM screenshot (16382 = 0x3FFE)
        FieldDef(
            offset=13, size=2, name="edacs_min_lid",
            display_name="EDACS Minimum LID",
            field_type="uint16",
            min_val=1, max_val=16382,
            description="Minimum Logical ID for EDACS systems",
        ),
        FieldDef(
            offset=15, size=2, name="edacs_max_lid",
            display_name="EDACS Maximum LID",
            field_type="uint16",
            min_val=1, max_val=16382,
            description="Maximum Logical ID for EDACS systems",
        ),

        # Bytes 17-40: additional fields
        FieldDef(
            offset=19, size=1, name="gen_radio_byte_19",
            display_name="Gen Radio Byte 19",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown general radio parameter (0xA0/160 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=30, size=1, name="gen_radio_byte_30",
            display_name="Gen Radio Byte 30",
            field_type="bool",
            description="Unknown general radio boolean (True in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=33, size=1, name="gen_radio_byte_33",
            display_name="Gen Radio Byte 33",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown general radio parameter (10 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=37, size=1, name="gen_radio_byte_37",
            display_name="Gen Radio Byte 37",
            field_type="bool",
            description="Unknown general radio boolean (True in PAWSOVERMAWS)",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=17, size=1, name="gen_radio_rsv_17",
                 display_name="GenRadioOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="gen_radio_rsv_18",
                 display_name="GenRadioOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="gen_radio_rsv_20",
                 display_name="GenRadioOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=21, size=1, name="gen_radio_rsv_21",
                 display_name="GenRadioOpts Reserved 21", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="gen_radio_rsv_22",
                 display_name="GenRadioOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="gen_radio_rsv_23",
                 display_name="GenRadioOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="gen_radio_rsv_24",
                 display_name="GenRadioOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="gen_radio_rsv_25",
                 display_name="GenRadioOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="gen_radio_rsv_26",
                 display_name="GenRadioOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="gen_radio_rsv_27",
                 display_name="GenRadioOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="gen_radio_rsv_28",
                 display_name="GenRadioOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="gen_radio_rsv_29",
                 display_name="GenRadioOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="gen_radio_rsv_31",
                 display_name="GenRadioOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="gen_radio_rsv_32",
                 display_name="GenRadioOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="gen_radio_rsv_34",
                 display_name="GenRadioOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="gen_radio_rsv_35",
                 display_name="GenRadioOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=36, size=1, name="gen_radio_rsv_36",
                 display_name="GenRadioOpts Reserved 36", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=38, size=1, name="gen_radio_rsv_38",
                 display_name="GenRadioOpts Reserved 38", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=39, size=1, name="gen_radio_rsv_39",
                 display_name="GenRadioOpts Reserved 39", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=40, size=1, name="gen_radio_rsv_40",
                 display_name="GenRadioOpts Reserved 40", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CDTMFOpts field map (56 data bytes) ──────────────────────────────
# Maps to the "DTMF Options" dialog in RPM.
# Layout: 4-byte prefix (flags/enums) + 6 IEEE 754 doubles + 4-byte suffix.
# All 6 doubles confirmed via cross-reference with RPM screenshot values.

DTMF_OPTS_MAP = OptionMap(
    class_name="CDTMFOpts",
    display_name="DTMF Options",
    data_size=56,
    fields=[
        FieldDef(
            offset=0, size=1, name="no_pre_emphasis_filter",
            display_name="No Pre-Emphasis Filter",
            field_type="bool",
            description="Disable pre-emphasis filter on DTMF tones",
        ),
        # Byte 1: 0x00 — unknown/reserved
        FieldDef(
            offset=2, size=1, name="side_tone",
            display_name="Side Tone",
            field_type="enum",
            enum_values={0x01: "Muted", 0x02: "Audible"},
            description="DTMF side tone audibility",
        ),
        # Byte 3: 0x00 — unknown/reserved
        FieldDef(
            offset=4, size=8, name="start_delay",
            display_name="Start Delay",
            field_type="double",
            description="DTMF start delay in milliseconds",
        ),
        FieldDef(
            offset=12, size=8, name="pause_delay",
            display_name="Pause Delay",
            field_type="double",
            description="DTMF pause delay in milliseconds",
        ),
        FieldDef(
            offset=20, size=8, name="interdigit_delay",
            display_name="Interdigit Delay",
            field_type="double",
            description="Delay between DTMF digits in milliseconds",
        ),
        FieldDef(
            offset=28, size=8, name="hang_delay",
            display_name="Hang Delay",
            field_type="double",
            description="DTMF hang delay in milliseconds",
        ),
        FieldDef(
            offset=36, size=8, name="tone_length_0_9",
            display_name="0-9 Tone Length",
            field_type="double",
            description="Tone length for digits 0-9 in milliseconds",
        ),
        FieldDef(
            offset=44, size=8, name="tone_length_star_hash",
            display_name="* # Tone Length",
            field_type="double",
            description="Tone length for * and # keys in milliseconds",
        ),
        # Bytes 52-55: 0x00000000 — reserved/unused

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=1, size=1, name="dtmf_rsv_1",
                 display_name="DTMFOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="dtmf_rsv_3",
                 display_name="DTMFOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=52, size=1, name="dtmf_rsv_52",
                 display_name="DTMFOpts Reserved 52", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=53, size=1, name="dtmf_rsv_53",
                 display_name="DTMFOpts Reserved 53", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=54, size=1, name="dtmf_rsv_54",
                 display_name="DTMFOpts Reserved 54", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=55, size=1, name="dtmf_rsv_55",
                 display_name="DTMFOpts Reserved 55", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CTimerOpts field map (82 data bytes) ─────────────────────────────
# Maps to the "Timer Options" dialog in RPM.
# Layout: 4-byte prefix + 9 IEEE 754 doubles (72 bytes) + 6-byte suffix.
# CCT (60.0) at offset 52 confirmed. Three fields at 10.0 (offsets 20, 28, 36)
# are Phone Entry Mode, ICall Timeout, and ICall Entry Mode — exact assignment
# order needs second sample to confirm. The 1.0 at offset 12 is unidentified.

TIMER_OPTS_MAP = OptionMap(
    class_name="CTimerOpts",
    display_name="Timer Options",
    data_size=82,
    fields=[
        # Bytes 0-3: prefix flags (all 0x00 in PAWSOVERMAWS)
        FieldDef(offset=0, size=1, name="timer_prefix_0",
                 display_name="Timer Prefix 0", field_type="uint8", min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="timer_prefix_1",
                 display_name="Timer Prefix 1", field_type="uint8", min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="timer_prefix_2",
                 display_name="Timer Prefix 2", field_type="uint8", min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="timer_prefix_3",
                 display_name="Timer Prefix 3", field_type="uint8", min_val=0, max_val=255),
        FieldDef(
            offset=4, size=8, name="priority_call_timeout",
            display_name="Priority Call Timeout",
            field_type="double",
            description="Priority call timeout in seconds",
        ),
        FieldDef(
            offset=12, size=8, name="timer_field_12",
            display_name="Timer Field 12",
            field_type="double",
            description="Unidentified timer double (1.0 in PAWSOVERMAWS)",
        ),
        # Offsets 20, 28, 36: all 10.0 — these correspond to Phone Entry Mode,
        # ICall Timeout, and ICall Entry Mode (all 10.0 in PAWSOVERMAWS).
        # Exact offset-to-field mapping uncertain; listed in dialog order.
        FieldDef(
            offset=20, size=8, name="phone_entry_mode",
            display_name="Phone Entry Mode",
            field_type="double",
            description="Phone entry mode timeout in seconds",
        ),
        FieldDef(
            offset=28, size=8, name="icall_timeout",
            display_name="ICall Timeout",
            field_type="double",
            description="Individual call timeout in seconds",
        ),
        FieldDef(
            offset=36, size=8, name="icall_entry_mode",
            display_name="ICall Entry Mode",
            field_type="double",
            description="ICall entry mode timeout in seconds",
        ),
        # Offset 44: double = 0.0 (another 0-value timer field)
        FieldDef(
            offset=44, size=8, name="cc_scan_delay_timer",
            display_name="CC SCAN Delay Timer",
            field_type="double",
            description="CC scan delay timer in seconds",
        ),
        FieldDef(
            offset=52, size=8, name="cct",
            display_name="CCT",
            field_type="double",
            description="CCT timeout in seconds (60.0 confirmed)",
        ),
        # Offset 60: NOT a standard double — only byte[63] is non-zero
        FieldDef(
            offset=63, size=1, name="timer_byte_63",
            display_name="Timer Byte 63",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown timer parameter (30/0x1E in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=68, size=8, name="vote_scan_hangtime",
            display_name="Vote Scan HangTime",
            field_type="double",
            description="Vote scan hang time in seconds",
        ),
        # Bytes 76-81: remaining bytes (6 bytes, 0x00 in PAWSOVERMAWS)

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=60, size=1, name="timer_rsv_60",
                 display_name="TimerOpts Reserved 60", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=61, size=1, name="timer_rsv_61",
                 display_name="TimerOpts Reserved 61", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=62, size=1, name="timer_rsv_62",
                 display_name="TimerOpts Reserved 62", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=64, size=1, name="timer_rsv_64",
                 display_name="TimerOpts Reserved 64", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=65, size=1, name="timer_rsv_65",
                 display_name="TimerOpts Reserved 65", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=66, size=1, name="timer_rsv_66",
                 display_name="TimerOpts Reserved 66", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=67, size=1, name="timer_rsv_67",
                 display_name="TimerOpts Reserved 67", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=76, size=1, name="timer_rsv_76",
                 display_name="TimerOpts Reserved 76", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=77, size=1, name="timer_rsv_77",
                 display_name="TimerOpts Reserved 77", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=78, size=1, name="timer_rsv_78",
                 display_name="TimerOpts Reserved 78", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=79, size=1, name="timer_rsv_79",
                 display_name="TimerOpts Reserved 79", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=80, size=1, name="timer_rsv_80",
                 display_name="TimerOpts Reserved 80", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=81, size=1, name="timer_rsv_81",
                 display_name="TimerOpts Reserved 81", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CSupervisoryOpts field map (36 data bytes) ──────────────────────
# Maps to the "Supervisory Options" dialog in RPM.
# Layout: 4 IEEE 754 doubles (32 bytes) + 4-byte suffix.
# Emergency Key Delay (1.0) at offset 8 confirmed via dialog screenshot.
# Other doubles are 0.0 (Emergency Autokey Timeout, Emergency Autocycle Timeout).

SUPERVISORY_OPTS_MAP = OptionMap(
    class_name="CSupervisoryOpts",
    display_name="Supervisory Options",
    data_size=36,
    fields=[
        FieldDef(
            offset=0, size=8, name="supervisory_double_0",
            display_name="Supervisory Double 0",
            field_type="double",
            description="Unidentified supervisory double (0.0 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=8, size=8, name="emergency_key_delay",
            display_name="Emergency Key Delay",
            field_type="double",
            description="Emergency key delay in seconds",
        ),
        FieldDef(
            offset=16, size=8, name="emergency_autokey_timeout",
            display_name="Emergency Autokey Timeout",
            field_type="double",
            description="Emergency autokey timeout in seconds",
        ),
        FieldDef(
            offset=24, size=8, name="emergency_autocycle_timeout",
            display_name="Emergency Autocycle Timeout",
            field_type="double",
            description="Emergency autocycle timeout in seconds",
        ),
        # Bytes 32-35: 0x00000000 — reserved/unused

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=32, size=1, name="supv_rsv_32",
                 display_name="SupervisoryOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="supv_rsv_33",
                 display_name="SupervisoryOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="supv_rsv_34",
                 display_name="SupervisoryOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="supv_rsv_35",
                 display_name="SupervisoryOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CPowerUpOpts field map (36 data bytes) ───────────────────────────
# Maps to the "Power Up Options" dialog in RPM.
# Contains power-up state, squelch, contrast, PIN settings, and many booleans.
# Most checkboxes are unchecked (0) in PAWSOVERMAWS making blind mapping hard.
# Two numeric fields confirmed via value cross-reference.

POWER_UP_OPTS_MAP = OptionMap(
    class_name="CPowerUpOpts",
    display_name="Power Up Options",
    data_size=36,
    fields=[
        FieldDef(
            offset=0, size=1, name="power_up_selection",
            display_name="Power Up Selection",
            field_type="enum",
            enum_values={0x00: "Default", 0x01: "System/Group", 0x02: "Zone/Group"},
            description="Power-up system/zone selection mode",
        ),
        # Bytes 1-10: Power Up Options dialog booleans — all unchecked in PAWSOVERMAWS
        FieldDef(offset=1, size=1, name="pu_ignore_ab_switch",
                 display_name="Ignore AB Switch", field_type="bool"),
        FieldDef(offset=2, size=1, name="pu_contrast",
                 display_name="Contrast", field_type="bool"),
        FieldDef(offset=3, size=1, name="pu_keypad_lock",
                 display_name="Keypad Lock", field_type="bool"),
        FieldDef(offset=4, size=1, name="pu_keypad_state",
                 display_name="Keypad State", field_type="bool"),
        FieldDef(offset=5, size=1, name="pu_edacs_auto_login",
                 display_name="EDACS/EDACS IP Auto Login", field_type="bool"),
        FieldDef(offset=6, size=1, name="pu_squelch",
                 display_name="Squelch", field_type="bool"),
        FieldDef(offset=7, size=1, name="pu_external_alarm",
                 display_name="External Alarm", field_type="bool"),
        FieldDef(offset=8, size=1, name="pu_scan",
                 display_name="Scan", field_type="bool"),
        FieldDef(offset=9, size=1, name="pu_audible_tone",
                 display_name="Audible Tone", field_type="bool"),
        FieldDef(offset=10, size=1, name="pu_private_mode",
                 display_name="Private Mode", field_type="bool"),
        FieldDef(
            offset=11, size=1, name="power_up_byte_11",
            display_name="Power Up Byte 11",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown power-up parameter (15 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=13, size=1, name="power_up_byte_13",
            display_name="Power Up Byte 13",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown power-up parameter (3 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=20, size=1, name="power_up_byte_20",
            display_name="Power Up Byte 20",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown power-up parameter (40 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=22, size=1, name="power_up_byte_22",
            display_name="Power Up Byte 22",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown power-up parameter (6 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=24, size=1, name="squelch_level",
            display_name="Squelch Level",
            field_type="uint8", min_val=0, max_val=15,
            description="Default squelch level at power-up (0-15)",
        ),
        FieldDef(
            offset=30, size=1, name="max_bad_pin_entries",
            display_name="Maximum # Bad Entries",
            field_type="uint8", min_val=0, max_val=255,
            description="Maximum incorrect PIN entries before lockout",
        ),
        # Byte 20: 0x28 (40) — unknown
        # Byte 22: 0x06 (6) — unknown

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=12, size=1, name="pu_rsv_12",
                 display_name="PowerUpOpts Reserved 12", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="pu_rsv_14",
                 display_name="PowerUpOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=15, size=1, name="pu_rsv_15",
                 display_name="PowerUpOpts Reserved 15", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="pu_rsv_16",
                 display_name="PowerUpOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=17, size=1, name="pu_rsv_17",
                 display_name="PowerUpOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="pu_rsv_18",
                 display_name="PowerUpOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=19, size=1, name="pu_rsv_19",
                 display_name="PowerUpOpts Reserved 19", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=21, size=1, name="pu_rsv_21",
                 display_name="PowerUpOpts Reserved 21", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="pu_rsv_23",
                 display_name="PowerUpOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="pu_rsv_25",
                 display_name="PowerUpOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="pu_rsv_26",
                 display_name="PowerUpOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="pu_rsv_27",
                 display_name="PowerUpOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="pu_rsv_28",
                 display_name="PowerUpOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="pu_rsv_29",
                 display_name="PowerUpOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="pu_rsv_31",
                 display_name="PowerUpOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="pu_rsv_32",
                 display_name="PowerUpOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="pu_rsv_33",
                 display_name="PowerUpOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="pu_rsv_34",
                 display_name="PowerUpOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="pu_rsv_35",
                 display_name="PowerUpOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CScanOpts field map (33 data bytes) ──────────────────────────────
# Maps to the "Scan Options" dialog in RPM.
# Contains conventional scan, trunked scan, and universal scan settings.
# Booleans at bytes 2,4 match checked boxes. Conv Pri Scan Hang Time and
# Band Hunt Interval confirmed at bytes 29 and 32.

SCAN_OPTS_MAP = OptionMap(
    class_name="CScanOpts",
    display_name="Scan Options",
    data_size=33,
    fields=[
        FieldDef(
            offset=0, size=1, name="scan_with_channel_guard",
            display_name="Scan With Channel Guard",
            field_type="bool",
            description="Scan with channel guard enabled",
        ),
        FieldDef(
            offset=1, size=1, name="alternate_scan",
            display_name="Alternate Scan",
            field_type="bool",
            description="Enable alternate scan mode",
        ),
        FieldDef(
            offset=2, size=1, name="always_scan_selected_chan",
            display_name="Always Scan Selected Channel",
            field_type="bool",
            description="Always include selected channel in scan list",
        ),
        FieldDef(
            offset=3, size=1, name="conv_pri_scan_with_cg",
            display_name="Conv Pri Scan With CG",
            field_type="bool",
            description="Conventional priority scan with channel guard",
        ),
        FieldDef(
            offset=4, size=1, name="scan_after_ptt",
            display_name="Scan After PTT",
            field_type="bool",
            description="Resume scan after PTT release",
        ),
        # Bytes 5-10: trunked/universal scan settings (enums, lockout values)
        FieldDef(
            offset=11, size=8, name="universal_hang_time",
            display_name="Universal Hang Time",
            field_type="double",
            description="Universal scan hang time in seconds",
        ),
        FieldDef(
            offset=19, size=1, name="scan_byte_19",
            display_name="Scan Byte 19",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown scan parameter (0x40/64 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=29, size=1, name="conv_pri_scan_hang_time",
            display_name="Conv Pri Scan Hang Time",
            field_type="uint8", min_val=0, max_val=255,
            description="Conventional priority scan hang time in seconds",
        ),
        # Bytes 30-31: reserved
        FieldDef(
            offset=32, size=1, name="band_hunt_interval",
            display_name="Band Hunt Interval",
            field_type="uint8", min_val=0, max_val=255,
            description="Band hunt interval in seconds",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=5, size=1, name="scan_rsv_5",
                 display_name="ScanOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="scan_rsv_6",
                 display_name="ScanOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="scan_rsv_7",
                 display_name="ScanOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="scan_rsv_8",
                 display_name="ScanOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="scan_rsv_9",
                 display_name="ScanOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="scan_rsv_10",
                 display_name="ScanOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="scan_rsv_20",
                 display_name="ScanOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=21, size=1, name="scan_rsv_21",
                 display_name="ScanOpts Reserved 21", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="scan_rsv_22",
                 display_name="ScanOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="scan_rsv_23",
                 display_name="ScanOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="scan_rsv_24",
                 display_name="ScanOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="scan_rsv_25",
                 display_name="ScanOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="scan_rsv_26",
                 display_name="ScanOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="scan_rsv_27",
                 display_name="ScanOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="scan_rsv_28",
                 display_name="ScanOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=30, size=1, name="scan_rsv_30",
                 display_name="ScanOpts Reserved 30", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="scan_rsv_31",
                 display_name="ScanOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CDiagnosticOpts field map (8 data bytes) ─────────────────────────
# Maps to the "Diagnostic Options" dialog in RPM.
# Very small section. IP Echo is the only enabled option in PAWSOVERMAWS.

DIAGNOSTIC_OPTS_MAP = OptionMap(
    class_name="CDiagnosticOpts",
    display_name="Diagnostic Options",
    data_size=8,
    fields=[
        # Bytes 0-6: Diagnostic dialog fields — all defaults/off in PAWSOVERMAWS
        FieldDef(offset=0, size=1, name="diagnostic_mode",
                 display_name="Diagnostic Mode", field_type="bool",
                 description="Enable diagnostic mode"),
        FieldDef(offset=1, size=1, name="system_diagnostic_mode",
                 display_name="System Diagnostic Mode", field_type="bool",
                 description="Enable system diagnostic mode"),
        FieldDef(offset=2, size=1, name="diag_baud_rate",
                 display_name="Baud Rate", field_type="uint8", min_val=0, max_val=255,
                 description="Diagnostic baud rate setting"),
        FieldDef(offset=3, size=1, name="diag_bits_per_char",
                 display_name="Bits Per Character", field_type="uint8", min_val=0, max_val=255,
                 description="Diagnostic bits per character"),
        FieldDef(offset=4, size=1, name="diag_stop_bits",
                 display_name="Stop Bits", field_type="uint8", min_val=0, max_val=255,
                 description="Diagnostic stop bits"),
        FieldDef(offset=5, size=1, name="diag_parity",
                 display_name="Parity", field_type="uint8", min_val=0, max_val=255,
                 description="Diagnostic parity setting"),
        FieldDef(offset=6, size=1, name="diag_byte_6",
                 display_name="Diagnostic Byte 6", field_type="uint8", min_val=0, max_val=255,
                 description="Unknown diagnostic parameter"),
        FieldDef(
            offset=7, size=1, name="ip_echo",
            display_name="IP Echo",
            field_type="bool",
            description="Enable IP echo diagnostic mode",
        ),
    ],
)


# ─── CMdcOpts field map (24 data bytes) ─────────────────────────────
# Maps to the "Signaling Options" dialog in RPM (MDC Options + Enhanced ID tabs).
# Cross-referenced with PAWSOVERMAWS screenshots.

MDC_OPTS_MAP = OptionMap(
    class_name="CMdcOpts",
    display_name="Signaling Options",
    data_size=24,
    fields=[
        # Bytes 0-1: likely Sidetone enum (value 0 = "Long" in PAWSOVERMAWS)
        FieldDef(
            offset=2, size=1, name="mdc_encode_trigger",
            display_name="MDC Encode Trigger",
            field_type="enum",
            enum_values={0x00: "None", 0x01: "PTT Press"},
            description="MDC encode trigger mode",
        ),
        # Byte 3: 0x00
        FieldDef(
            offset=4, size=1, name="send_preamble_during_pretime",
            display_name="Send Preamble During Pre-time",
            field_type="bool",
            description="Send MDC preamble during system pre-time",
        ),
        # Byte 5: unknown
        FieldDef(
            offset=6, size=1, name="mdc_emergency_enable",
            display_name="MDC Emergency Enable",
            field_type="bool",
            description="Enable MDC emergency signaling",
        ),
        FieldDef(
            offset=7, size=2, name="system_pretime",
            display_name="System Pre-time",
            field_type="uint16", min_val=0, max_val=9999,
            description="MDC system pre-time in milliseconds",
        ),
        FieldDef(
            offset=9, size=2, name="interpacket_delay",
            display_name="Interpacket Delay",
            field_type="uint16", min_val=0, max_val=9999,
            description="MDC interpacket delay in milliseconds",
        ),
        FieldDef(
            offset=12, size=1, name="mdc_bool_12",
            display_name="Signaling Bool 12",
            field_type="bool",
            description="Unknown signaling boolean (True in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=13, size=1, name="mdc_emergency_ack_tone",
            display_name="MDC Emergency ACK Tone",
            field_type="bool",
            description="Play ACK tone on MDC emergency acknowledgment",
        ),
        FieldDef(
            offset=14, size=1, name="mdc_hang_time",
            display_name="MDC Hang Time",
            field_type="uint8", min_val=0, max_val=255,
            description="MDC hang time in seconds",
        ),
        FieldDef(
            offset=15, size=1, name="enhanced_id_encode_trigger",
            display_name="Enhanced ID Encode Trigger",
            field_type="enum",
            enum_values={0x00: "None", 0x01: "PTT Press"},
            description="Enhanced ID encode trigger mode",
        ),
        # Byte 16: unknown
        FieldDef(
            offset=17, size=2, name="enhanced_id_system_pretime",
            display_name="Enhanced ID System Pre-time",
            field_type="uint16", min_val=0, max_val=9999,
            description="Enhanced ID system pre-time in milliseconds",
        ),
        FieldDef(
            offset=19, size=1, name="enhanced_id_hang_time",
            display_name="Enhanced ID Hang Time",
            field_type="uint8", min_val=0, max_val=255,
            description="Enhanced ID hang time in seconds",
        ),
        FieldDef(
            offset=20, size=1, name="emergency_tone_volume",
            display_name="Emergency Tone Volume",
            field_type="uint8", min_val=0, max_val=31,
            description="Emergency tone volume level (0-31)",
        ),
        FieldDef(
            offset=21, size=1, name="emergency_max_tx_power",
            display_name="Emergency Max Tx Power",
            field_type="bool",
            description="Use maximum TX power during emergency",
        ),
        FieldDef(
            offset=22, size=1, name="enhanced_emergency_ack_tone",
            display_name="Emergency ACK Tone",
            field_type="bool",
            description="Play ACK tone on Enhanced ID emergency acknowledgment",
        ),
        FieldDef(
            offset=23, size=1, name="alternate_alert_tone",
            display_name="Alternate Alert Tone",
            field_type="bool",
            description="Use alternate emergency alert tone",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="mdc_rsv_0",
                 display_name="MdcOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="mdc_rsv_1",
                 display_name="MdcOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="mdc_rsv_3",
                 display_name="MdcOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="mdc_rsv_5",
                 display_name="MdcOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="mdc_rsv_11",
                 display_name="MdcOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="mdc_rsv_16",
                 display_name="MdcOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CSecurityPolicy field map (2 data bytes) ──────────────────────
# Maps to the "Security Policy" dialog in RPM.
# Both checkboxes checked in PAWSOVERMAWS. 100% mapped.

SECURITY_POLICY_MAP = OptionMap(
    class_name="CSecurityPolicy",
    display_name="Security Policy",
    data_size=2,
    fields=[
        FieldDef(
            offset=0, size=1, name="k_erasure_unit_disable",
            display_name="K Erasure on Unit Disable",
            field_type="bool",
            description="Enable K (Authentication Key) erasure on unit disable",
        ),
        FieldDef(
            offset=1, size=1, name="k_erasure_zeroize",
            display_name="K Erasure on Zeroize",
            field_type="bool",
            description="Enable K (Authentication Key) erasure on zeroize",
        ),
    ],
)


# ─── CStatus field map (7 data bytes) ──────────────────────────────
# Maps to the "Status/Message Options" dialog in RPM.
# Mode Hang Time=10, Select Time=2, Transmit Type=AUTO,
# Reset on System Change=checked in PAWSOVERMAWS.

STATUS_OPTS_MAP = OptionMap(
    class_name="CStatus",
    display_name="Status/Message Options",
    data_size=7,
    fields=[
        # Bytes 0-1: unknown (possibly related to Status # and Message # lists)
        FieldDef(
            offset=2, size=1, name="mode_hang_time",
            display_name="Mode Hang Time",
            field_type="uint8", min_val=0, max_val=255,
            description="Status/message mode hang time in seconds",
        ),
        FieldDef(
            offset=3, size=1, name="select_time",
            display_name="Select Time",
            field_type="uint8", min_val=0, max_val=255,
            description="Status/message select time in seconds",
        ),
        FieldDef(
            offset=4, size=1, name="transmit_type",
            display_name="Transmit Type",
            field_type="enum",
            enum_values={0x00: "AUTO", 0x01: "Manual"},
            description="Status/message transmit type",
        ),
        FieldDef(
            offset=5, size=1, name="reset_on_system_change",
            display_name="Reset on System Change",
            field_type="bool",
            description="Reset status/message on system change",
        ),
        FieldDef(
            offset=6, size=1, name="p25_standard_status_format",
            display_name="P25 Standard Status Format",
            field_type="bool",
            description="Use P25 standard status format",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="status_rsv_0",
                 display_name="Status Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="status_rsv_1",
                 display_name="Status Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CSystemScanOpts field map (24 data bytes) ─────────────────────
# Maps to the "System Scan Options" dialog in RPM.
# Scan Type=ProScan, CC Loop Count=2, Priority Scan=checked in PAWSOVERMAWS.

SYSTEM_SCAN_OPTS_MAP = OptionMap(
    class_name="CSystemScanOpts",
    display_name="System Scan Options",
    data_size=24,
    fields=[
        FieldDef(
            offset=0, size=1, name="scan_type",
            display_name="Scan Type",
            field_type="enum",
            enum_values={0x00: "Standard", 0x01: "ProScan"},
            description="System scan type (Standard or ProScan)",
        ),
        FieldDef(
            offset=1, size=1, name="priority_scan",
            display_name="Priority Scan",
            field_type="bool",
            description="Enable priority system scanning",
        ),
        FieldDef(
            offset=2, size=1, name="tone_suppress",
            display_name="Tone Suppress",
            field_type="bool",
            description="Suppress tones during system scan",
        ),
        FieldDef(
            offset=5, size=1, name="sys_scan_byte_5",
            display_name="System Scan Byte 5",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown system scan parameter (98/0x62 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=6, size=1, name="sys_scan_byte_6",
            display_name="System Scan Byte 6",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown system scan parameter (3 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=7, size=8, name="cc_loop_count",
            display_name="CC Loop Count",
            field_type="double",
            description="Control channel loop count",
        ),
        FieldDef(
            offset=15, size=8, name="priority_scan_time",
            display_name="Priority Scan Time",
            field_type="double",
            description="Priority scan time in seconds",
        ),
        # Byte 23: unknown

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=3, size=1, name="sys_scan_rsv_3",
                 display_name="SystemScanOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="sys_scan_rsv_4",
                 display_name="SystemScanOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="sys_scan_rsv_23",
                 display_name="SystemScanOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CVoiceAnnunciation field map (12 data bytes) ──────────────────
# Maps to the "Voice Annunciation" dialog in RPM.
# All booleans unchecked, Min Volume=0, Max Volume=14 in PAWSOVERMAWS.

VOICE_ANNUNCIATION_MAP = OptionMap(
    class_name="CVoiceAnnunciation",
    display_name="Voice Annunciation",
    data_size=12,
    fields=[
        FieldDef(
            offset=0, size=1, name="enable_voice_annunciation",
            display_name="Enable Voice Annunciation",
            field_type="bool",
            description="Enable voice annunciation feature",
        ),
        FieldDef(
            offset=1, size=1, name="enable_verbose_playback",
            display_name="Enable Verbose Playback",
            field_type="bool",
            description="Enable verbose voice playback mode",
        ),
        FieldDef(
            offset=2, size=1, name="power_on",
            display_name="Power On",
            field_type="bool",
            description="Announce voice annunciation on power on",
        ),
        FieldDef(
            offset=3, size=1, name="minimum_volume",
            display_name="Minimum Volume",
            field_type="uint8", min_val=0, max_val=31,
            description="Minimum voice annunciation volume level",
        ),
        FieldDef(
            offset=4, size=1, name="maximum_volume",
            display_name="Maximum Volume",
            field_type="uint8", min_val=0, max_val=31,
            description="Maximum voice annunciation volume level",
        ),
        FieldDef(
            offset=5, size=1, name="va_byte_5",
            display_name="VA Byte 5",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown voice annunciation parameter (6 in PAWSOVERMAWS)",
        ),
        # Bytes 6-11: all zeros

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=6, size=1, name="va_rsv_6",
                 display_name="VoiceAnnunciation Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="va_rsv_7",
                 display_name="VoiceAnnunciation Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="va_rsv_8",
                 display_name="VoiceAnnunciation Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="va_rsv_9",
                 display_name="VoiceAnnunciation Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="va_rsv_10",
                 display_name="VoiceAnnunciation Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="va_rsv_11",
                 display_name="VoiceAnnunciation Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CType99Opts field map (4 data bytes) ──────────────────────────
# Maps to the "Type 99 Decode Options" dialog in RPM.
# Only boolean flags; actual tone data lives in CT99 section.

TYPE99_OPTS_MAP = OptionMap(
    class_name="CType99Opts",
    display_name="Type 99 Decode Options",
    data_size=4,
    fields=[
        FieldDef(
            offset=0, size=1, name="disable_after_ptt",
            display_name="Disable After PTT",
            field_type="bool",
            description="Disable Type 99 decode after PTT",
        ),
        FieldDef(
            offset=1, size=1, name="auto_reset",
            display_name="Auto Reset",
            field_type="bool",
            description="Auto-reset Type 99 decode",
        ),
        FieldDef(
            offset=2, size=1, name="type99_byte_2",
            display_name="Type 99 Byte 2",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown Type 99 parameter (36/0x24 in PAWSOVERMAWS)",
        ),
        # Byte 3: 0

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=3, size=1, name="t99_rsv_3",
                 display_name="Type99Opts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CDataOpts field map (41 data bytes) ─────────────────────────────
# Maps to the "Data Options" 3-tab dialog in RPM:
#   Tab 1: Data Applications (ProFile, GPS, Mobile, TextLink)
#   Tab 2: Data Transport (Universal, DCS+, P25T, SNDCP)
#   Tab 3: Data Interfaces (MDT, PPP/SLIP, Serial)
# Cross-referenced against PAWSOVERMAWS RPM screenshots.

DATA_OPTS_MAP = OptionMap(
    class_name="CDataOpts",
    display_name="Data Options",
    data_size=41,
    fields=[
        # Bytes 0-2: unknown (0x00) — possibly ProFile/CSS/GPS enable bools
        # Tab 2: Universal Data Options
        FieldDef(
            offset=3, size=1, name="ptt_receive_data",
            display_name="PTT Receive Data",
            field_type="bool",
            description="Enable data reception on PTT",
        ),
        FieldDef(
            offset=4, size=1, name="ptt_transmit_data",
            display_name="PTT Transmit Data",
            field_type="bool",
            description="Enable data transmission on PTT",
        ),
        FieldDef(
            offset=5, size=1, name="tx_data_overrides_rx_grp_call",
            display_name="Tx Data Overrides Rx Grp Call",
            field_type="bool",
            description="Transmit data takes priority over group call",
        ),
        # Tab 3: Data Interface Protocol
        FieldDef(
            offset=6, size=1, name="data_interface_protocol",
            display_name="Data Interface Protocol",
            field_type="enum",
            enum_values={0x00: "DI", 0x01: "PPP/SLIP"},
            description="Data interface protocol (DI or PPP/SLIP)",
        ),
        # Byte 7-9: unknown
        # Tab 1: GPS Mic Sample Interval
        FieldDef(
            offset=10, size=1, name="gps_mic_sample_interval",
            display_name="GPS Mic Sample Interval",
            field_type="uint8", min_val=0, max_val=255,
            description="GPS microphone sample interval in seconds",
        ),
        # Bytes 11-12: unknown (possibly DCS+ Enable, BREN bools)
        # Tab 2: DCS+ Options
        FieldDef(
            offset=13, size=1, name="dcs_max_frame_retries",
            display_name="DCS+ Max Frame Retries",
            field_type="uint8", min_val=0, max_val=255,
            description="Maximum DCS+ frame retransmission attempts",
        ),
        FieldDef(
            offset=14, size=1, name="dcs_max_frame_repeats",
            display_name="DCS+ Max Frame Repeats",
            field_type="uint8", min_val=0, max_val=255,
            description="Maximum DCS+ frame repeats",
        ),
        FieldDef(
            offset=15, size=1, name="dcs_ack_response_timeout",
            display_name="DCS+ Ack Response Timeout",
            field_type="uint8", min_val=0, max_val=255,
            description="ACK response timeout (value x100 = ms, 10=1000ms)",
        ),
        FieldDef(
            offset=16, size=1, name="dcs_data_response_timeout",
            display_name="DCS+ Data Response Timeout",
            field_type="uint8", min_val=0, max_val=255,
            description="Data response timeout (value x100 = ms, 80=8000ms)",
        ),
        # Bytes 17-19: unknown (possibly MDT Data Enable, P25T protocol)
        # Tab 3: PPP/SLIP Settings
        FieldDef(
            offset=20, size=1, name="ppp_slip_retry_count",
            display_name="PPP/SLIP Retry Count",
            field_type="uint8", min_val=0, max_val=255,
            description="Packet buffer retry count",
        ),
        FieldDef(
            offset=21, size=1, name="ppp_slip_retry_interval",
            display_name="PPP/SLIP Retry Interval",
            field_type="uint8", min_val=0, max_val=255,
            description="Packet buffer retry interval",
        ),
        # Byte 22: unknown
        FieldDef(
            offset=23, size=1, name="ppp_slip_ttl",
            display_name="PPP/SLIP TTL",
            field_type="uint8", min_val=0, max_val=255,
            description="Packet time to live",
        ),
        # Byte 24: unknown
        # Tab 3: PPP/SLIP IP Addresses
        FieldDef(
            offset=25, size=4, name="service_address",
            display_name="Service Address",
            field_type="ipv4",
            description="PPP/SLIP service IP address",
        ),
        # Bytes 29-30: unknown
        # Tab 3: Serial Settings
        FieldDef(
            offset=31, size=1, name="serial_baud_rate",
            display_name="Serial Baud Rate",
            field_type="enum",
            enum_values={
                0x00: "300", 0x01: "1200", 0x02: "2400",
                0x03: "4800", 0x04: "9600", 0x05: "19200",
            },
            description="Serial port baud rate",
        ),
        # Bytes 32-34: unknown
        FieldDef(
            offset=35, size=4, name="mdt_address",
            display_name="MDT Address",
            field_type="ipv4",
            description="MDT IP address",
        ),
        FieldDef(
            offset=39, size=1, name="serial_stop_bits",
            display_name="Serial Stop Bits",
            field_type="enum",
            enum_values={0x01: "One", 0x02: "Two"},
            description="Serial port stop bits",
        ),
        # Byte 40: unknown

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="data_rsv_0",
                 display_name="DataOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="data_rsv_1",
                 display_name="DataOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="data_rsv_2",
                 display_name="DataOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="data_rsv_7",
                 display_name="DataOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="data_rsv_8",
                 display_name="DataOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="data_rsv_9",
                 display_name="DataOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="data_rsv_11",
                 display_name="DataOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=12, size=1, name="data_rsv_12",
                 display_name="DataOpts Reserved 12", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=17, size=1, name="data_rsv_17",
                 display_name="DataOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="data_rsv_18",
                 display_name="DataOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=19, size=1, name="data_rsv_19",
                 display_name="DataOpts Reserved 19", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="data_rsv_22",
                 display_name="DataOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="data_rsv_24",
                 display_name="DataOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="data_rsv_29",
                 display_name="DataOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=30, size=1, name="data_rsv_30",
                 display_name="DataOpts Reserved 30", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="data_rsv_32",
                 display_name="DataOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="data_rsv_33",
                 display_name="DataOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="data_rsv_34",
                 display_name="DataOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=40, size=1, name="data_rsv_40",
                 display_name="DataOpts Reserved 40", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CSndcpOpts field map (8 data bytes) ─────────────────────────────
# Maps to SNDCP section of Data Options > Data Transport tab.

SNDCP_OPTS_MAP = OptionMap(
    class_name="CSndcpOpts",
    display_name="SNDCP Options",
    data_size=8,
    fields=[
        # Bytes 0-4: unknown (all 0x00 in PAWSOVERMAWS)
        # Byte 5-6: Hold-off Timer in ms (uint16 LE, 2000 = 2.0 seconds)
        FieldDef(
            offset=5, size=2, name="holdoff_timer_ms",
            display_name="Hold-off Timer (ms)",
            field_type="uint16", min_val=0, max_val=65535,
            description="SNDCP hold-off timer in milliseconds (2000=2.0s)",
        ),
        # Byte 7: unknown (0x00)

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="sndcp_rsv_0",
                 display_name="SndcpOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="sndcp_rsv_1",
                 display_name="SndcpOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="sndcp_rsv_2",
                 display_name="SndcpOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="sndcp_rsv_3",
                 display_name="SndcpOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="sndcp_rsv_4",
                 display_name="SndcpOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="sndcp_rsv_7",
                 display_name="SndcpOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CGEstarOpts field map (35 data bytes) ────────────────────────────
# Maps to "Conventional Emergency/Home Channel Options" dialog in RPM.
# Contains G-STAR emergency and repeat settings.

GESTAR_OPTS_MAP = OptionMap(
    class_name="CGEstarOpts",
    display_name="Conv Emergency/Home Options",
    data_size=35,
    fields=[
        # Bytes 0-3: unknown booleans (byte 4 = 0x01)
        FieldDef(
            offset=4, size=1, name="p25c_repeat_emer_tone",
            display_name="P25C Repeat Emer Tone",
            field_type="bool",
            description="Repeat P25 conventional emergency tone",
        ),
        # Bytes 5-9: unknown
        # Byte 10-17: Start Delay as IEEE 754 double (360.0 in PAWSOVERMAWS)
        FieldDef(
            offset=10, size=8, name="start_delay",
            display_name="Start Delay",
            field_type="double",
            description="Emergency start delay in seconds",
        ),
        # Byte 18: unknown
        FieldDef(
            offset=19, size=1, name="emer_repeat",
            display_name="Emer Repeat",
            field_type="uint8", min_val=0, max_val=255,
            description="Number of emergency repeats",
        ),
        FieldDef(
            offset=21, size=1, name="gestar_byte_21",
            display_name="GEstar Byte 21",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown GEstar parameter (32/0x20 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=22, size=1, name="gestar_byte_22",
            display_name="GEstar Byte 22",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown GEstar parameter (32/0x20 in PAWSOVERMAWS)",
        ),
        # Bytes 23-34: remaining zeros

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="gestar_rsv_0",
                 display_name="GEstarOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="gestar_rsv_1",
                 display_name="GEstarOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="gestar_rsv_2",
                 display_name="GEstarOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="gestar_rsv_3",
                 display_name="GEstarOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="gestar_rsv_5",
                 display_name="GEstarOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="gestar_rsv_6",
                 display_name="GEstarOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="gestar_rsv_7",
                 display_name="GEstarOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="gestar_rsv_8",
                 display_name="GEstarOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="gestar_rsv_9",
                 display_name="GEstarOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="gestar_rsv_18",
                 display_name="GEstarOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="gestar_rsv_20",
                 display_name="GEstarOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="gestar_rsv_23",
                 display_name="GEstarOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="gestar_rsv_24",
                 display_name="GEstarOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="gestar_rsv_25",
                 display_name="GEstarOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="gestar_rsv_26",
                 display_name="GEstarOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="gestar_rsv_27",
                 display_name="GEstarOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="gestar_rsv_28",
                 display_name="GEstarOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="gestar_rsv_29",
                 display_name="GEstarOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=30, size=1, name="gestar_rsv_30",
                 display_name="GEstarOpts Reserved 30", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="gestar_rsv_31",
                 display_name="GEstarOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="gestar_rsv_32",
                 display_name="GEstarOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="gestar_rsv_33",
                 display_name="GEstarOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="gestar_rsv_34",
                 display_name="GEstarOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CProSoundOpts field map (28 data bytes) ─────────────────────────
# Maps to "ProScan Options" dialog in RPM.
# Sensitivity and System Sample Time stored as IEEE 754 doubles.

PROSCAN_OPTS_MAP = OptionMap(
    class_name="CProSoundOpts",
    display_name="ProScan Options",
    data_size=28,
    fields=[
        # Byte 0: unknown (0x00)
        FieldDef(
            offset=1, size=8, name="sensitivity",
            display_name="Sensitivity",
            field_type="double",
            description="ProScan sensitivity level",
        ),
        FieldDef(
            offset=9, size=8, name="system_sample_time",
            display_name="System Sample Time",
            field_type="double",
            description="System sample time in milliseconds",
        ),
        # Bytes 17-27: stride-2 uint8 pattern (values at odd offsets, zeros between)
        FieldDef(
            offset=17, size=1, name="proscan_param_17",
            display_name="ProScan Param 17",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (5 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=19, size=1, name="proscan_param_19",
            display_name="ProScan Param 19",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (31 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=21, size=1, name="proscan_param_21",
            display_name="ProScan Param 21",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (21 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=23, size=1, name="proscan_param_23",
            display_name="ProScan Param 23",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (31 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=25, size=1, name="proscan_param_25",
            display_name="ProScan Param 25",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (18 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=27, size=1, name="proscan_param_27",
            display_name="ProScan Param 27",
            field_type="uint8", min_val=0, max_val=255,
            description="ProScan parameter (3 in PAWSOVERMAWS)",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="proscan_rsv_0",
                 display_name="ProSoundOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="proscan_rsv_18",
                 display_name="ProSoundOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="proscan_rsv_20",
                 display_name="ProSoundOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="proscan_rsv_22",
                 display_name="ProSoundOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="proscan_rsv_24",
                 display_name="ProSoundOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="proscan_rsv_26",
                 display_name="ProSoundOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CVgOpts field map (54 data bytes) ────────────────────────────────
# Maps to "Digital Voice Options" dialog in RPM.
# Contains encryption settings and cue data array.

VG_OPTS_MAP = OptionMap(
    class_name="CVgOpts",
    display_name="Digital Voice Options",
    data_size=54,
    fields=[
        # Bytes 0-1: TX/RX Data Polarity (0=Normal, 1=Inverted)
        FieldDef(
            offset=0, size=1, name="tx_data_polarity",
            display_name="TX Data Polarity",
            field_type="enum",
            enum_values={0x00: "Normal", 0x01: "Inverted"},
            description="Transmit data polarity",
        ),
        FieldDef(
            offset=1, size=1, name="rx_data_polarity",
            display_name="RX Data Polarity",
            field_type="enum",
            enum_values={0x00: "Normal", 0x01: "Inverted"},
            description="Receive data polarity",
        ),
        FieldDef(
            offset=2, size=1, name="max_key_bank",
            display_name="Max Key Bank",
            field_type="uint8", min_val=0, max_val=255,
            description="Maximum key bank number for encryption",
        ),
        # Bytes 3-4: unknown (0x00)
        FieldDef(
            offset=5, size=1, name="encryption_key_size",
            display_name="Encryption Key Size",
            field_type="enum",
            enum_values={0x08: "8 Bytes", 0x10: "16 Bytes"},
            description="Encryption key size in bytes",
        ),
        # Bytes 6-21: Cue Data array (16 bytes, displayed as 8 decimal values
        # in RPM dialog). In PAWSOVERMAWS all 0x41.
        FieldDef(
            offset=24, size=1, name="encryption_mode",
            display_name="Encryption Mode",
            field_type="enum",
            enum_values={0x00: "OFF", 0x01: "Forced On", 0x02: "Selectable"},
            description="Encryption operating mode",
        ),
        # Bytes 25-53: ARC4 key storage, Single Key DES fields (mostly 0x00)

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=3, size=1, name="vg_rsv_3",
                 display_name="VgOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="vg_rsv_4",
                 display_name="VgOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="vg_rsv_6",
                 display_name="VgOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="vg_rsv_7",
                 display_name="VgOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="vg_rsv_8",
                 display_name="VgOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="vg_rsv_9",
                 display_name="VgOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="vg_rsv_10",
                 display_name="VgOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="vg_rsv_11",
                 display_name="VgOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=12, size=1, name="vg_rsv_12",
                 display_name="VgOpts Reserved 12", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=13, size=1, name="vg_rsv_13",
                 display_name="VgOpts Reserved 13", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="vg_rsv_14",
                 display_name="VgOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=15, size=1, name="vg_rsv_15",
                 display_name="VgOpts Reserved 15", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="vg_rsv_16",
                 display_name="VgOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=17, size=1, name="vg_rsv_17",
                 display_name="VgOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="vg_rsv_18",
                 display_name="VgOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=19, size=1, name="vg_rsv_19",
                 display_name="VgOpts Reserved 19", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="vg_rsv_20",
                 display_name="VgOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=21, size=1, name="vg_rsv_21",
                 display_name="VgOpts Reserved 21", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="vg_rsv_22",
                 display_name="VgOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="vg_rsv_23",
                 display_name="VgOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="vg_rsv_25",
                 display_name="VgOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="vg_rsv_26",
                 display_name="VgOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="vg_rsv_27",
                 display_name="VgOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="vg_rsv_28",
                 display_name="VgOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="vg_rsv_29",
                 display_name="VgOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=30, size=1, name="vg_rsv_30",
                 display_name="VgOpts Reserved 30", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="vg_rsv_31",
                 display_name="VgOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="vg_rsv_32",
                 display_name="VgOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="vg_rsv_33",
                 display_name="VgOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="vg_rsv_34",
                 display_name="VgOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="vg_rsv_35",
                 display_name="VgOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=36, size=1, name="vg_rsv_36",
                 display_name="VgOpts Reserved 36", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=37, size=1, name="vg_rsv_37",
                 display_name="VgOpts Reserved 37", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=38, size=1, name="vg_rsv_38",
                 display_name="VgOpts Reserved 38", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=39, size=1, name="vg_rsv_39",
                 display_name="VgOpts Reserved 39", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=40, size=1, name="vg_rsv_40",
                 display_name="VgOpts Reserved 40", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=41, size=1, name="vg_rsv_41",
                 display_name="VgOpts Reserved 41", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=42, size=1, name="vg_rsv_42",
                 display_name="VgOpts Reserved 42", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=43, size=1, name="vg_rsv_43",
                 display_name="VgOpts Reserved 43", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=44, size=1, name="vg_rsv_44",
                 display_name="VgOpts Reserved 44", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=45, size=1, name="vg_rsv_45",
                 display_name="VgOpts Reserved 45", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=46, size=1, name="vg_rsv_46",
                 display_name="VgOpts Reserved 46", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=47, size=1, name="vg_rsv_47",
                 display_name="VgOpts Reserved 47", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=48, size=1, name="vg_rsv_48",
                 display_name="VgOpts Reserved 48", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=49, size=1, name="vg_rsv_49",
                 display_name="VgOpts Reserved 49", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=50, size=1, name="vg_rsv_50",
                 display_name="VgOpts Reserved 50", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=51, size=1, name="vg_rsv_51",
                 display_name="VgOpts Reserved 51", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=52, size=1, name="vg_rsv_52",
                 display_name="VgOpts Reserved 52", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=53, size=1, name="vg_rsv_53",
                 display_name="VgOpts Reserved 53", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CConvScanOpts field map (30 data bytes) ─────────────────────────
# Conventional scan configuration. Bytes 0,2,4,6 are booleans (stride-2).
# Byte 7 is an enum value (2 in PAWSOVERMAWS).

CONV_SCAN_OPTS_MAP = OptionMap(
    class_name="CConvScanOpts",
    display_name="Conv Scan Options",
    data_size=30,
    fields=[
        FieldDef(
            offset=0, size=1, name="conv_scan_opt_0",
            display_name="Conv Scan Option 1",
            field_type="bool",
        ),
        FieldDef(offset=1, size=1, name="conv_scan_gap_1",
                 display_name="Conv Scan Gap 1", field_type="bool",
                 description="Stride-2 gap byte (False in PAWSOVERMAWS)"),
        FieldDef(
            offset=2, size=1, name="conv_scan_opt_1",
            display_name="Conv Scan Option 2",
            field_type="bool",
        ),
        FieldDef(offset=3, size=1, name="conv_scan_gap_3",
                 display_name="Conv Scan Gap 3", field_type="bool",
                 description="Stride-2 gap byte (False in PAWSOVERMAWS)"),
        FieldDef(
            offset=4, size=1, name="conv_scan_opt_2",
            display_name="Conv Scan Option 3",
            field_type="bool",
        ),
        FieldDef(offset=5, size=1, name="conv_scan_gap_5",
                 display_name="Conv Scan Gap 5", field_type="bool",
                 description="Stride-2 gap byte (False in PAWSOVERMAWS)"),
        FieldDef(
            offset=6, size=1, name="conv_scan_opt_3",
            display_name="Conv Scan Option 4",
            field_type="bool",
        ),
        FieldDef(
            offset=7, size=1, name="conv_scan_mode",
            display_name="Conv Scan Mode",
            field_type="uint8", min_val=0, max_val=255,
        ),
        FieldDef(
            offset=9, size=8, name="conv_scan_double_9",
            display_name="Conv Scan Timer",
            field_type="double",
            description="Unidentified conv scan double (2.0 in PAWSOVERMAWS)",
        ),
        # Bytes 17-29: remaining zeros / reserved

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=8, size=1, name="conv_scan_rsv_8",
                 display_name="ConvScanOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=17, size=1, name="conv_scan_rsv_17",
                 display_name="ConvScanOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="conv_scan_rsv_18",
                 display_name="ConvScanOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=19, size=1, name="conv_scan_rsv_19",
                 display_name="ConvScanOpts Reserved 19", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=20, size=1, name="conv_scan_rsv_20",
                 display_name="ConvScanOpts Reserved 20", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=21, size=1, name="conv_scan_rsv_21",
                 display_name="ConvScanOpts Reserved 21", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=22, size=1, name="conv_scan_rsv_22",
                 display_name="ConvScanOpts Reserved 22", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="conv_scan_rsv_23",
                 display_name="ConvScanOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="conv_scan_rsv_24",
                 display_name="ConvScanOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="conv_scan_rsv_25",
                 display_name="ConvScanOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="conv_scan_rsv_26",
                 display_name="ConvScanOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="conv_scan_rsv_27",
                 display_name="ConvScanOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="conv_scan_rsv_28",
                 display_name="ConvScanOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=29, size=1, name="conv_scan_rsv_29",
                 display_name="ConvScanOpts Reserved 29", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CDisplayOpts field map (37 data bytes) ───────────────────────────
# NOT the "Display Settings" dialog (those are in XML platformConfig).
# Possibly maps to "Unity Portable/Mobile Options" or internal display state.

DISPLAY_OPTS_MAP = OptionMap(
    class_name="CDisplayOpts",
    display_name="Display Options",
    data_size=37,
    fields=[
        FieldDef(
            offset=3, size=1, name="display_opt_bool_0",
            display_name="Display Option 1",
            field_type="bool",
        ),
        FieldDef(
            offset=8, size=1, name="display_opt_bool_1",
            display_name="Display Option 2",
            field_type="bool",
        ),
        FieldDef(
            offset=29, size=1, name="display_opt_bool_2",
            display_name="Display Option 3",
            field_type="bool",
        ),
        FieldDef(
            offset=12, size=1, name="display_opt_byte_12",
            display_name="Display Option Byte 12",
            field_type="uint8", min_val=0, max_val=255,
            description="Unidentified display byte (42/0x2A in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=15, size=8, name="display_opt_double_15",
            display_name="Display Option Double 15",
            field_type="double",
            description="Unidentified display double (3.5 in PAWSOVERMAWS)",
        ),
        # Bytes 23-28: remaining unmapped

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="display_rsv_0",
                 display_name="DisplayOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="display_rsv_1",
                 display_name="DisplayOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="display_rsv_2",
                 display_name="DisplayOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="display_rsv_4",
                 display_name="DisplayOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="display_rsv_5",
                 display_name="DisplayOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="display_rsv_6",
                 display_name="DisplayOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="display_rsv_7",
                 display_name="DisplayOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="display_rsv_9",
                 display_name="DisplayOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="display_rsv_10",
                 display_name="DisplayOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="display_rsv_11",
                 display_name="DisplayOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=13, size=1, name="display_rsv_13",
                 display_name="DisplayOpts Reserved 13", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="display_rsv_14",
                 display_name="DisplayOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=23, size=1, name="display_rsv_23",
                 display_name="DisplayOpts Reserved 23", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=24, size=1, name="display_rsv_24",
                 display_name="DisplayOpts Reserved 24", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=25, size=1, name="display_rsv_25",
                 display_name="DisplayOpts Reserved 25", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=26, size=1, name="display_rsv_26",
                 display_name="DisplayOpts Reserved 26", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=27, size=1, name="display_rsv_27",
                 display_name="DisplayOpts Reserved 27", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=28, size=1, name="display_rsv_28",
                 display_name="DisplayOpts Reserved 28", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=30, size=1, name="display_rsv_30",
                 display_name="DisplayOpts Reserved 30", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=31, size=1, name="display_rsv_31",
                 display_name="DisplayOpts Reserved 31", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=32, size=1, name="display_rsv_32",
                 display_name="DisplayOpts Reserved 32", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="display_rsv_33",
                 display_name="DisplayOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="display_rsv_34",
                 display_name="DisplayOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="display_rsv_35",
                 display_name="DisplayOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=36, size=1, name="display_rsv_36",
                 display_name="DisplayOpts Reserved 36", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CIgnitionOpts field map (10 data bytes) ─────────────────────────
# Ignition-related settings for vehicle-mount radios.

IGNITION_OPTS_MAP = OptionMap(
    class_name="CIgnitionOpts",
    display_name="Ignition Options",
    data_size=10,
    fields=[
        FieldDef(
            offset=7, size=1, name="ignition_timer",
            display_name="Ignition Timer",
            field_type="uint8", min_val=0, max_val=255,
            description="Ignition timer value (20 in PAWSOVERMAWS)",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="ign_rsv_0",
                 display_name="IgnitionOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="ign_rsv_1",
                 display_name="IgnitionOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="ign_rsv_2",
                 display_name="IgnitionOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="ign_rsv_3",
                 display_name="IgnitionOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="ign_rsv_4",
                 display_name="IgnitionOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="ign_rsv_5",
                 display_name="IgnitionOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="ign_rsv_6",
                 display_name="IgnitionOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="ign_rsv_8",
                 display_name="IgnitionOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="ign_rsv_9",
                 display_name="IgnitionOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CNetworkOpts field map (38 data bytes) ───────────────────────────
# Network configuration. Contains doubles at offsets 17 (30.0) and 25 (2.0).
# Does NOT clearly map to P25 OTAR Options dialog values.

NETWORK_OPTS_MAP = OptionMap(
    class_name="CNetworkOpts",
    display_name="Network Options",
    data_size=38,
    fields=[
        FieldDef(
            offset=5, size=1, name="network_byte_5",
            display_name="Network Byte 5",
            field_type="bool",
            description="Unknown network boolean (True in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=10, size=1, name="network_byte_10",
            display_name="Network Byte 10",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown network parameter (2 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=13, size=1, name="network_byte_13",
            display_name="Network Byte 13",
            field_type="bool",
            description="Unknown network boolean (True in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=15, size=1, name="network_byte_15",
            display_name="Network Byte 15",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown network parameter (5 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=17, size=8, name="network_timer_1",
            display_name="Network Timer 1",
            field_type="double",
            description="Network timer value (30.0 in PAWSOVERMAWS)",
        ),
        FieldDef(
            offset=25, size=8, name="network_timer_2",
            display_name="Network Timer 2",
            field_type="double",
            description="Network timer value (2.0 in PAWSOVERMAWS)",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="net_rsv_0",
                 display_name="NetworkOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="net_rsv_1",
                 display_name="NetworkOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="net_rsv_2",
                 display_name="NetworkOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="net_rsv_3",
                 display_name="NetworkOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="net_rsv_4",
                 display_name="NetworkOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="net_rsv_6",
                 display_name="NetworkOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="net_rsv_7",
                 display_name="NetworkOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="net_rsv_8",
                 display_name="NetworkOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="net_rsv_9",
                 display_name="NetworkOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="net_rsv_11",
                 display_name="NetworkOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=12, size=1, name="net_rsv_12",
                 display_name="NetworkOpts Reserved 12", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="net_rsv_14",
                 display_name="NetworkOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="net_rsv_16",
                 display_name="NetworkOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=33, size=1, name="net_rsv_33",
                 display_name="NetworkOpts Reserved 33", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=34, size=1, name="net_rsv_34",
                 display_name="NetworkOpts Reserved 34", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=35, size=1, name="net_rsv_35",
                 display_name="NetworkOpts Reserved 35", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=36, size=1, name="net_rsv_36",
                 display_name="NetworkOpts Reserved 36", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=37, size=1, name="net_rsv_37",
                 display_name="NetworkOpts Reserved 37", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CMmsOpts field map (13 data bytes) ───────────────────────────────
# Multimedia messaging options.

MMS_OPTS_MAP = OptionMap(
    class_name="CMmsOpts",
    display_name="MMS Options",
    data_size=13,
    fields=[
        FieldDef(
            offset=8, size=1, name="mms_retries",
            display_name="MMS Retries",
            field_type="uint8", min_val=0, max_val=255,
        ),
        FieldDef(
            offset=9, size=1, name="mms_param_1",
            display_name="MMS Parameter 1",
            field_type="uint8", min_val=0, max_val=255,
        ),
        FieldDef(
            offset=11, size=1, name="mms_param_2",
            display_name="MMS Parameter 2",
            field_type="uint8", min_val=0, max_val=255,
        ),
        FieldDef(
            offset=12, size=1, name="mms_timeout",
            display_name="MMS Timeout",
            field_type="uint8", min_val=0, max_val=255,
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="mms_rsv_0",
                 display_name="MmsOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="mms_rsv_1",
                 display_name="MmsOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="mms_rsv_2",
                 display_name="MmsOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="mms_rsv_3",
                 display_name="MmsOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="mms_rsv_4",
                 display_name="MmsOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="mms_rsv_5",
                 display_name="MmsOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="mms_rsv_6",
                 display_name="MmsOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="mms_rsv_7",
                 display_name="MmsOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="mms_rsv_10",
                 display_name="MmsOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CKeypadCtrlOpts field map (20 data bytes) ───────────────────────
# Keypad control settings.

KEYPAD_CTRL_OPTS_MAP = OptionMap(
    class_name="CKeypadCtrlOpts",
    display_name="Keypad Control Options",
    data_size=20,
    fields=[
        FieldDef(
            offset=3, size=1, name="keypad_opt_0",
            display_name="Keypad Option 1",
            field_type="bool",
        ),
        FieldDef(
            offset=10, size=1, name="keypad_opt_1",
            display_name="Keypad Option 2",
            field_type="bool",
        ),
        FieldDef(
            offset=11, size=1, name="keypad_opt_2",
            display_name="Keypad Option 3",
            field_type="bool",
        ),
        FieldDef(
            offset=12, size=1, name="keypad_opt_3",
            display_name="Keypad Option 4",
            field_type="bool",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="keypad_rsv_0",
                 display_name="KeypadCtrlOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="keypad_rsv_1",
                 display_name="KeypadCtrlOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="keypad_rsv_2",
                 display_name="KeypadCtrlOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="keypad_rsv_4",
                 display_name="KeypadCtrlOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="keypad_rsv_5",
                 display_name="KeypadCtrlOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="keypad_rsv_6",
                 display_name="KeypadCtrlOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=7, size=1, name="keypad_rsv_7",
                 display_name="KeypadCtrlOpts Reserved 7", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="keypad_rsv_8",
                 display_name="KeypadCtrlOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="keypad_rsv_9",
                 display_name="KeypadCtrlOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=13, size=1, name="keypad_rsv_13",
                 display_name="KeypadCtrlOpts Reserved 13", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="keypad_rsv_14",
                 display_name="KeypadCtrlOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=15, size=1, name="keypad_rsv_15",
                 display_name="KeypadCtrlOpts Reserved 15", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=16, size=1, name="keypad_rsv_16",
                 display_name="KeypadCtrlOpts Reserved 16", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=17, size=1, name="keypad_rsv_17",
                 display_name="KeypadCtrlOpts Reserved 17", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=18, size=1, name="keypad_rsv_18",
                 display_name="KeypadCtrlOpts Reserved 18", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=19, size=1, name="keypad_rsv_19",
                 display_name="KeypadCtrlOpts Reserved 19", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── CMrkOpts field map (16 data bytes) ───────────────────────────────
# MRK (Mobile Radio Key?) options.

MRK_OPTS_MAP = OptionMap(
    class_name="CMrkOpts",
    display_name="MRK Options",
    data_size=16,
    fields=[
        FieldDef(
            offset=7, size=1, name="mrk_enable",
            display_name="MRK Enable",
            field_type="bool",
        ),
        FieldDef(
            offset=12, size=1, name="mrk_byte_12",
            display_name="MRK Byte 12",
            field_type="uint8", min_val=0, max_val=255,
            description="Unknown MRK parameter (64/0x40 in PAWSOVERMAWS)",
        ),

        # Unmapped/reserved bytes (zero in all known samples)
        FieldDef(offset=0, size=1, name="mrk_rsv_0",
                 display_name="MrkOpts Reserved 0", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=1, size=1, name="mrk_rsv_1",
                 display_name="MrkOpts Reserved 1", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=2, size=1, name="mrk_rsv_2",
                 display_name="MrkOpts Reserved 2", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=3, size=1, name="mrk_rsv_3",
                 display_name="MrkOpts Reserved 3", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=4, size=1, name="mrk_rsv_4",
                 display_name="MrkOpts Reserved 4", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=5, size=1, name="mrk_rsv_5",
                 display_name="MrkOpts Reserved 5", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=6, size=1, name="mrk_rsv_6",
                 display_name="MrkOpts Reserved 6", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=8, size=1, name="mrk_rsv_8",
                 display_name="MrkOpts Reserved 8", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=9, size=1, name="mrk_rsv_9",
                 display_name="MrkOpts Reserved 9", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=10, size=1, name="mrk_rsv_10",
                 display_name="MrkOpts Reserved 10", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=11, size=1, name="mrk_rsv_11",
                 display_name="MrkOpts Reserved 11", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=13, size=1, name="mrk_rsv_13",
                 display_name="MrkOpts Reserved 13", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=14, size=1, name="mrk_rsv_14",
                 display_name="MrkOpts Reserved 14", field_type="uint8",
                 min_val=0, max_val=255),
        FieldDef(offset=15, size=1, name="mrk_rsv_15",
                 display_name="MrkOpts Reserved 15", field_type="uint8",
                 min_val=0, max_val=255),
    ],
)


# ─── Registry ────────────────────────────────────────────────────────

OPTION_MAPS = {
    "CAccessoryDevice": ACCESSORY_DEVICE_MAP,
    "CAlertOpts": ALERT_OPTS_MAP,
    "CGenRadioOpts": GEN_RADIO_OPTS_MAP,
    "CDTMFOpts": DTMF_OPTS_MAP,
    "CTimerOpts": TIMER_OPTS_MAP,
    "CSupervisoryOpts": SUPERVISORY_OPTS_MAP,
    "CPowerUpOpts": POWER_UP_OPTS_MAP,
    "CScanOpts": SCAN_OPTS_MAP,
    "CDiagnosticOpts": DIAGNOSTIC_OPTS_MAP,
    "CMdcOpts": MDC_OPTS_MAP,
    "CSecurityPolicy": SECURITY_POLICY_MAP,
    "CStatus": STATUS_OPTS_MAP,
    "CSystemScanOpts": SYSTEM_SCAN_OPTS_MAP,
    "CVoiceAnnunciation": VOICE_ANNUNCIATION_MAP,
    "CType99Opts": TYPE99_OPTS_MAP,
    "CDataOpts": DATA_OPTS_MAP,
    "CSndcpOpts": SNDCP_OPTS_MAP,
    "CGEstarOpts": GESTAR_OPTS_MAP,
    "CProSoundOpts": PROSCAN_OPTS_MAP,
    "CVgOpts": VG_OPTS_MAP,
    "CConvScanOpts": CONV_SCAN_OPTS_MAP,
    "CDisplayOpts": DISPLAY_OPTS_MAP,
    "CIgnitionOpts": IGNITION_OPTS_MAP,
    "CNetworkOpts": NETWORK_OPTS_MAP,
    "CMmsOpts": MMS_OPTS_MAP,
    "CKeypadCtrlOpts": KEYPAD_CTRL_OPTS_MAP,
    "CMrkOpts": MRK_OPTS_MAP,
}


# ─── XML platformConfig field catalog ────────────────────────────────
# Maps XML element/attribute paths to RPM display names and types.
# This is the complete catalog of every field found in XG-100P PRS files.

@dataclass
class XmlFieldDef:
    """Definition of a field within the platformConfig XML."""
    element: str              # XML element path (e.g. "audioConfig")
    attribute: str            # XML attribute name (e.g. "speakerMode")
    display_name: str         # RPM GUI field name
    category: str             # RPM option tab (e.g. "Audio Settings")
    field_type: str           # 'onoff', 'enum', 'int', 'string'
    enum_values: List[str] = field(default_factory=list)
    display_map: Dict[str, str] = field(default_factory=dict)  # raw -> friendly
    min_val: Optional[int] = None
    max_val: Optional[int] = None
    description: str = ""
    conditional: bool = False
    group: str = ""           # sub-section header within category
    depends_on: str = ""      # attribute that must be ON for this to be editable


# ─── Programmable button / short menu display names ─────────────────
# Defined here (before XML_FIELDS) so XmlFieldDef entries can reference them.

BUTTON_FUNCTION_NAMES = {
    "UNASSIGNED": "Unassigned",
    "TALKAROUND_DIRECT": "Talkaround/Direct",
    "TALKAROUND": "Talkaround",
    "ZONE_UP_WRAP": "Zone Up (Wrap)",
    "ZONE_DOWN_WRAP": "Zone Down (Wrap)",
    "ZONE_UP_STOP": "Zone Up (Stop)",
    "ZONE_DOWN_STOP": "Zone Down (Stop)",
    "ZONE_UP": "Zone Up",
    "ZONE_DOWN": "Zone Down",
    "EMERGENCY_CALL": "Emergency Call",
    "SCAN": "Scan",
    "CHAN_BANK": "Channel Bank",
    "MONITOR": "Monitor",
    "MONITOR_CLEAR": "Monitor/Clear",
    "TX_POWER": "TX Power",
    "NUISANCE_DELETE": "Nuisance Delete",
    "LOCK_KEYPAD": "Lock Keypad",
    "DISPLAY_SA": "Display SA",
    "HOME_CHANNEL": "Home Channel",
    "SITE_DISPLAY": "Site Display",
    "SITE_LOCK": "Site Lock",
    "REPEATER_ACCESS": "Repeater Access",
    "PTCT": "PTCT",
}

BUTTON_NAME_DISPLAY = {
    "TOP_SIDE": "Top Side Button",
    "MID_SIDE": "Mid Side Button",
    "BOT_SIDE": "Bottom Side Button",
    "EMERGENCY": "Emergency Button",
    "ACC_USER_1": "Accessory User 1",
    "ACC_USER_2": "Accessory User 2",
    "ACC_EMERGENCY": "Accessory Emergency",
}

SHORT_MENU_NAMES = {
    "startScan": "Start Scan",
    "startMon": "Start Monitor",
    "nuisanceDel": "Nuisance Delete",
    "selChanGrp": "Select Channel Group",
    "lockKeypad": "Lock Keypad",
    "txPower": "TX Power",
    "dispSA": "Display SA",
    "siteDisplay": "Site Display",
    "siteLock": "Site Lock",
    "homeChannel": "Home Channel",
    "empty": "(Empty)",
}

SWITCH_FUNCTION_NAMES = {
    "SCAN": "Scan",
    "CHAN_BANK": "Channel Bank",
    "ZONE": "Zone",
    "TALKAROUND": "Talkaround",
}


def format_button_function(raw):
    """Get friendly name for a button function."""
    return BUTTON_FUNCTION_NAMES.get(raw, raw)


def format_button_name(raw):
    """Get friendly name for a physical button."""
    return BUTTON_NAME_DISPLAY.get(raw, raw)


def format_short_menu_name(raw):
    """Get friendly name for a short menu item."""
    return SHORT_MENU_NAMES.get(raw, raw)


def format_switch_function(raw):
    """Get friendly name for a switch function."""
    return SWITCH_FUNCTION_NAMES.get(raw, raw)


# ─── XML platformConfig field catalog ────────────────────────────────
# Organized by RPM category with sub-groups matching RPM layout.
# display_map provides friendly names for combo/tree display.

XML_FIELDS = [
    # ── Audio Settings ───────────────────────────────────────────────
    # Audio section
    XmlFieldDef("audioConfig", "speakerMode", "Speaker", "Audio Settings",
                "onoff", group="Audio",
                description="Enable the built-in speaker"),
    XmlFieldDef("audioConfig", "noiseCancellation", "Noise Cancellation",
                "Audio Settings", "onoff", group="Audio",
                description="Reduce background noise during transmit"),

    # PTT section
    XmlFieldDef("audioConfig", "pttMode", "PTT", "Audio Settings",
                "onoff", group="PTT",
                description="Enable push-to-talk"),
    XmlFieldDef("audioConfig", "pttAudio", "PTT Audio",
                "Audio Settings", "enum", group="PTT",
                enum_values=["RADIO_ACCESSORY", "ACCESSORY_ONLY"],
                display_map={"RADIO_ACCESSORY": "Radio and Accessory",
                             "ACCESSORY_ONLY": "Accessory Only"},
                description="Where PTT audio is routed"),
    XmlFieldDef("audioConfig", "tones", "Tones", "Audio Settings",
                "onoff", group="PTT",
                description="Enable alert tones"),
    XmlFieldDef("miscConfig", "keypadTones", "Keypad Tones",
                "Audio Settings", "onoff", group="PTT",
                description="Play tone on keypad press"),

    # Microphone section
    XmlFieldDef("audioConfig/microphone[@micType='INTERNAL']", "alc",
                "Internal Mic ALC", "Audio Settings", "onoff",
                group="Internal Microphone",
                description="Automatic level control for internal mic"),
    XmlFieldDef("audioConfig/microphone[@micType='INTERNAL']", "gain",
                "Internal Mic Gain (dB)", "Audio Settings", "int",
                min_val=-12, max_val=12, group="Internal Microphone",
                description="Internal microphone gain (-12 to +12 dB)"),
    XmlFieldDef("audioConfig/microphone[@micType='EXTERNAL']", "alc",
                "External Mic ALC", "Audio Settings", "onoff",
                group="External Microphone",
                description="Automatic level control for external mic"),
    XmlFieldDef("audioConfig/microphone[@micType='EXTERNAL']", "gain",
                "External Mic Gain (dB)", "Audio Settings", "int",
                min_val=-12, max_val=12, group="External Microphone",
                description="External microphone gain (-12 to +12 dB)"),

    # Speaker section
    XmlFieldDef("audioConfig", "minVol", "Minimum Volume", "Audio Settings",
                "int", min_val=0, max_val=14, group="Speaker",
                description="Lowest volume level (0-14)"),

    # ── Battery Settings ─────────────────────────────────────────────
    XmlFieldDef("miscConfig", "batteryType", "Battery Type",
                "Battery Settings", "enum",
                enum_values=["LITHIUM_ION_POLY", "NIMH", "ALKALINE",
                             "PRIMARY_LITHIUM"],
                display_map={"LITHIUM_ION_POLY": "Lithium Ion Poly",
                             "NIMH": "NiMH",
                             "ALKALINE": "Alkaline",
                             "PRIMARY_LITHIUM": "Primary Lithium"},
                description="Installed battery chemistry type"),

    # ── Display Settings ─────────────────────────────────────────────
    XmlFieldDef("miscConfig", "frontFpMode", "Front Backlight",
                "Display Settings", "enum", group="Front Display",
                enum_values=["BL_ON", "BL_MOMENTARY", "BL_OFF"],
                display_map={"BL_ON": "On", "BL_MOMENTARY": "Timed",
                             "BL_OFF": "Off"},
                description="Front display backlight mode"),
    XmlFieldDef("miscConfig", "frontFpIntensity", "Front Brightness",
                "Display Settings", "int", min_val=0, max_val=15,
                group="Front Display",
                description="Front display brightness level (0-15)"),
    XmlFieldDef("miscConfig", "frontFpTimeout", "Front Backlight Timeout",
                "Display Settings", "int", min_val=0, max_val=120,
                group="Front Display",
                description="Seconds before front display dims"),
    XmlFieldDef("miscConfig", "topFpMode", "Top Backlight",
                "Display Settings", "enum", group="Top Display",
                enum_values=["BL_ON", "BL_MOMENTARY", "BL_OFF"],
                display_map={"BL_ON": "On", "BL_MOMENTARY": "Timed",
                             "BL_OFF": "Off"},
                description="Top display backlight mode"),
    XmlFieldDef("miscConfig", "topFpIntensity", "Top Brightness",
                "Display Settings", "int", min_val=0, max_val=15,
                group="Top Display",
                description="Top display brightness level (0-15)"),
    XmlFieldDef("miscConfig", "topFpTimeout", "Top Backlight Timeout",
                "Display Settings", "int", min_val=0, max_val=120,
                group="Top Display",
                description="Seconds before top display dims"),
    XmlFieldDef("miscConfig", "topFpOrient", "Top Orientation",
                "Display Settings", "enum", group="Top Display",
                enum_values=["FRONT", "BACK"],
                display_map={"FRONT": "Front", "BACK": "Back"},
                description="Top display orientation"),
    XmlFieldDef("miscConfig", "enableTriColorLed", "Indicator LED",
                "Display Settings", "onoff", group="LED",
                description="Enable tri-color status LED"),
    XmlFieldDef("miscConfig", "topColorInvert", "Top Display Color Invert",
                "Display Settings", "onoff", group="LED",
                description="Invert top display colors"),
    XmlFieldDef("TimeDateCfg", "date", "Date Format",
                "Display Settings", "enum", group="Format",
                enum_values=["US_DATE_FORMAT", "INTL_DATE_FORMAT"],
                display_map={"US_DATE_FORMAT": "US (MM/DD/YYYY)",
                             "INTL_DATE_FORMAT": "International (DD/MM/YYYY)"},
                description="Date display format"),

    # ── GPS Settings ─────────────────────────────────────────────────
    XmlFieldDef("gpsConfig", "gpsMode", "GPS", "GPS Settings",
                "onoff", group="GPS",
                description="Enable GPS receiver"),
    XmlFieldDef("gpsConfig", "type", "GPS Type", "GPS Settings", "enum",
                group="GPS",
                enum_values=["INTERNAL_GPS", "EXTERNAL_GPS"],
                display_map={"INTERNAL_GPS": "Internal",
                             "EXTERNAL_GPS": "External"},
                description="Internal or external GPS receiver"),
    XmlFieldDef("gpsConfig", "mapDatum", "Datum", "GPS Settings",
                "enum", group="GPS",
                enum_values=["DATUM_WGD"],
                display_map={"DATUM_WGD": "WGS 84"},
                description="Map coordinate datum"),
    XmlFieldDef("gpsConfig", "positionFormat", "Position Format",
                "GPS Settings", "enum", group="Format",
                enum_values=["LAT_LONG_DMS", "LAT_LONG_DM", "LAT_LONG_DD",
                             "MGRS", "UTM_UPS"],
                display_map={"LAT_LONG_DMS": "Lat/Long DMS",
                             "LAT_LONG_DM": "Lat/Long DM",
                             "LAT_LONG_DD": "Lat/Long DD",
                             "MGRS": "MGRS", "UTM_UPS": "UTM/UPS"},
                description="How GPS coordinates are displayed"),
    XmlFieldDef("gpsConfig", "linearUnits", "Linear Units", "GPS Settings",
                "enum", group="Units",
                enum_values=["STATUTE", "METRIC", "NAUTICAL"],
                display_map={"STATUTE": "Statute", "METRIC": "Metric",
                             "NAUTICAL": "Nautical"},
                description="Distance measurement units"),
    XmlFieldDef("gpsConfig", "angularUnits", "Angular Units", "GPS Settings",
                "enum", group="Units",
                enum_values=["DEGREES", "CARDINAL", "NUMERIC"],
                display_map={"DEGREES": "Degrees", "CARDINAL": "Cardinal",
                             "NUMERIC": "Numeric"},
                description="Bearing display format"),
    XmlFieldDef("gpsConfig", "elevationBasis", "Elevation Basis",
                "GPS Settings", "enum", group="Units",
                enum_values=["SEA_LEVEL", "ELLIPSOID"],
                display_map={"SEA_LEVEL": "Sea Level",
                             "ELLIPSOID": "Ellipsoid"},
                description="Elevation reference point"),
    XmlFieldDef("gpsConfig", "northing", "Northing", "GPS Settings",
                "enum", group="Units",
                enum_values=["TRUE", "MAGNETIC"],
                display_map={"TRUE": "True North", "MAGNETIC": "Magnetic"},
                description="North reference type"),
    XmlFieldDef("gpsConfig", "gridDigits", "Grid Digits", "GPS Settings",
                "int", min_val=6, max_val=10, group="Units",
                description="Number of grid digits displayed (6-10)"),

    # ── Bluetooth Settings ───────────────────────────────────────────
    XmlFieldDef("bluetoothConfig", "btAdminMode", "Bluetooth Allowed",
                "Bluetooth Settings", "onoff",
                description="Master switch — disabling greys out other BT settings"),
    XmlFieldDef("bluetoothConfig", "btMode", "Bluetooth Enable",
                "Bluetooth Settings", "onoff",
                depends_on="btAdminMode",
                description="Turn bluetooth radio on or off"),
    XmlFieldDef("bluetoothConfig", "friendlyName", "Friendly Name",
                "Bluetooth Settings", "string",
                depends_on="btAdminMode",
                description="Name other devices see when discovering this radio"),

    # ── Accessory Device Options ─────────────────────────────────────
    XmlFieldDef("accessoryConfig", "pttMode", "PTT Mode",
                "Accessory Options", "enum", group="Accessory",
                enum_values=["BOTH", "ANY"],
                display_map={"BOTH": "Both", "ANY": "Any"},
                description="PTT activation mode for accessories"),
    XmlFieldDef("accessoryConfig", "noiseCancellation",
                "Noise Cancellation", "Accessory Options", "onoff",
                group="Accessory",
                description="Accessory noise cancellation"),
    XmlFieldDef("accessoryConfig", "micSelectMode",
                "Microphone Selection", "Accessory Options", "enum",
                group="Accessory",
                enum_values=["TOP", "BOTTOM"],
                display_map={"TOP": "Top", "BOTTOM": "Bottom"},
                description="Which microphone to use with accessory"),

    # Man Down
    XmlFieldDef("manDownConfig", "sensitivity", "Sensitivity",
                "Accessory Options", "enum", group="Man Down",
                enum_values=["0", "1", "3", "5"],
                display_map={"0": "Off", "1": "Low", "3": "Medium",
                             "5": "High"},
                description="Man Down tilt detection sensitivity"),
    XmlFieldDef("manDownConfig", "inactivityTime",
                "Detection Delay", "Accessory Options", "int",
                min_val=0, max_val=240, group="Man Down",
                description="Seconds of inactivity before alert (0-240)"),
    XmlFieldDef("manDownConfig", "warningTime", "Warning Delay",
                "Accessory Options", "int",
                min_val=0, max_val=240, group="Man Down",
                description="Seconds of warning before emergency (0-240)"),
    XmlFieldDef("manDownConfig", "action", "Action",
                "Accessory Options", "enum", group="Man Down",
                enum_values=["MD_EMERGENCY_CALL", "MD_ALERT_ONLY"],
                display_map={"MD_EMERGENCY_CALL": "Emergency Call",
                             "MD_ALERT_ONLY": "Alert Only"},
                description="What happens when Man Down triggers"),

    # ── Clock Settings ───────────────────────────────────────────────
    XmlFieldDef("TimeDateCfg", "time", "Display Time",
                "Clock Settings", "enum",
                enum_values=["TIME_12_HOUR_FORMAT", "TIME_24_HOUR_FORMAT"],
                display_map={"TIME_12_HOUR_FORMAT": "12 Hour",
                             "TIME_24_HOUR_FORMAT": "24 Hour"},
                description="12 or 24 hour time display"),
    XmlFieldDef("TimeDateCfg", "zone", "Time Zone",
                "Clock Settings", "enum",
                enum_values=[
                    "BIT", "SST", "HST", "AKST", "PST", "MST",
                    "CST", "EST", "AST", "ART", "BRST", "AZOT",
                    "GMT", "CET", "EET", "MSK", "GST", "PKT",
                    "BST", "ICT", "HKT", "JST", "AEST", "SBT",
                    "NZST", "PHOT", "LINT",
                ],
                display_map={
                    "BIT": "UTC-12", "SST": "UTC-11",
                    "HST": "UTC-10", "AKST": "UTC-9",
                    "PST": "UTC-8", "MST": "UTC-7",
                    "CST": "UTC-6", "EST": "UTC-5",
                    "AST": "UTC-4", "ART": "UTC-3",
                    "BRST": "UTC-2", "AZOT": "UTC-1",
                    "GMT": "UTC+0", "CET": "UTC+1",
                    "EET": "UTC+2", "MSK": "UTC+3",
                    "GST": "UTC+4", "PKT": "UTC+5",
                    "BST": "UTC+6", "ICT": "UTC+7",
                    "HKT": "UTC+8", "JST": "UTC+9",
                    "AEST": "UTC+10", "SBT": "UTC+11",
                    "NZST": "UTC+12", "PHOT": "UTC+13",
                    "LINT": "UTC+14",
                },
                description="Radio time zone (UTC-12 to UTC+14)"),

    # ── Unity XG100 Portable Options ─────────────────────────────────
    XmlFieldDef("miscConfig", "p25Optimize",
                "Optimize Conv P25 Battery Life",
                "Unity XG100 Portable Options", "onoff",
                description="Optimize radio for P25 conventional operation"),
    XmlFieldDef("miscConfig", "password", "Channel Edit Password",
                "Unity XG100 Portable Options", "string",
                description="Password for channel editing (4 digits)"),
    XmlFieldDef("miscConfig", "maintenancePassword",
                "Maintenance Password",
                "Unity XG100 Portable Options", "string",
                description="Password for maintenance mode (4 digits)"),

    # ── Programmable Buttons ──────────────────────────────────────────
    # progButtons container attributes (switch functions)
    XmlFieldDef("progButtons", "_2PosFunction", "2-Position Switch",
                "Programmable Buttons", "enum", group="Switches",
                display_map=SWITCH_FUNCTION_NAMES,
                description="Function assigned to 2-position switch"),
    XmlFieldDef("progButtons", "_2PosAValue", "2-Pos A Value",
                "Programmable Buttons", "string", group="Switches",
                description="2-position switch A value"),
    XmlFieldDef("progButtons", "_2PosBValue", "2-Pos B Value",
                "Programmable Buttons", "string", group="Switches",
                description="2-position switch B value"),
    XmlFieldDef("progButtons", "_2PosA_VAIndex", "2-Pos A Index",
                "Programmable Buttons", "int", group="Switches",
                description="2-position switch A value index"),
    XmlFieldDef("progButtons", "_2PosB_VAIndex", "2-Pos B Index",
                "Programmable Buttons", "int", group="Switches",
                description="2-position switch B value index"),
    XmlFieldDef("progButtons", "_3PosFunction", "3-Position Switch",
                "Programmable Buttons", "enum", group="Switches",
                display_map=SWITCH_FUNCTION_NAMES,
                description="Function assigned to 3-position switch"),
    XmlFieldDef("progButtons", "_3PosAFunc", "3-Pos A Function",
                "Programmable Buttons", "enum", group="Switches",
                display_map=SWITCH_FUNCTION_NAMES,
                description="3-position switch position A function"),
    XmlFieldDef("progButtons", "_3PosBFunc", "3-Pos B Function",
                "Programmable Buttons", "enum", group="Switches",
                display_map=SWITCH_FUNCTION_NAMES,
                description="3-position switch position B function"),
    XmlFieldDef("progButtons", "_3PosCFunc", "3-Pos C Function",
                "Programmable Buttons", "enum", group="Switches",
                display_map=SWITCH_FUNCTION_NAMES,
                description="3-position switch position C function"),
    XmlFieldDef("progButtons", "_3PosAIndex", "3-Pos A Index",
                "Programmable Buttons", "int", group="Switches",
                description="3-position switch position A index"),
    XmlFieldDef("progButtons", "_3PosBIndex", "3-Pos B Index",
                "Programmable Buttons", "int", group="Switches",
                description="3-position switch position B index"),
    XmlFieldDef("progButtons", "_3PosCIndex", "3-Pos C Index",
                "Programmable Buttons", "int", group="Switches",
                description="3-position switch position C index"),
    XmlFieldDef("progButtons", "_3PosAValue", "3-Pos A Value",
                "Programmable Buttons", "string", group="Switches",
                description="3-position switch position A value"),
    XmlFieldDef("progButtons", "_3PosBValue", "3-Pos B Value",
                "Programmable Buttons", "string", group="Switches",
                description="3-position switch position B value"),
    XmlFieldDef("progButtons", "_3PosCValue", "3-Pos C Value",
                "Programmable Buttons", "string", group="Switches",
                description="3-position switch position C value"),

    # progButton child elements (side buttons)
    XmlFieldDef("progButton", "function", "Function",
                "Programmable Buttons", "enum", group="Side Buttons",
                display_map=BUTTON_FUNCTION_NAMES,
                description="Function assigned to this button"),
    XmlFieldDef("progButton", "delay", "Delay",
                "Programmable Buttons", "string", group="Side Buttons",
                description="Button press delay (seconds)"),
    XmlFieldDef("progButton", "extraData", "Extra Data",
                "Programmable Buttons", "string", group="Side Buttons",
                description="Additional button configuration data"),

    # accessoryButton child elements
    XmlFieldDef("accessoryButton", "function", "Function",
                "Accessory Buttons", "enum", group="Accessory Buttons",
                display_map=BUTTON_FUNCTION_NAMES,
                description="Function assigned to this accessory button"),
    XmlFieldDef("accessoryButton", "extraData", "Extra Data",
                "Accessory Buttons", "string", group="Accessory Buttons",
                description="Additional accessory button data"),

    # ── Short Menu ────────────────────────────────────────────────────
    XmlFieldDef("shortMenuItem", "name", "Menu Item",
                "Short Menu", "enum",
                display_map=SHORT_MENU_NAMES,
                description="Short menu item assignment"),
    XmlFieldDef("shortMenuItem", "extraData", "Extra Data",
                "Short Menu", "string",
                description="Additional menu item data"),
]

# Index by (element, attribute) for quick lookup
XML_FIELD_INDEX = {(f.element, f.attribute): f for f in XML_FIELDS}

# Index by category
XML_FIELDS_BY_CATEGORY = {}
for _f in XML_FIELDS:
    XML_FIELDS_BY_CATEGORY.setdefault(_f.category, []).append(_f)


# ─── XG-100P Factory Defaults ────────────────────────────────────────
# From baseline: "new radio - xg 100 portable .PRS"

XG100P_DEFAULTS = {
    "audioConfig": {
        "speakerMode": "ON",
        "pttMode": "ON",
        "noiseCancellation": "OFF",
        "tones": "OFF",
        "cctTimer": "120",
        "minVol": "0",
        "pttAudio": "RADIO_ACCESSORY",
    },
    "audioConfig_internal_mic": {
        "alc": "OFF",
        "gain": "0",
    },
    "audioConfig_external_mic": {
        "alc": "OFF",
        "gain": "0",
    },
    "accessoryConfig": {
        "noiseCancellation": "ON",
        "micSelectMode": "TOP",
        "pttMode": "BOTH",
    },
    "manDownConfig": {
        "inactivityTime": "240",
        "warningTime": "30",
        "sensitivity": "0",
        "action": "MD_EMERGENCY_CALL",
    },
    "miscConfig": {
        "batteryType": "LITHIUM_ION_POLY",
        "keypadTones": "OFF",
        "topFpMode": "BL_MOMENTARY",
        "topFpOrient": "FRONT",
        "topFpIntensity": "5",
        "topFpTimeout": "30",
        "frontFpMode": "BL_MOMENTARY",
        "frontFpIntensity": "8",
        "frontFpTimeout": "30",
        "enableTriColorLed": "ON",
        "topColorInvert": "OFF",
        "p25Optimize": "ON",
    },
    "gpsConfig": {
        "gpsMode": "ON",
        "type": "INTERNAL_GPS",
        "operationMode": "INTERNAL",
        "mapDatum": "DATUM_WGD",
        "positionFormat": "LAT_LONG_DMS",
        "linearUnits": "STATUTE",
        "angularUnits": "CARDINAL",
        "elevationBasis": "SEA_LEVEL",
        "gridDigits": "10",
        "northing": "TRUE",
    },
    "bluetoothConfig": {
        "friendlyName": "MY RADIO",
        "btMode": "OFF",
        "btAdminMode": "ON",
    },
    "TimeDateCfg": {
        "time": "TIME_12_HOUR_FORMAT",
        "zone": "EST",
        "date": "US_DATE_FORMAT",
    },
}

ACCESSORY_DEVICE_DEFAULTS = bytes([
    0x00,  # PTT Mode: BOTH
    0x01,  # Noise Cancellation: ON
    0x01,  # Mic Selection: TOP
    0x00,  # Man Down Sensitivity: OFF
    0x1E,  # Unknown (30)
    0x00,  # Unknown
    0x00,  # Unknown
    0xF0,  # Man Down Detection Delay: 240
])
