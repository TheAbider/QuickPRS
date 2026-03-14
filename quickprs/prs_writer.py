"""PRS file writer — reassembles sections back to binary.

For Sprint 1, this is trivial: concatenate all section raw bytes.
Guaranteed byte-identical roundtrip because we preserve raw bytes.
"""

from pathlib import Path
import shutil


def write_prs(prs_file, filepath, backup=True):
    """Write a PRSFile back to disk.

    Args:
        prs_file: PRSFile object with ordered sections
        filepath: output path
        backup: if True and file exists, create .bak backup first
    """
    path = Path(filepath)

    if backup and path.exists():
        bak = path.with_suffix(path.suffix + '.bak')
        shutil.copy2(path, bak)

    data = prs_file.to_bytes()
    path.write_bytes(data)
    return len(data)
