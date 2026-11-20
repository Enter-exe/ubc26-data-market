"""Build the offline showdown, optionally refreshing both demos' BTC replays."""
import argparse
import hashlib
import json
from pathlib import Path

from arc_draw import BTC_DATASET, CHAIN_ID, FEE_BASE_UNITS, draw_indices, hex_data
from arc_purchase import FULL_PRICE_BASE_UNITS
from btc_buyer import listing_start, rehearse, usdc
from btc_value import price_preview
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


def build_paid_showdown(snapshot, benchmark, receipt):
    """Replay a verified Arc draw or the buyer decision made from that draw."""
    recorded = "draw" in receipt
    draw = receipt["draw"] if recorded else receipt
    source = draw.get("quicknode_streams")
    if (draw.get("dataset") != BTC_DATASET or draw.get("chain_id") != CHAIN_ID or
            draw.get("fee_base_units") != str(FEE_BASE_UNITS)):
        raise ValueError("Expected a verified BTC preview receipt on Arc Testnet")
    if "quicknode_streams" in draw and (not isinstance(source, dict) or source.get("network") != "arc-testnet" or
            source.get("dataset") != "block" or not isinstance(source.get("stream_id"), str) or not source["stream_id"].strip()):
        raise ValueError("Invalid QuickNode Streams provenance")
    request_height = draw["request_block"]
    if type(request_height) is not int or request_height < 0 or draw["draw_block"] != request_height + 2:
        raise ValueError("Expected the finalized draw block two blocks after the preview payment")
    for key in ("listing_tx", "request_tx", "draw_block_hash"):
        hex_data(draw[key], 32, key)
    indices = draw_indices(bytes.fromhex(draw["root"]), bytes.fromhex(draw["request_tx"][2:]),
                           bytes.fromhex(draw["draw_block_hash"][2:]))
    if indices != draw["indices"]:
        raise ValueError("Receipt indices differ from the reproduced BTC draw")
    delivery = package(snapshot, draw)
    check(delivery, draw)
    rows = [sample["row"] for sample in delivery["samples"]]
    price, gas, budget, reward = FULL_PRICE_BASE_UNITS, usdc("0.001"), usdc("0.20"), usdc("0.20")
    if recorded:
        offer = receipt["offer"]
        if (receipt.get("mode") != "arc-testnet" or any(offer[key] != draw[key] for key in
                ("chain_id", "dataset", "root", "seller", "listing_tx")) or offer["price_base_units"] != str(price)):
            raise ValueError("Buyer decision offer differs from the sampled BTC listing")
        hex_data(offer["offer_tx"], 32, "offer_tx")
        recorded_value = receipt["valuation"]
    if recorded and "available_base_units" in recorded_value:
        available = int(recorded_value["available_base_units"])
        if not 0 <= available < price:
            raise ValueError("Recorded funds cover the BTC offer")
        valuation = dict(decision="pass", reason="Full price exceeds remaining funds",
                         price_base_units=str(price), available_base_units=str(available))
    else:
        if recorded:
            gas, budget, reward = (int(recorded_value[key]) for key in
                                   ("gas_base_units", "budget_base_units", "reward_base_units_per_bp"))
        valuation = price_preview(rows, benchmark, price, gas, budget, reward, listing_start=listing_start(draw, rows))
    if recorded and valuation != recorded_value:
        raise ValueError("Recorded buyer valuation differs from the verified preview and benchmark")
    public_draw = {key: draw[key] for key in ("listing_tx", "request_tx", "request_block", "draw_block",
                                              "draw_block_hash", "fee_base_units", "dataset", "root")}
    if source:
        public_draw["quicknode_streams"] = {key: source[key] for key in ("network", "dataset", "stream_id")}
    if recorded:
        public_draw["offer_tx"] = offer["offer_tx"]
    run = dict(mode="recorded" if recorded else "modeled", root=draw["root"], indices=indices, valuation=valuation)
    return {"btc_draw": public_draw, "runs": {"0.20": run}, "samples": delivery["samples"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showdown", action="store_true", help="rebuild the paid showdown replay if present, otherwise use demo.html")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--btc-draw", type=Path, help="build only showdown.html from a verified BTC Arc draw or buyer decision")
    args = parser.parse_args()
    if args.showdown and (args.snapshot or args.benchmark or args.btc_draw):
        parser.error("--showdown uses the checked-in replay; omit other arguments")
    if not args.showdown and not (args.snapshot and args.benchmark):
        parser.error("supply --showdown or both --snapshot and --benchmark")
    root = Path(__file__).resolve().parent
    classic = root / "demo.html"
    prefix, marker, body = classic.read_text(encoding="utf-8").partition('<script type="application/json" id="recorded-runs">')
    replay, close, suffix = body.partition('</script>')
    if not marker or not close:
        parser.error("Missing demo replay block")
    output = root / "showdown.html"
    if args.showdown and output.is_file():
        _, existing_marker, body = output.read_text(encoding="utf-8").partition(marker)
        existing_replay, close_tag, _ = body.partition(close)
        if existing_marker and close_tag and "btc_draw" in json.loads(existing_replay):
            replay = existing_replay
    if not args.showdown:
        snapshot = json.loads(args.snapshot.read_text())
        benchmark = json.loads(args.benchmark.read_text())
        if args.btc_draw:
            try:
                data = build_paid_showdown(snapshot, benchmark, json.loads(args.btc_draw.read_text()))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                parser.error(f"Invalid BTC replay: {exc}")
        else:
            data = build(snapshot, benchmark)
        replay = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    evidence = marker + replay + close
    template = (root / "showdown-ui.html").read_text(encoding="utf-8")
    if any(template.count(tag) != 1 for tag in ("<!--SHOWDOWN_DATA-->", "<!--SHOWDOWN_CORE-->")):
        parser.error("Expected one showdown replay marker and one core script marker")
    core = (root / "showdown-core.js").read_text(encoding="utf-8")
    showdown = template.replace("<!--SHOWDOWN_DATA-->", evidence).replace("<!--SHOWDOWN_CORE-->", f"<script>{core}</script>")
    output.write_text(showdown, encoding="utf-8")
    if not (args.showdown or args.btc_draw):
        classic.write_text(prefix + evidence + suffix, encoding="utf-8")
