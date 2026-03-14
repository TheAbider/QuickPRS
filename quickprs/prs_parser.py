"""PRS file parser — splits .PRS binary into ordered sections for lossless roundtrip.

Strategy: Find all 0xFFFF markers, split into sections. Each section stores its
raw bytes verbatim. Class-name sections also store the parsed class name.
Writer just concatenates raw bytes → guaranteed byte-identical output.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .binary_io import find_all_ffff, try_read_class_name


@dataclass
class Section:
    """One section of a .PRS file, delimited by 0xFFFF markers."""
    offset: int           # byte offset in original file
    raw: bytes            # complete raw bytes including the ffff marker
    class_name: str = ""  # e.g. "CPersonality", "CP25TrkSystem", "" for data sections


@dataclass
class PRSFile:
    """Parsed .PRS file — ordered list of sections."""
    sections: list = field(default_factory=list)
    filepath: str = ""
    file_size: int = 0

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
        sections=sections,
        filepath=str(path),
        file_size=len(data),
    )
    return prs


def parse_prs_bytes(data):
    """Parse PRS data from raw bytes (no file I/O).

    Used for undo/restore operations where we have the bytes in memory.
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
        sections=sections,
        filepath="(from bytes)",
        file_size=len(data),
    )
