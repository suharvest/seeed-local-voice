#!/usr/bin/env python3
"""Diagnostic: dump EVERY frame /asr/stream sends, with timestamps relative to EOS."""
import argparse, asyncio, json, sys, time, wave
from pathlib import Path
import websockets

def load_pcm16(p):
    with wave.open(str(p), "rb") as w:
        return w.readframes(w.getnframes())

async def one(url, item, seg_dir, chunk_bytes, realtime, vad_none):
    ws_url = f"{url.rstrip('/')}/asr/stream?language=auto&sample_rate=16000"
    if vad_none:
        ws_url += "&vad=none"
    pcm = await asyncio.to_thread(load_pcm16, seg_dir / item["filename"])
    frames = []
    async with websockets.connect(ws_url, max_size=None, open_timeout=15) as ws:
        bpms = 16000 * 2 / 1000.0
        t_start = time.perf_counter()
        for s in range(0, len(pcm), chunk_bytes):
            c = pcm[s:s+chunk_bytes]
            t0 = time.perf_counter()
            await ws.send(c)
            if realtime:
                ms = len(c) / bpms
                el = (time.perf_counter() - t0) * 1000
                await asyncio.sleep(max(0.0, (ms - el) / 1000))
        # 10 ms drain, exactly like bench.py
        pre = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.01)
            except (asyncio.TimeoutError, TimeoutError):
                break
            m = json.loads(raw)
            frames.append({"phase": "pre_eos_drain", "t_rel_eos_ms": (time.perf_counter()-t_start)*1000, "msg": m})
            if m.get("is_final") and m.get("text"):
                pre.append(m["text"])
        eos = time.perf_counter()
        await ws.send(b"")
        deadline = eos + 40
        first_final_after_eos = None
        while time.perf_counter() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.perf_counter()))
            except (asyncio.TimeoutError, TimeoutError):
                break
            except websockets.ConnectionClosed:
                frames.append({"phase":"post_eos","t_rel_eos_ms":(time.perf_counter()-eos)*1000,"msg":"<closed>"})
                break
            m = json.loads(raw)
            frames.append({"phase": "post_eos", "t_rel_eos_ms": (time.perf_counter()-eos)*1000, "msg": m})
            if m.get("is_final") and first_final_after_eos is None:
                first_final_after_eos = m.get("text", "")
    joiner = "" if item["lang"] == "zh" else " "
    bench_text = joiner.join([t for t in (*pre, first_final_after_eos or "") if t])
    all_finals = [f["msg"]["text"] for f in frames
                  if isinstance(f["msg"], dict) and f["msg"].get("is_final") and f["msg"].get("text")]
    return {"id": item["id"], "duration_s": item.get("duration_s"),
            "ref": item.get("eval_transcript") or item["transcript"],
            "pre_eos_finals": len(pre),
            "bench_text": bench_text,
            "all_finals_text": joiner.join(all_finals),
            "frames": frames}

async def run(url, items, seg_dir, c, chunk_bytes, realtime, vad_none):
    q = asyncio.Queue()
    for it in items: q.put_nowait(it)
    out = []
    async def worker():
        while True:
            try: it = q.get_nowait()
            except asyncio.QueueEmpty: return
            try: out.append(await one(url, it, seg_dir, chunk_bytes, realtime, vad_none))
            except Exception as e: out.append({"id": it["id"], "error": repr(e)})
    await asyncio.gather(*(worker() for _ in range(c)))
    return out

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True); p.add_argument("--segments", required=True)
    p.add_argument("--lang", default="en"); p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--limit", type=int, default=None); p.add_argument("--chunk-bytes", type=int, default=4096)
    p.add_argument("--vad-none", action="store_true"); p.add_argument("--out", required=True)
    a = p.parse_args()
    seg = Path(a.segments)
    man = json.loads((seg / "manifest.json").read_text())
    items = [f for f in man["files"] if f["lang"] == a.lang]
    if a.limit: items = items[:a.limit]
    res = asyncio.run(run(a.url, items, seg, a.concurrency, a.chunk_bytes, True, a.vad_none))
    Path(a.out).write_text(json.dumps({"concurrency": a.concurrency, "vad_none": a.vad_none, "results": res}, indent=1))
    print("wrote", a.out, len(res))

main()
