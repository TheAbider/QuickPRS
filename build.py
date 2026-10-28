"""Build QuickPRS standalone executable using PyInstaller.

Usage:
    python build.py

Requires:
    pip install pyinstaller

Output:
    dist/QuickPRS.exe  (single-file executable)
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def get_version():
    """Read version from quickprs/__init__.py."""
    init = ROOT / "quickprs" / "__init__.py"
    for line in init.read_text().splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    return "0.0.0"


def build():
    version = get_version()

    # Windows uses ';' as path separator for --add-data, Unix uses ':'
    sep = ';' if os.name == 'nt' else ':'

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "QuickPRS",
        "--add-data", f"{ROOT / 'quickprs'}{sep}quickprs",
        # Every quickprs module, so new ones need no list to keep
        "--collect-submodules", "quickprs",
        # pyserial for `quickprs radio`
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools.list_ports",
        # Optional packages that would otherwise come along when installed:
        # bleak (BLE scans) brings the WinRT runtime, and httpx (zeep's
        # async transport, unused) brings rich, pygments, Pillow and numpy
        "--exclude-module", "bleak",
        "--exclude-module", "httpx",
        "--hidden-import", "windnd",
        "--hidden-import", "sv_ttk",
        "--hidden-import", "darkdetect",
        str(ROOT / "run.py"),
    ]

    print(f"Building QuickPRS v{version}...")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        exe = ROOT / "dist" / "QuickPRS.exe"
        if exe.exists():
            size_mb = exe.stat().st_size / 1024 / 1024
            print(f"\nBuild successful: {exe}")
            print(f"Version: {version}")
            print(f"Size: {size_mb:.1f} MB")
        else:
            print("\nBuild completed but exe not found at expected path.")
    else:
        print(f"\nBuild failed with return code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    build()
