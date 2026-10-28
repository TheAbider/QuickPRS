"""Build QuickPRS standalone executables using PyInstaller.

Usage:
    python build.py [extra PyInstaller options, e.g. --workpath DIR]

Requires:
    pip install pyinstaller

Output:
    dist/QuickPRS.exe      GUI (windowed, no console)
    dist/QuickPRS-cli.exe  command line (console)
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# (name, windowed). A console does not wait for a windowed program or show
# its output, so the command line needs its own console build.
EXECUTABLES = (
    ("QuickPRS", True),
    ("QuickPRS-cli", False),
)


def get_version():
    """Read version from quickprs/__init__.py."""
    init = ROOT / "quickprs" / "__init__.py"
    for line in init.read_text().splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    return "0.0.0"


def pyinstaller_cmd(name, windowed, extra=()):
    """The PyInstaller command line for one executable."""
    # Windows uses ';' as path separator for --add-data, Unix uses ':'
    sep = ';' if os.name == 'nt' else ':'

    return [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed" if windowed else "--console",
        "--name", name,
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
        *extra,
        str(ROOT / "run.py"),
    ]


def _dist_dir(extra):
    """Where PyInstaller puts the executables (--distpath or dist/)."""
    extra = list(extra)
    for i, arg in enumerate(extra):
        if arg == "--distpath" and i + 1 < len(extra):
            return Path(extra[i + 1])
        if arg.startswith("--distpath="):
            return Path(arg.split("=", 1)[1])
    return ROOT / "dist"


def build(extra=()):
    version = get_version()
    print(f"Building QuickPRS v{version}...")

    for name, windowed in EXECUTABLES:
        cmd = pyinstaller_cmd(name, windowed, extra)
        print(f"Command: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(ROOT))
        if result.returncode != 0:
            print(f"\nBuild of {name} failed with return code "
                  f"{result.returncode}")
            sys.exit(1)

    print(f"\nVersion: {version}")
    for name, _ in EXECUTABLES:
        exe = _dist_dir(extra) / f"{name}.exe"
        if exe.exists():
            size_mb = exe.stat().st_size / 1024 / 1024
            print(f"Built: {exe} ({size_mb:.1f} MB)")
        else:
            print(f"Build completed but {exe} was not found.")


if __name__ == "__main__":
    build(sys.argv[1:])
