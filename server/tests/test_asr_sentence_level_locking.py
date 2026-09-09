"""Sentence-level ASR locking: many sessions, one inference at a time.

Before this change ``/asr/stream`` held the coordinator "asr" slot for the
whole WebSocket, so the session count and the in-flight-inference count were
the same number — 1 on a shared RKNN context. A second capture endpoint was
refused at connect time against an NPU that is idle ~86% of the wall clock.

These tests drive ``server.main._asr_stream_backend`` directly with fake
WS / backend / stream / VAD objects (same style as
``test_asr_backend_endpoint_rearm.py``) and pin down what the change must and
must not do:

- N sessions run concurrently, but their inferences never overlap;
- transcripts never cross between sessions;
- a full backlog produces a ``busy`` frame and the session keeps working;
- the legacy connection-level path is untouched when a backend has not
  opted in.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

import numpy as np
import pytest
from fastapi import WebSocketDisconnect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import server.main as main_mod  # noqa: E402
from server.core import coordinator as coord_mod  # noqa: E402
from server.core.asr_infer_gate import (  # noqa: E402
    init_asr_inference_gate,
    reset_asr_inference_gate,
)
from server.core.capability_resolver import ResolvedCapability  # noqa: E402
from server.core.concurrency_capability import ConcurrencyCapability  # noqa: E402
from server.core.vad import VADSession  # noqa: E402

_SR = 16000
_CHUNK = np.zeros(1600, dtype=np.int16).tobytes()  # 100 ms @16k mono


def _asynctest(fn):
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fn(*args, **kwargs))
        finally:
            loop.close()

    wrapper.__name__ = fn.__name__
    return wrapper


# ── fakes ──────────────────────────────────────────────────────────────


class InferenceProbe:
    """Shared counter that records real overlap across executor threads.

    ``finalize`` runs in a ThreadPoolExecutor, so this deliberately uses a
    threading primitive rather than relying on the event loop to serialise.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.inflight = 0
        self.peak = 0
        self.total = 0

    def enter(self) -> None:
        with self._lock:
            self.inflight += 1
            self.total += 1
            self.peak = max(self.peak, self.inflight)

    def leave(self) -> None:
        with self._lock:
            self.inflight -= 1


class FakeOfflineStream:
    """Accumulate-then-transcribe stream, like ``OfflineAccumulateStream``.

    All "inference" is inside ``finalize``; ``get_partial`` never touches the
    shared runtime. That is exactly the property that makes a backend eligible
    for sentence-level locking.
    """

    def __init__(self, session: str, probe: InferenceProbe, dwell: float):
        self.session = session
        self._probe = probe
        self._dwell = dwell
        self.chunks = 0
        self.closed = False

    def accept_waveform(self, sr: int, samples) -> None:  # noqa: ANN001
        self.chunks += 1

    def get_partial(self):
        return "", False

    def prepare_finalize(self) -> None:
        pass

    def finalize(self):
        self._probe.enter()
        try:
            time.sleep(self._dwell)
            return f"utterance-from-{self.session}", None
        finally:
            self._probe.leave()

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    name = "fake-offline-rk"

    def __init__(self, session: str, probe: InferenceProbe, dwell: float = 0.05):
        self.session = session
        self._probe = probe
        self._dwell = dwell
        self.streams: list[FakeOfflineStream] = []

    def create_stream(self, language: str = "auto"):
        s = FakeOfflineStream(self.session, self._probe, self._dwell)
        self.streams.append(s)
        return s


class FakeWS:
    def __init__(self, messages):
        self._msgs = list(messages)
        self.sent: list[dict] = []

    async def receive(self):
        if self._msgs:
            return self._msgs.pop(0)
        raise WebSocketDisconnect(1000)

    async def send_json(self, payload) -> None:
        self.sent.append(payload)

    async def close(self, code=None, reason=None) -> None:
        pass


class FakeVAD:
    """Fires SPEECH_END every ``every`` chunks."""

    def __init__(self, every: int = 2):
        self.every = every
        self.n = 0
        self.reset_calls = 0

    def process(self, samples):  # noqa: ANN001
        self.n += 1
        if self.n % self.every == 0:
            return VADSession.SPEECH_END
        return None

    def reset(self) -> None:
        self.reset_calls += 1


def _finals(ws: FakeWS) -> list[dict]:
    return [p for p in ws.sent if p.get("type") == "final"]


def _busy(ws: FakeWS) -> list[dict]:
    return [p for p in ws.sent if p.get("type") == "busy"]


@pytest.fixture(autouse=True)
def _isolated_runtime():
    """Fresh coordinator + gate per test; restore whatever was there."""
    prev_coord = coord_mod._coordinator
    prev_flag = main_mod._asr_sentence_level_locking
    coord_mod.init_coordinator({"mode": "serialized"}, profile=None)
    yield
    coord_mod._coordinator = prev_coord
    main_mod._asr_sentence_level_locking = prev_flag
    reset_asr_inference_gate()


# ── the point of the change ────────────────────────────────────────────


@_asynctest
async def test_four_sessions_run_concurrently_with_serial_inference():
    """4 connections, 1 inference at a time — the whole reason for the gate."""
    init_asr_inference_gate(concurrency=1, max_waiting=None)
    probe = InferenceProbe()

    async def session(name: str):
        ws = FakeWS([{"bytes": _CHUNK}] * 4)
        backend = FakeBackend(name, probe, dwell=0.03)
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            vad_session=FakeVAD(every=2), per_utterance_slot=True,
        )
        return name, ws

    results = await asyncio.gather(*(session(f"s{i}") for i in range(4)))

    assert probe.peak == 1, (
        f"{probe.peak} inferences overlapped on a single-context backend"
    )
    assert probe.total == 8, f"expected 2 utterances x 4 sessions, got {probe.total}"
    for name, ws in results:
        finals = _finals(ws)
        assert len(finals) == 2, f"{name}: expected 2 finals, got {len(finals)}"
        for f in finals:
            assert f["text"] == f"utterance-from-{name}", (
                f"transcript crossed sessions: {name} received {f['text']!r}"
            )


@_asynctest
async def test_no_crosstalk_when_sessions_have_different_utterance_lengths():
    """A slow session must not have its text delivered to a fast one."""
    init_asr_inference_gate(concurrency=1, max_waiting=None)
    probe = InferenceProbe()

    async def session(name: str, dwell: float, chunks: int):
        ws = FakeWS([{"bytes": _CHUNK}] * chunks)
        backend = FakeBackend(name, probe, dwell=dwell)
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            vad_session=FakeVAD(every=2), per_utterance_slot=True,
        )
        return name, ws

    results = await asyncio.gather(
        session("slow", 0.08, 4),
        session("fast", 0.01, 8),
    )
    assert probe.peak == 1
    for name, ws in results:
        texts = {f["text"] for f in _finals(ws)}
        assert texts == {f"utterance-from-{name}"}, f"{name} saw {texts}"


# ── backpressure ───────────────────────────────────────────────────────


@_asynctest
async def test_full_backlog_emits_busy_and_keeps_the_session_alive():
    """Queue full → drop that utterance, tell the client, keep going.

    max_waiting=0 makes every concurrent utterance past the first one hit the
    backpressure path deterministically, without depending on timing.
    """
    init_asr_inference_gate(concurrency=1, max_waiting=0)
    probe = InferenceProbe()

    async def session(name: str):
        ws = FakeWS([{"bytes": _CHUNK}] * 6)
        backend = FakeBackend(name, probe, dwell=0.05)
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            vad_session=FakeVAD(every=2), per_utterance_slot=True,
        )
        return name, ws

    results = await asyncio.gather(*(session(f"s{i}") for i in range(3)))

    busy_total = sum(len(_busy(ws)) for _, ws in results)
    assert busy_total > 0, "no backpressure signalled with a zero-depth queue"
    for _, ws in results:
        for b in _busy(ws):
            assert b["reason"] == "asr_queue_full"
        # Rejection is not a session kill: every session still produced at
        # least one final across its three endpoints.
        assert len(_finals(ws)) >= 1
    assert probe.peak == 1


@_asynctest
async def test_busy_rearms_the_stream_and_vad():
    """A dropped utterance must leave a usable stream, not a stuck one."""
    init_asr_inference_gate(concurrency=1, max_waiting=0)
    probe = InferenceProbe()
    vads = []

    async def session(name: str):
        ws = FakeWS([{"bytes": _CHUNK}] * 6)
        backend = FakeBackend(name, probe, dwell=0.05)
        vad = FakeVAD(every=2)
        vads.append(vad)
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            vad_session=vad, per_utterance_slot=True,
        )
        return backend, ws

    results = await asyncio.gather(*(session(f"s{i}") for i in range(3)))
    for backend, ws in results:
        n_endpoints = len(_finals(ws)) + len(_busy(ws))
        # Every endpoint — successful or dropped — re-arms a fresh stream, so
        # the stream count is the endpoint count plus the initial one.
        assert len(backend.streams) == n_endpoints + 1
        assert all(s.closed for s in backend.streams[:-1])
    assert all(v.reset_calls == 3 for v in vads)


# ── the untouched legacy path ──────────────────────────────────────────


@_asynctest
async def test_connection_level_path_never_touches_the_gate():
    """Default (opt-out) behaviour must be byte-identical to before."""
    gate = init_asr_inference_gate(concurrency=1, max_waiting=0)
    probe = InferenceProbe()
    ws = FakeWS([{"bytes": _CHUNK}] * 4)
    backend = FakeBackend("legacy", probe, dwell=0.01)

    async with coord_mod.get_coordinator().acquire("asr"):
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            vad_session=FakeVAD(every=2),
        )

    assert len(_finals(ws)) == 2
    assert _busy(ws) == []
    snap = gate.snapshot()
    assert snap["total_acquired"] == 0, "legacy path went through the gate"
    assert snap["total_rejected"] == 0


# ── granularity decision ───────────────────────────────────────────────


def _resolved(asr_cap: ConcurrencyCapability, mode: str = "serialized"):
    return ResolvedCapability(
        session_ceiling=asr_cap.max_concurrent,
        executor_max_workers=1,
        coordinator_mode=mode,  # type: ignore[arg-type]
        ceiling_source="test",
        asr_cap=asr_cap,
        tts_cap=ConcurrencyCapability.default(),
        asr_infer_concurrency=(
            (asr_cap.max_concurrent or 4) if asr_cap.supports_parallel else 1
        ),
        asr_queue_depth=None,
    )


def test_single_session_backend_keeps_connection_level_locking():
    """The untouched majority: max_concurrent=1 → nothing changes."""
    main_mod._set_asr_sentence_level_locking(
        _resolved(ConcurrencyCapability(supports_parallel=False, max_concurrent=1))
    )
    assert main_mod._asr_sentence_level_locking is False


def test_serial_backend_admitting_n_gets_sentence_locking():
    """The contract other backends opt into: parallel=False + max_concurrent=N."""
    main_mod._set_asr_sentence_level_locking(
        _resolved(ConcurrencyCapability(supports_parallel=False, max_concurrent=4))
    )
    assert main_mod._asr_sentence_level_locking is True


def test_serial_backend_with_no_session_cap_gets_sentence_locking():
    main_mod._set_asr_sentence_level_locking(
        _resolved(ConcurrencyCapability(supports_parallel=False, max_concurrent=None))
    )
    assert main_mod._asr_sentence_level_locking is True


def test_parallel_backend_stays_connection_level():
    """Inference is already parallel — a queue would only add latency."""
    main_mod._set_asr_sentence_level_locking(
        _resolved(ConcurrencyCapability(supports_parallel=True, max_concurrent=4))
    )
    assert main_mod._asr_sentence_level_locking is False


def test_exclusive_mode_keeps_connection_level_locking():
    """``exclusive`` is a residency contract — per-sentence would thrash it."""
    main_mod._set_asr_sentence_level_locking(
        _resolved(
            ConcurrencyCapability(supports_parallel=False, max_concurrent=4),
            mode="exclusive",
        )
    )
    assert main_mod._asr_sentence_level_locking is False


# ── codex review follow-ups ────────────────────────────────────────────


@_asynctest
async def test_cancellation_does_not_release_the_slot_under_a_live_worker():
    """run_in_executor cannot cancel a running thread.

    Cancelling the handler must not hand the shared runtime to the next
    session while a worker is still inside the backend. Regression for the
    codex MUST-FIX.
    """
    init_asr_inference_gate(concurrency=1, max_waiting=None)
    probe = InferenceProbe()
    entered = asyncio.Event()

    class SlowStream(FakeOfflineStream):
        def finalize(self):
            self._probe.enter()
            try:
                entered._loop.call_soon_threadsafe(entered.set)
                time.sleep(0.3)
                return f"utterance-from-{self.session}", None
            finally:
                self._probe.leave()

    class SlowBackend(FakeBackend):
        def create_stream(self, language: str = "auto"):
            s = SlowStream(self.session, self._probe, self._dwell)
            self.streams.append(s)
            return s

    entered._loop = asyncio.get_running_loop()

    victim = asyncio.ensure_future(main_mod._asr_stream_backend(
        FakeWS([{"bytes": _CHUNK}] * 6), SlowBackend("victim", probe),
        language="auto", sample_rate=_SR,
        vad_session=FakeVAD(every=2), per_utterance_slot=True,
    ))
    await asyncio.wait_for(entered.wait(), timeout=5.0)
    victim.cancel()
    with pytest.raises(asyncio.CancelledError):
        await victim

    # The cancelled handler must not have returned before the worker left the
    # backend; if it had, the gate would already be free with inflight > 0.
    assert probe.inflight == 0, (
        "slot released while an executor worker was still inside the backend"
    )


@_asynctest
async def test_end_utterance_busy_rearms_the_stream():
    """A rejected explicit end_utterance must not leave its audio behind.

    Without the re-arm the rejected utterance stays in the stream and in the
    speaker buffer, and the next successful final splices two utterances.
    """
    init_asr_inference_gate(concurrency=1, max_waiting=0)
    probe = InferenceProbe()
    eou = {"text": '{"command": "end_utterance"}'}

    async def session(name: str):
        ws = FakeWS([{"bytes": _CHUNK}, eou] * 3)
        backend = FakeBackend(name, probe, dwell=0.05)
        await main_mod._asr_stream_backend(
            ws, backend, language="auto", sample_rate=_SR,
            per_utterance_slot=True,
        )
        return backend, ws

    results = await asyncio.gather(*(session(f"s{i}") for i in range(3)))
    busy_total = sum(len(_busy(ws)) for _, ws in results)
    assert busy_total > 0, "no backpressure on the end_utterance path"
    for backend, ws in results:
        for b in _busy(ws):
            assert b["endpoint"] == "end_utterance"
        # The success path for an explicit end_utterance deliberately keeps
        # its stream (pre-existing behaviour); only the rejection path re-arms.
        assert len(backend.streams) == len(_busy(ws)) + 1, (
            "a rejected end_utterance did not re-arm the stream"
        )
    assert probe.peak == 1


def test_lowered_infer_concurrency_engages_the_gate_on_a_parallel_backend():
    """An operator narrowing in-flight inference must actually get the queue."""
    cap = ConcurrencyCapability(supports_parallel=True, max_concurrent=4)
    resolved = ResolvedCapability(
        session_ceiling=4,
        executor_max_workers=1,
        coordinator_mode="concurrent",
        ceiling_source="test",
        asr_cap=cap,
        tts_cap=ConcurrencyCapability.default(),
        asr_infer_concurrency=1,   # OVS_ASR_INFER_CONCURRENCY=1
        asr_queue_depth=3,
    )
    main_mod._set_asr_sentence_level_locking(resolved)
    assert main_mod._asr_sentence_level_locking is True


def test_uncapped_parallel_backend_still_stays_connection_level():
    main_mod._set_asr_sentence_level_locking(
        _resolved(ConcurrencyCapability(supports_parallel=True, max_concurrent=None))
    )
    assert main_mod._asr_sentence_level_locking is False
