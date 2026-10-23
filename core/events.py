"""Event bus and event type definitions for Academic Research Suite.

This module defines:

* An :class:`EventType` enum with the canonical event types raised by the
  application (``ScrapeStarted``, ``ScrapeProgress``, … ``DBMigrated``).
* An :class:`Event` dataclass carrying a payload alongside the type.
* An :class:`EventBus` implementing the observer pattern with thread-safe
  :py:meth:`subscribe` / :py:meth:`publish`, string-topic interop and
  Qt-signal integration through :class:`SignalBridge`.

API CONTRACT (worklog "PATCH CONTRACTS" #2)
-------------------------------------------

* ``bus.publish(event_or_topic, payload=None)`` — accepts a ready-made
  :class:`Event`, an :class:`EventType`, **or** a plain string topic with a
  payload (``bus.publish("scrape:completed", {...})``). String topics are
  stored/matched *verbatim*; well-known spellings are additionally mapped
  onto their :class:`EventType` so enum-subscribers also fire.
* ``bus.subscribe(topic_or_type, handler)`` — accepts a string topic, an
  :class:`EventType`, or ``None`` (wildcard). Handlers always receive the
  :class:`Event` object; use ``event.payload`` for the published body
  (``Event.get(key)`` is a dict-payload convenience).
* ``get_event_bus()`` returns the process-wide singleton;
  ``EventBus.instance()`` is a classmethod alias (UI/web code calls it).

String-topic ↔ EventType interop
--------------------------------

Publishing an :class:`Event` also notifies string-subscribers whose topic
matches the event type (separator-insensitively): e.g. an
``Event(EventType.ScrapeCompleted)`` notifies subscribers of
``"scrape:completed"``, ``"scrape.completed"``, ``"scrape_completed"`` and
the synonyms ``"scrape_finished"`` / ``"scrape:complete"``. Conversely,
publishing the string ``"scrape:completed"`` also fires handlers registered
for ``EventType.ScrapeCompleted``. Topics with no matching event type
(``"paper_added"``, ``"log:line"``, ``"ai:token"``, …) are delivered to
their verbatim (and separator-normalised) string subscribers only.

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
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

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
    AnalysisCompleted = "analysis_completed"
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
AnalysisCompleted = EventType.AnalysisCompleted
ExportCompleted = EventType.ExportCompleted
ProxyRotated = EventType.ProxyRotated
AIResponse = EventType.AIResponse
DBMigrated = EventType.DBMigrated


def _norm_topic(topic: str) -> str:
    """Normalise a topic string for alias matching (not for storage).

    ``"scrape:completed"`` / ``"scrape.completed"`` / ``"Scrape_Completed"``
    all normalise to ``"scrape_completed"``. Registry keys themselves are
    always stored verbatim.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(topic).lower()).strip("_")


# Alias sets: every string spelling that a published EventType also notifies.
_EVENT_ALIASES: Dict[EventType, Tuple[str, ...]] = {
    EventType.ScrapeStarted: ("scrape_started",),
    EventType.ScrapeProgress: ("scrape_progress",),
    EventType.ScrapeCompleted: (
        "scrape_completed", "scrape_complete", "scrape_finished",
        "scrape_done",
    ),
    EventType.ScrapeFailed: (
        "scrape_failed", "scrape_error", "scrape_failure",
    ),
    EventType.AnalysisProgress: ("analysis_progress",),
    EventType.AnalysisCompleted: (
        "analysis_completed", "analysis_finished", "analysis_done",
    ),
    EventType.ExportCompleted: (
        "export_completed", "export_finished", "export_done",
    ),
    EventType.ProxyRotated: ("proxy_rotated", "proxy_rotation"),
    EventType.AIResponse: ("ai_response", "ai_done"),
    EventType.DBMigrated: ("db_migrated", "database_migrated",
                           "migration_completed"),
}

# Reverse lookup: normalised string topic -> EventType (if any).
_STRING_TO_EVENT: Dict[str, EventType] = {}
for _etype, _aliases in _EVENT_ALIASES.items():
    for _alias in _aliases:
        _STRING_TO_EVENT[_alias] = _etype


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------
@dataclass
class Event:
    """A single event published on the :class:`EventBus`.

    Attributes:
        type: One of :class:`EventType`, or the verbatim topic string for
            free-form topics (``"paper_added"``, ``"log:line"``, …).
        payload: Arbitrary structured data for the handler.
        timestamp: Monotonic creation time (epoch seconds).
        source: Optional name of the publishing component.
    """

    type: Union[EventType, str]
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style accessor over a dict payload (convenience for bridges).

        Returns ``default`` when the payload is not a dict or the key is
        missing, so consumers written as ``event.get("task_id")`` work for
        both structured and empty payloads.
        """
        payload = self.payload
        if isinstance(payload, dict):
            return payload.get(key, default)
        return default

    def topic_name(self) -> str:
        """Return the canonical string name of this event's type."""
        if isinstance(self.type, EventType):
            return self.type.value
        return str(self.type)


EventHandler = Callable[[Event], None]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------
class EventBus:
    """Thread-safe observer-pattern event bus.

    Handlers may subscribe by :class:`EventType`, by verbatim string topic,
    or wildcard (``None``). Handlers are invoked synchronously on the
    publishing thread, so they must be cheap or offload long work
    themselves. See the module docstring for the topic-interop rules.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._string_handlers: Dict[str, List[EventHandler]] = {}
        self._wildcard_handlers: List[EventHandler] = []
        self._bridge: Optional["SignalBridge"] = None

    # ------------------------------------------------------------------ keys
    @staticmethod
    def _string_keys_for(event_type: EventType) -> Set[str]:
        """Return the normalised topic keys notified for ``event_type``."""
        return set(_EVENT_ALIASES.get(event_type, ())) | {event_type.value}

    @staticmethod
    def _event_for_topic(topic: str) -> Optional[EventType]:
        """Return the :class:`EventType` a string topic maps to, if any."""
        return _STRING_TO_EVENT.get(_norm_topic(topic))

    # ------------------------------------------------------------------ subscribe
    def subscribe(
        self,
        topic_or_type: Optional[Union[EventType, str]],
        handler: EventHandler,
    ) -> EventHandler:
        """Register ``handler`` for a topic / event type / every event.

        Args:
            topic_or_type: An :class:`EventType`, a verbatim string topic
                (``"scrape:completed"``, ``"paper_added"``, …), or ``None``
                to receive every event (wildcard subscriber).
            handler: A callable accepting an :class:`Event`.

        Returns:
            The same handler, for use as a decorator.
        """
        with self._lock:
            if topic_or_type is None:
                self._wildcard_handlers.append(handler)
            elif isinstance(topic_or_type, EventType):
                self._handlers.setdefault(topic_or_type, []).append(handler)
            else:
                # Stored verbatim under the exact string given.
                self._string_handlers.setdefault(
                    str(topic_or_type), [],
                ).append(handler)
        return handler

    def unsubscribe(
        self,
        topic_or_type: Optional[Union[EventType, str]],
        handler: EventHandler,
    ) -> bool:
        """Remove a previously-registered handler.

        Args:
            topic_or_type: The same key passed to :meth:`subscribe`
                (``None`` for wildcard handlers).
            handler: The handler callable to remove.

        Returns:
            ``True`` if the handler was removed, ``False`` if not registered.
        """
        with self._lock:
            if topic_or_type is None:
                lst = self._wildcard_handlers
            elif isinstance(topic_or_type, EventType):
                lst = self._handlers.get(topic_or_type, [])
            else:
                lst = self._string_handlers.get(str(topic_or_type), [])
            if handler in lst:
                lst.remove(handler)
                return True
            return False

    # ------------------------------------------------------------------ publish
    def publish(
        self,
        event_or_topic: Union[Event, EventType, str],
        payload: Any = None,
        *,
        source: Optional[str] = None,
    ) -> Optional[Event]:
        """Dispatch an event (or topic + payload) to all matching handlers.

        Overloads:

        * ``publish(event)`` — dispatch a ready-made :class:`Event`
          (backward compatible with the original API).
        * ``publish(EventType.X)`` / ``publish(EventType.X, payload)`` —
          wrap into an :class:`Event` and dispatch.
        * ``publish("topic", payload)`` — wrap the verbatim string topic
          into an :class:`Event` and dispatch. If the topic maps to a
          known :class:`EventType` (e.g. ``"scrape:completed"``), the
          corresponding enum subscribers are notified as well.

        Handlers are invoked synchronously and always receive the
        :class:`Event` object. Exceptions raised by individual handlers are
        logged but do not prevent subsequent handlers from running.

        Args:
            event_or_topic: The :class:`Event`, :class:`EventType` or string
                topic to publish.
            payload: Payload used when wrapping (ignored when a ready-made
                :class:`Event` is passed).
            source: Optional component name for wrapped events.

        Returns:
            The :class:`Event` that was dispatched (``None`` if the input
            was invalid).
        """
        if isinstance(event_or_topic, Event):
            event = event_or_topic
        elif isinstance(event_or_topic, EventType):
            event = Event(type=event_or_topic, payload=payload, source=source)
        elif isinstance(event_or_topic, str):
            topic = event_or_topic
            mapped = self._event_for_topic(topic)
            if mapped is not None:
                event = Event(type=mapped, payload=payload, source=source)
            else:
                event = Event(type=topic, payload=payload, source=source)
        else:
            logger.warning(
                "EventBus.publish got unsupported %r — ignored",
                type(event_or_topic).__name__,
            )
            return None

        with self._lock:
            handler_lists: List[List[EventHandler]] = []
            if isinstance(event.type, EventType):
                handler_lists.append(list(self._handlers.get(event.type, [])))
                wanted = self._string_keys_for(event.type)
                for topic, lst in self._string_handlers.items():
                    if _norm_topic(topic) in wanted and lst:
                        handler_lists.append(list(lst))
            else:
                canonical = _norm_topic(str(event.type))
                for topic, lst in self._string_handlers.items():
                    if _norm_topic(topic) == canonical and lst:
                        handler_lists.append(list(lst))
                mapped = self._event_for_topic(str(event.type))
                if mapped is not None:
                    handler_lists.append(list(self._handlers.get(mapped, [])))
            handler_lists.append(list(self._wildcard_handlers))
            bridge = self._bridge

        for handlers in handler_lists:
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
        return event

    # ------------------------------------------------------------------ singleton
    @classmethod
    def instance(cls) -> "EventBus":
        """Return the process-wide singleton (alias of :func:`get_event_bus`).

        Provided because UI / web code calls ``EventBus.instance()``.
        """
        return get_event_bus()

    # ------------------------------------------------------------------ bridge
    def attach_bridge(self, bridge: "SignalBridge") -> None:
        """Attach a :class:`SignalBridge` for Qt signal integration."""
        with self._lock:
            self._bridge = bridge

    def clear(self) -> None:
        """Remove every subscribed handler (mainly for tests)."""
        with self._lock:
            self._handlers.clear()
            self._string_handlers.clear()
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
        if not _HAS_QT:
            # Per-instance stub so concurrent bridges never share slots
            # (the class attribute would otherwise be one shared object).
            self.event_published = _signal(object)
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
    "AnalysisCompleted",
    "ExportCompleted",
    "ProxyRotated",
    "AIResponse",
    "DBMigrated",
]
