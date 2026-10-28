"""Relay between RPM and the radio, logging both directions.

RPM talks to the radio through a COM port.  Give it a virtual one instead:
with a null-modem pair (for example com0com's COM20 <-> COM21), RPM opens
COM20, this relay opens COM21 and the radio's real port (the Bluetooth SPP
port, or the radio's serial port), and passes every byte across while
writing it to a capture file.  RPM stays in charge of the conversation; the
relay only forwards what each side sends.

com0com maps each side's DTR/RTS to the other side's DSR/CTS, so the relay
also copies RPM's modem lines to the radio's port.
"""

import threading
import time

from .capture import PC_TO_RADIO, RADIO_TO_PC


def _pump(src, dst, direction, writer, stop, on_chunk, errors):
    try:
        while not stop.is_set():
            data = src.read(max(1, getattr(src, "in_waiting", 0) or 1))
            if not data:
                continue
            dst.write(data)
            if writer is not None:
                writer.add(direction, data)
            if on_chunk is not None:
                on_chunk(direction, data)
    except Exception as e:  # a closed port ends the session
        errors.append((direction, e))
        stop.set()


def _mirror_lines(pc, radio, writer, stop, poll):
    """Copy RPM's DTR/RTS (seen as DSR/CTS on the virtual pair) across."""
    last = None
    while not stop.is_set():
        try:
            state = (bool(pc.dsr), bool(pc.cts))
            if state != last:
                radio.dtr, radio.rts = state
                if writer is not None:
                    writer.event(f"pc dtr={int(state[0])} rts={int(state[1])}")
                last = state
        except Exception:
            return
        time.sleep(poll)


def run_relay(pc_link, radio_link, writer=None, stop=None, on_chunk=None,
              mirror_lines=True, poll=0.05):
    """Forward bytes both ways until ``stop`` is set or a port closes.

    Returns the list of (direction, exception) that ended it, if any.
    """
    stop = stop or threading.Event()
    errors = []
    threads = [
        threading.Thread(target=_pump, daemon=True, args=(
            pc_link, radio_link, PC_TO_RADIO, writer, stop, on_chunk,
            errors)),
        threading.Thread(target=_pump, daemon=True, args=(
            radio_link, pc_link, RADIO_TO_PC, writer, stop, on_chunk,
            errors)),
    ]
    if mirror_lines:
        threads.append(threading.Thread(
            target=_mirror_lines, daemon=True,
            args=(pc_link, radio_link, writer, stop, poll)))
    for t in threads:
        t.start()
    try:
        while not stop.is_set():
            time.sleep(poll)
    except KeyboardInterrupt:
        stop.set()
    for t in threads:
        t.join(timeout=2)
    return errors
