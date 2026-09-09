# ASR bench: sensevoice / zh

- Target: `ws://127.0.0.1:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 641.5 | 856.8 | 0.106 | 0.115 | 0.15 | 0.0548 |
| 2 | 20 | 20 | 0 | 622.3 | 824.3 | 0.103 | 0.117 | 0.30 | 0.0548 |
| 4 | 20 | 20 | 0 | 620.1 | 865.7 | 0.105 | 0.117 | 0.58 | 0.0548 |
| 8 | 20 | 20 | 0 | 851.5 | 2280.2 | 0.125 | 0.274 | 1.00 | 0.0548 |
