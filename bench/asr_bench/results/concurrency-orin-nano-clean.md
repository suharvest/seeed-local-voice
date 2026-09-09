# SenseVoice ASR concurrency, clean repro — reComputer J3011 (Jetson Orin Nano 8GB Super)

Corpus: 20 AISHELL-1 zh utterances (Apache-2.0), 115.0 s of audio total.
Transport: `/asr/stream` WebSocket, fed at 1.0x real time in 4 KB chunks, one
`is_final` awaited per segment. Latency below is end-of-audio to `is_final`.

## Why this run exists

`concurrency-orin-nano.md` (previous pass) recorded p50/p95 of 136/311 ms at
c=1 and 3389/8885 ms at c=8 on this same board, with `tegrastats` showing
GR3D_FREQ peaking at only 31% during the c=8 run — the GPU was not saturated,
so the bottleneck was not raw GPU throughput. The question was whether other
containers on the board (`edge-inspection-assembly-app`,
`edge-inspection-assembly-mosquitto`, plus a long-lived ad hoc test container
`ovs-sv-test`) were stealing CPU/GPU cycles from the bench.

**Root cause found: no.** `docker stats --no-stream` with the board idle
shows `edge-inspection-assembly-app` at 12.75% CPU (one of six cores) and
`edge-inspection-assembly-mosquitto` at 0.05% — negligible, and neither
touches the GPU. `nvpmodel -q` was already `MAXN_SUPER` and
`jetson_clocks --show` already reported CPU and GPU pinned to their maxima
(CPU 1728 MHz all six cores, GPU 1020 MHz) — the board was not power-throttled
either.

The actual cause: the container that produced the bad numbers
(`ovs-sv-test`) was running **voxedge 0.0.8a0**. Isolating it — every other
container stopped, `ovs-sv-test` alone on the board, same profile
(`asr_max_slots=8`, `execution_policy.mode=serialized`), same c=8 bench —
reproduced degenerate latency: p50 1091 ms / p95 3494 ms (see
`concurrency-orin-nano-isolate-c8-oldvoxedge.json` in this directory). Zero
other containers were running. The regression is in that voxedge build, not
in device contention.

Redeploying openvoicestream `main` with **voxedge 0.0.13a0** (pip-installed
over the image's stock 0.0.5a0, plus `sentencepiece` and `kaldi_native_fbank`
which that backend needs and the older environment lacked) on the identical
board, identical `jetson.sensevoice_trt` backend, identical
`execution_policy.mode=serialized` (the backend still declares
`supports_parallel=False` — one TensorRT execution context, admission-only
concurrency, by design, see `sensevoice_trt.py`) fixes it: p95 stays under
200 ms through c=16. `tegrastats` during this run shows GR3D_FREQ reaching
98-99% — the GPU is now actually busy, versus 31% in the broken run — meaning
the old build's bottleneck was software overhead around the inference call
(not memcpy/context-recreation profiled further; the version bump alone
removed it), not the GPU itself.

## Environment for this run

- All non-ASR containers stopped before testing:
  `edge-inspection-assembly-app`, `edge-inspection-assembly-mosquitto`, and
  the old `ovs-sv-test` container. Confirmed idle: `tegrastats` GR3D_FREQ 0%,
  all 6 CPU cores 0%, `free -m` 1966/7620 MB used.
- Power/clocks: `nvpmodel -q` → `MAXN_SUPER`; `jetson_clocks --show` → CPU
  6x1728 MHz (pinned), GPU 1020 MHz (pinned) — already at max, unchanged for
  this test.
- Image `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
  with `server/` and `configs/` bind-mounted from openvoicestream `main`
  (this branch), plus `pip install voxedge==0.0.13a0 sentencepiece
  kaldi_native_fbank` inside the container (the stock image ships voxedge
  0.0.5a0, which lacks the `max_concurrent` field on `SenseVoiceTRTConfig`
  entirely and clamps to 1 slot — confirmed via the
  `admission ceiling 16 requested but this voxedge build has no
  max_concurrent field` warning before the upgrade).
- Profile `orin-nano-sensevoice-asr-c16`: copy of the tracked
  `jetson-sensevoice` profile with `asr_max_slots`/`max_concurrent_sessions`
  raised from 8 to 16 to find the real ceiling, per request. `PYTHONUTF8=1`
  set. `OVS_API_KEYS=testkey123`, bench run with `--api-key`.
- Server confirmed at startup: `SessionLimiter initialized: effective_limit=16`,
  `ASR executor: max_workers=16 (source=asr_cap.max_concurrent)`.
- All stopped containers restarted and `docker ps` reconciled against the
  pre-test list after the run.

## Results

| Concurrency | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Aggregate audio RTF | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1  | 20 | 0 | 94  | 183 | 0.0201 | 0.0435 | 0.164 | 0.94 | 5.99% |
| 2  | 20 | 0 | 102 | 182 | 0.0183 | 0.0404 | 0.317 | 1.83 | 5.99% |
| 4  | 20 | 0 | 123 | 167 | 0.0235 | 0.0308 | 0.603 | 3.47 | 5.99% |
| 8  | 20 | 0 | 101 | 160 | 0.0215 | 0.0362 | 1.051 | 6.05 | 5.99% |
| 12 | 20 | 0 | 111 | 195 | 0.0237 | 0.0422 | 1.452 | 8.36 | 5.99% |
| 16 | 20 | 0 | 127 | 186 | 0.0229 | 0.0462 | 1.669 | 9.61 | 5.99% |

No errors and no failed sessions through c=16, the highest level tested.
p95 stays in a 160-195 ms band across every concurrency level — this run did
not find the real ceiling; it found that the *previous* number was a software
regression, not a device limit. CER is 5.99% at every level, matching the
earlier (broken) run and the reference offline decode — concurrency does not
touch accuracy on this backend either way.

Throughput scales close to linearly with concurrency (0.164 → 1.669
segments/s from c=1 to c=16, a 10.2x increase for 16x the sessions),
consistent with a single serialized execution context whose per-call latency
is the true bottleneck and is small (order 5-10 ms of GPU time per 4-6 s
utterance) relative to network/feed overhead.

## What this run did NOT establish

The real admission ceiling for this board and backend is still unknown —
c=16 was the top of the requested sweep and showed no degradation. Finding
where it breaks (CPU exhaustion in VAD/feature extraction, GPU queue
overflow, or a WebSocket/uvicorn connection limit) needs concurrency levels
above 16, not covered here.

## Files

- `concurrency-orin-nano-clean.json` — full per-segment results for c=1/2/4/8/12/16.
- `concurrency-orin-nano-isolate-c8-oldvoxedge.json` — isolation control: old
  voxedge 0.0.8a0 container (`ovs-sv-test`), c=8, all other containers
  stopped, reproduces the 429/degenerate-latency signature (p50 1091 ms /
  p95 3494 ms) with zero device contention.
- `orin-nano-clean-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  clean bench run, showing GR3D_FREQ reaching 98-99% under load.
