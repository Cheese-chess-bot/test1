"""One background Jev request at a time; only fresh, relevant results are usable."""
from __future__ import annotations

import copy
import math
import queue
import threading
import time

from .battery import run_battery
from .client import DecisionClientError, JevThrottle, RateLimited


class BackgroundDecisions:
    def __init__(self, client, throttle: JevThrottle, timeout_s: float = 8.0):
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30:
            raise ValueError("Jev request timeout must be between 0 and 30 seconds")
        self.client, self.throttle, self.timeout_s = client, throttle, timeout_s
        self._results = queue.SimpleQueue()
        self._thread = None
        self._closed = threading.Event()
        self.status = "warming up"
        self.last_error = None

    @property
    def pending(self):
        return self._thread is not None and self._thread.is_alive()

    def _request(self, snapshot, sent_at):
        try:
            answers, meta = run_battery(self.client, snapshot, self.timeout_s)
            self._results.put((snapshot, sent_at, answers, meta, None))
        except Exception as exc:
            # Unknown exceptions are not allowed to leak credentials or kill the tick thread.
            error = exc if isinstance(exc, DecisionClientError) else DecisionClientError("Jev request failed")
            self._results.put((snapshot, sent_at, None, {}, error))
        finally:
            if self._closed.is_set():
                self._close_client()

    def _close_client(self):
        close = getattr(self.client, "close", None)
        if close:
            close()

    def poll(self, snapshot, *, now=None, launch=True):
        """Return (answers or None, metadata); never wait for network I/O.

        Age is measured from the source snapshot, never from arrival. A price,
        spread, or inventory change invalidates cached and in-flight results.
        """
        clock = time.monotonic() if now is None else now
        fresh = False
        while not self._results.empty():
            source, sent, answers, meta, error = self._results.get_nowait()
            if error:
                self.last_error = str(error)
                self.status = "rate limited" if isinstance(error, RateLimited) else "unavailable"
                if isinstance(error, RateLimited):
                    self.throttle.rate_limited(clock)
                continue
            self.last_error = None
            self.throttle.success(answers, meta, source, sent)
            fresh = True
        cached = self.throttle.last(clock)
        if cached and self.throttle._material_change(snapshot):
            cached = None
            self.status = "state changed"
        elif not cached and self.throttle.answers is not None:
            self.status = "stale judgment"
        if launch and not self._closed.is_set() and not self.pending:
            reason = self.throttle.due(snapshot, clock)
            if reason is not None:
                self.throttle.called(clock)
                self._thread = threading.Thread(
                    target=self._request, args=(copy.deepcopy(snapshot), clock),
                    name="jev-decision", daemon=True,
                )
                self._thread.start()
        if cached:
            answers, meta = cached
            self.status = "ready" if fresh else "cached"
            return answers, dict(meta, reused=not fresh, status=self.status, pending=self.pending)
        if self.pending and self.status in ("warming up", "ready", "cached"):
            self.status = "waiting for Jev"
        return None, {"route": self.client.name, "model": self.client.model,
                      "status": self.status, "pending": self.pending,
                      "error": self.last_error, "latency_ms": None}

    def wait_for_current(self):
        """Bounded wait for explicit bar-close mode only."""
        if self._thread:
            self._thread.join(timeout=self.timeout_s)

    def close(self):
        self._closed.set()
        if self._thread:
            self._thread.join(timeout=0.1)
        if not self.pending:
            self._close_client()
