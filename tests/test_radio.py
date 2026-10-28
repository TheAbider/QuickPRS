"""quickprs.radio: Bluetooth port discovery, capture files, the listen-only
probe, the RPM relay, capture analysis and the replay of a read.  No radio or Bluetooth adapter
is needed: ports and links are stand-ins."""

import threading
import time
from types import SimpleNamespace

import pytest

from quickprs.radio import (
    analyze, bluetooth, capture, probe, relay, replay,
)
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


def test_captures_are_never_written_over(tmp_path):
    path = tmp_path / "read.jsonl"
    path.write_text("an earlier capture\n")
    with capture.CaptureWriter(path) as w:
        w.add(PC_TO_RADIO, b"x")
    assert path.read_text() == "an earlier capture\n"
    assert w.path == tmp_path / "read-2.jsonl"
    assert capture.read_capture(w.path).stream(PC_TO_RADIO) == b"x"
    with capture.CaptureWriter(path) as w3:
        pass
    assert w3.path == tmp_path / "read-3.jsonl"


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
    return capture.read_capture(w.path)


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


# ─── replay ──────────────────────────────────────────────────────────

def _read_session(tmp_path, name="read.jsonl"):
    """RPM reading a radio: a hello, a request the radio does not answer
    (RPM then waits half a second), the personality in three parts (the
    last after a pause, so the answer is two messages) and a goodbye."""
    prs = _blank_bytes()
    third = len(prs) // 3
    with capture.CaptureWriter(tmp_path / name, note="RPM extract") as w:
        w.event("pc dtr=1 rts=0", t=0.0)
        w.add(RADIO_TO_PC, b"\x00", t=0.0)     # before the first request
        w.add(PC_TO_RADIO, b"\x02HELLO", t=0.1)
        w.add(RADIO_TO_PC, b"\x06XG-100P", t=0.12)
        w.add(PC_TO_RADIO, b"\x02MODE", t=0.2)
        w.add(PC_TO_RADIO, b"\x02READ", t=0.7)
        w.add(RADIO_TO_PC, prs[:third], t=0.72)
        w.add(RADIO_TO_PC, prs[third:2 * third], t=0.73)
        w.add(RADIO_TO_PC, prs[2 * third:], t=0.85)
        w.add(PC_TO_RADIO, b"\x02BYE", t=0.9)
        w.add(RADIO_TO_PC, b"\x06", t=0.91)
    return capture.read_capture(w.path), prs


class FakeRadio:
    """Answers each request with the parts scripted for it; a number in
    the script is a pause.  Time is a fake clock that a read moves on by
    the port's timeout when nothing has come."""

    def __init__(self, answers, timeout=0.2):
        self.answers = answers
        self.pending = []
        self.written = []           # (time, request)
        self.now = 0.0
        self.timeout = timeout

    def clock(self):
        return self.now

    @property
    def in_waiting(self):
        if self.pending and isinstance(self.pending[0], bytes):
            return len(self.pending[0])
        return 0

    def write(self, data):
        self.written.append((self.now, bytes(data)))
        self.pending.extend(self.answers.get(bytes(data), []))

    def read(self, n):
        if self.pending:
            part = self.pending.pop(0)
            if isinstance(part, bytes):
                self.now += 0.001
                return part
            self.now += part
            return b""
        self.now += self.timeout
        return b""


def _answers(prs, read=None):
    return {b"\x02HELLO": [b"\x06XG-100P"],
            b"\x02READ": read if read is not None else [prs[:500],
                                                        prs[500:]],
            b"\x02BYE": [b"\x06"]}


def test_steps_pair_requests_with_answers(tmp_path):
    cap, prs = _read_session(tmp_path)
    plan = replay.steps(cap)
    assert [(s.request, s.reply) for s in plan] == [
        (b"\x02HELLO", b"\x06XG-100P"),
        (b"\x02MODE", b""),
        (b"\x02READ", prs),
        (b"\x02BYE", b"\x06"),
    ]
    assert [s.pause for s in plan] == [0.1, 0.5, 0.2, 0.0]


def test_only_reads_are_replayed(tmp_path):
    cap, prs = _read_session(tmp_path)
    assert replay.why_refused(cap) is None
    with capture.CaptureWriter(tmp_path / "w.jsonl") as w:
        w.add(PC_TO_RADIO, b"\x02WRITE" + prs)
        w.add(RADIO_TO_PC, b"\x06")
    assert "it is a write" in replay.why_refused(
        capture.read_capture(w.path))
    assert "hold no personality" in replay.why_refused(
        _conversation(tmp_path))
    with capture.CaptureWriter(tmp_path / "big.jsonl") as w:
        w.add(PC_TO_RADIO, b"\x00" * (len(prs) + 1))
        w.add(RADIO_TO_PC, prs)
    assert "sent more than the radio answered" in replay.why_refused(
        capture.read_capture(w.path))
    with capture.CaptureWriter(tmp_path / "quiet.jsonl") as w:
        w.add(RADIO_TO_PC, prs)
    assert "sent nothing" in replay.why_refused(
        capture.read_capture(w.path))


def test_capture_lines(tmp_path):
    cap, _ = _read_session(tmp_path)
    assert replay.capture_lines(cap) == (True, False)
    assert replay.capture_lines(_conversation(tmp_path)) is None


def test_replay_gets_the_same_answers(tmp_path):
    cap, prs = _read_session(tmp_path)
    radio = FakeRadio(_answers(prs))
    with capture.CaptureWriter(tmp_path / "again.jsonl") as w:
        result = replay.replay(radio, replay.steps(cap), writer=w,
                               clock=radio.clock)
    assert (result.sent, result.same, result.differences,
            result.stopped) == (4, 4, [], "")
    assert [r for _, r in radio.written] == [
        b"\x02HELLO", b"\x02MODE", b"\x02READ", b"\x02BYE"]
    # RPM waited half a second after the request the radio did not answer
    assert radio.written[2][0] - radio.written[1][0] >= 0.5
    again = capture.read_capture(w.path)
    assert again.stream(PC_TO_RADIO) == cap.stream(PC_TO_RADIO)
    assert again.stream(RADIO_TO_PC) == cap.stream(RADIO_TO_PC)[1:]


def test_replay_waits_for_a_slow_answer(tmp_path):
    cap, prs = _read_session(tmp_path)
    radio = FakeRadio(_answers(prs, read=[prs[:500], 1.0, prs[500:]]))
    result = replay.replay(radio, replay.steps(cap), clock=radio.clock)
    assert (result.sent, result.same) == (4, 4)


def test_replay_stops_at_an_answer_that_differs(tmp_path):
    cap, prs = _read_session(tmp_path)
    changed = prs[:100] + bytes([prs[100] ^ 0xFF]) + prs[101:]
    radio = FakeRadio(_answers(prs, read=[changed]))
    result = replay.replay(radio, replay.steps(cap), clock=radio.clock)
    assert (result.sent, result.same) == (3, 2)
    assert "request 3 is not the one RPM got" in result.stopped
    assert [r for _, r in radio.written][-1] == b"\x02READ"
    (d,) = result.differences
    assert (d.step, d.offset) == (2, 100)
    assert d.describe().startswith(
        f"byte 100 differs: RPM got {prs[100]:02x}, this time "
        f"{changed[100]:02x}")
    radio = FakeRadio(_answers(prs, read=[changed]))
    result = replay.replay(radio, replay.steps(cap), keep_going=True,
                           clock=radio.clock)
    assert (result.sent, result.same, result.stopped) == (4, 3, "")


def test_replay_stops_when_the_radio_does_not_answer(tmp_path):
    cap, prs = _read_session(tmp_path)
    for keep_going in (False, True):
        radio = FakeRadio({})
        result = replay.replay(radio, replay.steps(cap),
                               keep_going=keep_going, clock=radio.clock)
        assert (result.sent, result.same) == (1, 0)
        assert result.stopped == "the radio did not answer request 1"
        assert result.differences[0].describe() == (
            "no answer (RPM got 8 bytes)")
    radio = FakeRadio({b"\x02HELLO": [b"\x06XG"]})
    result = replay.replay(radio, replay.steps(cap), clock=radio.clock)
    assert result.differences[0].describe() == (
        "3 bytes where RPM got 8; the first 3 are the same")


def test_replay_does_not_wait_for_a_radio_that_keeps_talking(tmp_path):
    cap, prs = _read_session(tmp_path)
    nmea = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,,*47\r\n"
    radio = FakeRadio({b"\x02HELLO": [nmea] * 1000})
    result = replay.replay(radio, replay.steps(cap), keep_going=True,
                           clock=radio.clock)
    # the answer was cut as soon as it was longer than RPM's, and so was
    # every answer after it while the radio went on talking
    assert result.same == 0
    assert len(radio.pending) > 900


class _Opener:
    """Stands in for open_serial: hands out a FakeRadio, remembers how
    the port was opened."""

    def __init__(self, radio):
        self.radio = radio
        self.calls = []

    def __call__(self, port, **kw):
        self.calls.append((port, kw))
        self.radio.close = lambda: None
        return self.radio


class _RealTimeRadio(FakeRadio):
    def read(self, n):
        if not self.pending or not isinstance(self.pending[0], bytes):
            time.sleep(0.001)
        return super().read(n)


def test_cli_replay(tmp_path, capsys, monkeypatch):
    from quickprs.cli import run_cli
    from quickprs.radio import commands
    monkeypatch.chdir(tmp_path)        # the default --log lands here
    cap, prs = _read_session(tmp_path)
    opener = _Opener(_RealTimeRadio(_answers(prs)))
    monkeypatch.setattr(commands, "open_serial", opener)
    log = tmp_path / "again.jsonl"
    assert commands.cmd_radio_replay(str(tmp_path / "read.jsonl"),
                                     port="COM99", log=str(log),
                                     quiet=0.01) == 0
    assert opener.calls == [("COM99", {"dtr": True, "rts": False})]
    out = capsys.readouterr().out
    assert "Sent 4 of 4 requests; 4 answers were the ones RPM got." in out
    assert capture.read_capture(log).stream(RADIO_TO_PC) == (
        b"\x06XG-100P" + prs + b"\x06")

    # only the first two requests
    opener.radio = _RealTimeRadio(_answers(prs))
    assert commands.cmd_radio_replay(str(tmp_path / "read.jsonl"),
                                     port="COM99", log=str(log),
                                     requests=2, quiet=0.01) == 0
    assert [r for _, r in opener.radio.written] == [b"\x02HELLO",
                                                    b"\x02MODE"]
    assert "Sent 2 of 2 requests" in capsys.readouterr().out

    # an answer that differs
    changed = prs[:7] + b"?" + prs[8:]
    opener.radio = _RealTimeRadio(_answers(prs, read=[changed]))
    assert commands.cmd_radio_replay(str(tmp_path / "read.jsonl"),
                                     port="COM99", log=str(log),
                                     quiet=0.01) == 1
    out = capsys.readouterr().out
    assert "request 3: byte 7 differs" in out
    assert "Stopped: the answer to request 3 is not the one RPM got." in out

    # a write is refused before any port is opened
    opener.calls.clear()
    assert commands.cmd_radio_replay(str(tmp_path / "read.jsonl"),
                                     port="COM99", requests=0) == 1
    assert "at least 1" in capsys.readouterr().err
    with capture.CaptureWriter(tmp_path / "w.jsonl") as w:
        w.add(PC_TO_RADIO, b"\x02WRITE" + prs)
        w.add(RADIO_TO_PC, b"\x06")
    assert run_cli(["radio", "replay", str(w.path), "--port",
                    "COM99"]) == 1
    assert "it is a write" in capsys.readouterr().err
    assert opener.calls == []


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
