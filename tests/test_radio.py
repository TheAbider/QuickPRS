"""quickprs.radio: Bluetooth port discovery, capture files, the listen-only
probe, the RPM relay and capture analysis.  No radio or Bluetooth adapter
is needed: ports and links are stand-ins."""

import threading
import time
from types import SimpleNamespace

import pytest

from quickprs.radio import analyze, bluetooth, capture, probe, relay
from quickprs.radio.capture import PC_TO_RADIO, RADIO_TO_PC

# Hardware IDs in the form Windows reports for a paired XG-100P
# (example address)
OUT_HWID = (r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002"
            r"\7&1A2B3C4D&0&000268123456_C00000000")
IN_HWID = (r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000"
           r"\7&1A2B3C4D&0&000000000000_00000025")


def _port(device, hwid, description=""):
    return SimpleNamespace(device=device, hwid=hwid, description=description)


# ─── discovery ───────────────────────────────────────────────────────

def test_parse_hwid():
    assert bluetooth.parse_hwid(OUT_HWID) == (bluetooth.SPP_UUID,
                                              "00:02:68:12:34:56")
    assert bluetooth.parse_hwid(IN_HWID) == (bluetooth.SPP_UUID, "")
    assert bluetooth.parse_hwid(r"USB\VID_303A&PID_1001&MI_00\6&1") is None


def test_radio_ports_pick_the_outgoing_spp_port():
    ports = bluetooth.bluetooth_serial_ports(
        comports=[_port("COM3", IN_HWID), _port("COM6", OUT_HWID),
                  _port("COM8", r"USB\VID_303A&PID_1001")],
        names={"00:02:68:12:34:56": "MY RADIO"})
    assert [(p.port, p.name, p.outgoing) for p in ports] == [
        ("COM3", "", False), ("COM6", "MY RADIO", True)]
    assert [p.port for p in bluetooth.radio_ports(ports)] == ["COM6"]


# ─── capture files ───────────────────────────────────────────────────

def test_capture_round_trip(tmp_path):
    path = tmp_path / "s.jsonl"
    with capture.CaptureWriter(path, note="unit test") as w:
        w.add(PC_TO_RADIO, b"\x01\x02")
        w.event("pc dtr=1 rts=0")
        w.add(RADIO_TO_PC, b"\xa5\x5a\x00")
        w.add(RADIO_TO_PC, b"")            # empty reads are not logged
    cap = capture.read_capture(path)
    assert cap.header["note"] == "unit test"
    assert [(c.direction, c.data) for c in cap.chunks] == [
        (PC_TO_RADIO, b"\x01\x02"), (RADIO_TO_PC, b"\xa5\x5a\x00")]
    assert cap.events[0][1] == "pc dtr=1 rts=0"
    assert cap.stream(RADIO_TO_PC) == b"\xa5\x5a\x00"


def test_capture_lines_stay_whole_across_threads(tmp_path):
    path = tmp_path / "t.jsonl"
    w = capture.CaptureWriter(path)

    def spam(direction):
        for i in range(300):
            w.add(direction, bytes([i % 256]) * 40)

    threads = [threading.Thread(target=spam, args=(d,))
               for d in (PC_TO_RADIO, RADIO_TO_PC)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    w.close()
    cap = capture.read_capture(path)
    assert len(cap.chunks) == 600
    assert all(len(c.data) == 40 for c in cap.chunks)


def test_hexdump():
    assert capture.hexdump(b"AB\x00", offset=16) == [
        "00000010  41 42 00" + " " * 40 + " AB."]   # hex column is 48 wide


# ─── probe ───────────────────────────────────────────────────────────

class FakeLink:
    """read() hands out queued chunks; write() must never be called by
    the probe."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.written = bytearray()
        self.lock = threading.Lock()
        self.dsr = self.cts = False
        self.dtr = self.rts = False

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, n):
        with self.lock:
            if self.chunks:
                return self.chunks.pop(0)
        time.sleep(0.001)
        return b""

    def write(self, data):
        with self.lock:
            self.written += data


@pytest.mark.parametrize("data,kind", [
    (b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
     b"\r\n", "NMEA"),
    (b"\x7e\xff\x03\xc0\x21\x01\x01\x00\x0e\x7e", "PPP"),
    (b"\r\nOK\r\n", "AT/modem"),
    (b"XG-100P READY\r\n", "plain text"),
    (b"\xa5\x01\x9c\x00\x13", "binary"),
    (b"", "nothing"),
])
def test_classify(data, kind):
    assert probe.classify(data).startswith(kind)


def test_listen_never_writes(tmp_path):
    link = FakeLink([b"\x01\x02", b"\x03"])
    ticks = iter(i * 0.1 for i in range(1000))
    with capture.CaptureWriter(tmp_path / "p.jsonl") as w:
        got = probe.listen(link, 0.5, writer=w, clock=lambda: next(ticks))
    assert got == b"\x01\x02\x03"
    assert link.written == b""
    cap = capture.read_capture(tmp_path / "p.jsonl")
    assert cap.stream(RADIO_TO_PC) == b"\x01\x02\x03"


# ─── relay ───────────────────────────────────────────────────────────

def test_relay_forwards_and_logs_both_ways(tmp_path):
    pc = FakeLink([b"\x10\x11", b"\x12"])          # what RPM sends
    radio = FakeLink([b"\x20", b"\x21\x22\x23"])   # what the radio answers
    pc.dsr = True                                  # RPM raised DTR
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    with capture.CaptureWriter(tmp_path / "r.jsonl") as w:
        errors = relay.run_relay(pc, radio, writer=w, stop=stop, poll=0.01)
    assert errors == []
    assert bytes(radio.written) == b"\x10\x11\x12"
    assert bytes(pc.written) == b"\x20\x21\x22\x23"
    assert radio.dtr is True and radio.rts is False
    cap = capture.read_capture(tmp_path / "r.jsonl")
    assert cap.stream(PC_TO_RADIO) == b"\x10\x11\x12"
    assert cap.stream(RADIO_TO_PC) == b"\x20\x21\x22\x23"
    assert any("dtr=1" in text for _, text in cap.events)


# ─── analysis ────────────────────────────────────────────────────────

def _blank_bytes():
    from quickprs.builder import create_blank_prs
    return create_blank_prs("RADIO.PRS").to_bytes()


def test_find_class_headers_in_a_stream():
    prs = _blank_bytes()
    stream = b"\xa5\x5a\x00\x10junk" + prs
    names = [h.name for h in analyze.find_class_headers(stream)]
    assert names[0] == "CPersonality"
    assert "CConvSystem" in names and "CConvChannel" in names


def test_extract_personality_from_framed_replies():
    prs = _blank_bytes()
    stream = b"\x02\x00\x41HEADER" + prs
    assert analyze.extract_personality(stream) == prs
    assert analyze.extract_personality(b"\x00" * 64) is None


def test_report_mentions_archive_and_text(tmp_path):
    prs = _blank_bytes()
    path = tmp_path / "a.jsonl"
    with capture.CaptureWriter(path, note="RPM extract") as w:
        w.add(PC_TO_RADIO, b"\x01READ PERSONALITY")
        for i in range(0, len(prs), 64):
            w.add(RADIO_TO_PC, prs[i:i + 64])
    text = "\n".join(analyze.report(capture.read_capture(path)))
    assert "RPM extract" in text
    assert "CPersonality@0x0" in text
    assert "'READ PERSONALITY'" in text


def _conversation(tmp_path):
    """A request in two chunks, a reply in two chunks, a late chunk the
    radio sends on its own, and the next request."""
    path = tmp_path / "talk.jsonl"
    with capture.CaptureWriter(path, note="talk") as w:
        w.add(PC_TO_RADIO, b"\x02RE", t=0.0)
        w.add(PC_TO_RADIO, b"AD", t=0.01)
        w.add(RADIO_TO_PC, b"\x06ok", t=0.02)
        w.add(RADIO_TO_PC, b"!", t=0.03)
        w.add(RADIO_TO_PC, b"\x15", t=0.5)
        w.add(PC_TO_RADIO, b"\x02NEXT", t=0.51)
    return capture.read_capture(path)


def test_messages_join_chunks_going_one_way(tmp_path):
    msgs = analyze.messages(_conversation(tmp_path))
    assert [(m.direction, m.data) for m in msgs] == [
        (PC_TO_RADIO, b"\x02READ"),
        (RADIO_TO_PC, b"\x06ok!"),
        (RADIO_TO_PC, b"\x15"),            # after a pause: its own message
        (PC_TO_RADIO, b"\x02NEXT"),
    ]
    assert [m.t for m in msgs] == [0.0, 0.02, 0.5, 0.51]


def test_transcript_lines(tmp_path):
    lines = analyze.transcript(_conversation(tmp_path), limit=3)
    assert len(lines) == 4
    assert lines[0].split() == ["0.000", PC_TO_RADIO, "5", "B",
                                "02", "52", "45", "41", "44", "|.READ|"]
    assert lines[2].split()[1:3] == [RADIO_TO_PC, "1"]
    assert lines[3] == "... 1 more messages"
    long = analyze.transcript(_conversation(tmp_path), width=2)
    assert "02 52 ..." in long[0] and "|.R|" in long[0]
    assert len(long) == 4                # no "more" line when all fit


def test_report_counts_messages(tmp_path):
    text = "\n".join(analyze.report(_conversation(tmp_path)))
    assert f"{PC_TO_RADIO}: 10 bytes in 3 chunks, 2 messages" in text
    assert f"{RADIO_TO_PC}: 5 bytes in 3 chunks, 2 messages" in text
    assert "common message sizes: 5 B x2" in text
    assert "common message openers: [06 6f] x1, [15] x1" in text


def test_cli_analyze_transcript(tmp_path, capsys):
    from quickprs.cli import run_cli
    _conversation(tmp_path)
    assert run_cli(["radio", "analyze", str(tmp_path / "talk.jsonl"),
                    "--transcript", "2"]) == 0
    out = capsys.readouterr().out
    assert "Conversation" in out
    assert "|.READ|" in out and "|.ok!|" in out
    assert "|.NEXT|" not in out and "... 2 more messages" in out


def test_cli_analyze_extracts(tmp_path, capsys):
    from quickprs.cli import run_cli
    prs = _blank_bytes()
    path = tmp_path / "a.jsonl"
    with capture.CaptureWriter(path) as w:
        w.add(RADIO_TO_PC, b"\xff\x00" + prs)
    out_prs = tmp_path / "radio.PRS"
    assert run_cli(["radio", "analyze", str(path), "--extract",
                    str(out_prs)]) == 0
    assert out_prs.read_bytes() == prs
