# harvest-pi (reComputer R2000 series, Raspberry Pi 5 + Hailo-8) — SenseVoice `/asr/stream` concurrency ceiling, 100-segment corpus

Boundary: **p95 stays under 1.5 s through c=6 (1249.5 ms)**; c=8 crosses it
(1722.8 ms). The server's own admission ceiling is 8 — every request past that
(c=12, c=16) is rejected with `too_many_sessions`, not queued. **Recommended
production concurrency: 6.**

Difference from the 20-segment pass in `results/harvest-pi.md`: that pass
reported 0 errors and p95 865.7 ms at c=4 and 2280.2 ms at c=8 from only 20
segments per level (5 per worker at c=4, 2.5 at c=8) — too few draws for a
stable p95, and it only swept c=1/2/4/8, never reaching the 8-session
admission ceiling from above. `bench.py`'s workers pull from one shared queue
(`bench/asr_bench/bench.py:232-249`), so corpus size does not by itself
determine how many sessions are open at once or how evenly segments split
across workers; the reason c=12/c=16 show rejections here and not in the
prior pass is that this pass is the first to test concurrency levels above
the 8-session ceiling, not the larger corpus by itself. This pass uses 100
segments per level (vs. 20), which does make the c=2..8 latency numbers more
stable, and c=8 is now measured error-free at p95 1722.8 ms.

## Setup

| | |
|---|---|
| Device | `harvest-pi` fleet entry, reComputer R2000 series (Raspberry Pi 5 Model B, 8 GB RAM, Hailo-8 on `/dev/hailo0`, unused for this backend) |
| Image | `asrbench-rpi5-sensevoice:local`, rebuilt on-device from this repo's `deploy/docker/Dockerfile.rpi --target final-slim` (the image from the prior pass had been pruned for disk space; disk was 2.6 GB free before the rebuild, same as the prior report) |
| Backend | `cpu.sherpa_asr` (sherpa-onnx `OfflineRecognizer.from_sense_voice`, `model.int8.onnx`, CPU provider), profile `rpi5-sensevoice` |
| Streaming fix | `voxedge` bind-mounted from `/home/harvest/asrbench-pi/voxedge-src` over the image's installed wheel — routes the offline-only backend's `/asr/stream` through `OfflineAccumulateStream` (accumulate to `finalize()`), the same fix used in `results/harvest-pi.md` |
| Admission | `OVS_MAX_CONCURRENT_SESSIONS=32` requested; clamped to **8** (`session_limiter: OVS_MAX_CONCURRENT_SESSIONS=32 exceeds backend ceiling (asr=8,tts=inf) → clamping to 8`). This 8 is the `rpi5-sensevoice` profile's `asr_max_slots: 8` (`configs/profiles/rpi5-sensevoice.json:14`), which feeds `cpu.sherpa_asr`'s `concurrency_capability` via `SHERPA_ASR_MAX_CONCURRENT` (`server/core/voxedge_backend_config.py:299-318`, default 4, profile-overridable) — a configured value, not a value this codebase hardcodes; raising it would need a different profile or an env override, both out of scope for this bench-only pass |
| Corpus | `bench/asr_bench/corpus` public AISHELL-1 zh subset rebuilt to 100 items (`download_public_corpus.py --limit 100`), vs. 20 in the prior pass |
| Client | `bench/asr_bench/bench.py` from the Mac over Tailscale (`ws://100.116.230.60:8621`), `--api-key ""`, chunks fed at 1.0x real time |
| Board state | Production containers already running on this device (`xiaozhi-server`, `home-assistant`, `mysql`, `mcp_face_rec`, etc.) were left untouched throughout — none were stopped or restarted; only the test container `asrbench-pi-ceil` was created and removed |

Startup log confirms the fix and the effective ceiling:

```
session_limiter: OVS_MAX_CONCURRENT_SESSIONS=32 exceeds backend ceiling (asr=8,tts=inf) → clamping to 8
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS='32', profile.max_concurrent_sessions=8)
ASR inference gate: concurrency=8 max_waiting=0
ASR locking granularity: connection (asr sessions=8, in-flight=8, queue depth=0, mode=concurrent)
Model OK: sensevoice (SenseVoice offline ASR (5 languages))
ASR backend: sherpa_asr (capabilities: ['offline'])
ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
```

## Results (100 zh segments per concurrency level)

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER | CPU peak | RAM/swap |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 100 | 100 | 0 | 595.8 | 1028.0 | 0.123 | 0.151 | 0.33 | 5.12% | — | — |
| 4 | 100 | 100 | 0 | 602.1 | 1016.8 | 0.125 | 0.158 | 0.65 | 5.12% | — | — |
| 6 | 100 | 100 | 0 | 626.1 | 1249.5 | 0.132 | 0.192 | 0.95 | 5.12% | — | — |
| 8 | 100 | 100 | 0 | 691.8 | 1722.8 | 0.136 | 0.250 | 1.24 | 5.12% | — | — |
| 12 | 100 | 16 | 84 | 707.6 | 1048.2 | 0.130 | 0.173 | 0.97 | 6.21% (n=16) | — | — |
| 16 | 100 | 9 | 91 | 533.7 | 796.3 | 0.130 | 0.136 | 0.89 | 9.55% (n=9) | — | — |

Peak CPU sampled with `top -b -d 1` (600 one-second samples spanning the full
sweep, `top-ceiling.log`): the server process peaked at **379.2%** of the
board's 400%, at the higher-concurrency levels. `free -m` before/after the
sweep: 3809 → 3824 MB used, swap 941 → 940 MB (both pre-existing from the
other containers on this board, not moved by this test) — no swap growth
attributable to this run.

The 84/91 errors at c=12/c=16 are `too_many_sessions` rejections at connect
time (the 8-session admission ceiling), not decode failures or timeouts — the
same failure mode as cat-remote's original SenseVoice "before" pass. CER at
c=12/c=16 is computed over the 16 and 9 admitted segments respectively and is
not comparable to the c=2..8 rows (much smaller, non-random sample: whichever
segments happened to win a connection slot first).

## Reading

- p95 crosses 1.5 s between c=6 (1249.5 ms) and c=8 (1722.8 ms) — the ceiling
  by the p95 ≤ 1.5 s rule sits at **c=6**.
- Throughput rises through the admission ceiling (0.33 → 1.24 seg/s, c=2 to
  c=8) then falls once requests start being rejected (0.97 at c=12, 0.89 at
  c=16) — rejected connections do no work, so aggregate throughput drops even
  though the 8 admitted slots keep decoding.
- CER is flat at 5.12% from c=2 through c=8 (n=100 each) in this pass —
  concurrency changes when an utterance is decoded, not what comes out,
  consistent with the cat-remote finding. It differs from the single-session
  baseline in `results/harvest-pi.md` (5.48%), which used a smaller,
  different draw from the corpus (20 items vs. this pass's 100) — the two
  numbers are not measuring the same sample and should not be read as a
  match or a mismatch caused by concurrency.
- The two limits found here are independent, not one causing the other: the
  8-session admission ceiling (a profile setting, `asr_max_slots: 8`) and the
  1.5 s latency bar (crossed between c=6 and c=8) both land at/near c=8 in
  this test, but for different reasons — the admission ceiling is a
  configuration choice, while the latency crossing is a measured CPU
  contention effect. Recommending c=6 uses the latency bar, which is the
  tighter of the two on this hardware; raising `asr_max_slots` past 8 would
  not help, since c=8 already exceeds the 1.5 s target on latency grounds
  alone.
