# ASR concurrency — reComputer J3011 (Jetson Orin Nano), Whisper

SenseVoice on this board is already measured in
`concurrency-orin-nano.md`/`.json` (not repeated here). This file covers the
Whisper pass on the same board, run separately per this task's recipe.

Corpus: 20 LibriSpeech test-clean en utterances (CC BY 4.0). Transport:
`/asr/stream` WebSocket, fed at 1.0x real time, one `is_final` per segment.
Latency = audio-end to `is_final`.

Server confirmed ready before the sweep: `SessionLimiter initialized:
effective_limit=8` and `ASR executor: max_workers=8` both present in the
container log.

Profile `orin-whisper`: backend `jetson.whisper_trt`, base model, `.plan`
built on-device with `--bf16` (confirmed in the container log: "Building
Whisper TRT encoder (host TRT 10.3.0, bf16)"). `asr_max_slots=8`,
`max_concurrent_sessions=8`, `execution_policy.mode=concurrent` — one shared
encoder handle and decoder KV cache, admission past the first session queues
rather than 429s.

| c | OK | Err | p50 (ms) | p95 (ms) | RTF p50 | Throughput (seg/s) | WER |
|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 521.3 | 1081.0 | 0.085 | 0.11 | 3.62% |
| 2 | 20 | 0 | 456.4 | 878.1 | 0.070 | 0.21 | 3.62% |
| 4 | 20 | 0 | 525.4 | 1144.9 | 0.075 | 0.40 | 3.62% |
| 8 | 19 | 1 | 752.4 | 1349.6 | 0.106 | 0.62 | 3.81% |

Throughput scales 0.11 -> 0.62 seg/s (5.6x) from c=1 to c=8. One segment
failed at c=8 (19/20 ok); WER at c=8 (3.81%) is computed over the successful
segments only, so it is not directly comparable to the other three levels'
3.62% (same 20-segment set). p50 stays at or under 525 ms through c=4 and
rises to 752 ms at c=8; p95 stays under 1.15 s through c=4 and reaches 1.35 s
at c=8.
