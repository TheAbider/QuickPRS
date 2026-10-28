"""platformConfig (radio options) editing: real attributes only, values
checked, nested elements addressed exactly, and the XML placed where RPM
keeps it."""

import re

import pytest

from quickprs import archive
from quickprs.builder import create_blank_prs
from quickprs.option_maps import (
    set_platform_option, extract_platform_xml, list_platform_options,
    _DEFAULT_PLATFORM_XML,
)


@pytest.fixture
def blank():
    return create_blank_prs()


def test_default_xml_is_rpm_new_radio():
    assert _DEFAULT_PLATFORM_XML.startswith("<platformConfig><progButtons")
    assert 'batteryType="LITHIUM_ION_POLY"' in _DEFAULT_PLATFORM_XML
    assert "ledEnabled" not in _DEFAULT_PLATFORM_XML
    assert "reportInterval" not in _DEFAULT_PLATFORM_XML


def test_first_option_adds_xml_in_place(blank):
    """The XML replaces the empty string RPM leaves after the IDEN sets;
    the fields around it keep their places."""
    tail_before = archive.document_from_prs(blank).root.parts[-1]
    set_platform_option(blank, "gps", "gpsMode", "OFF")
    assert archive.check(blank) == []
    tail_after = archive.document_from_prs(blank).root.parts[-1]
    assert tail_after[:6] == tail_before[:6]
    assert tail_after.endswith(tail_before[7:])
    assert 'gpsMode="OFF"' in extract_platform_xml(blank)


@pytest.mark.parametrize("section,attr,value,why", [
    ("gps", "gpsModee", "ON", "no attribute 'gpsModee'"),
    ("gps", "gpsMode", "BANANA", "must be ON or OFF"),
    ("misc", "batteryType", "STANDARD", "must be one of"),
    ("audioConfig/microphone[micType=INTERNAL]", "gain", "99",
     "must be <= 12"),
    ("nosuchsection", "x", "1", "'nosuchsection' not found"),
])
def test_bad_options_rejected(blank, section, attr, value, why):
    with pytest.raises(ValueError, match=re.escape(why)):
        set_platform_option(blank, section, attr, value)


def test_known_attribute_can_be_created(blank):
    set_platform_option(blank, "misc", "password", "1234")
    assert 'password="1234"' in extract_platform_xml(blank)


def test_nested_element_is_the_one_changed(blank):
    set_platform_option(blank, "audioConfig/microphone[micType=INTERNAL]",
                        "alc", "ON")
    mics = re.findall(r"<microphone [^>]*>", extract_platform_xml(blank))
    assert 'micType="INTERNAL" alc="ON"' in mics[0]
    assert 'micType="EXTERNAL" alc="OFF"' in mics[1]
    assert "<audioConfig alc=" not in extract_platform_xml(blank)


def test_listed_paths_round_trip(blank):
    """Every path list_platform_options shows can be written back (the GUI
    Radio Options dialog does exactly this)."""
    set_platform_option(blank, "gps", "gpsMode", "ON")
    for _, element, attr, value in list_platform_options(blank):
        set_platform_option(blank, element, attr, value)
    assert archive.check(blank) == []
