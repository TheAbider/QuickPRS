"""Talking to the radio itself (as opposed to editing .PRS files).

The XG-100P's Bluetooth is Bluetooth Classic (2.x pairing, not BLE).  A
paired radio offers a Serial Port Profile service, which Windows exposes as
a COM port, and RPM's help ("Setting Up A Bluetooth Connection") says RPM
programs the radio over that link just as it does over the USB cable: the
Unity Product Management window extracts (reads), writes, activates and
removes mission plans.

The programming protocol is not published, so this package does what is
needed to learn it from RPM, without guessing at commands:

* ``bluetooth``  find paired radios and their SPP COM ports (and scan BLE)
* ``link``       serial links (a Bluetooth COM port or a USB serial port)
* ``capture``    a timestamped, direction-tagged log of every byte
* ``probe``      open the radio's port and listen; never transmits
* ``relay``      sit between RPM and the radio and log what they say
* ``analyze``    summarise a capture and pull out any personality in it

Nothing here sends a byte of its own to the radio.
"""
