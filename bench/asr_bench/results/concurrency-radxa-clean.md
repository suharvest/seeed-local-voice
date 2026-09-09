# ASR bench: sensevoice / zh — radxa (RK3588), rknn-toolkit2 2.3.2 rebuild, clean board

Date: 2026-09-09. Device: radxa (reComputer RK3588 series). Model:
`sense-voice-encoder.rk3588.fp16-scaled.rknn` rebuilt with rknn-toolkit2 2.3.2
from the same source ONNX (`sense-voice-encoder.scaled.fixed.onnx`,
sha256 `ebfdbe96...ac3c1d`) that produced the toolkit-2.2.0 file already in
production. Board state: the 7 resident containers (`retail-web`,
`retail-server`, `retail-mosquitto`, `esk-rk-rtsp-{pub,server}`,
`fall-rtsp-{pub,server}`) were stopped for this run and restarted afterward
(`docker ps -a` before/after identical). Only c=1 is reported: this base
image (`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:rk-20260903.10`)
reports `SessionLimiter initialized: effective_limit=1` without the
worker-pool bind-mount patch used in `radxa-multicore.md`, which is a
concurrency feature independent of the model file under test here.

- Target: `ws://100.77.150.16:8621`
- Metric: final latency = audio-end -> `is_final` received (ms); RTF = final_latency / audio_duration

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | Mean error rate |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 20 | 0 | 1422.5 | 1703.7 | 0.244 | 0.381 | 0.13 | 0.0599 |

CER 0.0599 — identical to the toolkit-2.2.0 model's c=1 baseline in
`radxa-before.md`/`radxa-concurrency.md` (c>=2 in those files carries
`too_many_sessions` errors and a different CER because most sessions never
reach the NPU, so c=1 is the only directly comparable row).

## Single-core NPU inference microbenchmark (toolkit 2.2.0 vs 2.3.2)

`core_probe.py`, `rknnlite.api.RKNNLite` direct load, `core_mask=NPU_CORE_0`,
30 iterations after 1 warmup, native (no Docker), board otherwise idle
(retail stack up throughout — this table is not the "clean" board state used
for the c=1 WebSocket run above):

| toolkit | run | mean (ms) | p50 (ms) | min / max (ms) |
|---|---|---|---|---|
| 2.2.0 (production) | 1 | 1180.2 | 1184.6 | 990.2 / 1421.1 |
| 2.2.0 (production) | 2 | 1190.7 | 1201.5 | 1014.5 / 1438.6 |
| 2.3.2 (this rebuild) | 1 | 1167.6 | 1186.3 | 971.9 / 1335.3 |
| 2.3.2 (this rebuild) | 2 | 1144.9 | 1175.8 | 971.3 / 1327.3 |

2.3.2 averages 1156.3 ms across its two runs against 1185.5 ms for 2.2.0 —
a 29.2 ms (2.5%) difference. Two runs per version is not enough to establish
this as a reproducible speedup rather than measurement noise: each run's
own min/max already spans 350-450 ms (2.2.0: 990.2-1438.6 ms across its two
runs; 2.3.2: 971.3-1335.3 ms), and the run-to-run mean spread within a
single toolkit version (10.5 ms for 2.2.0, 22.7 ms for 2.3.2) is itself a
fraction of the 29.2 ms gap between versions. Both files carry the same
`RKNN_QUERY_INPUT_DYNAMIC_RANGE` static-shape warning at load.

## Conclusion

Rebuilding the RK3588 SenseVoice encoder with rknn-toolkit2 2.3.2 (matching
the RK3576 build's toolkit version) shows a small (2.5%) mean latency
reduction that these two-runs-per-version measurements do not establish as
reproducible, and CER is unchanged (0.0599 at c=1, the only directly
comparable row). The production model file is unchanged — confirmed by
sha256 `00978fd943e73f29feb58f1ed162f2d46cc27a29c4320d93955e4d26d2ac3c1d` on
`/home/radxa/svtest-scaled/sense-voice-encoder.rk3588.fp16-scaled.rknn`
still matching the value on record in `rk3588-vs-rk3576-asr-2026-09-09.md`
after this test. The 2.3.2 rebuild
(`sha256 56170c2af63c3992587d4bf011b3b85ed0ef26bcec4258aba201a597240ca452`,
490,055,098 bytes, staged at `/home/radxa/asrpar/models-2.3.2/` only) is not
published to the model repo. `docker ps -a` on radxa was captured before
stopping the 7 resident containers and again after restarting them; both
listings show the same 7 containers `Up` (plus the same 3 pre-existing
`Exited` containers), confirming the board was returned to its prior state.
