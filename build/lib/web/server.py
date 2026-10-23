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
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Flask, Response, g, jsonify, render_template, request
from flask_cors import CORS

logger = logging.getLogger(__name__)

# Canonical version string for the web server subsystem, sourced from
# the layered configuration so `/api/health` reports the real version.
try:
    from config.settings import get_settings as _get_settings

    __version__ = _get_settings().version
except Exception:  # noqa: BLE001 - config layer must never break startup
    __version__ = "2.0.0"

# Task-registry hygiene: in-memory tasks are capped and expired so the
# registry cannot grow without bound across a long-lived server process.
TASK_REGISTRY_CAP = 200
TASK_TTL_SECONDS = 3600.0  # 1 hour

# Content-Security-Policy allowing the inline <script>/<style> blocks the
# bundled templates use, while restricting every other source to 'self'.
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


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
        self._tasks_lock = threading.Lock()
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
        """Return the shared :class:`ChatEngine`, lazily created.

        The engine is built from the layered settings (``ai_provider``,
        ``ai_model``, ``ai_api_key``, ``ai_base_url``). If the real
        provider is misconfigured or unavailable we fall back to the
        offline echo backend so the web UI keeps working out-of-the-box.
        """
        if self._chat_engine is None:
            try:
                from ai_assistant.chat_engine import ChatEngine  # type: ignore
                from ai_assistant.llm_client import LLMClient  # type: ignore

                llm = None
                try:
                    from config.settings import get_settings

                    settings = get_settings()
                    llm = LLMClient(
                        provider=settings.ai_provider,
                        model=settings.ai_model or "echo",
                        api_key=settings.ai_api_key or None,
                        base_url=settings.ai_base_url or None,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Could not build LLMClient from settings: %s", exc
                    )
                if llm is None:  # echo fallback
                    llm = LLMClient(provider="none", model="echo")
                self._chat_engine = ChatEngine(llm_client=llm)
                logger.info(
                    "ChatEngine initialised (provider=%s)",
                    getattr(llm, "provider", "?"),
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("ChatEngine unavailable: %s", exc)
        return self._chat_engine

    @property
    def event_bus(self):
        """Return the process-wide :class:`EventBus` singleton.

        Always resolves through :func:`core.events.get_event_bus` so the
        web layer, the scraping engine, and the desktop UI all share the
        same bus (a private ``EventBus()`` instance would silently drop
        every cross-component event).
        """
        if self._event_bus is None:
            try:
                from core.events import get_event_bus  # type: ignore

                self._event_bus = get_event_bus()
                logger.info("EventBus initialised (process-wide singleton)")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("EventBus unavailable: %s", exc)
        return self._event_bus

    # ------------------------------------------------------------------ #
    # Task registry (used by the scraping endpoints)
    # ------------------------------------------------------------------ #
    # Entries are stored behind a lock and always handed out as copies,
    # so background workers mutating their local task dict never race
    # with request threads reading the registry.
    def register_task(self, task_id: str, payload: dict[str, Any]) -> None:
        """Record a new long-running task in the in-memory registry.

        The payload is copied on write and the registry is pruned
        (TTL 1h, cap 200) on every insert so it cannot grow unbounded.
        """
        now = time.time()
        with self._tasks_lock:
            record = dict(payload)
            record.setdefault("registered_at", now)
            self._tasks[task_id] = record
            self._evict_tasks(now)

    def _evict_tasks(self, now: float) -> None:
        """Drop stale entries (TTL) then enforce the registry cap."""
        stale = [
            task_id
            for task_id, task in self._tasks.items()
            if now - float(task.get("created_at")
                            or task.get("registered_at") or 0.0)
            > TASK_TTL_SECONDS
        ]
        for task_id in stale:
            del self._tasks[task_id]
        if len(self._tasks) > TASK_REGISTRY_CAP:
            ordered = sorted(
                self._tasks.items(),
                key=lambda item: float(item[1].get("created_at")
                                       or item[1].get("registered_at") or 0.0),
            )
            excess = len(self._tasks) - TASK_REGISTRY_CAP
            for task_id, _task in ordered[:excess]:
                del self._tasks[task_id]

    def update_task(self, task_id: str,
                    updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Merge ``updates`` into a stored task under the registry lock.

        The background scrape worker and the ``/cancel`` request handler
        both mutate the *shared* task record; routing every field-level
        write through this lock-guarded merge prevents lost updates
        (e.g. a ``cancelled`` status written by the cancel route being
        clobbered by the worker's next progress publish). Returns the
        updated copy, or ``None`` when the task id is unknown.
        """
        if not isinstance(updates, dict) or not updates:
            return self.get_task(task_id)
        with self._tasks_lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            record.update(updates)
            self._evict_tasks(time.time())
            return dict(record)

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Look up a task by id, returning a defensive copy or ``None``."""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            return dict(task) if task is not None else None

    def all_tasks(self) -> dict[str, dict[str, Any]]:
        """Return a copy of the entire task registry (copies per task)."""
        with self._tasks_lock:
            return {task_id: dict(task)
                    for task_id, task in self._tasks.items()}

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


def _register_request_hooks(app: Flask) -> None:
    """Attach per-request logging, a request id, and security headers."""

    @app.before_request
    def _assign_request_id():  # noqa: WPS430
        # Correlate log lines with error responses without leaking
        # internals to the client.
        g.request_id = uuid.uuid4().hex
        return None

    @app.after_request
    def _log_and_harden(response: Response) -> Response:  # noqa: WPS430
        try:
            logger.info(
                "%s %s -> %d (%d bytes) [%s]",
                request.method,
                request.path,
                response.status_code,
                response.calculate_content_length() or 0,
                getattr(g, "request_id", "-"),
            )
        except Exception:  # pragma: no cover - never break response
            pass
        # Baseline hardening applied to every response (HTML, JSON, SSE).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy",
                                    "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy",
                                    _CONTENT_SECURITY_POLICY)
        return response


def _register_error_handlers(app: Flask) -> None:
    """Install JSON error handlers for 400 / 404 / 405 / 500 responses."""

    @app.errorhandler(404)
    def _not_found(err):  # noqa: WPS430
        return jsonify({
            "error": "not_found",
            "message": str(err.description) if hasattr(err, "description") else "Resource not found",
            "path": request.path,
        }), 404

    @app.errorhandler(405)
    def _method_not_allowed(err):  # noqa: WPS430
        return jsonify({
            "error": "method_not_allowed",
            "message": f"{request.method} is not allowed for {request.path}",
            "path": request.path,
            "request_id": getattr(g, "request_id", None),
        }), 405

    @app.errorhandler(500)
    def _server_error(err):  # noqa: WPS430
        # Log the full exception server-side; the client only gets a
        # generic message plus a request id for log correlation — never
        # ``str(err)``, which can leak paths, SQL, or key material.
        request_id = getattr(g, "request_id", None) or uuid.uuid4().hex
        logger.exception("Internal server error [request_id=%s]: %s",
                         request_id, err)
        return jsonify({
            "error": "internal_server_error",
            "message": "an unexpected error occurred; see server logs for details",
            "request_id": request_id,
        }), 500

    @app.errorhandler(400)
    def _bad_request(err):  # noqa: WPS430
        return jsonify({
            "error": "bad_request",
            "message": str(err.description) if hasattr(err, "description") else str(err),
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
    # Security defaults: no hard-coded secret and no wildcard CORS.
    #  * SECRET_KEY: ``ARS_SECRET_KEY`` or a random per-process key.
    #  * CORS_ORIGINS: ``ARS_CORS_ORIGINS`` (comma-separated, or ``*`` to
    #    opt in to the old open behaviour); default is the local origins
    #    for the configured port. Same-origin requests never need CORS.
    _port = os.environ.get("ARS_WEB_SERVER_PORT", "8765")
    _env_origins = os.environ.get("ARS_CORS_ORIGINS", "").strip()
    if _env_origins == "*":
        _default_origins = "*"
    elif _env_origins:
        _default_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
    else:
        _default_origins = [f"http://127.0.0.1:{_port}", f"http://localhost:{_port}"]
    app.config.update(
        SECRET_KEY=os.environ.get("ARS_SECRET_KEY") or secrets.token_hex(32),
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # 50 MB upload cap
        CORS_ORIGINS=_default_origins,
    )
    if config_overrides:
        app.config.update(config_overrides)

    # ---- Extensions ---------------------------------------------------
    CORS(app, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})

    # flask-socketio is optional — if simple-websocket / eventlet are not
    # present, we still want a working HTTP API.
    socketio = None
    try:
        from flask_socketio import SocketIO

        socketio = SocketIO(
            app,
            cors_allowed_origins=app.config["CORS_ORIGINS"],
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

    # ---- Logging + security headers + errors + root routes ------------
    _register_request_hooks(app)
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
