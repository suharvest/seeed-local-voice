"""Regression: one segment's text must survive a server final delayed past EOS.

The J4012 Whisper c=24 sweep (results/concurrency-orin-nx-ceiling.md) reported
transcripts that were strict prefixes of the same item's c=1 text. The backend
was not truncating: the server VAD had split the utterance, and under queueing
its mid-utterance final was delivered AFTER the client's EOS frame. The client
stopped at the first is_final it saw and scored that fragment as the whole
segment.

Two things prevent that now and both are asserted here:
  * the URL pins ``vad=none`` unless ``--server-vad`` is asked for, so the
    client is the only endpoint detector (server/main.py "Streaming ASR
    endpointing" — running both detectors is the documented misconfiguration);
  * the post-EOS loop accumulates every final until the stream closes, so a
    delayed one is joined instead of mistaken for the result.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402


class _FakeWS:
    """Replays a scripted server frame sequence, recording the URL used."""

    def __init__(self, frames_before_eos, frames_after_eos, closes=True, gap=0.0):
        self._before = list(frames_before_eos)
        self._after = list(frames_after_eos)
        self._eos_seen = False
        self._closes = closes
        self._gap = gap

    async def send(self, payload):
        if isinstance(payload, (bytes, bytearray)) and len(payload) == 0:
            self._eos_seen = True

    async def recv(self):
        queue = self._after if self._eos_seen else self._before
        if not queue:
            if self._eos_seen:
                if self._closes:
                    raise bench.websockets.ConnectionClosedOK(None, None)
                await asyncio.sleep(3600)  # server never closes: exercise the gap cap
            await asyncio.sleep(3600)  # nothing queued pre-EOS: let the drain time out
        await asyncio.sleep(self._gap)
        return json.dumps(queue.pop(0))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


ITEM = {"id": "en_x", "filename": "x.wav", "lang": "en",
        "duration_s": 3.0, "transcript": "DO YOU SUPPOSE THE MINIATURE WAS A COPY"}


def _run(monkeypatch, frames_before, frames_after, server_vad=False, closes=True, gap=0.0):
    seen = {}

    def fake_connect(url, **kw):
        seen["url"] = url
        return _FakeWS(frames_before, frames_after, closes=closes, gap=gap)

    monkeypatch.setattr(bench, "load_pcm16", lambda p: b"\x00\x00" * 16000)
    monkeypatch.setattr(bench.websockets, "connect", fake_connect)
    res = asyncio.run(bench.run_segment("ws://h:1", ITEM, Path("/nonexistent"),
                                        chunk_bytes=32000, realtime=False,
                                        server_vad=server_vad))
    return res, seen["url"]


def test_pins_vad_none_by_default(monkeypatch):
    res, url = _run(monkeypatch, [], [{"type": "final", "text": "whole sentence",
                                       "is_final": True}])
    assert "vad=none" in url
    assert res.text == "whole sentence"
    assert res.ok


def test_server_vad_flag_leaves_the_server_detector_on(monkeypatch):
    _, url = _run(monkeypatch, [], [{"type": "final", "text": "x", "is_final": True}],
                  server_vad=True)
    assert "vad=none" not in url


def test_final_delayed_past_eos_is_not_mistaken_for_the_whole_segment(monkeypatch):
    """The exact c=24 failure: nothing readable in the 10 ms pre-EOS drain, then
    the server's mid-utterance final arrives after EOS ahead of the real one."""
    after = [
        {"type": "vad_endpoint"},
        {"type": "final", "text": "Do you suppose the", "is_final": True,
         "endpoint": "vad"},
        {"type": "final", "text": "miniature was a copy", "is_final": True},
    ]
    res, _ = _run(monkeypatch, [], after, server_vad=True)
    assert res.text == "Do you suppose the miniature was a copy"
    assert res.ok


def test_pre_eos_and_post_eos_finals_are_both_kept(monkeypatch):
    before = [{"type": "final", "text": "Do you suppose the", "is_final": True,
               "endpoint": "vad"}]
    after = [{"type": "final", "text": "miniature was a copy", "is_final": True}]
    res, _ = _run(monkeypatch, before, after, server_vad=True)
    assert res.pre_eos_finals == 1
    assert res.text == "Do you suppose the miniature was a copy"


def test_zh_finals_join_without_spaces(monkeypatch):
    item = dict(ITEM, lang="zh", transcript="限购")
    seen = {}

    def fake_connect(url, **kw):
        seen["url"] = url
        return _FakeWS([], [{"type": "final", "text": "限", "is_final": True,
                             "endpoint": "vad"},
                            {"type": "final", "text": "购", "is_final": True}])

    monkeypatch.setattr(bench, "load_pcm16", lambda p: b"\x00\x00" * 16000)
    monkeypatch.setattr(bench.websockets, "connect", fake_connect)
    res = asyncio.run(bench.run_segment("ws://h:1", item, Path("/nonexistent"),
                                        chunk_bytes=32000, realtime=False,
                                        server_vad=True))
    assert res.text == "限购"


def test_no_final_at_all_is_reported_as_an_error(monkeypatch):
    res, _ = _run(monkeypatch, [], [])
    assert not res.ok
    assert res.error == "no final message before deadline"


def test_a_vad_final_without_the_eos_final_is_not_scored_as_complete(monkeypatch):
    """The server split the utterance and never got to the EOS final. That is an
    incomplete transcript, not a result: it must not be reported as ok."""
    res, _ = _run(monkeypatch,
                  [], [{"type": "final", "text": "Do you suppose the",
                        "is_final": True, "endpoint": "vad"}],
                  server_vad=True, closes=False)
    assert not res.ok
    assert "incomplete" in (res.error or "")


def test_a_backend_midstream_final_does_not_end_collection(monkeypatch):
    """server/main.py's get_partial is_endpoint path emits a final with no
    ``endpoint`` field. Treating the missing field as "this is the EOS final"
    would drop everything after it."""
    after = [
        {"type": "final", "text": "first half", "is_final": True},
        {"type": "final", "text": "second half", "is_final": True},
    ]
    res, _ = _run(monkeypatch, [], after)
    assert res.text == "first half second half"
    assert res.ok


def test_a_slow_first_final_is_not_cut_off_by_the_gap_cap(monkeypatch):
    """The 5 s gap cap applies only after something has arrived; a decode that
    takes longer than it to produce the first final must still be collected."""
    monkeypatch.setattr(bench, "_IDLE_GAP_S", 0.05)
    res, _ = _run(monkeypatch, [], [{"type": "final", "text": "slow", "is_final": True}],
                  gap=0.2)
    assert res.ok
    assert res.text == "slow"


def test_a_terminal_error_frame_is_not_scored_as_a_result(monkeypatch):
    """server/main.py's error frame carries is_final. Counting it as the
    segment's transcript reports an empty string as a successful run."""
    res, _ = _run(monkeypatch, [], [{"type": "error", "text": "", "is_final": True,
                                     "reason": "backend_unavailable"}])
    assert not res.ok
    assert "server sent error" in (res.error or "")


def test_a_busy_frame_is_not_scored_as_a_result(monkeypatch):
    """busy means the utterance was dropped for backpressure — no transcript."""
    after = [{"type": "busy", "reason": "asr_queue_full", "endpoint": "eos"},
             {"type": "final", "text": "", "is_final": True}]
    res, _ = _run(monkeypatch, [], after, server_vad=True)
    assert not res.ok
    assert "asr_queue_full" in (res.error or "")
