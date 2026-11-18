"""Commit a reproducible 64-trip Chicago taxi demo listing."""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from market import tree


ROW_COUNT = 64
SOURCE_URL = "https://data.cityofchicago.org/resource/ajtu-isnz.json?" + urlencode({
    "$select": "trip_id,trip_miles,fare",
    "$where": "trip_start_timestamp >= '2024-01-02T12:00:00' "
              "AND trip_start_timestamp < '2024-01-02T13:00:00' "
              "AND trip_miles > 0 AND fare > 0",
    "$order": "trip_id ASC",
    "$limit": ROW_COUNT,
})


def hundredths(record, field):
    try:
        value = Decimal(str(record.get(field)))
    except InvalidOperation:
        raise ValueError(f"Invalid {field}") from None
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be finite and positive")
    numerator, denominator = value.as_integer_ratio()
    units, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError(f"{field} must be representable in hundredths")
    return units


def build_snapshot(records):
    if not isinstance(records, list) or len(records) != ROW_COUNT:
        raise ValueError(f"Expected {ROW_COUNT} records from the source query")
    rows = []
    for record in records:
        trip_id = record.get("trip_id") if isinstance(record, dict) else None
        if not isinstance(trip_id, str) or not trip_id:
            raise ValueError("Expected a nonempty trip_id")
        rows.append([trip_id, hundredths(record, "trip_miles"), hundredths(record, "fare")])
    rows.sort(key=lambda row: row[0])
    if len({row[0] for row in rows}) != ROW_COUNT:
        raise ValueError("Duplicate trip_id in source query")
    manifest = {
        "version": 1,
        "source_url": SOURCE_URL,
        "columns": ["trip_id", "miles_hundredths", "fare_cents"],
        "row_count": len(rows),
        "root": tree(rows)[-1][0].hex(),
    }
    return {"manifest": manifest, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Replay a saved raw response from the source query")
    parser.add_argument("--output", required=True, type=Path, help="Write the manifest and canonical rows here")
    args = parser.parse_args()
    try:
        with (args.input.open("rb") if args.input else urlopen(SOURCE_URL, timeout=30)) as source:
            snapshot = build_snapshot(json.load(source, parse_float=Decimal))
        args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Snapshot failed: {exc}\n")
    print(snapshot["manifest"]["root"])


if __name__ == "__main__":
    main()
