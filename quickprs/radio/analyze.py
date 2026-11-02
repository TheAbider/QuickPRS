"""Summarise a capture and look for personality data inside it.

Without the protocol, the useful questions about a capture of RPM reading
a radio are: how much went each way, how the bytes are chunked, which
byte patterns open messages, what text is in it, and whether the
personality crosses the link in the same MFC archive form a .PRS file
uses (class headers ``FF FF`` + schema + name, see archive.py).  If it
does, the archive can be cut out and saved as a .PRS file.
"""

import bisect
from collections import Counter
from dataclasses import dataclass, field
import re
import struct

from .capture import DIRECTIONS, PC_TO_RADIO, RADIO_TO_PC

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


def has_personality(data):
    """True when ``data`` holds a CPersonality class header: a .PRS
    personality starts there."""
    return any(h.name == "CPersonality" for h in find_class_headers(data))


def session_kind(capture):
    """A sentence on what the capture's session looks like: a read (the
    radio sent a personality), a write (RPM sent one), or neither."""
    sent = capture.stream(PC_TO_RADIO)
    answers = capture.stream(RADIO_TO_PC)
    if not sent and not answers:
        return "Nothing crossed the link."
    if has_personality(sent):
        return "Looks like a write: RPM sent a personality."
    if has_personality(answers):
        return ("Looks like a read: the radio sent a personality and RPM "
                "did not.")
    return ("Neither side sent a .PRS personality. If RPM read or wrote "
            "the radio in this session, either large packets were left "
            "out of the trace (the sniffer's Full Packet Logging was off) "
            "or the personality crosses the link in another form.")


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


@dataclass
class Alignment:
    """Where the bytes of a known file sit in a stream."""
    pieces: list = field(default_factory=list)   # (stream offset, file
                                                 # offset, length)
    gaps: list = field(default_factory=list)     # (stream offset, bytes
                                                 # between two pieces)
    missing: list = field(default_factory=list)  # (file offset, length)
                                                 # not found

    @property
    def found(self):
        return sum(n for _, _, n in self.pieces)


def _run(stream, j, known, k):
    """How many bytes from stream[j] and known[k] on are the same."""
    limit = min(len(stream) - j, len(known) - k)
    n, step = 0, 16
    while n < limit:
        m = min(limit, n + step)
        if stream[j + n:j + m] == known[k + n:k + m]:
            n, step = m, step * 2
        elif step > 1:
            step //= 2
        else:
            break
    return n


def _distinct(data, n=4):
    """True when ``data`` holds at least ``n`` different byte values: a run
    of zeros, say, matches in too many places to place anything."""
    return len(set(data)) >= n


def _continue(stream, known, s, k, anchor, window, slack=32):
    """(file offset, stream offset, length) where known[k:] goes on in
    stream[s:s + window], or None.

    Of the places within ``slack`` bytes of the first match, the one where
    the file runs on longest wins: when the file's next bytes also match
    in the framing (zeros, say), the real start runs on through the
    packet.  A match further away than framing counts only when it runs on
    for a while through varied bytes: a few bytes the file repeats
    elsewhere are no place to go on from."""
    needle = known[k:k + anchor]
    j = stream.find(needle, s, min(len(stream), s + window) + len(needle))
    if j < 0:
        return None
    best = (j, _run(stream, j, known, k))
    while True:
        j = stream.find(needle, j + 1, best[0] + slack + len(needle))
        if j < 0:
            break
        n = _run(stream, j, known, k)
        if n > best[1]:
            best = (j, n)
    j, n = best
    if (j - s <= 64 or k + n == len(known)
            or (n >= 64 and _distinct(stream[j:j + n]))):
        return k, j, n
    return None


_GRAM = 12


def _grams(known):
    """Where each run of _GRAM bytes starts in ``known``."""
    at = {}
    for i in range(len(known) - _GRAM + 1):
        at.setdefault(known[i:i + _GRAM], []).append(i)
    return at


def _resync(stream, known, s, k, grams, min_run=32):
    """(file offset, stream offset, length) of the first place from
    stream[s] on where the file goes on, at or after known[k], with a run
    of at least ``min_run`` bytes; or None.  Used when the file's next
    bytes are not in the stream nearby: a packet missing from the trace,
    a byte RPM's saved copy has differently, or a long stretch of other
    traffic.  Only varied runs place it; the run is then taken back over
    any matching bytes just before it."""
    for p in range(s, len(stream) - _GRAM + 1):
        gram = stream[p:p + _GRAM]
        places = grams.get(gram) if _distinct(gram) else None
        if not places:
            continue
        i = bisect.bisect_left(places, k)
        best = None
        for kk in places[i:i + 8]:
            n = _run(stream, p, known, kk)
            if best is None or n > best[1]:
                best = (kk, n)
        if best is None:
            continue
        kk, n = best
        if n >= min_run or kk + n == len(known) or p + n == len(stream):
            while p > s and kk > k and stream[p - 1] == known[kk - 1]:
                p, kk, n = p - 1, kk - 1, n + 1
            return kk, p, n
    return None


def align(stream, known, anchor=16, window=4096):
    """Find ``known`` (a personality RPM saved) in ``stream`` (the radio's
    answers), in order, allowing other bytes between the pieces.

    When the radio sends the personality as it is saved, cut into packets,
    each piece is one packet's data and the bytes between two pieces are
    the end of one packet and the start of the next: the framing.  Where
    the file and the stream disagree (a byte RPM changes when it saves, a
    packet missing from the trace), the file's bytes are skipped and noted
    as missing.  Where framing bytes happen to equal the file's next bytes
    (zeros, often), a piece can start or end a byte or two off."""
    al = Alignment()
    s = k = 0
    grams = None
    while k < len(known) and s < len(stream):
        hit = _continue(stream, known, s, k, anchor, window)
        if hit is None:
            if grams is None:
                grams = _grams(known)
            hit = _resync(stream, known, s, k, grams)
            if hit is None:
                break
        start, j, n = hit
        if start > k:
            al.missing.append((k, start - k))
        if j > s and al.pieces:
            al.gaps.append((s, stream[s:j]))
        al.pieces.append((j, start, n))
        s, k = j + n, start + n
    if k < len(known):
        al.missing.append((k, len(known) - k))
    return al


def alignment_report(al, stream, known_len, where="the radio's answers",
                     top=6):
    """Lines describing an Alignment of a known file in ``stream``
    (``where`` says which stream it is)."""
    pct = 100.0 * al.found / known_len if known_len else 0.0
    lines = [f"{al.found:,} of its {known_len:,} bytes ({pct:.1f}%) are in "
             f"{where}, in order, in {len(al.pieces):,} pieces."]
    if not al.pieces:
        lines.append(f"  None of it is in {where} as RPM saves it: if it "
                     f"crossed the link that way, it went in another form.")
        return lines
    sizes = Counter(n for _, _, n in al.pieces)
    lines.append("  piece sizes: " + ", ".join(
        f"{size:,} B x{n}" for size, n in sizes.most_common(top)))
    first = al.pieces[0][0]
    lead = stream[max(0, first - 16):first]
    lines.append(f"  before the first piece (stream offset 0x{first:x}): "
                 f"{lead.hex(' ') or 'nothing'}")
    if al.gaps:
        gaps = Counter(len(g) for _, g in al.gaps)
        lines.append("  between pieces (the framing, if a piece is one "
                     "packet's data): " + ", ".join(
                         f"{size:,} B x{n}" for size, n in
                         gaps.most_common(top)))
        for offset, gap in al.gaps[:top]:
            more = " ..." if len(gap) > 24 else ""
            lines.append(f"    0x{offset:06x}  {gap[:24].hex(' ')}{more}")
    last = al.pieces[-1]
    after = stream[last[0] + last[2]:last[0] + last[2] + 16]
    lines.append(f"  after the last piece: {after.hex(' ') or 'nothing'}")
    if al.missing:
        total = sum(n for _, n in al.missing)
        lines.append(f"  not found: {total:,} bytes in "
                     f"{len(al.missing):,} places, the first at file "
                     f"offset 0x{al.missing[0][0]:x} (RPM's saved file "
                     f"differs there, or those packets are not in the "
                     f"trace)")
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
    lines.append(session_kind(capture))
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
