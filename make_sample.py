#!/usr/bin/env python3
"""Build the KXGOLD15M public sample from the local capture store.

Selection is deterministic: a contiguous evening block from the busiest day,
plus one window every 8 hours across the rest of the capture range. Re-running
overwrites events/, snapshots/, metadata/, MANIFEST.csv and MARKETS.csv in place.

--metadata-only rebuilds just metadata/ and MARKETS.csv, leaving the tapes alone.
"""

import csv
import gzip
import json
import shutil
import sys
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

# MARKETS.csv — the strike and settlement of every window, flat, so the corpus
# can be filtered without parsing 39 JSON documents. Full fidelity stays in
# metadata/; these are the columns you actually grade a strategy against. Every
# value is comma-free, so awk and cut work without a CSV parser.
MARKET_COLUMNS = [
    ("window", None),
    ("event_ticker", "event"),
    ("open_time", "market"),
    ("close_time", "market"),
    ("strike_type", "market"),
    ("floor_strike", "market"),
    ("status", "market"),
    ("result", "market"),
    ("expiration_value", "market"),
    ("settlement_value_dollars", "market"),
    ("settlement_ts", "market"),
    ("price_level_structure", "market"),
    ("volume_fp", "market"),
    ("open_interest_fp", "market"),
]


def windows():
    out = []
    for h in BLOCK_HOURS:
        for m in (0, 15, 30, 45):
            out.append(f"{SERIES}-{BLOCK_DAY}{h:02d}{m:02d}-{m:02d}")
    for day in SPREAD_DAYS:
        for h in SPREAD_HOURS:
            out.append(f"{SERIES}-{day}{h:02d}00-00")
    return sorted(set(out))


def event_ticker(window):
    """KXGOLD15M-26AUG102130-30 -> KXGOLD15M-26AUG102130 (the parent event)."""
    return window.rsplit("-", 1)[0]


def write_metadata(wins):
    """Copy the REST event record for each window and index strikes/settlements.

    Returns manifest rows for the copied files.
    """
    meta_dst = DST / "metadata"
    if meta_dst.exists():
        shutil.rmtree(meta_dst)
    meta_dst.mkdir(parents=True)

    rows, market_rows = [], []
    for w in wins:
        src = SRC / "metadata" / SERIES / f"{event_ticker(w)}.json"
        if not src.is_file():
            print(f"skip (no metadata): {w}")
            continue
        doc = json.loads(src.read_text())
        event = doc["response"]["event"]
        market = next((m for m in event.get("markets", []) if m["ticker"] == w), None)
        if market is None:
            print(f"skip (window not in event record): {w}")
            continue

        out = meta_dst / f"{event_ticker(w)}.json"
        shutil.copy2(src, out)
        rows.append(
            {
                "window": w,
                "file": f"metadata/{out.name}",
                "bytes_gz": out.stat().st_size,
                "events": "",
            }
        )

        row = {}
        for col, source in MARKET_COLUMNS:
            if source is None:
                row[col] = w
            elif source == "event":
                row[col] = event.get(col.replace("event_title", "title"), "")
            else:
                row[col] = market.get(col, "")
        market_rows.append(row)
        print(f"{w}  strike {row['floor_strike']}  -> {row['result']}")

    with open(DST / "MARKETS.csv", "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=[c for c, _ in MARKET_COLUMNS])
        wtr.writeheader()
        wtr.writerows(market_rows)

    return rows


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

    rows.extend(write_metadata(windows()))
    total += sum(r["bytes_gz"] for r in rows[-39:] if r["file"].startswith("metadata/"))

    with open(DST / "MANIFEST.csv", "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["window", "file", "bytes_gz", "events"])
        wtr.writeheader()
        wtr.writerows(rows)

    print(f"\n{len(rows)} files, {total/1e6:.1f} MB total -> {DST}")


if __name__ == "__main__":
    if "--metadata-only" in sys.argv:
        meta_rows = write_metadata(windows())
        kept = [
            r
            for r in csv.DictReader(open(DST / "MANIFEST.csv"))
            if not r["file"].startswith("metadata/")
        ]
        with open(DST / "MANIFEST.csv", "w", newline="") as fh:
            wtr = csv.DictWriter(fh, fieldnames=["window", "file", "bytes_gz", "events"])
            wtr.writeheader()
            wtr.writerows(kept + meta_rows)
        print(f"\n{len(meta_rows)} metadata files -> {DST}")
    else:
        main()
