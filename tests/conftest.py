"""Shared test fixtures and cached PRS parsing for speed.

Session-scoped fixtures parse each test file ONCE and share the result
across all tests in the session.  Tests that only READ from the PRS
should use these directly.  Tests that MODIFY the PRS should use the
function-scoped variants (paws_prs_copy, claude_prs_copy) which return
a deep copy.

The cached_parse_prs() function provides module-level caching for test
files that use parse_prs() directly — just replace:
    prs = parse_prs(SOME_PATH)
with:
    prs = cached_parse_prs(SOME_PATH)
"""

import pytest
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

TESTDATA = Path(__file__).parent / "testdata"


# ─── Module-level parse cache (for non-fixture usage) ─────────────

@lru_cache(maxsize=32)
def _parse_prs_cached(path):
    """Internal: parse and cache a PRS file by path."""
    from quickprs.prs_parser import parse_prs
    return parse_prs(str(path))


def cached_parse_prs(path):
    """Parse a PRS file, caching the parse but returning a fresh deep copy.

    Each call returns an independent copy that can be freely mutated
    without affecting other tests.  The expensive binary parse is done
    only once per unique path.
    """
    return deepcopy(_parse_prs_cached(path))


# ─── Session-scoped fixtures (read-only, shared) ──────────────────

@pytest.fixture(scope="session")
def paws_prs():
    """Cached parse of PAWSOVERMAWS.PRS (session-scoped, read-only)."""
    prs_path = TESTDATA / "PAWSOVERMAWS.PRS"
    if not prs_path.exists():
        pytest.skip("PAWSOVERMAWS.PRS not available")
    from quickprs.prs_parser import parse_prs
    return parse_prs(str(prs_path))


@pytest.fixture(scope="session")
def claude_prs():
    """Cached parse of claude test.PRS (session-scoped, read-only)."""
    prs_path = TESTDATA / "claude test.PRS"
    if not prs_path.exists():
        pytest.skip("claude test.PRS not available")
    from quickprs.prs_parser import parse_prs
    return parse_prs(str(prs_path))


@pytest.fixture(scope="session")
def blank_prs():
    """Cached blank PRS (session-scoped, read-only)."""
    from quickprs.builder import create_blank_prs
    return create_blank_prs()


# ─── Function-scoped fixtures (deep copy for mutation) ────────────

@pytest.fixture
def paws_prs_copy(paws_prs):
    """Fresh deep copy of PAWSOVERMAWS.PRS for tests that modify it."""
    return deepcopy(paws_prs)


@pytest.fixture
def claude_prs_copy(claude_prs):
    """Fresh deep copy of claude test.PRS for tests that modify it."""
    return deepcopy(claude_prs)


@pytest.fixture
def blank_prs_copy(blank_prs):
    """Fresh deep copy of blank PRS for tests that modify it."""
    from quickprs.builder import create_blank_prs
    return create_blank_prs()
