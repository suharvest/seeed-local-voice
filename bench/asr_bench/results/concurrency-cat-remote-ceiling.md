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

## 2. Whisper (RKNN encoder + CPU KV-cache decoder) — hard-serialized by design

`rk.whisper` was confirmed present before this pass:
`docker run --rm openvoicestream:rk-20260903.10 python3 -c "from voxedge.backends.whisper import WhisperASR; print(WhisperASR)"`
→ `<class 'voxedge.backends.whisper.asr.WhisperASR'>` — the class exists in
the image's installed `voxedge` package. The image's own `server/main.py`
(built 2026-09-03) predates the `rk.whisper` / `hailo.whisper` /
`jetson.whisper_trt` entries in `server/core/asr_backend.py`'s registry, so
`server/core/asr_backend.py`, `server/core/voxedge_backend_config.py` and
`server/core/model_downloader.py` (the three files that changed together to
add Whisper registry/config/artifact support) were bind-mounted from this
worktree's `main` over the image's copies — `main.py` itself was left
untouched. The `asr_backend.py` diff against the image's baked-in copy is
7 lines: three new `_ASR_REGISTRY` entries (`hailo.whisper`, `rk.whisper`,
`jetson.whisper_trt`, all pointing at `voxedge.backends.whisper.WhisperASR`)
and a branch that routes those three specs through
`voxedge_backend_config.build_config_for_spec` — no behavior change to any
existing backend path.

**The backend admits exactly 1 concurrent session, unconditionally, by
design** — not by admission-ceiling misconfiguration. Source, both in the
image's installed `voxedge` and in `/home/cat/voxedge-whisper-src` (the
current `voxedge` worktree on this device): `voxedge/backends/whisper/asr.py`
hardcodes `concurrency_capability(..., max_concurrent=1, ...)` — there is no
`WhisperASRConfig` field or env var that raises it. `WHISPER_MAX_CONCURRENT`
only affects the *admission queue depth* the config builder requests; the
backend's own capability call overrides it back to 1 regardless. This matches
the `rk3576-whisper` profile's documented rationale: one encoder handle and
one CPU ONNX KV-cache decoder, serialized on a single lock — the same
decoder that, at the 20 s window this profile deliberately avoids, drove this
exact device into a global OOM that killed an unrelated container (see the
profile's own description in `configs/profiles/rk3576-whisper.json`).

### Setup

| | |
|---|---|
| Backend | `rk.whisper` (`voxedge.backends.whisper.WhisperASR`), RKNN encoder + CPU ONNX KV-cache decoder |
| Profile | `rk3576-whisper`, `WHISPER_VARIANT=base10`, `WHISPER_WINDOW_S=10`, `WHISPER_LANGUAGE=en` |
| Model artifacts | `whisper_encoder_base_10s.rknn`, `decoder_model.onnx` + `decoder_with_past_model.onnx`, `mel_80_filters.txt`, `vocab_en.txt`/`vocab_zh.txt` — all pre-existing on-device under `/home/cat/whisper-bench/{model,onnx_dec}`, bind-mounted individually into the `WHISPER_MODEL_DIR` layout `model_downloader.py` expects |
| Admission requested | `OVS_MAX_CONCURRENT_SESSIONS=16`, `WHISPER_MAX_CONCURRENT=16` — both clamped to the backend's hardcoded ceiling: `session_limiter: OVS_MAX_CONCURRENT_SESSIONS=16 exceeds backend ceiling (asr=1,tts=inf) → clamping to 1` |
| Corpus | English subset of the same public corpus (LibriSpeech test-clean, `download_public_corpus.py`), filtered to the **76 items ≤ 9.5 s** — `WHISPER_WINDOW_S=10` hard-truncates any longer segment at the encoder, and the 24 items over 10 s in the full 100-item en set produced truncated, WER-inflated transcripts (a c=1 smoke test on the untruncated corpus showed 87.5% error on one >10 s item); filtering to fit-the-window segments isolates the concurrency effect from the truncation artifact |
| Client | `bench/asr_bench/bench.py`, `--model whisper --lang en`, `ws://100.89.94.11:8622`, `--api-key ""` |

Startup log:

```
Applied profile rk3576-whisper from /opt/speech/configs/profiles/rk3576-whisper.json (4 env keys; 0 stale cleared)
whisper.rknn: admission ceiling 16 requested but this voxedge build has no max_concurrent field on WhisperASRConfig — staying at 1 slots
session_limiter: OVS_MAX_CONCURRENT_SESSIONS=16 exceeds backend ceiling (asr=1,tts=inf) → clamping to 1
SessionLimiter initialized: effective_limit=1 (env OVS_MAX_CONCURRENT_SESSIONS='16', profile.max_concurrent_sessions=1)
whisper: rknn encoder @10.0s window, CPU KV decoder, lang=en
ASR backend: whisper-rknn (capabilities: ['offline', 'streaming'])
ASR executor: max_workers=1 (source=asr_cap.max_concurrent)
```

### Results (76 en segments ≤ 9.5 s per concurrency level)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 76 | 76 | 0 | 719.3 | 1048.9 | 0.159 | 0.274 | 0.166 | 6.22% |
| 2 | 76 | 5 | 71 | 889.1 | 1066.4 | 0.167 | 0.288 | 0.166 | 22.07% (n=5) |
| 4 | 76 | 2 | 74 | 911.4 | 1073.5 | 0.251 | 0.306 | 0.202 | 43.75% (n=2) |
| 8 | 76 | 1 | 75 | 1059.4 | 1059.4 | 0.303 | 0.303 | 0.204 | 87.5% (n=1) |
| 12 | 76 | 1 | 75 | 1059.4 | 1059.4 | 0.303 | 0.303 | 0.205 | 87.5% (n=1) |

The WER figures at c≥2 are not concurrency-driven accuracy loss — they are
computed over 1-5 lucky segments out of 76 (whichever connection won the
single admission slot before the rest were rejected) and swing with which
segments happened to get through, not with load. The only concurrency level
with a real sample is c=1 (n=76, WER 6.22%). Errors at c≥2 are
`too_many_sessions` at connect time, the same admission-rejection pattern as
SenseVoice's original single-core baseline and harvest-pi's c=12/16 rows
above.

**Accuracy caveat, separate from concurrency**: the single item that succeeded
at c=8 and c=12 (`en_pub_00`, 3.5 s — well inside the 10 s window, so this is
not the truncation effect described above) scored 87.5% WER with repeated
text in the transcript. This is a per-item decode problem on this backend,
not something the 9.5 s corpus filter explains or fixes; it is not evaluated
further here since it is orthogonal to the concurrency question this pass
measures.

### NPU occupancy

`/sys/kernel/debug/rknpu/load`, 2 s samples spanning the full 5-level sweep
(264 samples): 44 samples with Core0 active, peak Core0 **12%**, Core1 flat
at 0% throughout. Whisper's RKNN encoder barely touches the NPU — the 10 s
window is a small, quick encode; the CPU ONNX KV-cache decoder is the
component doing the work, and it is invisible to this NPU counter.

### Reading

- The concurrency sweep does not change the finding: c=1 is the only usable
  level on RK3576 Whisper, by construction. `WHISPER_MAX_CONCURRENT` and
  `OVS_MAX_CONCURRENT_SESSIONS` are accepted but both get overridden back to
  1 by the backend's own `concurrency_capability()` call — there is no
  profile flag, env var, or session-limiter setting in this codebase version
  that raises RK Whisper past 1 concurrent session.
- At c=1, latency is comparable to SenseVoice's single-session numbers (p95
  1048.9 ms vs SenseVoice's 1316.5 ms at c=4) and NPU load is far lower (peak
  12% vs SenseVoice's 81%) — the ceiling here is architectural
  (single-decoder-lock), not NPU compute.
- Raising this ceiling is a code change (giving `WhisperASRConfig` a real
  `max_concurrent` and either pooling decoder instances or accepting
  serialized-but-queued admission like SenseVoice's stage-b queue), out of
  scope for this bench-only task. The profile's own rationale — a global OOM
  this device hit at the 20 s window — is reason to treat "how many decoder
  instances actually fit in RAM" as a real open question before raising it,
  not just an admission-limiter setting.
