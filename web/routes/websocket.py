"""Socket.IO blueprint and event-handler registration.

This module exposes the ``ws_bp`` Flask Blueprint (providing a small
number of HTTP endpoints for room introspection) plus the
:func:`init_socketio_handlers` function that registers Socket.IO event
handlers on a running :class:`flask_socketio.SocketIO` instance.

The handlers subscribe to :class:`core.events.EventBus` events and
re-broadcast them to per-task / per-channel socket rooms.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room

logger = logging.getLogger(__name__)

ws_bp = Blueprint("websocket", __name__, url_prefix="/ws")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


# ---------------------------------------------------------------------------
# Small HTTP routes on the /ws blueprint (Socket.IO event handlers are
# registered separately below via ``init_socketio_handlers``).
# ---------------------------------------------------------------------------
@ws_bp.route("/status", methods=["GET"])
def status():
    """Return the current state of the WebSocket subsystem."""
    state = _state()
    return jsonify({
        "socketio_available": state.socketio is not None,
        "event_bus_available": state.event_bus is not None,
        "tasks_tracked": len(state.all_tasks()),
    })


# ---------------------------------------------------------------------------
# Socket.IO event handler registration
# ---------------------------------------------------------------------------
def init_socketio_handlers(socketio: SocketIO) -> None:
    """Register Socket.IO event handlers on the given SocketIO instance.

    Args:
        socketio: The Socket.IO server bound to the Flask app.
    """
    logger.info("Registering Socket.IO event handlers")

    @socketio.on("connect")
    def _on_connect():  # noqa: WPS430
        logger.info("Socket.IO client connected: sid=%s",
                    getattr(request, "sid", "?"))
        emit("connected", {"status": "ok"})

    @socketio.on("disconnect")
    def _on_disconnect():  # noqa: WPS430
        logger.info("Socket.IO client disconnected: sid=%s",
                    getattr(request, "sid", "?"))

    @socketio.on("subscribe")
    def _on_subscribe(payload):  # noqa: WPS430
        """Subscribe the current client to a task / topic room.

        Payload: ``{"task_id": str}`` or ``{"channel": str}``.
        """
        if not isinstance(payload, dict):
            emit("error", {"message": "payload must be an object"})
            return
        task_id = payload.get("task_id")
        channel = payload.get("channel")
        room = None
        if task_id:
            room = f"task:{task_id}"
        elif channel:
            room = f"channel:{channel}"
        if room is None:
            emit("error", {"message": "task_id or channel required"})
            return
        join_room(room)
        emit("subscribed", {"room": room})

    @socketio.on("unsubscribe")
    def _on_unsubscribe(payload):  # noqa: WPS430
        """Unsubscribe the current client from a task / topic room."""
        if not isinstance(payload, dict):
            emit("error", {"message": "payload must be an object"})
            return
        task_id = payload.get("task_id")
        channel = payload.get("channel")
        room = None
        if task_id:
            room = f"task:{task_id}"
        elif channel:
            room = f"channel:{channel}"
        if room is None:
            emit("error", {"message": "task_id or channel required"})
            return
        leave_room(room)
        emit("unsubscribed", {"room": room})

    # Wire up the EventBus → Socket.IO bridge if available.
    _wire_event_bus_bridge(socketio)


def _wire_event_bus_bridge(socketio: SocketIO) -> None:
    """Subscribe to :class:`core.events.EventBus` and re-emit via Socket.IO.

    Bridges backend events (scrape progress, completion, failures) into
    the corresponding socket rooms so connected clients get live updates.

    * Subscribes through the process-wide ``get_event_bus()`` singleton
      so events published by the scraping engine / desktop UI arrive here
      too (a private bus would silently drop them).
    * Uses a wildcard subscription (with a per-topic fallback) and the
      handler accepts **both** :class:`core.events.Event` objects and
      plain ``(topic, payload)`` dicts, mapping every topic — string or
      :class:`core.events.EventType` — to its canonical string form.
    * Room semantics: payloads carrying a ``task_id`` are emitted only to
      ``task:<id>``; everything else broadcasts to all clients.
    """
    try:
        from core.events import EventType, get_event_bus

        bus = get_event_bus()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("EventBus unavailable — Socket.IO bridge disabled: %s",
                       exc)
        return

    # Canonical string topic for every publishable key: the verbatim
    # string keys used across the app plus the EventType enum members
    # (enum → closest contract string; unknown strings pass verbatim).
    _TOPIC_MAP: dict[Any, str] = {
        EventType.ScrapeStarted: "scrape:progress",
        EventType.ScrapeProgress: "scrape:progress",
        EventType.ScrapeCompleted: "scrape:completed",
        EventType.ScrapeFailed: "scrape:failed",
        EventType.AnalysisProgress: "analysis_progress",
        EventType.AnalysisCompleted: "analysis_finished",
        EventType.ExportCompleted: "export_finished",
        EventType.ProxyRotated: "proxy_rotated",
        EventType.AIResponse: "ai:token",
        EventType.DBMigrated: "db_migrated",
        "scrape_started": "scrape:progress",
        "scrape_progress": "scrape:progress",
        "scrape_completed": "scrape:completed",
        "scrape_failed": "scrape:failed",
        "scrape_error": "scrape:error",
        "scrape_finished": "scrape:completed",
        "analysis_finished": "analysis_finished",
        "analysis_completed": "analysis_finished",
        "export_completed": "export_finished",
        "export_finished": "export_finished",
        "paper_added": "paper_added",
    }

    def _normalize(evt: Any) -> tuple[str, dict[str, Any]]:
        """Map an Event / dict / string into a canonical (topic, payload)."""
        if isinstance(evt, dict):
            topic = evt.get("topic") or evt.get("type")
            payload = evt.get("payload", evt)
        else:
            topic = getattr(evt, "type", None)
            payload = getattr(evt, "payload", None)
            if topic is None and payload is None:
                # Handler was called with a bare value.
                topic, payload = "event", evt
            if topic is None:
                topic = "event"
        if hasattr(topic, "value"):  # EventType (or any) enum member
            topic = _TOPIC_MAP.get(topic, topic.value)
        topic = _TOPIC_MAP.get(topic, str(topic))
        if not isinstance(payload, dict):
            payload = {"data": payload}
        return topic, payload

    def _forward(evt: Any) -> None:
        try:
            topic, payload = _normalize(evt)
            task_id = payload.get("task_id")
            if task_id:
                socketio.emit(topic, payload, room=f"task:{task_id}",
                              namespace="/")
            else:
                socketio.emit(topic, payload, namespace="/")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("forward of %r failed: %s", evt, exc)

    subscribed = 0
    try:
        # Wildcard subscription: receives every event regardless of type.
        bus.subscribe(None, _forward)
        subscribed += 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("wildcard EventBus subscription failed: %s", exc)

    if not subscribed:
        # Fallback: explicit per-topic subscriptions (string topics are
        # accepted verbatim per the events contract).
        topics = [
            "scrape:progress", "scrape:completed", "scrape:failed",
            "scrape:error", "scrape:cancelled", "paper_added",
            "scrape_finished", "analysis_finished", "export_finished",
            "log:line", "ai:token", "ai:done",
        ]
        for topic in topics:
            try:
                bus.subscribe(topic, _forward)
                subscribed += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("subscribe to %s failed: %s", topic, exc)

    logger.info("EventBus → Socket.IO bridge wired (%d subscription%s)",
                subscribed, "" if subscribed == 1 else "s")
