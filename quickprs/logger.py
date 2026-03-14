"""Application logging for QuickPRS.

Logs user actions and internal operations to:
  ~/.quickprs/logs/quickprs.log

Rotates at 5 MB, keeps 5 backup files.
"""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


_logger = None


def get_logger():
    """Get or create the application logger."""
    global _logger
    if _logger is not None:
        return _logger

    log_dir = Path.home() / '.quickprs' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'quickprs.log'

    _logger = logging.getLogger('quickprs')
    _logger.setLevel(logging.DEBUG)

    # File handler — detailed debug log
    fh = RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=5, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)-5s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'))
    _logger.addHandler(fh)

    # Console handler — INFO+ only
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    _logger.addHandler(ch)

    _logger.info("QuickPRS logger initialized")
    _logger.info(f"Log file: {log_file}")
    return _logger


def log_action(action, **details):
    """Log a user action with optional detail fields.

    Usage:
        log_action("file_open", path="C:/foo.PRS", size=46822)
        log_action("inject", talkgroups=190, frequencies=129, set_name="CRIS")
    """
    logger = get_logger()
    parts = [action]
    for k, v in details.items():
        parts.append(f"{k}={v}")
    logger.info(" | ".join(parts))


def log_error(action, error, **details):
    """Log an error with context."""
    logger = get_logger()
    parts = [action, f"error={error}"]
    for k, v in details.items():
        parts.append(f"{k}={v}")
    logger.error(" | ".join(parts))
