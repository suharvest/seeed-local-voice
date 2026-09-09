# ASR concurrency ceiling — reComputer J4012 (Jetson Orin NX 16GB Super)

Zero errors through c=48 on SenseVoice; p95 at c=48 is still under 800 ms but
already more than double c=8's, so that is where degradation starts on this
board. Whisper's admission ceiling is 1 concurrent session, enforced by the
installed `voxedge` package itself, not by board resources — same as J3011.

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

Corpus: 20 (c=1) / 200 (c=4) LibriSpeech test-clean en utterances (CC BY 4.0).
Same transport/deployment recipe, profile `orin-whisper-c64` (copy of the
tracked `orin-whisper` profile with `asr_max_slots`/`max_concurrent_sessions`
raised from 8 to 64), `OVS_MAX_CONCURRENT_SESSIONS=64`. The Whisper base
encoder `.plan` was built fresh on first start (bf16, confirmed in the
container log: "Building Whisper TRT encoder (host TRT 10.3.0, bf16)").

Server startup log: `whisper.tensorrt: admission ceiling 64 requested but
this voxedge build has no max_concurrent field on WhisperASRConfig — staying
at 1 slots`, then `SessionLimiter initialized: effective_limit=1`
— the same hard package-level clamp seen on J3011, not board-specific.

The first c=1 attempt on this board (before a container restart) hit 18/20
`too_many_sessions` errors starting from the 3rd segment (`current: 1, limit:
1` while the previous session's slot should already have been released) —
looked like a session-release leak. The full per-segment result of that
failed attempt is preserved at
`orin-nx-whisper-c1-coldstart-failed-attempt.json` for independent
inspection. A `docker restart` and re-run of the same c=1 sweep completed
cleanly (20/20 OK, see the row below), so this was not reproduced on a
second attempt; it is recorded here as an observed but unconfirmed
intermittent failure mode on cold start, not a confirmed leak (needs more
repeated cold-start attempts to say more).

| Concurrency | Segments | OK | Errors | p50 latency (ms) | p95 latency (ms) | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|
| 1 | 20  | 20 | 0   | 326.5 | 641.2 | 0.11 | 3.62% |
| 4 | 200 | 2  | 198 | -     | -     | 0.19 | -     |

At c=1 (post-restart, clean run) all 20 segments transcribe correctly (WER
3.62%, matching J3011 and the project's known Whisper-base reference figure).
At c=4, only the first session is admitted; the other three are rejected at
the WebSocket layer with `{"error": "too_many_sessions", "current": 1,
"limit": 1}` — 198/200 segments fail this way. **This board's real Whisper
concurrency ceiling is 1**, identical to J3011 — c=8/16/24/32 were not run
for the same reason: the failure mode is a hard admission clamp confirmed in
the startup log, not a resource limit that more concurrency would probe
differently.

## Files

- `concurrency-orin-nx-ceiling.json` — full per-segment results for both
  sections (`sensevoice_zh`, `whisper_en`).
- `orin-nx-ceiling-tegrastats.log` — 1 Hz `tegrastats` samples spanning the
  SenseVoice sweep.
- `orin-nx-whisper-c1-coldstart-failed-attempt.json` — the failed first c=1
  cold-start attempt (18/20 `too_many_sessions`), preserved for independent
  inspection of the unconfirmed leak-like symptom described above.
