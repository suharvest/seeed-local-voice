# ASR concurrency — reComputer R2000 series (Pi 5 + Hailo-8, profile `rpi5-sensevoice`)

## What ran

Image built from `deploy/docker/Dockerfile.rpi` (`final-slim` target, 139 MB
content size) with `server/`, `configs/`, and the `voxedge` package
bind-mounted from the `feat/asr-admission-profiles` / `feat/asr-admission-ceiling`
worktrees, same pattern as the Jetson boards. Container started cleanly:

```
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS=None, profile.max_concurrent_sessions=8)
...
voxedge.backends.sherpa.asr: Loading SenseVoice model from /opt/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 (provider=cpu, use_itn=True, language=auto)
voxedge.backends.sherpa.asr: SenseVoice model loaded.
ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
Application startup complete.
```

`/readyz` returned `{"status":"ready"}` (HTTP 200) from both the device and
the Mac.

## No concurrency numbers — blocked, root-caused

All 80 requests (4 levels x 20 segments) against `/asr/stream` failed
immediately: the WebSocket is accepted, opens, and closes with code 1000
before any audio chunk is processed (`error: "received 1000 (OK); then sent
1000 (OK)"` on every segment, `feed_wall_ms: 0`, `eos_to_final_ms: 0`).
Container logs confirm this is a clean server-side close, not a network
failure: `"WebSocket /asr/stream?..." [accepted]` immediately followed by
`connection open` and `connection closed`, no exception, no ERROR line.

Root cause (source-verified, not inferred from behavior alone):

- `voxedge/backends/sherpa/asr.py:355-358` — `SherpaASRBackend.create_stream()`
  unconditionally builds a `SherpaASRStream` around `self._online_recognizer`;
  it never touches `self._offline_recognizer`.
- `voxedge/backends/sherpa/asr.py:310-315` — `capabilities` only includes
  `ASRCapability.STREAMING` when `self._online_recognizer is not None`.
- `configs/profiles/rpi5-sensevoice.json` sets `ENSURE_OFFLINE_ASR=1` /
  `OFFLINE_ASR_PROVIDER=cpu` only, which loads SenseVoice into
  `self._offline_recognizer`. `self._online_recognizer` (a Paraformer/Zipformer
  transducer, loaded only if `STREAMING_MODEL_DIR`/`STREAMING_ASR_PROVIDER`
  point at a *different*, streaming-capable model) is never populated by this
  profile.
- `server/main.py:5301-5305` gates on `has_capability(ASRCapability.STREAMING)`;
  when it is False, `server/main.py:5350-5352` sends
  `{"error": "no streaming ASR available"}` and closes with code 1000 — the
  exact behavior observed.
- Even if `STREAMING_MODEL_DIR` were set so `self._online_recognizer` loads
  (satisfying the capability gate), `create_stream()` still always returns a
  stream over the *online* (Paraformer/Zipformer) recognizer
  (`voxedge/backends/sherpa/asr.py:355-358`) — never SenseVoice's offline
  recognizer. So `/asr/stream` on this backend cannot be made to exercise
  SenseVoice by any profile/env combination in this codebase version.
- SenseVoice CPU is reachable only through the offline `POST /asr` and
  `POST /v1/asr` endpoints (`server/main.py:4964`, `server/main.py:5049`),
  which `bench/asr_bench/bench.py` does not call (WebSocket-only by design,
  see its module docstring).

This is a codebase-level gap between the `/asr/stream` benchmark harness and
the `rpi5-sensevoice` profile's actual backend wiring, not a device
limitation, a missing dependency, or a misconfigured container. No
concurrency/latency/CER numbers exist for SenseVoice-on-Pi5 via `/asr/stream`
in this codebase version; obtaining them requires either (a) a `bench.py`
mode that drives `POST /asr`/`POST /v1/asr` instead of the WebSocket, or (b)
a `create_stream()` change that can route to the offline recognizer per
request — both out of scope for this bench-only task.

## Model file confirmed (relevant to the CER 14.6% vs Jetson 5.99% question)

`voxedge/backends/sherpa/asr.py:468` loads `model.int8.onnx` from
`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` unconditionally — the
directory also contains a fp32 `model.onnx` (937 MB vs 239 MB for the int8
file) but the backend never selects it. On Jetson, `jetson-sensevoice.json`
runs a fp16 TensorRT engine built from `sense-voice-encoder.scaled.fixed.onnx`
(an activation-rescaled variant, per the profile description, "so Chinese
activations stay fp16-safe"). So the two boards are not running the same
weights at the same precision: Pi5 is int8 post-training-quantized sherpa-onnx
SenseVoice, Jetson is fp16 TensorRT with an activation-rescale fix applied
specifically for zh accuracy. A CER gap between int8 CPU decode and a zh-accuracy-tuned fp16 TensorRT
engine is consistent with quantization loss. The `/asr/stream` blocker above
means this run produced no CER number for Pi5 SenseVoice; a 14.6% figure
referenced in the task brief was not found in this worktree's checked-in
docs and is not confirmed by anything measured in this pass.
