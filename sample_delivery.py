"""Produce or check an eight-row sample against an independently verified Arc draw."""
import argparse
import json
from pathlib import Path

from chicago_snapshot import ROW_COUNT
from market import tree, verify


def check_full_rows(rows, expected_root):
    if not isinstance(rows, list) or len(rows) != ROW_COUNT:
        raise ValueError(f"Expected {ROW_COUNT} purchased Chicago taxi rows")
    last_id = ""
    for row in rows:
        if (not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str) or
                row[0] <= last_id or any(type(n) is not int or n <= 0 for n in row[1:])):
            raise ValueError("Expected ordered unique trip IDs with positive integer miles and fares in hundredths")
        last_id = row[0]
    if tree(rows)[-1][0].hex() != expected_root:
        raise ValueError("Purchased rows differ from the anchored listing")


def positions(draw):
    indices = draw["indices"]
    if (not isinstance(indices, list) or len(indices) != 8 or
            any(type(i) is not int or not 0 <= i < 64 for i in indices) or len(set(indices)) != 8):
        raise ValueError("Expected eight distinct indices in the 64-row listing")
    return indices


def snapshot_tree(snapshot, root):
    rows = snapshot["rows"]
    if not isinstance(rows, list) or len(rows) != 64:
        raise ValueError("Snapshot must contain 64 rows")
    levels = tree(rows)
    if levels[-1][0].hex() != root or snapshot["manifest"]["root"] != root:
        raise ValueError("Snapshot differs from the anchored listing")
    return levels


def package(snapshot, draw):
    levels = snapshot_tree(snapshot, draw["root"])
    rows = snapshot["rows"]
    samples = []
    for i in positions(draw):
        path = [layer[(i >> depth) ^ 1].hex() for depth, layer in enumerate(levels[:-1])]
        samples.append(dict(index=i, row=rows[i], proof=path))
    return dict(version=1, request_tx=draw["request_tx"], samples=samples)


def check(delivery, draw):
    if delivery["version"] != 1 or delivery["request_tx"] != draw["request_tx"]:
        raise ValueError("Delivery does not match this request")
    samples = delivery["samples"]
    if [s["index"] for s in samples] != positions(draw):
        raise ValueError("Received indices differ from the chain-selected draw")
    root = bytes.fromhex(draw["root"])
    for s in samples:
        path = [bytes.fromhex(h) for h in s["proof"]]
        if (type(s["index"]) is not int or len(path) != 6 or any(len(h) != 32 for h in path)
                or not verify(s["index"], s["row"], path, root)):
            raise ValueError(f"Invalid proof at index {s['index']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pack", "verify"))
    parser.add_argument("input", type=Path, help="Seller snapshot or received delivery JSON")
    parser.add_argument("draw", type=Path, help="Output from your own arc_draw.py verification")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text())
        draw = json.loads(args.draw.read_text())
        if args.action == "pack":
            print(json.dumps(package(data, draw)))
        else:
            check(data, draw)
            print("Verified eight selected rows against the listing root.")
    except (OSError, KeyError, IndexError, ValueError, TypeError) as exc:
        parser.exit(1, f"Sample processing failed: {exc}\n")


if __name__ == "__main__":
    main()
