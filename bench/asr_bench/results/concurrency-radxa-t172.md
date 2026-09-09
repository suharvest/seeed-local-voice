# ASR bench: sensevoice / zh

- Target: `ws://100.77.150.16:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 100 | 0 | 727.4 | 971.4 | 0.148 | 0.254 | 0.16 | 0.0474 |
| 2 | 100 | 100 | 0 | 714.2 | 1317.0 | 0.156 | 0.325 | 0.32 | 0.0474 |
| 4 | 100 | 100 | 0 | 642.9 | 898.3 | 0.140 | 0.244 | 0.65 | 0.0474 |
| 8 | 100 | 100 | 0 | 658.6 | 902.1 | 0.141 | 0.257 | 1.27 | 0.0474 |
| 12 | 100 | 85 | 15 | 697.8 | 1290.3 | 0.158 | 0.307 | 1.02 | 0.0551 |
