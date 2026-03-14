"""Tests for the main module (quickprs.main).

Smoke tests for the entry point module — import and basic structure.
"""

import importlib


def test_main_module_importable():
    """The main module should be importable without error."""
    mod = importlib.import_module("quickprs.main")
    assert mod is not None


def test_main_module_has_main_function():
    """The main module should re-export the GUI main function."""
    from quickprs.main import main
    assert callable(main)
