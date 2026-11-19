"""Refresh the two embedded buyer replays in the offline judge demo."""
import argparse
import hashlib
import json
from pathlib import Path

from btc_buyer import rehearse, usdc
from sample_delivery import check, package


def build(snapshot, benchmark):
    runs = {}
    for reward in ("0.10", "0.20"):
        runs[reward] = rehearse(snapshot, benchmark, 26, usdc("0.20"), usdc(reward), usdc("0.001"))
    run = runs["0.10"]
    draw = dict(dataset="btc-usd-hourly", indices=run["indices"], root=run["root"],
                request_tx="0x" + hashlib.sha256(b"offline BTC preview 26").hexdigest())
    preview = package(snapshot, draw)
    check(preview, draw)
    return {"runs": runs, "samples": preview["samples"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    args = parser.parse_args()
    data = build(json.loads(args.snapshot.read_text()), json.loads(args.benchmark.read_text()))
    page = Path(__file__).with_name("demo.html")
    prefix, marker, body = page.read_text().partition('<script type="application/json" id="recorded-runs">')
    _, close, suffix = body.partition('</script>')
    if not marker or not close:
        parser.error("Missing demo replay block")
    page.write_text(prefix + marker + json.dumps(data, separators=(",", ":")).replace("<", "\\u003c") + close + suffix)
