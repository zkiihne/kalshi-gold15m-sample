#!/usr/bin/env python3
"""Build the KXGOLD15M public sample from the local capture store.

Selection is deterministic: a contiguous evening block from the busiest day,
plus one window every 8 hours across the rest of the capture range. Re-running
overwrites events/, snapshots/ and MANIFEST.csv in place.
"""

import csv
import gzip
import shutil
from pathlib import Path

SRC = Path.home() / "data" / "kalshi-orderbook"
DST = Path(__file__).resolve().parent
SERIES = "KXGOLD15M"

# 1. contiguous block: 2026-08-10 18:00 -> 23:45 ET (24 windows, includes the
#    three densest tapes in the whole capture)
BLOCK_DAY = "26AUG10"
BLOCK_HOURS = range(18, 24)

# 2. spread: one window every 8 hours on every other captured day
SPREAD_DAYS = ["26AUG05", "26AUG06", "26AUG07", "26AUG11", "26AUG12"]
SPREAD_HOURS = [0, 8, 13]

# full parquet snapshots shipped for exactly one window (format demo)
SNAPSHOT_WINDOW = f"{SERIES}-26AUG102130-30"


def windows():
    out = []
    for h in BLOCK_HOURS:
        for m in (0, 15, 30, 45):
            out.append(f"{SERIES}-{BLOCK_DAY}{h:02d}{m:02d}-{m:02d}")
    for day in SPREAD_DAYS:
        for h in SPREAD_HOURS:
            out.append(f"{SERIES}-{day}{h:02d}00-00")
    return sorted(set(out))


def main():
    events_dst = DST / "events"
    snaps_dst = DST / "snapshots"
    for d in (events_dst, snaps_dst):
        if d.exists():
            shutil.rmtree(d)

    rows, total = [], 0
    for w in windows():
        src_dir = SRC / "events" / w
        if not src_dir.is_dir():
            print(f"skip (not captured): {w}")
            continue
        for f in sorted(src_dir.glob("*.ndjson.gz")):
            out_dir = events_dst / w
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out_dir / f.name)
            size = f.stat().st_size
            with gzip.open(f, "rt") as fh:
                lines = sum(1 for _ in fh)
            total += size
            rows.append(
                {
                    "window": w,
                    "file": f"events/{w}/{f.name}",
                    "bytes_gz": size,
                    "events": lines,
                }
            )
            print(f"{w}  {size/1e6:.2f} MB  {lines:,} events")

    src_snap = SRC / "snapshots" / SNAPSHOT_WINDOW
    if src_snap.is_dir():
        shutil.copytree(src_snap, snaps_dst / SNAPSHOT_WINDOW)
        for f in sorted((snaps_dst / SNAPSHOT_WINDOW).rglob("*.parquet")):
            total += f.stat().st_size
            rows.append(
                {
                    "window": SNAPSHOT_WINDOW,
                    "file": str(f.relative_to(DST)),
                    "bytes_gz": f.stat().st_size,
                    "events": "",
                }
            )

    with open(DST / "MANIFEST.csv", "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["window", "file", "bytes_gz", "events"])
        wtr.writeheader()
        wtr.writerows(rows)

    print(f"\n{len(rows)} files, {total/1e6:.1f} MB total -> {DST}")


if __name__ == "__main__":
    main()
