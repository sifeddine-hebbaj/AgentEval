"""Trace/span instrumentation primitives.

Uses contextvars so span() calls correctly nest under the current trace
even across threads/async tasks. Flushing NEVER raises into the calling
agent code and NEVER blocks it meaningfully (SRS NFR-AVAIL-2) -- if the
server is unreachable, spans are queued to local disk and retried later.
"""
from __future__ import annotations

import functools
import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agenteval_core.models import Span, SpanType, Trace

if TYPE_CHECKING:
    from agenteval_sdk.client import Client

_current_trace: ContextVar[Trace | None] = ContextVar("_current_trace")
_span_stack: ContextVar[list[str]] = ContextVar("_span_stack")


class _SpanHandle:
    def __init__(self, span: Span, on_close):
        self._span = span
        self._on_close = on_close

    def set_output(self, output: Any) -> None:
        self._span.output = output

    def set_error(self, message: str) -> None:
        self._span.status = "error"
        self._span.error_message = message

    def set_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0, cost: float = 0.0) -> None:
        self._span.prompt_tokens = prompt_tokens
        self._span.completion_tokens = completion_tokens
        self._span.cost = cost


@contextmanager
def span(type: str = "custom", name: str = "", model: str | None = None):
    trace_obj = _current_trace.get()
    if trace_obj is None:
        raise RuntimeError(
            "span() called outside of a trace() context. Wrap your agent entrypoint "
            "with @trace(client=...) first."
        )
    stack = _span_stack.get()
    if stack is None:
        stack = []
        _span_stack.set(stack)
    parent_id = stack[-1] if stack else None

    s = Span(trace_id=trace_obj.id, parent_span_id=parent_id, span_type=SpanType(type), name=name, model_name=model)
    trace_obj.spans.append(s)
    _span_stack.set(stack + [s.id])

    handle = _SpanHandle(s, on_close=None)
    try:
        yield handle
    except Exception as exc:
        s.status = "error"
        s.error_message = f"{exc.__class__.__name__}: {exc}"
        raise
    finally:
        s.ended_at = datetime.now(UTC)
        _span_stack.set(stack)


def trace(client: Client, name: str = ""):
    """Decorator that opens a Trace, runs the wrapped function, and
    flushes the trace to the configured Client (local SQLite or network)
    on exit -- even if the function raised.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            trace_obj = Trace(project_id=getattr(client, "project", None), metadata={"function": name or func.__name__})
            token = _current_trace.set(trace_obj)
            stack_token = _span_stack.set([])
            try:
                result = func(*args, **kwargs)
                trace_obj.status = "ok"
                return result
            except Exception:
                trace_obj.status = "error"
                raise
            finally:
                trace_obj.ended_at = datetime.now(UTC)
                _current_trace.reset(token)
                _span_stack.reset(stack_token)
                client._enqueue_trace(trace_obj)

        return wrapper

    return decorator


class DiskFallbackQueue:
    """Persists traces to a local JSONL file when the server is
    unreachable, so an agent's network blip never loses observability
    data and never blocks the calling code (NFR-AVAIL-2).
    """

    def __init__(self, path: str = ".agenteval/pending_traces.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def push(self, trace_obj: Trace) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(trace_obj.model_dump_json() + "\n")

    def drain(self) -> list[Trace]:
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
            self.path.write_text("", encoding="utf-8")
        return [Trace(**json.loads(line)) for line in lines if line.strip()]
