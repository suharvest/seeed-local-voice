# ASR concurrency ceiling — reComputer J3011 (Jetson Orin Nano 8GB Super)

Zero errors through c=32 on SenseVoice, with p95 breaking down at c=48 — that is
this board's ceiling for that backend. Whisper's admission ceiling was
previously 1 (the installed `voxedge==0.0.13a0` package had no
`max_concurrent` field on `WhisperASRConfig`); with a wheel built from
`voxedge` `main` (466f3e4, unreleased) the ceiling now follows the profile
and the real bottleneck is a serialized decode queue — recommended ceiling 8,
see the Whisper section below.

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
Only c=32 and c=48 bracket this transition, so the exact breaking point
between them is not established; a serialized single TensorRT execution
context queueing more requests is the plausible mechanism (matching
`jetson-sensevoice`'s documented design — see `execution_policy.mode:
serialized`), but no per-request queue-time breakdown was captured to
confirm that's the whole story. **Recommended admission ceiling: 32** — the
highest tested level whose p95 stays under the 1.5 s bar; this is a
"highest level that passed," not a claim that 32 is this board's exact
hardware ceiling. CER is unchanged at 5.83% at every concurrency level (this
corpus/board's offline CER; not comparable to the 5.99% figure in
`concurrency-orin-nano-clean.md`, computed on a different 20-segment corpus
subset).

## Whisper (en)

**History:** the PyPI package `voxedge==0.0.13a0` has no `max_concurrent`
field on `WhisperASRConfig`, so every prior pass on this board clamped
`effective_limit` to 1 regardless of the profile's requested ceiling (see
`concurrency-orin-nano-clean.md` and the previous revision of this file).
This run replaces PyPI voxedge with a wheel built from `voxedge` `main`
(466f3e4 `feat(asr): configurable admission ceilings for the whisper and
sherpa backends` — merged, not yet released to PyPI), which adds the field
and a matching `_lock`. That removes the artificial clamp; the sweep below
shows what actually gates Whisper concurrency once it is removed: a
serialized decode queue, not board resources exhausted or an error.

Corpus: 200 LibriSpeech test-clean en utterances (CC BY 4.0), round-robined
per level with `--limit` set so every level keeps segments >= 3x its worker
count (e.g. c=24 uses 72). Same transport/deployment recipe as SenseVoice
above: image `v0.9.0-ondemand-20260721c`, `server/`+`configs/` bind-mounted
from openvoicestream `main`, profile `orin-whisper-c64` (`asr_max_slots`/
`max_concurrent_sessions` raised from 8 to 64), `OVS_MAX_CONCURRENT_SESSIONS=64`,
`OVS_API_KEYS=testkey123` (bench run with `--api-key`), `PYTHONUTF8=1`,
`LC_ALL=C.UTF-8`. `pip install <voxedge-main-wheel> sentencepiece
kaldi_native_fbank` replaces the image's stock voxedge inside the container.
The Whisper base encoder `.plan` was already cached on this board from a
prior pass (bf16 TensorRT, confirmed via file timestamp/size, not rebuilt
this run). Server confirmed at startup: `SessionLimiter initialized:
effective_limit=64` and `ASR executor: max_workers=64
(source=asr_cap.max_concurrent)` — both survive a `docker restart` between
every level in the sweep below (checked explicitly after each restart, not
assumed from the first one). All non-ASR containers stopped before the run
and restarted after, `docker ps` reconciled against the pre-test list.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|
| 1  | 20 | 20 | 0 | 595.3  | 1114.6 | 0.084 | 0.11 | 3.62%  |
| 4  | 24 | 24 | 0 | 474.8  | 1119.7 | 0.072 | 0.42 | 4.41%  |
| 8  | 40 | 40 | 0 | 680.7  | 1288.1 | 0.120 | 0.86 | 7.87%  |
| 16 | 64 | 64 | 0 | 1819.3 | 3757.8 | 0.279 | 1.52 | 14.89% |
| 24 | 72 | 72 | 0 | 4098.8 | 7008.6 | 0.708 | 1.82 | 25.92% |

GR3D_FREQ peak 69%, RAM peak 3.03/7.62 GB (`orin-nano-ceiling-tegrastats.log`
whole-sweep peaks, not per-level).

Zero errors at every level tested (c=32 was not run — see below). p95 stays
in a 1.1-1.3 s band through c=8, then more than doubles at c=16 (1.29 s ->
3.76 s, 2.9x) and keeps climbing at c=24 (7.01 s) — the coordinator/executor
serializes Whisper decode behind one CPU KV-cache path
(`execution_policy.mode: concurrent` is declared but the backend still runs
one decode at a time; see `voxedge/backends/whisper/asr.py`), so admission
concurrency above the decode's real throughput turns into queueing, not
parallel work. WER also rises with concurrency (3.62% at c=1 to 25.92% at
c=24) — inspecting the c=24 per-segment transcripts shows genuine
transcription failures under queueing pressure (truncated output, e.g. "Do
you suppose the" for a full-sentence reference; hallucinated continuations
unrelated to the reference), not merely slower-but-correct decoding, so this
is an accuracy boundary as well as a latency one. **Recommended admission
ceiling: 8** — the highest level tested whose p95 stays under the 1.5 s bar
and whose WER (7.87%) has not yet diverged sharply from the c=1 baseline;
c=32 was not run since c=16/c=24 already show the ceiling has been passed by
a wide margin.

## Files

- `concurrency-orin-nano-ceiling.json` — full per-segment results for both
  sections (`sensevoice_zh`, `whisper_en`).
- `orin-nano-ceiling-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  SenseVoice sweep.
