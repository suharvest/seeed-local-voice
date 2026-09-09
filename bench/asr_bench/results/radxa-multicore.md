# radxa (reComputer RK3588) — SenseVoice ASR on 3 NPU cores, before/after

Date: 2026-09-09. Under test: `rkvoice-stream` branch
`feat/sensevoice-multicore-workers` + `voxedge` branch `rk-parallel-stage-a`.

## Setup

| | |
|---|---|
| Device | reComputer RK3588 series, aarch64, 3 NPU cores |
| Model | `sense-voice-encoder.rk3588.fp16-scaled.rknn` (490 MB) |
| Image | `seeed-local-voice:rk-20260903.10` with the changed files bind-mounted |
| Profile | `rk3588-sensevoice`, `ASR_MAX_SESSIONS=8` |
| Server flags | `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Corpus | `bench/asr_bench/corpus`, 20 zh items (AISHELL-1 train-range mirror — a labeled subset for CER measurement, not the canonical test split) |
| Client | `bench/asr_bench/bench.py` from a Mac over Tailscale, chunks fed at 1.0x real time |
| Board state | the board's seven resident containers were stopped for both passes and restarted afterwards; NPU at 0% on all three cores and load average 0.18 at the start |

Latency is `eos_to_final_ms` — the EOS frame to the `is_final` message — so one
Mac↔device network round trip is inside every figure. Both passes were measured
identically.

**before** = the sentence-level FIFO queue alone (openvoicestream #80 /
voxedge #12): 8 sessions admitted, 1 inference in flight, one RKNNLite context
on Core0.

```
ASR inference gate: concurrency=1 max_waiting=7
ASR locking granularity: sentence (asr sessions=8, in-flight=1, queue depth=7, mode=serialized)
```

**after** = one RKNNLite context per NPU core, dispatched from a pool.

```
ASR inference gate: concurrency=3 max_waiting=5
ASR locking granularity: sentence (asr sessions=8, in-flight=3, queue depth=5, mode=concurrent)
SenseVoice RKNN worker pool: 3 context(s) on NPU_CORE_0, NPU_CORE_1, NPU_CORE_2 (platform=rk3588)
```

## Results

| c | OK | p50 before | p50 after | p95 before | p95 after | RTF p50 before | RTF p50 after | seg/s before | seg/s after | CER |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 1277.8 ms | 1410.7 ms | 1599.9 ms | 1696.0 ms | 0.219 | 0.242 | 0.14 | 0.13 | 5.99% |
| 2 | 20/20 | 1370.3 ms | 1421.2 ms | 2216.0 ms | 1517.6 ms | 0.261 | 0.235 | 0.26 | 0.25 | 5.99% |
| 4 | 20/20 | 1475.3 ms | 1361.5 ms | 2023.7 ms | 1567.6 ms | 0.263 | 0.235 | 0.49 | 0.49 | 5.99% |
| 8 | 20/20 | 3218.8 ms | 1501.0 ms | 6168.4 ms | 2037.1 ms | 0.576 | 0.269 | 0.71 | 0.85 | 5.99% |

CER is 5.99% at every level in both passes — the same figure as the
single-session baseline.

## NPU occupancy

`/sys/kernel/debug/rknpu/load`, sampled every 2 s for the whole pass:

| | Core0 peak | Core1 peak | Core2 peak |
|---|---|---|---|
| before | 83% | 0% | 0% |
| after | 70% | 70% | 71% |

## Reading

Throughput is set by the client: 20 segments fed at 1.0x real time across `c`
workers, so seg/s tracks `c` in both passes and is not a capacity measurement.
What moves is the tail. At c=8 p95 drops 6168.4 → 2037.1 ms (-67%) and p50
3218.8 → 1501.0 ms (-53%); at c=2 and c=4 p95 drops 32% and 23%. At c=1, where
there is nothing to overlap, p95 sits 96 ms higher, inside the run-to-run
spread of this corpus. Across the four levels p95 spans 520 ms after the
change against 4.6 s before. Core1 and Core2 go from flat 0% to 70% and 71%
peaks.

An earlier RK3588 pass on this board was taken with the retail console stack and
four mediamtx containers resident; those figures are not comparable to these.
