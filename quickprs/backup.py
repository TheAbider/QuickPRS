"""Auto-backup system for PRS files.

Creates timestamped backups in a .quickprs_backups directory next to the
original file. Old backups are automatically pruned to keep disk usage
reasonable.
"""

import shutil
from pathlib import Path
from datetime import datetime

BACKUP_DIR_NAME = ".quickprs_backups"
MAX_BACKUPS = 10


def create_backup(filepath, backup_dir=None):
    """Create a timestamped backup of a PRS file.

    Backups are stored in a .quickprs_backups directory next to the file.
    Only keeps the last MAX_BACKUPS copies.

    Returns: backup file path
    """
    src = Path(filepath)
    if not src.exists():
        raise FileNotFoundError(f"File not found: {src}")

    if backup_dir is None:
        backup_dir = src.parent / BACKUP_DIR_NAME
    else:
        backup_dir = Path(backup_dir)
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"{src.stem}_{timestamp}{src.suffix}"
    backup_path = backup_dir / backup_name

    shutil.copy2(str(src), str(backup_path))

    # Prune old backups for this specific file (by stem prefix)
    backups = sorted(
        backup_dir.glob(f"{src.stem}_*{src.suffix}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[MAX_BACKUPS:]:
        old.unlink()

    return str(backup_path)


def list_backups(filepath):
    """List available backups for a PRS file.

    Returns: list of (index, path, mtime) tuples, newest first.
             Index 1 = most recent.
    """
    src = Path(filepath)
    backup_dir = src.parent / BACKUP_DIR_NAME

    if not backup_dir.exists():
        return []

    backups = sorted(
        backup_dir.glob(f"{src.stem}_*{src.suffix}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    result = []
    for i, bp in enumerate(backups, 1):
        mtime = datetime.fromtimestamp(bp.stat().st_mtime)
        result.append((i, bp, mtime))

    return result


def restore_backup(filepath, backup_path=None, index=None):
    """Restore a PRS file from a backup.

    If backup_path is None and index is None, restores from the most
    recent backup. If index is given, restores from the Nth most recent
    backup (1 = newest).

    Returns: the backup path that was restored from.
    """
    src = Path(filepath)

    # Explicit path takes priority — no need to enumerate backups
    if backup_path is not None:
        bp = Path(backup_path)
        if not bp.exists():
            raise FileNotFoundError(f"Backup not found: {bp}")
        shutil.copy2(str(bp), str(src))
        return str(bp)

    # Otherwise, look up from available backups
    backups = list_backups(filepath)

    if not backups:
        raise FileNotFoundError(
            f"No backups found for {src.name}"
        )

    if index is not None:
        if index < 1 or index > len(backups):
            raise ValueError(
                f"Backup index {index} out of range "
                f"(1-{len(backups)} available)"
            )
        _, bp, _ = backups[index - 1]
    else:
        # Most recent
        _, bp, _ = backups[0]

    shutil.copy2(str(bp), str(src))
    return str(bp)
