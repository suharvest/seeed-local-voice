#!/usr/bin/env python3
"""Build a zh (AISHELL-1) + en (LibriSpeech test-clean) labeled subset for
asr_bench, alongside the existing bench/perf/corpus/manifest.json (which stays
the primary "5 pairs x short/long" set from docs/perf-test-runbook.md).

Sources (fact-checked 2026-09-09 against hf-mirror.com):
  - zh: https://hf-mirror.com/datasets/AISHELL/AISHELL-1 (Apache-2.0).
    IMPORTANT: this HF mirror of AISHELL-1 only contains speakers
    S0002-S0101 (the corpus's TRAIN range in the official Kaldi split,
    S0002-S0723). The official TEST range (S0764-S0916) is NOT present in
    this re-upload. This script pulls a labeled zh subset from speaker
    S0002 for CER measurement; it is not the canonical AISHELL-1 test set.
    If a full test-split AISHELL-1 mirror shows up later, point --aishell-speaker
    at one of S0764..S0916 and re-run.
  - en: https://hf-mirror.com/datasets/openslr/librispeech_asr
    (all/test.clean/0000.parquet), CC BY 4.0, genuine test-clean split.

Usage:
    export HF_ENDPOINT=https://hf-mirror.com   # required — see CLAUDE.md mirror policy
    uv run download_public_corpus.py --limit 20
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AISHELL_REPO = "AISHELL/AISHELL-1"
LIBRISPEECH_REPO = "openslr/librispeech_asr"


def hf_url(repo: str, path: str) -> str:
    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    return f"{endpoint}/datasets/{repo}/resolve/main/{path}"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sL", "--max-time", "300", "-o", str(dest), url], check=True)


def build_zh(limit: int, speaker: str, out_dir: Path, manifest_files: list[dict]) -> None:
    tar_path = ROOT / "_dl" / f"{speaker}.tar.gz"
    if not tar_path.exists():
        download(hf_url(AISHELL_REPO, f"data_aishell/wav/{speaker}.tar.gz"), tar_path)
    transcript_path = ROOT / "_dl" / "aishell_transcript_v0.8.txt"
    if not transcript_path.exists():
        download(hf_url(AISHELL_REPO, "data_aishell/transcript/aishell_transcript_v0.8.txt"), transcript_path)

    transcripts = {}
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            transcripts[parts[0]] = parts[1].replace(" ", "")

    zh_dir = out_dir / "zh"
    zh_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        members = sorted((m for m in tar.getmembers() if m.name.endswith(".wav")), key=lambda m: m.name)
        for m in members:
            if n >= limit:
                break
            utt_id = Path(m.name).stem
            ref = transcripts.get(utt_id)
            if not ref:
                continue
            data = tar.extractfile(m).read()
            dest = zh_dir / f"{utt_id}.wav"
            dest.write_bytes(data)
            import soundfile as sf
            duration_s = round(sf.info(str(dest)).duration, 2)
            manifest_files.append({
                "id": f"zh_pub_{n:02d}",
                "filename": f"zh/{utt_id}.wav",
                "lang": "zh",
                "category": "pub",
                "duration_s": duration_s,
                "transcript": ref,
                "source": f"AISHELL-1 speaker {speaker} (train-range mirror, see module docstring)",
            })
            n += 1
    print(f"zh: wrote {n} files from speaker {speaker}")


def build_en(limit: int, out_dir: Path, manifest_files: list[dict]) -> None:
    parquet_path = ROOT / "_dl" / "librispeech_test_clean_0000.parquet"
    if not parquet_path.exists():
        download(hf_url(LIBRISPEECH_REPO, "all/test.clean/0000.parquet"), parquet_path)

    import pandas as pd
    df = pd.read_parquet(parquet_path, columns=["audio", "text"])
    en_dir = out_dir / "en"
    en_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for _, row in df.iterrows():
        if n >= limit:
            break
        audio = row["audio"]
        raw_bytes = audio["bytes"] if isinstance(audio, dict) else audio
        import soundfile as sf
        data, sr = sf.read(io.BytesIO(raw_bytes), dtype="int16")
        dest = en_dir / f"ls_test_clean_{n:03d}.wav"
        sf.write(str(dest), data, sr, subtype="PCM_16")
        duration_s = round(len(data) / sr, 2)
        manifest_files.append({
            "id": f"en_pub_{n:02d}",
            "filename": f"en/{dest.name}",
            "lang": "en",
            "category": "pub",
            "duration_s": duration_s,
            "transcript": str(row["text"]),
            "source": "LibriSpeech test-clean (openslr/librispeech_asr, HF mirror)",
        })
        n += 1
    print(f"en: wrote {n} files from LibriSpeech test-clean")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20, help="per-language item count")
    p.add_argument("--aishell-speaker", default="S0002")
    p.add_argument("--out", default=str(ROOT))
    args = p.parse_args()

    if "HF_ENDPOINT" not in os.environ:
        raise SystemExit("HF_ENDPOINT is not set. export HF_ENDPOINT=https://hf-mirror.com first (see CLAUDE.md mirror policy).")

    out_dir = Path(args.out)
    manifest_files: list[dict] = []
    build_zh(args.limit, args.aishell_speaker, out_dir, manifest_files)
    build_en(args.limit, out_dir, manifest_files)

    manifest = {
        "version": 1,
        "description": (
            "Public labeled subset for asr_bench CER/WER: zh from AISHELL-1 "
            "(Apache-2.0, train-range speaker per HF mirror availability — see "
            "module docstring), en from LibriSpeech test-clean (CC BY 4.0)."
        ),
        "audio_spec": {"sample_rate": 16000, "channels": 1, "bit_depth": 16, "format": "wav"},
        "categories": {"pub": "public labeled corpus, single utterance"},
        "files": manifest_files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'manifest.json'} with {len(manifest_files)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
