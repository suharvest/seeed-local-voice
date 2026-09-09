#!/usr/bin/env python3
"""Verify the 100 R2000 Hailo Whisper segment ids match a freshly regenerated
LibriSpeech test-clean draw on transcript + duration. Used to build the
matched-100 corpus for results/whisper-hailo-wer-isolation.md."""
import json

target = json.load(open("../results/concurrency-harvest-pi-ceiling.json"))
res = target["whisper_hailo"]["runs"][0]["results"]
target_map = {r["id"]: r for r in res}

en_manifest = json.load(open("en_manifest_400.json"))
en = {f["id"]: f for f in en_manifest}

mismatches = []
matched = []
for id_, r in target_map.items():
    f = en.get(id_)
    if f is None:
        mismatches.append((id_, "MISSING"))
        continue
    if f["transcript"].strip().upper() != r["ref"].strip().upper():
        mismatches.append((id_, "REF_MISMATCH", f["transcript"], r["ref"]))
        continue
    if abs(f["duration_s"] - r["duration_s"]) > 0.05:
        mismatches.append((id_, "DUR_MISMATCH", f["duration_s"], r["duration_s"]))
        continue
    matched.append(id_)

print(f"target count {len(target_map)}")
print(f"matched {len(matched)} mismatches {len(mismatches)}")
for m in mismatches[:10]:
    print(m)
