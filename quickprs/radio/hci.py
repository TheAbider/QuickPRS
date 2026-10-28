"""Serial data from a Bluetooth HCI trace.

RPM and the radio talk over the Serial Port Profile, which runs on RFCOMM,
which runs on L2CAP, which runs in HCI ACL packets between Windows and its
Bluetooth controller.  Microsoft's Bluetooth Virtual Sniffer (BTVS, part of
the Bluetooth Test Platform) records those HCI packets through Windows'
own tracing and serves them as a pcap stream on TCP for Wireshark.  This
module reads such a stream (or a saved pcap/pcapng file) and undoes the
layers:

    pcap record -> HCI packet (H4 type 2 = ACL data)
               -> L2CAP PDU (reassembled from ACL fragments)
               -> RFCOMM frame (on the channel L2CAP opened for PSM 3)
               -> UIH payload on a data channel = the serial bytes

Only those serial bytes are kept; HCI events, other Bluetooth traffic and
the link keys a full trace can hold are dropped.
"""

from dataclasses import dataclass, field
import struct

# pcap link types (https://www.tcpdump.org/linktypes.html)
LINKTYPE_H4 = 187              # H4 packet, no direction
LINKTYPE_H4_WITH_PHDR = 201    # 4-byte direction (0 = sent, 1 = received)

# H4 packet types
H4_COMMAND, H4_ACL, H4_SCO, H4_EVENT = 1, 2, 3, 4

# HCI events used here
EVT_CONNECTION_COMPLETE = 0x03
EVT_DISCONNECTION_COMPLETE = 0x05

# L2CAP
CID_SIGNALING = 0x0001
L2CAP_CONN_REQ = 0x02
L2CAP_CONN_RSP = 0x03
PSM_RFCOMM = 0x0003

# RFCOMM frame types (P/F bit masked out)
RFCOMM_SABM, RFCOMM_UA, RFCOMM_DM, RFCOMM_DISC, RFCOMM_UIH = (
    0x2F, 0x63, 0x0F, 0x43, 0xEF)
RFCOMM_PF = 0x10

# Directions as the capture files name them (see capture.py)
SENT = "pc>radio"        # host to controller: the PC to the radio
RECEIVED = "radio>pc"


# ── pcap / pcapng ─────────────────────────────────────────────────────

class PcapError(ValueError):
    pass


def _read_exact(stream, n):
    """n bytes, or b"" at a clean end of stream; PcapError if it stops
    part way through."""
    chunks, got = [], 0
    while got < n:
        part = stream.read(n - got)
        if not part:
            if got:
                raise PcapError(f"stream ended inside a record "
                                f"({got} of {n} bytes)")
            return b""
        chunks.append(part)
        got += len(part)
    return b"".join(chunks)


def read_packets(stream):
    """Yield (timestamp in seconds, linktype, packet bytes) from a classic
    pcap or a pcapng stream (a file or a socket's makefile("rb"))."""
    magic = _read_exact(stream, 4)
    if not magic:
        return
    if magic == b"\x0a\x0d\x0d\x0a":
        yield from _read_pcapng(stream, magic)
    else:
        yield from _read_pcap(stream, magic)


def _read_pcap(stream, magic):
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise PcapError(f"not a pcap or pcapng stream (magic {magic.hex()})")
    nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    head = _read_exact(stream, 20)
    if len(head) < 20:
        raise PcapError("pcap header cut short")
    linktype = struct.unpack(endian + "HHiIII", head)[5] & 0x0FFFFFFF
    while True:
        rec = _read_exact(stream, 16)
        if not rec:
            return
        sec, frac, incl, _ = struct.unpack(endian + "IIII", rec)
        data = _read_exact(stream, incl)
        if len(data) < incl:
            raise PcapError("pcap record cut short")
        yield sec + frac / (1e9 if nano else 1e6), linktype, data


def _read_pcapng(stream, magic):
    endian = "<"
    interfaces = []          # (linktype, ticks per second)
    first = True
    while True:
        if first:
            head = magic + _read_exact(stream, 4)
            first = False
        else:
            head = _read_exact(stream, 8)
            if not head:
                return
        btype_raw, blen_raw = head[:4], head[4:8]
        if btype_raw == b"\x0a\x0d\x0d\x0a":           # section header
            bom = _read_exact(stream, 4)
            endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            blen = struct.unpack(endian + "I", blen_raw)[0]
            _read_exact(stream, blen - 12)
            interfaces = []
            continue
        btype, blen = struct.unpack(endian + "II", head)
        body = _read_exact(stream, blen - 8)
        if len(body) < blen - 8:
            raise PcapError("pcapng block cut short")
        body = body[:-4]                                 # trailing length
        if btype == 1:                                   # interface
            linktype = struct.unpack_from(endian + "H", body, 0)[0]
            interfaces.append((linktype, _ts_resolution(body[8:], endian)))
        elif btype == 6:                                 # enhanced packet
            iface, hi, lo, incl = struct.unpack_from(endian + "IIII", body)
            linktype, tps = interfaces[iface]
            yield ((hi << 32 | lo) / tps, linktype, body[20:20 + incl])
        elif btype == 3 and interfaces:                  # simple packet
            linktype, _ = interfaces[0]
            incl = struct.unpack_from(endian + "I", body)[0]
            yield 0.0, linktype, body[4:4 + incl]


def _ts_resolution(options, endian):
    """Ticks per second from an interface block's if_tsresol option
    (default microseconds)."""
    pos = 0
    while pos + 4 <= len(options):
        code, length = struct.unpack_from(endian + "HH", options, pos)
        if code == 0:
            break
        if code == 9 and length >= 1:
            v = options[pos + 4]
            return 2 ** (v & 0x7F) if v & 0x80 else 10 ** v
        pos += 4 + ((length + 3) & ~3)
    return 1_000_000


# ── RFCOMM ────────────────────────────────────────────────────────────

def _crc_table():
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xE0 if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC = _crc_table()


def rfcomm_fcs(data):
    """RFCOMM (GSM 07.10) frame check: CRC-8, polynomial x^8+x^2+x+1."""
    crc = 0xFF
    for b in data:
        crc = _CRC[crc ^ b]
    return 0xFF - crc


@dataclass
class RfcommFrame:
    dlci: int
    frame_type: int        # P/F bit masked out
    pf: bool
    payload: bytes
    credits: int = 0


def parse_rfcomm(data, credit_flow=True):
    """One RFCOMM frame from an L2CAP payload, or None when it is not a
    well-formed frame (bad length or frame check).

    With credit based flow control (as Windows and nearly every stack
    negotiate) a UIH frame on a data channel with P/F set carries one
    credit byte before its payload.
    """
    if len(data) < 4 or not data[0] & 1:
        return None
    addr, ctrl = data[0], data[1]
    if data[2] & 1:
        length, pos = data[2] >> 1, 3
    else:
        if len(data) < 5:
            return None
        length, pos = (data[2] >> 1) | (data[3] << 7), 4
    frame_type, pf = ctrl & ~RFCOMM_PF & 0xFF, bool(ctrl & RFCOMM_PF)
    dlci = addr >> 2
    credits = 0
    if frame_type == RFCOMM_UIH and pf and dlci and credit_flow:
        if pos >= len(data):
            return None
        credits, pos = data[pos], pos + 1
    if pos + length + 1 != len(data):
        return None
    # The check covers address and control on UIH frames, and the length
    # field too on the others
    header_len = 3 if data[2] & 1 else 4
    checked = data[:2] if frame_type == RFCOMM_UIH else data[:header_len]
    if rfcomm_fcs(checked) != data[-1]:
        return None
    return RfcommFrame(dlci, frame_type, pf, bytes(data[pos:pos + length]),
                       credits)


# ── HCI and L2CAP ─────────────────────────────────────────────────────

@dataclass
class _Link:
    """One ACL connection (an HCI handle)."""
    address: str = ""
    partial: dict = field(default_factory=dict)       # direction -> bytes
    rfcomm_cids: dict = field(default_factory=dict)   # direction -> CID
    pending: dict = field(default_factory=dict)       # (dir, id) -> SCID


def format_address(raw6):
    """A BD_ADDR as HCI sends it (little-endian) in the usual text form."""
    return ":".join(f"{b:02X}" for b in reversed(raw6))


class SerialFromHci:
    """Turn HCI packets into the serial data of RFCOMM channels.

    feed() takes one H4 packet with its direction and returns the serial
    chunks it completes, as (direction, bytes).  When ``address`` is given,
    only the link to that device counts (once HCI has said which handle
    that is; a trace started after the connection never says, and then
    every link's RFCOMM data counts).
    """

    def __init__(self, address=None):
        self.address = address.upper() if address else None
        self.links = {}

    def _link(self, handle):
        return self.links.setdefault(handle, _Link())

    def feed(self, direction, packet):
        if not packet:
            return []
        kind = packet[0]
        if kind == H4_EVENT:
            self._event(packet[1:])
            return []
        if kind != H4_ACL or len(packet) < 5:
            return []
        head, length = struct.unpack_from("<HH", packet, 1)
        handle, pb = head & 0x0FFF, (head >> 12) & 0x3
        data = packet[5:5 + length]
        link = self._link(handle)
        if self.address and link.address and link.address != self.address:
            return []
        if pb == 0b01:                     # continuing fragment
            if direction not in link.partial:
                return []
            buf = link.partial[direction] + data
        else:                              # start of an L2CAP PDU
            buf = data
        if len(buf) < 4:
            link.partial[direction] = buf
            return []
        pdu_len, cid = struct.unpack_from("<HH", buf)
        if len(buf) < pdu_len + 4:
            link.partial[direction] = buf
            return []
        link.partial.pop(direction, None)
        return self._l2cap(link, direction, cid, buf[4:4 + pdu_len])

    def _event(self, body):
        if len(body) < 2:
            return
        code = body[0]
        params = body[2:2 + body[1]]
        if code == EVT_CONNECTION_COMPLETE and len(params) >= 9:
            status, handle = params[0], struct.unpack_from("<H", params, 1)[0]
            if status == 0:
                self.links[handle & 0x0FFF] = _Link(
                    address=format_address(params[3:9]))
        elif code == EVT_DISCONNECTION_COMPLETE and len(params) >= 3:
            handle = struct.unpack_from("<H", params, 1)[0] & 0x0FFF
            self.links.pop(handle, None)

    def _l2cap(self, link, direction, cid, payload):
        if cid == CID_SIGNALING:
            self._signaling(link, direction, payload)
            return []
        if cid < 0x0040:
            return []
        known = link.rfcomm_cids.get(direction)
        if known is not None and cid != known:
            return []
        frame = parse_rfcomm(payload)
        if frame is None:
            return []
        if known is None:
            # no connection setup seen: a valid RFCOMM frame names the CID
            link.rfcomm_cids[direction] = cid
        if frame.frame_type == RFCOMM_UIH and frame.dlci and frame.payload:
            return [(direction, frame.payload)]
        return []

    def _signaling(self, link, direction, data):
        pos = 0
        while pos + 4 <= len(data):
            code, ident, length = struct.unpack_from("<BBH", data, pos)
            body = data[pos + 4:pos + 4 + length]
            pos += 4 + length
            if code == L2CAP_CONN_REQ and len(body) >= 4:
                psm, scid = struct.unpack_from("<HH", body)
                if psm == PSM_RFCOMM:
                    link.pending[(direction, ident)] = scid
            elif code == L2CAP_CONN_RSP and len(body) >= 8:
                dcid, scid, result = struct.unpack_from("<HHH", body)
                asker = RECEIVED if direction == SENT else SENT
                if result == 0 and link.pending.pop((asker, ident),
                                                    None) == scid:
                    # the asker sends to dcid and is sent to on scid
                    link.rfcomm_cids[asker] = dcid
                    link.rfcomm_cids[direction] = scid


def h4_with_direction(linktype, data):
    """(direction, H4 packet) from a pcap record, or None for link types
    this reader does not handle.  Without a direction header (link type
    187) ACL data is taken as received; use a trace with directions."""
    if linktype == LINKTYPE_H4_WITH_PHDR:
        if len(data) < 5:
            return None
        flag = struct.unpack_from(">I", data)[0]
        return (RECEIVED if flag & 1 else SENT), data[4:]
    if linktype == LINKTYPE_H4:
        return RECEIVED, data
    return None


def serial_chunks(packets, address=None):
    """(seconds since the first packet, direction, bytes) for every serial
    chunk in an iterable of (timestamp, linktype, data) pcap records."""
    decoder = SerialFromHci(address)
    t0 = None
    for ts, linktype, data in packets:
        if t0 is None:
            t0 = ts
        split = h4_with_direction(linktype, data)
        if split is None:
            continue
        for direction, chunk in decoder.feed(*split):
            yield round(ts - t0, 6), direction, chunk
