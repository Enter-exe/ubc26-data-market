"""Build seller training rows and buyer benchmark windows from BTC-USD hourly candles."""
import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market import tree


HOUR = 3600
CALIBRATION_START = 1704067200  # 2024-01-01 00:00 UTC
LISTING_START = CALIBRATION_START + 193 * HOUR
HOLDOUT_START = LISTING_START + 65 * HOUR
SOURCE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"


def candle_rows(candles, start_hour, count):
    if not isinstance(candles, list):
        raise ValueError("Expected a list of Coinbase candles")
    ranges = {}
    for candle in candles:
        if not isinstance(candle, list) or len(candle) != 6 or type(candle[0]) is not int:
            raise ValueError("Expected a timestamped OHLCV candle")
        timestamp, low, high, opening, closing, _ = candle
        if not start_hour - HOUR <= timestamp < start_hour + count * HOUR:
            continue  # Coinbase can include buckets before the requested window.
        if timestamp % HOUR or timestamp in ranges:
            raise ValueError(f"Duplicate or off-hour BTC candle at {timestamp}")
        if any(type(n) not in (int, Decimal) or not Decimal(n).is_finite()
               for n in (low, high, opening, closing)):
            raise ValueError("Expected finite numeric OHLC prices")
        if low <= 0 or not (low <= opening <= high and low <= closing <= high):
            raise ValueError("Inconsistent OHLC prices")
        ranges[timestamp] = 1 + round(Decimal(10000) * (high - low) / opening)
    if len(ranges) != count + 1:
        raise ValueError(f"Missing BTC candles: expected {count + 1}, received {len(ranges)}")
    return [[f"BTC-USD:1h:{t}", ranges[t - HOUR], ranges[t]]
            for t in range(start_hour, start_hour + count * HOUR, HOUR)]


def source_url(start_hour, count):
    if type(start_hour) is not int or start_hour % HOUR or type(count) is not int or not 1 <= count <= 299:
        raise ValueError("Use a UTC hour boundary and request between 1 and 299 rows")

    def utc(timestamp):
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return SOURCE + "?" + urlencode({
        "start": utc(start_hour - HOUR), "end": utc(start_hour + count * HOUR - 1), "granularity": HOUR,
    })


def load_window(start_hour, count):
    req = Request(source_url(start_hour, count), headers={"User-Agent": "UBC26/1.0"})
    with urlopen(req, timeout=30) as source:
        return candle_rows(json.load(source, parse_float=Decimal), start_hour, count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the seller's 64 training rows and manifest")
    parser.add_argument("--benchmark-output", type=Path, help="Write the buyer's calibration and holdout rows")
    args = parser.parse_args()
    if not args.output and not args.benchmark_output:
        parser.error("Specify --output or --benchmark-output")
    if args.output and args.benchmark_output and args.output.resolve() == args.benchmark_output.resolve():
        parser.error("Seller and buyer output paths must be distinct")
    try:
        if args.output:
            rows = load_window(LISTING_START, 64)
            root = tree(rows)[-1][0].hex()
            manifest = dict(version=1, source_url=source_url(LISTING_START, 64), row_count=64, root=root,
                            columns=["btc_usd_hour", "previous_range_bps_plus_one", "range_bps_plus_one"])
            args.output.write_text(json.dumps(dict(manifest=manifest, rows=rows), indent=2) + "\n", encoding="utf-8")
            print(root)
        if args.benchmark_output:
            benchmark = dict(calibration=load_window(CALIBRATION_START, 192), holdout=load_window(HOLDOUT_START, 64))
            args.benchmark_output.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"BTC data import failed: {exc}\n")


if __name__ == "__main__":
    main()
