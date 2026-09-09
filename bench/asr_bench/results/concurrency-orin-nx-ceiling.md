# ASR concurrency ceiling — reComputer J4012 (Jetson Orin NX 16GB Super)

Zero errors through c=48 on SenseVoice; p95 at c=48 is still under 800 ms but
already more than double c=8's, so that is where degradation starts on this
board. Whisper's admission ceiling was previously 1 (the installed
`voxedge==0.0.13a0` package had no `max_concurrent` field on
`WhisperASRConfig`); with a wheel built from `voxedge` `main` the ceiling now
follows the profile. Whisper transcribes identically at c=1, 8, 16 and 24 —
0 of 72 items differ from c=1 and WER is byte-identical at every level — so
its ceiling is set by latency alone: p95 is under 1 s through c=8, 1.39 s at
c=16, 2.34 s at c=24. The shorter-transcript effect reported here previously
was a bench-client defect (two endpoint detectors racing), fixed in
`bench/asr_bench/bench.py`; see the Whisper section.

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

**History.** Every pass on this board before 2026-09-09 clamped
`effective_limit` to 1, because PyPI `voxedge==0.0.13a0` has no
`max_concurrent` field on `WhisperASRConfig`. A wheel built from `voxedge`
`main` adds the field. The first sweep with that wheel (recorded in the
previous revision of this file) reported shorter transcripts for the same
audio at c=16 and recommended a ceiling of 8 on that basis. Those shortened
transcripts were a bench-client defect, not backend behaviour: `bench.py`
opened `/asr/stream` with the server VAD left on while also sending the EOS
frame — the two-detector combination `server/main.py` and
`docs/CONFIGURATION.md` document as mutually exclusive — and returned on the
first `is_final` after EOS. The server split each utterance and delivered its
mid-utterance final whenever the ASR queue allowed, which under load is after
the client's EOS, so the client scored that fragment as the whole segment.
Frame dump on this board at c=24, `en_pub_00` (`probe_frames.py`):

```
post_eos  +562.5 ms  vad_endpoint
post_eos  +738.4 ms  final endpoint=vad  "Concorde."
post_eos +2569.8 ms  final               "return to its place amidst the tents."
```

The client kept `"Concorde."` and dropped the rest. Every matched item that
differed from its c=1 text was a strict prefix of it, and joining all the
finals reproduces the c=1 text exactly. The sweep below is rerun with the
fixed client (`?vad=none`, all finals collected).

Corpus: the same 72 LibriSpeech test-clean en items (CC BY 4.0) at every
level, so every level is per-item comparable to c=1. Deployment: image
`sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`,
`server/` + `configs/` bind-mounted from this branch, `pip install` of a
`voxedge` `main` wheel (15de2bb) over the image's stock voxedge, profile
`orin-whisper-c64`. The Whisper base encoder `.plan` (bf16 TensorRT) was
already cached in the `speech-models` volume on this board and was not
rebuilt. Server confirmed at startup: `SessionLimiter initialized:
effective_limit=64`, `ASR executor: max_workers=64
(source=asr_cap.max_concurrent)`, `ASR locking granularity: sentence (asr
sessions=64, in-flight=1, queue depth=63, mode=serialized)`. All non-ASR
containers stopped before the run and restarted after, `docker ps` reconciled
against the pre-test list.

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|
| 1  | 72 | 72 | 0 | 404.3  | 924.2  | 0.082 | 0.14 | 4.98% |
| 8  | 72 | 72 | 0 | 450.0  | 838.5  | 0.083 | 1.06 | 4.98% |
| 16 | 72 | 72 | 0 | 546.2  | 1387.8 | 0.110 | 1.90 | 4.98% |
| 24 | 72 | 72 | 0 | 1096.3 | 2336.5 | 0.169 | 2.32 | 4.98% |

Zero errors at every level. **No accuracy change with concurrency**: 0 of 72
items transcribe differently at c=8, c=16 or c=24 than at c=1, and
`error_rate_mean` is byte-identical (0.04979469810945721) at all four levels.
`pre_eos_finals` is 0 for every item at every level — with `?vad=none` the
client's EOS frame is the only endpoint, so nothing is emitted mid-feed.

What moves with concurrency is latency. p95 holds under 1 s through c=8, is
1.39 s at c=16 and 2.34 s at c=24; aggregate throughput keeps rising
(6.7x real time at c=8, 14.7x at c=24), which is the serialized CPU KV-cache
decode being kept busy by a deeper queue.

**Recommended admission ceiling: 16** — the highest level tested with p95
under 1.5 s. c=24 stays correct and error-free and roughly doubles p95, so it
is a throughput-over-latency choice rather than a failure point.

## Files

- `concurrency-orin-nx-ceiling.json` — full per-segment results for both
  sections (`sensevoice_zh`, `whisper_en`).
- `orin-nx-ceiling-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  SenseVoice sweep.
- `orin-nx-whisper-c1-coldstart-failed-attempt.json` — a failed Whisper c=1
  cold-start attempt from an earlier pass (18/20 `too_many_sessions` while
  `effective_limit` was still clamped to 1), preserved for independent
  inspection. Never reproduced after a container restart.
