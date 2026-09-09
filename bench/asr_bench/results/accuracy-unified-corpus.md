# Accuracy on a unified corpus, cross-device

Every prior Whisper accuracy number in this results/ directory was measured
on a different subset per device (J3011/J4012: 76-item &le;9.5 s draw;
RK3576/RK3588: 76-item draw; R2000: 100-item &le;4.0 s draw), so numbers
could not be compared device-to-device without also comparing corpora (see
`whisper-hailo-wer-isolation.md`, which found a 15.66-point gap attributable
to corpus alone on a matched-item check). This report re-scores every device
against one fixed 100-item subset per language, so the only variable left
between rows is the device/backend.

**Note on scope:** an earlier revision of this report covered only J3011 and
J4012 Whisper (plus SenseVoice on all 5 devices), with RK3576/RK3588/R2000
Whisper noted as a follow-up because those three boards were occupied by an
unrelated concurrent sweep at the time. That follow-up landed in
`bench/whisper-refix-recheck` and is folded in below — all 5 devices now
have a Whisper row on this same 100-item corpus.

## Client fix in flight during this pass

`bench.py` prior to PR #95 opened `/asr/stream` without `?vad=none` while
also sending an EOS frame, so the server's own VAD and the client's EOS both
tried to endpoint the same utterance. After sending EOS, the pre-#95 client
took the *first* `is_final` it received as the segment's result and stopped
reading; if the server queued a second, later final for the same utterance
(the real end-of-speech one), that text was silently dropped and the first
fragment was scored as the whole segment (see PR #95's commit message for a
frame-level trace). PR #95 (`438e0a4b`, now in this branch) fixes this by
pinning `?vad=none` (removing the server VAD as a second detector) and
reading until the server closes the stream, accumulating every final it
sends instead of stopping at the first.

This pass started with pre-#95 client runs on J3011 (`en_pub_*` matched-100
corpus, aggregate WER measured at 19.44%) and reused J4012/R2000's
already-existing matched-100 runs (19.06%/23.00%), all recorded before
`438e0a4b` existed. All three are withdrawn here and J3011/J4012 are rerun
on the post-#95 client (100/100 ok on both, see table below). R2000's rerun
on this same matched-100 corpus, plus first-time RK3576/RK3588 runs on it,
landed in the follow-up noted above (see "Note on scope") and are folded
into the table below.

Note on the `pre_eos_finals` counter: this field counts finals the client
drains **before** sending EOS (mid-feed VAD chatter) and exists unchanged in
both the pre- and post-#95 client — it does not indicate the post-EOS
first-final-wins bug PR #95 fixed, and a `0` value does not prove a given
historical run was unaffected by it (the old client never recorded how many
finals arrived *after* EOS, which is the count that would matter). It is
reported below only as a description of what each recorded run contains,
not as evidence for or against the race having occurred in it. The evidence
this report relies on for Whisper is the direct before/after WER comparison
on J3011 (19.44% pre-fix -> 7.62% post-fix, same board, same corpus); for
SenseVoice, the evidence that concurrency-related races are not a live
concern for this backend is the previously-documented flat CER across
concurrency levels (`concurrency-orin-nano-ceiling.md`: unchanged at every
level from c=8 to c=48 on the 200-item corpus), not the `pre_eos_finals`
count.

## Corpus

- **Whisper (en):** 100 LibriSpeech test-clean segments, duration &le;4.0 s,
  CC BY 4.0, drawn via `corpus/download_public_corpus.py` (HF-mirror
  `openslr/librispeech_asr`). Same 100 ids R2000's original Hailo Whisper
  pass used (`corpus_r2000_matched100/manifest.json`, ids `en_pub_00` ..
  `en_pub_368`); verified against a fresh 400-item redraw by
  `corpus/verify_r2000_match.py` (100/100 transcript + duration match,
  &plusmn;0.05 s tolerance).
- **SenseVoice (zh):** 100 AISHELL-1 utterances, speaker S0002 (Apache-2.0),
  drawn the same way (`--limit 100`, sorted tar-member order). Confirmed
  identical, by id and reference transcript, to the first 100 of the
  200-item AISHELL-1 draw used for J3011/J4012's own SenseVoice ceiling
  sweeps (0 missing, 0 reference mismatches across all 100 ids) — so those
  two devices' SenseVoice numbers below are extracted from already-run
  ceiling data, not a fresh pass.

## Scoring

`bench/asr_bench/score_unified.py` reproduces `bench.py`'s own CER/WER
normalization exactly (`bench.py:94-118`: lowercase, strip punctuation,
`jiwer.cer`/`jiwer.wer` with char/word tokenization) against the raw
ref/hyp pairs already recorded in each device's result JSON, restricted to
the unified 100-id list.

- **Aggregate** = `jiwer.cer`/`jiwer.wer` over all 100 ref/hyp pairs
  concatenated (edit distance summed over the whole corpus, divided by
  total reference length).
- **Mean** = average of each segment's individual error rate.
- **p50** = median of each segment's individual error rate.

## Whisper (en), 100 LibriSpeech segments &le;4.0 s, c=1

| Device | Backend | Segments OK | Aggregate WER | Mean WER | p50 WER |
|---|---|---|---|---|---|
| J3011 (Jetson Orin Nano 8GB Super) | TensorRT bf16 encoder, CPU ONNX KV decoder | 100/100 | **7.62%** | 8.86% | 0.00% |
| J4012 (Jetson Orin NX 16GB Super) | TensorRT bf16 encoder, CPU ONNX KV decoder | 100/100 | **7.62%** | 8.86% | 0.00% |
| RK3576 (cat-remote) | RKNN base10 encoder, CPU ONNX KV decoder | 100/100 | **8.51%** | 9.70% | 0.00% |
| RK3588 (radxa) | RKNN base10 encoder, CPU ONNX KV decoder | 100/100 | **7.50%** | 8.79% | 0.00% |
| R2000 (Raspberry Pi 5 + Hailo-8) | Hailo base encoder (5 s window), CPU ONNX KV decoder | 100/100 | **8.39%** | 9.95% | 0.00% |

All five zero-error, all `pre_eos_finals=0` on every one of the 100 segments
(no mid-feed VAD chatter drained before EOS on any device — see the note
above on what this counter does and does not indicate). J3011/J4012's mean
WER agrees exactly (0.08858982683982684 on both, per
`accuracy-unified-corpus.json`) — expected, since both boards run the
identical `enc_base_30s_bf16.plan` TensorRT engine reused unchanged from
each board's own model cache (not rebuilt this pass) plus the same CPU ONNX
KV decoder. RK3576/RK3588/R2000 each run a different encoder (RKNN base10 at
a 10 s window on the RK boards, Hailo base at a 5 s window on R2000, vs.
TensorRT bf16 at 30 s on the Jetsons) with the same CPU ONNX KV decoder, and
their aggregate WER spans 7.50-8.51% against the Jetsons' 7.62% — a
narrower spread than the pre-fix numbers this table withdraws, but not
shown here to isolate encoder-vs-decoder or window-size effects; that
would need a dedicated matched-item pass like
`whisper-hailo-wer-isolation.md`, not run for this table.

Recipe (J3011/J4012): image `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
with `server/`+`configs/` bind-mounted from this branch and `voxedge`
replaced in-container with a wheel built from `voxedge` `main` @466f3e4
(adds the `max_concurrent` field `WhisperASRConfig` needs; PyPI
`voxedge==0.0.13a0` does not have it); profile `orin-whisper-c64`,
`OVS_API_KEYS=testkey123` (bench run with `--api-key`); `speech-models`
Docker volume mounted at `/opt/models` for the persistent engine cache.

Recipe (RK3576/RK3588): image `openvoicestream:rk-20260903.10` /
`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:rk-20260903.10`,
`server/`+`configs/` bind-mounted from this branch, same `voxedge` `main`
@466f3e4 wheel, profiles `rk3576-whisper-c8` / `rk3588-whisper-10s` with
`OVS_MAX_CONCURRENT_SESSIONS=8`/`WHISPER_MAX_CONCURRENT=8`; model artifacts
(`whisper_encoder_base_10s.rknn`, decoder ONNX pair, vocab/mel files)
pre-existing on each device. `--api-key testkey123` (RK3576) / `--api-key ""`
(RK3588, no key configured on that profile).

Recipe (R2000): image `asrbench-rpi5-hailo-whisper:r2000b`, profile
`rpi5-hailo-whisper` with `OVS_MAX_CONCURRENT_SESSIONS=16`, same `voxedge`
`main` @466f3e4 wheel, HEF + decoder ONNX cached on-device, `--api-key
testkey123`; `mcp_face_rec` stopped for the run (holds `/dev/hailo0`) and
restarted after.

## SenseVoice (zh), 100 AISHELL-1 S0002 segments

No device in the existing result set has a c=1 SenseVoice pass on the
100-item corpus (the lowest tested concurrency per device is shown below;
NPU/GPU-serialized profiles on RK3576/RK3588/R2000 and the 200-item Jetson
sweeps both start above c=1). Per-device concurrency is noted in the table;
CER at a given concurrency for this backend has previously been shown flat
across concurrency levels (`concurrency-orin-nano-ceiling.md`: SenseVoice
CER unchanged at every level from c=8 to c=48 on the 200-item corpus), so
these are not expected to move at c=1, but that has not been independently
re-verified for every board in this pass. `pre_eos_finals` on the unified
100-id subset is 0 for all 100 segments on all 5 devices (no mid-feed VAD
chatter drained before EOS); per the note above, this counter does not by
itself indicate whether the post-EOS race affected these runs — the
evidence that SenseVoice is not a live concern here is the previously
established flat CER across concurrency levels, not this counter.

| Device | Backend | Concurrency used | Aggregate CER | Mean CER | p50 CER |
|---|---|---|---|---|---|
| J3011 (Jetson Orin Nano 8GB Super) | TensorRT SenseVoice | c=8 (extracted from 200-item corpus) | **4.82%** | 5.13% | 0.00% |
| J4012 (Jetson Orin NX 16GB Super) | TensorRT SenseVoice | c=8 (extracted from 200-item corpus) | **4.82%** | 5.13% | 0.00% |
| RK3576 | RKNN SenseVoice, fp16-scaled encoder | c=4 | **4.82%** | 5.13% | 0.00% |
| RK3588 (radxa) | RKNN SenseVoice, fp16-scaled encoder | c=2 | **4.82%** | 5.13% | 0.00% |
| R2000 (Raspberry Pi 5) | CPU ONNX SenseVoice | c=2 | **4.82%** | 5.12% | 0.00% |

Aggregate CER is identical to two decimal places across all five
devices/backends on this corpus; the mean differs by 0.01 point for R2000
only. Spot-checking raw hypotheses (`zh_pub_00`) shows genuinely different
text per device (R2000 differs from the others by a trailing period vs.
comma), so this is not five copies of the same file — SenseVoice's CER on
this 100-item corpus is not measurably sensitive to backend/quantization
(TensorRT fp16/bf16, RKNN fp16-scaled INT-adjacent, CPU ONNX fp32) at the
tested concurrency levels, unlike Whisper's cross-device spread once the
client bug above is corrected.

## Files

- `accuracy-unified-corpus.json` — every scored cell above, with `n`,
  `aggregate`, `mean`, `p50`, source JSON path, and concurrency, produced by
  `build_unified_report.py` calling `score_unified.py` once per cell (no
  numbers hand-copied from other reports).
- `j3011-whisper-matched100-fixed.json` / `.md`,
  `j4012-whisper-matched100-fixed.json` / `.md`,
  `rk3576-whisper-matched100-fixed.json`, `rk3588-whisper-matched100-fixed.json`,
  `r2000-whisper-matched100-fixed.json` — raw `bench.py` output (post-#95
  client) used for the Whisper rows above.
- `j3011-whisper-matched100-prefix-withdrawn.json` — the pre-#95 J3011 run
  (99/100 ok, 19.44% aggregate WER, cited above as withdrawn), kept as
  evidence for that comparison rather than only asserted.
- `whisper100_ids.txt` / `sensevoice100_ids.txt` — the exact 100 ids that
  define each unified subset, one per line.
