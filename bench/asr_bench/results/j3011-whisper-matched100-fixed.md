# ASR bench: whisper / en

- Target: `ws://100.92.125.65:8000`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 100 | 0 | 362.7 | 538.2 | 0.121 | 0.192 | 0.27 | 0.0886 |
