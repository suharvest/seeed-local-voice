# ASR bench: sensevoice / zh

- Target: `ws://100.116.230.60:8000`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 20 | - | - | - | - | 0.00 | - |
| 2 | 20 | 0 | 20 | - | - | - | - | 0.00 | - |
| 4 | 20 | 0 | 20 | - | - | - | - | 0.00 | - |
| 8 | 20 | 0 | 20 | - | - | - | - | 0.00 | - |
