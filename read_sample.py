#!/usr/bin/env python3
"""Fold a KXGOLD15M event log into an order book and describe it.

Usage: python3 read_sample.py events/KXGOLD15M-26AUG102130-30/*.ndjson.gz
Stdlib only.
"""

import collections
import gzip
import json
import sys
from decimal import Decimal


def load(paths):
    for p in paths:
        with gzip.open(p, "rt") as fh:
            for line in fh:
                yield json.loads(line)


def fold(records, until_ms=None):
    """Return {side: {price: size}} after applying every message up to until_ms."""
    book = {"yes": collections.defaultdict(Decimal), "no": collections.defaultdict(Decimal)}
    applied = 0
    for rec in records:
        ev = rec["event"]
        msg = ev.get("msg", {})
        ts = msg.get("ts_ms", rec["recv_ms"])
        if until_ms is not None and ts > until_ms:
            break
        if ev["type"] == "orderbook_snapshot":
            book = {"yes": collections.defaultdict(Decimal), "no": collections.defaultdict(Decimal)}
            for side, key in (("yes", "yes_dollars_fp"), ("no", "no_dollars_fp")):
                for price, size in msg.get(key, []):
                    book[side][Decimal(price)] = Decimal(size)
        elif ev["type"] == "orderbook_delta":
            side = msg["side"]
            price = Decimal(msg["price_dollars"])
            book[side][price] += Decimal(msg["delta_fp"])
            if book[side][price] <= 0:
                book[side].pop(price, None)
        applied += 1
    return book, applied


def main(paths):
    records = list(load(paths))
    if not records:
        sys.exit("no events")

    stamps = [r["event"].get("msg", {}).get("ts_ms", r["recv_ms"]) for r in records]
    lo, hi = min(stamps), max(stamps)
    mid = lo + (hi - lo) // 2

    types = collections.Counter(r["event"]["type"] for r in records)
    print(f"{len(records):,} events over {(hi - lo) / 1000:.0f}s")
    for t, n in types.most_common():
        print(f"  {t:22s} {n:>8,}")

    book, applied = fold(records, until_ms=mid)
    print(f"\nbook at t+{(mid - lo) / 1000:.0f}s ({applied:,} events applied)")
    for side in ("yes", "no"):
        levels = sorted(book[side].items(), reverse=True)[:8]
        depth = sum(book[side].values())
        print(f"  {side}: {len(book[side])} levels, {depth} contracts resting")
        for price, size in levels:
            print(f"    {price}  {size:>10}")

    per_sec = collections.Counter(t // 1000 for t in stamps)
    busiest = per_sec.most_common(1)[0]
    print(f"\npeak second: {busiest[1]:,} events")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
