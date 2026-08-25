"""Flask application factory and WebSocket server bootstrap.

This module exposes :func:`create_app` (a Flask app factory) and
:func:`run_server` (an entry point that starts the HTTP + Socket.IO
server). It also defines the :class:`ServerState` singleton that
lazy-initialises backend services (database, scraping engine, proxy
pool, AI chat engine) on first use.

Every backend service is imported lazily so that the web server can
boot even when downstream agents have not yet delivered their modules.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

logger = logging.getLogger(__name__)

# Canonical version string for the web server subsystem.
__version__ = "0.1.0"


class ServerState:
    """Process-wide singleton holding references to backend services.

    Backend modules (``database``, ``data_acquisition.scraping_engine``,
    ``proxy.proxy_pool``, ``ai_assistant.chat_engine`` ...) are imported
    lazily inside the accessor properties so that the web server can
    boot before those modules have been wired up. If a service cannot be
    imported, the corresponding property returns ``None`` and logs a
    warning; route handlers are expected to degrade gracefully.
    """

    _instance: Optional["ServerState"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ServerState":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._db = None
        self._project_manager = None
        self._scraping_engine = None
        self._proxy_pool = None
        self._chat_engine = None
        self._event_bus = None
        self._tasks: dict[str, dict[str, Any]] = {}
        self._socketio = None
        self._initialized = True

    # ------------------------------------------------------------------ #
    # Lazy backend accessors
    # ------------------------------------------------------------------ #
    @property
    def db(self):
        """Return the shared :class:`DatabaseConnection`, lazily created.

        On first access the schema is auto-initialised via
        :meth:`DatabaseConnection.init_db` so that the web server works
        out-of-the-box against a fresh ``data/ars.db`` file without
        requiring the caller to have run a separate bootstrapping step.
        """
        if self._db is None:
            try:
                from database.connection import DatabaseConnection  # type: ignore

                self._db = DatabaseConnection()
                # Ensure the canonical schema exists — idempotent.
                try:
                    self._db.init_db()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("init_db() on first db access failed: %s", exc)
                logger.info("DatabaseConnection initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("DatabaseConnection unavailable: %s", exc)
        return self._db

    @property
    def project_manager(self):
        """Return the shared :class:`ProjectManager`, lazily created."""
        if self._project_manager is None:
            try:
                from project_management.project_manager import (  # type: ignore
                    ProjectManager,
                )

                self._project_manager = ProjectManager(self.db)
                logger.info("ProjectManager initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("ProjectManager unavailable: %s", exc)
        return self._project_manager

    @property
    def scraping_engine(self):
        """Return the shared :class:`ScrapingEngine`, lazily created."""
        if self._scraping_engine is None:
            try:
                from data_acquisition.scraping_engine import (  # type: ignore
                    ScrapingEngine,
                )

                # ``ProxyPool.manager`` (a :class:`ProxyManager`) exposes the
                # ``get_proxy()`` contract the scrapers expect. We pass it
                # through as the engine's ``proxy_manager`` so registered
                # scrapers inherit proxy rotation transparently. If the
                # ``proxy_pool`` itself exposes ``get_proxy`` (it does), we
                # prefer the underlying manager for a cleaner API surface.
                proxy_mgr = None
                pool = self.proxy_pool
                if pool is not None:
                    proxy_mgr = getattr(pool, "manager", None) or pool
                self._scraping_engine = ScrapingEngine(proxy_manager=proxy_mgr)
                logger.info("ScrapingEngine initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("ScrapingEngine unavailable: %s", exc)
        return self._scraping_engine

    @property
    def proxy_pool(self):
        """Return the shared :class:`ProxyPool`, lazily created."""
        if self._proxy_pool is None:
            try:
                from proxy.proxy_pool import ProxyPool  # type: ignore

                self._proxy_pool = ProxyPool()
                logger.info("ProxyPool initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("ProxyPool unavailable: %s", exc)
        return self._proxy_pool

    @property
    def chat_engine(self):
        """Return the shared :class:`ChatEngine`, lazily created."""
        if self._chat_engine is None:
            try:
                from ai_assistant.chat_engine import ChatEngine  # type: ignore
                from ai_assistant.llm_client import LLMClient  # type: ignore

                # ChatEngine requires an llm_client. Default to the offline
                # echo backend so the web UI works out-of-the-box without
                # cloud API keys; users can swap in a real provider later
                # via the desktop settings panel.
                llm = LLMClient(provider="none", model="echo")
                self._chat_engine = ChatEngine(llm_client=llm)
                logger.info("ChatEngine initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("ChatEngine unavailable: %s", exc)
        return self._chat_engine

    @property
    def event_bus(self):
        """Return the shared :class:`EventBus`, lazily created."""
        if self._event_bus is None:
            try:
                from core.events import EventBus  # type: ignore

                self._event_bus = EventBus()
                logger.info("EventBus initialised")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("EventBus unavailable: %s", exc)
        return self._event_bus

    # ------------------------------------------------------------------ #
    # Task registry (used by the scraping endpoints)
    # ------------------------------------------------------------------ #
    def register_task(self, task_id: str, payload: dict[str, Any]) -> None:
        """Record a new long-running task in the in-memory registry."""
        self._tasks[task_id] = payload

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Look up a task by id, returning ``None`` if not found."""
        return self._tasks.get(task_id)

    def all_tasks(self) -> dict[str, dict[str, Any]]:
        """Return a shallow copy of the entire task registry."""
        return dict(self._tasks)

    # ------------------------------------------------------------------ #
    # Socket.IO handle (set by ``create_app`` after instantiation)
    # ------------------------------------------------------------------ #
    @property
    def socketio(self):
        """Return the Socket.IO server instance bound to this app."""
        return self._socketio

    @socketio.setter
    def socketio(self, value) -> None:
        self._socketio = value


def _register_request_logging(app: Flask) -> None:
    """Attach an after-request hook that logs every HTTP request."""

    @app.after_request
    def _log_response(response: Response) -> Response:  # noqa: WPS430
        try:
            logger.info(
                "%s %s -> %d (%d bytes)",
                request.method,
                request.path,
                response.status_code,
                response.calculate_content_length() or 0,
            )
        except Exception:  # pragma: no cover - never break response
            pass
        return response


def _register_error_handlers(app: Flask) -> None:
    """Install JSON error handlers for 404 and 500 responses."""

    @app.errorhandler(404)
    def _not_found(err):  # noqa: WPS430
        return jsonify({
            "error": "not_found",
            "message": str(err.description) if hasattr(err, "description") else "Resource not found",
            "path": request.path,
        }), 404

    @app.errorhandler(500)
    def _server_error(err):  # noqa: WPS430
        logger.exception("Internal server error: %s", err)
        return jsonify({
            "error": "internal_server_error",
            "message": str(err),
        }), 500

    @app.errorhandler(400)
    def _bad_request(err):  # noqa: WPS430
        return jsonify({
            "error": "bad_request",
            "message": str(err),
        }), 400


def _register_root_routes(app: Flask) -> None:
    """Register the dashboard and API docs HTML routes."""

    @app.route("/")
    def _index():  # noqa: WPS430
        return render_template("index.html")

    @app.route("/api/docs")
    def _api_docs():  # noqa: WPS430
        return render_template("api_docs.html")

    @app.route("/api/health")
    def _health():  # noqa: WPS430
        state = ServerState()
        modules = {
            "database": state.db is not None,
            "project_manager": state.project_manager is not None,
            "scraping_engine": state.scraping_engine is not None,
            "proxy_pool": state.proxy_pool is not None,
            "chat_engine": state.chat_engine is not None,
            "event_bus": state.event_bus is not None,
        }
        active = [name for name, ok in modules.items() if ok]
        return jsonify({
            "status": "ok",
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modules": modules,
            "active_modules": active,
            "tasks": len(state.all_tasks()),
        })


def create_app(config_overrides: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_overrides: Optional dict of Flask config keys to override
            after defaults have been applied.

    Returns:
        Configured Flask application with all blueprints registered
        and Socket.IO bound. The Socket.IO server is stored on the
        ``ServerState`` singleton under the ``socketio`` attribute.
    """
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    # ---- Configuration ------------------------------------------------
    app.config.update(
        SECRET_KEY=os.environ.get("ARS_SECRET_KEY", "ars-dev-secret-change-me"),
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # 50 MB upload cap
        CORS_ORIGINS="*",
    )
    if config_overrides:
        app.config.update(config_overrides)

    # ---- Extensions ---------------------------------------------------
    CORS(app, resources={r"/*": {"origins": "*"}})

    # flask-socketio is optional — if simple-websocket / eventlet are not
    # present, we still want a working HTTP API.
    socketio = None
    try:
        from flask_socketio import SocketIO

        socketio = SocketIO(
            app,
            cors_allowed_origins="*",
            async_mode="threading",
            logger=False,
            engineio_logger=False,
        )
        ServerState().socketio = socketio

        # Register Socket.IO event handlers from the websocket blueprint.
        try:
            from web.routes.websocket import init_socketio_handlers

            init_socketio_handlers(socketio)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not register Socket.IO handlers: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("flask-socketio unavailable, running HTTP-only: %s", exc)

    # ---- Blueprints ---------------------------------------------------
    from web.routes import ALL_BLUEPRINTS  # local import avoids cycles

    for bp in ALL_BLUEPRINTS:
        try:
            app.register_blueprint(bp)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to register blueprint %s: %s",
                           getattr(bp, "name", "?"), exc)

    # ---- Logging + errors + root routes -------------------------------
    _register_request_logging(app)
    _register_error_handlers(app)
    _register_root_routes(app)

    app.config["ARS_SOCKETIO"] = socketio
    logger.info("Flask app created with %d blueprints", len(ALL_BLUEPRINTS))
    return app


def run_server(port: int = 8765, host: str = "127.0.0.1",
               debug: bool = False) -> None:
    """Start the HTTP + WebSocket server.

    Args:
        port: TCP port to listen on (default 8765).
        host: Bind address (default ``127.0.0.1`` — local only).
        debug: Whether to enable Flask's debug reloader.
    """
    app = create_app()
    socketio = app.config.get("ARS_SOCKETIO")
    logger.info("Starting Academic Research Suite web server on %s:%d", host, port)
    if socketio is not None:
        socketio.run(app, host=host, port=port, debug=debug,
                     allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=debug)
