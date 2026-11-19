"""Price a verified BTC training-data preview and prepare its Arc payment if it qualifies."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from arc_draw import ArcPending, RPC_URL, draw_indices, quantity, rpc_client, verify_draw
from arc_intent import purchase_wallet_request
from arc_purchase import FULL_PRICE_BASE_UNITS, verify_offer, verify_purchase
from btc_value import measured_outcome, price_preview
from buyer_sample import fetch_preview, fetch_purchase
from sample_delivery import btc_row_hour, check, check_full_rows, package


def usdc(text):
    """Parse a nonnegative test-USDC amount exactly in native 18-decimal units."""
    if not re.fullmatch(r"[0-9]{1,25}(\.[0-9]{1,18})?", text):
        raise ValueError("Use a nonnegative test-USDC amount with up to 18 decimal places")
    whole, _, fraction = text.partition(".")
    return int(whole) * 10**18 + int(fraction.ljust(18, "0"))


def paid_sample(rpc, url, token, seller, buyer, listing, request):
    draw = verify_draw(rpc, seller, buyer, listing, request)
    if draw.get("dataset") != "btc-usd-hourly":
        raise ValueError("This buyer requires a BTC-USD hourly listing")
    delivery = fetch_preview(url, token, draw)
    return draw, [s["row"] for s in delivery["samples"]]


def listing_start(draw, sample):
    # Verified BTC positions and hourly timestamps fix the first hour even when index zero was not drawn.
    return btc_row_hour(sample[0]) - draw["indices"][0] * 3600


def arc_decision(rpc, url, token, seller, buyer, listing, request, offer, benchmark, budget, reward):
    draw, sample = paid_sample(rpc, url, token, seller, buyer, listing, request)
    terms = verify_offer(rpc, seller, listing, offer)
    if terms.get("dataset") != draw["dataset"] or terms["root"] != draw["root"]:
        raise ValueError("Full purchase offer differs from the sampled listing")
    envelope = purchase_wallet_request(seller, buyer, offer)
    tx = envelope["params"][0]
    balance = quantity(rpc("eth_getBalance", [tx["from"], "pending"]), "buyer balance")
    price = int(terms["price_base_units"])
    receipt = {"mode": "arc-testnet", "draw": draw, "offer": terms}
    if min(balance, budget) < price:
        receipt["valuation"] = {"decision": "pass", "reason": "Full price exceeds remaining funds",
                                "price_base_units": str(price), "available_base_units": str(min(balance, budget))}
        return receipt
    gas_price = quantity(rpc("eth_gasPrice", []), "gas price")
    gas_limit = quantity(rpc("eth_estimateGas", [tx]), "estimated gas")
    valuation = price_preview(sample, benchmark, price, gas_limit * gas_price, min(balance, budget), reward,
                              listing_start=listing_start(draw, sample))
    receipt["valuation"] = valuation
    if valuation["decision"] == "buy":
        tx.update(gas=hex(gas_limit), gasPrice=hex(gas_price), chainId=hex(draw["chain_id"]))
        receipt["wallet_request"] = envelope
    return receipt


def rehearse(snapshot, benchmark, seed, budget, reward, gas):
    root = snapshot["manifest"]["root"]
    request = hashlib.sha256(("offline BTC preview " + str(seed)).encode()).digest()
    block = hashlib.sha256(b"offline BTC draw block").digest()
    draw = dict(dataset="btc-usd-hourly", root=root, request_tx="0x" + request.hex(),
                indices=draw_indices(bytes.fromhex(root), request, block))
    preview = package(snapshot, draw)
    check(preview, draw)
    sample = [s["row"] for s in preview["samples"]]
    valuation = price_preview(sample, benchmark, FULL_PRICE_BASE_UNITS, gas, budget, reward,
                              listing_start=listing_start(draw, sample))
    receipt = dict(mode="simulated", seed=seed, root=root, indices=draw["indices"], valuation=valuation)
    if valuation["decision"] == "buy":
        check_full_rows(snapshot["rows"], root, draw["dataset"])
        receipt["outcome"] = measured_outcome(sample, snapshot["rows"], benchmark)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    demo = commands.add_parser("rehearse", help="Replay locally with simulated payments")
    demo.add_argument("--snapshot", required=True, type=Path)
    demo.add_argument("--seed", type=int, default=26)
    demo.add_argument("--purchase-gas", type=usdc, default="0.001", help="Simulated test USDC")
    decide = commands.add_parser("decide", help="Price a paid Arc preview before authorizing a full purchase")
    assess = commands.add_parser("assess", help="Verify full payment and measure the delivered rows on holdout")
    assess.add_argument("--purchase-tx", required=True)
    for cmd in (decide, assess):
        for key in ("seller", "buyer", "listing-tx", "request-tx", "offer-tx"):
            cmd.add_argument("--" + key, required=True)
        cmd.add_argument("--rpc-url", default=RPC_URL)
        cmd.add_argument("--seller-api", default="http://127.0.0.1:8766")
    for cmd in (demo, decide, assess):
        cmd.add_argument("--benchmark", required=True, type=Path)
    for cmd in (demo, decide):
        cmd.add_argument("--remaining-budget", required=True, type=usdc, help="Test USDC remaining after preview")
        cmd.add_argument("--reward-per-bp", required=True, type=usdc, help="Buyer's test USDC per bp of lower MAE")
    args = parser.parse_args()
    try:
        benchmark = json.loads(args.benchmark.read_text())
        if args.action == "rehearse":
            result = rehearse(json.loads(args.snapshot.read_text()), benchmark, args.seed,
                              args.remaining_budget, args.reward_per_bp, args.purchase_gas)
        else:
            token = os.environ.get("UBC26_BUYER_TOKEN")
            if not token:
                parser.error("Set UBC26_BUYER_TOKEN for this seller")
            rpc = rpc_client(args.rpc_url)
            context = (rpc, args.seller_api, token, args.seller, args.buyer, args.listing_tx, args.request_tx)
            if args.action == "decide":
                result = arc_decision(*context, args.offer_tx, benchmark, args.remaining_budget, args.reward_per_bp)
            else:
                draw, sample = paid_sample(*context)
                purchase = verify_purchase(rpc, args.seller, args.buyer, args.listing_tx, args.offer_tx, args.purchase_tx)
                if purchase["root"] != draw["root"] or purchase.get("dataset") != draw["dataset"]:
                    raise ValueError("Full purchase differs from the sampled listing")
                full = fetch_purchase(args.seller_api, token, purchase)
                result = dict(mode="arc-testnet", draw=draw, purchase=purchase,
                              outcome=measured_outcome(sample, full["rows"], benchmark))
        print(json.dumps(result, indent=2, allow_nan=False))
    except ArcPending as exc:
        parser.exit(75, f"{exc}. Repeat this read with the same transaction hashes.\n")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        parser.exit(1, f"BTC buyer failed: {exc}\n")


if __name__ == "__main__":
    main()
