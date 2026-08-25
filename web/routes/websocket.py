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

    Bridges backend events (scrape progress, log lines, AI tokens) into
    the corresponding socket rooms so connected clients get live updates.
    """
    state = _state()
    bus = state.event_bus
    if bus is None or not hasattr(bus, "subscribe"):
        logger.info("EventBus unavailable — Socket.IO bridge disabled")
        return

    def _forward(event_type: str, payload: dict[str, Any]) -> None:
        task_id = payload.get("task_id")
        room = f"task:{task_id}" if task_id else None
        try:
            if room:
                socketio.emit(event_type, payload, room=room, namespace="/")
            else:
                socketio.emit(event_type, payload, namespace="/")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("forward of %s failed: %s", event_type, exc)

    # Common event types emitted by the backend.
    events = [
        "scrape:progress", "scrape:complete", "scrape:error",
        "scrape:cancelled", "log:line", "ai:token", "ai:done",
    ]
    for evt in events:
        try:
            bus.subscribe(evt, lambda payload, e=evt: _forward(e, payload))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("subscribe to %s failed: %s", evt, exc)

    logger.info("EventBus → Socket.IO bridge wired for %d events", len(events))
