# harvest-pi (reComputer R2000 series, Raspberry Pi 5 + Hailo-8) — SenseVoice and Whisper `/asr/stream` concurrency ceilings, 100-segment corpora

Both passes ran on an **idle board**: all ten containers that were running
beforehand were stopped for the whole sweep and restarted afterwards.

Two separate limits. On latency (p95 ≤ 1.5 s), the largest level that clears
the bar is **c=6 for SenseVoice** — c=8 measured 1265.2–3058.4 ms over four
passes and c=12 measured 1565.5 ms, while c=6 measured 1172.6 ms.

Whisper's original c=8 admission rejections and its per-level WER drift were
both bench-client artifacts (the client raced the server's own VAD against
its EOS frame — see "History (superseded below)" in the Whisper section) and
do not reproduce after `bench.py` was fixed to pin `?vad=none`. Rerun with
the fixed client and a `voxedge` build that gives `WHISPER_MAX_CONCURRENT` a
real effect: zero errors and zero rejections through c=16, WER byte-identical
(8.39%) at every level, 0/100 transcripts differing from c=1 at any level.
Recommended production concurrency: **6** for SenseVoice (the latency bar),
**16** for Whisper (highest level tested, p95 1465.3 ms, still under the
1.5 s bar).

## Setup

| | |
|---|---|
| Device | `harvest-pi` fleet entry, reComputer R2000 series (Raspberry Pi 5 Model B, 8 GB RAM, Hailo-8 on `/dev/hailo0`) |
| Board state | The ten containers running before this pass (`missionpack-industrial-gateway`, `xiaozhi-server`, `xiaozhi-esp32-server-web`, `xiaozhi-esp32-server-redis`, `xiaozhi-esp32-server-db`, `mcp-endpoint-server`, `recamera-mqtt`, `recamera-ha`, `mcp_warehouse`, `mcp_face_rec`) were **stopped** before the first bench and restarted after the last. Idle `top` before the runs: 95.3% id, 1637 MB used, 457 MB swap. `mcp_face_rec` holds `/dev/hailo0`, so stopping it is also what frees the NPU for the Whisper pass |
| Images | Both built on-device from this repo's `deploy/docker/Dockerfile.rpi`: `--target final-slim` → `asrbench-rpi5-sensevoice:r2000clean` (`sha256:968aa4f9fa90…`, 593 MB), `--target final-hailo` → `asrbench-rpi5-hailo-whisper:r2000` (`sha256:2c5069e42558…`, 657 MB). The `final-hailo` stage as committed drops an `LD_LIBRARY_PATH=/usr/lib` that this image carried; `import hailo_platform` was re-checked on a rebuild without it (`sha256:f6d9bf16557a…`) |
| voxedge | `voxedge-0.0.13a0-py3-none-any.whl`, built from voxedge `origin/main` at `15de2bb` (`uv build --wheel`), sha256 `8f1c2cf8995d4826749f3cacaea883faa1d75fa9149fe77fdae4b9ca2f3cc849`. Installed into each container over the image's pinned wheel (`pip3 install --no-deps --force-reinstall`); `pip3 show voxedge` in-container reports 0.0.13a0 |
| Server code | `server/` and `configs/` bind-mounted from OpenVoiceStream `origin/main` at `4d66f475` |
| Client | `bench/asr_bench/bench.py` from the Mac over Tailscale (`ws://100.116.230.60:8621`), `--api-key ""`, chunks fed at 1.0x real time |

### SenseVoice

| | |
|---|---|
| Backend | `cpu.sherpa_asr` (sherpa-onnx `OfflineRecognizer.from_sense_voice`, `model.int8.onnx`, CPU provider), profile `rpi5-sensevoice` |
| Admission | Raised from the profile's `asr_max_slots: 8` to 16 for this pass (`SHERPA_ASR_MAX_CONCURRENT=16`, `OVS_MAX_CONCURRENT_SESSIONS=16`), so c=12 is measured on latency rather than clipped by the ceiling — the prior pass rejected 84/100 segments at c=12 for that reason |
| Corpus | 100 zh AISHELL-1 items (`corpus/download_public_corpus.py`, speaker S0002 train-range mirror), 500.8 s of audio |

Startup log:

```
SessionLimiter initialized: effective_limit=16 (env OVS_MAX_CONCURRENT_SESSIONS='16', profile.max_concurrent_sessions=8)
ASR inference gate: concurrency=16 max_waiting=0
ASR locking granularity: connection (asr sessions=16, in-flight=16, queue depth=0, mode=concurrent)
Model OK: sensevoice (SenseVoice offline ASR (5 languages))
Creating ASR backend cpu.sherpa_asr (voxedge.backends.sherpa.asr.SherpaASRBackend)
ASR backend: sherpa_asr (capabilities: ['offline'])
ASR executor: max_workers=16 (source=asr_cap.max_concurrent)
```

### Whisper on Hailo-8

| | |
|---|---|
| Backend | `hailo.whisper` (`voxedge.backends.whisper.WhisperASR`), profile `rpi5-hailo-whisper`: Whisper **base** encoder as `base-whisper-encoder-5s.hef` on the NPU, decoder as an ONNX KV-cache graph on the CPU. 5 s compiled window with a 1 s boundary guard → 4 s usable |
| HailoRT | Host `hailortcli fw-control identify` → firmware 4.21.0; host `dpkg -l` → `hailort` / `hailort-pcie-driver` 4.21.0. Container carries `hailort-4.21.0-cp311-cp311-linux_aarch64.whl` (md5 `2fde57f853ea66d670a60e68b4ca15da`) and bind-mounts the host's `/usr/lib/libhailort.so.4.21.0` — same version on both sides |
| Artifacts | Downloaded at first start from `harvestsu/whisper-edge` via `HF_ENDPOINT=https://hf-mirror.com`: the 46,075,038-byte HEF, the base decoder pair, `vocab_en.txt`, `vocab_zh.txt`, `mel_80_filters.txt` |
| Admission | `OVS_MAX_CONCURRENT_SESSIONS=8` and `WHISPER_MAX_CONCURRENT=8` against a profile that ships `max_concurrent_sessions: 1`. Admission is 8; **execution stays serialized** — the backend keeps one encoder handle and one KV cache behind a lock, so the extra slots buy queueing, not parallelism |
| Corpus | 100 LibriSpeech test-clean items filtered to **duration ≤ 4.0 s** (the usable window), 296.4 s of audio, so no segment is split by the window |

Startup log:

```
Applied profile rpi5-hailo-whisper from /opt/speech/configs/profiles/rpi5-hailo-whisper.json (6 env keys; 0 stale cleared)
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS='8', profile.max_concurrent_sessions=1)
ASR inference gate: concurrency=1 max_waiting=7
ASR locking granularity: sentence (asr sessions=8, in-flight=1, queue depth=7, mode=serialized)
Whisper asset ready: encoder/hailo/base-whisper-encoder-5s.hef (46075038 bytes)
Creating ASR backend hailo.whisper (voxedge.backends.whisper.WhisperASR)
whisper: hailo encoder @5.0s window, CPU KV decoder, lang=en
ASR backend: whisper-hailo (capabilities: ['streaming', 'offline'])
ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
```

## SenseVoice — 100 zh segments per level, idle board

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | CER (per-segment mean) | CER (corpus aggregate) |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 100 | 100 | 0 | 689.9 | 1220.3 | 0.132 | 0.235 | 0.32 | 5.12% | 4.82% |
| 4 | 100 | 100 | 0 | 639.0 | 1240.6 | 0.126 | 0.235 | 0.65 | 5.12% | 4.82% |
| 6 | 100 | 100 | 0 | 624.9 | 1172.6 | 0.131 | 0.170 | 0.95 | 5.12% | 4.82% |
| 8 | 100 | 100 | 0 | 723.0 | 3058.4 | 0.142 | 0.495 | 1.19 | 5.12% | 4.82% |
| 12 | 100 | 100 | 0 | 791.4 | 1565.5 | 0.157 | 0.257 | 1.78 | 5.12% | 4.82% |

Peak CPU during the sweep, `top -b -d 1`: the server process reached **393.1%**
of the board's 400%. Peak system memory used **2385 MB** (1637 MB idle); swap
unchanged at 457 MB.

The c=8 p95 of 3058.4 ms is above both its neighbours, so c=8 was re-run three
more times on the same corpus and container:

| Repeat | OK | Errors | p50 (ms) | p95 (ms) | Throughput (seg/s) |
|---|---|---|---|---|---|
| 1 | 100 | 0 | 630.2 | 1458.9 | 1.25 |
| 2 | 100 | 0 | 699.6 | 1555.9 | 1.25 |
| 3 | 100 | 0 | 659.9 | 1265.2 | 1.24 |

Across the four c=8 passes p95 is 1265.2 / 1458.9 / 1555.9 / 3058.4 ms — c=8
sits on the 1.5 s line rather than under it, and one pass in four ran twice
that. c=6 (1172.6 ms) and c=12 (1565.5 ms) each measured once.

Two differences from the previous 100-segment pass in this repo's history:
the board is idle here (that pass ran alongside all ten production containers),
and admission was raised to 16, so c=12 completes 100/100 instead of rejecting
84. Throughput now keeps climbing to 1.78 seg/s at c=12 instead of falling
back once rejections start.

CER is identical at every level, per-segment mean 5.12% and corpus-aggregate
4.82% — concurrency changes when an utterance is decoded, not what comes out.

## Whisper on Hailo-8 — 100 en segments (≤ 4 s) per level, idle board

| Concurrency | Segments | OK | Err | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | WER (per-segment mean) | WER (corpus aggregate) | Hailo util | RAM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 100 | 0 | 310.6 | 1428.1 | 0.108 | 0.530 | 0.25 | 24.43% | 23.00% | 4.0% @ 1.0 FPS | — |
| 2 | 100 | 100 | 0 | 302.1 | 986.6 | 0.102 | 0.438 | 0.50 | 23.40% | 21.86% | 15.0% @ 4.0 FPS | — |
| 4 | 100 | 100 | 0 | 303.4 | 1093.2 | 0.105 | 0.359 | 1.04 | 24.21% | 22.62% | 16.2% @ 4.0 FPS | — |
| 8 | 100 | 70 | 30 | 506.5 | 1085.6 | 0.175 | 0.397 | 1.83 | 21.61% (n=70) | 20.77% (n=70) | 25.0% @ 6.0 FPS | — |
| 8 (repeat) | 100 | 78 | 22 | 492.6 | 1021.5 | 0.165 | 0.370 | 1.92 | 20.95% (n=78) | 20.22% (n=78) | — | — |

Peak CPU during the sweep: the server process reached **381%** of 400%. Peak
system memory used **2159 MB**, against 1637 MB at idle before the container
started; both are whole-system readings and were not broken out per process,
so the 522 MB difference is not attributable to the container alone. Swap
unchanged at 457 MB. The RAM column is per-level blank because `top` was
sampled across the whole sweep, not per concurrency level.

Hailo utilization is the `base-whisper-encoder-5s` row of `hailortcli monitor`
(`HAILO_MONITOR=1` in the container, `/tmp/hmon_files` shared with the host),
sampled for 30 s inside each level; the device-wide row matched the model row
at c=8 (25.0%), so nothing else was using the NPU. The highest of these samples is a
quarter of the NPU, taken at the level where the server is already rejecting
connections. Sampling was 30 s per level, not continuous, so these are the
values observed in those windows rather than bounds on the whole sweep.

All 30 (and 22 on the repeat) c=8 failures are the same message at connect
time:

```
received 4429 (private use) {"error": "too_many_sessions", "current": 8, "limit": 8}
```

The limiter reports 8 of 8 slots in use, so these are admission rejections and
not decode failures. Both c=8 passes hit them, at 30 and 22 of 100; whether the
cause is a worker's reconnect racing the previous session's slot release was
not instrumented.

61 of the 100 c=1 segments produced at least one `is_final` before end-of-audio
(`pre_eos_finals` 1–4), i.e. the server-side endpointer cut them mid-feed and
the client scored the joined text. For those rows `rtf` is not a decode-only
figure. Whisper's WER also moves by roughly a point between concurrency levels
here, while SenseVoice's CER is identical at every level. This pass did not
isolate what varies, so the two observations are reported side by side without
a link between them.

WER is word-level on lowercased, unpunctuated text (`bench.py:84-118`). The
per-segment mean runs about a point above the corpus aggregate: it weights
every utterance equally, and one wrong word is a large fraction of a 3-second
clip.

**History (superseded below):** the table above and its per-level WER drift
were collected with a bench client that opened `/asr/stream` with the server
VAD left on while also sending the EOS frame; under load the client's own
EOS raced the server's endpoint detector, and the client scored whichever
`is_final` arrived first as the whole segment. `bench.py` now pins
`?vad=none` and accumulates every final. The c=8 `too_many_sessions`
rejections were a real admission-ceiling limit at the time (`voxedge==0.0.13a0`
had no `max_concurrent` field, so `WHISPER_MAX_CONCURRENT` had no effect);
that has since been fixed upstream (see below).

### Rerun with the fixed client and a real admission ceiling

Image/profile/artifacts unchanged (`asrbench-rpi5-hailo-whisper:r2000b`,
profile `rpi5-hailo-whisper`, HEF + decoder cached on-device). voxedge
`0.0.12a0` replaced with a wheel built from `voxedge` `main` 466f3e4 (the
same commit as the J3011/J4012/RK3576/RK3588 reruns), `pip3 install --no-deps
--force-reinstall` then `docker restart`; server confirmed at startup
`ASR executor: max_workers=16 (source=asr_cap.max_concurrent)` —
`OVS_MAX_CONCURRENT_SESSIONS=16` now actually takes effect instead of
clamping to 1. `OVS_API_KEYS=testkey123`, bench run with `--api-key`.
`mcp_face_rec` stopped for the run (holds `/dev/hailo0`) and restarted after.

Corpus: the same 100-item en <=4.0 s subset as the table above (verified
byte-identical ref/duration match against a fresh draw from the same
HF-mirror parquet), the same 100 items reused at every concurrency level.

| Concurrency | Segments | OK | Errors | p50 (ms) | p95 (ms) | RTF p50 | RTF p95 | Throughput (seg/s) | WER (aggregate) |
|---|---|---|---|---|---|---|---|---|---|
| 1  | 100 | 100 | 0 | 305.3 | 491.6  | 0.106 | 0.186 | 0.28 | 8.39% |
| 2  | 100 | 100 | 0 | 314.1 | 520.8  | 0.109 | 0.198 | 0.55 | 8.39% |
| 4  | 100 | 100 | 0 | 330.6 | 690.8  | 0.115 | 0.282 | 1.07 | 8.39% |
| 8  | 100 | 100 | 0 | 340.1 | 870.4  | 0.118 | 0.362 | 2.06 | 8.39% |
| 12 | 100 | 100 | 0 | 472.6 | 1300.0 | 0.168 | 0.431 | 2.62 | 8.39% |
| 16 | 100 | 100 | 0 | 751.7 | 1465.3 | 0.261 | 0.547 | 3.60 | 8.39% |

Zero errors and zero admission rejections through c=16 — the `too_many_sessions`
failures in the withdrawn table above do not reproduce; the real
`max_concurrent` field removes the clamp that made `WHISPER_MAX_CONCURRENT`
a no-op. WER is byte-identical (8.39% aggregate) at every level, and every
segment's transcript is identical to its c=1 text at every other level (0/100
differ at c=2, c=4, c=8, c=12, c=16). `pre_eos_finals` is 0 for every segment
at every level (the withdrawn table's 61/100 mid-feed cuts at c=1 do not
reproduce with `?vad=none` pinned). **Recommended admission ceiling: 16** —
the highest level tested, with p95 (1465.3 ms) still under the 1.5 s bar;
c=16 was the top of this pass's requested range and was not shown to be this
board's hardware ceiling, only the highest level that stayed clean.

## Reading

- Both paths are CPU-heavy: SenseVoice peaked at 393.1% of 400% and Whisper at
  381%, since Whisper's decoder also runs on the CPU and only its encoder is on
  the NPU. On latency they land close: p50 is 625–791 ms for SenseVoice across
  its sweep and 302–507 ms for Whisper. Whisper's lower p50 comes with a 5 s
  window that only fits short utterances, and with rejections starting at c=8
  while SenseVoice was still completing 100/100 there.
- Throughput at the recommended level: SenseVoice 0.95 seg/s at c=6, Whisper
  1.04 seg/s at c=4. Whisper's segments are shorter (2.96 s mean vs. 5.01 s),
  so in audio-seconds per wall-second SenseVoice does 4.78 and Whisper 3.09.
- Accuracy is not comparable across the two sections — different languages,
  different corpora, character-level vs. word-level scoring. SenseVoice: 4.82%
  corpus-aggregate CER on zh AISHELL-1. Whisper base on Hailo: 23.00%
  corpus-aggregate WER on LibriSpeech test-clean clips ≤ 4 s at c=1. Compare
  aggregate with aggregate and mean with mean; the two columns are different
  statistics over the same transcripts.
- The Hailo-8 sampled at 25% utilization at the highest level tested, and at
  4–16% below that. What would happen at c=5/6/7, or with the admission
  ceiling raised above 8, was not measured — those levels were not run.
