# orin-nano (Jetson Orin Nano, reComputer J3011) — ASR bench results

Date: 2026-09-08/09. Image: `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
(pulled fresh on-device; this is the compose default in `deploy/docker-compose.yml`,
confirmed as *not* already present via `docker images` before the pull).
`server/` and `configs/` inside the container were overlay-mounted from the
locally fetched `bench/asr-bench` branch checkout (see "Image gaps" below) —
model artifacts and TensorRT engines were still built/downloaded on-device,
nothing was cross-compiled or copied in from elsewhere.

## Result tables

See `orin-nano-sensevoice-zh.md` and `orin-nano-whisper-en.md` in this directory
for the per-model tables (also duplicated below). Raw per-segment data:
`orin-nano-sensevoice-zh.json`, `orin-nano-whisper-en.json`. Resource sampling:
`orin-nano-tegrastats.log` (1 Hz, 1626 samples spanning both bench passes).

### SenseVoice (zh, `jetson-sensevoice` / `jetson.sensevoice_trt`)

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 111.1 | 148.9 | 0.021 | 0.026 | 0.17 | 0.0599 |
| 2 | 20 | 1 | 19 | 121.6 | 121.6 | 0.020 | 0.020 | 0.16 | 0.0667 |
| 4 | 20 | 1 | 19 | 133.5 | 133.5 | 0.022 | 0.022 | 0.16 | 0.0667 |
| 8 | 20 | 1 | 19 | 88.9 | 88.9 | 0.015 | 0.015 | 0.16 | 0.0667 |

TensorRT engine build (first container start, cold model dir): ~3m34s
(23:51:07 → 23:54:41 in container logs; `sensevoice.plan`, 479,943,852 bytes).

### Whisper (en, `orin-whisper` / `jetson.whisper_trt`, base/30s, bf16)

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 373.0 | 742.6 | 0.055 | 0.109 | 0.114 | 0.0362 |
| 2 | 20 | 1 | 19 | 288.8 | 288.8 | 0.083 | 0.083 | 0.240 | 0.125 |
| 4 | 20 | 1 | 19 | 270.4 | 270.4 | 0.077 | 0.077 | 0.240 | 0.125 |
| 8 | 20 | 1 | 19 | 262.4 | 262.4 | 0.075 | 0.075 | 0.240 | 0.125 |

TensorRT engine build (bf16, first container start): ~1m1s (00:14:46 →
00:15:47; `enc_base_30s_bf16.plan`, 44,433,164 bytes). Build precision
confirmed as bf16 both from the build log line ("Building Whisper TRT
encoder (host TRT 10.3.0, bf16)") and from transcript sanity (all 20 en
segments returned coherent, on-topic English text matching the LibriSpeech
reference — see `orin-nano-whisper-en.json`, e.g. `en_pub_00`: "Concord.
return to its place amidst the tents." vs ref "CONCORD RETURNED TO ITS
PLACE AMIDST THE TENTS"). `bench/perf/whisper/cmp_engine_precision.py` was
**not** run (it expects a pre-populated `/home/harvest/whisper-bench`
fixture directory that doesn't exist on this box) — the transcript-based
check above is a substitute, not a replacement, for that numeric cosine
check.

## Concurrency: both profiles hard-cap at 1 session, confirmed not overridable

Both profiles reject concurrency>=2 with a WS 4429
`{"error":"too_many_sessions","current":1,"limit":1}`, matching the
cat-remote RK3576 pattern in the matrix doc. This was cross-checked against
`server/core/session_limiter.py` and `server/core/capability_resolver.py`:

- `jetson-sensevoice`: `execution_policy.mode="serialized"`,
  `shared_resource="gpu"`. `max_concurrent_sessions` is unset in the profile
  JSON, so the ceiling comes from the backend's declared
  `ConcurrencyCapability` (`jetson.sensevoice_trt` → `max_concurrent=1`;
  server log: `ASR executor: max_workers=1 (source=asr_cap.max_concurrent)`).
- `orin-whisper`: `execution_policy.mode="concurrent"` in the profile JSON
  (contradicting its own `max_concurrent_sessions: 1` field one line below —
  the same profile declares both "concurrent" and a hard cap of 1; the
  cap wins). Server log confirms:
  `coordinator: downgrading concurrent -> serialized (asr.supports_parallel=False/max=1, ...)`.
- **Tested whether the cap can be "opened up"**, per dispatch instruction:
  restarted `jetson-sensevoice` with `OVS_MAX_CONCURRENT_SESSIONS=8` and
  re-ran the full concurrency sweep. `effective_limit` stayed at 1
  (`SessionLimiter initialized: effective_limit=1 (env
  OVS_MAX_CONCURRENT_SESSIONS='8', profile.max_concurrent_sessions=None)`),
  and concurrency=2..8 still failed identically. Root cause, confirmed by
  reading `capability_resolver.py`: the env override is clamped to
  `min(env, backend-declared max_concurrent)`, and `jetson.sensevoice_trt`
  declares `max_concurrent=1` as a hard capability (single TensorRT
  execution context, `ASR executor: max_workers=1`) — this is a backend
  capability ceiling, not a soft config knob, and is not raisable without a
  code change to the backend's `concurrency_capability()`. Recorded here as
  verified, not assumed.

## Whisper-only anomaly: session state degrades across concurrency levels within one continuous run

Running `bench.py --concurrency 1,2,4,8` as a single invocation against
`orin-whisper` produced a *worsening* pattern of spurious
`too_many_sessions` rejections even at concurrency=1 (14/20 errors on the
first pass, 17/20 on a same-session re-run of concurrency=1 alone) —
despite `curl .../admin/backend/status` reporting `inflight_ws: 0` between
runs (no visibly stuck slot). A `docker restart` before each isolated
concurrency level produced clean results every time (see the Whisper table
above and the note in `orin-nano-whisper-en.md`), and the concurrency>=2
hard-fail was reproduced identically with or without the restart, so that
result is not in question — only the *sequencing* is unreliable. SenseVoice
did not show this: its own single continuous 1,2,4,8 run stayed consistent
(c=1 clean, c=2/4/8 each rejecting 19/20 and passing 1/20, not degrading
further across levels). This looks like a session/executor cleanup issue
specific to `jetson.whisper_trt` (new backend, first real run on this repo
version) rather than a `bench.py` bug — flagged here, not root-caused
further within this pass's time budget.

## Image gaps found and worked around (all logged as EVIDENCE below)

The compose-default image `v0.9.0-ondemand-20260721c` (built 2026-07-21)
predates both ASR backends being benched (SenseVoice landed 2026-06-10,
Whisper landed 2026-08-28 — `git log` on `configs/profiles/{jetson-sensevoice,orin-whisper}.json`).
No other locally cached Jetson image on this box (checked full `docker
images` list) is more recent than 2026-07-21 either. Fixes applied, in the
running containers only, not persisted to any image or registry:

1. `voxedge` (the PyPI ASR/TTS runtime library) was pinned in the image at
   `0.0.5a0`. `jetson.sensevoice_trt` preload failed with `ModuleNotFoundError:
   No module named 'sentencepiece'` and, once that was patched, `... No module
   named 'kaldi_native_fbank'` — both are `voxedge` runtime deps not bundled
   in this image's site-packages. Installed both via `pip install
   --index-url https://pypi.tuna.tsinghua.edu.cn/simple sentencepiece
   kaldi_native_fbank` inside the running container; no restart needed for
   `kaldi_native_fbank` (imported lazily per-call), one `docker restart` for
   `sentencepiece` (imported at ASR preload).
2. `jetson.whisper_trt` doesn't exist at all in `voxedge==0.0.5a0`
   (`voxedge/backends/` has no `whisper/` package). Checked PyPI
   (`pypi.tuna.tsinghua.edu.cn/simple/voxedge/`): latest is `0.0.13a0`, which
   does ship `voxedge/backends/whisper/{asr,decoder,encoders,frontend}.py`.
   Upgraded to `0.0.13a0` in the whisper container only (left the SenseVoice
   container on `0.0.5a0` — SenseVoice already worked there and mixing
   changes was avoidable).
3. `configs/profiles/orin-whisper.json` doesn't exist in this image either
   (same reason — added 2026-08-28, image built 2026-07-21). The application
   code layer (`server/core/asr_backend.py`'s `_ASR_REGISTRY` dict) baked
   into this image also has zero `whisper` references — confirmed by
   `docker exec ... grep -n whisper /opt/speech/server/core/asr_backend.py`
   returning nothing. Per `deploy/docker/Dockerfile.jetson.edgellm-v090-ondemand`
   (`COPY server/ /opt/speech/server/`, `COPY configs/ /opt/speech/configs/`
   — plain copies, no compilation), this is reproducible without a rebuild:
   bind-mounted the locally fetched (`git fetch origin`, `bench/asr-bench`
   branch) repo's `server/` and `configs/` directories over the image's
   copies (`-v .../repo/server:/opt/speech/server:ro`, same for `configs`).
   This is exactly what a real image rebuild from the current branch would
   produce, without running the actual build.
4. Whisper's vocab loader (`voxedge/backends/whisper/decoder.py:read_vocab`)
   opens `vocab_zh.txt` (UTF-8, contains CJK text) without an explicit
   encoding, and Python's `open()` fell back to ASCII in this container
   (`UnicodeDecodeError: 'ascii' codec can't decode byte 0xc2 ...`) despite
   `LANG=C.UTF-8` being set at the image level — `LC_ALL` was apparently not
   propagated the same way. Fixed by adding `-e PYTHONUTF8=1 -e
   LC_ALL=C.UTF-8` to the container's env (forces UTF-8 text-mode I/O
   regardless of locale detection). This is a `voxedge` library bug
   (missing `encoding="utf-8"` on the `open()` call), not something fixed by
   the profile/server overlay — worth a small upstream patch pass to
   `voxedge`, not done here (out of scope for this bench pass; container-level
   env workaround only).

None of the above touched the shared `speech-models` or
`seeed-local-voice-data` volumes' pre-existing contents (only added new
subdirectories the app itself wrote), nor any other running container.

## Docker/disk discipline

- `docker ps -a` and `df -h /` were checked before any change (see EVIDENCE).
  Pre-existing containers `edge-inspection-assembly-app`,
  `edge-inspection-assembly-mosquitto`, `ovs-sv-test` were left untouched.
- Disk: 87% used / 32G free before, 87% used / 30G free after (net ~2GB: the
  `v0.9.0-ondemand-20260721c` image pull + SenseVoice/Whisper model+engine
  artifacts written to the `speech-models` named volume). No headroom
  concern at any point (never below 25G free).
- All bench containers (`asrbench-orin-sv`, `asrbench-orin-whisper`) were
  `docker rm -f`'d at the end of this pass. Temp files under
  `/home/harvest/asrbench-profiles` and `/tmp/tegrastats-sv.log` were
  removed from the device.

## Resource sampling

`orin-nano-tegrastats.log`, 1 Hz, spans both bench passes (~27 min). Peak
observed: `GR3D_FREQ` (GPU) up to 31% (SenseVoice's TRT engine is small;
Whisper's encoder likewise light per-call — neither backend saturates the
GPU at these concurrency levels, consistent with concurrency being capped
by the session limiter rather than by compute headroom). Peak RAM 4664 MB
of 7620 MB available. No thermal throttling observed (gpu/tj temps stayed
in the 58-60C range throughout).

## What this pass did NOT do

- Did not run `cmp_engine_precision.py` (missing fixture directory on this
  box) — substituted a transcript-sanity check (see Whisper section above).
- Did not root-cause the Whisper continuous-run session degradation
  (worked around via per-level container restarts; flagged as an open
  issue for whoever next touches `jetson.whisper_trt`).
- Did not patch `voxedge`'s `read_vocab` UTF-8 bug upstream; only worked
  around it at the container-env level for this bench pass.
- Did not touch orin-nx (J4012), radxa (RK3588), or harvest-pi (Pi5+Hailo)
  — those remain per the DISPATCH per-device sections not yet run, same as
  the matrix doc's existing "What this task did NOT do" section.

## EVIDENCE

### docker ps -a / df -h before any change

```
CONTAINER ID   IMAGE                                               NAMES
519621c77493   edge-inspection-assembly-jetson:0.1.0-dev           edge-inspection-assembly-app
00f41ef3f469   docker.m.daocloud.io/library/eclipse-mosquitto:2    edge-inspection-assembly-mosquitto
7b7a8955ab8b   seeed-local-voice:edgellm-v010-production-001128d   ovs-sv-test

/dev/nvme0n1p1  233G  192G   32G  87% /
```

### Missing v0.9.0-ondemand image, pulled fresh

```
$ docker images | grep ondemand   # (empty before pull)
$ docker pull sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c
...
Digest: sha256:2004b95437518cfc5ceec963c9db0055b43f2e5dbb613ba3263f874db0d5a115
Status: Downloaded newer image for ...v0.9.0-ondemand-20260721c
```

### SenseVoice missing deps

```
2026-09-08 23:54:43,819 [WARNING] server.main: ASR backend failed: No module named 'sentencepiece'
...
2026-09-08 23:58:52,512 [ERROR] server.main: ASR stream error (backend=sensevoice_trt): No module named 'kaldi_native_fbank'
```

### Whisper: unknown backend on stock image code, then missing profile file, then UTF-8 crash

```
2026-09-09 00:13:07,046 [WARNING] server.main: ASR backend failed: Unknown asr_backend: 'jetson.whisper_trt'
```
```
FileNotFoundError: [Errno 2] No such file or directory: '/opt/speech/configs/profiles/orin-whisper.json'
```
```
File "/usr/local/lib/python3.10/dist-packages/voxedge/backends/whisper/decoder.py", line 141, in read_vocab
    for line in f:
UnicodeDecodeError: 'ascii' codec can't decode byte 0xc2 in position 463: ordinal not in range(128)
```

### Session cap confirmed not overridable (jetson-sensevoice)

```
SessionLimiter initialized: effective_limit=1 (env OVS_MAX_CONCURRENT_SESSIONS='8', profile.max_concurrent_sessions=None)
```
(with `OVS_MAX_CONCURRENT_SESSIONS=8` set on the container; concurrency=2..8
still returned `too_many_sessions` with `"limit": 1`.)

### Cleanup confirmation

```
$ docker rm -f asrbench-orin-sv asrbench-orin-whisper
$ docker ps -a | grep asrbench   # (empty)
$ df -h /
/dev/nvme0n1p1  233G  194G   30G  87% /
```
