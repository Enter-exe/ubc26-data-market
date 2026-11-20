"""Discover a paid sample and reproduce its draw from filtered Arc Testnet Streams deliveries."""
import argparse
import gzip
import json
from pathlib import Path

from arc_draw import ArcPending, RPC_URL, draw_indices, hex_data, quantity, rpc_client, verify_draw


def load_deliveries(paths):
    """Read one filtered JSON delivery per destination file."""
    for path in map(Path, paths):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as source:
            yield json.load(source)


def from_deliveries(deliveries, seller, buyer, listing_tx, rpc):
    seller = hex_data(seller, 20, "expected seller")
    buyer = hex_data(buyer, 20, "expected buyer")
    listing_tx = hex_data(listing_tx, 32, "expected listing")
    stream_id = None
    blocks = {}
    requests = {}
    for delivery in deliveries:
        if (not isinstance(delivery, dict) or delivery.get("network") != "arc-testnet" or
                delivery.get("dataset") != "block" or not isinstance(delivery.get("blocks"), list)):
            raise ValueError("Expected an Arc Testnet block delivery from the Proofdesk stream filter")
        source = delivery.get("stream_id")
        if not isinstance(source, str) or not source.strip() or (stream_id is not None and source != stream_id):
            raise ValueError("Expected deliveries from one QuickNode stream ID")
        stream_id = source
        for block in delivery["blocks"]:
            if not isinstance(block, dict) or not isinstance(block.get("requests"), list):
                raise ValueError("Malformed QuickNode block or request list")
            height = quantity(block.get("number"), "stream block number")
            block_hash = hex_data(block.get("hash"), 32, "stream block hash")
            if height in blocks and blocks[height] != block:
                raise ValueError(f"Conflicting deliveries for stream block {height}")
            blocks[height] = block
            for request in block["requests"]:
                if not isinstance(request, dict):
                    raise ValueError("Malformed QuickNode sample request")
                tx = hex_data(request.get("hash"), 32, "stream payment hash")
                details = (hex_data(request.get("from"), 20, "stream sender"),
                           hex_data(request.get("to"), 20, "stream recipient"),
                           hex_data(request.get("listing_tx"), 32, "stream listing"), height, block_hash)
                if tx in requests and requests[tx] != details:
                    raise ValueError("Conflicting stream records for the same payment")
                requests[tx] = details

    candidates = [(tx, fields[3], fields[4]) for tx, fields in requests.items()
                  if fields[:3] == (buyer, seller, listing_tx)]
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one matching sample payment in the supplied blocks, found {len(candidates)}")
    request_tx, height, request_hash = candidates[0]
    if height + 2 not in blocks:
        raise ValueError(f"Include the stream delivery containing draw block {height + 2}")
    future_hash = hex_data(blocks[height + 2]["hash"], 32, "stream draw block hash")
    draw = verify_draw(rpc, seller, buyer, listing_tx, request_tx)
    if (draw["request_block"] != height or draw["request_block_hash"] != request_hash
            or draw["draw_block"] != height + 2 or draw["draw_block_hash"] != future_hash):
        raise ValueError("Stream blocks differ from the verified Arc payment and draw blocks")
    indices = draw_indices(bytes.fromhex(draw["root"]), bytes.fromhex(request_tx[2:]), bytes.fromhex(future_hash[2:]))
    if indices != draw["indices"]:
        raise ValueError("Streams draw differs from the finalized Arc draw")
    return dict(draw, indices=indices,
                quicknode_streams={"stream_id": stream_id, "network": "arc-testnet", "dataset": "block"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller", required=True)
    parser.add_argument("--buyer", required=True)
    parser.add_argument("--listing-tx", required=True)
    parser.add_argument("--rpc-url", default=RPC_URL)
    parser.add_argument("deliveries", nargs="+", help="Files containing the filter output (.json or .json.gz)")
    args = parser.parse_args()
    try:
        draw = from_deliveries(load_deliveries(args.deliveries), args.seller, args.buyer, args.listing_tx,
                               rpc_client(args.rpc_url))
    except ArcPending as exc:
        parser.exit(75, f"Draw pending: {exc}. Retry with the same deliveries.\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Streams draw failed: {exc}\n")
    print(json.dumps(draw, indent=2))


if __name__ == "__main__":
    main()
