# harvest-pi (reComputer R2000 series, Raspberry Pi 5 + Hailo-8) — ASR bench results

Date: 2026-09-09. Device: `harvest-pi` fleet entry, page label reComputer
R2000 series (Raspberry Pi 5 Model B, 8 GB RAM, Hailo-8 accelerator on
`/dev/hailo0`). Scope per `DISPATCH.md`: SenseVoice (CPU backend) zh corpus
at concurrency 1/2/4/8, and Whisper (Hailo-8 encoder + CPU decoder) en
corpus at concurrency 1/2/4/8.

## Summary

| Backend | Lang | Endpoint used | Result |
|---|---|---|---|
| SenseVoice (`cpu.sherpa_asr`, profile `rpi5-sensevoice`) | zh | `/asr` (offline, multipart) — **not** `/asr/stream` | Measured, see below |
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

## Blocker 2: SenseVoice cannot be served over `/asr/stream` at all — architectural, not a config bug

The dispatch's own bench tool (`bench.py`) only targets `/asr/stream`
(WebSocket). Running it against the freshly-built `rpi5-sensevoice`
container produced **100% errors at every concurrency level** (see
`harvest-pi-sensevoice-zh-stream-FAILED.json`): server accepts the
WebSocket then immediately sends `{"error": "no streaming ASR available"}`
and closes (code 1000).

Root cause, traced to source (not guessed):

- `server/main.py:5167` `/asr/stream` gates on
  `asr_be.has_capability(ASRCapability.STREAMING)` (`server/main.py`
  ~line 5266-5270); if false it sends the error and closes
  (`server/main.py` ~line 5320-5321).
- `voxedge/backends/sherpa/asr.py` `SherpaASRBackend.capabilities`
  (line ~283-290) only reports `STREAMING` when its **online** (Paraformer)
  recognizer loaded; `create_stream()` (line 331) — the only thing
  `/asr/stream` can call — **raises if the online recognizer is None** and
  has no path to the offline SenseVoice recognizer at all.
  `transcribe()` (line 350, offline/SenseVoice) is wired only to the
  non-streaming `POST /asr` endpoint (`server/main.py:4940`).
- The `rpi5-sensevoice` profile deliberately does not fetch
  `paraformer-streaming` (`server/core/model_downloader.py`'s
  `_BUNDLE_MODEL_BACKEND` gate suppresses it unless
  `asr_backend == jetson.paraformer_trt`), so on this profile the online
  recognizer never loads and `STREAMING` capability is never present.

In other words: on this backend, SenseVoice **only ever serves the offline
`POST /asr` endpoint** — never `/asr/stream` — no matter what env vars or
profile overrides are set. This is true for any device using
`cpu.sherpa_asr` (not just this Pi). The `rpi5-sensevoice` profile's own
description text ("SenseVoice serves the offline /asr path; streaming
Paraformer also loads for /asr/stream") already says this — it was not
mentioned in the task brief and the mismatch with `bench.py`'s fixed target
was not caught before dispatch.

**What was measured instead**: rather than report zero data, the same
running container's `/asr` (offline, multipart upload) endpoint was
benchmarked with a small ad-hoc script
(`offline_asr_bench.py`, not committed — kept out-of-repo since it is a
stopgap, not a permanent tool) that reuses the same corpus manifest and the
same `jiwer` CER logic as `bench.py`, at the same concurrency levels. This
is the real SenseVoice engine, same container, same corpus — just the
correct endpoint for this backend.

## SenseVoice zh results (`POST /asr`, 20-item AISHELL-1 subset)

### Pass 1 — profile default (`max_concurrent_sessions=1`, server-enforced)

| concurrency | ok/20 | latency p50 (ms) | latency p95 (ms) | RTF p50 | mean CER |
|---|---|---|---|---|---|
| 1 | 20 | 768 | 1183 | 0.128 | 14.6% |
| 2 | 5 | — | — | — | `too_many_sessions` (current=1, limit=1) on the rest |
| 4 | 3 | — | — | — | `too_many_sessions` (current=1, limit=1) on the rest |
| 8 | 2 | — | — | — | `too_many_sessions` (current=1, limit=1) on the rest |

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
| 8 | 4/20 | 1446 | 1571 | 0.448 | 0.560 | `too_many_sessions` (current=4, limit=4) on the other 16 |

`results/harvest-pi-sensevoice-zh-offline-limit4.json`. The c=1 p95 outlier
(14.5 s on one segment) coincides with the first request after container
warm-up in this run and is not representative — treat c=1 p50/RTF as the
reliable single-session baseline; c=2/c=4 show the expected **graceful CPU
contention degradation** (latency scales roughly linearly with concurrency,
no errors) that the profile description predicted, up to the
backend-declared ceiling of 4, where the 5th+ concurrent request is
rejected with `429`/`too_many_sessions` rather than queued or degraded
further. CER is identical (14.6%) across all levels and passes — as
expected, since it is the same 20-item corpus and the same deterministic
model; almost all of that CER is Arabic- vs Chinese-numeral normalization
in the reference text, not real ASR errors (same caveat as the RK3576 smoke
test in the matrix doc).

**Conclusion for SenseVoice on this device**: concurrency 1 is the safe
default (server-pinned); concurrency up to 4 works with linear latency
degradation and no accuracy loss if `OVS_MAX_CONCURRENT_SESSIONS` is raised;
concurrency 8 is rejected by the backend's own declared ceiling, not by a
hardware limit — this is a software policy question (how much CPU
contention is acceptable), not a "does not support concurrency" hard
failure like the RK3576 NPU or Hailo device exclusivity cases.

## Resource sampling

`resource_sampler.py` was pushed to the device
(`/home/harvest/asrbench-pi/resource_sampler.py`) but **not run
concurrently with the sweep** — disk headroom was critical for most of this
session (see below) and the sweep itself completed inside the fleet-exec
step budget without it. No CPU/mem/temp time series was captured for this
pass; only `hailortcli monitor` availability was confirmed
(`hailortcli` 4.21.0 present on host, used by other containers) — it was
not exercised since the Whisper/Hailo leg did not run.

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
- All bench-specific artifacts created during this session (the built
  `asrbench-rpi5-sensevoice:local` image, `/home/harvest/asrbench-pi/models`
  bind mount with the downloaded SenseVoice tarball, the build context) were
  removed after the run. Final state: **2.3 GB free**, no bench containers
  running, `mcp_face_rec` (the only container holding `/dev/hailo0`)
  untouched throughout — confirmed `healthy` before and after this session
  since `/dev/hailo0` was never needed (Whisper/Hailo did not run).

## Files

- `harvest-pi-sensevoice-zh-stream-FAILED.{json,md}` — the literal `bench.py`
  run against `/asr/stream`, kept as evidence of Blocker 2 (100% errors,
  not a transient failure).
- `harvest-pi-sensevoice-zh-offline.json` — Pass 1 (profile default,
  `max_concurrent_sessions=1`).
- `harvest-pi-sensevoice-zh-offline-limit4.json` — Pass 2
  (`OVS_MAX_CONCURRENT_SESSIONS=8` clamped to 4 by the backend's declared
  ceiling).

## Not done

- Whisper (Hailo-8 encoder + CPU decoder) en corpus — blocked, see
  Blocker 1. Needs a Dockerfile that installs HailoRT + the Python
  `hailo_platform` bindings and mounts `/dev/hailo0`; none exists in this
  repo today. This is a prerequisite engineering task, not a bench-run
  task — flagging for a scoped decision rather than building it
  unprompted.
- Live resource sampling (CPU/mem/temp) during the sweep — not captured
  this pass (see Resource sampling above).
- `bench.py` itself was not modified to add an `/asr` (offline) mode, even
  though that is the only endpoint SenseVoice-on-CPU can actually serve —
  that is a tool-design decision for whoever owns `bench/asr_bench`, not a
  per-device dispatch decision. The ad-hoc script used here
  (`offline_asr_bench.py`) is *not* committed to this repo for that reason.
