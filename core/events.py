"""Event bus and event type definitions for Academic Research Suite.

This module defines:

* An :class:`EventType` enum with the canonical event types raised by the
  application (``ScrapeStarted``, ``ScrapeProgress``, … ``DBMigrated``).
* An :class:`Event` dataclass carrying a payload alongside the type.
* An :class:`EventBus` implementing the observer pattern with thread-safe
  :py:meth:`subscribe` / :py:meth:`publish` and Qt-signal integration through
  :class:`SignalBridge`.

The bus is intentionally Qt-agnostic at its core — handlers are plain Python
callables invoked on the publishing thread. The optional :class:`SignalBridge`
forwards every published event to a Qt signal so that GUI code can subscribe
without worrying about threading.

The module is independently importable; qtpy is imported lazily inside
:class:`SignalBridge`.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------
class EventType(enum.Enum):
    """Canonical event types raised throughout the application."""

    ScrapeStarted = "scrape_started"
    ScrapeProgress = "scrape_progress"
    ScrapeCompleted = "scrape_completed"
    ScrapeFailed = "scrape_failed"
    AnalysisProgress = "analysis_progress"
    ExportCompleted = "export_completed"
    ProxyRotated = "proxy_rotated"
    AIResponse = "ai_response"
    DBMigrated = "db_migrated"


# Convenience aliases (the names called out in the spec).
ScrapeStarted = EventType.ScrapeStarted
ScrapeProgress = EventType.ScrapeProgress
ScrapeCompleted = EventType.ScrapeCompleted
ScrapeFailed = EventType.ScrapeFailed
AnalysisProgress = EventType.AnalysisProgress
ExportCompleted = EventType.ExportCompleted
ProxyRotated = EventType.ProxyRotated
AIResponse = EventType.AIResponse
DBMigrated = EventType.DBMigrated


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------
@dataclass
class Event:
    """A single event published on the :class:`EventBus`.

    Attributes:
        type: One of :class:`EventType`.
        payload: Arbitrary structured data for the handler.
        timestamp: Monotonic creation time (epoch seconds).
        source: Optional name of the publishing component.
    """

    type: EventType
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None


EventHandler = Callable[[Event], None]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------
class EventBus:
    """Thread-safe observer-pattern event bus.

    Multiple handlers may subscribe to the same :class:`EventType`. Handlers
    are invoked synchronously on the publishing thread, so they must be cheap
    or offload long work themselves.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._wildcard_handlers: List[EventHandler] = []
        self._bridge: Optional["SignalBridge"] = None

    # ------------------------------------------------------------------ subscribe
    def subscribe(
        self,
        event_type: Optional[EventType],
        handler: EventHandler,
    ) -> EventHandler:
        """Register ``handler`` for events of ``event_type``.

        Args:
            event_type: The :class:`EventType` to listen for, or ``None`` to
                receive every event (wildcard subscriber).
            handler: A callable accepting an :class:`Event`.

        Returns:
            The same handler, for use as a decorator.
        """
        with self._lock:
            if event_type is None:
                self._wildcard_handlers.append(handler)
            else:
                self._handlers.setdefault(event_type, []).append(handler)
        return handler

    def unsubscribe(
        self,
        event_type: Optional[EventType],
        handler: EventHandler,
    ) -> bool:
        """Remove a previously-registered handler.

        Args:
            event_type: The same type passed to :meth:`subscribe`, or ``None``
                for wildcard handlers.
            handler: The handler callable to remove.

        Returns:
            ``True`` if the handler was removed, ``False`` if not registered.
        """
        with self._lock:
            lst = (
                self._wildcard_handlers
                if event_type is None
                else self._handlers.get(event_type, [])
            )
            if handler in lst:
                lst.remove(handler)
                return True
            return False

    # ------------------------------------------------------------------ publish
    def publish(self, event: Event) -> None:
        """Dispatch ``event`` to all matching handlers.

        Handlers are invoked synchronously. Exceptions raised by individual
        handlers are logged but do not prevent subsequent handlers from
        running.

        Args:
            event: The :class:`Event` to publish.
        """
        with self._lock:
            handlers = list(self._handlers.get(event.type, [])) + list(self._wildcard_handlers)
            bridge = self._bridge
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Event handler %r raised", handler)
        if bridge is not None:
            try:
                bridge.forward(event)
            except Exception:  # pragma: no cover - defensive
                logger.debug("SignalBridge.forward failed", exc_info=True)

    # ------------------------------------------------------------------ bridge
    def attach_bridge(self, bridge: "SignalBridge") -> None:
        """Attach a :class:`SignalBridge` for Qt signal integration."""
        with self._lock:
            self._bridge = bridge

    def clear(self) -> None:
        """Remove every subscribed handler (mainly for tests)."""
        with self._lock:
            self._handlers.clear()
            self._wildcard_handlers.clear()


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
_EVENT_BUS: Optional[EventBus] = None
_BUS_LOCK = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide :class:`EventBus` singleton."""
    global _EVENT_BUS
    with _BUS_LOCK:
        if _EVENT_BUS is None:
            _EVENT_BUS = EventBus()
        return _EVENT_BUS


# ---------------------------------------------------------------------------
# SignalBridge — forwards every event to a Qt signal for GUI consumers
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


class SignalBridge(_QObjectBase):  # type: ignore[misc]
    """Bridges :class:`EventBus` events to a Qt signal.

    The :attr:`event_published` signal carries the :class:`Event` object so Qt
    slots can subscribe with::

        bridge.event_published.connect(my_slot)
    """

    event_published: Any = _signal(object)

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        """Initialize the bridge.

        Args:
            bus: The :class:`EventBus` to attach to. Defaults to the singleton.
        """
        super().__init__()
        self._bus: EventBus = bus or get_event_bus()
        self._bus.attach_bridge(self)

    def forward(self, event: Event) -> None:
        """Emit the Qt signal for ``event``."""
        try:
            self.event_published.emit(event)
        except Exception:  # pragma: no cover - defensive
            logger.debug("event_published emission failed", exc_info=True)


__all__ = [
    "EventType",
    "Event",
    "EventBus",
    "get_event_bus",
    "SignalBridge",
    # Convenience aliases for the spec-named types
    "ScrapeStarted",
    "ScrapeProgress",
    "ScrapeCompleted",
    "ScrapeFailed",
    "AnalysisProgress",
    "ExportCompleted",
    "ProxyRotated",
    "AIResponse",
    "DBMigrated",
]
