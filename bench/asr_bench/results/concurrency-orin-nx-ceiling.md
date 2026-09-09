# ASR concurrency ceiling — reComputer J4012 (Jetson Orin NX 16GB Super)

Zero errors through c=48 on SenseVoice; p95 at c=48 is still under 800 ms but
already more than double c=8's, so that is where degradation starts on this
board. Whisper's admission ceiling was previously 1 (the installed
`voxedge==0.0.13a0` package had no `max_concurrent` field on
`WhisperASRConfig`); with a wheel built from `voxedge` `main` (466f3e4,
unreleased) the ceiling now follows the profile, and the sweep below finds a
serialized-decode-queue ceiling of 8 — above that, confirmed audio
truncation, not just added latency — the same recommendation as J3011.

## SenseVoice (zh)

Corpus: 200 AISHELL-1 zh utterances (Apache-2.0, speaker S0002, train-range
mirror — see `corpus/download_public_corpus.py` docstring), regenerated for
this run so every concurrency level keeps segments >= 3x its worker count
(200 >> 3x48=144). Transport: `/asr/stream` WebSocket, fed at 1.0x real time
in 4 KB chunks, one `is_final` awaited per segment. Latency = audio-end to
`is_final`.

Deployment: image
`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`
with `server/` and `configs/` bind-mounted from openvoicestream `main` (this
branch), `pip install voxedge==0.0.13a0 sentencepiece kaldi_native_fbank`
inside the container. Profile `jetson-sensevoice-c64` (copy of the tracked
`jetson-sensevoice` profile with `asr_max_slots`/`max_concurrent_sessions`
raised from 8 to 64) plus `OVS_MAX_CONCURRENT_SESSIONS=64`, `PYTHONUTF8=1`,
`OVS_API_KEYS=testkey123` (bench run with `--api-key`). The SenseVoice TensorRT
`.plan` was built fresh on first start (~3.5 min, ONNX -> TRT fp16, host TRT
10.3.0) since this board had no cached engine; server confirmed after that:
`SessionLimiter initialized: effective_limit=64` and
`ASR executor: max_workers=64 (source=asr_cap.max_concurrent)`. All non-ASR
containers (`edge-inspection-mosquitto`, `esk-jetson-rtsp-pub`,
`esk-jetson-rtsp-server`) stopped before the run and restarted after, `docker
ps` reconciled against the pre-test list.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER | GR3D_FREQ peak | RAM peak (used/total) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8  | 200 | 200 | 0 | 88.6  | 135.4 | 0.0200 | 0.0457 | 1.57 | 5.83% | 98% | 6.27/15.66 GB |
| 16 | 200 | 200 | 0 | 103.7 | 216.2 | 0.0240 | 0.0601 | 3.04 | 5.83% | 98% | 6.27/15.66 GB |
| 24 | 200 | 200 | 0 | 117.3 | 245.0 | 0.0259 | 0.0725 | 4.48 | 5.83% | 98% | 6.27/15.66 GB |
| 32 | 200 | 200 | 0 | 123.5 | 218.9 | 0.0270 | 0.0680 | 5.65 | 5.83% | 98% | 6.27/15.66 GB |
| 48 | 200 | 200 | 0 | 504.8 | 788.7 | 0.1085 | 0.2237 | 7.29 | 5.83% | 98% | 6.27/15.66 GB |

GR3D_FREQ and RAM figures are the peaks observed in `orin-nx-ceiling-tegrastats.log`
across the whole sweep, not per-level. This board has 16 GB RAM and no swap
pressure was observed at any level (peak used 6.27 GB, well under the total).

Zero errors through every level tested, including c=48. p95 stays in a
135-245 ms band through c=32, then rises to 789 ms at c=48 (p50 also rises,
89->505 ms) — 5.8x the c=8 p95, more than double, which is the relative-
degradation threshold for flagging a ceiling. Unlike J3011, the absolute p95
at c=48 (789 ms) is still under the 1.5 s bar, so **recommended admission
ceiling: 48** (the highest level tested; degradation is visible in the
p50/p95 trend at 48 but has not yet crossed 1.5 s or produced any error).
Whether c=48 is close to this board's true breaking point, or whether it
would hold up further before failing outright, was not established — that
needs levels above 48, not covered here. CER is unchanged at 5.83% at every
concurrency level.

## Whisper (en)

**History:** as on J3011, every prior pass on this board clamped
`effective_limit` to 1 because PyPI `voxedge==0.0.13a0` has no
`max_concurrent` field on `WhisperASRConfig` (see the previous revision of
this file, including a suspected session-release leak observed once at c=1
before a restart, never reproduced). This run replaces it with a wheel built
from `voxedge` `main` (466f3e4, merged, not yet released to PyPI), which
adds the field. The sweep below is the first real Whisper concurrency data
on this board.

Corpus: 200 LibriSpeech test-clean en utterances (CC BY 4.0), round-robined
per level with `--limit` set so every level keeps segments >= 3x its worker
count. Same transport/deployment recipe as SenseVoice above and as J3011's
Whisper section: image `v0.9.0-ondemand-20260721c`, `server/`+`configs/`
bind-mounted from openvoicestream `main`, profile `orin-whisper-c64`,
`OVS_MAX_CONCURRENT_SESSIONS=64`, `OVS_API_KEYS=testkey123` (bench run with
`--api-key`), `PYTHONUTF8=1`, `LC_ALL=C.UTF-8`, `pip install
<voxedge-main-wheel> sentencepiece kaldi_native_fbank` replacing the image's
stock voxedge. The Whisper base encoder `.plan` was already cached on this
board from a prior pass (bf16 TensorRT, confirmed via file timestamp/size,
not rebuilt this run). Server confirmed at startup: `SessionLimiter
initialized: effective_limit=64` and `ASR executor: max_workers=64
(source=asr_cap.max_concurrent)` — both re-checked after every `docker
restart` between levels below, not assumed from the first one. All non-ASR
containers stopped before the run and restarted after, `docker ps`
reconciled against the pre-test list.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|
| 1  | 20 | 20 | 0 | 429.9  | 750.7  | 0.057 | 0.11 | 3.62%  |
| 4  | 24 | 24 | 0 | 492.7  | 694.5  | 0.062 | 0.43 | 4.41%  |
| 8  | 40 | 40 | 0 | 499.9  | 1058.1 | 0.098 | 0.88 | 7.87%  |
| 16 | 64 | 64 | 0 | 1769.6 | 5756.8 | 0.349 | 1.41 | 16.07% |

GR3D_FREQ peak 57%, RAM peak 3.99/15.66 GB (`orin-nx-ceiling-tegrastats.log`
whole-sweep peaks, not per-level).

Zero errors at every level tested (c=24/32 were not run — see below). p95
holds in a 0.69-1.06 s band through c=8, then jumps to 5.76 s at c=16 (5.4x
c=8's) — the same serialized-CPU-KV-cache-decode queueing pattern as J3011;
this board's larger GPU/CPU headroom does not move the onset meaningfully.

**Accuracy is also confirmed to degrade under load on this board**, checked
the same way as J3011: a follow-up c=1 run against the identical 64-item
corpus subset used at c=16 (`docker restart` first, `effective_limit=64`
reconfirmed).

- **c=4 and c=8 are clean**: every item shared with the c=1/64 baseline (24
  items at c=4, 40 at c=8) scores byte-identical `err` — zero degradation at
  the levels this report recommends.
- **c=16 shows real, confirmed defects**: 11 of the 64 shared items score
  differently at c=16 than at c=1 for the same audio. Example (`en_pub_22`,
  ref "THEY WERE CERTAINLY NO NEARER THE SOLUTION OF THEIR PROBLEM"): c=1
  transcribes the full sentence ("there were certainly no near the solution
  of their problem.", `pre_eos_finals=1`) while c=16 for the identical
  segment returns just `"there were certainly no"` (`pre_eos_finals=0`) —
  the same early-finalization/truncation-under-queueing mechanism confirmed
  on J3011. Two more matched examples: `en_pub_29` (c=1 gives a full two-
  sentence transcript, c=16 cuts it after the first sentence) and
  `en_pub_62` (c=1 includes a trailing "[BLANK_AUDIO]" tag that c=16's
  earlier finalization drops). This confirms the defect is not board-
  specific to J3011.
- The aggregate WER trend (3.62% at c=1 to 16.07% at c=16) is therefore a
  mix of corpus composition (harder items entering at higher `--limit`,
  which score identically regardless of concurrency at c=4/c=8) and the
  confirmed truncation defect that appears at c=16, isolated by the
  matched-item comparison above.

**Recommended admission ceiling: 8** — the highest level tested that is
confirmed clean on both latency (p95 under the 1.5 s bar) and accuracy (zero
matched-item degradation vs the c=1 baseline); c=16 is confirmed unsafe on
both axes, not just slow, so c=24/c=32 were not run.


## Files

- `concurrency-orin-nx-ceiling.json` — full per-segment results for both
  sections (`sensevoice_zh`, `whisper_en`).
- `orin-nx-ceiling-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  SenseVoice sweep.
- `orin-nx-whisper-c1-coldstart-failed-attempt.json` — the failed first c=1
  cold-start attempt (18/20 `too_many_sessions`), preserved for independent
  inspection of the unconfirmed leak-like symptom described above.
