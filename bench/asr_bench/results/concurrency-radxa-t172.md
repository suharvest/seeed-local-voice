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

## 修后复测（c972711，2026-09-09）

The table above and PR #96's numbers were measured before rkvoice-stream#6's
`c972711` fixed three windowed-decode bugs (CTC repeat-collapse restarting per
window, ASCII-space rejoin splitting words at the cut, filename-derived T
skipping the env floor). This section re-measures with the merged
(post-`c972711`) `sensevoice_rknn.py`, same device (radxa, RK3588), same
container recipe (`start_t172.sh`, `models-t172/`, image
`seeed-local-voice:rk-20260903.10`), 7 resident containers stopped for the
duration and restarted after, c=1 only, 100 zh + 100 en segments (same corpus,
`--limit 100`).

zh (no segment above 10.08 s, so the windowing fix cannot move this number):

| c | ok/err | p50 (ms) | p95 (ms) | CER |
|---|---|---|---|---|
| 1 | 100/0 | 632.9 | 1105.6 | 0.0474 |

en, split by duration bucket. Two back-to-back c=1 runs each had 4/100
segments fail with a client-side WebSocket error (`timed out during opening
handshake` in run 1, `no close frame received or sent` in run 2) — different
segment ids each time, none of them repeating, so this reads as Mac<->radxa
Tailscale link flakiness rather than a server-side or decode fault. The two
runs' successful ids are disjoint-complementary (each run's 4 failures are
all in the other run's 96 successes), so the results below merge to a clean
100/100 by taking, for each segment id, whichever run succeeded on it
(`results/radxa-t172-postfix-en.json` + `-en-retry.json` ->
`radxa-t172-postfix-en-merged100.json`). WER is the mean of per-utterance
`jiwer.wer` (matches `bench.py`'s own `error_rate_mean` methodology, verified
against the zh CER above matching PR #96's number exactly).

| bucket | n | pre-fix (PR #96) | post-fix (c972711) | delta |
|---|---|---|---|---|
| all | 100 | 0.0459 | 0.0413 | -0.46 pp |
| <= 10.08 s (one pass) | 82 | 0.0412 | 0.0412 | 0.00 pp |
| > 10.08 s (windowed) | 18 | 0.0669 | 0.0418 | -2.51 pp |

Against the 344-frame baseline (PR #96's own comparison point): aggregate
English at 172 frames is now 0.0413 vs 344's 0.0423 (172 is 0.10 pp *better*,
not worse), and the windowed bucket is 0.0418 vs 344's 0.0380 (+0.38 pp,
down from the pre-fix +2.89 pp). The single-pass bucket is unchanged at 0.00
pp against pre-fix, as expected — the three c972711 fixes only touch the
cross-window decode path.

Server startup log confirms the merged backend was in effect:
`SenseVoice RKNN worker pool: 3 context(s) on NPU_CORE_0, NPU_CORE_1,
NPU_CORE_2 (platform=rk3588, T_FIXED=172, max 10.1s audio per encoder pass)`.

Raw data: `results/radxa-t172-postfix-zh.json`,
`results/radxa-t172-postfix-en.json`, `results/radxa-t172-postfix-en-retry.json`,
`results/radxa-t172-postfix-en-merged100.json`.
