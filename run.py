"""QuickPRS launcher — entry point for both development and PyInstaller.

Usage:
    python run.py                         Launch GUI
    python run.py file.PRS                Launch GUI with file
    python run.py info file.PRS           Print personality summary
    python run.py validate file.PRS       Validate PRS file
    python run.py export-csv file.PRS dir Export to CSV
    python run.py compare a.PRS b.PRS    Compare two files
    python run.py dump file.PRS [-s N]   Dump section info
"""

import sys
from pathlib import Path


def _gui_target(argv):
    """(True, file or None) when the arguments ask for the GUI.

    No arguments, or a personality file, opens the GUI; anything else is a
    CLI command (argparse reports unknown ones), so new commands never
    need to be listed here.
    """
    if len(argv) < 2:
        return True, None
    arg = argv[1]
    if arg.startswith("-"):
        return False, None
    path = Path(arg)
    if path.suffix.lower() == ".prs" or path.is_file():
        return True, arg
    return False, None


def main():
    gui, filepath = _gui_target(sys.argv)
    if not gui:
        from quickprs.cli import run_cli
        result = run_cli()
        sys.exit(result if result is not None else 0)

    from quickprs.gui.app import main as gui_main
    gui_main(filepath=filepath)


if __name__ == "__main__":
    main()
