# Accuracy on a unified corpus, cross-device

Every prior Whisper accuracy number in this results/ directory was measured
on a different subset per device (J3011/J4012: 76-item &le;9.5 s draw;
RK3576/RK3588: 76-item draw; R2000: 100-item &le;4.0 s draw), so numbers
could not be compared device-to-device without also comparing corpora (see
`whisper-hailo-wer-isolation.md`, which found a 15.66-point gap attributable
to corpus alone on a matched-item check). This report re-scores every device
against one fixed 100-item subset per language, so the only variable left
between rows is the device/backend.

**Note on scope:** this PR covers J3011 and J4012 Whisper, plus SenseVoice
on all 5 devices. RK3576, RK3588, and R2000 Whisper rows on this same
100-item corpus are produced by a separate, concurrent PR (that work was
already using those three boards' exclusive-hardware paths for an unrelated
sweep at the time of this pass) and will land as a follow-up.

## Client fix in flight during this pass

`bench.py` prior to PR #95 opened `/asr/stream` without `?vad=none` while
also sending an EOS frame, so the server's own VAD and the client's EOS both
tried to endpoint the same utterance; under load the server could split an
utterance and deliver a mid-utterance final that the client's
first-`is_final`-wins collection scored as the whole segment. This pass
started with pre-#95 client runs (J3011 aggregate WER measured at 19.44%
with 70/100 unified-corpus segments showing `pre_eos_finals>0`; J4012 and
R2000's already-existing matched-100 runs showed 72/100 and 61/100
respectively) — all three withdrawn and superseded by reruns on the
post-#95 client (rebased onto `438e0a4b`, which pins `?vad=none` and
accumulates every final until the server closes the stream). The SenseVoice
numbers below were not affected: checking `pre_eos_finals` on the unified
100-id subset in each of the 5 source JSONs shows 0 nonzero entries in every
one.

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

Both zero-error, both `pre_eos_finals=0` on every one of the 100 segments,
and mean WER agrees to 14 significant figures (0.08858982683982683 vs
0.08858982683982684) — expected, since both boards run the identical
`enc_base_30s_bf16.plan` TensorRT engine reused unchanged from each board's
own model cache (not rebuilt this pass) plus the same CPU ONNX KV decoder.

Recipe: image `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
with `server/`+`configs/` bind-mounted from this branch and `voxedge`
replaced in-container with a wheel built from `voxedge` `main` @466f3e4
(adds the `max_concurrent` field `WhisperASRConfig` needs; PyPI
`voxedge==0.0.13a0` does not have it); profile `orin-whisper-c64`,
`OVS_API_KEYS=testkey123` (bench run with `--api-key`); `speech-models`
Docker volume mounted at `/opt/models` for the persistent engine cache.

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
100-id subset is 0 for all 100 segments on all 5 devices — the endpoint-race
bug the Whisper section above describes did not manifest in any of these
SenseVoice runs.

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
  `j4012-whisper-matched100-fixed.json` / `.md` — raw `bench.py` output
  (post-#95 client) used for the Whisper rows above.
- `whisper100_ids.txt` / `sensevoice100_ids.txt` — the exact 100 ids that
  define each unified subset, one per line.
