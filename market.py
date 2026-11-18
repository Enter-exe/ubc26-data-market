"""Offline, single-buyer demonstration. Run with Python 3.8 or later."""
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


def main():
    # The seller commits before the buyer chooses indices.
    sellers = {"Regional freight": freight(17, 64, 3), "Legacy quotes": freight(23, 64, 1)}
    listings = {name: tree(rows) for name, rows in sellers.items()}
    holdout = freight(71, 32, 3)
    baseline = error(2, holdout)
    balance, fee, price = 100, 1, 40
    offers = []
    for name, levels in listings.items():
        print(f"{name} | 64 rows | SHA-256 root {levels[-1][0].hex()}")
    print(f"\nBuyer baseline: {baseline:.2f} mean absolute quote error on 32 private jobs.")
    seed = secrets.randbits(64)
    print(f"Buyer draw seed: {seed}. Starting wallet: {balance} demo credits.")
    rng = random.Random(seed)
    for name, levels in listings.items():
        balance -= fee
        root = levels[-1][0]
        indices = rng.sample(range(64), 8)
        sample = []
        for i in indices:
            row = sellers[name][i]
            proof = [layer[(i >> depth) ^ 1] for depth, layer in enumerate(levels[:-1])]
            if not verify(i, row, proof, root):
                raise ValueError(f"Invalid sample from {name} at row {i}")
            sample.append(row)
        rate = sum(quote for _, quote in sample) / sum(miles for miles, _ in sample)
        measured = error(rate, holdout)
        # Illustrative buyer utility: one credit per ten units of error reduction.
        value = max(0, baseline - measured) / 10
        print(f"\n{name}: paid {fee} credit for rows {indices}. All 8 proofs verified.")
        print(f"Held-out error {measured:.2f} | estimated utility {value:.2f} credits | price {price}.")
        if value > price and balance >= price:
            offers.append((value - price, name))
        else:
            print("PASS")
    if offers:
        _, name = max(offers)
        delivery = sellers[name]
        if tree(delivery)[-1][0] != listings[name][-1][0]:
            raise ValueError("Delivery commitment mismatch")
        balance -= price
        print(f"\nBUY {name}: full delivery of {len(delivery)} rows verified for {price} credits.")
    print(f"Final wallet: {balance} demo credits.")


if __name__ == "__main__":
    main()
