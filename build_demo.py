"""Build the offline showdown, optionally refreshing both demos' BTC replays."""
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
    chicago_path = Path(__file__).with_name("examples") / "arc-testnet-draw.json"
    return {"runs": runs, "samples": preview["samples"], "chicago": json.loads(chicago_path.read_text())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showdown", action="store_true", help="rebuild from the replay in demo.html")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--benchmark", type=Path)
    args = parser.parse_args()
    if args.showdown and (args.snapshot or args.benchmark):
        parser.error("--showdown uses the checked-in replay; omit --snapshot and --benchmark")
    if not args.showdown and not (args.snapshot and args.benchmark):
        parser.error("supply --showdown or both --snapshot and --benchmark")
    root = Path(__file__).resolve().parent
    classic = root / "demo.html"
    prefix, marker, body = classic.read_text(encoding="utf-8").partition('<script type="application/json" id="recorded-runs">')
    replay, close, suffix = body.partition('</script>')
    if not marker or not close:
        parser.error("Missing demo replay block")
    if not args.showdown:
        data = build(json.loads(args.snapshot.read_text()), json.loads(args.benchmark.read_text()))
        replay = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    evidence = marker + replay + close
    template = (root / "showdown-ui.html").read_text(encoding="utf-8")
    if any(template.count(tag) != 1 for tag in ("<!--SHOWDOWN_DATA-->", "<!--SHOWDOWN_CORE-->")):
        parser.error("Expected one showdown replay marker and one core script marker")
    core = (root / "showdown-core.js").read_text(encoding="utf-8")
    showdown = template.replace("<!--SHOWDOWN_DATA-->", evidence).replace("<!--SHOWDOWN_CORE-->", f"<script>{core}</script>")
    (root / "showdown.html").write_text(showdown, encoding="utf-8")
    if not args.showdown:
        classic.write_text(prefix + evidence + suffix, encoding="utf-8")
