# cat-remote (reComputer RK3576) — SenseVoice ASR on 2 NPU cores, before/after

Date: 2026-09-09. Under test: `rkvoice-stream` branch
`feat/sensevoice-multicore-workers` + `voxedge` branch `rk-parallel-stage-a`.

## Setup

| | |
|---|---|
| Device | reComputer RK3576 series, aarch64, 2 NPU cores |
| Model | `sense-voice-encoder.rk3576.fp16-scaled.rknn` (490 MB) |
| Image | `openvoicestream:rk-20260903.10` with the changed files bind-mounted |
| Profile | `rk3576-sensevoice`, `ASR_MAX_SESSIONS=8` |
| Server flags | `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Corpus | `bench/asr_bench/corpus`, 20 zh items (AISHELL-1 train-range mirror — a labeled subset for CER measurement, not the canonical test split) |
| Client | `bench/asr_bench/bench.py` from a Mac over Tailscale, chunks fed at 1.0x real time |
| Board state | no other containers running on the board during either pass |

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
ASR inference gate: concurrency=2 max_waiting=6
ASR locking granularity: sentence (asr sessions=8, in-flight=2, queue depth=6, mode=concurrent)
SenseVoice RKNN worker pool: 2 context(s) on NPU_CORE_0, NPU_CORE_1 (platform=rk3576)
```

## Results

| c | OK | p50 before | p50 after | p95 before | p95 after | RTF p50 before | RTF p50 after | seg/s before | seg/s after | CER |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 933.0 ms | 925.7 ms | 1382.4 ms | 1450.7 ms | 0.164 | 0.163 | 0.14 | 0.13 | 5.99% |
| 2 | 20/20 | 922.2 ms | 946.2 ms | 1653.7 ms | 1108.4 ms | 0.175 | 0.161 | 0.26 | 0.27 | 5.99% |
| 4 | 20/20 | 898.7 ms | 890.6 ms | 1518.0 ms | 1229.3 ms | 0.164 | 0.157 | 0.51 | 0.52 | 5.99% |
| 8 | 20/20 | 1418.7 ms | 1079.6 ms | 2569.7 ms | 1443.8 ms | 0.280 | 0.197 | 0.83 | 0.89 | 5.99% |

CER is 5.99% at every level in both passes — the same figure as the
single-session baseline.

## NPU occupancy

`/sys/kernel/debug/rknpu/load`, sampled every 2 s for the whole pass:

| | Core0 peak | Core1 peak |
|---|---|---|
| before | 78% | 0% |
| after | 76% | 71% |

## Reading

Throughput is set by the client: 20 segments fed at 1.0x real time across `c`
workers, so seg/s tracks `c` in both passes and is not a capacity measurement.
What moves is the tail. At c=8 p95 drops 2570 → 1443.8 ms (-44%) and p50
1418.7 → 1079.6 ms (-24%). At c=2 and c=4 p95 drops 33% and 19%; at c=1, where
there is nothing to overlap, p95 sits 68 ms higher, inside the run-to-run
spread of this corpus. Core1 goes from flat 0% to a 71% peak.

After the change p95 stays inside 1.5 s from c=1 to c=8; before it left that
bound at c=2.
