"""Qt-friendly background worker primitives.

This module provides three building blocks for offloading CPU-bound or
I/O-bound work off the GUI thread:

* :class:`WorkerSignals` — a ``QObject`` that exposes ``started``,
  ``finished``, ``progress(int, str)``, ``error(str)`` and ``result(object)``
  signals.
* :class:`Worker` — a ``QRunnable`` that wraps any callable and its args,
  emitting the signals above as it runs.
* :class:`WorkerPool` — a singleton wrapper around ``QThreadPool.globalInstance()``
  exposing :py:meth:`submit` and :py:meth:`wait_all`.

A convenience function :func:`run_in_background` ties them together for the
common one-shot case.

If ``qtpy`` (and thus PyQt5/PySide2) is unavailable, the module still imports
— the Qt-backed classes fall back to no-op stubs so headless environments can
use the same call sites without crashing on import.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import inspect
import logging
import threading
import traceback
from typing import Any, Callable, Optional, Union

PROGRESS_CALLBACK_PARAMS = ("progress_callback", "progress")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Qt shim
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    from qtpy.QtCore import QObject, QRunnable, Signal
    from qtpy.QtCore import QThreadPool

    _HAS_QT = True
    _QObjectBase = QObject  # type: ignore[misc, valid-type]
    _QRunnableBase = QRunnable  # type: ignore[misc, valid-type]
except Exception:  # pragma: no cover - depends on environment
    _HAS_QT = False

    class _QObjectBase:  # type: ignore[no-redef]
        """Stub QObject replacement used when Qt is missing."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _QRunnableBase:  # type: ignore[no-redef]
        """Stub QRunnable replacement used when Qt is missing."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def setAutoDelete(self, value: bool) -> None:  # noqa: N802 - Qt API
            self._auto_delete = value

        def autoDelete(self) -> bool:  # noqa: N802 - Qt API
            return getattr(self, "_auto_delete", True)


# ---------------------------------------------------------------------------
# Signal helpers when Qt is unavailable
# ---------------------------------------------------------------------------
class _StubSignal:
    """A no-op replacement for ``qtpy.QtCore.Signal``."""

    def __init__(self, *types: object) -> None:
        self._types = types

    def emit(self, *args: object, **kwargs: object) -> None:
        return None

    def connect(self, slot: Callable[..., Any]) -> Callable[..., Any]:
        return slot


def _signal(*types: object) -> Any:
    """Return a real Qt ``Signal`` or a stub depending on availability."""
    if _HAS_QT:
        return Signal(*types)  # type: ignore[no-redef]
    return _StubSignal(*types)


def accepts_progress_callback(
    fn: Callable[..., Any],
    *names: str,
) -> bool:
    """Return ``True`` if ``fn`` can accept a progress-callback keyword.

    This is the SIGNATURE-AWARE check used by :class:`Worker` (and reusable
    by :mod:`core.task_queue` / :mod:`core.orchestrator`) before injecting a
    ``progress_callback`` keyword argument. A callable "accepts" it when
    its signature declares a parameter named ``progress_callback`` (or one
    of the extra ``names``) as a normal or keyword-only parameter, or when
    it accepts ``**kwargs``.

    Builtins and C extensions without introspectable signatures return
    ``False`` (never inject — injection would raise ``TypeError``).

    Args:
        fn: The callable to inspect.
        *names: Additional parameter names to accept (defaults to
            ``progress_callback`` and ``progress``).

    Returns:
        ``True`` only when injection is safe.
    """
    names = names or PROGRESS_CALLBACK_PARAMS
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - C builtins
        return False
    for name, param in sig.parameters.items():
        if name in names and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return False


# ---------------------------------------------------------------------------
# WorkerSignals
# ---------------------------------------------------------------------------
class WorkerSignals(_QObjectBase):  # type: ignore[misc]
    """Defines the signals emitted by a :class:`Worker` during its lifecycle.

    Attributes (signals):
        started: Emitted before ``fn`` is called.
        finished: Emitted after ``fn`` returns (success or failure).
        progress: ``(int, str)`` progress percent and message.
        error: ``str`` traceback / message when ``fn`` raises.
        result: The return value of ``fn`` (any object).
    """

    started: Any = _signal()
    finished: Any = _signal()
    progress: Any = _signal(int, str)
    error: Any = _signal(str)
    result: Any = _signal(object)

    def __init__(self) -> None:
        super().__init__()
        if not _HAS_QT:
            # Per-instance stub signals so separate WorkerSignals objects
            # never share connection state (class-level stubs would be
            # shared across every instance when Qt is absent).
            self.started = _signal()
            self.finished = _signal()
            self.progress = _signal(int, str)
            self.error = _signal(str)
            self.result = _signal(object)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class Worker(_QRunnableBase):  # type: ignore[misc]
    """Generic background worker that runs any callable.

    The wrapped callable may accept an optional ``progress_callback`` keyword
    argument; if it does, the worker will inject a callable that emits the
    ``progress`` signal with ``(percent: int, message: str)``.

    Example:
        >>> def long_task(progress_callback=None):
        ...     for i in range(10):
        ...         progress_callback(i * 10, f"step {i}")
        ...     return "done"
        >>> worker = Worker(long_task)
        >>> worker.signals.result.connect(lambda r: print("result:", r))
        >>> WorkerPool.instance().submit(worker)

    CONTRACT (see worklog "PATCH CONTRACTS" #1):

    * Signals live on ``worker.signals`` (``result`` / ``error`` /
      ``progress`` / ``finished`` / ``started``). Convenience read-only
      properties on the worker itself forward to ``worker.signals`` so
      legacy call sites using ``worker.result.connect(...)`` keep working.
    * Run workers via ``WorkerPool.instance().submit(worker)`` (or the
      ``worker.start()`` convenience, which does exactly that). A plain
      ``QRunnable`` has no Qt ``start()``; this class provides one.
    * ``progress_callback`` is injected ONLY when the wrapped callable's
      signature accepts it (see :func:`accepts_progress_callback`) —
      zero-argument callables are invoked verbatim, never with an
      unexpected keyword.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the worker.

        Args:
            fn: The callable to execute in the background.
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``. ``progress_callback``
                is injected automatically unless explicitly provided.
        """
        super().__init__()
        self.fn: Callable[..., Any] = fn
        self.args: tuple = args
        self.kwargs: dict = kwargs
        self.signals: WorkerSignals = WorkerSignals()
        self._cancel_requested: bool = False

        # SIGNATURE-AWARE injection: only add the kwarg when ``fn`` can
        # actually accept it, otherwise zero-arg callables would raise
        # TypeError. An explicit ``progress_callback=`` passed by the caller
        # is always honoured and never overwritten.
        if (
            "progress_callback" not in self.kwargs
            and "progress" not in self.kwargs
            and accepts_progress_callback(fn)
        ):
            self.kwargs["progress_callback"] = self._emit_progress

    # ------------------------------------------------- convenience proxies
    @property
    def started(self) -> Any:
        """Forward to ``self.signals.started`` (legacy call-site shim)."""
        return self.signals.started

    @property
    def finished(self) -> Any:
        """Forward to ``self.signals.finished`` (legacy call-site shim)."""
        return self.signals.finished

    @property
    def progress(self) -> Any:
        """Forward to ``self.signals.progress`` (legacy call-site shim)."""
        return self.signals.progress

    @property
    def error(self) -> Any:
        """Forward to ``self.signals.error`` (legacy call-site shim)."""
        return self.signals.error

    @property
    def result(self) -> Any:
        """Forward to ``self.signals.result`` (legacy call-site shim)."""
        return self.signals.result

    # ------------------------------------------------------ lifecycle API
    def start(self) -> None:
        """Submit this worker to the shared :class:`WorkerPool`.

        ``QRunnable`` has no ``start()``; this convenience submits via
        ``WorkerPool.instance().submit(self)`` so legacy call sites that
        call ``worker.start()`` run on the pool instead of raising
        ``AttributeError``.
        """
        WorkerPool.instance().submit(self)

    def cancel(self) -> None:
        """Request cooperative cancellation (best-effort).

        The wrapped callable is never interrupted; long-running functions
        can poll :meth:`is_cancelled` between chunks to exit early.
        """
        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        """Return ``True`` after :meth:`cancel` has been requested."""
        return self._cancel_requested

    # ------------------------------------------------------------------ helpers
    def _emit_progress(self, percent: int, message: str = "") -> None:
        """Emit the ``progress`` signal.

        Args:
            percent: Integer 0-100 progress value.
            message: Optional human-readable status message.
        """
        try:
            self.signals.progress.emit(int(percent), str(message))
        except Exception:  # pragma: no cover - defensive
            logger.debug("progress emission failed", exc_info=True)

    # ------------------------------------------------------------------ runtime
    def run(self) -> None:  # noqa: D401 - QRunnable API contract
        """Execute ``fn`` and emit the appropriate signals.

        Catches any exception, emits ``error`` with a formatted traceback, and
        always emits ``finished`` at the end.
        """
        try:
            self.signals.started.emit()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            value = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            tb = traceback.format_exc()
            try:
                self.signals.error.emit(tb)
            except Exception:  # pragma: no cover - defensive
                logger.error("Worker error: %s", tb)
            logger.error("Worker %r raised: %s", getattr(self.fn, "__name__", self.fn), exc)
        else:
            try:
                self.signals.result.emit(value)
            except Exception:  # pragma: no cover - defensive
                logger.debug("result emission failed", exc_info=True)
        finally:
            try:
                self.signals.finished.emit()
            except Exception:  # pragma: no cover - defensive
                pass


# ---------------------------------------------------------------------------
# WorkerPool — singleton (composition, not inheritance, around QThreadPool)
# ---------------------------------------------------------------------------
class WorkerPool:
    """Process-wide singleton wrapping ``QThreadPool.globalInstance()``.

    Use :py:meth:`instance` to obtain the shared pool. The pool exposes
    :py:meth:`submit` (alias for ``start``) and :py:meth:`wait_all`.

    Composition is used instead of subclassing so we can avoid sip lifecycle
    issues with singletons that inherit from ``QThreadPool``.
    """

    _instance: Optional["WorkerPool"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "WorkerPool":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        with self._instance_lock:
            if getattr(self, "_initialized", False):
                return
            if _HAS_QT:
                try:
                    self._real = QThreadPool.globalInstance()
                except Exception:  # pragma: no cover - defensive
                    self._real = None
            else:
                self._real = None
            self._initialized: bool = True

    @classmethod
    def instance(cls) -> "WorkerPool":
        """Return the singleton :class:`WorkerPool` (thread-safe)."""
        return cls()

    def submit(self, worker: Union[Worker, Callable[..., Any]]) -> Optional[Worker]:
        """Submit a :class:`Worker` for asynchronous execution.

        This is the canonical way to run background work (see PATCH
        CONTRACT #1). A bare callable may also be passed for convenience —
        it is wrapped in a :class:`Worker` first.

        Args:
            worker: The :class:`Worker` to run, or any callable (wrapped
                automatically).

        Returns:
            The :class:`Worker` instance that was scheduled.
        """
        if not isinstance(worker, Worker):
            worker = Worker(worker)
        if self._real is not None:
            self._real.start(worker)
        else:
            # Headless fallback — execute synchronously.
            try:
                worker.run()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("WorkerPool stub caught: %s", exc)
        return worker

    def wait_all(self, timeout_ms: int = -1) -> bool:
        """Block until all queued workers complete.

        Args:
            timeout_ms: Maximum wait in milliseconds, or ``-1`` to wait forever.

        Returns:
            ``True`` if all workers completed, ``False`` on timeout.
        """
        if self._real is not None:
            return self._real.waitForDone(timeout_ms if timeout_ms >= 0 else -1)
        return True

    def active_count(self) -> int:
        """Return the current number of active workers."""
        if self._real is not None:
            return self._real.activeThreadCount()
        return 0

    def max_thread_count(self) -> int:
        """Return the configured maximum thread count."""
        if self._real is not None:
            return self._real.maxThreadCount()
        return 1


# ---------------------------------------------------------------------------
# Convenience: run_in_background
# ---------------------------------------------------------------------------
def run_in_background(
    func: Callable[..., Any],
    *args: Any,
    on_done: Optional[Callable[[Any], None]] = None,
    on_progress: Optional[Callable[[int, str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_started: Optional[Callable[[], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> Worker:
    """Schedule ``func`` on the :class:`WorkerPool` and wire up callbacks.

    Each callback is optional; pass ``None`` to skip wiring that signal.

    Args:
        func: The callable to run in the background.
        *args: Positional arguments forwarded to ``func``.
        on_done: Called with the return value on success.
        on_progress: Called with ``(int, str)`` progress updates.
        on_error: Called with a formatted traceback string on failure.
        on_started: Called immediately before ``func`` runs.
        on_finished: Called after ``func`` returns (success or failure).
        **kwargs: Keyword arguments forwarded to ``func``.

    Returns:
        The :class:`Worker` instance (already submitted).
    """
    worker = Worker(func, *args, **kwargs)
    if on_done is not None:
        worker.signals.result.connect(on_done)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    if on_started is not None:
        worker.signals.started.connect(on_started)
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    WorkerPool.instance().submit(worker)
    return worker


__all__ = [
    "WorkerSignals",
    "Worker",
    "WorkerPool",
    "run_in_background",
    "accepts_progress_callback",
]
