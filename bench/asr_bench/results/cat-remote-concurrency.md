# cat-remote (RK3576) — SenseVoice ASR concurrency, before/after

Date: 2026-09-09. Branch under test: `feat/rk-asr-concurrency`.

## Setup

| | |
|---|---|
| Device | cat-remote, RK3576, aarch64, 2 NPU cores |
| Model | `sense-voice-encoder.rk3576.fp16-scaled.rknn` (490 MB), mounted from `/home/cat/svtest-scaled` |
| Image | `openvoicestream:rk-20260903.10` |
| Profile | `rk3576-sensevoice`, `execution_policy.mode=serialized`, `ASR_NPU_CORE_MASK=NPU_CORE_0` |
| Server flags | `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Corpus | `bench/asr_bench/corpus`, 20 zh items (AISHELL-1 train-range mirror — a labeled subset for CER measurement, **not** the canonical AISHELL-1 test split) |
| Client | `bench/asr_bench/bench.py`, run from the Mac over Tailscale, chunks fed at 1.0x real time |

Latency is `eos_to_final_ms`: the empty-binary EOS frame to the `is_final`
message, so it includes one Mac↔device network round trip. Both columns were
measured the same way, so the before/after comparison is unaffected; the
absolute numbers are not device-local latency.

**after** = the same image with four files bind-mounted over it:
`server/main.py`, `server/core/capability_resolver.py`,
`server/core/asr_infer_gate.py` and
`voxedge/backends/rk/asr.py`, plus `ASR_MAX_SESSIONS=8`.

## before — one session admitted, the rest refused

```
SessionLimiter initialized: effective_limit=1
ASR executor: max_workers=1 (source=asr_cap.max_concurrent)
```

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 778.0 | 978.0 | 0.135 | 0.243 | 0.15 | 0.0599 |
| 2 | 20 | 1 | 19 | 779.6 | 779.6 | 0.130 | 0.130 | 0.15 | 0.0667 |
| 4 | 20 | 1 | 19 | 747.0 | 747.0 | 0.124 | 0.124 | 0.14 | 0.0667 |
| 8 | 20 | 1 | 19 | 861.9 | 861.9 | 0.144 | 0.144 | 0.14 | 0.0667 |

The 19 errors at each level are `too_many_sessions` (WS close 4429) at connect
time — server-enforced admission, not a timeout or a crash. The single
surviving session's latency is unchanged across levels, which is what "the
other 19 never reached the NPU" looks like.

## after — every session admitted, inference still serial

```
SessionLimiter initialized: effective_limit=8
ASR inference gate: concurrency=1 max_waiting=7
ASR locking granularity: sentence (asr sessions=8, in-flight=1, queue depth=7, mode=serialized)
```

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 867.3 | 1276.4 | 0.160 | 0.278 | 0.14 | 0.0599 |
| 2 | 20 | 20 | 0 | 864.5 | 1219.4 | 0.145 | 0.339 | 0.27 | 0.0599 |
| 4 | 20 | 20 | 0 | 1043.3 | 1346.9 | 0.180 | 0.416 | 0.50 | 0.0599 |
| 8 | 20 | 20 | 0 | 1363.6 | 2733.0 | 0.290 | 0.411 | 0.87 | 0.0599 |

Zero errors at every level. No `busy` frame was emitted: with 8 sessions and a
queue depth of 7, a simultaneous endpoint on all of them fills the queue
exactly without overflowing it.

## Reading

- **p95 ≤ 1.5 s holds through c=4** (1346.9 ms) and breaks at c=8 (2733.0 ms).
  Max supported N on this device by that bar: **4**.
- Throughput scales 0.15 → 0.87 seg/s, 5.8x from c=1 to c=8, on hardware whose
  in-flight inference count never left 1. The headroom was queueing, not
  compute.
- CER is 0.0599 at every concurrency level, identical to the before c=1 figure.
  Queueing changes when an utterance is decoded, not what comes out.
- c=1 p50 moved 778.0 → 867.3 ms (+89 ms) and p95 978.0 → 1276.4 ms. These runs
  are 20 items each and the before/after c=1 p95 spread across the two earlier
  cat-remote passes was already 945-978 ms, so a single-run delta of this size
  is not separable from run-to-run variance at n=20. Whether the gate costs the
  single-session path anything needs a repeated-run comparison, not this one
  number.

## NPU occupancy

Sampled `/sys/kernel/debug/rknpu/load` every 2 s for 50 s during the after run:

```
17x  Core0:  0%, Core1: 0%
 2x  Core0: 53%, Core1: 0%
 1x  Core0: 59%, Core1: 0%
 1x  Core0: 54%, Core1: 0%
 1x  Core0: 51%, Core1: 0%
 1x  Core0: 38%, Core1: 0%
 1x  Core0: 25%, Core1: 0%
 1x  Core0: 12%, Core1: 0%
```

Core0 peaks at 59% and Core1 never leaves 0% — the second NPU core is unused,
because the profile pins `NPU_CORE_0` and rkvoice-stream holds one RKNN
context. That is the remaining ceiling and what stage a would address.
