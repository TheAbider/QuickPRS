"""PRS file writer — reassembles sections back to binary.

For Sprint 1, this is trivial: concatenate all section raw bytes.
Guaranteed byte-identical roundtrip because we preserve raw bytes.
"""

import logging
from pathlib import Path
import shutil

logger = logging.getLogger("quickprs")


def write_prs(prs_file, filepath, backup=True):
    """Write a PRSFile back to disk.

    Args:
        prs_file: PRSFile object with ordered sections
        filepath: output path
        backup: if True and file exists, create .bak backup first
                Also creates a timestamped backup via the backup module.
    """
    path = Path(filepath)

    if backup and path.exists():
        bak = path.with_suffix(path.suffix + '.bak')
        shutil.copy2(path, bak)

        # Also create a timestamped auto-backup
        try:
            from .backup import create_backup
            create_backup(path)
        except Exception as e:
            logger.debug("Auto-backup skipped: %s", e)

    data = prs_file.to_bytes()
    path.write_bytes(data)
    return len(data)
