"""Tests for P25 conventional channel (CP25ConvSet / CP25ConvChannel) decoding.

Verifies parse/serialize roundtrip for P25 conventional channels,
which have a different structure from regular CConvChannel:
  - 22-byte flags block (vs 48 for CConvChannel)
  - NAC (Network Access Code) uint16 fields
  - No pre_long_name block
  - 20-byte trailer (vs 7 for CConvChannel)
  - Set metadata includes group_set_ref and band limits
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quickprs.prs_parser import parse_prs, parse_prs_bytes
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    P25ConvChannel, P25ConvSet,
    parse_class_header,
    parse_p25_conv_channel_section,
    build_p25_conv_channel_section,
    build_p25_conv_set_section,
    parse_sets_from_sections,
)

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"


# ─── CP25ConvSet parse tests ────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_set_parse():
    """CP25ConvSet section parses correctly (header + channel count)."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    sec = prs.get_section_by_class("CP25ConvSet")
    assert sec is not None

    _, byte1, byte2, ds = parse_class_header(sec.raw, 0)
    assert byte1 == 0x66
    assert byte2 == 0x00
    count, _ = read_uint16_le(sec.raw, ds)
    assert count == 1


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_set_roundtrip():
    """CP25ConvSet section rebuilds byte-identically."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    sec = prs.get_section_by_class("CP25ConvSet")
    _, _, _, ds = parse_class_header(sec.raw, 0)
    count, _ = read_uint16_le(sec.raw, ds)

    rebuilt = build_p25_conv_set_section(count, byte1=0x66, byte2=0x00)
    assert rebuilt == sec.raw


# ─── CP25ConvChannel parse tests ────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_channel_header():
    """CP25ConvChannel section has correct header bytes."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    sec = prs.get_section_by_class("CP25ConvChannel")
    assert sec is not None

    _, byte1, byte2, ds = parse_class_header(sec.raw, 0)
    assert byte1 == 0x71
    assert byte2 == 0x00


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_channel_parse_fields():
    """Parse P25ConvChannel fields from claude test.PRS."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    _, _, _, ds = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds)

    _, _, _, cd = parse_class_header(ch_sec.raw, 0)
    sets = parse_p25_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), first_count)

    assert len(sets) == 1
    cset = sets[0]
    assert cset.name == "NEW"
    assert len(cset.channels) == 1

    ch = cset.channels[0]
    assert ch.short_name == "name"
    assert abs(ch.tx_freq - 806.0) < 0.001
    assert abs(ch.rx_freq - 851.0) < 0.001
    assert ch.tx_tone == ""
    assert ch.rx_tone == ""
    assert ch.nac_tx == 0x293  # 659 decimal
    assert ch.nac_rx == 0x293
    assert ch.long_name == "LONG NAME"


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_channel_flags():
    """P25ConvChannel flags decode correctly."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    _, _, _, ds = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds)
    _, _, _, cd = parse_class_header(ch_sec.raw, 0)
    sets = parse_p25_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), first_count)

    ch = sets[0].channels[0]
    assert ch.rx is True
    assert ch.calls is True
    assert ch.alert is True
    assert ch.scan_list_member is True
    assert ch.scan is True
    assert ch.tx is True


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_set_metadata():
    """P25ConvSet metadata fields parse correctly."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    _, _, _, ds = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds)
    _, _, _, cd = parse_class_header(ch_sec.raw, 0)
    sets = parse_p25_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), first_count)

    cset = sets[0]
    assert cset.scan_list_size == 8
    assert cset.config_byte2 == 0
    assert abs(cset.tx_min - 136.0) < 0.001
    assert abs(cset.rx_min - 136.0) < 0.001
    assert abs(cset.tx_max - 870.0) < 0.001
    assert abs(cset.rx_max - 870.0) < 0.001
    assert cset.group_set_ref == "GROUP SE"


# ─── Roundtrip tests ────────────────────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_channel_section_roundtrip():
    """CP25ConvChannel section rebuilds byte-identically."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    _, _, _, ds = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds)
    _, _, _, cd = parse_class_header(ch_sec.raw, 0)
    sets = parse_p25_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), first_count)

    rebuilt = build_p25_conv_channel_section(sets, byte1=0x71, byte2=0x00)
    assert rebuilt == ch_sec.raw, (
        f"Roundtrip mismatch: {len(rebuilt)} vs {len(ch_sec.raw)} bytes"
    )


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_channel_record_roundtrip():
    """Individual P25ConvChannel record roundtrips."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    _, _, _, ds = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, ds)
    _, _, _, cd = parse_class_header(ch_sec.raw, 0)
    sets = parse_p25_conv_channel_section(ch_sec.raw, cd, len(ch_sec.raw), first_count)

    ch = sets[0].channels[0]
    rebuilt = ch.to_bytes()
    # Parse again from rebuilt bytes
    ch2, end = P25ConvChannel.parse(rebuilt, 0)
    assert end == len(rebuilt)
    assert ch2.short_name == ch.short_name
    assert ch2.tx_freq == ch.tx_freq
    assert ch2.rx_freq == ch.rx_freq
    assert ch2.nac_tx == ch.nac_tx
    assert ch2.nac_rx == ch.nac_rx
    assert ch2.long_name == ch.long_name
    assert ch2.flags == ch.flags
    assert ch2.trailer == ch.trailer


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_full_file_roundtrip():
    """Full file roundtrip with P25 conv channel sections intact."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    raw_original = prs.to_bytes()
    prs2 = parse_prs_bytes(raw_original)
    raw_rebuilt = prs2.to_bytes()
    assert raw_original == raw_rebuilt


# ─── parse_sets_from_sections helper ─────────────────────────────────


@pytest.mark.skipif(not CLAUDE.exists(), reason="Test PRS data not available")
def test_p25_conv_parse_sets_from_sections():
    """parse_sets_from_sections works with P25 conv sections."""
    prs = parse_prs(TESTDATA / "claude test.PRS")
    set_sec = prs.get_section_by_class("CP25ConvSet")
    ch_sec = prs.get_section_by_class("CP25ConvChannel")

    sets = parse_sets_from_sections(
        set_sec.raw, ch_sec.raw, parse_p25_conv_channel_section)
    assert len(sets) == 1
    assert sets[0].name == "NEW"
    assert len(sets[0].channels) == 1


# ─── Synthetic tests ────────────────────────────────────────────────


def test_p25_conv_channel_construct():
    """Construct a P25ConvChannel from scratch and roundtrip."""
    ch = P25ConvChannel(
        short_name="TEST",
        tx_freq=460.500,
        rx_freq=465.500,
        nac_tx=0x293,
        nac_rx=0x293,
        long_name="Test Channel",
    )
    raw = ch.to_bytes()
    ch2, end = P25ConvChannel.parse(raw, 0)
    assert end == len(raw)
    assert ch2.short_name == "TEST"
    assert abs(ch2.tx_freq - 460.500) < 0.001
    assert abs(ch2.rx_freq - 465.500) < 0.001
    assert ch2.nac_tx == 0x293
    assert ch2.nac_rx == 0x293
    assert ch2.long_name == "Test Channel"


def test_p25_conv_set_construct():
    """Construct a P25ConvSet and build/parse roundtrip."""
    ch = P25ConvChannel(
        short_name="P25CH",
        tx_freq=851.0125,
        rx_freq=806.0125,
        nac_tx=0x123,
        nac_rx=0x123,
        long_name="P25 Channel",
    )
    cset = P25ConvSet(
        name="P25SET",
        channels=[ch],
        scan_list_size=8,
        tx_min=136.0,
        rx_min=136.0,
        tx_max=870.0,
        rx_max=870.0,
        group_set_ref="GRPREF",
    )
    # Build full section
    set_raw = build_p25_conv_set_section(1, byte1=0x66, byte2=0x00)
    ch_raw = build_p25_conv_channel_section([cset], byte1=0x71, byte2=0x00)

    # Parse back
    sets = parse_sets_from_sections(
        set_raw, ch_raw, parse_p25_conv_channel_section)
    assert len(sets) == 1
    assert sets[0].name == "P25SET"
    assert len(sets[0].channels) == 1
    assert sets[0].channels[0].short_name == "P25CH"
    assert sets[0].channels[0].nac_tx == 0x123
    assert sets[0].group_set_ref == "GRPREF"


def test_p25_conv_channel_flags_property():
    """flags property roundtrips through setter."""
    ch = P25ConvChannel(short_name="A", tx_freq=0.0, rx_freq=0.0)
    ch.rx = True
    ch.tx = True
    ch.scan = False
    flags = ch.flags
    assert len(flags) == 22

    ch2 = P25ConvChannel(short_name="B", tx_freq=0.0, rx_freq=0.0)
    ch2.flags = flags
    assert ch2.rx is True
    assert ch2.tx is True
    assert ch2.scan is False
