# ASR bench: sensevoice / zh

- Target: `ws://100.82.225.102:8000`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 113.2 | 152.0 | 0.019 | 0.037 | 0.17 | 0.0599 |
| 2 | 20 | 1 | 19 | 144.9 | 144.9 | 0.037 | 0.037 | 0.24 | 0.0000 |
| 4 | 20 | 1 | 19 | 76.3 | 76.3 | 0.020 | 0.020 | 0.25 | 0.0000 |
| 8 | 20 | 1 | 19 | 62.8 | 62.8 | 0.016 | 0.016 | 0.24 | 0.0000 |
