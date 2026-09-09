# ASR bench: whisper / en

- Target: `ws://100.92.125.65:8000`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration
- Each concurrency level below was run as a separate `bench.py` invocation with a
  full container restart in between. A single continuous multi-level run (c=1
  immediately followed by c=2,4,8) showed the c=1 pass itself degrading
  (14/20 then 17/20 spurious `too_many_sessions` errors on later attempts,
  worsening across repeated same-session runs) even though `docker exec
  .../admin/backend/status` reported `inflight_ws: 0` between runs. A fresh
  `docker restart` before each isolated level produced clean, reproducible
  numbers; the concurrency>=2 result (server-enforced session cap) was
  reproduced identically in both the continuous and isolated runs. Treat the
  continuous-run degradation as an open issue, suspected to be in
  `jetson.whisper_trt`'s session/executor cleanup path rather than in
  `bench.py`'s client — not root-caused within this pass, see report body.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 373.0 | 742.6 | 0.055 | 0.109 | 0.114 | 0.0362 |
| 2 | 20 | 1 | 19 | 288.8 | 288.8 | 0.083 | 0.083 | 0.240 | 0.125 |
| 4 | 20 | 1 | 19 | 270.4 | 270.4 | 0.077 | 0.077 | 0.240 | 0.125 |
| 8 | 20 | 1 | 19 | 262.4 | 262.4 | 0.075 | 0.075 | 0.240 | 0.125 |
