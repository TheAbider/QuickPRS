"""Tests for the logger module."""

import logging
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from quickprs import logger as logger_mod


def _close_and_reset():
    """Close all handlers and reset the logger singleton."""
    qp_logger = logging.getLogger('quickprs')
    for h in qp_logger.handlers[:]:
        h.close()
        qp_logger.removeHandler(h)
    logger_mod._logger = None


@pytest.fixture(autouse=True)
def reset_logger():
    """Reset the logger singleton between tests."""
    _close_and_reset()
    yield
    _close_and_reset()


@pytest.fixture
def log_dir():
    """Provide a temp directory for log files, closing handlers before cleanup."""
    d = tempfile.mkdtemp()
    yield Path(d)
    _close_and_reset()
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestGetLogger:

    def test_returns_logger(self, log_dir):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            result = logger_mod.get_logger()
        assert isinstance(result, logging.Logger)
        assert result.name == 'quickprs'

    def test_singleton(self, log_dir):
        """get_logger should return the same instance on repeated calls."""
        with mock.patch.object(Path, 'home', return_value=log_dir):
            first = logger_mod.get_logger()
            second = logger_mod.get_logger()
        assert first is second

    def test_creates_log_directory(self, log_dir):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            logger_mod.get_logger()
        assert (log_dir / '.quickprs' / 'logs').is_dir()

    def test_has_file_handler(self, log_dir):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            result = logger_mod.get_logger()
        file_handlers = [h for h in result.handlers
                         if hasattr(h, 'baseFilename')]
        assert len(file_handlers) >= 1

    def test_has_stream_handler(self, log_dir):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            result = logger_mod.get_logger()
        stream_handlers = [h for h in result.handlers
                           if isinstance(h, logging.StreamHandler)
                           and not hasattr(h, 'baseFilename')]
        assert len(stream_handlers) >= 1

    def test_debug_level(self, log_dir):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            result = logger_mod.get_logger()
        assert result.level == logging.DEBUG


class TestLogAction:

    def test_log_action_basic(self, log_dir, caplog):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            with caplog.at_level(logging.INFO, logger='quickprs'):
                logger_mod.log_action("file_open", path="test.PRS")
        assert "file_open" in caplog.text
        assert "path=test.PRS" in caplog.text

    def test_log_action_no_details(self, log_dir, caplog):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            with caplog.at_level(logging.INFO, logger='quickprs'):
                logger_mod.log_action("simple_action")
        assert "simple_action" in caplog.text

    def test_log_action_multiple_details(self, log_dir, caplog):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            with caplog.at_level(logging.INFO, logger='quickprs'):
                logger_mod.log_action("inject", tgs=190, freqs=129)
        assert "tgs=190" in caplog.text
        assert "freqs=129" in caplog.text


class TestLogError:

    def test_log_error_basic(self, log_dir, caplog):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            with caplog.at_level(logging.ERROR, logger='quickprs'):
                logger_mod.log_error("parse_fail", "bad format")
        assert "parse_fail" in caplog.text
        assert "error=bad format" in caplog.text

    def test_log_error_with_details(self, log_dir, caplog):
        with mock.patch.object(Path, 'home', return_value=log_dir):
            with caplog.at_level(logging.ERROR, logger='quickprs'):
                logger_mod.log_error("io_fail", "denied",
                                      path="/foo.PRS")
        assert "path=/foo.PRS" in caplog.text
