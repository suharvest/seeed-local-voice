# ASR bench: sensevoice / en

- Target: `ws://100.77.150.16:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 96 | 4 | 637.9 | 1187.0 | 0.117 | 0.275 | 0.12 | 0.0424 |
