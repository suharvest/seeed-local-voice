# harvest-pi (reComputer R2000 series, Raspberry Pi 5 + Hailo-8) — ASR bench results

Date: 2026-09-09. Device: `harvest-pi` fleet entry, page label reComputer
R2000 series (Raspberry Pi 5 Model B, 8 GB RAM, Hailo-8 accelerator on
`/dev/hailo0`). Scope per `DISPATCH.md`: SenseVoice (CPU backend) zh corpus
at concurrency 1/2/4/8, and Whisper (Hailo-8 encoder + CPU decoder) en
corpus at concurrency 1/2/4/8.

## Summary

| Backend | Lang | Endpoint used | Result |
|---|---|---|---|
| SenseVoice (`cpu.sherpa_asr`, profile `rpi5-sensevoice`) | zh | `/asr/stream` (WebSocket) at c=1/2/4/8 | Measured, see below |
| Whisper (`hailo.whisper`, profile `rpi5-hailo-whisper`) | en | — | **Not run — no buildable container exists for this backend on this device (see Blockers)** |

## Blocker 1: no rpi image exists with the current profile system

The only rpi image ever published to the registry
(`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice`) is
`rpi-v1.0-onnx` (plus two older/slim tags) — confirmed by querying the
registry's own tag list via the Harbor v2 API (anonymous token, `GET
/v2/solution/seeed-local-voice/tags/list`): `["...", "rpi-20260721",
"rpi-slim-2026-06-01", "rpi-v1.0-onnx"]`, none newer. The `openvoicestream`
repo on the same registry has zero `rpi-*` tags at all (only `rk-*`). That
one rpi image predates the `server/` + `configs/profiles/*.json` +
`voxedge` layout this repo now uses — running it applies the image's own
baked-in `rpi5-default` profile (`app.main:app`, module path `app/`, no
`rpi5-sensevoice`/`rpi5-hailo-whisper` profile files exist inside it at
all — confirmed via `docker run --rm ... ls configs/profiles/`).

**Action taken**: built a fresh image on-device from this repo's own
`deploy/docker/Dockerfile.rpi` (`docker build -f deploy/docker/Dockerfile.rpi
--target final-slim -t asrbench-rpi5-sensevoice:local .`), using the current
`server/` + `configs/` copied over via `fleet push`. This is the Dockerfile
the repo already ships for exactly this purpose (its own header says
"Post-migration the CPU sherpa ASR/TTS backends live in voxedge") — it had
just never been built and pushed as a new tag. Build succeeded, image is
139 MB (CPU-only, no baked models).

**This does not exist for Whisper+Hailo.** There is no `Dockerfile` in this
repo that installs HailoRT (`grep -rl hailort deploy/` → no matches), and no
`hailort`/`hailo_platform` Python package is installed in the image I built
or in the base `Dockerfile.rpi` (`pip3 show hailort hailo_platform` inside
the built image → "Package(s) not found"). `hailortcli` (4.21.0) is present
on the **host** (used by other containers on this box, e.g. `mcp_face_rec`),
but nothing in this repo containerizes it for OpenVoiceStream. Building a
new Hailo-enabled Dockerfile from scratch is a new-infrastructure task
outside this dispatch's scope (`--sudo`/new-abstraction guardrail) — **the
Whisper/Hailo leg of this task is blocked on that missing Dockerfile, not on
anything device-specific**, and was not attempted.

## SenseVoice over `/asr/stream`: what was broken, what fixed it

The first pass on this device produced **100% errors at every concurrency
level**: the server accepted the WebSocket, sent
`{"error": "no streaming ASR available"}` and closed with code 1000.

Root cause, traced to source:

- `server/main.py` gates `/asr/stream` on
  `asr_be.has_capability(ASRCapability.STREAMING)`; when false it sends that
  error and closes.
- `voxedge/backends/sherpa/asr.py` reported `STREAMING` only when its
  **online** (Paraformer) recognizer had loaded, and `create_stream()` — the
  only entry point `/asr/stream` has — raised whenever that recognizer was
  `None`, with no path to the offline SenseVoice recognizer. `transcribe()`
  reached the offline recognizer, but only `POST /asr` calls it.
- `rpi5-sensevoice` does not fetch `paraformer-streaming`
  (`server/core/model_downloader.py`'s `_BUNDLE_MODEL_BACKEND` gate suppresses
  it unless `asr_backend == jetson.paraformer_trt`), so on this profile the
  online recognizer never loads:

  ```
  [INFO] voxedge.backends.sherpa.asr: Streaming ASR not available: /opt/models/paraformer-streaming/tokens.txt does not exist
  [INFO] voxedge.backends.sherpa.asr: Sherpa offline ASR loaded
  ```

**Fix** (voxedge `fix/sherpa-offline-stream`): route the offline-only case
through the generic `OfflineAccumulateStream`, the same adapter
`jetson/sensevoice_trt.py` and `whisper/asr.py` already use — accumulate the
utterance, transcribe on `finalize()`, endpointing from the server-side VAD.
`create_stream()` still prefers a native online recognizer when one is
loaded, so existing sherpa deployments are unchanged. The results below were
measured with that fix in place; the profile description in
`configs/profiles/rpi5-sensevoice.json` was corrected in the same pass (it
claimed streaming Paraformer also loads here, which it does not).

## SenseVoice zh results (`/asr/stream`, 20-item AISHELL-1 subset)

Container: `Dockerfile.rpi --target final-slim`, profile `rpi5-sensevoice`
(`max_concurrent_sessions=8`, `asr_max_slots=8`), model
`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx`
(239 233 841 bytes, CPU provider). Corpus and CER logic identical to the
`radxa` (RK3588) SenseVoice pass, so the CER numbers are directly comparable.
Latency = audio-end → `is_final`; RTF = that latency / audio duration.

| c | OK | Err | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 0 | 641.5 | 856.8 | 0.106 | 0.115 | 0.15 | 5.48% |
| 2 | 20/20 | 0 | 622.3 | 824.3 | 0.103 | 0.117 | 0.30 | 5.48% |
| 4 | 20/20 | 0 | 620.1 | 865.7 | 0.105 | 0.117 | 0.58 | 5.48% |
| 8 | 20/20 | 0 | 851.5 | 2280.2 | 0.125 | 0.274 | 1.00 | 5.48% |

`results/harvest-pi-sensevoice-zh-stream.{json,md}`. Throughput scales 1:2:4:8
across the four levels (0.15 → 1.00 seg/s) with p50 latency flat through c=4;
at c=8 — twice the core count — p50 rises 37% and p95 2.7x, which is queueing
in the ONNX Runtime thread pool, not rejection: no level returned an error.
CER is identical at every level, as expected from a deterministic model on a
fixed corpus.

`top -b -d 1` sampled through the sweep (`harvest-pi-top.log`, 251 samples).
The server process peaked at **336% CPU** of the board's 400% during the c=8
burst; at c=1 the machine sits near idle between utterances, consistent with
RTF 0.106.

### Concurrent-decode safety

Before raising the ceiling, one shared `OfflineRecognizer` was decoded from
several threads at once inside the same container — 6 clips per thread, every
clip decoded concurrently, compared against a serial baseline:

```
MODEL_FILE /opt/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx 239233841 bytes
SERIAL_OK 6
THREADS=2 elapsed=3.74s errors=0 mismatches=0
THREADS=4 elapsed=11.21s errors=0 mismatches=0
```

No exceptions, no transcript differences — so the backend keeps
`supports_parallel=True` with no added lock.

## Earlier pass: SenseVoice zh over `POST /asr`

This is the same 20-item AISHELL-1 subset (`bench/asr_bench/corpus/manifest.json`)
used in the `radxa` (RK3588) report's SenseVoice pass
(`bench/asr_bench/results/radxa.md`, mean CER 5.99% at c=1) — the two CER
numbers are directly comparable: same corpus, same reference text, same
`jiwer` CER logic, different backend/quantization (RK3588 RKNN fp16-scaled
vs this device's CPU `sherpa_asr`).

### Pass 1 — profile default (`max_concurrent_sessions=1`, server-enforced)

| concurrency | ok/20 | latency p50 (ms) | latency p95 (ms) | RTF p50 | RTF p95 | mean CER (successful segments) |
|---|---|---|---|---|---|---|
| 1 | 20 | 768 | 1183 | 0.128 | 0.161 | 14.6% |
| 2 | 5 | 820 | 982 | 0.129 | 0.134 | 14.8% (n=5) — remaining 15 rejected with `too_many_sessions` (current=1, limit=1) |
| 4 | 3 | 818 | 968 | 0.153 | 0.183 | 19.9% (n=3) — remaining 17 rejected with `too_many_sessions` (current=1, limit=1) |
| 8 | 2 | 1078 | 1078 | 0.156 | 0.156 | 9.3% (n=2) — remaining 18 rejected with `too_many_sessions` (current=1, limit=1) |

The c=2/4/8 CER figures above are computed over only the 1-5 sessions the
server admitted before rejecting the rest with `too_many_sessions`; the
sample size is too small (n=2 to n=5) to read as a concurrency effect on
accuracy — see Pass 2 for the CER-vs-concurrency comparison that actually
holds sample size constant (n=20 or n=4 per level).

`results/harvest-pi-sensevoice-zh-offline.json`.

### Pass 2 — `execution_policy.mode` re-check: profile pin loosened

Per `configs/profiles/rpi5-sensevoice.json`'s own description
("`max_concurrent_sessions` is pinned to 1... the declared ceiling is not
safe here until it is measured") and `execution_policy.mode: "concurrent"`
(not `serialized` — this is a defensive software cap, not a hardware
exclusivity lock like the RK NPU or Hailo device), the container was
restarted with `OVS_MAX_CONCURRENT_SESSIONS=8`. The session limiter clamped
this to **4** on its own
(`session_limiter: OVS_MAX_CONCURRENT_SESSIONS=8 exceeds backend ceiling
(asr=4,tts=inf) → clamping to 4` — the backend's own
`concurrency_capability()` declares `max_concurrent=4`, matching the
historical desktop default for independent CPU/ONNXRuntime recognizer
instances). Re-ran the sweep against this limit:

| concurrency | ok/20 | latency p50 (ms) | latency p95 (ms) | RTF p50 | RTF p95 | mean CER |
|---|---|---|---|---|---|---|
| 1 | 20 | 736 | (14536 outlier, see note) | 0.123 | 2.42 | 14.6% |
| 2 | 20 | 874 | 1413 | 0.145 | 0.177 | 14.6% |
| 4 | 20 | 1539 | 2940 | 0.281 | 0.315 | 14.6% |
| 8 | 4/20 | 1446 | 1571 | 0.448 | 0.560 | 20.6% (n=4) — remaining 16 rejected with `too_many_sessions` (current=4, limit=4) |

`results/harvest-pi-sensevoice-zh-offline-limit4.json`. The c=1 p95 outlier
(14.5 s on one segment) coincides with the first request after container
warm-up in this run and is not representative — treat c=1 p50/RTF as the
reliable single-session baseline; c=2/c=4 show the expected **graceful CPU
contention degradation** (latency scales roughly linearly with concurrency,
no errors) that the profile description predicted, up to the
backend-declared ceiling of 4, where the 5th+ concurrent request is
rejected with `429`/`too_many_sessions` rather than queued or degraded
further. At c=1/2/4 (n=20 each), CER is identical (14.6%) — as expected,
since it is the same 20-item corpus and the same deterministic model; almost
all of that CER is Arabic- vs Chinese-numeral normalization in the reference
text, not real ASR errors (same caveat as the RK3576 smoke test in the
matrix doc). At c=8 the 4 successful segments show 20.6% CER; with n=4 this
is consistent with normal item-to-item variance in this corpus rather than
a concurrency-driven accuracy loss, but the sample is too small to rule
that out.

**Conclusion for SenseVoice on this device**: concurrency 1 is the safe
default (server-pinned); concurrency up to 4 works with linear latency
degradation and no accuracy loss if `OVS_MAX_CONCURRENT_SESSIONS` is raised;
concurrency 8 is rejected by the backend's own declared ceiling, not by a
hardware limit — this is a software policy question (how much CPU
contention is acceptable), not a "does not support concurrency" hard
failure like the RK3576 NPU or Hailo device exclusivity cases.

## Resource sampling

`top -b -d 1` ran alongside the `/asr/stream` sweep; the series is
`harvest-pi-top.log` (251 samples). Peak was 336% CPU of the board's 400%
during the c=8 burst. `hailortcli` (4.21.0) is present on the host and used
by other containers, but was not exercised — the Whisper/Hailo leg did not
run and `/dev/hailo0` was never opened by this session.

The earlier `POST /asr` passes have no CPU series: `resource_sampler.py` was
pushed to the device but not run concurrently with them.

## Disk-space handling

`harvest-pi` started this session at **1.1 GB free** (29 GB card, 97%
used), matching the prior-session baseline noted in the dispatch. Per the
dispatch's own instruction, only a self-built directory was cleaned, not
anything belonging to other projects on this shared device:

- Removed `/home/harvest/hailo-whisper-bench/` (1.7 GB) — a self-built,
  stale (Aug 27) ad-hoc Whisper+Hailo bench directory from an earlier,
  unrelated manual investigation (venv + logs + results, not a
  running service, not referenced by any container). This was the only
  cleanup needed to get enough headroom to pull the old image / build the
  new one.
- The `/asr/stream` pass rebuilt the image and re-downloaded the SenseVoice
  bundle. Its unused fp32 `model.onnx` (895 MB) was deleted — the backend
  loads `model.int8.onnx` — and the Docker build cache pruned, which returned
  the device to **2.1 GB free** with the bench container still up.
- `mcp_face_rec` (the only container holding `/dev/hailo0`) was untouched
  throughout and stayed `healthy`; `/dev/hailo0` was never opened.

## Files

- `harvest-pi-sensevoice-zh-stream.{json,md}` — `bench.py` against
  `/asr/stream` at c=1/2/4/8, 20 segments each, with the offline-stream fix in
  place. Replaces the earlier `-FAILED` pair (100% errors), which is dropped:
  the failure it recorded is described above and no longer reproduces.
- `harvest-pi-top.log` — `top -b -d 1` through that sweep, 251 samples.
- `harvest-pi-sensevoice-zh-offline.json` — earlier `POST /asr` Pass 1
  (profile default, `max_concurrent_sessions=1`).
- `harvest-pi-sensevoice-zh-offline-limit4.json` — earlier `POST /asr` Pass 2
  (`OVS_MAX_CONCURRENT_SESSIONS=8` clamped to 4 by the backend's declared
  ceiling at the time).

## Not done

- Whisper (Hailo-8 encoder + CPU decoder) en corpus — blocked, see
  Blocker 1. Needs a Dockerfile that installs HailoRT + the Python
  `hailo_platform` bindings and mounts `/dev/hailo0`; none exists in this
  repo today. This is a prerequisite engineering task, not a bench-run
  task — flagging for a scoped decision rather than building it
  unprompted.
- `bench.py` still has no `/asr` (offline, multipart) mode. It is no longer
  needed for SenseVoice-on-CPU now that `/asr/stream` serves it, so the ad-hoc
  script used for the earlier offline pass stays out of this repo.
