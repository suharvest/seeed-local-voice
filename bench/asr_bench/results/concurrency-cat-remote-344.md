# ASR bench: sensevoice / zh

- Target: `ws://100.89.94.11:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 96 | 4 | 911.7 | 8487.1 | 0.216 | 2.200 | 0.11 | 0.0534 |
| 2 | 100 | 100 | 0 | 889.7 | 1509.4 | 0.207 | 0.353 | 0.31 | 0.0513 |
| 4 | 100 | 100 | 0 | 950.8 | 1484.9 | 0.206 | 0.432 | 0.60 | 0.0513 |
| 8 | 100 | 100 | 0 | 980.6 | 1504.0 | 0.232 | 0.380 | 1.18 | 0.0513 |
| 12 | 100 | 100 | 0 | 1218.2 | 2194.7 | 0.269 | 0.592 | 1.62 | 0.0513 |
