# orin-nx (reComputer J4012, Jetson Orin NX 16GB) ASR bench results — 2026-09-09

Device: `orin-nx` (fleet-managed, tailscale IP `100.82.225.102`). Board runs
pre-existing containers `edge-inspection-mosquitto`, `esk-jetson-rtsp-pub`,
`esk-jetson-rtsp-server` throughout this pass — none were touched. All bench
containers used the `asrbench-jetson-*` naming convention with
`--network host` (compose's `8621:8000` mapping does not apply outside
bridge networking, so the service actually listens on host port **8000**,
not 8621 — confirmed via `curl localhost:8000/readyz` after `8621` connection
refused). `docker ps -a` before/after matches (see EVIDENCE).

## SenseVoice (zh, AISHELL-1 subset, 20 items)

Image: `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
— **not present on the box**, pulled fresh (1.17 GB; `docker images` is the
source of truth per DISPATCH, and neither `jetson-v1.14-hotswap` nor
`jetson-v1.12-highperf` — the two tags DISPATCH said to check — were
present; the actual compose default on `main` is this v0.9.0 tag). Profile:
`jetson-sensevoice` (`jetson.sensevoice_trt`, standalone TensorRT engine).

The container needs the host CUDA/TensorRT bind mounts from
`deploy/docker-compose.yml` (`/usr/local/cuda/lib64`, the nvidia libs, the
host's `tensorrt` Python package and `/usr/src/tensorrt`) — `docker run`
without them fails `ModuleNotFoundError: No module named 'tensorrt'`
immediately. With the mounts in place, the TRT engine built successfully
on first start from the shipped ONNX (`sense-voice-encoder.scaled.fixed.onnx`),
taking **~3.5 min of engine-build CPU time** (`docker top` CPU time
00:00:14 → 00:03:53 before `Speech service ready`), consistent with
DISPATCH's "expect a multi-minute delay before `/readyz` on a cold model
dir."

Two Python packages are missing from this image's venv and had to be
installed at runtime as a throwaway workaround (**not a deployment fix** —
the image itself needs a rebuild with these pinned):
`ModuleNotFoundError: No module named 'sentencepiece'` (SenseVoice backend
`preload()`) and, after fixing that, `ModuleNotFoundError: No module named
'kaldi_native_fbank'` (feature extraction in `transcribe_array()` — this one
was silently swallowed per-request, producing `ok: true` with an **empty
transcript** rather than a startup crash; the first full concurrency sweep
was run against this broken state before the bug was caught and is not the
number reported below — see EVIDENCE for the discarded run).

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Mean CER |
|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 113.2 | 152.0 | 0.019 | 0.037 | 5.99% |
| 2 | 20 | 1 | 19 | — | — | — | — | `too_many_sessions` (19/20) |
| 4 | 20 | 1 | 19 | — | — | — | — | `too_many_sessions` (19/20) |
| 8 | 20 | 1 | 19 | — | — | — | — | `too_many_sessions` (19/20) |

Concurrency ≥2 is **not supported by this profile** — same pattern as
RK3576/RK3588: every extra session gets
`{"error": "too_many_sessions", "current": 1, "limit": 1}` from the server's
admission gate (one segment per level slips through because the first WS
grabs the slot before the rest connect — a race in the client fan-out, not a
working concurrency=2+ result). Full raw JSON: `orin-nx-sensevoice-zh.json`.

### Can the session cap be raised? No — checked, not assumed

`jetson-sensevoice.json`'s `execution_policy` is `{"mode": "serialized",
"shared_resource": "gpu"}`. Traced the backend source at the exact
`voxedge` version this image bakes in (`0.0.5a0`, confirmed via
`voxedge.__version__` inside the container — see EVIDENCE):
`voxedge/backends/jetson/sensevoice_trt.py:96`,
`SenseVoiceTRTBackend.__init__` —
`self._lock = threading.Lock()  # single shared context; offline is
serialized`. A single `threading.Lock()` guards the one TensorRT execution
context — a hardware/runtime-context fact, not a config choice.

Verified empirically: mounted an edited `jetson-sensevoice.json` with
`execution_policy.mode: "concurrent"` and `max_concurrent_sessions: 4` over
the container's copy. Result:

```
session_limiter: profile.max_concurrent_sessions=4 exceeds backend ceiling
  (asr=1,tts=1) → clamping to 1
SessionLimiter initialized: effective_limit=1 (env OVS_MAX_CONCURRENT_SESSIONS=None,
  profile.max_concurrent_sessions=4)
```

No config change re-opens concurrency for SenseVoice on this board.

## Whisper (en) — not benchable on this image; root-caused, not skipped

`configs/profiles/orin-whisper.json` does not exist in this image at all
(`FileNotFoundError` on container start with `OVS_PROFILE=orin-whisper`) —
listing `/opt/speech/configs/profiles/` inside the image shows 41 profiles,
none named `orin-whisper` or containing "whisper". Confirmed the backend
code itself is also absent: `from voxedge.backends.jetson import
whisper_trt` raises `ImportError: cannot import name 'whisper_trt'`, and
`server.core.asr_backend._ASR_REGISTRY` inside this image is
`{cpu.sherpa_asr, jetson.paraformer_trt, jetson.sensevoice_trt,
jetson.trt_edge_llm, rk.asr}` — no `jetson.whisper_trt` key.

Root cause: Whisper backend registration landed in commit `7cc9dd55`
(2026-08-28, "Whisper across five edge accelerators"), and `voxedge`
0.0.12a0 (commit `a867e4cd`, "the first release with the Whisper backend")
followed it — both **are already merged to `main`** (verified against
`origin/main` at `d932330e`, not a stale local ref: `git merge-base
--is-ancestor 7cc9dd55 origin/main` exits 0). The blocker is not an
unmerged commit — it is that the **compose default image tag on `main`**
(`v0.9.0-ondemand-20260721c`, built July 21) predates both changes and
bakes in `voxedge==0.0.5a0` (confirmed via `voxedge.__version__` inside the
container, see EVIDENCE), which has no `whisper_trt` module at all. No
newer Jetson image with Whisper support was found to pull (same category of
blocker cat-remote and radxa each hit for their own platforms — the
published image lags merged source by weeks).

**Conclusion**: Whisper Orin support exists in merged source (`7cc9dd55`,
`a867e4cd`) but the only image currently pulled by `main`'s compose default
predates it (`v0.9.0-ondemand-20260721c` / `voxedge==0.0.5a0`) and has no
distributable successor today. Building/publishing a newer image is out of
scope for this bench pass (dispatch scope is "run the bench," not "build a
release image").

The `orin-whisper.json` profile's own description string (encoder 11.4 ms on
NX, TTFT 58-83 ms) is cited from that commit's one-off validation, not
measured by this bench tool here.

## Resource sampling

`resource_sampler.py --accel tegrastats` **does not work on this box's
tegrastats build**: it calls `tegrastats --interval 200 --count 1`, and this
device's tegrastats has no `--count` flag (`Unknown command: --count`,
confirmed via `tegrastats --help`) — every accel-probe row in its CSV output
is that error string instead of a parsed reading. This is a tool/device
version-compatibility gap, not attempted-and-idle.

Fell back to a native `tegrastats --interval 2000 --logfile
orin-nx-tegrastats.log`, run manually via `setsid nohup` for the remainder
of the session (`results/orin-nx-tegrastats.log`, ~142 samples). During the
actual SenseVoice c=1 run window, `GR3D_FREQ` (GPU utilization) reads **0%
on nearly every 2 s sample** — not a claim the GPU was idle: c=1 final
latency p50 is 113 ms against audio segments 2.5-6 s long fed at 1.0x
real-time pace, so the TRT decode burst is roughly 20-50x shorter than the
sampler's 2 s interval and is very likely to be missed, same
measurement-resolution gap radxa's report documents for `rknpu/load`. One
sample during the profile-override test start briefly showed `GR3D_FREQ 6%`
(cv0 core waking for engine init). CPU/RAM from the same log: RAM steady at
~2.7-2.8 GB / 15.6 GB total; CPU per-core mostly <10% outside the brief
engine-build window recorded separately in container logs.

## Files

- `results/orin-nx-sensevoice-zh.json` — raw per-segment SenseVoice zh rows
  (fixed run, post `kaldi_native_fbank` install).
- `results/orin-nx-sensevoice-zh.md` — bench.py's own summary table.
- `results/orin-nx-tegrastats.log` — native tegrastats log, 2 s interval,
  spanning the profile-override test (partial coverage — see above).
- No Whisper JSON/CSV produced — see "not benchable" above.

## EVIDENCE

### Disk headroom (before / after)

```
before pull: /dev/nvme0n1p1  233G  193G   31G  87% /
after pull:  /dev/nvme0n1p1  233G  195G   28G  88% /   (image ~1.2GB added)
```

### `docker ps -a` before / after (pre-existing containers untouched)

```
edge-inspection-mosquitto, esk-jetson-rtsp-pub, esk-jetson-rtsp-server (all running)
```
identical before this task started and after cleanup; no `asrbench-*`
container remains (`docker ps -a` re-checked after `docker rm -f`).

### Missing-module chain (both caught by trying, not by reading code alone)

```
ModuleNotFoundError: No module named 'tensorrt'
  → fixed by mounting host CUDA/TensorRT libs per deploy/docker-compose.yml
ModuleNotFoundError: No module named 'sentencepiece'
  → pip install sentencepiece (runtime workaround, not a deployment fix)
ASR stream error (backend=sensevoice_trt): No module named 'kaldi_native_fbank'
  → silently produced ok:true + empty transcript per segment (discarded run,
    error_rate_mean 1.0 across all 4 concurrency levels)
  → pip install kaldi_native_fbank fixed it; re-ran the full sweep
```

### SenseVoice zh concurrency=1, full run (ok=20, errors=0, post-fix)

```json
{
  "concurrency": 1, "segments": 20, "ok": 20, "errors": 0,
  "final_latency_ms_p50": 113.18854195997119,
  "final_latency_ms_p95": 151.96305608842522,
  "rtf_p50": 0.018585840702797493, "rtf_p95": 0.03738884384520063,
  "error_rate_mean": 0.05990954715219421
}
```

### `execution_policy` override test (mounted profile, max_concurrent_sessions=4)

```
2026-09-09 00:20:39,868 [WARNING] server.core.session_limiter: session_limiter:
  profile.max_concurrent_sessions=4 exceeds backend ceiling (asr=1,tts=1) → clamping to 1
2026-09-09 00:20:39,869 [INFO] server.core.session_limiter:
  SessionLimiter initialized: effective_limit=1 (env OVS_MAX_CONCURRENT_SESSIONS=None,
  profile.max_concurrent_sessions=4)
```

### Whisper backend-registry / profile check

```
$ docker run --rm --entrypoint python3 .../seeed-local-voice:v0.9.0-ondemand-20260721c \
    -c "from voxedge.backends.jetson import whisper_trt"
ImportError: cannot import name 'whisper_trt' from 'voxedge.backends.jetson'

$ docker run --rm --entrypoint python3 .../seeed-local-voice:v0.9.0-ondemand-20260721c \
    -c "import sys; sys.path.insert(0,'/opt/speech'); from server.core.asr_backend import _ASR_REGISTRY; print(sorted(_ASR_REGISTRY.keys()))"
['cpu.sherpa_asr', 'jetson.paraformer_trt', 'jetson.sensevoice_trt', 'jetson.trt_edge_llm', 'rk.asr']

$ docker run --rm --entrypoint python3 .../seeed-local-voice:v0.9.0-ondemand-20260721c \
    -c "import voxedge; print(voxedge.__version__)"
0.0.5a0

$ git merge-base --is-ancestor 7cc9dd55 origin/main; echo $?
0   # IS an ancestor — Whisper commit is already on main (origin/main at
    #   time of this check: d932330e); the blocker is the stale image tag,
    #   not the source merge state (see "Whisper (en)" section above)
```

### Shared working tree caution (repo hygiene note for whoever reads this)

`~/project/openvoicestream` was being used concurrently by other dispatched
bench passes for other devices during this task (observed the checked-out
branch change under this task mid-run, from `bench-asr-work` to
`bench/results-radxa`, and a sibling `orin-nano-sensevoice-zh.{json,md}`
result pair appearing in the shared `results/` directory that this task did
not create). Verified this did not corrupt the orin-nx numbers above — the
`bench.py` actually executed included the `pre_eos_finals` field (only
present in the post-fix `64ef0573` version, confirmed via md5 comparison
against that commit) — but switched to an isolated `git worktree` at
`/Users/harvest/project/_worktrees/ovs-orin-nx` (branch
`bench/results-orin-nx`, based on `bench-asr-work`) for all further work and
this commit, to avoid clobbering or being clobbered by concurrent tasks in
the shared clone.
