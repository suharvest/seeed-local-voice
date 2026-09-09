# SenseVoice ASR concurrency — reComputer J3011 (Jetson Orin Nano 8GB)

Corpus: 20 AISHELL-1 zh utterances (Apache-2.0), 115.0 s of audio total.
Transport: `/asr/stream` WebSocket, fed at 1.0x real time in 8 KB chunks, one
`is_final` awaited per segment. Latency below is end-of-audio to `is_final`,
so it excludes the real-time feed and measures decode plus queueing only.

Profile `orin-nano-sensevoice-asr`: `asr_max_slots=8`,
`max_concurrent_sessions=8`, `execution_policy.mode=serialized`.
Backend `jetson.sensevoice_trt`, one TensorRT execution context.
Server reports `SessionLimiter effective_limit=8`, `ASR executor max_workers=8`.

| Concurrency | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Aggregate audio RTF | CER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 136 | 311 | 0.0244 | 0.0905 | 0.160 | 0.92 | 5.99% |
| 2 | 20 | 0 | 144 | 2470 | 0.0226 | 0.6251 | 0.296 | 1.71 | 5.99% |
| 4 | 20 | 0 | 359 | 2552 | 0.0581 | 0.6385 | 0.506 | 2.91 | 5.99% |
| 8 | 20 | 0 | 3389 | 8885 | 0.5175 | 2.7217 | 0.664 | 3.82 | 5.99% |

## What the numbers say

Zero errors at every level. Before the admission change this profile admitted
one session, so c=2, c=4 and c=8 returned 429 for every request past the first
and no latency figure existed for them.

CER is 5.99% at all four levels — the same value to four decimals. Decoding is
deterministic and queueing does not touch it, so concurrency costs latency, not
accuracy.

Throughput rises 0.160 → 0.296 → 0.506 → 0.664 segments/s, i.e. 1.85x, 3.16x
and 4.15x over c=1. Aggregate audio RTF flattens at 3.82: eight callers are
sharing one execution context, so past roughly four in flight the extra
sessions add queue time rather than work.

p50 stays under 360 ms through c=4 and reaches 3.39 s at c=8. p95 is the figure
that separates the operating points: 311 ms at c=1, about 2.5 s at both c=2 and
c=4, then 8.9 s at c=8. Moving from c=4 to c=8 buys 31% more throughput for
3.5x the p95.

GPU occupancy sampled with `tegrastats` during the run peaked at GR3D_FREQ 31%
with the board at 7.6-8.9 W and 2.68 GB of 7.62 GB RAM in use.

## Reading this for a deployment

Four concurrent capture points is the point where this board still answers
inside a few seconds at the 95th percentile. Eight is admissible — nothing is
rejected — but a caller must tolerate a ~9 s tail.
