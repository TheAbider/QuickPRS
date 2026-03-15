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


def main():
    # Check if any CLI subcommand is being used
    # CLI subcommands: info, validate, export-csv, compare, --version
    cli_commands = {"info", "validate", "export-csv", "compare", "dump",
                    "rename", "sort", "freq-tools"}
    cli_flags = {"--version", "-V"}

    has_cli = (len(sys.argv) > 1 and
               (sys.argv[1] in cli_commands or sys.argv[1] in cli_flags))

    if has_cli:
        from quickprs.cli import run_cli
        result = run_cli()
        sys.exit(result if result is not None else 0)
    else:
        # GUI mode — pass first arg as filepath if it looks like a file
        filepath = None
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            filepath = sys.argv[1]

        from quickprs.gui.app import main as gui_main
        gui_main(filepath=filepath)


if __name__ == "__main__":
    main()
