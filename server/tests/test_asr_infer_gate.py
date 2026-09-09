"""Unit tests for the bounded FIFO ASR inference gate.

The gate is what lets the session limiter admit N connections while a single
shared RKNN context still runs exactly one inference at a time. Its three
load-bearing properties are tested here:

1. it never lets more than ``concurrency`` holders in at once;
2. waiters are granted in strict FIFO order (no starvation of an early
   connection by a chatty later one);
3. the backlog is bounded — a full queue rejects rather than growing.

Plus cancellation safety, because a WebSocket client disconnecting while its
utterance is queued is the normal case, not an edge case: a leaked permit
there would wedge ASR for the whole process.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.core.asr_infer_gate import (  # noqa: E402
    AsrInferenceGate,
    InferenceQueueFull,
    get_asr_inference_gate,
    init_asr_inference_gate,
    reset_asr_inference_gate,
)


def _asynctest(fn):
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fn(*args, **kwargs))
        finally:
            loop.close()

    wrapper.__name__ = fn.__name__
    return wrapper


# ── mutual exclusion ───────────────────────────────────────────────────


@_asynctest
async def test_concurrency_one_never_overlaps():
    gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    inflight = 0
    peak = 0

    async def worker():
        nonlocal inflight, peak
        async with gate.acquire():
            inflight += 1
            peak = max(peak, inflight)
            # Yield control so a second task would interleave if it could.
            await asyncio.sleep(0.01)
            inflight -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert peak == 1, f"gate let {peak} inferences overlap on a 1-slot runtime"
    assert gate.running == 0
    assert gate.waiting == 0


@_asynctest
async def test_concurrency_n_allows_exactly_n():
    gate = AsrInferenceGate(concurrency=3, max_waiting=None)
    inflight = 0
    peak = 0

    async def worker():
        nonlocal inflight, peak
        async with gate.acquire():
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.01)
            inflight -= 1

    await asyncio.gather(*(worker() for _ in range(12)))
    assert peak == 3
    assert gate.running == 0


# ── FIFO ordering ──────────────────────────────────────────────────────


@_asynctest
async def test_waiters_are_served_fifo():
    """Arrival order is service order — an early session is never starved."""
    gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    order: list[int] = []
    started = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await asyncio.sleep(0.05)

    async def waiter(i: int):
        async with gate.acquire():
            order.append(i)

    h = asyncio.ensure_future(holder())
    await started.wait()

    tasks = []
    for i in range(5):
        tasks.append(asyncio.ensure_future(waiter(i)))
        # One event-loop turn between spawns so enqueue order is deterministic.
        await asyncio.sleep(0)

    await asyncio.gather(h, *tasks)
    assert order == [0, 1, 2, 3, 4], f"non-FIFO service order: {order}"


# ── backpressure ───────────────────────────────────────────────────────


@_asynctest
async def test_full_queue_rejects_instead_of_growing():
    gate = AsrInferenceGate(concurrency=1, max_waiting=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    async def waiter():
        async with gate.acquire():
            pass

    h = asyncio.ensure_future(holder())
    await started.wait()

    parked = [asyncio.ensure_future(waiter()) for _ in range(2)]
    await asyncio.sleep(0)
    assert gate.waiting == 2

    with pytest.raises(InferenceQueueFull) as exc:
        async with gate.acquire():
            pass
    assert exc.value.depth == 2
    assert gate.snapshot()["total_rejected"] == 1

    release.set()
    await asyncio.gather(h, *parked)
    assert gate.running == 0
    assert gate.waiting == 0


@_asynctest
async def test_max_waiting_zero_never_queues():
    gate = AsrInferenceGate(concurrency=1, max_waiting=0)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    h = asyncio.ensure_future(holder())
    await started.wait()
    with pytest.raises(InferenceQueueFull):
        async with gate.acquire():
            pass
    release.set()
    await h


@_asynctest
async def test_rejection_does_not_consume_a_permit():
    """A rejected acquire must leave the gate exactly as it found it."""
    gate = AsrInferenceGate(concurrency=1, max_waiting=0)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    h = asyncio.ensure_future(holder())
    await started.wait()
    for _ in range(3):
        with pytest.raises(InferenceQueueFull):
            async with gate.acquire():
                pass
    release.set()
    await h
    assert gate.running == 0
    # Still fully usable afterwards.
    async with gate.acquire():
        assert gate.running == 1
    assert gate.running == 0


# ── cancellation safety ────────────────────────────────────────────────


@_asynctest
async def test_cancelled_waiter_releases_its_queue_slot():
    """A client that disconnects while queued must not hold a queue slot."""
    gate = AsrInferenceGate(concurrency=1, max_waiting=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    async def waiter():
        async with gate.acquire():
            pass

    h = asyncio.ensure_future(holder())
    await started.wait()

    doomed = asyncio.ensure_future(waiter())
    await asyncio.sleep(0)
    assert gate.waiting == 1

    doomed.cancel()
    with pytest.raises(asyncio.CancelledError):
        await doomed
    assert gate.waiting == 0, "cancelled waiter left a phantom entry in the queue"

    release.set()
    await h
    assert gate.running == 0


@_asynctest
async def test_cancel_in_the_grant_race_window_does_not_leak_the_permit():
    """Cancelled after being handed ownership → the permit passes on.

    The holder releases and hands the permit to waiter A in the same tick that
    A is cancelled. If A swallowed the permit, waiter B would hang forever and
    the process would never run ASR again.
    """
    gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    started = asyncio.Event()
    release = asyncio.Event()
    b_ran = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    async def waiter_a():
        async with gate.acquire():
            pass

    async def waiter_b():
        async with gate.acquire():
            b_ran.set()

    h = asyncio.ensure_future(holder())
    await started.wait()
    a = asyncio.ensure_future(waiter_a())
    await asyncio.sleep(0)
    b = asyncio.ensure_future(waiter_b())
    await asyncio.sleep(0)
    assert gate.waiting == 2

    # Release and cancel A in the same turn: A is granted, then cancelled
    # before it resumes.
    release.set()
    a.cancel()
    await asyncio.gather(h, b, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await a

    await asyncio.wait_for(b_ran.wait(), timeout=1.0)
    assert gate.running == 0
    assert gate.waiting == 0


@_asynctest
async def test_exception_inside_the_slot_releases_it():
    gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    with pytest.raises(ValueError):
        async with gate.acquire():
            raise ValueError("backend blew up mid-inference")
    assert gate.running == 0
    async with gate.acquire():
        pass
    assert gate.running == 0


# ── observability + construction ───────────────────────────────────────


@_asynctest
async def test_snapshot_reports_wait_time_and_queue_high_water():
    gate = AsrInferenceGate(concurrency=1, max_waiting=None)
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.acquire():
            started.set()
            await release.wait()

    async def waiter():
        async with gate.acquire() as waited:
            assert waited > 0, "queued acquire reported zero wait"

    h = asyncio.ensure_future(holder())
    await started.wait()
    w = [asyncio.ensure_future(waiter()) for _ in range(3)]
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(h, *w)

    snap = gate.snapshot()
    assert snap["max_observed_queue"] == 3
    assert snap["max_observed_wait_s"] > 0
    assert snap["total_acquired"] == 4
    assert snap["total_rejected"] == 0


@_asynctest
async def test_uncontended_acquire_reports_zero_wait():
    """The single-session path must not be slowed or mislabelled as queued."""
    gate = AsrInferenceGate(concurrency=1, max_waiting=4)
    async with gate.acquire() as waited:
        assert waited == 0.0 or waited < 1e-3
    assert gate.snapshot()["max_observed_wait_s"] == 0.0


def test_invalid_construction_rejected():
    with pytest.raises(ValueError):
        AsrInferenceGate(concurrency=0)
    with pytest.raises(ValueError):
        AsrInferenceGate(concurrency=1, max_waiting=-1)


def test_singleton_defaults_to_serial_then_honours_init():
    reset_asr_inference_gate()
    try:
        default = get_asr_inference_gate()
        assert default.concurrency == 1
        assert get_asr_inference_gate() is default
        built = init_asr_inference_gate(concurrency=2, max_waiting=5)
        assert get_asr_inference_gate() is built
        assert (built.concurrency, built.max_waiting) == (2, 5)
    finally:
        reset_asr_inference_gate()
