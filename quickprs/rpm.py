"""Harris RPM (Radio Personality Manager) on this PC.

QuickPRS cannot write a personality to a radio by itself yet; RPM does.
These helpers find RPM and hand it a personality file, so a file edited in
QuickPRS goes straight to RPM, ready to write to the radio.
"""

import os
from pathlib import Path
import re
import subprocess

RPM_EXE = "RadPersMgr.exe"
INSTALL_DIR = "Harris Radio Personality Manager"


def exe_from_command(command):
    """The program in a Windows open command such as
    '"C:\\...\\RadPersMgr.exe" "%1"', or None."""
    command = (command or "").strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 1 else None
    m = re.match(r"(.+?\.exe)(?=\s|$)", command, re.IGNORECASE)
    return m.group(1) if m else None


def prs_open_command():
    """The command Windows opens .PRS files with, or None."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".prs") as key:
            prog_id = winreg.QueryValue(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            prog_id + r"\shell\open\command") as key:
            return winreg.QueryValue(key, None)
    except OSError:
        return None


def find_rpm(command=None, environ=None, exists=os.path.isfile):
    """The path of RPM's program, or None when it is not installed.

    The program Windows opens .PRS files with counts when it is RPM's;
    otherwise RPM's default install folders are tried."""
    if command is None:
        command = prs_open_command()
    exe = exe_from_command(command)
    if exe and Path(exe).name.lower() == RPM_EXE.lower() and exists(exe):
        return exe
    environ = os.environ if environ is None else environ
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = environ.get(var)
        if base:
            path = str(Path(base) / INSTALL_DIR / RPM_EXE)
            if exists(path):
                return path
    return None


def open_in_rpm(path, rpm, popen=subprocess.Popen):
    """Start RPM (``rpm``, from find_rpm) with the personality file
    ``path``, as opening the file from Explorer does."""
    path = Path(path).resolve()
    return popen([str(rpm), str(path)], cwd=str(path.parent))
