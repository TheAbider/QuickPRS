"""Allow running as: python -m quickprs [subcommand ...]"""

import sys

from .cli import run_cli

exit_code = run_cli()
if exit_code is not None:
    sys.exit(exit_code)

# No CLI subcommand — try GUI, fall back to wizard if no display
try:
    from .gui.app import main
    main()
except Exception:
    # GUI unavailable (no display, no tkinter, etc.) — offer wizard
    print("GUI not available. Use 'quickprs wizard' for interactive mode,")
    print("or run 'quickprs --help' for CLI commands.")
    sys.exit(1)
