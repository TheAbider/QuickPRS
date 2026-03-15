"""Tests for CLI remove, edit, and enhanced info commands."""

import pytest
import shutil
import tempfile
from pathlib import Path

from quickprs.cli import (
    run_cli, cmd_info, cmd_remove, cmd_edit,
)
from quickprs.prs_parser import parse_prs
from conftest import cached_parse_prs
from quickprs.record_types import parse_personality_section

TESTDATA = Path(__file__).parent / "testdata"
CLAUDE = TESTDATA / "claude test.PRS"
PAWS = TESTDATA / "PAWSOVERMAWS.PRS"


def _copy_prs(src, tmp_path, name="test.PRS"):
    """Copy a PRS file to tmp_path for modification."""
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return str(dst)


# ─── cmd_remove: system ──────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRemoveSystem:
    """Test removing systems by long name."""

    def test_remove_system_by_long_name(self, capsys, tmp_path):
        """Remove a system config by its long display name."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "system", "PSERN SEATTLE")
        assert result == 0
        out = capsys.readouterr().out
        assert "Removed system 'PSERN SEATTLE'" in out
        # Verify system is gone
        prs = parse_prs(path)
        from quickprs.record_types import (
            parse_system_long_name, is_system_config_data,
        )
        long_names = []
        for sec in prs.sections:
            if not sec.class_name and is_system_config_data(sec.raw):
                ln = parse_system_long_name(sec.raw)
                if ln:
                    long_names.append(ln)
        assert "PSERN SEATTLE" not in long_names

    def test_remove_system_not_found(self, capsys, tmp_path):
        """Removing a nonexistent system should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "system", "NONEXISTENT SYSTEM")
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_remove_system_via_run_cli(self, capsys, tmp_path):
        """Remove via run_cli dispatcher."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["remove", path, "system", "PSERN SEATTLE"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Removed" in out


# ─── cmd_remove: trunk-set ───────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestRemoveTrunkSet:
    """Test removing trunk frequency sets."""

    def test_remove_trunk_set(self, capsys, tmp_path):
        """Remove a trunk set by name."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "trunk-set", "PSERN")
        assert result == 0
        out = capsys.readouterr().out
        assert "Removed trunk set 'PSERN'" in out
        # Verify set is gone
        from quickprs.cli import _parse_trunk_sets
        prs = parse_prs(path)
        sets = _parse_trunk_sets(prs)
        names = [s.name for s in sets]
        assert "PSERN" not in names
        # Other sets should remain
        assert len(sets) == 6  # was 7

    def test_remove_trunk_set_not_found(self, capsys, tmp_path):
        """Removing a nonexistent trunk set should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "trunk-set", "NOSUCHSET")
        assert result == 1

    def test_remove_trunk_set_validates(self, capsys, tmp_path):
        """Output should include validation status."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "trunk-set", "PSERN")
        out = capsys.readouterr().out
        assert "Validation:" in out

    def test_remove_trunk_set_via_run_cli(self, capsys, tmp_path):
        """Remove trunk-set via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["remove", path, "trunk-set", "PSERN"])
        assert result == 0

    def test_remove_last_trunk_set(self, capsys, tmp_path):
        """Removing the only trunk set should remove sections entirely."""
        path = _copy_prs(CLAUDE, tmp_path)
        # Claude test has 1 trunk set
        from quickprs.cli import _parse_trunk_sets
        prs = parse_prs(path)
        sets = _parse_trunk_sets(prs)
        assert len(sets) == 1
        name = sets[0].name

        result = cmd_remove(path, "trunk-set", name)
        assert result == 0
        prs2 = parse_prs(path)
        assert prs2.get_section_by_class("CTrunkChannel") is None
        assert prs2.get_section_by_class("CTrunkSet") is None


# ─── cmd_remove: group-set ───────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestRemoveGroupSet:
    """Test removing P25 talkgroup sets."""

    def test_remove_group_set(self, capsys, tmp_path):
        """Remove a group set by name."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "group-set", "PSERN PD")
        assert result == 0
        out = capsys.readouterr().out
        assert "Removed group set 'PSERN PD'" in out
        # Verify
        from quickprs.cli import _parse_group_sets
        prs = parse_prs(path)
        sets = _parse_group_sets(prs)
        names = [s.name for s in sets]
        assert "PSERN PD" not in names
        assert len(sets) == 6  # was 7

    def test_remove_group_set_not_found(self, capsys, tmp_path):
        """Removing a nonexistent group set should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "group-set", "NOSUCHSET")
        assert result == 1

    def test_remove_group_set_via_run_cli(self, capsys, tmp_path):
        """Remove group-set via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["remove", path, "group-set", "PSERN PD"])
        assert result == 0

    def test_remove_last_group_set(self, capsys, tmp_path):
        """Removing the only group set should remove sections entirely."""
        path = _copy_prs(CLAUDE, tmp_path)
        from quickprs.cli import _parse_group_sets
        prs = parse_prs(path)
        sets = _parse_group_sets(prs)
        assert len(sets) == 1
        name = sets[0].name

        result = cmd_remove(path, "group-set", name)
        assert result == 0
        prs2 = parse_prs(path)
        assert prs2.get_section_by_class("CP25Group") is None
        assert prs2.get_section_by_class("CP25GroupSet") is None


# ─── cmd_remove: conv-set ───────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRemoveConvSet:
    """Test removing conventional channel sets."""

    def test_remove_conv_set(self, capsys, tmp_path):
        """Remove a conv set by name."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "conv-set", "FURRY NB")
        assert result == 0
        out = capsys.readouterr().out
        assert "Removed conv set 'FURRY NB'" in out
        # Verify
        from quickprs.cli import _parse_conv_sets
        prs = parse_prs(path)
        sets = _parse_conv_sets(prs)
        names = [s.name for s in sets]
        assert "FURRY NB" not in names
        assert len(sets) == 2  # was 3

    def test_remove_conv_set_not_found(self, capsys, tmp_path):
        """Removing a nonexistent conv set should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_remove(path, "conv-set", "NOSUCHSET")
        assert result == 1

    def test_remove_conv_set_via_run_cli(self, capsys, tmp_path):
        """Remove conv-set via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["remove", path, "conv-set", "FURRY NB"])
        assert result == 0

    def test_remove_unknown_type(self, capsys, tmp_path):
        """Unknown remove type should be rejected by argparse."""
        path = _copy_prs(PAWS, tmp_path)
        with pytest.raises(SystemExit):
            run_cli(["remove", path, "unknown-type", "NAME"])

    def test_remove_output_flag(self, capsys, tmp_path):
        """Remove with -o should write to a different file."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        dst = str(tmp_path / "output.PRS")
        result = run_cli(["remove", src, "trunk-set", "PSERN",
                          "-o", dst])
        assert result == 0
        # Source should be unchanged
        from quickprs.cli import _parse_trunk_sets
        prs = parse_prs(src)
        names = [s.name for s in _parse_trunk_sets(prs)]
        assert "PSERN" in names
        # Destination should have PSERN removed
        prs2 = parse_prs(dst)
        names2 = [s.name for s in _parse_trunk_sets(prs2)]
        assert "PSERN" not in names2


# ─── cmd_edit: personality ────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestEditPersonality:
    """Test editing personality metadata."""

    def test_edit_name(self, capsys, tmp_path):
        """Edit personality filename."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path, name="NEW NAME.PRS")
        assert result == 0
        out = capsys.readouterr().out
        assert "name='NEW NAME.PRS'" in out
        # Verify
        prs = parse_prs(path)
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "NEW NAME.PRS"

    def test_edit_author(self, capsys, tmp_path):
        """Edit saved-by field."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path, author="NewAuthor")
        assert result == 0
        out = capsys.readouterr().out
        assert "author='NewAuthor'" in out
        # Verify
        prs = parse_prs(path)
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.saved_by == "NewAuthor"

    def test_edit_name_and_author(self, capsys, tmp_path):
        """Edit both name and author at once."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path, name="EDITED.PRS", author="Editor")
        assert result == 0
        prs = parse_prs(path)
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "EDITED.PRS"
        assert p.saved_by == "Editor"

    def test_edit_no_changes(self, capsys, tmp_path):
        """Edit with no flags should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path)
        assert result == 1
        err = capsys.readouterr().err
        assert "No changes" in err

    def test_edit_name_via_run_cli(self, capsys, tmp_path):
        """Edit --name via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["edit", path, "--name", "CLI EDIT.PRS"])
        assert result == 0
        prs = parse_prs(path)
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "CLI EDIT.PRS"

    def test_edit_author_via_run_cli(self, capsys, tmp_path):
        """Edit --author via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["edit", path, "--author", "CLI Author"])
        assert result == 0

    def test_edit_validates(self, capsys, tmp_path):
        """Edit output should include validation."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path, name="VALID.PRS")
        out = capsys.readouterr().out
        assert "Validation:" in out

    def test_edit_output_flag(self, capsys, tmp_path):
        """Edit with -o should write to a different file."""
        src = _copy_prs(PAWS, tmp_path, "source.PRS")
        dst = str(tmp_path / "edited.PRS")
        result = run_cli(["edit", src, "--name", "EDITED.PRS",
                          "-o", dst])
        assert result == 0
        # Source should be unchanged
        prs = parse_prs(src)
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename != "EDITED.PRS"
        # Destination should have new name
        prs2 = parse_prs(dst)
        sec2 = prs2.get_section_by_class("CPersonality")
        p2 = parse_personality_section(sec2.raw)
        assert p2.filename == "EDITED.PRS"


# ─── cmd_edit: set rename ────────────────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestEditRenameSet:
    """Test renaming data sets."""

    def test_rename_trunk_set(self, capsys, tmp_path):
        """Rename a trunk set."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="trunk",
                          rename_old="PSERN",
                          rename_new="NEWPSERN")
        assert result == 0
        out = capsys.readouterr().out
        assert "renamed trunk set" in out
        # Verify
        from quickprs.cli import _parse_trunk_sets
        prs = parse_prs(path)
        sets = _parse_trunk_sets(prs)
        names = [s.name for s in sets]
        assert "PSERN" not in names
        assert "NEWPSERN" in names

    def test_rename_group_set(self, capsys, tmp_path):
        """Rename a group set."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="group",
                          rename_old="PSERN PD",
                          rename_new="NEW PD")
        assert result == 0
        from quickprs.cli import _parse_group_sets
        prs = parse_prs(path)
        sets = _parse_group_sets(prs)
        names = [s.name for s in sets]
        assert "PSERN PD" not in names
        assert "NEW PD" in names

    def test_rename_conv_set(self, capsys, tmp_path):
        """Rename a conv set."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="conv",
                          rename_old="FURRY NB",
                          rename_new="NEW NB")
        assert result == 0
        from quickprs.cli import _parse_conv_sets
        prs = parse_prs(path)
        sets = _parse_conv_sets(prs)
        names = [s.name for s in sets]
        assert "FURRY NB" not in names
        assert "NEW NB" in names

    def test_rename_set_not_found(self, capsys, tmp_path):
        """Renaming a nonexistent set should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="trunk",
                          rename_old="NOSUCHSET",
                          rename_new="NEWNAME")
        assert result == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_rename_unknown_type(self, capsys, tmp_path):
        """Unknown set type should return 1."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="badtype",
                          rename_old="PSERN",
                          rename_new="NEWNAME")
        assert result == 1

    def test_rename_via_run_cli(self, capsys, tmp_path):
        """--rename-set via run_cli."""
        path = _copy_prs(PAWS, tmp_path)
        result = run_cli(["edit", path,
                          "--rename-set", "trunk", "PSERN", "NEWPSERN"])
        assert result == 0

    def test_rename_truncates_to_8(self, capsys, tmp_path):
        """New name should be truncated to 8 chars."""
        path = _copy_prs(PAWS, tmp_path)
        result = cmd_edit(path,
                          rename_set_type="trunk",
                          rename_old="PSERN",
                          rename_new="VERYLONGNAME")
        assert result == 0
        from quickprs.cli import _parse_trunk_sets
        prs = parse_prs(path)
        sets = _parse_trunk_sets(prs)
        new_names = [s.name for s in sets if s.name.startswith("VERYLONG")]
        assert len(new_names) == 1
        assert len(new_names[0]) <= 8


# ─── cmd_info: enhanced / --detail ───────────────────────────────────


@pytest.mark.skipif(not PAWS.exists() or not CLAUDE.exists(), reason="Test PRS data not available")
class TestInfoDetail:
    """Test the --detail flag for enhanced info output."""

    def test_detail_flag_accepted(self, capsys):
        """--detail flag should be accepted and not crash."""
        result = cmd_info(str(PAWS), detail=True)
        assert result == 0

    def test_detail_shows_wan_entries(self, capsys):
        """Detail mode should show WAN entries."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "WAN Entries" in out
        assert "WACN=" in out
        assert "SysID=" in out

    def test_detail_shows_iden_base_freqs(self, capsys):
        """Detail mode should show IDEN base frequencies."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "MHz]" in out  # base freq list ends with MHz]

    def test_detail_shows_conv_channel_details(self, capsys):
        """Detail mode should show conv channel frequencies."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "Conv Channel Details:" in out

    def test_detail_shows_option_sections(self, capsys):
        """Detail mode should list option section classes."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "Option Sections" in out

    def test_detail_shows_size_breakdown(self, capsys):
        """Detail mode should show file size breakdown."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "Size Breakdown:" in out
        assert "bytes" in out
        assert "%" in out

    def test_detail_size_breakdown_totals(self, capsys):
        """Size breakdown should show total matching file size."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        assert "Total" in out
        assert "46,822" in out  # PAWS file size

    def test_detail_via_run_cli(self, capsys):
        """--detail via run_cli should work."""
        result = run_cli(["info", str(PAWS), "--detail"])
        assert result == 0
        out = capsys.readouterr().out
        assert "WAN Entries" in out
        assert "Size Breakdown:" in out

    def test_detail_short_flag(self, capsys):
        """-d short flag via run_cli."""
        result = run_cli(["info", str(PAWS), "-d"])
        assert result == 0
        out = capsys.readouterr().out
        assert "Size Breakdown:" in out

    def test_detail_simple_file(self, capsys):
        """Detail on simple file should not crash."""
        result = cmd_info(str(CLAUDE), detail=True)
        assert result == 0
        out = capsys.readouterr().out
        # Should still show size breakdown
        assert "Size Breakdown:" in out

    def test_info_no_detail_unchanged(self, capsys):
        """Without --detail, output should be unchanged from before."""
        result = cmd_info(str(PAWS))
        assert result == 0
        out = capsys.readouterr().out
        # Standard output should be present
        assert "P25 Trunked" in out
        assert "Group Sets (7)" in out
        # Detail-only output should NOT be present
        assert "WAN Entries" not in out
        assert "Size Breakdown:" not in out
        assert "Conv Channel Details:" not in out

    def test_detail_preferred_entries(self, capsys):
        """Detail mode should show preferred system table if present."""
        cmd_info(str(PAWS), detail=True)
        out = capsys.readouterr().out
        # PAWS may or may not have preferred entries — just don't crash
        assert "Size Breakdown:" in out


# ─── Injector-level removal tests ────────────────────────────────────


class TestInjectorRemoveFunctions:
    """Direct tests of injector removal functions."""

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_trunk_set_direct(self, tmp_path):
        """Direct call to remove_trunk_set."""
        from quickprs.injector import remove_trunk_set
        path = _copy_prs(PAWS, tmp_path)
        prs = parse_prs(path)
        result = remove_trunk_set(prs, "PSERN")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_trunk_set_nonexistent(self):
        """remove_trunk_set returns False for nonexistent set."""
        from quickprs.injector import remove_trunk_set
        prs = cached_parse_prs(str(PAWS))
        result = remove_trunk_set(prs, "NOSET")
        assert result is False

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_group_set_direct(self, tmp_path):
        """Direct call to remove_group_set."""
        from quickprs.injector import remove_group_set
        prs = cached_parse_prs(str(PAWS))
        result = remove_group_set(prs, "PSERN PD")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_group_set_nonexistent(self):
        """remove_group_set returns False for nonexistent set."""
        from quickprs.injector import remove_group_set
        prs = cached_parse_prs(str(PAWS))
        result = remove_group_set(prs, "NOSET")
        assert result is False

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_conv_set_direct(self, tmp_path):
        """Direct call to remove_conv_set."""
        from quickprs.injector import remove_conv_set
        prs = cached_parse_prs(str(PAWS))
        result = remove_conv_set(prs, "FURRY NB")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_conv_set_nonexistent(self):
        """remove_conv_set returns False for nonexistent set."""
        from quickprs.injector import remove_conv_set
        prs = cached_parse_prs(str(PAWS))
        result = remove_conv_set(prs, "NOSET")
        assert result is False

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_edit_personality_direct(self):
        """Direct call to edit_personality."""
        from quickprs.injector import edit_personality
        prs = cached_parse_prs(str(PAWS))
        result = edit_personality(prs, filename="NEW.PRS")
        assert result is True
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        assert p.filename == "NEW.PRS"

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_edit_personality_no_change(self):
        """edit_personality returns False when nothing changes."""
        from quickprs.injector import edit_personality
        prs = cached_parse_prs(str(PAWS))
        sec = prs.get_section_by_class("CPersonality")
        p = parse_personality_section(sec.raw)
        result = edit_personality(prs, filename=p.filename)
        assert result is False

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_rename_trunk_set_direct(self):
        """Direct call to rename_trunk_set."""
        from quickprs.injector import rename_trunk_set
        prs = cached_parse_prs(str(PAWS))
        result = rename_trunk_set(prs, "PSERN", "RENAMED")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_rename_group_set_direct(self):
        """Direct call to rename_group_set."""
        from quickprs.injector import rename_group_set
        prs = cached_parse_prs(str(PAWS))
        result = rename_group_set(prs, "PSERN PD", "NEW PD")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_rename_conv_set_direct(self):
        """Direct call to rename_conv_set."""
        from quickprs.injector import rename_conv_set
        prs = cached_parse_prs(str(PAWS))
        result = rename_conv_set(prs, "FURRY NB", "NEW NB")
        assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_rename_nonexistent(self):
        """Rename returns False for nonexistent set."""
        from quickprs.injector import rename_trunk_set
        prs = cached_parse_prs(str(PAWS))
        result = rename_trunk_set(prs, "NOSET", "NEWNAME")
        assert result is False

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_wan_entry_direct(self):
        """Direct call to remove_wan_entry."""
        from quickprs.injector import remove_wan_entry
        prs = cached_parse_prs(str(PAWS))
        # PAWS has WAN entries
        wan_sec = prs.get_section_by_class("CP25TrkWan")
        assert wan_sec is not None
        from quickprs.record_types import parse_wan_section
        entries = parse_wan_section(wan_sec.raw)
        if entries:
            name = entries[0].wan_name.strip()
            result = remove_wan_entry(prs, name)
            assert result is True

    @pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
    def test_remove_wan_entry_not_found(self):
        """remove_wan_entry returns False for nonexistent entry."""
        from quickprs.injector import remove_wan_entry
        prs = cached_parse_prs(str(PAWS))
        result = remove_wan_entry(prs, "NOWAN")
        assert result is False

    def test_remove_no_sections(self):
        """Remove functions return False when sections don't exist."""
        from quickprs.injector import (
            remove_trunk_set, remove_group_set, remove_conv_set,
        )
        from quickprs.prs_parser import PRSFile
        prs = PRSFile(sections=[], file_size=10)
        assert remove_trunk_set(prs, "X") is False
        assert remove_group_set(prs, "X") is False
        assert remove_conv_set(prs, "X") is False

    def test_rename_no_sections(self):
        """Rename functions return False when sections don't exist."""
        from quickprs.injector import (
            rename_trunk_set, rename_group_set, rename_conv_set,
        )
        from quickprs.prs_parser import PRSFile
        prs = PRSFile(sections=[], file_size=10)
        assert rename_trunk_set(prs, "X", "Y") is False
        assert rename_group_set(prs, "X", "Y") is False
        assert rename_conv_set(prs, "X", "Y") is False


# ─── Integration: remove + validate ──────────────────────────────────


@pytest.mark.skipif(not PAWS.exists(), reason="Test PRS data not available")
class TestRemoveIntegration:
    """Integration tests — remove then validate."""

    def test_remove_trunk_validates(self, tmp_path):
        """File should validate after trunk set removal."""
        from quickprs.validation import validate_prs, ERROR
        path = _copy_prs(PAWS, tmp_path)
        cmd_remove(path, "trunk-set", "PSERN")
        prs = parse_prs(path)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_remove_group_validates(self, tmp_path):
        """File should validate after group set removal."""
        from quickprs.validation import validate_prs, ERROR
        path = _copy_prs(PAWS, tmp_path)
        cmd_remove(path, "group-set", "PSERN PD")
        prs = parse_prs(path)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_remove_conv_validates(self, tmp_path):
        """File should validate after conv set removal."""
        from quickprs.validation import validate_prs, ERROR
        path = _copy_prs(PAWS, tmp_path)
        cmd_remove(path, "conv-set", "FURRY NB")
        prs = parse_prs(path)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_edit_validates(self, tmp_path):
        """File should validate after personality edit."""
        from quickprs.validation import validate_prs, ERROR
        path = _copy_prs(PAWS, tmp_path)
        cmd_edit(path, name="EDITED.PRS", author="Tester")
        prs = parse_prs(path)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_rename_validates(self, tmp_path):
        """File should validate after set rename."""
        from quickprs.validation import validate_prs, ERROR
        path = _copy_prs(PAWS, tmp_path)
        cmd_edit(path, rename_set_type="trunk",
                 rename_old="PSERN", rename_new="NEWNAME")
        prs = parse_prs(path)
        issues = validate_prs(prs)
        errors = [m for s, m in issues if s == ERROR]
        assert len(errors) == 0, f"Errors: {errors}"

    def test_multiple_removes(self, tmp_path):
        """Multiple sequential removes should all work."""
        path = _copy_prs(PAWS, tmp_path)
        assert cmd_remove(path, "trunk-set", "PSERN") == 0
        assert cmd_remove(path, "group-set", "PSERN PD") == 0
        assert cmd_remove(path, "conv-set", "FURRY NB") == 0
        prs = parse_prs(path)
        from quickprs.cli import (
            _parse_trunk_sets, _parse_group_sets, _parse_conv_sets,
        )
        assert "PSERN" not in [s.name for s in _parse_trunk_sets(prs)]
        assert "PSERN PD" not in [s.name for s in _parse_group_sets(prs)]
        assert "FURRY NB" not in [s.name for s in _parse_conv_sets(prs)]
