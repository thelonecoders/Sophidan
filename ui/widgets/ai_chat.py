"""AI chat widget with streaming responses, RAG toggle, and inline citation cards.

Provides :class:`AIChatWidget` — a chat interface backed by
``ai_assistant.chat_engine.ChatEngine`` (lazy import). Supports provider/model
selection (Ollama / OpenAI / Anthropic / None), temperature / max_tokens /
system-prompt overrides, multi-line input, streaming token display, "Use RAG"
checkbox, Clear History button, and clickable paper-citation cards embedded
inline in AI messages. Conversation history is persisted to
``data/projects/{project_id}/chat_history.json``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QFont, QTextCursor
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.modern_theme import ModernTheme

logger = logging.getLogger(__name__)

# Provider/model options exposed in the top dropdown.
PROVIDERS: List[str] = ["None", "Ollama (local)", "OpenAI", "Anthropic"]

# Where chat history is persisted on disk (under the app data dir).
HISTORY_DIR_NAME = "data/projects"


def _citation_from_source(source: Any, index: int) -> Dict[str, Any]:
    """Convert a RAG source (Paper/dict) into a citation-card dict."""
    if isinstance(source, dict):
        return {"id": source.get("id", str(index)),
                "title": source.get("title", "(untitled)"),
                "doi": source.get("doi", "")}
    return {"id": str(index),
            "title": str(getattr(source, "title", "(untitled)")),
            "doi": str(getattr(source, "doi", "") or "")}


# ----------------------------------------------------------------- Bubble
class ChatBubble(QTextBrowser):
    """A single chat message bubble (user-right blue / AI-left gray)."""

    cite_clicked = Signal(dict)

    def __init__(self, role: str, text: str, citations: Optional[List[Dict[str, Any]]] = None,
                 parent: Optional[QWidget] = None) -> None:
        """Build a message bubble.

        Args:
            role: "user" or "assistant".
            text: Message body (HTML supported).
            citations: Optional list of paper-citation dicts to embed inline.
        """
        super().__init__(parent)
        self._role = role
        self._citations = citations or []
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setMinimumHeight(40)
        self.setHtml(self._render_html(text))
        self.document().adjustSize()
        self._adjust_height()
        self.anchorClicked.connect(self._on_anchor)

    def _render_html(self, text: str) -> str:
        user_bubble = self._role == "user"
        if user_bubble:
            bg, fg = ModernTheme.ACCENT, "#ffffff"
        else:
            # Neutral translucent bubble that reads well on both themes.
            bg, fg = "rgba(128,128,128,0.22)", "inherit"
        align = "right" if user_bubble else "left"
        safe_text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace("\n", "<br/>"))
        parts = [
            f"<div style='background:{bg}; color:{fg}; "
            f"border-radius:8px; padding:8px 10px; text-align:{align};'>"
            f"{safe_text}"
        ]
        for i, cite in enumerate(self._citations, start=1):
            title = cite.get("title", "(untitled)")
            cite_id = cite.get("id", str(i))
            # anchor with the citation JSON percent-encoded in the href
            payload = quote(json.dumps(cite, ensure_ascii=False), safe="")
            href = f"cite://{payload}"
            parts.append(
                f"<div style='margin-top:6px; background:rgba(255,255,255,0.12); "
                f"border-radius:4px; padding:4px 6px; text-align:left;'>"
                f"<a href='{href}' style='color:#9fd8ff;'>[{i}] {title}</a>"
                f"</div>"
            )
        parts.append("</div>")
        return "".join(parts)

    def _adjust_height(self) -> None:
        doc_height = self.document().size().height()
        self.setFixedHeight(int(doc_height) + 16)

    def _on_anchor(self, url: Any) -> None:
        spec = url.toString() if hasattr(url, "toString") else str(url)
        if spec.startswith("cite://"):
            try:
                payload = spec[len("cite://"):]
                # The payload was percent-encoded on write; decode here.
                cite = json.loads(unquote(payload))
                self.cite_clicked.emit(cite)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse citation anchor: %s", exc)


# --------------------------------------------------------- Settings dialog
class ChatSettingsDialog(QDialog):
    """Modal dialog for chat settings: temperature, max_tokens, system prompt."""

    def __init__(self, settings: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        """Initialize with current settings dict (mutated on accept)."""
        super().__init__(parent)
        self.setWindowTitle("Chat Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._settings = dict(settings)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        self.temperature.setValue(float(self._settings.get("temperature", 0.7)))
        form.addRow("Temperature:", self.temperature)

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(64, 32768)
        self.max_tokens.setSingleStep(64)
        self.max_tokens.setValue(int(self._settings.get("max_tokens", 2048)))
        form.addRow("Max tokens:", self.max_tokens)

        self.system_prompt = QPlainTextEdit()
        self.system_prompt.setPlainText(self._settings.get("system_prompt", ""))
        self.system_prompt.setMaximumHeight(120)
        form.addRow("System prompt:", self.system_prompt)

        layout.addLayout(form)

        btns = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._on_accept)
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

    def _on_accept(self) -> None:
        self._settings["temperature"] = self.temperature.value()
        self._settings["max_tokens"] = self.max_tokens.value()
        self._settings["system_prompt"] = self.system_prompt.toPlainText().strip()
        self.accept()

    def settings(self) -> Dict[str, Any]:
        """Return the (possibly mutated) settings dict."""
        return self._settings


# ------------------------------------------------------------- Main widget
class AIChatWidget(QWidget):
    """AI chat interface widget with streaming responses and citation cards.

    Persists conversation history to
    ``data/projects/{project_id}/chat_history.json`` and uses
    ``ai_assistant.chat_engine.ChatEngine`` (lazy import).
    """

    cite_clicked = Signal(dict)

    def __init__(self, project_id: Optional[str] = None,
                 parent: Optional[QWidget] = None) -> None:
        """Initialize the chat widget bound to ``project_id`` (optional)."""
        super().__init__(parent)
        self._project_id = project_id
        self._engine: Optional[Any] = None
        self._worker: Optional[Any] = None
        self._should_cancel: bool = False
        self._settings: Dict[str, Any] = {
            "temperature": 0.7,
            "max_tokens": 2048,
            "system_prompt": "",
        }
        self._history: List[Dict[str, Any]] = []
        self._streaming_bubble: Optional[ChatBubble] = None
        self._stream_buffer: str = ""
        self._ready: bool = False  # guards provider/model persistence at boot

        self._build_ui()
        self._connect_signals()
        self._ready = True
        if project_id is not None:
            self.load_history(project_id)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Top bar: provider / model / settings
        top = QHBoxLayout()
        top.addWidget(QLabel("Provider:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(PROVIDERS)
        self.provider_combo.setCurrentIndex(0)
        top.addWidget(self.provider_combo)

        top.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(["gpt-4o-mini", "claude-sonnet-5-5", "claude-3-5-sonnet", "llama3.1:8b"])
        top.addWidget(self.model_combo, stretch=1)

        self.settings_button = QPushButton("Settings…")
        top.addWidget(self.settings_button)

        self.use_rag = QCheckBox("Use RAG")
        self.use_rag.setChecked(False)
        top.addWidget(self.use_rag)

        self.clear_button = QPushButton("Clear History")
        top.addWidget(self.clear_button)
        outer.addLayout(top)

        # Center: chat history scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._history_container = QWidget()
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(8, 8, 8, 8)
        self._history_layout.setSpacing(8)
        self._history_layout.addStretch()
        self.scroll_area.setWidget(self._history_container)
        outer.addWidget(self.scroll_area, stretch=1)

        # Bottom: input row
        input_row = QHBoxLayout()
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Type your message… (Ctrl+Enter to send)")
        self.input_edit.setMaximumHeight(80)
        self.input_edit.keyPressEvent = self._input_key_press  # type: ignore[assignment]
        input_row.addWidget(self.input_edit, stretch=1)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("PrimaryBtn")
        input_row.addWidget(self.send_button)
        outer.addLayout(input_row)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._on_send)
        self.clear_button.clicked.connect(self._on_clear_history)
        self.settings_button.clicked.connect(self._on_open_settings)
        # Changing provider/model persists the choice and rebuilds the
        # engine lazily on the next send (LLMClient reads flat settings).
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)

    def _on_provider_changed(self, provider: str) -> None:
        """Persist the provider choice and invalidate the engine."""
        if not self._ready:
            return
        key = {"OpenAI": "openai", "Anthropic": "anthropic",
               "Ollama (local)": "ollama", "None": "none"}.get(provider)
        if key is None:
            return
        try:
            from utils.config_manager import ConfigManager
            ConfigManager().set("ai_provider", key, persist=True)
        except Exception:  # noqa: BLE001
            logger.debug("Could not persist ai_provider.", exc_info=True)
        self._engine = None

    def _on_model_changed(self, model: str) -> None:
        """Persist the model choice and invalidate the engine."""
        model = (model or "").strip()
        if not model or not self._ready:
            return
        try:
            from utils.config_manager import ConfigManager
            ConfigManager().set("ai_model", model, persist=True)
        except Exception:  # noqa: BLE001
            logger.debug("Could not persist ai_model.", exc_info=True)
        self._engine = None

    # ------------------------------------------------------- Input handling

    def _input_key_press(self, event: Any) -> None:
        from qtpy.QtCore import QEvent
        from qtpy.QtGui import QKeyEvent
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._on_send()
            return
        QPlainTextEdit.keyPressEvent(self.input_edit, event)

    # --------------------------------------------------------- Public slots

    def set_project(self, project_id: Optional[str]) -> None:
        """Bind the widget to a different project and load its history."""
        self._project_id = project_id
        if project_id is not None:
            self.load_history(project_id)

    def load_history(self, project_id: str) -> None:
        """Load chat history from ``data/projects/{project_id}/chat_history.json``."""
        path = self._history_path(project_id)
        if path is None or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self._history = json.load(fh)
            self._render_history()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load chat history %s: %s", path, exc)

    def save_history(self) -> None:
        """Persist the in-memory chat history to disk."""
        if self._project_id is None:
            return
        path = self._history_path(self._project_id)
        if path is None:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._history, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save chat history %s: %s", path, exc)

    def _history_path(self, project_id: str) -> Optional[str]:
        """Build the chat-history path under the configured projects dir."""
        try:
            from pathlib import Path
            try:
                from config.settings import get_settings
                root = get_settings().resolve_path("projects_dir")
            except Exception:  # noqa: BLE001 — settings optional
                root = Path(os.getcwd()) / HISTORY_DIR_NAME
            return str(Path(root) / project_id / "chat_history.json")
        except Exception:  # noqa: BLE001
            return None

    # --------------------------------------------------------- Send message

    def _on_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self._append_message("user", text)
        self._history.append({"role": "user", "content": text})
        self.save_history()

        # Build the assistant bubble in streaming mode.
        self._stream_buffer = ""
        self._streaming_bubble = ChatBubble("assistant", "", citations=[])
        self._history_layout.insertWidget(
            self._history_layout.count() - 1, self._streaming_bubble
        )
        self._streaming_bubble.cite_clicked.connect(self.cite_clicked.emit)

        # Get engine, dispatch.
        engine = self._get_engine()
        if engine is None:
            self._append_chunk(
                "Chat engine unavailable — set provider/model in settings.")
            self._finalize_stream()
            return
        from utils.workers import Worker, WorkerPool

        use_rag = self.use_rag.isChecked()

        def _stream(progress_callback=None, **_ignored: Any) -> Any:
            """Run the chat request on a pool thread.

            Streams via ``engine.send_streaming`` when available — each
            chunk is forwarded through the injected progress callback
            (the Worker's only cross-thread channel).  Falls back to the
            blocking ``engine.send`` and returns the full response.
            """
            report = progress_callback or (lambda pct, msg="": None)
            try:
                stream_fn = getattr(engine, "send_streaming", None)
                if callable(stream_fn):
                    parts: List[str] = []
                    try:
                        # Real signature: send_streaming(text, use_rag=…).
                        gen = stream_fn(text, use_rag=use_rag)
                    except TypeError:
                        gen = stream_fn(text)
                    for chunk in gen:
                        if self._should_cancel:
                            break
                        piece = chunk if isinstance(chunk, str) \
                            else str(getattr(chunk, "content", chunk))
                        parts.append(piece)
                        report(0, piece)  # message carries the streamed chunk
                    return "".join(parts)
                # Fallback: blocking send → ChatResponse.
                response = engine.send(text)
                content = getattr(response, "content", str(response))
                sources = getattr(response, "sources", []) or []
                return {"content": content,
                        "citations": [_citation_from_source(s, i)
                                      for i, s in enumerate(sources, start=1)]}
            except Exception as exc:  # noqa: BLE001
                logger.exception("Chat request failed.")
                raise

        self._should_cancel = False
        self._worker = Worker(_stream)
        self._worker.signals.progress.connect(self._on_worker_chunk)
        self._worker.signals.result.connect(self._on_worker_result)
        self._worker.signals.error.connect(self._on_worker_error)
        self._worker.signals.finished.connect(
            lambda: setattr(self, "_worker_running", False))
        self._worker_running = True
        WorkerPool.instance().submit(self._worker)

    def _get_engine(self) -> Any:
        """Build the ChatEngine lazily.

        Per the engine contract, ``ChatEngine()`` is no-arg constructible
        and auto-builds its ``LLMClient`` from the flat settings fields
        (ai_provider / ai_model / ai_api_key / …).  A defensive fallback
        builds an explicit ``LLMClient`` for pre-contract builds.
        """
        if self._engine is None:
            try:
                from ai_assistant.chat_engine import ChatEngine
                self._engine = ChatEngine()
            except TypeError:
                try:
                    from ai_assistant.chat_engine import ChatEngine
                    from ai_assistant.llm_client import LLMClient
                    self._engine = ChatEngine(LLMClient())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ChatEngine not available: %s", exc)
                    self._engine = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChatEngine not available: %s", exc)
                self._engine = None
        return self._engine

    def _on_worker_chunk(self, _percent: int, message: str) -> None:
        """Streamed chunks arrive via the worker's progress channel."""
        if message:
            self._append_chunk(message)

    def _on_worker_result(self, result: Any) -> None:
        """Handle the worker's final result (str, dict, or list of chunks)."""
        if isinstance(result, dict):
            content = str(result.get("content", ""))
            citations = list(result.get("citations", []) or [])
            self._replace_streaming_bubble(content, citations)
            self._history.append({"role": "assistant", "content": content,
                                  "citations": citations})
        elif isinstance(result, str):
            # Streaming path: chunks were already appended incrementally;
            # only commit if nothing streamed (empty generator).
            if result and not self._stream_buffer:
                self._append_chunk(result)
            self._history.append({"role": "assistant",
                                  "content": self._stream_buffer or result})
        elif isinstance(result, list):
            for chunk in result:
                self._append_chunk(chunk)
            self._history.append({"role": "assistant",
                                  "content": self._stream_buffer})
        self.save_history()

    def _replace_streaming_bubble(self, content: str,
                                  citations: List[Dict[str, Any]]) -> None:
        """Re-render the streaming bubble as a finalized message."""
        if self._streaming_bubble is not None:
            self._history_layout.removeWidget(self._streaming_bubble)
            self._streaming_bubble.deleteLater()
            self._streaming_bubble = None
        self._stream_buffer = ""
        bubble = ChatBubble("assistant", content, citations=citations)
        self._history_layout.insertWidget(
            self._history_layout.count() - 1, bubble
        )
        bubble.cite_clicked.connect(self.cite_clicked.emit)

    def _on_worker_error(self, err: Any) -> None:
        self._append_chunk(f"\n[error] {err}")
        self._finalize_stream()

    # --------------------------------------------------------- Streaming UI

    def _append_chunk(self, chunk: Any) -> None:
        if chunk is None:
            return
        self._stream_buffer += str(chunk)
        if self._streaming_bubble is None:
            self._streaming_bubble = ChatBubble("assistant", "")
            self._history_layout.insertWidget(
                self._history_layout.count() - 1, self._streaming_bubble
            )
            self._streaming_bubble.cite_clicked.connect(self.cite_clicked.emit)
        # Update bubble content
        self._streaming_bubble.setHtml(
            self._streaming_bubble._render_html(self._stream_buffer)  # type: ignore[attr-defined]
        )
        self._streaming_bubble._adjust_height()  # type: ignore[attr-defined]
        # Auto-scroll to bottom
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _finalize_stream(self) -> None:
        self._worker = None
        self._worker_running = False
        self._streaming_bubble = None
        self._stream_buffer = ""
        self.save_history()

    def shutdown(self) -> None:
        """Stop the background chat worker (called by MainWindow on close).

        The pool thread cannot be killed mid-call; we raise the
        cooperative cancel flag which the streaming loop checks between
        chunks, then drop the reference so the UI cannot queue a new
        request while the app is shutting down.
        """
        self._should_cancel = True
        if getattr(self, "_worker_running", False):
            logger.debug("Chat worker still running — cancellation flagged.")
        self._worker = None

    # --------------------------------------------------------- Misc actions

    def _on_clear_history(self) -> None:
        if not self._history:
            return
        confirm = QMessageBox.question(
            self, "Clear History",
            "Clear all chat history for this project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._history.clear()
        self.save_history()
        self._render_history()

    def _on_open_settings(self) -> None:
        dlg = ChatSettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.settings()
            # Persist generation parameters (flat settings fields read by
            # LLMClient when the engine is rebuilt).
            try:
                from utils.config_manager import ConfigManager
                cfg = ConfigManager()
                cfg.set("ai_temperature", float(self._settings.get("temperature", 0.7)),
                        persist=True)
                cfg.set("ai_max_tokens", int(self._settings.get("max_tokens", 2048)),
                        persist=True)
                cfg.set("ai_system_prompt", str(self._settings.get("system_prompt", "")),
                        persist=True)
            except Exception:  # noqa: BLE001
                logger.debug("Could not persist chat settings.", exc_info=True)
            self._engine = None  # rebuild with the new settings on next send

    # --------------------------------------------------------- Render history

    def _render_history(self) -> None:
        # Clear existing bubbles
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for msg in self._history:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            citations = msg.get("citations", [])
            bubble = ChatBubble(role, content, citations=citations)
            bubble.cite_clicked.connect(self.cite_clicked.emit)
            self._history_layout.insertWidget(
                self._history_layout.count() - 1, bubble
            )

    def _append_message(self, role: str, text: str,
                        citations: Optional[List[Dict[str, Any]]] = None) -> None:
        """Append a single non-streaming message bubble to the layout."""
        bubble = ChatBubble(role, text, citations=citations)
        bubble.cite_clicked.connect(self.cite_clicked.emit)
        self._history_layout.insertWidget(
            self._history_layout.count() - 1, bubble
        )
