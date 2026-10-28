"""Session capture: every byte that crossed a link, in order.

A capture is a JSON Lines file.  The first line describes the session; each
later line is one chunk as it was read, or an event such as a modem-line
change::

    {"capture": "quickprs", "version": 1, "started": "...", "note": "..."}
    {"t": 0.0123, "dir": "pc>radio", "hex": "a5 01 ..."}
    {"t": 0.0456, "dir": "radio>pc", "hex": "5a 01 ..."}
    {"t": 0.0460, "event": "pc dtr=1 rts=0"}

``t`` is seconds since the session started.  Directions are named from the
radio's side of the conversation: ``pc>radio`` is what RPM (or the PC)
sent, ``radio>pc`` what the radio answered.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import threading
import time

PC_TO_RADIO = "pc>radio"
RADIO_TO_PC = "radio>pc"
DIRECTIONS = (PC_TO_RADIO, RADIO_TO_PC)


@dataclass
class Chunk:
    t: float
    direction: str
    data: bytes


@dataclass
class Capture:
    chunks: list = field(default_factory=list)
    events: list = field(default_factory=list)   # (t, text)
    header: dict = field(default_factory=dict)

    def stream(self, direction):
        """All bytes sent one way, joined."""
        return b"".join(c.data for c in self.chunks
                        if c.direction == direction)

    def total(self, direction=None):
        return sum(len(c.data) for c in self.chunks
                   if direction is None or c.direction == direction)


class CaptureWriter:
    """Append chunks to a capture file as they happen.

    Each line is flushed at once, so a crash or Ctrl+C keeps everything
    read so far, and a lock keeps lines whole when two threads (the two
    directions of a relay) write at the same time.
    """

    def __init__(self, path, note=""):
        self._f = open(path, "w", encoding="utf-8", newline="\n")
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        header = {"capture": "quickprs", "version": 1,
                  "started": datetime.now(timezone.utc).isoformat(
                      timespec="seconds")}
        if note:
            header["note"] = note
        self._write(header)

    def _write(self, obj):
        with self._lock:
            self._f.write(json.dumps(obj) + "\n")
            self._f.flush()

    def _now(self):
        return round(time.monotonic() - self._t0, 6)

    def add(self, direction, data, t=None):
        """Log a chunk; ``t`` (seconds since the start) defaults to now,
        and is given when the chunk comes from a trace with its own
        times."""
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {direction!r}")
        if data:
            self._write({"t": self._now() if t is None else t,
                         "dir": direction, "hex": data.hex(" ")})

    def event(self, text):
        self._write({"t": self._now(), "event": str(text)})

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_capture(path):
    """Load a capture file written by :class:`CaptureWriter`."""
    cap = Capture()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "capture" in obj:
                cap.header = obj
            elif "event" in obj:
                cap.events.append((float(obj.get("t", 0)), obj["event"]))
            elif obj.get("dir") in DIRECTIONS:
                cap.chunks.append(Chunk(float(obj["t"]), obj["dir"],
                                        bytes.fromhex(obj["hex"])))
            else:
                raise ValueError(f"{path}:{n}: not a capture line")
    return cap


def hexdump(data, width=16, offset=0):
    """Classic offset / hex / ASCII lines."""
    lines = []
    for i in range(0, len(data), width):
        row = data[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in row)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{offset + i:08x}  {hexpart:<{width * 3}} {text}")
    return lines
