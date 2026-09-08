#!/usr/bin/env python3
"""Optional resource sampler to run alongside bench.py on the DEVICE (not the
Mac driving the benchmark). Samples CPU/mem every --interval seconds and,
when available, NPU/GPU load, writing one CSV row per sample.

Accelerator probes (best-effort; missing ones are left blank, not guessed):
  - RK3576/RK3588 NPU: /sys/kernel/debug/rknpu/load (needs root/CAP_SYS_ADMIN)
  - Jetson GPU/NPU:    tegrastats --interval <ms> (parsed if present)
  - Hailo-8 NPU:       `hailortcli monitor` is interactive; not sampled here —
    fall back to /sys/devices/.../hailo0 utilization if the driver exposes one
    on this build (unverified — leave blank if absent rather than guess).

Usage (on the device, while bench.py runs from elsewhere):
    python3 resource_sampler.py --out /tmp/res.csv --interval 1 --duration 120
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import time
from pathlib import Path


def read_top_cpu_mem() -> tuple[float | None, float | None]:
    """Return (cpu_pct_used, mem_pct_used) via /proc, portable across ARM boards."""
    try:
        with open("/proc/stat") as f:
            line1 = f.readline()
        time.sleep(0.15)
        with open("/proc/stat") as f:
            line2 = f.readline()
        def parts(line):
            vals = [int(x) for x in line.split()[1:]]
            idle = vals[3] + vals[4]
            total = sum(vals)
            return idle, total
        idle1, total1 = parts(line1)
        idle2, total2 = parts(line2)
        dt, di = total2 - total1, idle2 - idle1
        cpu_pct = 100.0 * (dt - di) / dt if dt > 0 else None
    except Exception:
        cpu_pct = None
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":")
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        mem_pct = 100.0 * (total - avail) / total if total > 0 else None
    except Exception:
        mem_pct = None
    return cpu_pct, mem_pct


def read_rknpu_load() -> str | None:
    path = Path("/sys/kernel/debug/rknpu/load")
    if not path.exists():
        return None
    try:
        return path.read_text().strip()
    except PermissionError:
        return "permission_denied"
    except Exception:
        return None


def read_tegrastats_once() -> str | None:
    try:
        out = subprocess.run(["tegrastats", "--interval", "200", "--count", "1"],
                              capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or None
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--duration", type=float, default=120.0)
    p.add_argument("--accel", choices=["none", "rknpu", "tegrastats"], default="none")
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["t", "cpu_pct", "mem_pct", "accel_raw"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        t0 = time.time()
        while time.time() - t0 < args.duration:
            cpu_pct, mem_pct = read_top_cpu_mem()
            accel_raw = None
            if args.accel == "rknpu":
                accel_raw = read_rknpu_load()
            elif args.accel == "tegrastats":
                accel_raw = read_tegrastats_once()
            w.writerow({"t": round(time.time() - t0, 2), "cpu_pct": cpu_pct, "mem_pct": mem_pct, "accel_raw": accel_raw})
            f.flush()
            time.sleep(max(0.0, args.interval))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
