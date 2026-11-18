"""Offline, single-buyer demonstration. Run with Python 3.8 or later."""
import argparse
import hashlib
import json
import random
import secrets
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


def freight(seed, count, rate):
    rng = random.Random(seed)
    miles = [rng.randint(100, 900) for _ in range(count)]
    return [(m, round(m * rate) + rng.randint(-12, 12)) for m in miles]


def error(rate, holdout):
    return mean(abs(miles * rate - quote) for miles, quote in holdout)


SCENARIOS = {
    "baseline": "Regional and stale quotes",
    "stale": "Two stale offers",
    "altered": "Regional sample altered in transit",
}


def evaluate(seed, scenario="baseline", price=40):
    if scenario not in SCENARIOS or not 1 <= price <= 100:
        raise ValueError("Select a listed scenario and a price from 1 to 100")
    sellers = {"Regional freight": freight(17, 64, 1 if scenario == "stale" else 3),
               "Legacy quotes": freight(23, 64, 1)}
    listings = {name: tree(rows) for name, rows in sellers.items()}
    holdout = freight(71, 32, 3)
    baseline = error(2, holdout)
    rng = random.Random(seed)
    ledger, offers, eligible = [], [], []
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
        offer = dict(seller=name, root=levels[-1][0].hex(), samples=samples,
                     error=None, value=None, decision="Proof failed")
        offers.append(offer)
        if all(row["verified"] for row in samples):
            rate = sum(row["quote"] for row in samples) / sum(row["miles"] for row in samples)
            measured = error(rate, holdout)
            value = max(0, baseline - measured) / 10
            offer.update(error=measured, value=value, decision="Pass")
            if value > price:
                eligible.append(offer)
    winner = None
    if eligible and price <= balance:
        best = max(eligible, key=lambda offer: offer["value"])
        winner = best["seller"]
        if tree(sellers[winner])[-1][0].hex() != best["root"]:
            raise ValueError("Delivery commitment mismatch")
        best["decision"] = "Buy"
        balance -= price
        ledger.append(dict(seller=winner, purpose="Full dataset · 64 rows", amount=price, balance=balance))
    return dict(version=1, settlement="simulated", seed=str(seed), scenario=scenario,
                price=price, baseline=baseline, offers=offers, ledger=ledger, winner=winner, balance=balance)


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
    for offer in receipt["offers"]:
        print(f"\n{offer['seller']} | {offer['root']}")
        print("Sample rows:", [s["index"] for s in offer["samples"]])
        if offer["error"] is not None:
            print(f"Held-out error {offer['error']:.2f} | utility {offer['value']:.2f}")
        print(offer["decision"].upper())
    for item in receipt["ledger"]:
        print(f"{item['purpose']} · {item['seller']} · paid {item['amount']} · balance {item['balance']}")
    print(f"Final wallet: {receipt['balance']} demo credits.")


if __name__ == "__main__":
    main()
