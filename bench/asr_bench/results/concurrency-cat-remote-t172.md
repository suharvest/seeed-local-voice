# ASR bench: sensevoice / zh

- Target: `ws://100.89.94.11:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 100 | 0 | 535.7 | 1802.4 | 0.123 | 0.543 | 0.16 | 0.0474 |
| 2 | 100 | 100 | 0 | 539.5 | 922.1 | 0.121 | 0.233 | 0.32 | 0.0474 |
| 4 | 100 | 100 | 0 | 539.1 | 933.8 | 0.123 | 0.202 | 0.65 | 0.0474 |
| 8 | 100 | 100 | 0 | 544.6 | 867.2 | 0.126 | 0.237 | 1.26 | 0.0474 |
| 12 | 100 | 100 | 0 | 583.4 | 1067.1 | 0.133 | 0.315 | 1.81 | 0.0474 |
