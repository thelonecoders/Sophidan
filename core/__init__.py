"""Core infrastructure package for Academic Research Suite.

Re-exports the :class:`Orchestrator`, :class:`SignalHub`,
:class:`EventBus`, :class:`TaskQueue` and helpers so callers can do::

    from core import get_orchestrator, get_event_bus
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from .events import EventBus, Event, EventType, get_event_bus, SignalBridge
from .task_queue import Task, TaskQueue, TaskStatus
from .orchestrator import Orchestrator, SignalHub, get_orchestrator

__all__ = [
    "EventBus",
    "Event",
    "EventType",
    "get_event_bus",
    "SignalBridge",
    "Task",
    "TaskQueue",
    "TaskStatus",
    "Orchestrator",
    "SignalHub",
    "get_orchestrator",
]
