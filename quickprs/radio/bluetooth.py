"""Find paired radios and the COM ports their Bluetooth serial service uses.

Windows gives every Bluetooth Serial Port Profile (SPP) service of a paired
device a "Standard Serial over Bluetooth link" COM port.  Its hardware ID
holds the service UUID and the device address, e.g.::

    BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002\\
        7&1A2B3C4D&0&000268123456_C00000000

An address of all zeros marks the *incoming* port (for devices that connect
to the PC); the outgoing port carries the device's address and is the one
to open.  Device names come from the Bluetooth stack's registry entries.
"""

from dataclasses import dataclass
import re
import sys

SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

_BTHENUM = re.compile(
    r"BTHENUM\\\{(?P<uuid>[0-9A-F-]{36})\}[^\\]*\\[^&\\]*&[^&\\]*&[^&\\]*&"
    r"(?P<addr>[0-9A-F]{12})_", re.IGNORECASE)


@dataclass
class BluetoothPort:
    """A COM port backed by a Bluetooth Classic serial service."""
    port: str            # e.g. "COM6"
    address: str         # "00:02:68:12:34:56", or "" for an incoming port
    service_uuid: str
    name: str = ""       # paired device name, e.g. "MY RADIO"
    description: str = ""

    @property
    def outgoing(self):
        """True for the port that connects out to the device."""
        return bool(self.address)


def format_address(raw12):
    """'000268123456' -> '00:02:68:12:34:56' ('' for all zeros)."""
    raw12 = raw12.upper()
    if set(raw12) == {"0"}:
        return ""
    return ":".join(raw12[i:i + 2] for i in range(0, 12, 2))


def parse_hwid(hwid):
    """(service UUID, address) from a BTHENUM hardware ID, or None."""
    m = _BTHENUM.search(hwid or "")
    if not m:
        return None
    return m.group("uuid").upper(), format_address(m.group("addr"))


def paired_device_names():
    """{address: name} for paired Bluetooth devices (Windows only)."""
    if sys.platform != "win32":
        return {}
    import winreg
    names = {}
    key_path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return names
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            raw, _ = winreg.QueryValueEx(winreg.OpenKey(root, sub), "Name")
        except OSError:
            continue
        name = bytes(raw).split(b"\x00")[0].decode("utf-8", "replace")
        names[format_address(sub)] = name
    return names


def bluetooth_serial_ports(comports=None, names=None):
    """Every COM port backed by a Bluetooth serial service.

    ``comports`` and ``names`` default to the live system (pyserial's port
    list and the paired-device registry); tests pass their own.
    """
    if comports is None:
        from serial.tools import list_ports
        comports = list_ports.comports()
    if names is None:
        names = paired_device_names()
    found = []
    for p in comports:
        parsed = parse_hwid(getattr(p, "hwid", ""))
        if not parsed:
            continue
        uuid, address = parsed
        found.append(BluetoothPort(
            port=p.device, address=address, service_uuid=uuid,
            name=names.get(address, ""),
            description=getattr(p, "description", "") or ""))
    return found


def radio_ports(ports=None):
    """Outgoing SPP ports: the ones a paired radio can be reached on."""
    if ports is None:
        ports = bluetooth_serial_ports()
    return [p for p in ports if p.outgoing and p.service_uuid == SPP_UUID]


def scan_ble(seconds=5.0):
    """Advertising BLE devices as (address, name, rssi), strongest first.

    Needs the optional ``bleak`` package.  An XG-100P does not show up
    here: its Bluetooth is Classic, which BLE scanning does not see.
    """
    import asyncio
    try:
        from bleak import BleakScanner
    except ImportError as e:
        raise RuntimeError(
            "BLE scanning needs the 'bleak' package "
            "(pip install bleak)") from e

    async def _scan():
        found = await BleakScanner.discover(timeout=seconds,
                                            return_adv=True)
        rows = []
        for device, adv in found.values():
            rows.append((device.address, device.name or adv.local_name or "",
                         adv.rssi))
        return sorted(rows, key=lambda r: -r[2])

    return asyncio.run(_scan())
