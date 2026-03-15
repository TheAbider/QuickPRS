"""Tests for personality cloner, channel renumbering, and auto-naming.

Covers:
- clone_personality with various modification options
- renumber_channels for conv and group sets
- auto_name_talkgroups with compact/numbered/department styles
- CLI commands: clone-personality, renumber, auto-name
"""

import pytest
import shutil
from pathlib import Path
from copy import deepcopy

from quickprs.prs_parser import parse_prs
from quickprs.prs_writer import write_prs
from quickprs.validation import validate_prs, ERROR, WARNING
from quickprs.binary_io import read_uint16_le
from quickprs.record_types import (
    parse_class_header, parse_group_section,
    parse_trunk_channel_section, parse_conv_channel_section,
    parse_system_long_name, is_system_config_data,
)
from quickprs.injector import (
    make_conv_channel, make_conv_set, add_conv_set,
    make_p25_group, make_group_set, add_group_set,
    renumber_channels, auto_name_talkgroups,
    _compact_name, _department_name, _strip_numeric_prefix,
)
from quickprs.cloner import clone_personality
from quickprs.cli import (
    run_cli, cmd_clone_personality, cmd_renumber, cmd_auto_name,
    cmd_create,
)


TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


# ─── Helpers ──────────────────────────────────────────────────────────


def _copy_prs(src, tmp_path, name="work.PRS"):
    """Copy a PRS file to tmp_path and return the path."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


def _create_blank(tmp_path, name="blank.PRS"):
    """Create a blank PRS file and return its path."""
    out = tmp_path / name
    cmd_create(str(out))
    return str(out)


def _get_conv_sets(prs):
    """Parse all conv sets from a PRSFile."""
    ch_sec = prs.get_section_by_class("CConvChannel")
    set_sec = prs.get_section_by_class("CConvSet")
    if not ch_sec or not set_sec:
        return []
    _, _, _, cs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, cs_data)
    _, _, _, ch_data = parse_class_header(ch_sec.raw, 0)
    return parse_conv_channel_section(ch_sec.raw, ch_data,
                                       len(ch_sec.raw), first_count)


def _get_group_sets(prs):
    """Parse all group sets from a PRSFile."""
    grp_sec = prs.get_section_by_class("CP25Group")
    set_sec = prs.get_section_by_class("CP25GroupSet")
    if not grp_sec or not set_sec:
        return []
    _, _, _, gs_data = parse_class_header(set_sec.raw, 0)
    first_count, _ = read_uint16_le(set_sec.raw, gs_data)
    _, _, _, g_data = parse_class_header(grp_sec.raw, 0)
    return parse_group_section(grp_sec.raw, g_data, len(grp_sec.raw),
                                first_count)


def _get_system_long_names(prs):
    """Get all system config long names from a PRS."""
    names = []
    for sec in prs.sections:
        if not sec.class_name and is_system_config_data(sec.raw):
            ln = parse_system_long_name(sec.raw)
            if ln:
                names.append(ln)
    return names


# ─── _strip_numeric_prefix ───────────────────────────────────────────


class TestStripNumericPrefix:
    """Test the numeric prefix stripping utility."""

    def test_strip_prefix(self):
        """Strip '01 ' prefix."""
        assert _strip_numeric_prefix("01 MURS1") == "MURS1"

    def test_strip_two_digit(self):
        """Strip '99 ' prefix."""
        assert _strip_numeric_prefix("99 CH") == "CH"

    def test_no_prefix(self):
        """No numeric prefix leaves name unchanged."""
        assert _strip_numeric_prefix("MURS 1") == "MURS 1"

    def test_single_digit_not_stripped(self):
        """Single digit + space is not a valid prefix."""
        assert _strip_numeric_prefix("1 MURS") == "1 MURS"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert _strip_numeric_prefix("") == ""

    def test_prefix_only(self):
        """Just '01 ' returns empty after strip."""
        assert _strip_numeric_prefix("01 ") == ""


# ─── _compact_name ────────────────────────────────────────────────────


class TestCompactName:
    """Test compact abbreviation generation."""

    def test_dispatch_abbreviation(self):
        """'Dispatch' should abbreviate to 'DISP'."""
        result = _compact_name("Dispatch")
        assert result == "DISP"

    def test_police_dispatch(self):
        """'Police Dispatch' -> 'PD DISP'."""
        result = _compact_name("Police Dispatch")
        assert result == "PD DISP"

    def test_fire_tactical_numbered(self):
        """'Fire Tactical 2' -> 'FD TAC 2'."""
        result = _compact_name("Fire Tactical 2")
        assert result == "FD TAC 2"

    def test_long_name_truncated(self):
        """Names over 8 chars are truncated."""
        result = _compact_name("Seattle Police Dispatch Unit")
        assert len(result) <= 8

    def test_short_word_preserved(self):
        """Words 3 chars or less are preserved as-is."""
        result = _compact_name("PD Tac")
        assert "PD" in result

    def test_empty_returns_empty(self):
        """Empty string returns empty."""
        result = _compact_name("")
        assert result == ""

    def test_single_word(self):
        """Single word gets abbreviation if known."""
        assert _compact_name("Operations") == "OPS"
        assert _compact_name("Emergency") == "EMRG"

    def test_unknown_word_initial(self):
        """Unknown multi-char word uses first letter."""
        result = _compact_name("Yakima")
        assert result == "Y"


# ─── _department_name ─────────────────────────────────────────────────


class TestDepartmentName:
    """Test department-style name generation."""

    def test_police_dispatch(self):
        """'Police Dispatch' -> 'PD DISP'."""
        result = _department_name("Police Dispatch")
        assert result == "PD DISP"

    def test_fire_tactical(self):
        """'Fire Tactical' -> 'FD TAC'."""
        result = _department_name("Fire Tactical")
        assert result == "FD TAC"

    def test_sheriff_operations(self):
        """'Sheriff Operations' -> 'SO OPS'."""
        result = _department_name("Sheriff Operations")
        assert result == "SO OPS"

    def test_unknown_department(self):
        """Unknown department uses first 3 chars."""
        result = _department_name("Metro Dispatch")
        assert result.startswith("MET")

    def test_empty(self):
        """Empty returns empty."""
        result = _department_name("")
        assert result == ""

    def test_truncated_to_8(self):
        """Result is always 8 chars or less."""
        result = _department_name("Police Dispatch Operations Command")
        assert len(result) <= 8


# ─── renumber_channels (conv) ────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRenumberChannelsConv:
    """Test renumbering of conventional channels."""

    def test_renumber_conv_channels(self):
        """Renumber conv channels in a test file."""
        prs = parse_prs(PAWS)
        conv_before = _get_conv_sets(prs)
        if not conv_before:
            pytest.skip("No conv sets in test file")

        first_set = conv_before[0]
        count = renumber_channels(prs, set_name=first_set.name, start=1)
        assert count == len(first_set.channels)

        conv_after = _get_conv_sets(prs)
        first_after = conv_after[0]
        assert first_after.channels[0].short_name.startswith("01 ")
        if len(first_after.channels) > 1:
            assert first_after.channels[1].short_name.startswith("02 ")

    def test_renumber_start_offset(self):
        """Renumber starting at 10."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        first_set = conv[0]
        renumber_channels(prs, set_name=first_set.name, start=10)

        conv_after = _get_conv_sets(prs)
        assert conv_after[0].channels[0].short_name.startswith("10 ")

    def test_renumber_no_set_returns_zero(self):
        """Renumbering non-existent set returns 0."""
        prs = parse_prs(PAWS)
        count = renumber_channels(prs, set_name="NOTHERE", start=1)
        assert count == 0

    def test_renumber_all_conv_sets(self):
        """Renumber all conv sets when set_name is None."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        total = sum(len(cs.channels) for cs in conv)
        count = renumber_channels(prs, set_name=None, start=1)
        assert count == total

    def test_renumber_idempotent(self):
        """Renumbering twice still produces correct prefixes."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        first_name = conv[0].name
        renumber_channels(prs, set_name=first_name, start=1)
        renumber_channels(prs, set_name=first_name, start=1)

        conv_after = _get_conv_sets(prs)
        # Should not have double-prefix like "01 01 ..."
        for ch in conv_after[0].channels:
            sn = ch.short_name
            # After the first '01 ', the next should not be digits + space
            after_prefix = sn[3:]
            assert not (len(after_prefix) >= 3 and
                       after_prefix[:2].isdigit() and
                       after_prefix[2] == ' '), \
                f"Double prefix detected: {sn!r}"

    def test_renumber_short_names_within_limit(self):
        """Renumbered names are still 8 chars or less."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        renumber_channels(prs, set_name=conv[0].name, start=1)

        conv_after = _get_conv_sets(prs)
        for ch in conv_after[0].channels:
            assert len(ch.short_name) <= 8


# ─── renumber_channels (group) ───────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRenumberChannelsGroup:
    """Test renumbering of P25 talkgroups."""

    def test_renumber_group_set(self):
        """Renumber talkgroups in a group set."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        first_name = groups[0].name
        first_count = len(groups[0].groups)
        count = renumber_channels(prs, set_name=first_name,
                                   start=1, set_type="group")
        assert count == first_count

        groups_after = _get_group_sets(prs)
        assert groups_after[0].groups[0].group_name.startswith("01 ")

    def test_renumber_group_no_set(self):
        """Renumbering non-existent group set returns 0."""
        prs = parse_prs(PAWS)
        count = renumber_channels(prs, set_name="NOPE",
                                   set_type="group")
        assert count == 0


# ─── auto_name_talkgroups ────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestAutoNameTalkgroups:
    """Test auto-naming of talkgroup short names from long names."""

    def test_auto_name_compact_style(self):
        """Compact style generates abbreviations."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        first_name = groups[0].name
        count = auto_name_talkgroups(prs, first_name, style="compact")
        assert count > 0

        groups_after = _get_group_sets(prs)
        for g in groups_after[0].groups:
            assert len(g.group_name) <= 8

    def test_auto_name_numbered_style(self):
        """Numbered style uses sequential numbers."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        first_name = groups[0].name
        count = auto_name_talkgroups(prs, first_name, style="numbered")
        assert count > 0

        groups_after = _get_group_sets(prs)
        first_sn = groups_after[0].groups[0].group_name
        assert first_sn.startswith("001 ")

    def test_auto_name_department_style(self):
        """Department style extracts department prefix."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        first_name = groups[0].name
        count = auto_name_talkgroups(prs, first_name, style="department")
        assert count > 0

        groups_after = _get_group_sets(prs)
        for g in groups_after[0].groups:
            assert len(g.group_name) <= 8

    def test_auto_name_nonexistent_set(self):
        """Auto-naming non-existent set returns 0."""
        prs = parse_prs(PAWS)
        count = auto_name_talkgroups(prs, "NOTHERE")
        assert count == 0


# ─── clone_personality ───────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestClonePersonality:
    """Test personality cloning with modifications."""

    def test_clone_exact_copy(self):
        """Cloning without modifications produces identical bytes."""
        prs = parse_prs(PAWS)
        original_bytes = prs.to_bytes()
        cloned = clone_personality(prs)
        cloned_bytes = cloned.to_bytes()
        assert cloned_bytes == original_bytes

    def test_clone_is_independent(self):
        """Modifications to clone don't affect original."""
        prs = parse_prs(PAWS)
        original_sections = len(prs.sections)
        cloned = clone_personality(prs)
        # Modify clone
        if cloned.sections:
            cloned.sections.pop()
        assert len(prs.sections) == original_sections

    def test_clone_with_no_mods(self):
        """Passing None for modifications returns exact copy."""
        prs = parse_prs(PAWS)
        cloned = clone_personality(prs, modifications=None)
        assert cloned.to_bytes() == prs.to_bytes()

    def test_clone_with_empty_mods(self):
        """Passing empty dict returns exact copy."""
        prs = parse_prs(PAWS)
        cloned = clone_personality(prs, modifications={})
        assert cloned.to_bytes() == prs.to_bytes()

    def test_clone_remove_conv_set(self):
        """Clone with remove_sets removes a conv set."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        set_name = conv[0].name
        cloned = clone_personality(prs, {'remove_sets': [set_name]})

        cloned_conv = _get_conv_sets(cloned)
        cloned_names = {s.name for s in cloned_conv}
        assert set_name not in cloned_names

    def test_clone_remove_group_set(self):
        """Clone with remove_sets removes a group set."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        set_name = groups[0].name
        cloned = clone_personality(prs, {'remove_sets': [set_name]})

        cloned_groups = _get_group_sets(cloned)
        cloned_names = {s.name for s in cloned_groups}
        assert set_name not in cloned_names

    def test_clone_enable_tx(self):
        """Clone with enable_tx_sets enables TX on all talkgroups."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        set_name = groups[0].name
        cloned = clone_personality(prs, {'enable_tx_sets': [set_name]})

        cloned_groups = _get_group_sets(cloned)
        target = None
        for gs in cloned_groups:
            if gs.name == set_name:
                target = gs
                break
        assert target is not None
        for g in target.groups:
            assert g.tx is True

    def test_clone_disable_tx(self):
        """Clone with disable_tx_sets disables TX on all talkgroups."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        set_name = groups[0].name
        cloned = clone_personality(prs, {'disable_tx_sets': [set_name]})

        cloned_groups = _get_group_sets(cloned)
        target = None
        for gs in cloned_groups:
            if gs.name == set_name:
                target = gs
                break
        assert target is not None
        for g in target.groups:
            assert g.tx is False

    def test_clone_add_talkgroups(self):
        """Clone with add_talkgroups adds new talkgroups."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        set_name = groups[0].name
        original_count = len(groups[0].groups)

        new_tgs = [(60001, "NEW TG1", "New Talkgroup 1"),
                    (60002, "NEW TG2", "New Talkgroup 2")]

        cloned = clone_personality(prs, {
            'add_talkgroups': {set_name: new_tgs}
        })

        cloned_groups = _get_group_sets(cloned)
        target = None
        for gs in cloned_groups:
            if gs.name == set_name:
                target = gs
                break
        assert target is not None
        assert len(target.groups) == original_count + 2

    def test_clone_validates_ok(self):
        """Cloned personality passes validation."""
        prs = parse_prs(PAWS)
        cloned = clone_personality(prs)
        issues = validate_prs(cloned)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0


# ─── CLI: clone-personality ──────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestCLIClonePersonality:
    """Test clone-personality CLI command."""

    def test_cli_clone_exact(self, tmp_path):
        """CLI clone without modifications creates copy."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        out = str(tmp_path / "clone.PRS")
        rc = cmd_clone_personality(src, output=out)
        assert rc == 0
        assert Path(out).exists()
        # Both files should parse
        parse_prs(out)

    def test_cli_clone_with_name(self, tmp_path):
        """CLI clone with --name sets personality name."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        out = str(tmp_path / "clone.PRS")
        rc = cmd_clone_personality(src, output=out, name="TESTNAME")
        assert rc == 0

    def test_cli_clone_remove_set(self, tmp_path):
        """CLI clone with --remove-set removes a set."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        out = str(tmp_path / "clone.PRS")
        rc = cmd_clone_personality(src, output=out,
                                    remove_sets=[conv[0].name])
        assert rc == 0

        cloned = parse_prs(out)
        cloned_conv = _get_conv_sets(cloned)
        names = {s.name for s in cloned_conv}
        assert conv[0].name not in names

    def test_cli_clone_enable_tx(self, tmp_path):
        """CLI clone with --enable-tx modifies TX."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        out = str(tmp_path / "clone.PRS")
        rc = cmd_clone_personality(src, output=out,
                                    enable_tx=[groups[0].name])
        assert rc == 0

    def test_cli_clone_via_run_cli(self, tmp_path):
        """clone-personality works through run_cli dispatcher."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        out = str(tmp_path / "clone.PRS")
        rc = run_cli(["clone-personality", src, "-o", out])
        assert rc == 0
        assert Path(out).exists()


# ─── CLI: renumber ───────────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestCLIRenumber:
    """Test renumber CLI command."""

    def test_cli_renumber_conv(self, tmp_path):
        """CLI renumber command works on conv channels."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "renumbered.PRS")
        rc = cmd_renumber(work, set_name=conv[0].name, output=out)
        assert rc == 0

        result = parse_prs(out)
        result_conv = _get_conv_sets(result)
        assert result_conv[0].channels[0].short_name.startswith("01 ")

    def test_cli_renumber_no_match(self, tmp_path):
        """CLI renumber returns 1 for non-existent set."""
        work = _copy_prs(PAWS, tmp_path)
        rc = cmd_renumber(work, set_name="NOTASET")
        assert rc == 1

    def test_cli_renumber_via_run_cli(self, tmp_path):
        """renumber works through run_cli dispatcher."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "renumbered.PRS")
        rc = run_cli(["renumber", work, "--set", conv[0].name,
                       "-o", out])
        assert rc == 0

    def test_cli_renumber_start_offset(self, tmp_path):
        """CLI renumber with --start flag."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "renumbered.PRS")
        rc = cmd_renumber(work, set_name=conv[0].name, start=5,
                          output=out)
        assert rc == 0

        result = parse_prs(out)
        result_conv = _get_conv_sets(result)
        assert result_conv[0].channels[0].short_name.startswith("05 ")


# ─── CLI: auto-name ──────────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestCLIAutoName:
    """Test auto-name CLI command."""

    def test_cli_auto_name_compact(self, tmp_path):
        """CLI auto-name with compact style."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "named.PRS")
        rc = cmd_auto_name(work, groups[0].name, style="compact",
                           output=out)
        assert rc == 0

        result = parse_prs(out)
        result_groups = _get_group_sets(result)
        for g in result_groups[0].groups:
            assert len(g.group_name) <= 8

    def test_cli_auto_name_numbered(self, tmp_path):
        """CLI auto-name with numbered style."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "named.PRS")
        rc = cmd_auto_name(work, groups[0].name, style="numbered",
                           output=out)
        assert rc == 0

    def test_cli_auto_name_no_set(self, tmp_path):
        """CLI auto-name returns 1 for non-existent set."""
        work = _copy_prs(PAWS, tmp_path)
        rc = cmd_auto_name(work, "NOTASET")
        assert rc == 1

    def test_cli_auto_name_via_run_cli(self, tmp_path):
        """auto-name works through run_cli dispatcher."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets in test file")

        work = _copy_prs(PAWS, tmp_path)
        out = str(tmp_path / "named.PRS")
        rc = run_cli(["auto-name", work, "--set", groups[0].name,
                       "-o", out])
        assert rc == 0


# ─── Integration: renumber + validate ────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRenumberValidation:
    """Verify renumbered files pass validation."""

    def test_renumbered_conv_validates(self):
        """Renumbered conv file passes validation."""
        prs = parse_prs(PAWS)
        conv = _get_conv_sets(prs)
        if not conv:
            pytest.skip("No conv sets")

        renumber_channels(prs, set_name=conv[0].name)
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_renumbered_groups_validates(self):
        """Renumbered group file passes validation."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets")

        renumber_channels(prs, set_name=groups[0].name,
                          set_type="group")
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0


# ─── Integration: auto-name + validate ───────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestAutoNameValidation:
    """Verify auto-named files pass validation."""

    def test_auto_named_compact_validates(self):
        """Auto-named compact file passes validation."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets")

        auto_name_talkgroups(prs, groups[0].name, style="compact")
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_auto_named_numbered_validates(self):
        """Auto-named numbered file passes validation."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets")

        auto_name_talkgroups(prs, groups[0].name, style="numbered")
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0

    def test_auto_named_department_validates(self):
        """Auto-named department file passes validation."""
        prs = parse_prs(PAWS)
        groups = _get_group_sets(prs)
        if not groups:
            pytest.skip("No group sets")

        auto_name_talkgroups(prs, groups[0].name, style="department")
        issues = validate_prs(prs)
        errors = [(s, m) for s, m in issues if s == ERROR]
        assert len(errors) == 0
