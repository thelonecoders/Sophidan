"""Academic Research Suite — application entry point.

Supports two modes:

1. **Desktop mode** (default): launches the PyQt5 desktop UI.
2. **Web server mode** (``--web``): starts the local Flask + Socket.IO
   server, exposing the same engine over HTTP.

Heavy modules (PyQt5, MainWindow, the web server) are imported lazily so
that ``--version`` and ``--help`` resolve in well under a second.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import argparse
import logging
import os
import platform
import signal
import sys
import time
from typing import Optional

# === Constants ============================================================

__version__ = "0.1.0"
APP_NAME = "Academic Research Suite"

logger = logging.getLogger("ars.main")


# === Argument parsing =====================================================

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argv list (defaults to ``sys.argv[1:]``).

    Returns:
        Namespace with: web (bool), port (int), theme (str),
        reset_db (bool), version (bool).
    """
    parser = argparse.ArgumentParser(
        prog="academic-research-suite",
        description=f"{APP_NAME} v{__version__} — desktop + web server",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="start the local Flask web server instead of the desktop UI",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="port for the web server (default: 8765)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="host to bind the web server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--theme", choices=("dark", "light"), default="dark",
        help="UI theme (default: dark)",
    )
    parser.add_argument(
        "--reset-db", action="store_true",
        help="wipe the local SQLite database before starting",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="enable Flask debug mode (web only)",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s v{__version__}",
    )
    return parser.parse_args(argv)


# === Startup banner =======================================================

def _log_banner() -> None:
    """Emit a startup banner to the logger (and stdout if a tty)."""
    py_version = sys.version.split()[0]
    qt_version = _detect_qt_version()
    lines = [
        "",
        "=" * 64,
        f"  {APP_NAME}",
        f"  Version:  {__version__}",
        f"  Platform: {platform.system()} {platform.release()} "
        f"({platform.machine()})",
        f"  Python:   {py_version}",
        f"  Qt:       {qt_version}",
        "=" * 64,
    ]
    banner = "\n".join(lines)
    # Logger is the canonical channel; mirror to stdout for interactive use.
    for line in lines:
        logger.info(line)
    if sys.stdout.isatty():
        print(banner, flush=True)


def _detect_qt_version() -> str:
    """Return the installed Qt binding version, or ``n/a``."""
    try:  # pragma: no cover - environment-dependent
        try:
            from qtpy import API_NAME, QT_VERSION  # type: ignore

            return f"{API_NAME} {QT_VERSION}"
        except Exception:
            try:
                from PyQt5.QtCore import QT_VERSION_STR  # type: ignore

                return f"PyQt5 {QT_VERSION_STR}"
            except Exception:
                try:
                    from PySide2.QtCore import __version__ as v  # type: ignore

                    return f"PySide2 {v}"
                except Exception:
                    return "n/a (web-only mode)"
    except Exception:
        return "n/a"


# === Signal handling ======================================================

def _install_signal_handlers() -> None:
    """Install graceful Ctrl+C handling.

    On SIGINT we attempt to close the database connection (if any) and
    exit cleanly. PyQt5 installs its own SIGINT handler that raises
    KeyboardInterrupt, so this is mainly for web mode.
    """

    def _handler(signum, frame):  # noqa: ARG001
        logger.info("Received SIGINT (%d) — shutting down", signum)
        _shutdown()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        # signal() raises if not in the main thread — ignore.
        pass


def _shutdown() -> None:
    """Best-effort cleanup: flush logs, close DB."""
    try:  # pragma: no cover - depends on backend availability
        from web.server import ServerState

        state = ServerState()
        db = state.db
        if db is not None and hasattr(db, "close"):
            db.close()
            logger.info("Database connection closed")
    except Exception as exc:
        logger.warning("Shutdown cleanup failed: %s", exc)
    finally:
        logging.shutdown()


# === Database reset =======================================================

def _reset_database() -> None:
    """Wipe and reinitialise the local SQLite database."""
    logger.warning("Resetting database as requested via --reset-db")
    try:
        from database.connection import DatabaseConnection  # type: ignore

        db = DatabaseConnection()
        if hasattr(db, "reset"):
            db.reset()
            logger.info("Database reset complete")
        else:
            logger.warning("DatabaseConnection has no reset() method")
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not reset database: %s", exc)


# === Web server entry =====================================================

def run_web_server(port: int = 8765, host: str = "127.0.0.1",
                   debug: bool = False) -> None:
    """Start the local Flask + Socket.IO web server.

    Thin wrapper around :func:`web.server.run_server` so that ``main``
    can avoid importing the web subsystem at module import time.

    Args:
        port: TCP port (default 8765).
        host: Bind address (default ``127.0.0.1``).
        debug: Enable Flask debug reloader.
    """
    logger.info("Starting web server on %s:%d (debug=%s)", host, port, debug)
    from web.server import run_server

    run_server(port=port, host=host, debug=debug)


# === Desktop UI entry =====================================================

def run_desktop(theme: str = "dark") -> int:
    """Launch the PyQt5 desktop UI.

    Args:
        theme: ``"dark"`` or ``"light"``.

    Returns:
        Exit code from ``QApplication.exec_()`` (0 on clean exit).
    """
    try:
        from qtpy.QtWidgets import QApplication  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-dependent
        logger.error(
            "No Qt binding available. Install PyQt5 (or PySide2) and "
            "qtpy, or run with --web to use the browser UI. Error: %s", exc,
        )
        print(
            f"Fatal: no Qt binding available ({exc}).\n"
            "Install PyQt5 + qtpy, or run with --web to use the web UI.",
            file=sys.stderr,
        )
        return 1

    from ui.modern_theme import ModernTheme  # type: ignore
    from ui.main_window import MainWindow  # type: ignore
    from ui.welcome_screen import WelcomeScreen  # type: ignore

    app = QApplication.instance() or QApplication(sys.argv)
    ModernTheme.apply(app, theme=theme)

    window = MainWindow()
    window.show()

    # Show the welcome screen on first launch (when no DB exists yet).
    try:
        from utils.config_manager import ConfigManager  # type: ignore

        cfg = ConfigManager()
        if not cfg.get_setting("first_run_completed", False):
            welcome = WelcomeScreen()
            welcome.exec_()
            cfg.set_setting("first_run_completed", True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Welcome screen skipped: %s", exc)

    return app.exec()


# === Main =================================================================

def main(argv: Optional[list[str]] = None) -> int:
    """Entry point: parse args, dispatch to desktop or web mode.

    Args:
        argv: Optional argv list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    # Configure logging before anything else so subsequent imports log.
    logging.basicConfig(
        level=os.environ.get("ARS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = parse_args(argv)
    _log_banner()
    _install_signal_handlers()

    if args.reset_db:
        _reset_database()

    if args.web:
        try:
            run_web_server(port=args.port, host=args.host, debug=args.debug)
            return 0
        except KeyboardInterrupt:
            logger.info("Web server interrupted by user")
            _shutdown()
            return 0
        except Exception as exc:
            logger.exception("Web server crashed: %s", exc)
            return 1

    # Desktop mode.
    try:
        return run_desktop(theme=args.theme)
    except KeyboardInterrupt:
        logger.info("Desktop interrupted by user")
        _shutdown()
        return 0
    except Exception as exc:
        logger.exception("Desktop crashed: %s", exc)
        return 1
    finally:
        _shutdown()


if __name__ == "__main__":
    sys.exit(main())
