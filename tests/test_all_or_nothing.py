"""Adding a system is all or nothing (#3 of the GUI import audit): a set
that cannot be added (its name is taken) used to leave the system behind
without it, and the GUI showed an error but kept the half-added system,
unmarked, for Save to write."""

from quickprs import archive
from quickprs.builder import create_blank_prs
from quickprs.injector import (
    _safe_add_group_set, add_conv_system, add_p25_trunked_system,
    make_conv_set, make_group_set, make_trunk_set,
)
from quickprs.radioreference import ConvChannelData, add_rr_conv_channels
from quickprs.record_types import ConvSystemConfig, P25TrkSystemConfig

import pytest


def _names(prs):
    doc = archive.document_from_prs(prs)
    return [o.cls for o in doc.list("systems").items
            if o is not None]


def _blank_with_group_set(name):
    prs = create_blank_prs("t.PRS")
    _safe_add_group_set(prs, make_group_set(name, [(100, "A", "A")]))
    return prs


def test_p25_system_with_a_taken_set_name_changes_nothing():
    prs = _blank_with_group_set("TAKEN")
    before = prs.to_bytes()
    config = P25TrkSystemConfig(system_name="TAKEN", long_name="TAKEN",
                                trunk_set_name="TAKEN",
                                group_set_name="TAKEN", wan_name="TAKEN")
    with pytest.raises(ValueError, match="already exists"):
        add_p25_trunked_system(
            prs, config,
            trunk_set=make_trunk_set("TAKEN", [(851.0125, 851.0125)]),
            group_set=make_group_set("TAKEN", [(200, "B", "B")]))
    assert prs.to_bytes() == before
    # and it still works once the name is free
    config.group_set_name = config.trunk_set_name = "FREE"
    add_p25_trunked_system(
        prs, config,
        trunk_set=make_trunk_set("FREE", [(851.0125, 851.0125)]),
        group_set=make_group_set("FREE", [(200, "B", "B")]))
    assert "CP25TrkSystem" in _names(prs)


def test_conv_system_with_a_taken_set_name_changes_nothing():
    prs = create_blank_prs("t.PRS")
    conv = make_conv_set("TAKEN", [{"short_name": "CH1",
                                    "tx_freq": 155.0, "rx_freq": 155.0}])
    add_conv_system(prs, ConvSystemConfig(system_name="TAKEN",
                                          long_name="TAKEN",
                                          conv_set_name="TAKEN"),
                    conv_set=conv)
    before = prs.to_bytes()
    with pytest.raises(ValueError, match="already exists"):
        add_conv_system(prs, ConvSystemConfig(system_name="AGAIN",
                                              long_name="AGAIN",
                                              conv_set_name="TAKEN"),
                        conv_set=make_conv_set("TAKEN", [
                            {"short_name": "CH2", "tx_freq": 156.0,
                             "rx_freq": 156.0}]))
    assert prs.to_bytes() == before


def test_rr_conv_channels_both_systems_or_neither():
    """The analog system went in before the P25 set failed."""
    prs = create_blank_prs("t.PRS")
    channels = [ConvChannelData(freq=155.76, name="LE D1", mode="FMN"),
                ConvChannelData(freq=155.85, name="LE P25", mode="P25",
                                nac=0x293)]
    add_rr_conv_channels(prs, "CNTY1", "CNTY1", channels)
    before = prs.to_bytes()
    with pytest.raises(ValueError, match="already exists"):
        # a new analog set name, the same P25 set name (CNTY1P25)
        add_rr_conv_channels(prs, "CNTY1X", "CNTY1X", [
            ConvChannelData(freq=155.91, name="NEW", mode="FMN"),
            ConvChannelData(freq=155.95, name="NEW P25", mode="P25",
                            nac=0x293)])
    assert prs.to_bytes() == before
