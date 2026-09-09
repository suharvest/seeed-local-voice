# cat-remote (RK3576) ASR bench results — 2026-09-09

Device: `cat-remote` (EmbedFire LubanCat-3, RK3576, fleet host `100.89.94.11`).
Image: `openvoicestream:rk-20260903.10` (locally cached, no compose stack
touched — container run directly per `bench/asr_bench/DISPATCH.md`).

## SenseVoice, zh, fp16-scaled encoder

Model: `sense-voice-encoder.rk3576.fp16-scaled.rknn` (staged at
`/home/cat/svtest-scaled/`, the file documented in
`docs/reports/retail-voice-asr-bench-matrix-2026-09-09.md` as the fix for
the RK3576 fp16-overflow CER bug). Neither cached image reads the
`fp16-scaled` filename directly (confirmed again here — see EVIDENCE); a
symlink named `sense-voice-encoder.rk3576.fp16.rknn` pointing at the scaled
file was created in the staged directory (bind-mounted read-write at
`/opt/asr/sensevoice-rknn`, not a shared/named volume) so the container's
hardcoded plain-filename lookup resolves to the scaled model's bytes. This
is a workaround for benchmarking, not a code fix — the model_downloader
filename mapping in the running image is unchanged.

Corpus: `bench/asr_bench/corpus` (20 zh items, AISHELL-1 train-range
subset — see `bench/asr_bench/README.md` caveat).

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 777.5 | 945.5 | 0.135 | 0.279 | 0.15 | 5.99% |
| 2 | 20 | 1 | 19 | 755.3 | 755.3 | 0.126 | 0.126 | 0.15 | not supported by this profile |
| 4 | 20 | 1 | 19 | 766.0 | 766.0 | 0.128 | 0.128 | 0.15 | not supported by this profile |
| 8 | 20 | 1 | 19 | 806.7 | 806.7 | 0.134 | 0.134 | 0.14 | not supported by this profile |

- Concurrency ≥2: 19/20 requests fail immediately with
  `{"error": "too_many_sessions", "current": 1, "limit": 1}` (the one "OK"
  per level is the single session that won admission; the rest are rejected
  before any audio is processed). This is `execution_policy.mode:
  serialized` / `SessionLimiter effective_limit=1`, server-enforced, not a
  timeout or crash — report c≥2 as "not supported by this profile", not as
  a degraded data point.
- Mean CER at c=1 is 5.99%, materially better than the 24.6% measured on
  the plain-fp16 encoder in the prior smoke test (same corpus,
  `docs/reports/retail-voice-asr-bench-matrix-2026-09-09.md` §"Known
  accuracy bug") — consistent with the fp16-scaled file fixing the
  documented activation-overflow bug. 0/20 items came back empty this run
  (the plain-fp16 run had 2/20 empty transcripts).
- Raw data: `results/cat-remote-sensevoice-zh.json` / `.md`.

## Can `execution_policy.mode` be changed to allow parallel SenseVoice sessions? No — tested directly

Tested by mounting an edited copy of `configs/profiles/rk3576-sensevoice.json`
into the container with `execution_policy.mode` changed from `serialized` to
`concurrent` and `max_concurrent_sessions` raised from unset to `4`. Result,
from the container's own startup log:

```
session_limiter: profile.max_concurrent_sessions=4 exceeds backend ceiling
(asr=1,tts=inf) → clamping to 1
SessionLimiter initialized: effective_limit=1 (env
OVS_MAX_CONCURRENT_SESSIONS=None, profile.max_concurrent_sessions=4)
coordinator: downgrading concurrent -> serialized (asr.supports_parallel=False/max=1,
tts.supports_parallel=True/max=None)
```

`server/core/coordinator.py`'s own docstring says why: "backend capability
is the ceiling, profile.execution_policy is the floor" — profile/env
`max_concurrent_sessions` can only *downgrade* the ceiling, never raise it
above what the ASR backend declares (`asr_cap.max_concurrent=1` for
`rk.asr`/SenseVoice-RKNN, a hardware fact — one RKNN execution context on
this NPU — not a config knob). `execution_policy.mode` in the profile only
arbitrates ASR-vs-TTS interleaving on a single shared lock (irrelevant here,
this profile is ASR-only); it does not control same-backend session
admission count, which is what `SessionLimiter`/`too_many_sessions` enforce.
**No profile/env change lifts the c≥2 cap on this backend** — raising it
would require a backend code change (declaring `supports_parallel=True` and
`max_concurrent>1` for `rk.asr`, i.e. an execution-context pool), which is
out of scope for this bench pass.

## Whisper — blocked, not a disk-space issue

`df -h /` before starting: 5.6G free / 58G (90% used, ~9.7% headroom) — the
~358 MB the `rk3576-whisper` (`base10`) assets would need (42.6 MB RKNN
encoder + 159.5 MB + 156.3 MB decoder ONNX, confirmed via `curl -sIL` against
`https://hf-mirror.com/harvestsu/whisper-edge/resolve/main/...`) would have
fit.

The actual blocker: **the only two OpenVoiceStream images cached on
cat-remote do not register an `rk.whisper` ASR backend at all.** Querying
the running container's registry directly:

```
docker exec asrbench-rk3576-whisper python3 -c \
  "from server.core.asr_backend import _ASR_REGISTRY; print(sorted(_ASR_REGISTRY.keys()))"
['cpu.sherpa_asr', 'jetson.paraformer_trt', 'jetson.sensevoice_trt', 'jetson.trt_edge_llm', 'rk.asr']
```

Starting the container with `OVS_PROFILE=rk3576-whisper` (profile JSON
mounted in from this repo, since the image doesn't even ship that profile
file — `FileNotFoundError` on the first attempt before the mount was added)
gets past profile loading but then:

```
ASR backend failed: Unknown asr_backend: 'rk.whisper'
ASR-only mode: profile declares no tts_backend; TTS endpoints will return 503.
Speech service ready.
```

The server comes up and reports `/readyz` OK, but has no ASR backend
loaded — `/asr/stream` would 503/error on any real request. This is an
image/build gap on this device, not a resource constraint: no cached image
on cat-remote (`openvoicestream:rk-20260903.10`,
`seeed-local-voice:rk-20260803b`, or the sha-pinned
`sensecraft-missionpack.../openvoicestream`) has the `rk.whisper` backend
registered. **No Whisper number was collected for cat-remote** — getting one
requires a newer image build that registers `rk.whisper` (out of scope for
this bench pass; flag it for whoever owns image builds). No model files
were downloaded before hitting this error (confirmed empty
`/home/cat/whisper-rk3576-model`, 4.0K/`du -sh`), so no cleanup was needed
beyond removing the container.

## Resource sampling — incomplete (fleet job died early)

`resource_sampler.py --accel rknpu --interval 1 --duration 400` was started
via `fleet exec --sudo --detach` (needs root for
`/sys/kernel/debug/rknpu/load`) in parallel with the concurrency=1
SenseVoice run (wall time 135 s). The underlying job showed `stale` in
`fleet jobs` almost immediately (known limitation, see project memory
`project_fleet_detach_job_stale_monitor`) and its CSV only captured the
first ~25.5 s (26 samples) before writes stopped — well short of the 135 s
run.

What the partial data shows: CPU 3.3-20.8%, mem ~20.1% (stable, no leak in
this window), `NPU load: Core0: 0%, Core1: 0%` for every one of the 26
samples. The 0% NPU reading across the whole captured window (which does
overlap active decode calls, since c=1 items were still being processed at
t=8-25s per the bench log timing) is not itself validated as a real
"NPU idle" signal — it may equally be a sampling-interval miss against
short (<1s) decode bursts, or the sysfs path not reflecting this specific
NPU core-mask (`ASR_NPU_CORE_0`) under this driver version. Treat the NPU
utilization number as unconfirmed, not as evidence of a CPU-bound decode
path. Raw partial CSV kept at `results/cat-remote-resource-sv-zh-partial.csv`.

## Docker / disk state discipline

- `docker ps -a` checked before every container start; no pre-existing
  `asrbench-*` or foreign containers were touched (all pre-existing
  containers on the box were `Exited`, unrelated names).
- Shared volumes `rk-asr-models`, `rk-tts-models` were mounted read-only
  intent (SenseVoice run bind-mounted `rk-asr-models` per DISPATCH's exact
  command; it was never written to by this pass — the model dir actually
  used was the `/home/cat/svtest-scaled` bind mount) and never deleted or
  recreated.
- All `asrbench-*` containers were removed after use
  (`docker rm -f asrbench-rk3576-sv`, `asrbench-rk3576-whisper`); no
  container left running.
- Files added under `/home/cat/`: `rk3576-sensevoice-concurrent.json`
  (removed), `rk3576-whisper.json` (removed), `whisper-rk3576-model/`
  (removed, was empty), `res-sv-zh.csv`/`.log` (pulled to this repo's
  `results/`, left on-device — harmless small text files, ~2 KB).
  `/home/cat/svtest-scaled/sense-voice-encoder.rk3576.fp16.rknn` (the
  symlink created for the model-filename workaround) was left in place —
  it points at the pre-staged scaled file and does not consume extra disk;
  removing it would be reasonable for the next runner but was left since
  DISPATCH says this directory is for "whoever runs the real bench pass"
  and the symlink documents the working invocation.
- `df -h /`: 5.6G free before and after this pass (no net disk usage from
  this run — the only file possibly added, the Whisper decoder/encoder
  download, never started).

## What this pass did NOT do

- No `radxa`, `orin-nano`, `orin-nx`, `harvest-pi` work — out of scope for
  this dispatch (cat-remote only).
- No Whisper CER/latency numbers for cat-remote (see blocker above).
- No confirmed NPU utilization number (see resource sampling above).
