#!/usr/bin/env python3
"""Score aggregate/mean/p50 CER or WER for a fixed set of segment ids, pulled
from arbitrary result JSON files. Replicates bench.py's exact normalization
(bench.py:94-118) so numbers are comparable to every other figure in
results/.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import jiwer

CER_TR = jiwer.Compose([
    jiwer.ToLowerCase(),
    jiwer.RemovePunctuation(),
    jiwer.RemoveWhiteSpace(replace_by_space=""),
    jiwer.ReduceToListOfListOfChars(),
])
WER_TR = jiwer.Compose([
    jiwer.ToLowerCase(),
    jiwer.RemovePunctuation(),
    jiwer.RemoveMultipleSpaces(),
    jiwer.Strip(),
    jiwer.ReduceToListOfListOfWords(),
])


def find_run(obj, want_concurrency=None):
    """Walk a results JSON looking for the first dict with a 'runs' list,
    return list of (path, run) for every run found."""
    found = []
    def walk(o, path):
        if isinstance(o, dict):
            if "runs" in o and isinstance(o["runs"], list):
                for r in o["runs"]:
                    found.append((path, r))
            for k, v in o.items():
                walk(v, path + "/" + k)
    walk(obj, "")
    return found


def load_ids_map(json_path, concurrency, root_key=None):
    d = json.loads(Path(json_path).read_text())
    runs = find_run(d)
    cands = [(p, r) for p, r in runs if r.get("concurrency") == concurrency]
    if root_key:
        cands = [(p, r) for p, r in cands if root_key in p]
    if not cands:
        avail = sorted(set(r.get("concurrency") for _, r in runs))
        raise SystemExit(f"no run with concurrency={concurrency} in {json_path} (root_key={root_key}); available={avail}")
    # prefer exact root_key match else first
    _, run = cands[0]
    return {r["id"]: r for r in run["results"]}


def score(id_ref_hyp, mode):
    refs = [x[0] for x in id_ref_hyp]
    hyps = [x[1] for x in id_ref_hyp]
    tr = CER_TR if mode == "cer" else WER_TR
    fn = jiwer.cer if mode == "cer" else jiwer.wer
    agg = fn(refs, hyps, reference_transform=tr, hypothesis_transform=tr)
    per_item = [fn([r], [h], reference_transform=tr, hypothesis_transform=tr) for r, h in id_ref_hyp]
    mean = statistics.mean(per_item)
    p50 = statistics.median(per_item)
    return agg, mean, p50, len(id_ref_hyp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--root-key", default=None)
    ap.add_argument("--ids-file", required=True, help="text file, one id per line, defines the unified subset")
    ap.add_argument("--mode", choices=["cer", "wer"], required=True)
    args = ap.parse_args()

    ids = [l.strip() for l in Path(args.ids_file).read_text().splitlines() if l.strip()]
    id_map = load_ids_map(args.json, args.concurrency, args.root_key)
    missing = [i for i in ids if i not in id_map]
    if missing:
        print(f"WARNING: {len(missing)} ids missing from {args.json}: {missing[:5]}", file=sys.stderr)
    pairs = [(id_map[i]["ref"], id_map[i]["text"]) for i in ids if i in id_map]
    agg, mean, p50, n = score(pairs, args.mode)
    print(json.dumps({
        "json": args.json, "concurrency": args.concurrency, "n": n,
        "aggregate": agg, "mean": mean, "p50": p50,
    }, indent=2))


if __name__ == "__main__":
    main()
