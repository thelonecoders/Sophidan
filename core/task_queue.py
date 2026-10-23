"""Thread-pool task queue with structured futures.

This module exposes:

* :class:`TaskStatus` — enum for the lifecycle of a :class:`Task`.
* :class:`Task` — a dataclass capturing everything the orchestrator/UI needs
  to know about a piece of background work.
* :class:`TaskQueue` — a thin wrapper around
  :class:`concurrent.futures.ThreadPoolExecutor` providing :py:meth:`enqueue`,
  :py:meth:`wait_all`, :py:meth:`cancel`, :py:meth:`results`.

The queue is fully thread-safe and uses only the Python standard library, so
the module imports cleanly in any environment.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import enum
import inspect
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------
class TaskStatus(enum.Enum):
    """Lifecycle states for a :class:`Task`."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """A unit of background work.

    Attributes:
        id: Unique identifier (auto-generated UUID4 hex string).
        name: Human-readable name (used in UI lists).
        callable: The function to execute.
        args: Positional arguments forwarded to ``callable``.
        kwargs: Keyword arguments forwarded to ``callable``.
        status: Current :class:`TaskStatus`.
        progress: Integer 0-100 progress percentage.
        result: Return value once completed.
        error: Exception instance on failure, else ``None``.
        started_at: Epoch seconds when the task started running.
        finished_at: Epoch seconds when the task reached a terminal state.
        future: The underlying :class:`concurrent.futures.Future` (if any).
    """

    name: str
    callable: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    result: Any = None
    error: Optional[BaseException] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    future: Optional[Future] = field(default=None, repr=False)
    cancel_requested: bool = False
    progress_hook: Optional[Callable[[int, str], None]] = field(
        default=None, repr=False, compare=False,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict (for UI / IPC)."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "result": repr(self.result) if self.result is not None else None,
            "error": repr(self.error) if self.error is not None else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------
class TaskQueue:
    """A thread-safe queue backed by a :class:`ThreadPoolExecutor`.

    Example:
        >>> q = TaskQueue(max_workers=4)
        >>> t = q.enqueue("compute", lambda x: x * 2, 21)
        >>> q.wait_all()
        >>> t.result
        42
    """

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize the queue.

        Args:
            max_workers: Maximum number of worker threads.
        """
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ars-task",
        )
        self._lock = threading.RLock()
        self._tasks: Dict[str, Task] = {}

    # ------------------------------------------------------------------ enqueue
    def enqueue(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        task_id: Optional[str] = None,
        progress_hook: Optional[Callable[[int, str], None]] = None,
        **kwargs: Any,
    ) -> Task:
        """Schedule ``fn`` for execution and return the associated :class:`Task`.

        Args:
            name: Human-readable task name.
            fn: The callable to run.
            *args: Positional arguments forwarded to ``fn``.
            task_id: Optional pre-generated id. Callers that need to bind
                callbacks to the task id *before* the executor may start
                the callable (e.g. the orchestrator's progress emitters)
                can supply one to avoid the submit/identify race.
            progress_hook: Optional ``(percent, message)`` callback invoked
                whenever the injected progress callback fires. Bound to the
                task *before* the executor starts it (no race). The runner
                only injects a progress callback when ``fn``'s signature
                accepts one; the hook is then invoked in addition to the
                task's ``progress`` field being updated.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            The :class:`Task` instance (already queued).
        """
        task = Task(
            name=name, callable=fn, args=args, kwargs=kwargs,
            id=task_id or uuid.uuid4().hex,
            progress_hook=progress_hook,
        )
        # Register the task BEFORE submitting it to the executor: otherwise a
        # fast worker thread (or cancel()/get() from another thread) could
        # observe the running/finished task before it appears in ``_tasks``.
        with self._lock:
            self._tasks[task.id] = task
        future = self._executor.submit(self._run, task)
        with self._lock:
            task.future = future
        logger.info("Enqueued task %s (%s)", task.id, task.name)
        return task

    # ------------------------------------------------------------------ runner
    @staticmethod
    def _fn_accepts_progress(fn: Callable[..., Any]) -> bool:
        """Signature-aware check for a ``progress_callback`` parameter."""
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):  # pragma: no cover - C builtins
            return False
        for pname, param in sig.parameters.items():
            if pname in ("progress_callback", "progress") and param.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                return True
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    def _set_progress(self, task: Task, percent: Any, message: Any = "") -> None:
        """Update a task's progress and fire its hook (worker thread)."""
        try:
            pct = max(0, min(100, int(percent)))
        except (TypeError, ValueError):
            return
        with self._lock:
            task.progress = pct
        hook = task.progress_hook
        if hook is not None:
            try:
                hook(pct, str(message or ""))
            except Exception:  # pragma: no cover - defensive
                logger.debug("task progress hook failed", exc_info=True)

    def _run(self, task: Task) -> Any:
        """Internal: actually execute the task and update its lifecycle."""
        with self._lock:
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                logger.info("Task %s (%s) cancelled before start",
                            task.id, task.name)
                return None
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
        kwargs = dict(task.kwargs)
        if ("progress_callback" not in kwargs
                and "progress" not in kwargs
                and self._fn_accepts_progress(task.callable)):
            kwargs["progress_callback"] = (
                lambda pct, msg="": self._set_progress(task, pct, msg)
            )
        try:
            result = task.callable(*task.args, **kwargs)
        except Exception as exc:
            task.error = exc
            task.status = TaskStatus.FAILED
            task.finished_at = time.time()
            logger.error("Task %s (%s) failed: %s", task.id, task.name, exc)
            raise
        else:
            task.result = result
            task.progress = 100
            # Honour the cancel() promise: a task whose cancel() was requested
            # while running is marked CANCELLED once it finishes, not COMPLETED.
            task.status = (
                TaskStatus.CANCELLED if task.cancel_requested
                else TaskStatus.COMPLETED
            )
            task.finished_at = time.time()
            if task.status is TaskStatus.CANCELLED:
                logger.info("Task %s (%s) finished (marked CANCELLED)",
                            task.id, task.name)
            else:
                logger.info("Task %s (%s) completed", task.id, task.name)
            return result

    # ------------------------------------------------------------------ ops
    def cancel(self, task_id: str) -> bool:
        """Attempt to cancel a task.

        Tasks that have not started running yet are cancelled directly; tasks
        that are already running cannot be interrupted but ARE marked as
        ``CANCELLED`` once they finish (implemented via a done-callback and
        the :attr:`Task.cancel_requested` flag, which the runner also checks
        at start-up and completion).

        Args:
            task_id: The :attr:`Task.id` to cancel.

        Returns:
            ``True`` if the task was cancelled before it started running,
            ``False`` otherwise (a cancel *request* on a running task still
            marks it ``CANCELLED`` when it finishes, but returns ``False``).
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                               TaskStatus.CANCELLED):
                return False
            future = task.future
            if future is None:
                # Not yet submitted (or submitted racing) — mark cancelled now.
                task.cancel_requested = True
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return True
            if future.cancel():
                task.cancel_requested = True
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return True
            # Already running — promise: mark CANCELLED once it finishes.
            task.cancel_requested = True

        def _mark_cancelled_on_finish(fut: Future) -> None:
            with self._lock:
                if task.cancel_requested and not fut.cancelled():
                    task.status = TaskStatus.CANCELLED
                    if task.finished_at is None:
                        task.finished_at = time.time()

        try:
            future.add_done_callback(_mark_cancelled_on_finish)
        except Exception:  # pragma: no cover - defensive
            logger.debug("add_done_callback failed for cancel marking",
                         exc_info=True)
        return False

    def wait_all(self, timeout: Optional[float] = None) -> None:
        """Block until every submitted task has reached a terminal state.

        Args:
            timeout: Maximum wait in seconds, or ``None`` for unbounded.
        """
        with self._lock:
            futures = [t.future for t in self._tasks.values() if t.future is not None]
        from concurrent.futures import wait, FIRST_EXCEPTION, ALL_COMPLETED

        wait(futures, timeout=timeout, return_when=ALL_COMPLETED)

    def results(self) -> Dict[str, Any]:
        """Return a mapping ``{task_id: result}`` for completed tasks."""
        with self._lock:
            return {
                tid: t.result
                for tid, t in self._tasks.items()
                if t.status == TaskStatus.COMPLETED
            }

    # ------------------------------------------------------------------ introspection
    def get(self, task_id: str) -> Optional[Task]:
        """Return the :class:`Task` for ``task_id``, or ``None``."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_all(self) -> List[Task]:
        """Return a snapshot list of every task ever submitted."""
        with self._lock:
            return list(self._tasks.values())

    def list_by_status(self, status: TaskStatus) -> List[Task]:
        """Return all tasks in a given status."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == status]

    def list_active(self) -> List[Task]:
        """Return all tasks that are pending or currently running."""
        with self._lock:
            return [
                t
                for t in self._tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

    # ------------------------------------------------------------------ shutdown
    def shutdown(self, wait: bool = True) -> None:
        """Shut down the underlying executor.

        Args:
            wait: If ``True``, block until all running tasks finish.
        """
        try:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:  # pragma: no cover - Python <3.9 fallback
            self._executor.shutdown(wait=wait)


__all__ = ["TaskStatus", "Task", "TaskQueue"]
