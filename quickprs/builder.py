"""Create minimal valid PRS files from scratch.

Builds a complete .PRS binary without needing an existing file as a template.
Uses the section builders from record_types.py to construct each section.
"""

from .prs_parser import PRSFile, Section, parse_prs_bytes
from .binary_io import (
    SECTION_MARKER, FILE_TERMINATOR,
    write_lps, write_uint8, write_uint16_le,
)
from .record_types import (
    Personality, build_personality_section,
    ConvSystemConfig,
    ConvChannel, ConvSet,
    build_conv_channel_section, build_conv_set_section,
    build_wan_opts_section, build_wan_section,
    build_class_header,
)


# Template for CT99 data section: 103 zero bytes with two 2-byte markers
# at positions 33-34 and 68-69. Marker values vary by file but 5e 80 is
# common for simple files created by RPM.
_CT99_CORE = bytearray(103)
_CT99_CORE[33] = 0x5e
_CT99_CORE[34] = 0x80
_CT99_CORE[68] = 0x5e
_CT99_CORE[69] = 0x80
_CT99_CORE = bytes(_CT99_CORE)


def _build_type99_opts_section():
    """Build a CType99Opts section (header + uint16(0) + uint16(0x24))."""
    header = build_class_header('CType99Opts', 0x64, 0x00)
    return header + write_uint16_le(0) + write_uint16_le(0x24)


def _build_ct99_section(filename=""):
    """Build a CT99 section with optional filename and band limits.

    Args:
        filename: PRS filename to embed (e.g. "New Personality.PRS").
                  If provided, appends filename + band limits after the
                  103-byte core block. If empty, uses just the core block.
    """
    header = build_class_header('CT99', 0x64, 0x00)
    parts = [header, _CT99_CORE]

    if filename:
        # Append: LPS(filename) + 3 zero bytes + uint8(0x0e) + 3 zeros
        # + 4 band-limit doubles (136.0, 870.0, 136.0, 870.0) + 0x7e + 00 01 00
        import struct
        parts.append(write_lps(filename))
        parts.append(b'\x00\x00\x00')
        parts.append(write_uint8(0x0e))
        parts.append(b'\x00' * 6)
        parts.append(struct.pack('<d', 136.0))   # tx_min
        parts.append(struct.pack('<d', 870.0))   # tx_max
        parts.append(struct.pack('<d', 136.0))   # rx_min
        parts.append(struct.pack('<d', 870.0))   # rx_max
        parts.append(b'\x7e\x00\x01\x00')

    return b''.join(parts)


def create_blank_prs(
    filename="New Personality.PRS",
    saved_by="",
):
    """Create a minimal valid PRS file from scratch.

    The resulting file contains:
      - CPersonality (file metadata)
      - CConvSystem header + data section (one conventional system)
      - CConvSet + CConvChannel (one set with one default channel)
      - CP25tWanOpts + CP25TrkWan (empty WAN, required by format)
      - CType99Opts + CT99 (Type 99 decode, always present)
      - File terminator (ffff ffff0001)

    Args:
        filename: PRS filename stored in the personality section.
        saved_by: user name stored in personality (default empty).

    Returns:
        PRSFile: parsed PRS object that roundtrips through to_bytes().

    The file is built as an archive.Document, so its object headers, class
    tags and list counts follow the layout RPM itself writes (header and
    tail fields are copied from RPM-saved files).
    """
    from . import archive
    from .archive import Obj, ObjList

    # 1. CPersonality header: the 0x08-separated name/version block, four
    #    flag bytes, six strings and the radio type list (101, 126 = XG-100P),
    #    as in a fresh RPM personality.
    header = build_personality_section(Personality(
        filename=filename, saved_by=saved_by, version="0014",
        mystery4=b'\x01\x00\x00\x00', version_str="1", footer=b''))
    header = header[6 + len("CPersonality"):] + b'\x02\x00\x65\x00\x7e\x00'

    # 2. One conventional system and its set with a single channel.
    conv_sys = ConvSystemConfig(
        system_name="Conv 1",
        long_name="",
        conv_set_name="Conv 1",
    )
    default_channel = ConvChannel(
        short_name="CH 1",
        tx_freq=146.520,
        rx_freq=146.520,
        long_name="Channel 1",
    )
    default_set = ConvSet(
        name="Conv 1",
        channels=[default_channel],
        config_flag=0x01,
        has_band_limits=0x00,
    )
    conv_set_obj = Obj("CConvSet", [
        ObjList("items", [Obj("CConvChannel", [default_channel.to_bytes()])]),
        default_set.metadata_to_bytes(),
    ])

    # 3. Options: an empty WAN list (P25 systems add their entries) and the
    #    Type 99 options with their three tone objects.
    import struct
    options = [
        Obj("CP25tWanOpts", [ObjList("WAN entries")]),
        Obj("CType99Opts", [
            b'\x00\x00\x24\x00',
            ObjList("Type 99 tones",
                    [Obj("CT99", [bytes(33)]) for _ in range(3)],
                    counted=False),
        ]),
    ]

    # 4. Personality name, user name and the radio's band limits.
    doc_fields = (write_lps(filename) + b'\x00\x00' + write_lps(saved_by) +
                  b'\x0e\x00' + struct.pack('<4d', 136.0, 870.0, 136.0, 870.0)
                  + b'\x7e\x00')

    root = Obj("CPersonality", [
        header,
        ObjList("systems", [Obj("CConvSystem", [conv_sys.object_data()])]),
        ObjList("trunk sets"),
        b'\x00' * 6,
        ObjList("conv sets", [conv_set_obj]),
        ObjList("options", options),
        doc_fields,
        ObjList("group sets"),
        ObjList("P25 conv sets"),
        ObjList("unknown list"),
        ObjList("IDEN sets"),
        # Remaining document fields of a personality without platformConfig
        # XML, as RPM writes them.
        b'\x00' * 39 + FILE_TERMINATOR,
    ])
    raw = archive.serialize(archive.Document(root))
    prs = parse_prs_bytes(raw)
    prs.filepath = filename

    return prs
