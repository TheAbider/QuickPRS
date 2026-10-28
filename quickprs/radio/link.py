"""Serial links: a paired radio's Bluetooth COM port, or a USB serial port.

Opening a Bluetooth SPP COM port is what makes Windows connect to the
radio, so ``open_serial`` can take several seconds and fails when the radio
is off, out of range or has Bluetooth disabled.
"""


class LinkError(RuntimeError):
    """The port could not be opened or used."""


def open_serial(port, baudrate=115200, timeout=0.2, dtr=False, rts=False):
    """Open ``port`` with the modem lines set before the port opens.

    For a Bluetooth SPP port the baud rate means nothing (RFCOMM carries
    bytes, not a line rate); it matters only for a real serial cable.
    DTR and RTS default to off, the quietest way to connect: over
    Bluetooth they travel to the radio as RFCOMM modem status.
    """
    try:
        import serial
    except ImportError as e:
        raise LinkError("serial ports need the 'pyserial' package "
                        "(pip install pyserial)") from e
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baudrate
    ser.timeout = timeout
    ser.write_timeout = 5
    ser.dtr = dtr
    ser.rts = rts
    try:
        ser.open()
    except (serial.SerialException, OSError) as e:
        raise LinkError(
            f"could not open {port}: {e}. For a Bluetooth port, check the "
            f"radio is on, in range and has Bluetooth enabled "
            f"(SETTINGS > BLUETOOTH > ENABLED).") from e
    return ser
