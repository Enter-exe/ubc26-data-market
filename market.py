"""Offline, single-buyer demonstration. Run with Python 3.8 or later."""
import argparse
import hashlib
import json
import random
import secrets
from itertools import permutations
from statistics import mean


def digest(data):
    return hashlib.sha256(data).digest()


def leaf(index, row):
    return digest(b"row:" + json.dumps([index, *row], separators=(",", ":")).encode())


def parent(left, right):
    return digest(b"node:" + left + right)


def tree(rows):
    # Both demo listings have 64 rows, a complete binary tree.
    if not rows or len(rows) & (len(rows) - 1):
        raise ValueError("Demo listings require a power-of-two row count")
    levels = [[leaf(i, row) for i, row in enumerate(rows)]]
    while len(levels[-1]) > 1:
        nodes = levels[-1]
        levels.append([parent(nodes[i], nodes[i + 1]) for i in range(0, len(nodes), 2)])
    return levels


def verify(index, row, siblings, root):
    node = leaf(index, row)
    for sibling in siblings:
        node = parent(sibling, node) if index % 2 else parent(node, sibling)
        index //= 2
    return index == 0 and node == root


def freight(seed, scenario, stale=False):
    """One quote for each of 64 lanes. Index is the public lane identifier."""
    geography = random.Random(71)
    noise = random.Random(seed)
    rows = []
    for _ in range(64):
        miles = geography.randint(400, 900)
        lane_adjustment = geography.choice((-550, 550))
        typical = 3 * miles if scenario == "uniform" else 2 * miles + lane_adjustment
        quote = typical + noise.randint(-12, 12) + (1300 if stale else 0)
        rows.append((miles, quote))
    return rows


def quote_error(predictions, holdout):
    return mean(abs(prediction - quote) for prediction, (_, quote) in zip(predictions, holdout))


SCENARIOS = {
    "baseline": "Regional and stale quotes",
    "uniform": "One rate fits every route",
    "stale": "Two stale offers",
    "altered": "Regional sample altered in transit",
}


def evaluate(seed, scenario="baseline", price=40):
    if scenario not in SCENARIOS or not 1 <= price <= 100:
        raise ValueError("Select a listed scenario and a price from 1 to 100")
    sellers = {"Regional freight": freight(17, scenario, stale=scenario == "stale"),
               "Legacy quotes": freight(23, scenario, stale=True)}
    listings = {name: tree(rows) for name, rows in sellers.items()}
    holdout = freight(11, scenario)
    base_predictions = [2 * miles for miles, _ in holdout]
    baseline = quote_error(base_predictions, holdout)
    rng = random.Random(seed)
    ledger, offers = [], []
    balance = 100
    for name, levels in listings.items():
        balance -= 1
        ledger.append(dict(seller=name, purpose="Sample", amount=1, balance=balance))
        samples = []
        for i in rng.sample(range(64), 8):
            miles, quote = sellers[name][i]
            if scenario == "altered" and name == "Regional freight" and not samples:
                quote += 1
            path = [layer[(i >> depth) ^ 1] for depth, layer in enumerate(levels[:-1])]
            valid = verify(i, (miles, quote), path, levels[-1][0])
            samples.append(dict(index=i, miles=miles, quote=quote, verified=valid,
                                proof=[h.hex() for h in path]))
        offers.append(dict(seller=name, root=levels[-1][0].hex(), samples=samples,
                           projected_error=None, value=None, decision="Proof failed"))

    # A buyer can keep both previews. Evaluate each rate model and each
    # seller's route lookups, including using one for the other’s missing lanes.
    verified = [o for o in offers if all(row["verified"] for row in o["samples"])]
    rates = [2]
    for offer in verified:
        sample = offer["samples"]
        rates.append(sum(r["quote"] for r in sample) / sum(r["miles"] for r in sample))
        offer["projected_error"] = mean(abs(r["quote"] - holdout[r["index"]][1]) for r in sample)
    best_error = baseline
    best_strategy = "Existing rate of 2 per mile"
    for rate in rates:
        for count in range(len(verified) + 1):
            for order in permutations(verified, count):
                predictions = [rate * miles for miles, _ in holdout]
                for offer in order:
                    for row in offer["samples"]:
                        predictions[row["index"]] = row["quote"]
                measured = quote_error(predictions, holdout)
                if measured < best_error:
                    best_error = measured
                    sources = ", ".join(o["seller"] for o in order)
                    best_strategy = f"Rate {rate:.3f} per mile" + (f" with route quotes from {sources}" if sources else "")

    for offer in verified:
        # Each committed listing covers every lane once. Sample error estimates
        # full lookup error, with one independent benchmark quote per lane.
        offer["value"] = max(0, best_error - offer["projected_error"]) / 10
        offer["decision"] = "Pass"
    winner, realized_error = None, None
    if verified:
        best = max(verified, key=lambda offer: offer["value"])
        if best["value"] > price and price <= balance:
            winner = best["seller"]
            delivery = sellers[winner]
            if tree(delivery)[-1][0].hex() != best["root"]:
                raise ValueError("Delivery commitment mismatch")
            best["decision"] = "Buy"
            balance -= price
            ledger.append(dict(seller=winner, purpose="Full dataset · 64 rows", amount=price, balance=balance))
            realized_error = quote_error([quote for _, quote in delivery], holdout)
    return dict(version=2, settlement="simulated", seed=str(seed), scenario=scenario,
                price=price, baseline=baseline, retained_error=best_error, retained_strategy=best_strategy,
                delivered_error=realized_error, offers=offers, ledger=ledger, winner=winner, balance=balance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--price", type=int, choices=range(1, 101), metavar="1–100", default=40)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    receipt = evaluate(secrets.randbits(64) if args.seed is None else args.seed, args.scenario, args.price)
    if args.json:
        print(json.dumps(receipt, indent=2))
        return
    print(f"Seed {receipt['seed']} | baseline error {receipt['baseline']:.2f} | price {args.price}")
    print(f"Keeping paid samples: error {receipt['retained_error']:.2f} · {receipt['retained_strategy']}")
    for offer in receipt["offers"]:
        print(f"\n{offer['seller']} | {offer['root']}")
        print("Sample rows:", [s["index"] for s in offer["samples"]])
        if offer["projected_error"] is not None:
            print(f"Projected full lookup error {offer['projected_error']:.2f} | additional value {offer['value']:.2f}")
        print(offer["decision"].upper())
    if receipt["delivered_error"] is not None:
        print(f"Measured full delivery error {receipt['delivered_error']:.2f}")
    for item in receipt["ledger"]:
        print(f"{item['purpose']} · {item['seller']} · paid {item['amount']} · balance {item['balance']}")
    print(f"Final wallet: {receipt['balance']} demo credits.")


if __name__ == "__main__":
    main()
