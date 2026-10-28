"""Summarise a capture and look for personality data inside it.

Without the protocol, the useful questions about a capture of RPM reading
a radio are: how much went each way, how the bytes are chunked, which
byte patterns open messages, what text is in it, and whether the
personality crosses the link in the same MFC archive form a .PRS file
uses (class headers ``FF FF`` + schema + name, see archive.py).  If it
does, the archive can be cut out and saved as a .PRS file.
"""

from collections import Counter
from dataclasses import dataclass, field
import re
import struct

from .capture import DIRECTIONS

_CLASS_NAME = re.compile(rb"C[A-Za-z0-9_]{2,47}")


@dataclass
class ClassHeader:
    offset: int
    schema: int
    name: str


@dataclass
class DirectionSummary:
    direction: str
    total_bytes: int = 0
    chunks: int = 0
    chunk_sizes: Counter = field(default_factory=Counter)
    first_bytes: Counter = field(default_factory=Counter)  # chunk openers
    strings: list = field(default_factory=list)
    class_headers: list = field(default_factory=list)


def find_class_headers(data):
    """Every MFC new-class header in ``data``: FF FF, schema, name length,
    and a class name that looks like RPM's (C + letters/digits)."""
    hits = []
    pos = data.find(b"\xff\xff")
    while pos >= 0:
        if pos + 6 <= len(data):
            schema, n = struct.unpack_from("<HH", data, pos + 2)
            name = data[pos + 6:pos + 6 + n]
            if (1 <= schema <= 999 and 3 <= n <= 48 and len(name) == n and
                    _CLASS_NAME.fullmatch(name)):
                hits.append(ClassHeader(pos, schema, name.decode("ascii")))
        pos = data.find(b"\xff\xff", pos + 1)
    return hits


def printable_strings(data, min_len=6):
    """ASCII runs of at least ``min_len`` characters, with offsets."""
    return [(m.start(), m.group().decode("ascii"))
            for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data)]


def summarize(capture, opener_len=2):
    """A DirectionSummary for each direction."""
    out = {}
    for direction in DIRECTIONS:
        s = DirectionSummary(direction)
        for c in capture.chunks:
            if c.direction != direction:
                continue
            s.chunks += 1
            s.total_bytes += len(c.data)
            s.chunk_sizes[len(c.data)] += 1
            s.first_bytes[c.data[:opener_len].hex(" ")] += 1
        stream = capture.stream(direction)
        s.strings = printable_strings(stream)
        s.class_headers = find_class_headers(stream)
        out[direction] = s
    return out


@dataclass
class Message:
    t: float
    direction: str
    data: bytes


def messages(capture, gap=0.05):
    """The conversation as messages: consecutive chunks going the same way
    with less than ``gap`` seconds between them are one message (a serial
    read returns whatever has arrived, so one message often comes in
    several chunks)."""
    out = []
    last_t = None
    for c in capture.chunks:
        if (out and out[-1].direction == c.direction
                and last_t is not None and c.t - last_t < gap):
            out[-1].data.extend(c.data)
        else:
            out.append(Message(c.t, c.direction, bytearray(c.data)))
        last_t = c.t
    for m in out:
        m.data = bytes(m.data)
    return out


def transcript(capture, limit=40, width=32, gap=0.05):
    """The first ``limit`` messages, one line each: time, direction,
    length, and the first ``width`` bytes in hex and as text."""
    lines = []
    msgs = messages(capture, gap)
    for m in msgs[:limit]:
        head = m.data[:width]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
        more = " ..." if len(m.data) > width else ""
        lines.append(f"{m.t:9.3f}  {m.direction:8s} {len(m.data):6,} B  "
                     f"{head.hex(' ')}{more}  |{text}|")
    if len(msgs) > limit:
        lines.append(f"... {len(msgs) - limit} more messages")
    return lines


def extract_personality(data):
    """Bytes of a .PRS archive found in ``data``, or None.

    Tries each CPersonality header in turn and keeps the first one the
    archive walker can follow to the end of its IDEN sets.  The walker
    reads everything after them as document fields, so protocol bytes
    after the archive end up in the file too; the result is a starting
    point for comparing against a .PRS that RPM saved, not a finished
    file.
    """
    from .. import archive
    for hit in find_class_headers(data):
        if hit.name != "CPersonality":
            continue
        try:
            doc, _ = archive.read_document(data[hit.offset:], lenient=True)
        except archive.WalkError:
            continue
        return archive.serialize(doc)
    return None


def report(capture, top=8):
    """Human-readable analysis lines."""
    lines = []
    if capture.header:
        lines.append(f"Capture started {capture.header.get('started', '?')}"
                     + (f" ({capture.header['note']})"
                        if capture.header.get("note") else ""))
    if capture.chunks:
        span = capture.chunks[-1].t - capture.chunks[0].t
        lines.append(f"{len(capture.chunks)} chunks over {span:.1f} s, "
                     f"{len(capture.events)} line events")
    msgs = messages(capture)
    for direction, s in summarize(capture).items():
        lines.append("")
        mine = [m for m in msgs if m.direction == direction]
        lines.append(f"{direction}: {s.total_bytes:,} bytes in "
                     f"{s.chunks} chunks, {len(mine)} messages")
        if not s.chunks:
            continue
        sizes = Counter(len(m.data) for m in mine)
        openers = Counter(m.data[:2].hex(" ") for m in mine)
        lines.append("  common message sizes: " + ", ".join(
            f"{size} B x{n}" for size, n in sizes.most_common(top)))
        lines.append("  common message openers: " + ", ".join(
            f"[{k}] x{n}" for k, n in openers.most_common(top)))
        sizes = ", ".join(f"{size} B x{n}"
                          for size, n in s.chunk_sizes.most_common(top))
        lines.append(f"  common chunk sizes: {sizes}")
        openers = ", ".join(f"[{k}] x{n}"
                            for k, n in s.first_bytes.most_common(top))
        lines.append(f"  common chunk openers: {openers}")
        if s.class_headers:
            names = ", ".join(f"{h.name}@0x{h.offset:x}"
                              for h in s.class_headers[:top])
            more = len(s.class_headers) - top
            lines.append(f"  PRS archive class headers: {names}"
                         + (f" (+{more} more)" if more > 0 else ""))
        else:
            lines.append("  no PRS archive class headers (the data is in "
                         "another form, or compressed/encrypted)")
        if s.strings:
            shown = "; ".join(f"0x{o:x} {t!r}" for o, t in s.strings[:top])
            lines.append(f"  text: {shown}")
    return lines
