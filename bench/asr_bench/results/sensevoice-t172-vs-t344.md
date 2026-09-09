# SenseVoice RKNN: 172-frame encoder vs 344-frame, RK3588 and RK3576

Date: 2026-09-09. Devices: `radxa` (reComputer RK3588 series), `cat-remote`
(reComputer RK3576 series). Both boards idle for every run — the 7 resident
containers on RK3588 were stopped and restarted afterwards (`docker ps`
before/after identical), RK3576 had none running.

## What changed

The `.rknn` is frozen to a fixed encoder sequence length. The shipped builds use
344 LFR frames = 20.4 s of audio; a VAD-delimited utterance in this corpus
averages 5.9 s, so most of each NPU pass computed zero padding. This compares
the shipped 344 builds against 172-frame (10.1 s) rebuilds of the same source
ONNX, on the same toolkit (rknn-toolkit2 2.3.2) and the same corpus.

Audio longer than one encoder pass is windowed by
`rkvoice_stream/backends/asr/sensevoice_rknn.py` (each window past the first
re-reads 16 LFR frames of left context and decodes only past them), where it
was previously truncated at T_FIXED and the tail dropped.

## Corpus and harness

- 100 zh segments (AISHELL-1 mirror) + 100 en segments (LibriSpeech test-clean),
  `manifest.json` durations 1.3-23.3 s, mean 5.9 s. 19 en segments exceed 10.08 s
  (one 172-frame pass); no zh segment does.
- `bench/asr_bench/bench.py` from the Mac over Tailscale, 1.0x real-time feed,
  `--api-key`. Latency is audio-end -> `is_final`, so it includes one Mac↔device
  round trip. zh scores CER, en scores WER.
- Server: `seeed-local-voice:rk-20260903.10` with the stage-a worker-pool
  bind-mounts, `ASR_MAX_SESSIONS=32`, `OVS_MAX_CONCURRENT_SESSIONS=32`,
  `OVS_VAD_BACKEND=none`. Startup logs confirm `effective_limit=32` and a pool
  of 3 contexts (RK3588) / 2 contexts (RK3576).

## Encoder latency, no server in the path

`rknnlite.api.RKNNLite`, one context, 30 iterations per configuration, two
rounds per core, idle board.

| SoC | core | T=344 mean (ms) | T=172 mean (ms) |
|---|---|---|---|
| RK3588 | NPU_CORE_0 | 1023.2 / 1082.1 | 440.3 / 431.9 |
| RK3588 | NPU_CORE_1 | 1167.0 / 1072.2 | 474.9 / 431.5 |
| RK3588 | NPU_CORE_2 | 1194.2 / 1180.5 | 426.1 / 438.8 |
| RK3576 | NPU_CORE_0 | 678.1 / 678.6 | 345.3 / 340.5 |
| RK3576 | NPU_CORE_1 | 673.6 / 670.4 | 343.7 / 343.5 |

Across all rounds and cores: RK3588 1119.9 -> 440.6 ms (2.54x), RK3576
675.2 -> 343.2 ms (1.97x). RK3588 also gains from binding all three cores to one
inference (`NPU_CORE_0_1_2`, 355.2 ms), the same ~10-20% multi-core ceiling
measured at 344.

## /asr/stream, zh, 100 segments

RK3588 (radxa), 3-context pool:

| c | T=344 ok/err | T=344 p50 | T=344 p95 | T=344 CER | T=172 ok/err | T=172 p50 | T=172 p95 | T=172 CER |
|---|---|---|---|---|---|---|---|---|
| 1 | 100/0 | 1356.2 | 1668.0 | 0.0513 | 100/0 | 727.4 | 971.4 | 0.0474 |
| 2 | 100/0 | 1359.8 | 1661.3 | 0.0513 | 100/0 | 714.2 | 1317.0 | 0.0474 |
| 4 | 100/0 | 1361.5 | 1694.9 | 0.0513 | 100/0 | 642.9 | 898.3 | 0.0474 |
| 8 | 100/0 | 1477.3 | 1796.0 | 0.0513 | 100/0 | 658.6 | 902.1 | 0.0474 |
| 12 | 100/0 | 1640.6 | 2491.3 | 0.0513 | 85/15 | 697.8 | 1290.3 | 0.0551 |

RK3576 (cat-remote), 2-context pool:

| c | T=344 ok/err | T=344 p50 | T=344 p95 | T=344 CER | T=172 ok/err | T=172 p50 | T=172 p95 | T=172 CER |
|---|---|---|---|---|---|---|---|---|
| 1 | 96/4 | 911.7 | 8487.1 | 0.0534 | 100/0 | 535.7 | 1802.4 | 0.0474 |
| 2 | 100/0 | 889.7 | 1509.4 | 0.0513 | 100/0 | 539.5 | 922.1 | 0.0474 |
| 4 | 100/0 | 950.8 | 1484.9 | 0.0513 | 100/0 | 539.1 | 933.8 | 0.0474 |
| 8 | 100/0 | 980.6 | 1504.0 | 0.0513 | 100/0 | 544.6 | 867.2 | 0.0474 |
| 12 | 100/0 | 1218.2 | 2194.7 | 0.0513 | 100/0 | 583.4 | 1067.1 | 0.0474 |

Against a 1.5 s p95 gate: at 344 RK3588 clears no concurrency level and RK3576
clears none below c=8 cleanly (1484-1509 ms sits on the line). At 172 RK3588
clears c=1 through 8 and RK3576 clears c=1 through 12.

The 15 failures at RK3588 c=12 are 6 `timed out during opening handshake` plus 9
with no error text — WebSocket upgrades, not `too_many_sessions`; the 85
completed sessions kept p95 at 1290 ms. The 4 failures and the 8487 ms p95 at
RK3576 c=1 with T=344 are the same client-side effect on the first run of that
sweep.

## English, including segments longer than one pass

RK3588, c=1, 100 en segments, WER:

| bucket | n | T=344 | T=172 | delta | T=344 p50 | T=172 p50 |
|---|---|---|---|---|---|---|
| all | 100 | 0.0423 | 0.0459 | +0.36 pp | 1424 ms | 769 ms |
| <= 10.08 s (one 172 pass) | 82 | 0.0432 | 0.0412 | -0.20 pp | 1414 ms | 748 ms |
| > 10.08 s (172 windows) | 18 | 0.0380 | 0.0669 | +2.89 pp | 1476 ms | 1271 ms |

Utterances that fit one 172-frame pass score slightly better than at 344 — less
zero padding reaches the encoder. Utterances that need windowing pay at the cut:
16 frames (0.96 s) of re-read left context brought that bucket from +3.52 pp to
+2.89 pp, and the aggregate from +0.47 pp to +0.36 pp, but it does not close.
The 23.3 s segment, the only one that both builds have to window, scores
identically (0.0312) on both.

The zh set carries no segment above 10 s, which is why its CER improves
uniformly (0.0513 -> 0.0474).

## Artifacts

Published to `harvestsu/sensevoice-rknn` (both new files; no existing file was
modified or removed):

```
sense-voice-encoder.rk3588.fp16-scaled.t172.rknn  485072826 B
  sha256 c21c754f282ff499efa6dbfe59131b12f435a010470ec0887d644b5b68b09759
sense-voice-encoder.rk3576.fp16-scaled.t172.rknn  498959418 B
  sha256 2c4cd5a5723a27e35379e3c9d7fd784071a6965caa0586ec09e4fd6ffacfeaf6
```

Both were converted on spark (aarch64, rknn-toolkit2 2.3.2) from
`sense-voice-encoder.scaled.t172.onnx` (sha256 `1faa79b3...c56a70b1`), itself the
published `sense-voice-encoder.scaled.fixed.onnx` re-frozen from T=344 to T=172.
