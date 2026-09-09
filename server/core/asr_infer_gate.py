"""Bounded FIFO admission gate for ASR inference.

Why this exists
---------------
Before this module the ``/asr/stream`` handler held the coordinator lock for
the *entire* WebSocket connection (``server/main.py``: ``async with
get_coordinator().acquire("asr")`` around ``_asr_stream_backend``). On a
single-runtime NPU backend (RK SenseVoice: one shared ``RKNNLite`` context)
that made "how many clients may be connected" equal to "how many inferences
may run at once" — both 1. A second capture endpoint was rejected at connect
time even though the NPU was idle 86% of the wall clock (RTF 0.135).

The two numbers are separable. Audio arrival is bursty and mostly silence;
inference only happens at an utterance boundary and takes ~RTF x utterance
length. This gate holds the *inference* concurrency at whatever the backend
can actually sustain (1 for a single shared RKNN context) while the session
limiter admits N connections. Per-utterance work queues here in FIFO order.

Contract
--------
- ``acquire()`` is an async context manager. It serialises the critical
  section to ``concurrency`` simultaneous holders.
- Waiters are granted in strict FIFO order — no starvation of an early
  connection by a chatty later one.
- The wait queue is bounded. When it is full, ``acquire()`` raises
  ``InferenceQueueFull`` instead of growing an unbounded backlog; the caller
  turns that into an application-level "busy" signal. Backpressure is a
  first-class outcome, not an exception path that shouldn't happen.
- Cancellation-safe: a task cancelled while waiting removes itself from the
  queue, and a task cancelled in the race window after it was handed
  ownership passes ownership on rather than leaking a permit.

This gate deliberately does NOT know about backends, profiles or the NPU. It
is a scheduling primitive; the policy (how many, how deep) is resolved by
``server.core.capability_resolver`` and applied by the caller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import AsyncIterator, Deque, Optional

logger = logging.getLogger(__name__)


class InferenceQueueFull(RuntimeError):
    """Raised by :meth:`AsrInferenceGate.acquire` when the backlog is full.

    Carries the queue depth that was exceeded so the caller can report a
    useful reason to the client.
    """

    def __init__(self, depth: int) -> None:
        super().__init__(
            f"ASR inference queue full (max_waiting={depth}); "
            "rejecting rather than queueing unboundedly"
        )
        self.depth = depth


class AsrInferenceGate:
    """FIFO, bounded, cancellation-safe concurrency gate.

    Args:
        concurrency: simultaneous holders of the critical section. ``>= 1``.
            For a single shared RKNN context this is 1 — the whole point of
            the gate is that this stays 1 while sessions go to N.
        max_waiting: how many tasks may be *queued* behind the running ones
            before ``acquire()`` starts rejecting. ``None`` means unbounded
            (not recommended in production: a stuck backend then turns into
            unbounded memory growth). ``0`` means "never queue" — reject the
            moment all permits are taken.
    """

    def __init__(self, concurrency: int = 1, max_waiting: Optional[int] = None) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {concurrency}")
        if max_waiting is not None and max_waiting < 0:
            raise ValueError(f"max_waiting must be >= 0 or None, got {max_waiting}")
        self._concurrency = concurrency
        self._max_waiting = max_waiting
        self._running = 0
        self._waiters: Deque[asyncio.Future] = deque()
        # Observability for the bench harness / /health. Cheap counters only.
        self._total_acquired = 0
        self._total_rejected = 0
        self._max_observed_wait_s = 0.0
        self._max_observed_queue = 0

    # -- introspection ---------------------------------------------------

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def max_waiting(self) -> Optional[int]:
        return self._max_waiting

    @property
    def running(self) -> int:
        return self._running

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    def snapshot(self) -> dict:
        return {
            "concurrency": self._concurrency,
            "max_waiting": self._max_waiting,
            "running": self._running,
            "waiting": len(self._waiters),
            "total_acquired": self._total_acquired,
            "total_rejected": self._total_rejected,
            "max_observed_wait_s": round(self._max_observed_wait_s, 4),
            "max_observed_queue": self._max_observed_queue,
        }

    # -- core ------------------------------------------------------------

    def _wake_next(self) -> None:
        """Hand the freed permit to the oldest live waiter, or release it.

        Ownership transfer, not a re-race: the waiter wakes already holding
        the permit, so a task that is cancelled between the ``set_result``
        and its own resumption must pass the permit on (handled in
        ``acquire``'s cancellation branch).
        """
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_result(True)
                return
        self._running -= 1

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[float]:
        """Enter the critical section, yielding the seconds spent queued.

        The yielded wait time is what the bench harness attributes to
        queueing rather than to compute, so p95 regressions can be split
        into "the NPU got slower" vs "we queued behind someone".
        """
        t0 = time.perf_counter()
        queued = False

        if self._running < self._concurrency:
            self._running += 1
        else:
            if self._max_waiting is not None and len(self._waiters) >= self._max_waiting:
                self._total_rejected += 1
                raise InferenceQueueFull(self._max_waiting)
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters.append(fut)
            queued = True
            self._max_observed_queue = max(self._max_observed_queue, len(self._waiters))
            try:
                await fut
            except asyncio.CancelledError:
                if fut.done() and not fut.cancelled():
                    # We were granted ownership and then cancelled in the
                    # same tick: do not swallow the permit.
                    self._wake_next()
                else:
                    try:
                        self._waiters.remove(fut)
                    except ValueError:
                        pass
                raise

        waited = time.perf_counter() - t0
        if queued:
            self._max_observed_wait_s = max(self._max_observed_wait_s, waited)
        self._total_acquired += 1
        try:
            yield waited
        finally:
            self._wake_next()


# ---------------------------------------------------------------------------
# Process-wide singleton
#
# One gate per process because the thing being protected — the shared RKNN
# context inside the loaded ASR backend — is also per process. Rebuilt only by
# ``init_asr_inference_gate`` at startup (or by tests).
# ---------------------------------------------------------------------------

_gate: Optional[AsrInferenceGate] = None


def init_asr_inference_gate(
    concurrency: int = 1, max_waiting: Optional[int] = None
) -> AsrInferenceGate:
    global _gate
    _gate = AsrInferenceGate(concurrency=concurrency, max_waiting=max_waiting)
    logger.info(
        "ASR inference gate: concurrency=%d max_waiting=%s",
        concurrency,
        "unbounded" if max_waiting is None else max_waiting,
    )
    return _gate


def get_asr_inference_gate() -> AsrInferenceGate:
    """Return the process gate, lazily defaulting to the safe 1-at-a-time."""
    global _gate
    if _gate is None:
        _gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    return _gate


def reset_asr_inference_gate() -> None:
    """Test hook — drop the singleton so the next get() rebuilds it."""
    global _gate
    _gate = None
