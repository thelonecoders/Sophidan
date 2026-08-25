"""AI Assistant subpackage — LLM client, RAG engine, summarizer, chat, prompts.

This package groups all AI-related functionality for the Academic Research
Suite: a unified :class:`LLMClient` (OpenAI / Anthropic / Ollama / offline
echo), curated :class:`PromptTemplates`, a :class:`RAGEngine` over the local
paper corpus, a :class:`PaperSummarizer` that produces structured summaries
and literature reviews, and a :class:`ChatEngine` with Qt-friendly signals and
a lightweight tool-calling layer.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from .llm_client import LLMClient, LLMProvider
from .prompts import PromptTemplates
from .rag_engine import RAGEngine, RAGResponse
from .summarizer import (
    ComparisonTable,
    PaperSummarizer,
    PaperSummary,
    TopicSummary,
)
from .chat_engine import ChatEngine, ChatResponse

__all__ = [
    "LLMClient",
    "LLMProvider",
    "PromptTemplates",
    "RAGEngine",
    "RAGResponse",
    "PaperSummarizer",
    "PaperSummary",
    "TopicSummary",
    "ComparisonTable",
    "ChatEngine",
    "ChatResponse",
]
