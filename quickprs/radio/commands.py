"""`quickprs radio ...` commands (see quickprs.radio for the background)."""

import sys
from pathlib import Path

from .analyze import extract_personality, report
from .bluetooth import (
    SPP_UUID, bluetooth_serial_ports, radio_ports, scan_ble,
)
from .capture import CaptureWriter, RADIO_TO_PC, hexdump, read_capture
from .link import LinkError, open_serial
from .probe import classify, listen

PAIRING_HELP = (
    "Pair the radio first. On the radio: SETTINGS > BLUETOOTH, set "
    "ENABLED to YES, then PAIRING MGNT > ADD NEW and pick this PC; accept "
    "the pass key on both. (Bluetooth must be enabled in the radio's "
    "personality: Options > Bluetooth Settings.)")


def _pick_port(port):
    if port:
        return port
    radios = radio_ports()
    if len(radios) == 1:
        return radios[0].port
    if not radios:
        print("Error: no paired Bluetooth serial device found. "
              + PAIRING_HELP, file=sys.stderr)
    else:
        listed = ", ".join(f"{r.port} ({r.name or r.address})"
                           for r in radios)
        print(f"Error: several Bluetooth serial ports ({listed}); "
              f"choose one with --port", file=sys.stderr)
    return None


def cmd_radio_scan(ble=False, ble_seconds=5.0):
    ports = bluetooth_serial_ports()
    if ports:
        print("Bluetooth serial ports:")
        for p in ports:
            kind = "SPP" if p.service_uuid == SPP_UUID else p.service_uuid
            who = p.name or "(unnamed)"
            addr = p.address or "incoming (for devices that call the PC)"
            print(f"  {p.port:7s} {who:20s} {addr:20s} {kind}")
    radios = radio_ports(ports)
    if radios:
        print()
        for r in radios:
            print(f"Use --port {r.port} for {r.name or r.address}.")
    else:
        print("No outgoing Bluetooth serial port. " + PAIRING_HELP)

    if ble:
        print()
        print(f"BLE devices advertising nearby ({ble_seconds:g} s scan):")
        try:
            rows = scan_ble(ble_seconds)
        except RuntimeError as e:
            print(f"  {e}", file=sys.stderr)
            return 1
        for address, name, rssi in rows:
            print(f"  {address:20s} {rssi:4d} dBm  {name}")
        if not rows:
            print("  none")
        print("  (An XG-100P is Bluetooth Classic and does not appear in a "
              "BLE scan.)")
    return 0


def cmd_radio_probe(port=None, seconds=10.0, log=None, dtr=False,
                    quiet=False):
    port = _pick_port(port)
    if port is None:
        return 1
    print(f"Opening {port}. For a Bluetooth port this connects to the radio "
          f"and can take several seconds...")
    try:
        link = open_serial(port, dtr=dtr)
    except LinkError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Connected. Listening for {seconds:g} s; nothing is sent.")
    writer = CaptureWriter(log, note=f"probe {port}") if log else None
    offset = [0]

    def show(data):
        if not quiet:
            for line in hexdump(data, offset=offset[0]):
                print(line)
        offset[0] += len(data)

    try:
        data = listen(link, seconds, writer=writer, on_chunk=show)
    except KeyboardInterrupt:
        data = b""
    finally:
        link.close()
        if writer is not None:
            writer.close()
    print(f"Received {offset[0]} bytes: {classify(data)}.")
    if log:
        print(f"Capture saved to {log}")
    return 0


def cmd_radio_relay(pc_port, radio_port=None, log="session.jsonl",
                    note=""):
    from .relay import run_relay
    radio_port = _pick_port(radio_port)
    if radio_port is None:
        return 1
    try:
        radio = open_serial(radio_port)
    except LinkError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    try:
        pc = open_serial(pc_port)
    except LinkError as e:
        radio.close()
        print(f"Error: {e}", file=sys.stderr)
        return 1

    counts = {"pc>radio": 0, "radio>pc": 0}

    def tally(direction, data):
        counts[direction] += len(data)

    print(f"Relaying {pc_port} (RPM side) <-> {radio_port} (radio), "
          f"logging to {log}. Point RPM at the other end of the virtual "
          f"pair, run the operation, then press Ctrl+C here.")
    with CaptureWriter(log, note=note or
                       f"relay {pc_port} <-> {radio_port}") as writer:
        try:
            errors = run_relay(pc, radio, writer=writer, on_chunk=tally)
        finally:
            pc.close()
            radio.close()
    print(f"Stopped. RPM to radio: {counts['pc>radio']:,} bytes; radio to "
          f"RPM: {counts['radio>pc']:,} bytes.")
    for direction, e in errors:
        print(f"  {direction} ended: {e}", file=sys.stderr)
    print(f"Analyze with: quickprs radio analyze {log}")
    return 0


def _radio_address():
    """The one paired radio's Bluetooth address, or None."""
    radios = radio_ports()
    return radios[0].address if len(radios) == 1 else None


def cmd_radio_sniff(host="127.0.0.1", port=24352, log="session.jsonl",
                    pcap=None, address=None, all_links=False, note=""):
    """Write the serial data in a Bluetooth HCI trace to a capture file.

    Live: connect to Microsoft's Bluetooth Virtual Sniffer (btvs.exe
    -Mode Wireshark), which serves the trace on TCP.  Or read a pcap or
    pcapng file saved from it.  Only the serial (RFCOMM) bytes are kept.
    """
    import socket
    from .hci import read_packets, serial_chunks, PcapError

    if not all_links and address is None:
        address = _radio_address()
    counts = {"pc>radio": 0, "radio>pc": 0}
    source = pcap or f"{host}:{port}"
    note = note or f"sniff {source}" + (f" ({address})" if address else "")

    if pcap:
        try:
            stream = open(pcap, "rb")
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        try:
            sock = socket.create_connection((host, port), timeout=10)
        except OSError as e:
            print(f"Error: cannot connect to {host}:{port} ({e}). Start "
                  f"the Bluetooth Virtual Sniffer first: btvs.exe -Mode "
                  f"Wireshark", file=sys.stderr)
            return 1
        sock.settimeout(None)
        stream = sock.makefile("rb")
        print(f"Reading the Bluetooth trace from {host}:{port}"
              + (f", link to {address}" if address else "")
              + f". Run the operation in RPM, then press Ctrl+C here.")

    with CaptureWriter(log, note=note) as writer:
        try:
            for t, direction, data in serial_chunks(read_packets(stream),
                                                    address=address):
                writer.add(direction, data, t=t)
                counts[direction] += len(data)
        except KeyboardInterrupt:
            pass
        except PcapError as e:
            print(f"Error: {e}", file=sys.stderr)
        finally:
            stream.close()
    print(f"RPM to radio: {counts['pc>radio']:,} bytes; radio to RPM: "
          f"{counts['radio>pc']:,} bytes.")
    if not any(counts.values()):
        print("No serial data found. Was Full Packet Logging on in the "
              "sniffer, and did RPM talk to the radio while it ran?",
              file=sys.stderr)
    print(f"Analyze with: quickprs radio analyze {log}")
    return 0


def cmd_radio_analyze(capture_path, extract=None):
    try:
        cap = read_capture(capture_path)
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    for line in report(cap):
        print(line)
    if extract:
        data = extract_personality(cap.stream(RADIO_TO_PC))
        if data is None:
            print("\nNo .PRS archive the walker could follow in the radio's "
                  "replies.", file=sys.stderr)
            return 1
        Path(extract).write_bytes(data)
        print(f"\nWrote {len(data):,} bytes of archive to {extract} "
              f"(compare with a .PRS RPM saved before trusting it).")
    return 0
