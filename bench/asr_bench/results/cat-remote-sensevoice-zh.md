# ASR bench: sensevoice / zh

- Target: `ws://100.89.94.11:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 777.5 | 945.5 | 0.135 | 0.279 | 0.15 | 0.0599 |
| 2 | 20 | 1 | 19 | 755.3 | 755.3 | 0.126 | 0.126 | 0.15 | 0.0667 |
| 4 | 20 | 1 | 19 | 766.0 | 766.0 | 0.128 | 0.128 | 0.15 | 0.0667 |
| 8 | 20 | 1 | 19 | 806.7 | 806.7 | 0.134 | 0.134 | 0.14 | 0.0667 |
