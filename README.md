# KXGOLD15M order-book sample

A 39-window sample of **full L2 order-book capture** for Kalshi's 15-minute gold
markets (`KXGOLD15M`), recorded live in August 2026. 2.2 M raw events, 32 MB.

Kalshi has no historical order-book API — candles bottom out at 1 minute and
depth is live-only — so this data only exists because it was captured going
forward off the WebSocket feed.

## What's in here

| Path | What |
|---|---|
| `events/<window>/<date>.ndjson.gz` | lossless raw event log — every message, in receive order |
| `snapshots/KXGOLD15M-26AUG102130-30/` | the same window resampled to a 100 ms grid, Parquet (format demo) |
| `MANIFEST.csv` | every file with byte size and event count |
| `read_sample.py` | reconstruct the book at any instant; no deps for the NDJSON path |

Windows are Kalshi market tickers: `KXGOLD15M-26AUG102130-30` = the 15-minute
market closing 2026-08-10 21:30 ET.

**Selection** (deterministic, see `make_sample.py`):

1. A contiguous 6-hour block — 2026-08-10 18:00 → 23:45 ET, 24 consecutive
   windows, including the three densest tapes in the whole capture
   (~198 k events in one 15-minute market).
2. One window every 8 hours on 08-05, 08-06, 08-07, 08-11, 08-12 — 15 windows
   covering Asia, London and NY sessions.

## Event log format

One gzipped NDJSON file per market per UTC day. One line per raw WebSocket
message:

```json
{"recv_ms":1786410915579,
 "event":{"type":"orderbook_delta","sid":1,"seq":2399869,
  "msg":{"market_ticker":"KXGOLD15M-26AUG102130-30","price_dollars":"0.4800",
         "delta_fp":"-40.00","side":"no","ts_ms":1786410915566}}}
```

1. `recv_ms` — local receive time, Unix ms. `msg.ts_ms` — exchange time. Replay
   on the exchange clock, not the receive clock.
2. `orderbook_snapshot` messages carry `yes_dollars_fp` / `no_dollars_fp` level
   arrays (a key is omitted when that side is empty); `orderbook_delta` carries
   one `price_dollars` / `delta_fp` / `side`; `trade` carries the fill.
3. `seq` is per-subscription and monotonic — a gap means a resubscribe happened
   and the next snapshot re-bases the book.
4. Prices are dollar strings at 0.0001 granularity. Sizes are fixed-point with
   two decimals (Kalshi supports fractional contracts).
5. Kalshi quotes two price axes, `yes` and `no`, rather than bid/ask. A resting
   no at 0.48 is economically a yes bid at 0.52.

Replay = re-feed lines in order, folding deltas into the book.

## Snapshot format

`snapshots/<ticker>/<date>/<hour>/*.parquet` — the entire book on a fixed 100 ms
grid, long format, one row per level per tick:

| column | type | meaning |
|---|---|---|
| `ts_ms` | int64 | sample time, Unix ms, grid-aligned |
| `ticker` | string | market ticker |
| `side` | string | `yes` or `no` |
| `price_1e4` | int32 | price × 10 000 |
| `size_1e2` | int64 | resting size × 100 |

Scaled integers so sums stay exact. Long rather than 198 fixed columns because
Kalshi books are thin — most levels are empty.

## Quick start

```bash
python3 read_sample.py events/KXGOLD15M-26AUG102130-30/*.ndjson.gz
```

Prints the book state at the midpoint of the window and a per-second event
histogram. Parquet reading needs `pyarrow`; the NDJSON path is stdlib-only.

## Caveats

1. Capture gap on 08-08 and 08-09 (host restart) — no sample windows fall in it.
2. Some overnight windows are nearly empty; gold is thinnest around 04:00 ET.
   Two such windows are included deliberately.
3. The 100 ms sampler is a derived layer. If the two layers ever disagree, the
   event log is the source of truth.
