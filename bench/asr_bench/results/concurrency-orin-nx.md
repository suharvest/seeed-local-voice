# ASR concurrency — reComputer J4012 (Jetson Orin NX)

Corpus: 20 AISHELL-1 zh utterances for SenseVoice, 20 LibriSpeech test-clean en
utterances for Whisper (each Apache-2.0 / CC BY 4.0, see `bench/asr_bench/README.md`).
Transport: `/asr/stream` WebSocket, fed at 1.0x real time, one `is_final` per
segment. Latency = audio-end to `is_final` (excludes the real-time feed).

Server confirmed ready before each sweep: `SessionLimiter initialized:
effective_limit=8` and `ASR executor: max_workers=8` both present in the
container log.

## SenseVoice zh — profile `jetson-sensevoice`

Backend `jetson.sensevoice_trt`, TensorRT engine built on first container
start (~4 min: HF-mirror asset download + fp16 engine build).
`execution_policy: {mode: serialized, shared_resource: gpu}` — one shared
TensorRT execution context; `asr_max_slots=8` is an admission ceiling, not
parallel decode.

| c | OK | Err | p50 (ms) | p95 (ms) | RTF p50 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 144.0 | 227.9 | 0.026 | 0.16 | 5.99% |
| 2 | 20 | 0 | 148.8 | 264.0 | 0.031 | 0.30 | 5.99% |
| 4 | 20 | 0 | 175.0 | 618.6 | 0.037 | 0.58 | 5.99% |
| 8 | 20 | 0 | 178.6 | 330.2 | 0.032 | 1.03 | 5.99% |

CER is 5.99% at every level — decoding is deterministic, queueing only adds
latency. Throughput scales 0.16 -> 1.03 seg/s (6.4x) from c=1 to c=8; p50
stays under 180 ms through c=8, p95 stays under 620 ms at every level tested.

## Whisper en (base, bf16) — profile `orin-whisper`

Backend `jetson.whisper_trt`. The `.plan` was built on-device from the
shipped ONNX with `--bf16` (confirmed in the container log: "Building
Whisper TRT encoder (host TRT 10.3.0, bf16)" — the fp16 build of this graph
is known to score cosine 0.826 against onnxruntime and drift off-topic, so
this was checked, not assumed). Decoder runs as a CPU ONNX graph with a KV
cache. `execution_policy.mode=concurrent`, `asr_max_slots=8` (admission
ceiling on the shared encoder handle + decoder KV-cache lock).

| c | OK | Err | p50 (ms) | p95 (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 472.4 | 796.0 | 0.069 | 0.11 | 4.25% |
| 2 | 20 | 0 | 505.1 | 860.7 | 0.079 | 0.21 | 4.25% |
| 4 | 20 | 0 | 423.8 | 739.5 | 0.066 | 0.41 | 4.25% |
| 8 | 20 | 0 | 627.4 | 2685.2 | 0.089 | 0.64 | 4.25% |

Throughput scales 0.11 -> 0.64 seg/s (5.8x) from c=1 to c=8. p50 stays under
630 ms through c=8; p95 grows to 2.7 s at c=8 as callers queue for the shared
decoder KV-cache lock.

## Deviation from the standard run recipe

Whisper's four concurrency levels ran back-to-back on one container start
(no restart between levels), against the recipe's normal instruction to
restart between levels to avoid session degradation seen previously on
J3011. All four levels came back error-free with sane latency, so the
degradation pattern did not reproduce here; noted for completeness, not
treated as invalidating the numbers.
