"""Listen on a radio's port without sending anything.

Useful first contact: it shows whether the radio's Bluetooth serial service
connects at all and whether the radio says anything unprompted (NMEA from
GPS, PPP frames for data, a text banner ...).  It never writes a byte.
"""

import re
import time

from .capture import RADIO_TO_PC

_NMEA = re.compile(rb"\$(G[PNLA]|P[A-Z]{3})[A-Z]{3},[^\r\n*]*\*[0-9A-F]{2}")


def classify(data):
    """Best guess at what a received byte stream is, as a short phrase."""
    if not data:
        return "nothing received"
    if _NMEA.search(data):
        return "NMEA sentences (GPS position output)"
    if data.count(b"\x7e") >= 2 and (b"\xff\x03" in data or
                                      b"\xff\x7d\x23" in data):
        return "PPP frames (HDLC framing, 0x7E flags)"
    text = data.strip(b"\r\n\x00")
    if re.search(rb"(^|\r|\n)(OK|ERROR|CONNECT|RING|AT[A-Z])", data):
        return "AT/modem text"
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in text)
    if text and printable / len(text) > 0.9:
        return "plain text"
    return "binary"


def listen(link, seconds, writer=None, on_chunk=None, clock=time.monotonic):
    """Read from ``link`` for ``seconds``; return everything received.

    ``link`` needs ``read(n)`` and ``in_waiting``; nothing is written to
    it.  Each chunk goes to ``writer`` (a CaptureWriter) and ``on_chunk``.
    """
    received = bytearray()
    end = clock() + seconds
    while clock() < end:
        data = link.read(max(1, getattr(link, "in_waiting", 0) or 1))
        if data:
            received += data
            if writer is not None:
                writer.add(RADIO_TO_PC, data)
            if on_chunk is not None:
                on_chunk(data)
    return bytes(received)
