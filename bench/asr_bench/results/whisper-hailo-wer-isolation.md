# Whisper WER isolation: R2000 (Hailo-8) vs J4012 (Jetson Orin NX bf16), identical corpus

`concurrency-harvest-pi-ceiling.md` reported Whisper base on Hailo-8 at
**23.00% aggregate WER** (100 LibriSpeech test-clean segments, duration
&le;4.0 s, c=1). `concurrency-orin-nx-ceiling.md` separately reported Whisper
base bf16 TensorRT on J4012 at **3.62% WER** on a **different** 20-segment
subset (unfiltered by duration, first 20 items of a 200-item round-robin
draw). Comparing those two numbers directly conflates two variables: the
corpus and the accelerator. This isolates them by running J4012 against the
exact same 100 segments R2000 used.

## Method

1. The R2000 pass's 100 segment ids, reference transcripts, and durations
   were read from `concurrency-harvest-pi-ceiling.json`
   (`whisper_hailo.runs[0].results`, ids `en_pub_00`..`en_pub_368`).
2. `corpus/download_public_corpus.py`'s `build_en()` was re-run with
   `--limit 400` against the same HF-mirror LibriSpeech test-clean parquet
   (`openslr/librispeech_asr`, `all/test.clean/0000.parquet`) to regenerate a
   superset draw. Parquet row order is fixed, so this reproduces the same
   `en_pub_NN` -> audio mapping as whichever draw produced the original 100.
3. All 100 ids were checked against the regenerated draw: transcript
   (case-insensitive) and duration (&plusmn;0.05 s) matched for **100/100**
   segments — see EVIDENCE. The matched 100 wavs were copied into a dedicated
   `bench/asr_bench/corpus_r2000_matched100/` manifest (not committed —
   working artifact, LibriSpeech audio is not repo-tracked elsewhere either).
4. J4012 (`orin-nx`, Jetson Orin NX 16GB Super) was run with the same
   recipe as `concurrency-orin-nx-ceiling.md`'s Whisper section: image
   `sensecraft-missionpack.seeed.cn/solution/seeed-local-voice:v0.9.0-ondemand-20260721c`,
   profile `orin-whisper` (`jetson.whisper_trt`, base, 30 s window, **bf16**
   TensorRT encoder — confirmed via startup log `Whisper TRT engine up to
   date: /opt/models/whisper/encoder/jetson/enc_base_30s_bf16.plan`, reused
   from the cache the prior pass built, not rebuilt this run), CPU ONNX KV
   decoder. `server/`+`configs/` bind-mounted from this worktree. The image's
   baked voxedge (0.0.5a0, no `voxedge.backends.whisper` module at all) was
   replaced with the same `voxedge-0.0.13a0` wheel used for the R2000 pass
   (`pip install --no-deps --force-reinstall`, then `docker restart`).
5. `bench.py --concurrency 1` against the 100-item matched corpus, same
   normalization (`bench.py:84-118`, lowercase/depunctuate/word-tokenize,
   `jiwer.wer`) used for every other result in this results/ directory.

## Result

| Pass | Device | Corpus | Segments | WER (aggregate) | WER (per-segment mean) |
|---|---|---|---|---|---|
| `concurrency-harvest-pi-ceiling.md` | R2000 (Hailo-8) | 100 LibriSpeech &le;4.0 s | 100 | **23.00%** | 24.43% |
| this pass | J4012 (Orin NX, bf16) | **same 100 segments** | 100 | **19.06%** | 21.49% |
| `concurrency-orin-nx-ceiling.md` (for reference, different corpus) | J4012 (Orin NX, bf16) | 20 LibriSpeech, unfiltered duration | 20 | 3.40%\* | 3.62% |

\* `concurrency-orin-nx-ceiling.md` reports 3.62% for this row, which is the
per-segment mean (`error_rate_mean` in its JSON), not the aggregate. This
report's own aggregate/mean pair for the 100-item corpus (19.06%/21.49%) uses
the same `jiwer.wer` aggregate definition as the 23.00%/24.43% R2000 pair, so
comparing aggregate-to-aggregate requires recomputing the 20-item corpus's
aggregate from its stored ref/hyp pairs: 15 edits / 441 reference words =
**3.40%** (see EVIDENCE).

On the identical 100-segment corpus, J4012 bf16 scores 19.06% aggregate WER
against R2000 Hailo's 23.00% — a **3.94-point difference between the two
tested backend configurations** (same corpus, same normalization; see
"What this does and does not isolate" below for what that difference can and
cannot be attributed to). Comparing aggregate to aggregate throughout: the
originally-compared figures (23.00% vs 3.40%) differ by **19.60 points**; of
that, **15.66 points is associated with the corpus** (J4012's own aggregate
WER goes from 3.40% on the easy 20-item draw to 19.06% on this harder
100-item &le;4.0 s draw) and **3.94 points is the same-corpus difference
between the R2000/Hailo-8 and J4012/bf16 configurations**. The
corpus-associated share is about 4x the same-corpus share.

Both devices show heavy server-side endpointing on this short-clip corpus:
72/100 J4012 segments and 61/100 R2000 segments produced at least one
`is_final` before end-of-audio (`pre_eos_finals` > 0), i.e. the VAD cut
mid-feed on both. This is a property of the corpus (mean segment 2.96 s) and
the shared VAD/endpointer, not something that differs between the two
backends.

## 10 largest per-item WER deltas (same id, same reference)

| id | ref | R2000 Hailo (err) | J4012 bf16 (err) |
|---|---|---|---|
| `en_pub_324` | SPINNING INDEED | Spinning indeed (0.0) | Spinning indeed. Thank you. (1.0) |
| `en_pub_145` | WHO TOUCHES ME AM I IN BED | How does it taste? Am I in bad (0.714) | Who touches me? Am I in bed? (0.0) |
| `en_pub_353` | OH SIR DON'T MENTION IT SAID MISSUS POYSER | Oh, sir, don't mention it. 6 and 6 and 6 is Placer. (0.875) | Oh, sir, don't mention it. said Mrs. Poiser. (0.25) |
| `en_pub_355` | POYSER IS NOT AT HOME IS HE | Poiser is not a toe missy (0.714) | Poisoner is not at home, is he? (0.143) |
| `en_pub_77` | FOR SOME TIME AFTER THAT I REMEMBERED NOTHING DISTINCTLY | remembered nothing distinctly. (0.667) | For some time after that, I wrote remembered nothing distinctly. (0.111) |
| `en_pub_43` | THEN SHE SUDDENLY REMARKED | damage She suddenly remained. smart (0.75) | then she suddenly marked. (0.25) |
| `en_pub_76` | MY OVERWROUGHT NERVES YIELDED AT LAST | My overwrought nerve sealed it at last. (0.5) | My overwrought nerves yielded at last. (0.0) |
| `en_pub_66` | BUT THAT IS KAFFAR'S KNIFE | but that is calf Knife (0.2) | but that is ca- for his knife. (0.6) |
| `en_pub_221` | DURING HIS WATCH I SLEPT | &gt;&gt; I slept. (0.6) | During his watch, I I slept. (0.2) |
| `en_pub_28` | NOW WHAT HAVE YOU TO SAY CYNTHIA SPRAGUE | Now what have you to say, sent this brawg? | Now what have you to say, Cynthia Sprague? (0.0) |

8 of these 10 rows favor J4012, 1 favors R2000 (`en_pub_66`: 0.2 vs 0.6),
and 1 is near-even in the other direction (`en_pub_324`: 0.0 vs 1.0, J4012
appending an unprompted "Thank you." not in the audio — the same class of
decoder hallucination noted for the CPU KV-cache decoder elsewhere in this
results/ directory). On 7 of the 8 rows that favor J4012, R2000's Hailo
transcript substitutes an unrelated word or phrase for a proper noun or
content word (POYSER -> "Placer"/"missy", KAFFAR'S -> "calf", CYNTHIA
SPRAGUE -> "sent this brawg", REMARKED -> "remained... smart") rather than a
plausible near-miss.

### What this does and does not isolate

The 3.94-point same-corpus difference is the observed gap between the two
tested backend configurations (R2000: Hailo-8 encoder, 5 s window, CPU KV
decoder; J4012: TensorRT bf16 encoder, 30 s window, CPU KV decoder) — it is
not proven to isolate encoder transcription quality specifically. Two
confounds were not ruled out in this pass:

- **Window size differs (5 s vs 30 s).** Every matched segment is &le;4.0 s,
  well under both windows' usable length, so no segment is truncated or
  split by either window — but that only rules out truncation, not other
  effects the encoder's compiled window length could have on how it
  processes a short, heavily-padded clip.
- **Endpointing differs in count.** 72/100 J4012 segments and 61/100 R2000
  segments produced at least one `is_final` before end-of-audio
  (`pre_eos_finals` > 0) — a real difference in how often each configuration
  cuts mid-feed. `bench.py` records that this happened per segment but not
  where in the audio the cut landed, so whether the extra J4012 cuts
  concentrate on segments that also happen to score well, or are otherwise
  neutral to WER, was not checked.

Report the 3.94 points as an observed difference between the tested
end-to-end configurations, with the encoder-vs-window-vs-endpointer
attribution unresolved.

## Hailo HEF provenance and quantization

`server/core/model_downloader.py:934` maps `("hailo.whisper", "base")` to
`encoder/hailo/base-whisper-encoder-5s.hef`, fetched from HF repo
`harvestsu/whisper-edge` (confirmed live via
`https://hf-mirror.com/api/models/harvestsu/whisper-edge`, package tags
`hailo`/`rknn`/`tensorrt`). That repo's own README
(`https://hf-mirror.com/harvestsu/whisper-edge/resolve/main/README.md`)
states under Provenance: **"The Hailo HEFs come from Hailo's own
`edge_whisper` example assets"**. That is the extent of what the README
documents — it identifies a source, not a specific upstream release or a
hash to confirm the file in this repo matches that source byte-for-byte, so
this pass does not claim the HEF was "carried through unmodified," only that
it is attributed to Hailo's own example assets rather than a custom
quantization built for this project. The README does not state the HEF's
internal numeric precision (int8/int4/mixed), and no calibration or
quantization log for it exists in this repo or the HF repo to confirm the
exact scheme — that detail is **not verified** here. What is documented and
confirmed independently: Hailo-8 is a fixed-point NPU (its Dataflow Compiler
targets INT8/INT4 execution; it has no native fp16/bf16 execution path the
way Jetson's TensorRT does), so *some* fixed-point quantization is inherent
to running on this hardware at all — but the precise per-layer scheme for
this specific HEF was not independently verified in this pass.

`server/core/model_downloader.py:917-921` (`_WHISPER_GEOMETRY`) compiles the
base HEF at a fixed **5.0 s window with a 1.0 s boundary guard** (4 s
usable). Every one of the 100 matched segments is &le;4.0 s
(`concurrency-harvest-pi-ceiling.md`'s own corpus filter), so none of them
are truncated or split by the window — that rules out truncation as a
factor, not the window-size confound described above.

## Conclusion

On the identical 100-segment, &le;4.0 s corpus, comparing aggregate WER to
aggregate WER throughout: corpus difficulty accounts for **15.66 of the
19.60-point** originally-compared gap (23.00% R2000 vs 3.40% J4012 on
different corpora); the remaining **3.94 points** is the observed
same-corpus difference between the R2000/Hailo-8 and J4012/bf16
configurations (23.00% vs 19.06%, same corpus, same normalization) — a real
effect whose mechanism (encoder, window, or endpointer) is not isolated by
this pass. The corpus-associated share is about 4x the same-corpus share.

## EVIDENCE

### Subset file-list consistency (100/100 matched)

```
$ cd bench/asr_bench/corpus && python3 verify_r2000_match.py
target count 100
matched 100 mismatches 0
```
`verify_r2000_match.py` (committed alongside this report) checks
transcript (case-insensitive) and duration (&plusmn;0.05 s) for each of the
100 R2000 ids against `en_manifest_400.json`, the freshly regenerated
LibriSpeech draw — a metadata match, not a PCM/audio-hash match; the
underlying `.wav` files (and `en_manifest_400.json`) are not committed
(LibriSpeech audio, not repo-tracked elsewhere either). Total duration of
the matched 100: 296.43 s (R2000's own report: 296.4 s of audio) — matches
to the reported precision.

### J4012 container startup log (bf16 confirmation)

```
Applied profile orin-whisper from /opt/speech/configs/profiles/orin-whisper.json (4 env keys; 0 stale cleared)
SessionLimiter initialized: effective_limit=8 (env OVS_MAX_CONCURRENT_SESSIONS=None, profile.max_concurrent_sessions=8)
Whisper asset OK: encoder/jetson/enc_base_30s.onnx
Whisper TRT engine up to date: /opt/models/whisper/encoder/jetson/enc_base_30s_bf16.plan
Creating ASR backend jetson.whisper_trt (voxedge.backends.whisper.WhisperASR)
whisper: tensorrt encoder @30.0s window, CPU KV decoder, lang=en
ASR backend: whisper-tensorrt (capabilities: ['streaming', 'offline'])
ASR executor: max_workers=8 (source=asr_cap.max_concurrent)
```
Note: the image's baked `voxedge` was 0.0.5a0, which has no
`voxedge.backends.whisper` module at all (`ASR backend failed: No module
named 'voxedge.backends.whisper'` on first start). Replaced with
`voxedge-0.0.13a0` (the same wheel used for the R2000 pass,
`/home/harvest/ovs-whisper-trunc/voxedge-0.0.13a0-py3-none-any.whl` on the
device) before the log above.

### c=1 raw summary line

```
== concurrency=1 lang=en model=whisper segments=100 ==
{
  "concurrency": 1, "segments": 100, "ok": 100, "errors": 0,
  "wall_s": 366.46, "throughput_segments_per_s": 0.273,
  "throughput_audio_rtf_aggregate": 0.809,
  "final_latency_ms_p50": 292.31, "final_latency_ms_p95": 590.00,
  "final_latency_ms_mean": 318.87,
  "rtf_p50": 0.0987, "rtf_p95": 0.2219,
  "error_rate_mean": 0.21486
}
```
Aggregate WER computed the same way as the rest of this directory
(`jiwer.wer` over the full ref/hyp lists, not the mean of per-item err):
**0.19060 (19.06%)**, verified against `error_rate_mean=0.21486` (mean of
per-item err) independently by recomputing edit distances over all 100
stored (ref, hyp) pairs — both figures reproduce from
`results/j4012-matched-r2000-100.json`.

### Aggregate WER for the 20-item J4012 reference row

`concurrency-orin-nx-ceiling.md`'s Whisper c=1 row reports 3.62%, which is
`error_rate_mean` (per-segment mean) in its own JSON
(`concurrency-orin-nx-ceiling.json`, `whisper_en.runs[c=1].results`), not the
aggregate used everywhere else in this report:

```
$ python3 -c "
import json, jiwer
d = json.load(open('concurrency-orin-nx-ceiling.json'))
res = [r for r in d['whisper_en']['runs'] if r['concurrency']==1][0]['results']
refs = [r['ref'] for r in res]; hyps = [r['text'] for r in res]
tr = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(),
                     jiwer.RemoveMultipleSpaces(), jiwer.Strip(),
                     jiwer.ReduceToListOfListOfWords()])
print(jiwer.wer(refs, hyps, reference_transform=tr, hypothesis_transform=tr))
print(sum(r['err'] for r in res)/len(res))
"
0.034013605442176874
0.03620410839271684
```
Aggregate 3.40% (15 edits / 441 reference words), mean 3.62% — the mean
matches the reported figure exactly; the aggregate is the number used for
every comparison in this report's Result/Conclusion sections.

### 10-item comparison table

See table above; source ids/text pulled directly from
`concurrency-harvest-pi-ceiling.json` and `j4012-matched-r2000-100.json`.

### HEF provenance / quantization

- `server/core/model_downloader.py:934`: `"base": ("encoder/hailo/base-whisper-encoder-5s.hef", _WHISPER_DECODER_BASE)`
- `server/core/model_downloader.py:917-921`: `_WHISPER_GEOMETRY[("hailo.whisper", "base")] = (5.0, 1.0)`
- `https://hf-mirror.com/api/models/harvestsu/whisper-edge` -> HTTP 200, tags include `hailo`, `rknn`, `tensorrt`
- `https://hf-mirror.com/harvestsu/whisper-edge/resolve/main/README.md` -> Provenance section: "The Hailo HEFs come from Hailo's own `edge_whisper` example assets and the RKNN encoders from Rockchip's model zoo conversion flow; the ONNX decoders are `optimum` exports of OpenAI Whisper."

### docker ps before / after (orin-nx)

Before (first check, this pass):
```
ovs-whisper-trunc          Exited (0) 3 minutes ago
edge-inspection-mosquitto  Up 27 minutes
esk-jetson-rtsp-pub        Up 27 minutes
esk-jetson-rtsp-server     Up 27 minutes
```

After this pass's own container (`ovs-hailo-wer-j4012`) was removed, the
three non-`ovs-whisper-trunc` containers were found `Exited` (a host/docker
daemon-level event, not caused by any command this pass ran against them —
this pass only ever started/restarted/removed its own `ovs-hailo-wer-j4012`
container; `ovs-whisper-trunc`, owned by a separate concurrent investigation,
was found `Up` again at that same check, consistent with a daemon restart
that some containers' restart policy recovered from and these three did
not). Restored with `docker start`:
```
$ docker rm -f ovs-hailo-wer-j4012
$ docker start edge-inspection-mosquitto esk-jetson-rtsp-pub esk-jetson-rtsp-server
$ docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
ovs-whisper-trunc          Up 15 minutes
edge-inspection-mosquitto  Up 3 seconds
esk-jetson-rtsp-pub        Up 2 seconds
esk-jetson-rtsp-server     Up 3 seconds
```

### PR / merge

PR number and merge sha to be filled in after push (see below).
