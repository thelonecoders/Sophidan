"""High-level workflow orchestrator and Qt signal hub.

The :class:`Orchestrator` coordinates the long-running pipeline of the
Academic Research Suite:

    scrape → clean → analyze → visualize → report

Modules register themselves with the orchestrator, which then accepts
:class:`core.task_queue.Task` instances and dispatches them onto the shared
:class:`core.task_queue.TaskQueue`. Progress and lifecycle events are
broadcast both on the :class:`core.events.EventBus` and through a Qt-friendly
:class:`SignalHub` singleton (defined in this module).

The :class:`SignalHub` is a thin ``QObject`` exposing Qt signals so UI widgets
can subscribe without directly touching the event bus.

Everything is thread-safe via a single :class:`threading.RLock`. The module is
independently importable: qtpy is imported lazily inside :class:`SignalHub`.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import re
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from utils.workers import accepts_progress_callback

logger = logging.getLogger(__name__)

# Lazy local imports to avoid any circular dependency at module import time.
# These resolve at first call to Orchestrator methods, so importing the
# module never triggers them.
def _import_event_bus():
    from core.events import EventBus, Event, EventType, get_event_bus

    return EventBus, Event, EventType, get_event_bus


def _import_task_queue():
    from core.task_queue import Task, TaskQueue, TaskStatus

    return Task, TaskQueue, TaskStatus


# ---------------------------------------------------------------------------
# Qt shim — only SignalHub needs Qt; falls back to a stub when unavailable.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    from qtpy.QtCore import QObject, Signal

    _HAS_QT = True
    _QObjectBase = QObject  # type: ignore[misc, valid-type]
except Exception:  # pragma: no cover - depends on environment
    _HAS_QT = False

    class _QObjectBase:  # type: ignore[no-redef]
        """Stub QObject replacement used when Qt is missing."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass


class _StubSignal:
    """No-op replacement for ``qtpy.QtCore.Signal``."""

    def __init__(self, *types: object) -> None:
        self._types = types
        self._slots: List[Callable[..., None]] = []

    def emit(self, *args: object, **kwargs: object) -> None:
        for slot in self._slots:
            try:
                slot(*args, **kwargs)
            except Exception:  # pragma: no cover - defensive
                pass

    def connect(self, slot: Callable[..., None]) -> Callable[..., None]:
        self._slots.append(slot)
        return slot


def _signal(*types: object) -> Any:
    if _HAS_QT:
        return Signal(*types)  # type: ignore[no-redef]
    return _StubSignal(*types)


# ---------------------------------------------------------------------------
# SignalHub — Qt-friendly view of orchestrator activity
# ---------------------------------------------------------------------------
if _HAS_QT:

    class _SignalHubImpl(QObject):  # type: ignore[misc]
        """Internal QObject holding the real Qt signals."""

        task_started = Signal(str)  # type: ignore[arg-type]
        task_progress = Signal(str, int, str)  # type: ignore[arg-type]
        task_completed = Signal(str, object)  # type: ignore[arg-type]
        task_failed = Signal(str, str)  # type: ignore[arg-type]
        stage_changed = Signal(str)  # type: ignore[arg-type]

else:  # pragma: no cover - depends on environment

    class _SignalHubImpl:  # type: ignore[no-redef]
        """Stub replacement used when Qt is unavailable."""

        def __init__(self) -> None:
            self.task_started = _StubSignal(str)
            self.task_progress = _StubSignal(str, int, str)
            self.task_completed = _StubSignal(str, object)
            self.task_failed = _StubSignal(str, str)
            self.stage_changed = _StubSignal(str)


class SignalHub:
    """Singleton that emits Qt signals for orchestration events.

    Composition is used instead of QObject-inheritance so the singleton pattern
    does not collide with sip lifecycle requirements. The underlying Qt
    object is created lazily inside ``__init__`` and exposed via the same
    attribute names (``task_started``, ``task_progress``, …) so callers can
    do ``SignalHub.instance().task_completed.connect(slot)``.

    Signals (forwarded to the underlying QObject):
        task_started(str): Emitted with the task id when a task starts.
        task_progress(str, int, str): ``id``, percent, message.
        task_completed(str, object): ``id``, result.
        task_failed(str, str): ``id``, error message.
        stage_changed(str): Emitted when the orchestrator moves to a new
            pipeline stage (``scrape`` / ``clean`` / ``analyze`` / …).
    """

    _instance: Optional["SignalHub"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "SignalHub":
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
            # Instantiate the real (or stub) QObject-backed implementation.
            self._impl = _SignalHubImpl()
            # Expose the signal attributes on the hub itself for convenience.
            self.task_started = self._impl.task_started
            self.task_progress = self._impl.task_progress
            self.task_completed = self._impl.task_completed
            self.task_failed = self._impl.task_failed
            self.stage_changed = self._impl.stage_changed
            self._initialized: bool = True

    @classmethod
    def instance(cls) -> "SignalHub":
        """Return the singleton :class:`SignalHub`."""
        return cls()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class Orchestrator:
    """Coordinates long-running workflows across registered modules.

    The orchestrator is the central nervous system of the suite: scrapers,
    cleaners, analysis engines, visualization builders and reporting exporters
    register themselves by name; the orchestrator then accepts
    :class:`core.task_queue.Task` instances, dispatches them onto its
    :class:`core.task_queue.TaskQueue`, and broadcasts progress through both
    the :class:`core.events.EventBus` and the :class:`SignalHub`.

    All public methods are thread-safe.
    """

    STAGES = ("scrape", "clean", "analyze", "visualize", "report")

    def __init__(
        self,
        max_workers: int = 4,
        *,
        bus: Optional[Any] = None,
        hub: Optional[SignalHub] = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            max_workers: Maximum number of background worker threads.
            bus: Optional :class:`EventBus` instance. Defaults to the
                process-wide singleton.
            hub: Optional :class:`SignalHub` instance. Defaults to the
                singleton.
        """
        self._lock = threading.RLock()
        self._modules: Dict[str, Any] = {}

        _, TaskQueue, _ = _import_task_queue()
        _, _, _, get_event_bus = _import_event_bus()

        self._queue: TaskQueue = TaskQueue(max_workers=max_workers)
        self._bus = bus or get_event_bus()
        self._hub: SignalHub = hub or SignalHub.instance()
        self._current_stage: Optional[str] = None

    # ------------------------------------------------------------------ modules
    def register_module(self, name: str, module: Any) -> None:
        """Register a subsystem module under ``name``.

        Args:
            name: Logical module name (e.g. ``"scrapers"``).
            module: Any object — typically an instance of a scraper/engine
                class — exposing callable entry points used by the
                orchestrator.
        """
        with self._lock:
            self._modules[name] = module
        logger.info("Registered orchestrator module: %s", name)

    def get_module(self, name: str) -> Optional[Any]:
        """Return the module registered under ``name``, or ``None``."""
        with self._lock:
            return self._modules.get(name)

    def list_modules(self) -> List[str]:
        """Return the names of all registered modules."""
        with self._lock:
            return list(self._modules.keys())

    # ------------------------------------------------------------------ tasks
    # Pipeline stage -> event "kind" used to pick the emitted EventTypes.
    _STAGE_KINDS = {
        "scrape": "scrape",
        "clean": "analysis",
        "analyze": "analysis",
        "visualize": "export",
        "report": "export",
    }

    @staticmethod
    def _detect_kind(stage: Optional[str], name: str) -> Optional[str]:
        """Guess the task "kind" from its stage / name.

        The kind selects which :class:`core.events.EventType` values are
        published (``scrape`` → ScrapeStarted/Progress/Completed/Failed,
        ``analysis`` → AnalysisProgress/AnalysisCompleted, ``export`` →
        ExportCompleted, ``migrate`` → DBMigrated, ``ai`` → AIResponse,
        ``proxy`` → ProxyRotated). Unknown kinds emit only the generic
        SignalHub signals — never a misleading ``ScrapeStarted``.
        """
        if stage and stage in Orchestrator._STAGE_KINDS:
            return Orchestrator._STAGE_KINDS[stage]
        hay = f"{stage or ''} {name or ''}".lower()
        if "migrat" in hay:
            return "migrate"
        if "scrape" in hay or "crawl" in hay or "harvest" in hay:
            return "scrape"
        if "export" in hay or "report" in hay:
            return "export"
        if "analy" in hay or "cluster" in hay or "topic" in hay or "embed" in hay:
            return "analysis"
        if "proxy" in hay or "rotat" in hay:
            return "proxy"
        if re.search(r"\b(ai|llm|chat|summar|gpt|rag)\b", hay):
            return "ai"
        if "search" in hay or "query" in hay or "fetch" in hay:
            return "scrape"
        return None

    def submit_task(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        stage: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Submit a task for background execution.

        Emits ``task_started`` synchronously on the calling thread (before
        the task actually begins running on the worker pool), publishes the
        kind-appropriate ``Event`` on the :class:`core.events.EventBus`
        (see :meth:`_detect_kind`), and arranges for completion / failure /
        progress events to be emitted from the worker thread. If ``fn``
        accepts a ``progress_callback`` parameter (signature-aware), one is
        injected that drives both the ``task_progress`` Qt signal and the
        progress ``EventType`` for the task kind.

        Args:
            name: Human-readable task name.
            fn: The callable to run.
            *args: Positional arguments forwarded to ``fn``.
            stage: Optional pipeline stage label (one of :attr:`STAGES`).
                If provided, sets the current stage and emits ``stage_changed``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            The :class:`core.task_queue.Task` instance.
        """
        _, Event, EventType, _ = _import_event_bus()

        kind = self._detect_kind(stage, name)
        if stage is not None and stage in self.STAGES:
            self._set_stage(stage)

        # Pre-generate the task id so the progress hook (and any callbacks)
        # can bind to it BEFORE the executor starts the callable.
        task_id = uuid.uuid4().hex

        def _emit_progress(percent: Any, message: Any = "") -> None:
            try:
                pct = max(0, min(100, int(percent)))
            except (TypeError, ValueError):
                return
            try:
                self._hub.task_progress.emit(task_id, pct, str(message))
            except Exception:  # pragma: no cover - defensive
                logger.debug("task_progress emission failed", exc_info=True)
            progress_type = {
                "scrape": EventType.ScrapeProgress,
                "analysis": EventType.AnalysisProgress,
            }.get(kind)
            if progress_type is not None:
                try:
                    self._bus.publish(
                        Event(
                            type=progress_type,
                            payload={
                                "task_id": task_id,
                                "name": name,
                                "percent": pct,
                                "message": str(message),
                            },
                            source="orchestrator",
                        )
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.debug("progress publish failed", exc_info=True)

        # The TaskQueue runner injects a progress callback into fn ONLY when
        # fn's signature accepts it (signature-aware, zero-arg callables are
        # never broken) and routes it through task.progress_hook — which is
        # bound before submit, so there is no identify/submit race.
        task = self._queue.enqueue(
            name, fn, *args,
            task_id=task_id,
            progress_hook=_emit_progress,
            **kwargs,
        )

        # Emit started immediately on the calling thread.
        try:
            self._hub.task_started.emit(task_id)
        except Exception:  # pragma: no cover - defensive
            logger.debug("task_started emission failed", exc_info=True)
        # Publish a bus start event ONLY for the scrape kind — emitting
        # ScrapeStarted for every task kind was the audited bug.
        if kind == "scrape":
            try:
                self._bus.publish(
                    Event(
                        type=EventType.ScrapeStarted,
                        payload={"name": name, "task_id": task_id},
                        source="orchestrator",
                    )
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug("ScrapeStarted publish failed", exc_info=True)

        # Attach completion / failure hooks to the underlying Future so we
        # can emit signals without re-wrapping the callable. This avoids
        # any race between enqueue and the worker picking the task up.
        original_future = task.future

        done_events = {
            "scrape": EventType.ScrapeCompleted,
            "analysis": EventType.AnalysisCompleted,
            "export": EventType.ExportCompleted,
            "migrate": EventType.DBMigrated,
            "ai": EventType.AIResponse,
            "proxy": EventType.ProxyRotated,
        }

        def _on_done(fut: Any) -> None:
            from core.task_queue import TaskStatus  # local, cheap
            try:
                exc = fut.exception()
            except Exception:  # pragma: no cover - defensive
                exc = None
            cancelled = getattr(task, "cancel_requested", False) and (
                task.status is TaskStatus.CANCELLED
            )
            if exc is not None:
                try:
                    self._hub.task_failed.emit(task_id, str(exc))
                except Exception:  # pragma: no cover - defensive
                    pass
                if kind == "scrape":
                    try:
                        self._bus.publish(
                            Event(
                                type=EventType.ScrapeFailed,
                                payload={
                                    "task_id": task_id,
                                    "name": name,
                                    "error": str(exc),
                                },
                                source="orchestrator",
                            )
                        )
                    except Exception:  # pragma: no cover - defensive
                        pass
                return
            if cancelled:
                # cancel() promised post-finish CANCELLED marking — do not
                # advertise a completion event for it.
                return
            try:
                self._hub.task_completed.emit(task_id, fut.result())
            except Exception:  # pragma: no cover - defensive
                pass
            done_type = done_events.get(kind)
            if done_type is not None:
                try:
                    self._bus.publish(
                        Event(
                            type=done_type,
                            payload={
                                "task_id": task_id,
                                "name": name,
                                "result": fut.result(),
                            },
                            source="orchestrator",
                        )
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.debug("done publish failed", exc_info=True)

        if original_future is not None:
            try:
                original_future.add_done_callback(_on_done)
            except Exception:  # pragma: no cover - defensive
                logger.debug("add_done_callback failed", exc_info=True)

        return task

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of the orchestrator state.

        Includes registered module names, current stage, and per-task
        statuses.
        """
        with self._lock:
            return {
                "modules": list(self._modules.keys()),
                "current_stage": self._current_stage,
                "tasks": [t.to_dict() for t in self._queue.list_all()],
                "active_count": len(self._queue.list_active()),
            }

    def cancel(self, task_id: str) -> bool:
        """Cancel a task by id (see :meth:`TaskQueue.cancel`)."""
        return self._queue.cancel(task_id)

    def list_active(self) -> List[Any]:
        """Return a list of currently-active tasks."""
        return self._queue.list_active()

    def wait_all(self, timeout: Optional[float] = None) -> None:
        """Block until every submitted task has reached a terminal state."""
        self._queue.wait_all(timeout=timeout)

    # ------------------------------------------------------------------ stages
    def _set_stage(self, stage: str) -> None:
        """Update the current stage and emit ``stage_changed``."""
        with self._lock:
            self._current_stage = stage
        try:
            self._hub.stage_changed.emit(stage)
        except Exception:  # pragma: no cover - defensive
            logger.debug("stage_changed emission failed", exc_info=True)
        logger.info("Orchestrator stage -> %s", stage)

    # ------------------------------------------------------------------ shutdown
    def shutdown(self, wait: bool = True) -> None:
        """Shut down the underlying task queue."""
        self._queue.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
_ORCHESTRATOR: Optional[Orchestrator] = None
_O_LOCK = threading.Lock()


def get_orchestrator() -> Orchestrator:
    """Return the process-wide :class:`Orchestrator` singleton."""
    global _ORCHESTRATOR
    with _O_LOCK:
        if _ORCHESTRATOR is None:
            _ORCHESTRATOR = Orchestrator()
        return _ORCHESTRATOR


__all__ = [
    "Orchestrator",
    "SignalHub",
    "get_orchestrator",
]
