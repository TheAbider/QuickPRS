"""Serial data out of a Bluetooth HCI trace (quickprs radio sniff).

The traces here are built byte by byte from the Bluetooth layers: H4
packets with a direction header (pcap link type 201), ACL data, L2CAP
(with the connection setup that opens the RFCOMM channel) and RFCOMM
frames with their frame checks.  The device address is an example.
"""

import io
import socket
import struct
import threading

import pytest

from quickprs.radio import hci
from quickprs.radio.capture import read_capture

RADIO = "00:02:68:12:34:56"
OTHER = "AA:BB:CC:DD:EE:01"


# ── trace builders ────────────────────────────────────────────────────

def rfcomm(dlci, ftype, payload=b"", pf=False, credits=None, cr=1,
           corrupt=False):
    addr = (dlci << 2) | (cr << 1) | 1
    ctrl = ftype | (hci.RFCOMM_PF if pf else 0)
    n = len(payload)
    length = bytes([(n << 1) | 1]) if n < 128 else bytes([(n << 1) & 0xFE,
                                                          n >> 7])
    head = bytes([addr, ctrl]) + length
    fcs = hci.rfcomm_fcs(head[:2] if ftype == hci.RFCOMM_UIH else head)
    body = (bytes([credits]) if credits is not None else b"") + payload
    return head + body + bytes([fcs ^ (0xFF if corrupt else 0)])


def l2cap(cid, payload):
    return struct.pack("<HH", len(payload), cid) + payload


def acl(handle, data, pb=0b10):
    return bytes([hci.H4_ACL]) + struct.pack(
        "<HH", handle | (pb << 12), len(data)) + data


def event(code, params):
    return bytes([hci.H4_EVENT, code, len(params)]) + params


def conn_complete(handle, address):
    raw = bytes(int(x, 16) for x in reversed(address.split(":")))
    return event(hci.EVT_CONNECTION_COMPLETE,
                 bytes([0]) + struct.pack("<H", handle) + raw + b"\x01\x00")


def conn_req(ident, scid, psm=hci.PSM_RFCOMM):
    return l2cap(hci.CID_SIGNALING, struct.pack(
        "<BBHHH", hci.L2CAP_CONN_REQ, ident, 4, psm, scid))


def conn_rsp(ident, dcid, scid, result=0):
    return l2cap(hci.CID_SIGNALING, struct.pack(
        "<BBHHHHH", hci.L2CAP_CONN_RSP, ident, 8, dcid, scid, result, 0))


def pcap(records, linktype=hci.LINKTYPE_H4_WITH_PHDR):
    """records: (seconds, sent?, h4 bytes)"""
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for t, sent, h4 in records:
        data = struct.pack(">I", 0 if sent else 1) + h4
        out += struct.pack("<IIII", int(t), int(round(t % 1 * 1e6)),
                           len(data), len(data)) + data
    return out


SENT, RECV = True, False
H = 0x000B          # the radio's link
H2 = 0x000C         # another device


def session():
    """Connection, RFCOMM setup, then 'hello' to the radio and a 300-byte
    reply split across two ACL packets."""
    reply = bytes(range(256)) + b"x" * 44
    frame = rfcomm(2, hci.RFCOMM_UIH, reply, cr=0)
    pdu = l2cap(0x0040, frame)
    return reply, [
        (100.0, RECV, conn_complete(H, RADIO)),
        (100.1, SENT, acl(H, conn_req(1, 0x0040))),
        (100.2, RECV, acl(H, conn_rsp(1, 0x0041, 0x0040))),
        (100.3, SENT, acl(H, l2cap(0x0041, rfcomm(0, hci.RFCOMM_SABM,
                                                   pf=True)))),
        (100.4, RECV, acl(H, l2cap(0x0040, rfcomm(0, hci.RFCOMM_UA,
                                                   pf=True)))),
        (100.5, SENT, acl(H, l2cap(0x0041, rfcomm(
            2, hci.RFCOMM_UIH, b"hello", pf=True, credits=7)))),
        (100.6, RECV, acl(H, pdu[:100], pb=0b10)),
        (100.6, RECV, acl(H, pdu[100:], pb=0b01)),
        # a credit-only frame carries no data
        (100.7, RECV, acl(H, l2cap(0x0040, rfcomm(
            2, hci.RFCOMM_UIH, b"", pf=True, credits=4, cr=0)))),
    ]


def chunks(records, **kw):
    return [(d, data) for _, d, data in hci.serial_chunks(
        hci.read_packets(io.BytesIO(pcap(records))), **kw)]


# ── tests ─────────────────────────────────────────────────────────────

def test_fcs_known_frames():
    """Frames as every RFCOMM stack sends them: SABM and UA on the
    control channel, and a UIH frame's check over address and control."""
    assert hci.rfcomm_fcs(b"\x03\x3f\x01") == 0x1C
    assert hci.rfcomm_fcs(b"\x03\x73\x01") == 0xD7
    assert hci.rfcomm_fcs(b"\x03\xef") == 0x70


def test_serial_data_in_both_directions():
    reply, records = session()
    assert chunks(records) == [("pc>radio", b"hello"), ("radio>pc", reply)]


def test_times_are_from_the_trace():
    _, records = session()
    times = [t for t, _, _ in hci.serial_chunks(
        hci.read_packets(io.BytesIO(pcap(records))))]
    assert times == [0.5, 0.6]


def test_corrupt_frames_are_dropped():
    _, records = session()
    records.append((101.0, SENT, acl(H, l2cap(0x0041, rfcomm(
        2, hci.RFCOMM_UIH, b"bad", corrupt=True)))))
    assert b"bad" not in [data for _, data in chunks(records)]
    assert len(chunks(records)) == 2


def test_other_channels_are_ignored():
    """L2CAP channels other than the RFCOMM one, and data not framed as
    RFCOMM, never reach the capture."""
    _, records = session()
    records += [
        (101.0, SENT, acl(H, l2cap(0x0050, b"\x01\x02\x03\x04\x05"))),
        (101.1, SENT, acl(H, l2cap(0x0041, b"\x00\x00\x00\x00"))),
    ]
    assert len(chunks(records)) == 2


def test_only_the_radios_link_with_an_address():
    reply, records = session()
    records += [
        (101.0, RECV, conn_complete(H2, OTHER)),
        (101.1, SENT, acl(H2, conn_req(2, 0x0044))),
        (101.2, RECV, acl(H2, conn_rsp(2, 0x0045, 0x0044))),
        (101.3, SENT, acl(H2, l2cap(0x0045, rfcomm(
            4, hci.RFCOMM_UIH, b"headset", pf=True, credits=1)))),
    ]
    assert chunks(records, address=RADIO) == [("pc>radio", b"hello"),
                                              ("radio>pc", reply)]
    assert ("pc>radio", b"headset") in chunks(records)


def test_trace_started_mid_session():
    """Without the connection setup, a valid RFCOMM frame names the
    channel."""
    _, records = session()
    later = records[5:]
    assert [d for d, _ in chunks(later)] == ["pc>radio", "radio>pc"]


def test_pcapng():
    def block(btype, body):
        body += b"\0" * (-len(body) % 4)
        n = len(body) + 12
        return struct.pack("<II", btype, n) + body + struct.pack("<I", n)
    shb = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    idb = block(1, struct.pack("<HHI", hci.LINKTYPE_H4_WITH_PHDR, 0, 0))
    out = shb + idb
    _, records = session()
    for t, sent, h4 in records:
        data = struct.pack(">I", 0 if sent else 1) + h4
        ts = int(t * 1e6)
        out += block(6, struct.pack("<IIII", 0, ts >> 32, ts & 0xFFFFFFFF,
                                    len(data)) + struct.pack("<I", len(data))
                     + data)
    got = [(d, c) for _, d, c in hci.serial_chunks(
        hci.read_packets(io.BytesIO(out)))]
    assert [d for d, _ in got] == ["pc>radio", "radio>pc"]
    assert got[0][1] == b"hello"


def test_cut_short_stream_is_an_error():
    data = pcap(session()[1])
    with pytest.raises(hci.PcapError):
        list(hci.read_packets(io.BytesIO(data[:-3])))


def test_sniff_command_from_a_file(tmp_path, capsys):
    from quickprs.radio.commands import cmd_radio_sniff
    reply, records = session()
    trace = tmp_path / "trace.pcap"
    trace.write_bytes(pcap(records))
    log = tmp_path / "read.jsonl"
    assert cmd_radio_sniff(pcap=str(trace), log=str(log),
                           address=RADIO) == 0
    cap = read_capture(log)
    assert cap.stream("pc>radio") == b"hello"
    assert cap.stream("radio>pc") == reply
    assert "radio to RPM: 300 bytes" in capsys.readouterr().out


def test_sniff_never_writes_over_a_capture(tmp_path, capsys):
    from quickprs.radio.commands import cmd_radio_sniff
    trace = tmp_path / "trace.pcap"
    trace.write_bytes(pcap(session()[1]))
    log = tmp_path / "read.jsonl"
    log.write_text("an earlier capture\n")
    assert cmd_radio_sniff(pcap=str(trace), log=str(log),
                           address=RADIO) == 0
    assert log.read_text() == "an earlier capture\n"
    assert read_capture(tmp_path / "read-2.jsonl").stream("pc>radio") == (
        b"hello")
    assert "read-2.jsonl" in capsys.readouterr().out


def test_sniff_command_live(tmp_path):
    """The sniffer serves the trace on TCP and closes when it stops."""
    from quickprs.radio.commands import cmd_radio_sniff
    reply, records = session()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        conn, _ = server.accept()
        conn.sendall(pcap(records))
        conn.close()
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    log = tmp_path / "live.jsonl"
    assert cmd_radio_sniff(port=port, log=str(log), address=RADIO) == 0
    assert read_capture(log).stream("radio>pc") == reply


# ── traces without directions, and the trace report ──────────────────

def pcap_h4(records):
    """The same records as link type 187: no direction header."""
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535,
                      hci.LINKTYPE_H4)
    for t, _sent, h4 in records:
        out += struct.pack("<IIII", int(t), 0, len(h4), len(h4)) + h4
    return out


def chunks_h4(records, **kw):
    return [(d, data) for _, d, data in hci.serial_chunks(
        hci.read_packets(io.BytesIO(pcap_h4(records))), **kw)]


def test_no_direction_header_with_connection_setup():
    """The L2CAP setup says which CID is whose: the side asking for the
    RFCOMM channel is the PC."""
    reply, records = session()
    assert chunks_h4(records) == [("pc>radio", b"hello"),
                                  ("radio>pc", reply)]


def test_no_direction_header_mid_session():
    """Without the setup, RFCOMM's C/R bit says who sent a frame: the PC
    opened the channel, and its UIH frames carry C/R = 1."""
    reply, records = session()
    assert chunks_h4(records[5:]) == [("pc>radio", b"hello"),
                                      ("radio>pc", reply)]


def test_radio_opened_channel_with_directions():
    """When the radio asks for the channel, the CIDs swap roles."""
    records = [
        (1.0, RECV, acl(H, conn_req(9, 0x0070))),
        (1.1, SENT, acl(H, conn_rsp(9, 0x0071, 0x0070))),
        (1.2, SENT, acl(H, l2cap(0x0070, rfcomm(
            2, hci.RFCOMM_UIH, b"to radio", cr=0)))),
        (1.3, RECV, acl(H, l2cap(0x0071, rfcomm(
            2, hci.RFCOMM_UIH, b"to pc")))),
    ]
    assert chunks(records) == [("pc>radio", b"to radio"),
                               ("radio>pc", b"to pc")]


def test_trace_report():
    reply, records = session()
    stats = hci.TraceStats()
    list(hci.serial_chunks(hci.read_packets(io.BytesIO(pcap(records))),
                           stats=stats))
    assert stats.packets == len(records)
    assert stats.serial_bytes == {"pc>radio": 5, "radio>pc": len(reply)}
    assert stats.rfcomm_frames == {"SABM": 1, "UA": 1, "UIH": 3}
    lines = hci.describe(stats)
    assert "9 packets (9 HCI H4 with direction)" in lines[0]
    assert "serial channel(s) 1" in lines[1]


@pytest.mark.parametrize("records, linktype, words", [
    ([], hci.LINKTYPE_H4_WITH_PHDR, "is btvs.exe"),
    ([(1.0, RECV, conn_complete(H, RADIO))], hci.LINKTYPE_H4_WITH_PHDR,
     "No Bluetooth data packets"),
    ([(1.0, SENT, acl(H, l2cap(0x0050, b"\x01\x02\x03\x04\x05")))],
     hci.LINKTYPE_H4_WITH_PHDR, "Full Packet Logging"),
    ([(1.0, SENT, b"\x02\x0b\x20\x00\x00")], 1, "link type 1 (not read)"),
])
def test_trace_report_says_why_nothing_was_found(records, linktype, words):
    stats = hci.TraceStats()
    list(hci.serial_chunks(hci.read_packets(io.BytesIO(
        pcap(records, linktype=linktype))), stats=stats))
    assert words in "\n".join(hci.describe(stats))


# ── modem lines ───────────────────────────────────────────────────────

def msc(signals, command=True, dlci=2):
    """An RFCOMM modem status message for the control channel."""
    return bytes([hci.MSC_COMMAND if command else 0xE1, (2 << 1) | 1,
                  (dlci << 2) | 0b11, signals])


def control(cid, payload, cr):
    return l2cap(cid, rfcomm(0, hci.RFCOMM_UIH, payload, cr=cr))


def test_modem_lines_from_the_control_channel(tmp_path):
    """Each side's modem status command becomes a line event; the answers
    that echo them are left out."""
    _, records = session()
    records = records[:5] + [
        # the PC: DTR on, RTS off
        (100.45, SENT, acl(H, control(0x0041, msc(0x05), cr=1))),
        (100.46, RECV, acl(H, control(0x0040, msc(0x05, command=False),
                                      cr=0))),
        # the radio: CTS and RI on
        (100.47, RECV, acl(H, control(0x0040, msc(0x49), cr=0))),
    ] + records[5:]
    out = chunks(records, address=RADIO)
    assert [(d, x) for d, x in out if isinstance(x, str)] == [
        ("pc>radio", "pc dtr=1 rts=0"),
        ("radio>pc", "radio dsr=0 cts=1 ri=1 dcd=0"),
    ]
    assert b"".join(x for d, x in out if d == "pc>radio"
                    and isinstance(x, bytes)) == b"hello"

    from quickprs.radio.commands import cmd_radio_sniff
    trace = tmp_path / "trace.pcap"
    trace.write_bytes(pcap(records))
    log = tmp_path / "read.jsonl"
    assert cmd_radio_sniff(pcap=str(trace), log=str(log),
                           address=RADIO) == 0
    assert read_capture(log).events == [
        (0.45, "pc dtr=1 rts=0"), (0.47, "radio dsr=0 cts=1 ri=1 dcd=0")]


def test_modem_lines_mid_session():
    """Without the connection setup, the control channel counts once a
    data frame has shown which channel RFCOMM is on."""
    records = [
        (1.0, SENT, acl(H, control(0x0041, msc(0x0D), cr=1))),
        (1.1, SENT, acl(H, l2cap(0x0041, rfcomm(
            2, hci.RFCOMM_UIH, b"hi", pf=True, credits=1)))),
        (1.2, SENT, acl(H, control(0x0041, msc(0x01), cr=1))),
    ]
    assert chunks(records) == [("pc>radio", b"hi"),
                               ("pc>radio", "pc dtr=0 rts=0")]
