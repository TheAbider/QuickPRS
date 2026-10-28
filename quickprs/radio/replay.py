"""Send RPM's side of a recorded read session to the radio again.

The first test of whether QuickPRS can read a radio without RPM.  It sends
the requests RPM sent, in order, waits for the radio's answer to each and
compares it with the answer the radio gave RPM.  Identical answers mean
RPM's requests can become QuickPRS's own read command.  An answer that
differs means the session holds something that changes from one session to
the next (a counter, a time, a challenge); the replay stops there, unless
told to keep going, rather than send requests that no longer fit what the
radio said.

Only sessions that read a personality are replayed: the radio's answers
must hold one (a CPersonality archive header) and RPM's requests must not.
Anything else (a write, an activate, a remove) changes the radio, and
replaying it would do that again with whatever the capture held.
"""

from dataclasses import dataclass, field
import re
import time

from .analyze import find_class_headers, messages
from .capture import PC_TO_RADIO, RADIO_TO_PC


@dataclass
class Step:
    """A request RPM sent, and what the radio answered before RPM's next
    request."""
    request: bytes
    reply: bytes = b""
    pause: float = 0.0          # seconds until RPM's next request


def steps(capture, gap=0.05):
    """The capture's requests and answers, in order.  Anything the radio
    said before the first request is left out."""
    out, replies, times = [], [], []
    for m in messages(capture, gap):
        if m.direction == PC_TO_RADIO:
            out.append(Step(m.data))
            replies.append([])
            times.append(m.t)
        elif out:
            replies[-1].append(m.data)
    for step, parts in zip(out, replies):
        step.reply = b"".join(parts)
    for step, t, t_next in zip(out, times, times[1:]):
        step.pause = round(t_next - t, 6)
    return out


def _has_personality(data):
    return any(h.name == "CPersonality" for h in find_class_headers(data))


def why_refused(capture):
    """None when ``capture`` is a session that read a personality, else
    why it is not replayed."""
    sent = capture.stream(PC_TO_RADIO)
    answers = capture.stream(RADIO_TO_PC)
    if not sent:
        return "RPM sent nothing in it"
    if _has_personality(sent):
        return "RPM sent a personality in it: it is a write"
    if not _has_personality(answers):
        return ("the radio's answers hold no personality, so it is not a "
                "read QuickPRS can recognise (a write, activate or remove "
                "changes the radio, and is never replayed)")
    if len(sent) > len(answers):
        return (f"RPM sent more than the radio answered ({len(sent):,} "
                f"against {len(answers):,} bytes): it looks like a write")
    return None


def capture_lines(capture):
    """RPM's (DTR, RTS) from the capture's first 'pc dtr=.. rts=..' event,
    or None when it recorded none."""
    for _, text in capture.events:
        m = re.match(r"pc dtr=([01]) rts=([01])", text)
        if m:
            return m.group(1) == "1", m.group(2) == "1"
    return None


@dataclass
class Difference:
    """An answer that was not the one RPM got."""
    step: int                   # index of the request
    expected: bytes
    got: bytes

    @property
    def offset(self):
        """The first byte that differs, or the shorter length when one
        answer starts the other."""
        for i, (a, b) in enumerate(zip(self.expected, self.got)):
            if a != b:
                return i
        return min(len(self.expected), len(self.got))

    def describe(self):
        if not self.got:
            return f"no answer (RPM got {len(self.expected):,} bytes)"
        i = self.offset
        if i < min(len(self.expected), len(self.got)):
            return (f"byte {i} differs: RPM got {self.expected[i]:02x}, "
                    f"this time {self.got[i]:02x} ({len(self.got):,} "
                    f"bytes, RPM got {len(self.expected):,})")
        return (f"{len(self.got):,} bytes where RPM got "
                f"{len(self.expected):,}; the first {i:,} are the same")


@dataclass
class ReplayResult:
    sent: int = 0               # requests sent
    same: int = 0               # answers identical to RPM's
    differences: list = field(default_factory=list)
    stopped: str = ""           # why it stopped early, if it did


def read_answer(link, expected, timeout, quiet, clock=time.monotonic,
                on_data=None):
    """The radio's answer: read until ``expected`` bytes have come and the
    radio has then been quiet for ``quiet`` seconds, or until it has been
    silent for ``timeout`` seconds short of that.  More than ``expected``
    bytes is already not RPM's answer, so reading stops there: a radio that
    keeps talking (GPS output, say) cannot hold the replay up."""
    got = bytearray()
    last = clock()
    while True:
        data = link.read(max(1, getattr(link, "in_waiting", 0) or 1))
        now = clock()
        if data:
            got += data
            last = now
            if on_data is not None:
                on_data(data)
            if len(got) > expected:
                return bytes(got)
            continue
        if now - last >= (quiet if len(got) >= expected else timeout):
            return bytes(got)


def replay(link, plan, writer=None, timeout=3.0, quiet=0.3,
           keep_going=False, max_pause=5.0, clock=time.monotonic):
    """Send each request in ``plan`` (Steps) and compare the answer with
    the reply RPM got.

    Where RPM got no answer, RPM's pause before its next request (up to
    ``max_pause``) is kept: the radio may have needed it.  Stops when the
    radio does not answer, and at the first answer that differs unless
    ``keep_going``.
    """
    result = ReplayResult()
    log = None
    if writer is not None:
        def log(data):
            writer.add(RADIO_TO_PC, data)
    try:
        for i, step in enumerate(plan):
            link.write(step.request)
            if writer is not None:
                writer.add(PC_TO_RADIO, step.request)
            result.sent += 1
            wait = quiet if step.reply else max(quiet,
                                                min(step.pause, max_pause))
            got = read_answer(link, len(step.reply), timeout, wait, clock,
                              log)
            if got == step.reply:
                result.same += 1
                continue
            result.differences.append(Difference(i, step.reply, got))
            if not got:
                result.stopped = f"the radio did not answer request {i + 1}"
                break
            if not keep_going:
                result.stopped = (f"the answer to request {i + 1} is not "
                                  f"the one RPM got")
                break
    except KeyboardInterrupt:
        result.stopped = "stopped with Ctrl+C"
    return result
