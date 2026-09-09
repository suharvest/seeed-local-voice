# cat-remote (reComputer RK3576 series) — ASR concurrency ceiling, 100-segment corpus

## 1. SenseVoice (2-core RKNN worker pool)

Boundary: **p95 stays under 1.5 s through c=8 (1324.6 ms)**; c=12 crosses it
(2016.3 ms) and c=24 falls off a cliff (RTF p50 > 1, the device can no longer
keep up with real-time audio arrival). Zero errors at every level tested.
**Recommended production concurrency: 8.**

Difference from the 20-segment pass in `results/cat-remote-multicore.md`:
that report measured this same 2-core stage-a build at c=8 with only 20
segments (2.5 per worker) and got p95 1443.8 ms — close to this pass's
1324.6 ms at n=100, so that number holds up. But that pass did not test
c=12/16/24 on the 2-core pool (the c=12/16 numbers quoted in the task brief —
p95 3619/5660 ms — are from a *different* build: the single-core "stageb"
sentence-queue config measured in `results/cat-remote-concurrency.md`, which
reports 2733.0 ms at c=8 under serialized single-core inference, not this
2-core pool). This pass is the first 2-core-pool measurement above c=8, and
with 100 segments per level it shows the 2-core pool holding p95 under 2.8 s
through c=16 before c=24 collapses — a materially different (better) ceiling
than the single-core figures the task brief cited for c=12/16.

### Setup

| | |
|---|---|
| Device | `cat-remote`, reComputer RK3576 series, aarch64, 2 NPU cores |
| Image | `openvoicestream:rk-20260903.10` |
| Backend | `sensevoice_rknn` via `rkvoice_stream`, one RKNN context per NPU core (`stage a`: `voxedge` PR a3b57cb8 + `rkvoice-stream` `feat/sensevoice-multicore-workers`, bind-mounted over the image per `results/cat-remote-multicore.md`) |
| Model | `sense-voice-encoder.rk3576.fp16-scaled.rknn` (490 MB), mounted from `/home/cat/svtest-scaled` |
| Profile | `rk3576-sensevoice`, `ASR_NPU_CORE_MASK` unset (both cores), `OVS_VAD_BACKEND=none`, `OVS_PUNCT=0`, `OVS_SPEAKER_EMB=0` |
| Admission | `ASR_MAX_SESSIONS=32 -e OVS_MAX_CONCURRENT_SESSIONS=32` — both applied without clamping (`effective_limit=32`) |
| Corpus | `bench/asr_bench/corpus`, public AISHELL-1 zh subset rebuilt to 100 items (`download_public_corpus.py --limit 100`), vs. 20 in every prior cat-remote pass |
| Client | `bench/asr_bench/bench.py` from the Mac over Tailscale (`ws://100.89.94.11:8621`), `--api-key ""`, chunks fed at 1.0x real time |
| Board state | `docker ps -a` before the run showed only exited containers (`conversational-voice-speech`, `conversational-voice-agent`, `voice-client-uitest`) — board was idle; those were left untouched |

Startup log:

```
SessionLimiter initialized: effective_limit=32 (env OVS_MAX_CONCURRENT_SESSIONS='32', profile.max_concurrent_sessions=None)
ASR inference gate: concurrency=2 max_waiting=30
ASR locking granularity: sentence (asr sessions=32, in-flight=2, queue depth=30, mode=concurrent)
SenseVoice RKNN worker pool: 2 context(s) on NPU_CORE_0, NPU_CORE_1 (platform=rk3576)
```

### Results (100 zh segments per concurrency level)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER |
|---|---|---|---|---|---|---|---|---|---|
| 4 | 100 | 100 | 0 | 889.0 | 1316.5 | 0.192 | 0.363 | 0.61 | 5.13% |
| 8 | 100 | 100 | 0 | 950.3 | 1324.6 | 0.203 | 0.349 | 1.17 | 5.13% |
| 12 | 100 | 100 | 0 | 1235.6 | 2016.3 | 0.262 | 0.570 | 1.61 | 5.13% |
| 16 | 100 | 100 | 0 | 1625.8 | 2785.7 | 0.350 | 0.773 | 1.96 | 5.13% |
| 24 | 100 | 100 | 0 | 5382.0 | 6801.8 | 1.042 | 2.056 | 2.07 | 5.13% |

NPU occupancy (`/sys/kernel/debug/rknpu/load`, 2 s samples spanning the full
sweep, 152 samples): 96 samples with at least one core active, peak
Core0 81%, peak Core1 79% — both cores load-bearing, consistent with the
2-context pool design.

### Reading

- CER is 5.13% at every concurrency level in this pass — flat across c=4
  through c=24, confirming queueing/parallel dispatch does not change decode
  output on this backend. It is not the same figure as the single-session
  baselines in the prior 20-item reports (5.99% in `cat-remote-multicore.md`,
  5.48% in `harvest-pi.md`) — those used a different, smaller draw from the
  corpus, so the two numbers are not directly comparable; what this pass
  establishes is that CER does not move with concurrency on a fixed 100-item
  corpus, not that it matches an unrelated corpus draw.
- Throughput keeps rising through c=24 (0.61 → 2.07 seg/s) but latency stops
  being a fair trade well before that: at c=24, RTF p50 crosses 1.0 (1.042),
  meaning the median segment's response time (which includes queueing wait,
  not just decode time — `bench.py` measures EOS-to-`is_final`) now exceeds
  its own audio duration. That is evidence of response latency exceeding
  real time under this test's load pattern (each worker waits for one
  segment to finish before sending the next), not an independently
  established claim about sustained live-arrival throughput. p95 at c=24
  (6801.8 ms) is 5.1x the c=8 figure (1324.6 ms) for roughly double the
  throughput gain (1.17 → 2.07 seg/s, 1.8x).
- The c=8 → c=12 step is where p95 first crosses 1.5 s (1324.6 → 2016.3 ms,
  +52%) while throughput grows only 38% (1.17 → 1.61 seg/s) — the marginal
  latency cost per added session accelerates faster than the marginal
  throughput gain starting at c=12.

## 2. Whisper (RKNN encoder + CPU KV-cache decoder)

**History:** the previous pass on this section found `rk.whisper` admitting
exactly 1 concurrent session regardless of `WHISPER_MAX_CONCURRENT` /
`OVS_MAX_CONCURRENT_SESSIONS`, and attributed it to `voxedge/backends/whisper/asr.py`
hardcoding `concurrency_capability(..., max_concurrent=1, ...)` with no config
field to raise it (see the prior revision of this section for the full
c=1/2/4/8/12 sweep against that build, including the accuracy caveat on
`en_pub_00`). That has changed upstream: `voxedge` `main` (466f3e4
`feat(asr): configurable admission ceilings for the whisper and sherpa
backends`, merged, not yet released to PyPI as of `voxedge==0.0.13a0`) adds a
real `max_concurrent` field to `WhisperASRConfig` plus a matching `_lock`.
This run replaces the image's installed voxedge with a wheel built from that
commit and re-runs the sweep.

### Setup

| | |
|---|---|
| Backend | `rk.whisper` (`voxedge.backends.whisper.WhisperASR`), RKNN encoder + CPU ONNX KV-cache decoder |
| Image | `openvoicestream:rk-20260903.10` (cached on-device; no `rk-20260909` tag was present to try) |
| `server/`+`configs/` | bind-mounted read-only from this worktree's `main` (bench harness only — no code change to `asr_backend.py`/`voxedge_backend_config.py`/`model_downloader.py` was needed this time, since main's copies already carry the `rk.whisper` registry entries from the prior pass) |
| voxedge | PyPI `0.0.13a0` replaced with a wheel built from `voxedge` `main` 466f3e4 (`uv build --wheel` in a dedicated worktree), plus `sentencepiece`/`kaldi_native_fbank`, `pip install`ed into the running container then `docker restart` |
| Profile | new `rk3576-whisper-c8` (copy of the tracked `rk3576-whisper` profile with `max_concurrent_sessions` raised from 1 to 8), `WHISPER_VARIANT=base10`, `WHISPER_WINDOW_S=10`, `WHISPER_LANGUAGE=en`, `OVS_MAX_CONCURRENT_SESSIONS=8`, `WHISPER_MAX_CONCURRENT=8` |
| Model artifacts | the RK3576-correct `whisper_encoder_base_10s.rknn` (from `/home/cat/whisper-bench/model`) plus `decoder_model.onnx`/`decoder_with_past_model.onnx` (from `/home/cat/whisper-bench/onnx_dec`) and the shared vocab/mel files, assembled into the `encoder/rk/`, `decoder/base/` layout `model_downloader.py` expects under a bind mount — note `/home/cat/asrpar/whisper-model/encoder/rk/whisper_encoder_base_10s.rknn` (a different pre-existing path on this device) is actually an **RK3588** engine and fails `rknn_init` on this RK3576 board (`This rknn model is for RK3588, but current platform is RK3576`) — do not reuse that path for RK3576 |
| Corpus | same LibriSpeech test-clean public corpus regenerated for the Jetson runs in this PR, filtered to items <= 9.5 s for the 10 s window: **138 items** (this corpus regeneration produced more short items than the 76 used in the prior pass's 100-item corpus; both filters use the same <=9.5s rule) |
| Client | `bench/asr_bench/bench.py`, `--model whisper --lang en`, `ws://100.89.94.11:8622`, `--api-key testkey123` |

Startup log (confirmed fresh after every `docker restart` between levels
below, not assumed from the first one):

```
Applied profile rk3576-whisper-c8 from /opt/speech/configs/profiles/rk3576-whisper-c8.json (4 env keys; 0 stale cleared)
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS='8', profile.max_concurrent_sessions=8)
whisper: rknn encoder @10.0s window, CPU KV decoder, lang=en
ASR backend: whisper-rknn (capabilities: ['offline', 'streaming'])
ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
```

No `no max_concurrent field` warning and no `clamping to 1` line — the
admission ceiling now follows the profile.

### Results (en segments <= 9.5 s per concurrency level, `--limit` = 8x concurrency)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|
| 1 | 8  | 8  | 0 | 835.9  | 1197.6 | 0.186 | 0.17 | 11.46% |
| 2 | 16 | 16 | 0 | 774.1  | 1277.2 | 0.194 | 0.35 | 7.98%  |
| 4 | 32 | 32 | 0 | 820.1  | 1478.4 | 0.211 | 0.63 | 6.44%  |
| 8 | 64 | 64 | 0 | 1575.5 | 2754.5 | 0.380 | 1.09 | 6.28%  |

Zero errors through every level tested. WER at c=1 (11.46%, n=8) is close to
the profile's documented ~11.37% short-segment figure; it settles to
6.3-8.0% at c>=2 as the corpus subset (round-robined, more items) broadens
— not a concurrency-driven accuracy change. p95 stays under the 1.5 s bar
through c=4 (1478 ms), then rises to 2755 ms at c=8 (1.9x c=4's) — the
serialized CPU ONNX KV-cache decoder queueing more sessions than it can
service concurrently, the same mechanism documented in this profile's
description (one encoder handle, one decoder lock) and in the Jetson Whisper
sections of the companion `concurrency-orin-{nano,nx}-ceiling.md` reports in
this PR. **Recommended admission ceiling: 4** — the highest level tested
whose p95 stays under the 1.5 s bar; c=8 was the last level run per this
board's dispatch spec (c=1/2/4/8) and already shows the ceiling passed, so no
higher level was attempted.

### NPU occupancy

`/sys/kernel/debug/rknpu/load` sampled ad hoc during the c=8 run: `Core0: 11%,
Core1: 0%` — consistent with the prior pass's finding that the RKNN encoder
barely touches the NPU at this window size; the CPU ONNX KV-cache decoder is
the actual bottleneck and is invisible to this counter. This was a single
manual sample, not a continuous log across the whole sweep like the SenseVoice
section above.

### Reading

- Raising `WhisperASRConfig.max_concurrent` (the voxedge `main` 466f3e4 fix)
  turns RK3576 Whisper from a hard single-session admission clamp into the
  same serialized-decode-queue pattern already seen on both Jetson boards in
  this PR: concurrency above the decoder's real throughput becomes queueing
  latency, not an admission rejection. c=8 error-free but past the 1.5 s
  latency bar is a materially different (better) failure mode than the
  previous `too_many_sessions` rejection wall at c>=2.
- This confirms the previous section's "architectural, not admission-limiter"
  framing was specific to the *installed package version*, not something
  inherent to the RK3576 RKNN-encoder/CPU-decoder design — the same hardware
  and model artifacts now sustain c=4 cleanly once the config field exists.
- The per-item decode problem on `en_pub_00` noted in the prior pass was not
  re-investigated here (out of scope for the concurrency question this pass
  measures).
