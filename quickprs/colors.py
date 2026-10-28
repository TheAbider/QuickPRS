"""ANSI color support for terminal output.

Provides colored text helpers that auto-detect TTY capability.
Colors are disabled when output is piped or redirected, when the
--no-color flag is active or NO_COLOR is set, and in a Windows console
that cannot show them.
"""

import os
import sys

# Global flag — set True by --no-color CLI flag
_no_color = False

# Whether this Windows console shows ANSI codes (None until checked)
_windows_vt = None

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def disable_color():
    """Disable all color output (called by --no-color flag)."""
    global _no_color
    _no_color = True


def _kernel32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _enable_windows_vt():
    """Turn on ANSI code handling in this Windows console.

    A Windows console prints escape codes as text unless the program
    turns this on (Windows 10 and later). Returns False when it cannot.
    """
    global _windows_vt
    if _windows_vt is None:
        _windows_vt = False
        try:
            import ctypes
            from ctypes import wintypes
            k32 = _kernel32()
            k32.GetStdHandle.restype = wintypes.HANDLE
            handle = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = wintypes.DWORD()
            if k32.GetConsoleMode(handle, ctypes.pointer(mode)):
                vt = ENABLE_VIRTUAL_TERMINAL_PROCESSING
                _windows_vt = bool(mode.value & vt) or bool(
                    k32.SetConsoleMode(handle, mode.value | vt))
        except (AttributeError, OSError):
            pass
    return _windows_vt


def supports_color():
    """Check if stdout supports ANSI color codes."""
    if _no_color or os.environ.get("NO_COLOR"):
        return False
    if not (hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()):
        return False
    if sys.platform == "win32":
        return _enable_windows_vt()
    return True


def _code(ansi):
    """Return ANSI code if color is supported, empty string otherwise."""
    return ansi if supports_color() else ''


# Color codes (evaluated lazily via functions to respect runtime state)
def _red():
    return _code('\033[91m')


def _green():
    return _code('\033[92m')


def _yellow():
    return _code('\033[93m')


def _cyan():
    return _code('\033[96m')


def _bold():
    return _code('\033[1m')


def _dim():
    return _code('\033[2m')


def _reset():
    return _code('\033[0m')


def red(text):
    """Wrap text in red."""
    return f"{_red()}{text}{_reset()}"


def green(text):
    """Wrap text in green."""
    return f"{_green()}{text}{_reset()}"


def yellow(text):
    """Wrap text in yellow."""
    return f"{_yellow()}{text}{_reset()}"


def cyan(text):
    """Wrap text in cyan."""
    return f"{_cyan()}{text}{_reset()}"


def bold(text):
    """Wrap text in bold."""
    return f"{_bold()}{text}{_reset()}"


def dim(text):
    """Wrap text in dim."""
    return f"{_dim()}{text}{_reset()}"


def error_label(text="ERROR"):
    """Format an error label."""
    return red(f"[{text}]")


def warn_label(text="WARN"):
    """Format a warning label."""
    return yellow(f"[{text}]")


def info_label(text="INFO"):
    """Format an info label."""
    return cyan(f"[{text}]")


def ok_label(text="PASS"):
    """Format a success label."""
    return green(f"[{text}]")
