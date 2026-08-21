# KXGOLD15M order-book sample

A 39-window sample of **full L2 order-book capture** for Kalshi's 15-minute gold
markets (`KXGOLD15M`), recorded live in August 2026. 2.2 M raw events, 32 MB.

Kalshi has no historical order-book API — candles bottom out at 1 minute and
depth is live-only — so this data only exists because it was captured going
forward off the WebSocket feed.

Every window ships with its market definition and its settlement, so a tape is
self-describing: you know the strike the book was quoting against and how it
resolved. 21 of the 39 windows settled `yes`, 18 `no`.

## What's in here

| Path | What |
|---|---|
| `events/<window>/<date>.ndjson.gz` | lossless raw event log — every message, in receive order |
| `snapshots/KXGOLD15M-26AUG102130-30/` | the same window resampled to a 100 ms grid, Parquet (format demo) |
| `metadata/<event>.json` | the REST market record — strike, rules, settlement — verbatim |
| `MARKETS.csv` | strike and settlement of all 39 windows, flat |
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

## Market definition and settlement

`metadata/<event_ticker>.json` is the unmodified `GET /events/{ticker}` response,
wrapped with the fetch time, request URL and HTTP status. The market objects sit
in the top-level `markets` array, exactly as the default endpoint returns them.
64 fields per window. The ones that make a tape gradeable:

| field | meaning |
|---|---|
| `floor_strike` | the target price the book is quoting against |
| `strike_type` | `greater_or_equal` — yes pays if the settlement value clears the strike |
| `custom_strike.round_digits` | strike rounding, 2 decimals |
| `open_time` / `close_time` | the window, exchange clock. `close_time` is the last tradeable instant |
| `expiration_value` | the observed gold price at settlement |
| `result` | `yes` or `no` |
| `settlement_value_dollars` | `1.0000` or `0.0000` — what a contract paid |
| `settlement_ts` | when Kalshi finalized it, a few seconds after close |
| `status` | `finalized` for every window here |
| `rules_primary` / `rules_secondary` | the resolution text, including the Pyth candlestick convention |
| `price_level_structure` + `price_ranges` | tick grid: `linear_cent`, 0.0000–1.0000 step 0.0100 |
| `settlement_sources` | Pyth Gold, with the feed URL |

`MARKETS.csv` flattens the 14 columns you sort and filter on so you can pick
windows without opening 39 JSON documents. Every value is comma-free, so no CSV
parser is needed:

```bash
awk -F, 'NR>1 && $8=="no"' MARKETS.csv | wc -l    # 18 windows resolved no
```

Grading a strategy is then: fold the event log to your decision instant, take a
side, and settle against `result` at `settlement_value_dollars`.

## Quick start

```bash
python3 read_sample.py events/KXGOLD15M-26AUG102130-30/*.ndjson.gz
```

Prints the market's strike and settlement, the book state at the midpoint of the
window, and a per-second event histogram. Parquet reading needs `pyarrow`; the
NDJSON path is stdlib-only.

## Caveats

1. Capture gap on 08-08 and 08-09 (host restart) — no sample windows fall in it.
2. Some overnight windows are nearly empty; gold is thinnest around 04:00 ET.
   Two such windows are included deliberately.
3. The 100 ms sampler is a derived layer. If the two layers ever disagree, the
   event log is the source of truth.
4. **The metadata is a single post-settlement fetch, not a time series.** Every
   record was pulled after its market finalized, so fields that mutate while a
   market is open — `status`, close-time extensions, tick and limit changes —
   survive only in final form. The strike, the rules, the window bounds and the
   settlement are exact. The quote and volume fields (`yes_bid_dollars`,
   `last_price_dollars`, `volume_fp`, `open_interest_fp` and their siblings) are
   end-of-life values, *not* the state of the market during the window — for
   that, fold the event log. Read the metadata as the market's definition and
   outcome, not as a snapshot of its REST surface mid-window.
