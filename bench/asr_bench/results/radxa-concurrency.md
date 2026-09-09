# radxa (RK3588) — SenseVoice ASR concurrency, before/after

Date: 2026-09-09. Branch under test: `feat/rk-asr-concurrency`.

## Setup

| | |
|---|---|
| Device | radxa, RK3588, aarch64, 3 NPU cores |
| Model | `sense-voice-encoder.rk3588.fp16-scaled.rknn` (490 MB), downloaded from `hf-mirror.com/harvestsu/sensevoice-rknn` to `/home/radxa/svtest-scaled` |
| Image | `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:rk-20260903.10` (byte-identical `server/` and `voxedge/` to `openvoicestream:rk-20260903.10` — same md5 for `main.py`, `capability_resolver.py`, `voxedge/backends/rk/asr.py`) |
| Profile | `rk3588-sensevoice`, `execution_policy.mode=serialized`, `ASR_NPU_CORE_MASK=NPU_CORE_0` |
| Server flags | `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Corpus | same 20 zh items as the cat-remote run |
| Client | `bench/asr_bench/bench.py` from the Mac over Tailscale, 1.0x real-time feed |

**Concurrent load on the device.** The `edge_retail_console` stack
(`retail-web`, `retail-server`, `retail-mosquitto`) and four `mediamtx` RTSP
containers were running throughout both passes. These numbers are
"RK3588 with the retail stack resident", not an idle board. Both passes ran
under the same load, so the before/after comparison holds; the absolute
latencies are higher than an idle board would give.

A `sense-voice-encoder.rk3588.fp16.rknn` symlink points at the fp16-scaled
file, matching the workaround already used on cat-remote for the image's
hardcoded plain-fp16 filename.

## before — one session admitted

```
SessionLimiter initialized: effective_limit=1
```

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 1485.2 | 1966.6 | 0.280 | 0.467 | 0.13 | 0.0599 |
| 2 | 20 | 2 | 18 | 1461.9 | 1693.3 | 0.222 | 0.280 | 0.11 | 0.0333 |
| 4 | 20 | 1 | 19 | 1414.7 | 1414.7 | 0.236 | 0.236 | 0.13 | 0.0667 |
| 8 | 20 | 1 | 19 | 1366.6 | 1366.6 | 0.228 | 0.228 | 0.13 | 0.0667 |

Errors are `too_many_sessions` (WS 4429) at connect time.

## after — `ASR_MAX_SESSIONS=8`

```
SessionLimiter initialized: effective_limit=8
ASR inference gate: concurrency=1 max_waiting=7
ASR locking granularity: sentence (asr sessions=8, in-flight=1, queue depth=7, mode=serialized)
```

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 1477.8 | 1648.3 | 0.231 | 0.492 | 0.13 | 0.0599 |
| 2 | 20 | 20 | 0 | 1528.3 | 2613.9 | 0.303 | 0.560 | 0.25 | 0.0599 |
| 4 | 20 | 20 | 0 | 1926.7 | 2476.7 | 0.350 | 0.578 | 0.46 | 0.0599 |
| 8 | 20 | 8 | 12 | 3288.1 | 6190.1 | 0.801 | 1.053 | 0.55 | 0.0830 |

## Reading

- c=1, 2 and 4 complete with zero errors and CER 0.0599 — identical to before
  at c=1. Throughput 0.13 → 0.46 seg/s.
- **p95 ≤ 1.5 s is not met at any level on this device, including c=1**
  (1648 ms after, 1967 ms before). RK3588 here is roughly 2x slower per
  utterance than RK3576 on cat-remote (p50 ~1478 ms vs ~867 ms). The retail
  stack resident on the box and the Mac↔device round trip are both inside
  these numbers and neither has been separated out. Do not read this as
  "RK3588 is slower than RK3576" — that comparison needs an idle board and a
  device-local client.
- **The 12 errors at c=8 are still `too_many_sessions`**, with
  `{"current": 8, "limit": 8}` — not a queue rejection, not a timeout. The
  bench opens one connection per segment; with exactly 8 client workers and a
  ceiling of exactly 8, a worker's next connect can arrive before the previous
  connection's slot has been released. `main.py` documents this release lag on
  connection teardown (issue #41 P3). Deployment note: set the session ceiling
  above the expected client count, not equal to it.
- CER rises to 0.0830 at c=8, but only 8 of 20 segments were transcribed there,
  so that figure is over a different (smaller) sample than the other rows and
  is not comparable to them.

## NPU occupancy

`/sys/kernel/debug/rknpu/load` sampled every 2 s for 40 s during the after run:

```
15x  Core0:  0%, Core1: 0%, Core2: 0%
 1x  Core0: 73%, Core1: 0%, Core2: 0%
 1x  Core0: 67%, Core1: 0%, Core2: 0%
 1x  Core0: 59%, Core1: 0%, Core2: 0%
 1x  Core0: 16%, Core1: 0%, Core2: 0%
 1x  Core0: 11%, Core1: 0%, Core2: 0%
```

Core0 peaks at 73%; Core1 and Core2 never leave 0%. Two of three NPU cores are
idle for the whole run.
