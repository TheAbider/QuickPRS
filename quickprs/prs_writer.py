"""PRS file writer — reassembles sections back to binary.

Before writing, the archive is walked (see archive.py): every MFC class tag
and list count is set to what RPM expects, so a personality edited by any
code path still opens in RPM.  An edit that leaves a previously readable
file in a state the walker cannot follow is refused instead of written.
"""

import logging
from pathlib import Path
import shutil

from . import archive

logger = logging.getLogger("quickprs")


class UnsafeWriteError(ValueError):
    """The personality would not open in RPM, so it was not written."""


def prepare_for_write(prs_file):
    """Fix class tags and list counts in place; return the bytes to write.

    Raises UnsafeWriteError when the file was readable when it was loaded
    (or built) but no longer is.  Files QuickPRS could never follow (an
    unknown RPM layout) are passed through unchanged with a warning, as
    before.
    """
    data = prs_file.to_bytes()
    try:
        fixed = archive.repair_bytes(data)
    except archive.WalkError as e:
        if getattr(prs_file, "archive_ok", None):
            raise UnsafeWriteError(
                f"not written: after this edit the personality no longer "
                f"follows RPM's file structure ({e})") from e
        logger.warning("Archive structure not verified (%s); writing the "
                       "file unchanged", e)
        return data
    if fixed != data:
        from .prs_parser import parse_prs_bytes
        logger.info("Rewrote archive class tags and list counts")
        prs_file.sections = parse_prs_bytes(fixed, verify=False).sections
        prs_file.file_size = len(fixed)
    prs_file.archive_ok = True
    return fixed


def write_prs(prs_file, filepath, backup=True):
    """Write a PRSFile back to disk.

    Args:
        prs_file: PRSFile object with ordered sections
        filepath: output path
        backup: if True and file exists, create .bak backup first
                Also creates a timestamped backup via the backup module.

    Raises:
        UnsafeWriteError: the edit broke the file's structure; nothing was
            written.
    """
    path = Path(filepath)
    data = prepare_for_write(prs_file)

    if backup and path.exists():
        bak = path.with_suffix(path.suffix + '.bak')
        shutil.copy2(path, bak)

        # Also create a timestamped auto-backup
        try:
            from .backup import create_backup
            create_backup(path)
        except Exception as e:
            logger.debug("Auto-backup skipped: %s", e)

    path.write_bytes(data)
    return len(data)
