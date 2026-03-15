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
        "--hidden-import", "quickprs",
        "--hidden-import", "quickprs.gui",
        "--hidden-import", "quickprs.gui.app",
        "--hidden-import", "quickprs.gui.personality_view",
        "--hidden-import", "quickprs.gui.import_panel",
        "--hidden-import", "quickprs.gui.settings",
        "--hidden-import", "quickprs.gui.button_config",
        "--hidden-import", "quickprs.gui.diff_viewer",
        "--hidden-import", "quickprs.gui.hex_viewer",
        "--hidden-import", "quickprs.gui.system_wizard",
        "--hidden-import", "quickprs.prs_parser",
        "--hidden-import", "quickprs.prs_writer",
        "--hidden-import", "quickprs.record_types",
        "--hidden-import", "quickprs.binary_io",
        "--hidden-import", "quickprs.injector",
        "--hidden-import", "quickprs.radioreference",
        "--hidden-import", "quickprs.validation",
        "--hidden-import", "quickprs.comparison",
        "--hidden-import", "quickprs.cli",
        "--hidden-import", "quickprs.csv_import",
        "--hidden-import", "quickprs.csv_export",
        "--hidden-import", "quickprs.logger",
        "--hidden-import", "quickprs.cache",
        "--hidden-import", "quickprs.builder",
        "--hidden-import", "quickprs.json_io",
        "--hidden-import", "quickprs.templates",
        "--hidden-import", "quickprs.config_builder",
        "--hidden-import", "quickprs.iden_library",
        "--hidden-import", "quickprs.option_maps",
        "--hidden-import", "quickprs.option_differ",
        "--hidden-import", "quickprs.main",
        "--hidden-import", "quickprs.fleet",
        "--hidden-import", "quickprs.repair",
        "--hidden-import", "quickprs.undo",
        "--hidden-import", "quickprs.scanner_import",
        "--hidden-import", "quickprs.freq_tools",
        "--hidden-import", "quickprs.auto_setup",
        "--hidden-import", "quickprs.completions",
        "--hidden-import", "quickprs.system_database",
        "--hidden-import", "quickprs.zones",
        "--hidden-import", "quickprs.export_formats",
        "--hidden-import", "quickprs.reports",
        "--hidden-import", "quickprs.backup",
        "--hidden-import", "quickprs.cleanup",
        "--hidden-import", "quickprs.cloner",
        "--hidden-import", "quickprs.diff_report",
        "--hidden-import", "quickprs.profile_templates",
        "--hidden-import", "quickprs.search",
        "--hidden-import", "quickprs.wizard",
        "--hidden-import", "quickprs.gui.import_wizard",
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
