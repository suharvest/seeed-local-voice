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
segments fail on the client side: run 1 failed `en_pub_96`/`en_pub_97` (no
error text recorded) and `en_pub_98`/`en_pub_99` (`timed out during opening
handshake`); run 2 failed `en_pub_01`-`en_pub_04` (`no close frame received
or sent`). The two failure sets don't overlap and neither repeats a segment
id, but the client-side error strings alone don't establish Mac<->radxa
network flakiness versus some other client-side cause — recorded as
undetermined. The two runs' *failure* ids are disjoint (run 1's 4 failures
are all present in run 2's 96 successes and vice versa), so merging by
segment id — for each of the 100 ids, taking whichever run has an `ok`
record — yields all 100 unique ids with a real result (92 ids succeeded in
both runs with identical transcripts/scores; 8 ids succeeded in only one of
the two), not a rerun of a single clean pass
(`results/radxa-t172-postfix-en.json` + `-en-retry.json` ->
`radxa-t172-postfix-en-merged100.json`, 100 records). WER is the mean of
per-utterance `jiwer.wer` (matches `bench.py`'s own `error_rate_mean`
methodology, verified against the zh CER above matching PR #96's number
exactly).

| bucket | n | pre-fix (PR #96) | post-fix (c972711) | delta |
|---|---|---|---|---|
| all | 100 | 0.0459 | 0.0413 | -0.45 pp |
| <= 10.08 s (one pass) | 82 | 0.0412 | 0.0412 | 0.00 pp |
| > 10.08 s (windowed) | 18 | 0.0669 | 0.0418 | -2.51 pp |

Against the 344-frame baseline (PR #96's own comparison point): aggregate
English at 172 frames is now 0.0413 vs 344's 0.0423 (172 is 0.10 pp *better*,
not worse), and the windowed bucket is 0.0418 vs 344's 0.0380 (+0.38 pp,
down from the pre-fix +2.89 pp). The single-pass bucket is unchanged at 0.00
pp against pre-fix, as expected — the three c972711 fixes only touch the
cross-window decode path.

The server startup log confirms `T_FIXED=172` (the intended config, not
proof of the exact commit — that log line is unchanged since before
`c972711`): `SenseVoice RKNN worker pool: 3 context(s) on NPU_CORE_0,
NPU_CORE_1, NPU_CORE_2 (platform=rk3588, T_FIXED=172, max 10.1s audio per
encoder pass)`. The revision itself is pinned by bind-mounting
`/home/radxa/asrpar/stagea/sensevoice_rknn_merged.py` (md5
`fa7d8d5fe5e48220b3e5b8bf830c40b0`) over the image's copy — that file was
written via `git show origin/main:rkvoice_stream/backends/asr/sensevoice_rknn.py`
from rkvoice-stream after PR #6 merged (HEAD `9d18ab35`, which is
`c972711` squashed).

Raw data: `results/radxa-t172-postfix-zh.json`,
`results/radxa-t172-postfix-en.json`, `results/radxa-t172-postfix-en-retry.json`,
`results/radxa-t172-postfix-en-merged100.json`.
