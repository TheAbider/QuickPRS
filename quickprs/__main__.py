"""Allow running as: python -m quickprs [subcommand ...]"""

import sys

from .cli import run_cli

exit_code = run_cli()
if exit_code is not None:
    sys.exit(exit_code)

# No CLI subcommand — launch GUI
from .gui.app import main
main()
