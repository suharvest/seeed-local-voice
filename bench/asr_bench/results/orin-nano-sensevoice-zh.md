# ASR bench: sensevoice / zh

- Target: `ws://100.92.125.65:8000`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 111.1 | 148.9 | 0.021 | 0.026 | 0.17 | 0.0599 |
| 2 | 20 | 1 | 19 | 121.6 | 121.6 | 0.020 | 0.020 | 0.16 | 0.0667 |
| 4 | 20 | 1 | 19 | 133.5 | 133.5 | 0.022 | 0.022 | 0.16 | 0.0667 |
| 8 | 20 | 1 | 19 | 88.9 | 88.9 | 0.015 | 0.015 | 0.16 | 0.0667 |
