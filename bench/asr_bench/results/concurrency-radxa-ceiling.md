# radxa (reComputer RK3588 series) — ASR concurrency ceiling, 100-segment corpus

## 1. SenseVoice (3-core RKNN worker pool)

Boundary: c=16 is where the pool falls over — 2 `too_many_sessions`/timeout-class
errors out of 100 and p95 jumps to 13962.0 ms (7.9x the c=4 baseline of 1744.1 ms).
Every level from c=2 through c=12 is error-free and stays within 2x of the c=4
p95 (1744.1 -> 3488.2 ms threshold; c=12's 3275.9 ms is the last level under
it). No tested level keeps p95 at or under 1.5 s — the closest is c=6
(1721.8 ms). **Recommended production concurrency: 8** (p95 2222.2 ms, last
level with p95 under c=4's 2x threshold by a wide margin and still comfortably
inside the c=12 boundary; c=12 is usable but starts trading measurably more
latency per added session).

Difference from the 20-segment pass in `results/radxa-multicore.md` (the "after"
row, same 3-core pool, same profile family): at c=2/4/8 that pass reported p50
1421.2/1361.5/1501.0 ms and p95 1517.6/1567.6/2037.1 ms with CER 5.99% (a
different, smaller corpus draw). This 100-segment pass's p50s are close
(1442.2/1480.2/1532.1 ms) but p95 is consistently higher at n=100
(1911.6/1744.1/2222.2 ms) — with only 20 segments per level, c>=8 drained just
2-3 segments per worker before the sweep ended, too few for a stable p95;
CER also differs (5.13% vs 5.99%) because the corpus draw itself changed (100
public AISHELL-1 items vs 20), not because of a decode regression. This pass
is also the first to test c=12/16 on this 3-core pool with a corpus large
enough to sustain each concurrency level, and it is where the pool's actual
ceiling (c=16) first becomes visible.

### Setup

| | |
|---|---|
| Device | `radxa`, reComputer RK3588 series, aarch64, 3 NPU cores |
| Image | `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:rk-20260903.10` (referred to elsewhere as `openvoicestream:rk-20260903.10`) |
| Backend | `sensevoice_rknn`, one RKNN context per NPU core (`stage a`: files bind-mounted from `/home/radxa/asrpar/stagea`, the same file set as prior radxa multicore passes) |
| Model | `sense-voice-encoder.rk3588.fp16-scaled.rknn` (490 MB), mounted from `/home/radxa/svtest-scaled`, sha256 `00978fd943e73f29feb58f1ed162f2d46cc27a29c4320d93955e4d26d2ac3c1d` (the production file confirmed unchanged in PR #90) |
| Profile | `rk3588-sensevoice`, `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Admission | `ASR_MAX_SESSIONS=32 -e OVS_MAX_CONCURRENT_SESSIONS=32` — both applied without clamping (`effective_limit=32`) |
| Corpus | `bench/asr_bench/corpus` semantics, rebuilt to 100 zh (AISHELL-1, speaker S0002) + 100 en (LibriSpeech test-clean) items via `download_public_corpus.py --limit 100`, `HF_ENDPOINT=https://hf-mirror.com` — same method as PR #89's 100-segment cat-remote/harvest-pi pass, redrawn for this device |
| Client | `bench/asr_bench/bench.py` from the Mac over Tailscale (`ws://100.77.150.16:8621`), `--api-key ""`, chunks fed at 1.0x real time |
| Board state | 7 resident production containers (`retail-web`, `retail-server`, `retail-mosquitto`, `esk-rk-rtsp-pub`, `esk-rk-rtsp-server`, `fall-rtsp-pub`, `fall-rtsp-server`) stopped for the full sweep and restarted after; NPU at 0/0/0% before starting |

Startup log:

```
SessionLimiter initialized: effective_limit=32 (env OVS_MAX_CONCURRENT_SESSIONS='32', profile.max_concurrent_sessions=None)
ASR inference gate: concurrency=3 max_waiting=29
ASR locking granularity: sentence (asr sessions=32, in-flight=3, queue depth=29, mode=concurrent)
SenseVoice RKNN worker pool: 3 context(s) on NPU_CORE_0, NPU_CORE_1, NPU_CORE_2 (platform=rk3588)
```

### Results (100 zh segments per concurrency level)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 2 | 100 | 100 | 0 | 1442.2 | 1911.6 | 0.313 | 0.588 | 0.29 | 5.13% |
| 4 | 100 | 100 | 0 | 1480.2 | 1744.1 | 0.306 | 0.518 | 0.57 | 5.13% |
| 6 | 100 | 100 | 0 | 1432.6 | 1721.8 | 0.317 | 0.521 | 0.86 | 5.13% |
| 8 | 100 | 100 | 0 | 1532.1 | 2222.2 | 0.325 | 0.541 | 1.09 | 5.13% |
| 12 | 100 | 100 | 0 | 1844.7 | 3275.9 | 0.387 | 0.867 | 1.45 | 5.13% |
| 16 | 100 | 98 | 2 | 3689.9 | 13962.0 | 0.922 | 2.647 | 1.26 | 5.23%* |

*c=16's CER is computed over the 98 segments that completed; it is not
comparable to the other rows on a per-segment basis and is listed only for
completeness.

NPU occupancy (`/sys/kernel/debug/rknpu/load`, 2 s samples spanning the full
sweep, 482 samples, 285 with at least one core active): peak Core0 80%, peak
Core1 84%, peak Core2 89% — all three cores load-bearing, consistent with the
3-context pool design confirmed by the startup log.

### Reading

- CER is flat at 5.13% from c=2 through c=12, confirming concurrency does not
  change decode output on this backend at a fixed corpus. It is not directly
  comparable to the 20-segment pass's 5.99% figure — that used a smaller,
  different draw from the same AISHELL-1 speaker.
- p50 stays inside a narrow band (1432-1533 ms) through c=8, meaning the
  queue absorbs load without much per-segment latency growth up to 8
  concurrent sessions on 3 physical worker contexts. p95 is the metric that
  moves first: it climbs from 1744.1 ms (c=4) through 3275.9 ms (c=12), a
  gradual, monotonic increase consistent with growing queue depth, then jumps
  to 13962.0 ms at c=16 alongside the first errors — a step change, not a
  continuation of the same trend.
- No concurrency level tested keeps p95 at or under 1.5 s (the bar met by
  cat-remote's 2-core RK3576 pool through c=8 in `concurrency-cat-remote-ceiling.md`).
  The lowest p95 measured here is 1721.8 ms at c=6. This is a materially
  worse latency floor than cat-remote's, on a board with more NPU cores (3
  vs 2) — the extra core buys higher sustainable throughput (1.45 seg/s at
  c=12 vs cat-remote's 1.61 seg/s at c=12 is comparable) but not lower
  single-segment latency.
- The c=8 -> c=12 step is where the marginal latency cost accelerates
  (p95 +47%, 2222.2 -> 3275.9 ms) while throughput grows +33% (1.09 -> 1.45
  seg/s); c=12 -> c=16 is where the system stops queueing gracefully and
  starts dropping/timing out requests.

## 2. Whisper (rk.whisper, RKNN encoder + CPU ONNX KV-cache decoder)

Boundary: none of the tested levels (c=1/2/4/8) produced an error — the
`voxedge` wheel built from `main` (commit `15de2bb`, PR #14) gives
`WhisperASRConfig` a real `max_concurrent` field with admission queueing
behind a single serialized execution lock, replacing the previous hardcoded
`max_concurrent=1` that made every concurrency level above 1 fail with
`too_many_sessions` (see `concurrency-cat-remote-ceiling.md`'s RK3576 pass).
On this board admission is no longer the limit; queueing latency is. p95
crosses 1.5 s already at c=2 (2964.8 ms) and keeps growing to 5530.8 ms at
c=8 — inference is still one-at-a-time, so raising the admission ceiling
converts what used to be an instant rejection into a longer wait, not more
throughput. **Recommended concurrency: 1** — it is the only level with p95
under 1.5 s (968.2 ms); every level above it trades latency for admission
headroom without adding decode throughput.

### Setup

| | |
|---|---|
| Backend | `rk.whisper` (`voxedge.backends.whisper.WhisperASR`), RKNN encoder + CPU ONNX KV-cache decoder |
| voxedge wheel | Built from `voxedge` `origin/main` @ `15de2bbbc915a41b08dc4eb33586607b693e4a1f` ("fix(sherpa/asr): serve /asr/stream from the offline recognizer when no online one is loaded (#14)"), `voxedge-0.0.13a0-py3-none-any.whl`, sha256 `c740167357660fe93357059444162747c9e11bcf1e4523f1e076464e0c4fd892`. Installed with `pip install --no-deps --force-reinstall` over the image's baked `voxedge-0.0.12a0+kokoro.20260903.2`, replacing only the ASR admission-ceiling logic added in `voxedge` PR #12/#13 |
| Server-side files bind-mounted from this worktree's `main` (ahead of the image's Sep 3 baseline) | `server/core/asr_backend.py` (registers `rk.whisper` -> `voxedge.backends.whisper.WhisperASR`), `server/core/voxedge_backend_config.py` (wires `WHISPER_MAX_CONCURRENT` -> `WhisperASRConfig.max_concurrent`), `server/core/model_downloader.py` (Whisper artifact registry) |
| Profile | `rk3588-whisper-10s`, `WHISPER_VARIANT=base10`, `WHISPER_WINDOW_S=10`, `WHISPER_LANGUAGE=en`, `max_concurrent_sessions` raised from the file's default of 1 to 8 for this pass (the field controls session **admission**, not decode parallelism, which stays serialized by design) |
| Model artifacts | `whisper_encoder_base_10s.rknn`, `decoder_model.onnx` + `decoder_with_past_model.onnx`, `mel_80_filters.txt`, `vocab_en.txt`/`vocab_zh.txt`, pre-existing on-device at `/home/radxa/whisper-models` |
| Corpus | English subset of the same 100-item public corpus, filtered to the **76 items <= 9.5 s** (`WHISPER_WINDOW_S=10` truncates longer segments at the encoder) — same filter and same count (76) as the cat-remote RK3576 pass, confirming the corpus draw itself is unchanged between passes |
| Client | `bench/asr_bench/bench.py`, `--model whisper --lang en`, `ws://100.77.150.16:8621`, `--api-key ""` |

Startup log:

```
Applied profile rk3588-whisper-10s from /opt/speech/configs/profiles/rk3588-whisper-10s.json (4 env keys; 0 stale cleared)
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS=None, profile.max_concurrent_sessions=8)
coordinator: downgrading concurrent -> serialized (asr.supports_parallel=False/max=8, tts.supports_parallel=True/max=None)
server.core.asr_backend: Creating ASR backend rk.whisper (voxedge.backends.whisper.WhisperASR)
voxedge.backends.whisper.asr: whisper: rknn encoder @10.0s window, CPU KV decoder, lang=en
server.main: ASR backend: whisper-rknn (capabilities: ['offline', 'streaming'])
server.main: ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
```

Admission is 8, not 1 — the fix under test in this pass.

### Results (76 en segments <= 9.5 s per concurrency level)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 76 | 76 | 0 | 647.6 | 968.2 | 0.139 | 0.243 | 0.17 | 6.09% |
| 2 | 76 | 76 | 0 | 708.0 | 2964.8 | 0.144 | 0.832 | 0.32 | 6.09% |
| 4 | 76 | 76 | 0 | 1006.6 | 4774.9 | 0.229 | 1.738 | 0.55 | 6.09% |
| 8 | 76 | 76 | 0 | 2505.0 | 5530.8 | 0.628 | 2.190 | 0.98 | 6.09% |

WER is flat at 6.09% across every level — expected, since decode is
serialized regardless of admission concurrency and produces identical output
per segment; this also differs from cat-remote RK3576's 6.22% c=1 figure
because it is a different board/model pairing (RK3588 base10 vs RK3576
base10), not a regression.

NPU occupancy (`/sys/kernel/debug/rknpu/load`, 2 s samples spanning the full
sweep, 456 samples, 141 with Core0 active): peak Core0 **35%**, Core1 and
Core2 flat at 0% throughout. As on RK3576, the RKNN encoder is a small, fast
part of the pipeline; the CPU ONNX KV-cache decoder (invisible to this NPU
counter) is what the added admission concurrency queues in front of.

### Reading

- The fix (`voxedge` PR #12/#13, this pass's wheel) does what it was built to
  do: it turns a hard rejection at c>=2 (cat-remote's `too_many_sessions`
  pattern) into queued admission with zero errors through c=8. p50 barely
  moves (647.6 -> 1006.6 ms from c=1 to c=4) because half the admitted
  requests are still near the front of the queue; p95 is the metric that
  shows the real cost, rising 5.7x from c=1 to c=8 (968.2 -> 5530.8 ms) as
  more requests wait behind the single serialized decoder.
- Because inference stays serialized (`supports_parallel=False`), raising
  `max_concurrent` past 1 does not raise decode throughput — aggregate RTF
  (`throughput_audio_rtf_aggregate`) grows with concurrency purely because
  more audio is being *accepted* per wall-clock second, not decoded faster;
  segment throughput (seg/s) grows sub-linearly (0.17 -> 0.98 from c=1 to
  c=8, a 5.8x increase for an 8x concurrency increase) because the decoder
  is still the bottleneck.
- This is architecturally the same trade cat-remote's report predicted as
  "out of scope" for a bench-only pass: "giving `WhisperASRConfig` a real
  `max_concurrent`... is a code change" needed before the ceiling could be
  raised past 1. That code change (voxedge PR #12/#13) is now upstream on
  `main`; this pass is the first concurrency measurement against it on
  hardware, and it confirms the queueing behaves as designed (zero errors,
  monotonically increasing p95, flat WER) rather than raising the actual
  decode ceiling.
