# ASR concurrency ceiling — reComputer J3011 (Jetson Orin Nano 8GB Super)

Zero errors through c=32 on SenseVoice, with p95 breaking down at c=48 — that is
this board's ceiling for that backend. Whisper's admission ceiling is 1
concurrent session, enforced by the installed `voxedge` package itself, not by
board resources.

## SenseVoice (zh)

Corpus: 200 AISHELL-1 zh utterances (Apache-2.0, speaker S0002, train-range
mirror — see `corpus/download_public_corpus.py` docstring), regenerated for
this run so every concurrency level keeps segments >= 3x its worker count
(200 >> 3x48=144). Transport: `/asr/stream` WebSocket, fed at 1.0x real time
in 4 KB chunks, one `is_final` awaited per segment. Latency = audio-end to
`is_final`.

Deployment: image
`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
with `server/` and `configs/` bind-mounted from openvoicestream `main` (this
branch), `pip install voxedge==0.0.13a0 sentencepiece kaldi_native_fbank`
inside the container — the same recipe as
`concurrency-orin-nano-clean.md` (PR #87). Profile `jetson-sensevoice-c64`
(copy of the tracked `jetson-sensevoice` profile with `asr_max_slots` /
`max_concurrent_sessions` raised from 8 to 64) plus
`OVS_MAX_CONCURRENT_SESSIONS=64`, `PYTHONUTF8=1`, `OVS_API_KEYS=testkey123`
(bench run with `--api-key`). Server confirmed at startup:
`SessionLimiter initialized: effective_limit=64` and
`ASR executor: max_workers=64 (source=asr_cap.max_concurrent)`.
`nvpmodel -q` → `MAXN_SUPER` (already pinned, unchanged). All non-ASR
containers (`edge-inspection-assembly-app`, `edge-inspection-assembly-mosquitto`,
the pre-existing `ovs-sv-test`) stopped before the run and restarted after,
`docker ps` reconciled against the pre-test list.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER | GR3D_FREQ peak | RAM peak (used/total) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8  | 200 | 200 | 0 | 139.6 | 246.2  | 0.0316 | 0.0745 | 1.50 | 5.83% | 98% | 2.76/7.62 GB |
| 16 | 200 | 200 | 0 | 146.5 | 225.7  | 0.0335 | 0.0813 | 2.97 | 5.83% | 98% | 2.76/7.62 GB |
| 24 | 200 | 200 | 0 | 152.4 | 280.5  | 0.0350 | 0.0871 | 4.37 | 5.83% | 98% | 2.76/7.62 GB |
| 32 | 200 | 200 | 0 | 167.3 | 292.6  | 0.0374 | 0.0969 | 5.48 | 5.83% | 98% | 2.76/7.62 GB |
| 48 | 200 | 200 | 0 | 768.2 | 2931.6 | 0.1733 | 0.7097 | 6.44 | 5.83% | 98% | 2.76/7.62 GB |

GR3D_FREQ and RAM figures are the peaks observed in `orin-nano-ceiling-tegrastats.log`
/ periodic `free -m` samples across the whole sweep, not per-level; swap stayed
flat at ~408 MB used out of 3.81 GB the entire run (no swap pressure at any
level).

Zero errors through every level tested, including c=48. p95 stays in a
150-300 ms band through c=32, then jumps to 2.93 s at c=48 (p50 also jumps,
139->768 ms) — more than 10x the c=8 p95 with no error and no swap growth.
That is the ceiling for this board and backend: requests still complete
correctly, but queueing delay (single serialized TensorRT execution context)
dominates once concurrency exceeds ~32. **Recommended admission ceiling: 32**
(p95 <= 1.5 s; 48 exceeds it 2x over). CER is unchanged at 5.83% at every
concurrency level (this corpus/board's offline CER; not comparable to the
5.99% figure in `concurrency-orin-nano-clean.md`, computed on a different
20-segment corpus subset).

## Whisper (en)

Corpus: 20 (c=1) / 200 (c=4) LibriSpeech test-clean en utterances (CC BY 4.0).
Same transport/deployment recipe, profile `orin-whisper-c64` (copy of the
tracked `orin-whisper` profile with `asr_max_slots`/`max_concurrent_sessions`
raised from 8 to 64), `OVS_MAX_CONCURRENT_SESSIONS=64`.

Server startup log: `whisper.tensorrt: admission ceiling 64 requested but
this voxedge build has no max_concurrent field on WhisperASRConfig — staying
at 1 slots`, then `session_limiter: OVS_MAX_CONCURRENT_SESSIONS=64 exceeds
backend ceiling (asr=1,tts=inf) -> clamping to 1`, and
`SessionLimiter initialized: effective_limit=1`. This is a property of the
installed `voxedge==0.0.13a0` package (confirmed the sole and latest
available pre-release via `pip index versions voxedge --pre`, which lists
0.0.13a0 down to 0.0.1a0 with nothing newer) — not a profile setting we can
raise, and not board resource exhaustion.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|
| 1 | 20  | 20 | 0   | 500.3 | 738.5 | 0.11 | 3.62% |
| 4 | 200 | 5  | 195 | -     | -     | 0.16 | -     |

At c=1 all 20 segments transcribe correctly (WER 3.62%, matching the
project's known Whisper-base reference figure). At c=4, only the first
session is admitted; the other three are rejected at the WebSocket layer
with `{"error": "too_many_sessions", "current": 1, "limit": 1}` — 195/200
segments fail this way (the 5 that succeed are the sole admitted slot's
share, processed sequentially as earlier callers finish and free the slot).
**This board's real Whisper concurrency ceiling is 1** — c=8/16/24/32 were
not run because the failure mode (a hard admission clamp, confirmed in the
startup log) does not change with more attempted concurrency; running them
would only reproduce the same near-total `too_many_sessions` rejection rate
already shown at c=4, not new information about a resource limit.

## Files

- `concurrency-orin-nano-ceiling.json` — full per-segment results for both
  sections (`sensevoice_zh`, `whisper_en`).
- `orin-nano-ceiling-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  SenseVoice sweep.
