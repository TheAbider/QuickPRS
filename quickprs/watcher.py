"""File watcher — monitor a PRS file for changes and auto-validate.

Usage:
    quickprs watch radio.PRS [--interval 2]

Polls the file's modification time. When it changes, the file is parsed
and validated, with results printed immediately. Useful when editing
with RPM — save in RPM and QuickPRS shows validation results.
"""

import time
from pathlib import Path


def watch_file(filepath, interval=2.0, callback=None):
    """Watch a PRS file for changes and run validation on each change.

    Args:
        filepath: PRS file to watch
        interval: check interval in seconds
        callback: optional function(prs, issues) called on each change

    Polls the file's modification time. When it changes:
    1. Parse the file
    2. Run validate_prs + validate_structure
    3. Print results
    4. Call callback if provided
    """
    path = Path(filepath)
    if not path.exists():
        print(f"Error: {filepath} not found")
        return

    last_mtime = path.stat().st_mtime
    last_size = path.stat().st_size
    print(f"Watching {filepath} (Ctrl+C to stop)")
    print(f"  Current size: {last_size:,} bytes")
    print()

    try:
        while True:
            time.sleep(interval)
            try:
                current_mtime = path.stat().st_mtime
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    current_size = path.stat().st_size
                    print(f"[{time.strftime('%H:%M:%S')}] File changed"
                          f" ({current_size:,} bytes)")

                    # Parse and validate
                    from .prs_parser import parse_prs
                    from .validation import (
                        validate_prs, validate_structure, ERROR, WARNING,
                    )

                    try:
                        prs = parse_prs(str(path))
                        issues = validate_prs(prs)
                        issues.extend(validate_structure(prs))
                        errors = [m for s, m in issues if s == ERROR]
                        warnings = [m for s, m in issues if s == WARNING]

                        if errors:
                            print(f"  ERRORS ({len(errors)}):")
                            for msg in errors[:5]:
                                print(f"    [!] {msg}")
                            if len(errors) > 5:
                                print(f"    ... and {len(errors) - 5} more")
                        if warnings:
                            print(f"  Warnings ({len(warnings)}):")
                            for msg in warnings[:3]:
                                print(f"    [~] {msg}")
                            if len(warnings) > 3:
                                print(f"    ... and {len(warnings) - 3} more")
                        if not errors:
                            print(f"  OK ({len(prs.sections)} sections,"
                                  f" {len(warnings)} warnings)")

                        if callback:
                            callback(prs, issues)
                    except Exception as e:
                        print(f"  Parse error: {e}")

                    print()
                    last_size = current_size
            except FileNotFoundError:
                print(f"[{time.strftime('%H:%M:%S')}] File deleted!")
                break
    except KeyboardInterrupt:
        print("\nStopped watching.")


def validate_once(filepath):
    """Parse and validate a single PRS file, returning (prs, issues).

    This is the core logic used by the watcher on each file change,
    extracted for testability.

    Args:
        filepath: PRS file path

    Returns:
        tuple of (prs, issues) where issues is a list of (severity, message)

    Raises:
        FileNotFoundError: if file doesn't exist
        ValueError: if file can't be parsed
    """
    from .prs_parser import parse_prs
    from .validation import validate_prs, validate_structure

    prs = parse_prs(str(filepath))
    issues = validate_prs(prs)
    issues.extend(validate_structure(prs))
    return prs, issues
