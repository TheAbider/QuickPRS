"""PRS file parser — splits .PRS binary into ordered sections for lossless roundtrip.

Strategy: Find all 0xFFFF markers, split into sections. Each section stores its
raw bytes verbatim. Class-name sections also store the parsed class name.
Writer just concatenates raw bytes → guaranteed byte-identical output.
"""

from dataclasses import dataclass, field
from pathlib import Path
import struct

from .binary_io import find_all_ffff, try_read_class_name


@dataclass
class Section:
    """One section of a .PRS file, delimited by 0xFFFF markers."""
    offset: int           # byte offset in original file
    raw: bytes            # complete raw bytes including the ffff marker
    class_name: str = ""  # e.g. "CPersonality", "CP25TrkSystem", "" for data sections


@dataclass
class PRSFile:
    """Parsed .PRS file — ordered list of sections.

    ``archive_ok`` records whether the bytes followed RPM's archive layout
    when they were loaded (see archive.py); write_prs uses it to refuse an
    edit that broke a readable file.
    """
    sections: list = field(default_factory=list)
    filepath: str = ""
    file_size: int = 0
    archive_ok: object = None

    def get_sections_by_class(self, class_name):
        """Get all sections with a given class name."""
        return [s for s in self.sections if s.class_name == class_name]

    def get_section_by_class(self, class_name):
        """Get first section with a given class name, or None."""
        for s in self.sections:
            if s.class_name == class_name:
                return s
        return None

    def to_bytes(self):
        """Reassemble all sections back into binary. Lossless roundtrip."""
        return b''.join(s.raw for s in self.sections)

    def summary(self):
        """Print a human-readable summary of file structure."""
        lines = [f"PRS File: {self.filepath} ({self.file_size} bytes)"]
        lines.append(f"Sections: {len(self.sections)}")
        lines.append("")
        for i, s in enumerate(self.sections):
            name = s.class_name if s.class_name else "(data)"
            lines.append(f"  [{i:3d}] 0x{s.offset:04x} {len(s.raw):5d} bytes  {name}")
        return "\n".join(lines)


# Classes whose objects hold user values (talkgroup and key IDs, unit IDs,
# frequencies) that can contain the bytes FF FF.  The splitter would start
# a new section there; such pieces belong to the section before them.
_JOIN_CONTINUATIONS = frozenset({
    "CTrunkChannel", "CConvChannel", "CP25Group", "CP25ConvChannel",
    "CDefaultIdenElem", "CICall", "CPhoneCall", "CP25TrkWan",
})


def _join_continuations(sections):
    joined = []
    for sec in sections:
        if (joined and not sec.class_name and
                joined[-1].class_name in _JOIN_CONTINUATIONS and
                sec.raw != b'\xff\xff' and
                not sec.raw.startswith(b'\xff\xff\x00\x01')):
            prev = joined[-1]
            joined[-1] = Section(offset=prev.offset, raw=prev.raw + sec.raw,
                                 class_name=prev.class_name)
        else:
            joined.append(sec)
    return joined


def parse_prs(filepath):
    """Parse a .PRS file into an ordered list of sections.

    Each section starts at a 0xFFFF marker and extends to the next marker.
    Sections with valid class names get their class_name field populated.
    """
    path = Path(filepath)
    data = path.read_bytes()

    markers = find_all_ffff(data)

    if not markers:
        raise ValueError(f"No ffff markers found in {filepath}")

    sections = []
    for i, marker_offset in enumerate(markers):
        # Section extends from this marker to the next (or end of file)
        if i + 1 < len(markers):
            next_offset = markers[i + 1]
        else:
            next_offset = len(data)

        raw = data[marker_offset:next_offset]

        # Try to identify the class name
        class_name, _ = try_read_class_name(data, marker_offset)

        sections.append(Section(
            offset=marker_offset,
            raw=raw,
            class_name=class_name or "",
        ))

    prs = PRSFile(
        sections=_join_continuations(sections),
        filepath=str(path),
        file_size=len(data),
        archive_ok=_archive_readable(data),
    )
    return prs


def _archive_readable(data):
    from .archive import read_document, WalkError
    try:
        read_document(data, lenient=True)
        return True
    except (WalkError, IndexError, UnicodeDecodeError, struct.error):
        return False


def parse_prs_bytes(data, verify=True):
    """Parse PRS data from raw bytes (no file I/O).

    Used for undo/restore operations where we have the bytes in memory.
    ``verify=False`` skips the archive check (for callers that only want
    the sections of bytes they just serialized).
    """
    markers = find_all_ffff(data)

    if not markers:
        raise ValueError("No ffff markers found in data")

    sections = []
    for i, marker_offset in enumerate(markers):
        if i + 1 < len(markers):
            next_offset = markers[i + 1]
        else:
            next_offset = len(data)

        raw = data[marker_offset:next_offset]
        class_name, _ = try_read_class_name(data, marker_offset)

        sections.append(Section(
            offset=marker_offset,
            raw=raw,
            class_name=class_name or "",
        ))

    return PRSFile(
        sections=_join_continuations(sections),
        filepath="(from bytes)",
        file_size=len(data),
        archive_ok=_archive_readable(data) if verify else None,
    )
