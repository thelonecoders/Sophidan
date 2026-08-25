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

from qtpy.QtCore import Qt, QTimer, Signal
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

logger = logging.getLogger(__name__)

# Provider/model options exposed in the top dropdown.
PROVIDERS: List[str] = ["None", "Ollama (local)", "OpenAI", "Anthropic"]

# Where chat history is persisted on disk (under the app data dir).
HISTORY_DIR_NAME = "data/projects"


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
        bg = "#1e6bb8" if self._role == "user" else "#3a3a3a"
        fg = "#ffffff" if self._role == "user" else "#f0f0f0"
        align = "right" if self._role == "user" else "left"
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
            # anchor with the citation JSON URL-encoded in the href
            payload = json.dumps(cite, ensure_ascii=False)
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
                cite = json.loads(payload)
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
        self._settings: Dict[str, Any] = {
            "temperature": 0.7,
            "max_tokens": 2048,
            "system_prompt": "",
        }
        self._history: List[Dict[str, Any]] = []
        self._streaming_bubble: Optional[ChatBubble] = None
        self._stream_buffer: str = ""

        self._build_ui()
        self._connect_signals()
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
        self.model_combo.addItems(["gpt-4o-mini", "claude-3-5-sonnet", "llama3.1:8b"])
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
        self.send_button.setObjectName("PrimaryButton")
        input_row.addWidget(self.send_button)
        outer.addLayout(input_row)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._on_send)
        self.clear_button.clicked.connect(self._on_clear_history)
        self.settings_button.clicked.connect(self._on_open_settings)

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
        try:
            from pathlib import Path
            root = Path(os.getcwd())
            return str(root / HISTORY_DIR_NAME / project_id / "chat_history.json")
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
            self._append_chunk("Chat engine unavailable — set provider/model in settings.")
            self._finalize_stream()
            return
        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker unavailable: %s", exc)
            Worker = None  # type: ignore

        provider = self.provider_combo.currentText()
        model = self.model_combo.currentText().strip()
        use_rag = self.use_rag.isChecked()
        settings = dict(self._settings)

        def _stream() -> Any:
            return engine.chat(
                messages=list(self._history),
                provider=provider,
                model=model,
                use_rag=use_rag,
                **settings,
            )

        if Worker is None:
            try:
                for chunk in _stream():
                    self._append_chunk(chunk)
                self._finalize_stream()
            except Exception as exc:  # noqa: BLE001
                self._append_chunk(f"\n[error] {exc}")
                self._finalize_stream()
            return

        self._worker = Worker(_stream)
        for sig_name, slot in (
            ("result", self._on_worker_result),
            ("chunk", self._append_chunk),  # if Worker exposes per-chunk signal
            ("error", self._on_worker_error),
            ("finished", lambda *_: self._finalize_stream()),
        ):
            sig = getattr(self._worker, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not connect %s: %s", sig_name, exc)
        try:
            self._worker.start()
        except Exception as exc:  # noqa: BLE001
            logger.error("Chat worker failed to start: %s", exc)
            self._append_chunk(f"[error] {exc}")
            self._finalize_stream()

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                from ai_assistant.chat_engine import ChatEngine
                self._engine = ChatEngine()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChatEngine not available: %s", exc)
                self._engine = None
        return self._engine

    def _on_worker_result(self, result: Any) -> None:
        """Handle a worker's final result (string, dict, or list of chunks)."""
        if isinstance(result, dict):
            content = result.get("content", "")
            citations = result.get("citations", [])
            self._append_chunk(content)
            if citations and self._streaming_bubble is not None:
                # Replace streaming bubble with a finalized one containing citations.
                self._history_layout.removeWidget(self._streaming_bubble)
                self._streaming_bubble.deleteLater()
                self._streaming_bubble = ChatBubble("assistant", content, citations=citations)
                self._history_layout.insertWidget(
                    self._history_layout.count() - 1, self._streaming_bubble
                )
                self._streaming_bubble.cite_clicked.connect(self.cite_clicked.emit)
            self._history.append({"role": "assistant", "content": content,
                                  "citations": citations})
        elif isinstance(result, str):
            self._append_chunk(result)
            self._history.append({"role": "assistant", "content": result})
        elif isinstance(result, list):
            for chunk in result:
                self._append_chunk(chunk)
            joined = "".join(str(c) for c in result)
            self._history.append({"role": "assistant", "content": joined})
        self.save_history()

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
        self._streaming_bubble = None
        self._stream_buffer = ""
        self.save_history()

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
