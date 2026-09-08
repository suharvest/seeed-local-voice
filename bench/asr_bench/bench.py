#!/usr/bin/env python3
"""Generalized ASR benchmark for OpenVoiceStream's /asr/stream WebSocket.

Sends each audio segment as a "pseudo-streaming, non-streaming" pass: the
whole segment is fed in fixed-size binary chunks at 1.0x real-time pace (like
a live mic), then an empty binary frame signals end-of-segment, and the
client waits for the `is_final` JSON message. This matches how
docs/perf-test-runbook.md and bench/perf/asr_stream_ws_bench.py already
exercise the service; this script generalizes that single-shot pattern to
N concurrent sessions and reports percentiles + RTF + CER/WER.

Protocol note (fact-checked 2026-09-09): this hits OpenVoiceStream's own
`/asr/stream` WebSocket (JSON keyed by `is_final`, no `type: connection/vad`
envelope). The `ws_api.md` doc referenced in the task describes a DIFFERENT
service (`sensecraft-asr-service`, Go, port 8080, `/ws`, `type:
connection|vad|final|error`) that sits in front of OpenVoiceStream as an app
compatibility shim in the retail_voice compose stack. There is no evidence
that shim exposes per-model timing/CER data any differently than the engine
underneath, and benchmarking model backends (SenseVoice vs Whisper) needs the
engine's own endpoint, not the shim. See docs/reports/retail-voice-asr-bench-matrix-2026-09-09.md
for the full trace (file:line citations for both services).

Usage:
    uv run bench.py --url ws://cat-remote:8621 --model sensevoice --lang zh \
        --segments ../perf/corpus --concurrency 1
    uv run bench.py --url ws://cat-remote:8621 --model sensevoice --lang zh \
        --segments ../perf/corpus --concurrency 1,2,4,8 --out results/rk3576-sensevoice-zh.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets

try:
    import jiwer
except ImportError:  # pragma: no cover
    jiwer = None


# ---------------------------------------------------------------------------
# Corpus loading — reuses bench/perf/corpus/manifest.json's schema, and also
# accepts a flat "segments dir" with a manifest.json of the same shape (see
# bench/asr_bench/corpus/README.md for the AISHELL-1 / LibriSpeech subsets).
# ---------------------------------------------------------------------------

def load_items(segments_dir: Path, lang: str, category: str | None, limit: int | None) -> list[dict]:
    manifest_path = segments_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = [f for f in manifest["files"] if f["lang"] == lang]
    if category:
        items = [f for f in items if f.get("category") == category]
    if limit:
        items = items[:limit]
    if not items:
        raise SystemExit(f"No items for lang={lang} category={category} in {manifest_path}")
    return items


def load_pcm16(path: Path) -> bytes:
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        x_old = np.linspace(0, len(audio) - 1, len(audio))
        x_new = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
        audio = np.interp(x_new, x_old, audio).astype(np.float32)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    return pcm.tobytes()


# ---------------------------------------------------------------------------
# Error rate
# ---------------------------------------------------------------------------

def error_rate(ref: str, hyp: str, lang: str) -> float:
    ref = ref.strip()
    hyp = hyp.strip()
    if not ref:
        return 0.0
    if jiwer is not None:
        if lang == "zh":
            tr = jiwer.Compose([
                jiwer.RemoveWhiteSpace(replace_by_space=""),
                jiwer.RemovePunctuation(),
                jiwer.ReduceToListOfListOfChars(),
            ])
            return jiwer.cer(ref, hyp, reference_transform=tr, hypothesis_transform=tr)
        return jiwer.wer(ref, hyp)
    # naive fallback: character-level edit distance
    a, b = list(ref), list(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(a))


# ---------------------------------------------------------------------------
# One segment, one WS session
# ---------------------------------------------------------------------------

@dataclass
class SegmentResult:
    id: str
    lang: str
    duration_s: float
    feed_wall_ms: float
    eos_to_final_ms: float
    rtf: float
    text: str
    ref: str
    err: float
    ok: bool
    error: str | None = None


async def run_segment(url: str, item: dict, segments_dir: Path, chunk_bytes: int, realtime: bool) -> SegmentResult:
    wav_path = segments_dir / item["filename"]
    pcm = load_pcm16(wav_path)
    duration_s = float(item["duration_s"])
    ref = item.get("eval_transcript") or item["transcript"]
    lang = item["lang"]
    ws_url = f"{url.rstrip('/')}/asr/stream?language=auto&sample_rate=16000"

    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=15) as ws:
            feed_start = time.perf_counter()
            bytes_per_ms = 16000 * 2 / 1000.0  # 16-bit mono @16kHz
            for start in range(0, len(pcm), chunk_bytes):
                chunk = pcm[start:start + chunk_bytes]
                t0 = time.perf_counter()
                await ws.send(chunk)
                if realtime:
                    chunk_ms = len(chunk) / bytes_per_ms
                    elapsed = (time.perf_counter() - t0) * 1000
                    await asyncio.sleep(max(0.0, (chunk_ms - elapsed) / 1000))
            feed_wall_ms = (time.perf_counter() - feed_start) * 1000

            eos_at = time.perf_counter()
            await ws.send(b"")  # empty frame = end-of-segment
            final_msg = None
            deadline = eos_at + 20
            while time.perf_counter() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.perf_counter()))
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if msg.get("is_final"):
                    final_msg = msg
                    break
            eos_to_final_ms = (time.perf_counter() - eos_at) * 1000
            text = (final_msg or {}).get("text", "")
            err = error_rate(ref, text, lang)
            rtf = (eos_to_final_ms / 1000.0) / duration_s if duration_s > 0 else float("nan")
            return SegmentResult(
                id=item["id"], lang=lang, duration_s=duration_s,
                feed_wall_ms=feed_wall_ms, eos_to_final_ms=eos_to_final_ms,
                rtf=rtf, text=text, ref=ref, err=err, ok=final_msg is not None,
                error=None if final_msg is not None else "no final message before deadline",
            )
    except Exception as exc:  # noqa: BLE001 — record and continue, don't crash the run
        return SegmentResult(
            id=item["id"], lang=lang, duration_s=duration_s,
            feed_wall_ms=0.0, eos_to_final_ms=0.0, rtf=float("nan"),
            text="", ref=ref, err=1.0, ok=False, error=str(exc),
        )


# ---------------------------------------------------------------------------
# Concurrency runner: N workers each drain a shared queue of items once.
# ---------------------------------------------------------------------------

async def run_concurrency(url: str, items: list[dict], segments_dir: Path, concurrency: int,
                           chunk_bytes: int, realtime: bool) -> dict:
    queue: asyncio.Queue = asyncio.Queue()
    for it in items:
        queue.put_nowait(it)
    results: list[SegmentResult] = []
    lock = asyncio.Lock()

    async def worker():
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            r = await run_segment(url, item, segments_dir, chunk_bytes, realtime)
            async with lock:
                results.append(r)

    wall_start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    wall_s = time.perf_counter() - wall_start

    ok_results = [r for r in results if r.ok]
    err_count = len(results) - len(ok_results)
    lat = [r.eos_to_final_ms for r in ok_results]
    rtfs = [r.rtf for r in ok_results if r.rtf == r.rtf]  # filter NaN
    errs = [r.err for r in ok_results]

    def pct(values: list[float], p: float) -> float | None:
        if not values:
            return None
        s = sorted(values)
        k = (len(s) - 1) * p
        f, c = int(k), min(int(k) + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)

    total_audio_s = sum(r.duration_s for r in ok_results)
    return {
        "concurrency": concurrency,
        "segments": len(items),
        "ok": len(ok_results),
        "errors": err_count,
        "wall_s": wall_s,
        "throughput_segments_per_s": len(ok_results) / wall_s if wall_s > 0 else None,
        "throughput_audio_rtf_aggregate": total_audio_s / wall_s if wall_s > 0 else None,
        "final_latency_ms_p50": pct(lat, 0.50),
        "final_latency_ms_p95": pct(lat, 0.95),
        "final_latency_ms_mean": statistics.fmean(lat) if lat else None,
        "rtf_p50": pct(rtfs, 0.50),
        "rtf_p95": pct(rtfs, 0.95),
        "error_rate_mean": statistics.fmean(errs) if errs else None,
        "results": [r.__dict__ for r in results],
    }


def to_markdown(model: str, lang: str, url: str, runs: list[dict]) -> str:
    lines = [
        f"# ASR bench: {model} / {lang}",
        "",
        f"- Target: `{url}`",
        f"- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration",
        "",
        "| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        def f(v, nd=1):
            return "-" if v is None else f"{v:.{nd}f}"
        lines.append(
            f"| {r['concurrency']} | {r['segments']} | {r['ok']} | {r['errors']} | "
            f"{f(r['final_latency_ms_p50'])} | {f(r['final_latency_ms_p95'])} | "
            f"{f(r['rtf_p50'],3)} | {f(r['rtf_p95'],3)} | "
            f"{f(r['throughput_segments_per_s'],2)} | {f(r['error_rate_mean'],4)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="ws://host:port (no path) — /asr/stream is appended")
    p.add_argument("--model", required=True, choices=["sensevoice", "whisper"], help="label only, describes which OVS profile is running on --url")
    p.add_argument("--lang", required=True, choices=["zh", "en"])
    p.add_argument("--category", default=None, help="filter manifest 'category' (e.g. short/long); default: all")
    p.add_argument("--segments", required=True, help="dir containing manifest.json + wav files (see corpus/README.md)")
    p.add_argument("--concurrency", default="1", help="comma-separated list, e.g. 1,2,4,8")
    p.add_argument("--limit", type=int, default=None, help="cap segments per concurrency run")
    p.add_argument("--chunk-bytes", type=int, default=4096)
    p.add_argument("--no-realtime", action="store_true", help="send chunks as fast as possible instead of 1.0x real-time pace")
    p.add_argument("--out", default=None, help="write JSON results here; a sibling .md is also written")
    args = p.parse_args()

    segments_dir = Path(args.segments)
    items = load_items(segments_dir, args.lang, args.category, args.limit)
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]

    runs = []
    for c in levels:
        print(f"== concurrency={c} lang={args.lang} model={args.model} segments={len(items)} ==", flush=True)
        run = asyncio.run(run_concurrency(args.url, items, segments_dir, c, args.chunk_bytes, not args.no_realtime))
        print(json.dumps({k: v for k, v in run.items() if k != "results"}, ensure_ascii=False, indent=2), flush=True)
        runs.append(run)

    payload = {
        "url": args.url,
        "model": args.model,
        "lang": args.lang,
        "category": args.category,
        "chunk_bytes": args.chunk_bytes,
        "realtime": not args.no_realtime,
        "runs": runs,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path = out_path.with_suffix(".md")
        md_path.write_text(to_markdown(args.model, args.lang, args.url, runs), encoding="utf-8")
        print(f"wrote {out_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
