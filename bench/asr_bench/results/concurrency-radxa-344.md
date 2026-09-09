# ASR bench: sensevoice / zh

- Target: `ws://100.77.150.16:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 100 | 0 | 1356.2 | 1668.0 | 0.295 | 0.463 | 0.15 | 0.0513 |
| 2 | 100 | 100 | 0 | 1359.8 | 1661.3 | 0.287 | 0.462 | 0.29 | 0.0513 |
| 4 | 100 | 100 | 0 | 1361.5 | 1694.9 | 0.284 | 0.519 | 0.57 | 0.0513 |
| 8 | 100 | 100 | 0 | 1477.3 | 1796.0 | 0.316 | 0.511 | 1.11 | 0.0513 |
| 12 | 100 | 100 | 0 | 1640.6 | 2491.3 | 0.364 | 0.626 | 1.50 | 0.0513 |
