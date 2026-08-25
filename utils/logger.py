"""Logging configuration and Qt-friendly log viewer for the suite.

This module exposes :func:`get_logger`, a process-wide logger factory that
attaches:

* a :class:`logging.handlers.RotatingFileHandler` writing to ``logs/ars.log``
* a :class:`logging.StreamHandler` for console output

Log format::

    %(asctime)s [%(levelname)s] %(name)s: %(message)s

It also exposes :class:`LogViewer` — a Qt widget (subclass of
``QPlainTextEdit``) that buffers the last 10 000 log lines and exposes an
:py:meth:`append_line` method. If ``qtpy`` (and thus PyQt5/PySide2) is not
installed, :class:`LogViewer` degrades to a pure-Python ring buffer so the
module remains independently importable.

Example:
    >>> from utils.logger import get_logger, LogViewer
    >>> log = get_logger("demo")
    >>> log.info("hello world")
    >>> viewer = LogViewer()           # Qt widget if available, else stub
    >>> viewer.append_line("captured line")
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Qt shim — qtpy abstracts PyQt5 / PySide2. Fall back to a stub object if Qt
# is unavailable so the module remains importable in headless environments.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    from qtpy.QtCore import QObject, Signal
    from qtpy.QtWidgets import QPlainTextEdit

    _HAS_QT = True
    _QtTextBase = QPlainTextEdit  # type: ignore[misc, valid-type]
    _QtObjectBase = QObject  # type: ignore[misc, valid-type]
except Exception:  # pragma: no cover - depends on environment
    _HAS_QT = False

    class _QtTextBase:  # type: ignore[no-redef]
        """Stub used when Qt is unavailable — keeps the module importable."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _QtObjectBase:  # type: ignore[no-redef]
        """Stub used when Qt is unavailable."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Resolve log directory relative to project root (parent of utils/).
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_LOG_DIR: Path = _PROJECT_ROOT / "logs"
_LOG_FILE: Path = _LOG_DIR / "ars.log"

_LOCK = threading.Lock()
_CONFIGURED_ROOTS: set = set()

_MAX_VIEWER_LINES = 10_000


# ---------------------------------------------------------------------------
# Qt log handler — emits a signal per record (used by LogViewer)
# ---------------------------------------------------------------------------
class QtLogHandler(logging.Handler, _QtObjectBase):  # type: ignore[misc]
    """Logging handler that re-emits each record as a Qt signal.

    The signal carries the formatted log line so any Qt slot can subscribe.
    """

    log_emitted = None

    def __init__(self, level: int = logging.NOTSET) -> None:
        """Initialize both bases and define the signal if Qt is available."""
        logging.Handler.__init__(self, level=level)
        _QtObjectBase.__init__(self)
        if _HAS_QT:
            # ``Signal`` must be defined at class scope; we attach an instance
            # proxy that delegates to a freshly created signal-like callable.
            self._emit = _create_signal(str)  # type: ignore[arg-type]
        else:
            self._emit = None

    def emit(self, record: logging.LogRecord) -> None:
        """Format ``record`` and broadcast it via the Qt signal."""
        try:
            msg = self.format(record)
        except Exception:  # pragma: no cover - defensive
            msg = record.getMessage()
        if self._emit is not None:
            try:
                self._emit.emit(msg)
            except Exception:  # pragma: no cover - Qt not on main thread
                pass


def _create_signal(*args: object) -> object:
    """Helper that constructs a Qt ``Signal`` proxy on demand.

    Args:
        *args: Signal type arguments (e.g. ``(str,)``).

    Returns:
        A Signal-like object exposing an ``emit`` callable.
    """
    if not _HAS_QT:
        return _NullSignal()
    return _SignalProxy(args)


class _NullSignal:  # pragma: no cover - only used when Qt missing
    """No-op signal replacement for headless environments."""

    def emit(self, *args: object, **kwargs: object) -> None:
        return None

    def connect(self, *args: object, **kwargs: object) -> None:
        return None


class _SignalProxy:
    """Lazily binds a Qt ``Signal`` to a QObject instance.

    Qt's ``Signal`` must be defined as a class attribute, not an instance
    attribute. To allow ``QtLogHandler`` to expose a per-instance signal we
    create a tiny QObject subclass on the fly.
    """

    def __init__(self, types: tuple) -> None:
        self._types = types
        self._impl: Optional[QObject] = None

    def emit(self, *args: object) -> None:
        if self._impl is None:
            self._build()
        if self._impl is not None:
            self._impl.log_emitted.emit(*args)

    def connect(self, slot: object) -> None:
        if self._impl is None:
            self._build()
        if self._impl is not None:
            self._impl.log_emitted.connect(slot)

    def _build(self) -> None:
        if not _HAS_QT:
            return

        class _Emitter(QObject):  # type: ignore[misc]
            log_emitted = Signal(object)  # type: ignore[arg-type]

        self._impl = _Emitter()


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------
def _ensure_handlers(logger: logging.Logger) -> None:
    """Attach file + console handlers to ``logger`` exactly once."""
    if logger.name in _CONFIGURED_ROOTS and logger.handlers:
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - defensive
        # Fall back to a logs/ dir in cwd if the project path is read-only.
        fallback = Path.cwd() / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        logger.debug("Could not create %s, falling back to %s (%s)", _LOG_DIR, fallback, exc)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    try:
        file_handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not attach file handler at %s: %s", _LOG_FILE, exc)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    logger.setLevel(logging.DEBUG)  # per-handler levels filter the noise
    logger.propagate = False
    _CONFIGURED_ROOTS.add(logger.name)


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """Return a configured :class:`logging.Logger` with file + console handlers.

    The logger is cached by name; calling this repeatedly with the same name
    returns the same instance without piling on duplicate handlers.

    Args:
        name: Logger name (typically ``__name__``).
        level: Optional level override (e.g. ``logging.DEBUG``).

    Returns:
        A configured :class:`logging.Logger`.
    """
    logger = logging.getLogger(name)
    with _LOCK:
        _ensure_handlers(logger)
        if level is not None:
            logger.setLevel(level)
    return logger


# ---------------------------------------------------------------------------
# LogViewer — Qt widget that buffers the last N lines
# ---------------------------------------------------------------------------
class LogViewer(_QtTextBase):  # type: ignore[misc]
    """A Qt widget that streams log lines, keeping the last 10 000 in buffer.

    When PyQt5/PySide2 (via qtpy) is available, :class:`LogViewer` subclasses
    :class:`qtpy.QtWidgets.QPlainTextEdit` and appends lines to both the Qt
    document and the in-memory ring buffer. When Qt is unavailable, the Qt
    base is a no-op stub and only the buffer is maintained.

    Attributes:
        max_lines: Maximum number of lines kept in the buffer.
    """

    def __init__(self, max_lines: int = _MAX_VIEWER_LINES, *args: object, **kwargs: object) -> None:
        """Initialize the viewer.

        Args:
            max_lines: Maximum number of lines to retain.
            *args: Forwarded to the Qt base class.
            **kwargs: Forwarded to the Qt base class.
        """
        try:
            super().__init__(*args, **kwargs)  # type: ignore[call-arg]
        except TypeError:
            # Stubs accept any kwargs.
            super().__init__()
        self.max_lines: int = max_lines
        self._buffer: List[str] = []
        self._lock = threading.Lock()
        self._handler: Optional[logging.Handler] = None

        if _HAS_QT:
            try:
                self.setReadOnly(True)  # type: ignore[attr-defined]
                self.setMaximumBlockCount(max_lines)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------ public
    def append_line(self, line: str) -> None:
        """Append a single line to the viewer.

        Args:
            line: The log line to display.
        """
        with self._lock:
            self._buffer.append(line)
            if len(self._buffer) > self.max_lines:
                # Trim oldest entries to stay within the cap.
                overflow = len(self._buffer) - self.max_lines
                self._buffer = self._buffer[overflow:]
        if _HAS_QT:
            try:
                self.appendPlainText(line)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive
                pass

    def lines(self) -> List[str]:
        """Return a snapshot copy of the current buffer."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:  # type: ignore[override]
        """Clear both the buffer and (if available) the Qt document."""
        with self._lock:
            self._buffer = []
        if _HAS_QT:
            try:
                super().clear()  # type: ignore[misc]
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------ bridge
    def attach_to_logger(self, logger: logging.Logger, level: int = logging.INFO) -> QtLogHandler:
        """Attach a :class:`QtLogHandler` for ``logger`` that pipes to this viewer.

        Args:
            logger: The logger to subscribe to.
            level: Minimum level to forward.

        Returns:
            The installed handler (call ``logger.removeHandler(h)`` to detach).
        """
        handler = QtLogHandler(level=level)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        if _HAS_QT:
            try:
                handler._emit.connect(self.append_line)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive
                # Fall back to a lambda — at least the buffer still updates.
                handler._emit = _NullSignal()  # type: ignore[assignment]
        logger.addHandler(handler)
        self._handler = handler
        return handler


__all__ = ["get_logger", "LogViewer", "QtLogHandler"]
