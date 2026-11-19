"""Verify a paid Arc Testnet sample request and print its repeatable 8-of-64 draw."""
import argparse
import hashlib
import json
import re
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


CHAIN_ID = 5042002
RPC_URL = "https://rpc.testnet.arc.io"
FEE_BASE_UNITS = 10**16  # 0.01 native test USDC (18 decimals)
LISTING_TAG = b"UBC26:listing:v1:"
REQUEST_TAG = b"UBC26:sample:v1:"
DRAW_TAG = b"UBC26:draw:v1:"


def hex_data(value, size, label):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{%d}" % (2 * size), value):
        raise ValueError(f"Expected {size} bytes of 0x-prefixed hex for {label}")
    return value.lower()


def quantity(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value):
        raise ValueError(f"Invalid RPC quantity for {label}")
    return int(value, 16)


def rpc_client(url):
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("An HTTP or HTTPS RPC endpoint is required")

    def call(method, params):
        body = json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "UBC26/1.0"})
        with urlopen(req, timeout=15) as response:
            message = json.load(response)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != 1:
            raise ValueError(f"Malformed {method} RPC response")
        if "error" in message or "result" not in message:
            raise ValueError(f"{method} failed: {message.get('error', 'missing result')}")
        return message["result"]

    return call


def block_at(rpc, tag):
    block = rpc("eth_getBlockByNumber", [tag, False])
    if not isinstance(block, dict):
        raise ValueError(f"Block {tag} unavailable")
    height = quantity(block.get("number"), "block number")
    if tag != "finalized" and height != int(tag, 16):
        raise ValueError("RPC returned a different block height")
    block_hash = hex_data(block.get("hash"), 32, "block hash")
    return height, block_hash, block.get("transactions")


def checked_transaction(rpc, tx_hash, sender, recipient, value):
    tx = rpc("eth_getTransactionByHash", [tx_hash])
    receipt = rpc("eth_getTransactionReceipt", [tx_hash])
    if not isinstance(tx, dict) or not isinstance(receipt, dict):
        raise ValueError(f"Transaction or receipt unavailable for {tx_hash}")
    if (hex_data(tx.get("hash"), 32, "transaction hash") != tx_hash or
            hex_data(receipt.get("transactionHash"), 32, "receipt transaction hash") != tx_hash or
            quantity(receipt.get("status"), "receipt status") != 1):
        raise ValueError(f"Expected a matching successful receipt for {tx_hash}")
    if (hex_data(tx.get("from"), 20, "sender") != sender or
            hex_data(tx.get("to"), 20, "recipient") != recipient or
            quantity(tx.get("value"), "value") != value or
            quantity(tx.get("type"), "transaction type") not in (0, 1, 2)):
        raise ValueError(f"Incorrect sender, recipient, value or transaction type for {tx_hash}")

    if any(tx.get(field) is None for field in ("blockNumber", "blockHash", "transactionIndex")):
        raise ValueError(f"Transaction {tx_hash} is not yet indexed as mined; retry with the same hash")

    height = quantity(receipt.get("blockNumber"), "receipt block number")
    index = quantity(receipt.get("transactionIndex"), "transaction index")
    tag = hex(height)
    _, canonical_hash, hashes = block_at(rpc, tag)
    if (quantity(tx.get("blockNumber"), "transaction block number") != height or
            quantity(tx.get("transactionIndex"), "transaction index") != index or
            hex_data(tx.get("blockHash"), 32, "transaction block hash") != canonical_hash or
            hex_data(receipt.get("blockHash"), 32, "receipt block hash") != canonical_hash or
            not isinstance(hashes, list) or index >= len(hashes) or
            hex_data(hashes[index], 32, "included transaction hash") != tx_hash):
        raise ValueError(f"Transaction {tx_hash} does not match its canonical block")
    for address in {sender, recipient}:
        if rpc("eth_getCode", [address, tag]) != "0x":
            raise ValueError(f"Expected an account with empty code at block {height}: {address}")
    return (height, index), canonical_hash, tx.get("input"), receipt


def draw_indices(root_bytes, request_hash_bytes, block_hash_bytes):
    """Use the low six SHA-256 bits, discarding duplicates in first-seen order."""
    prefix = DRAW_TAG + root_bytes + request_hash_bytes + block_hash_bytes
    indices = []
    counter = 0
    while len(indices) < 8:
        digest = hashlib.sha256(prefix + counter.to_bytes(4, "big")).digest()
        candidate = digest[-1] % 64
        if candidate not in indices:
            indices.append(candidate)
        counter += 1
    return indices


def verify_listing(rpc, seller, listing_tx):
    """Read a finalized seller commitment before preparing a sample payment."""
    seller = hex_data(seller, 20, "seller")
    listing_tx = hex_data(listing_tx, 32, "listing transaction")
    if quantity(rpc("eth_chainId", []), "chain ID") != CHAIN_ID:
        raise ValueError(f"Expected Arc Testnet chain {CHAIN_ID}")

    listing_pos, listing_hash, anchor, _ = checked_transaction(rpc, listing_tx, seller, seller, 0)
    anchor = hex_data(anchor, len(LISTING_TAG) + 32, "listing calldata")
    if not anchor.startswith("0x" + LISTING_TAG.hex()):
        raise ValueError("Listing calldata has the wrong protocol tag")
    final_height, final_hash, _ = block_at(rpc, "finalized")
    if listing_pos[0] > final_height or (listing_pos[0] == final_height and listing_hash != final_hash):
        raise ValueError("Listing anchor is not finalized on the canonical chain")
    return listing_pos, listing_hash, anchor[-64:]


def verify_draw(rpc, seller, buyer, listing_tx, request_tx):
    """Resolve both transactions with a trusted read-only RPC and return JSON-ready evidence."""
    seller = hex_data(seller, 20, "seller")
    buyer = hex_data(buyer, 20, "buyer")
    listing_tx = hex_data(listing_tx, 32, "listing transaction")
    request_tx = hex_data(request_tx, 32, "request transaction")
    if seller == buyer:
        raise ValueError("Seller and buyer must have distinct addresses")
    listing_pos, listing_hash, root = verify_listing(rpc, seller, listing_tx)
    request_pos, request_hash, payment, receipt = checked_transaction(rpc, request_tx, buyer, seller, FEE_BASE_UNITS)
    payment = hex_data(payment, len(REQUEST_TAG) + 32, "request calldata")
    if payment != "0x" + REQUEST_TAG.hex() + listing_tx[2:]:
        raise ValueError("Sample payment must reference the listing transaction")
    if listing_pos >= request_pos:
        raise ValueError("Listing must precede the sample payment")

    draw_block = request_pos[0] + 2
    final_height, final_hash, _ = block_at(rpc, "finalized")
    if draw_block > final_height:
        raise ValueError(f"Await finalized draw block {draw_block} (currently {final_height})")
    _, draw_hash, _ = block_at(rpc, hex(draw_block))
    if draw_block == final_height and draw_hash != final_hash:
        raise ValueError("Draw block does not match the finalized tip")
    indices = draw_indices(bytes.fromhex(root), bytes.fromhex(request_tx[2:]), bytes.fromhex(draw_hash[2:]))
    gas_used = quantity(receipt.get("gasUsed"), "request gas used")
    gas_price = quantity(receipt.get("effectiveGasPrice"), "request effective gas price")
    network_fee = gas_used * gas_price
    return dict(version=1, chain_id=CHAIN_ID, root=root, indices=indices, seller=seller, buyer=buyer,
                listing_tx=listing_tx, request_tx=request_tx, fee_base_units=str(FEE_BASE_UNITS),
                request_gas_fee_base_units=str(network_fee), buyer_total_base_units=str(FEE_BASE_UNITS + network_fee),
                listing_block=listing_pos[0], listing_block_hash=listing_hash,
                request_block=request_pos[0], request_block_hash=request_hash,
                draw_block=draw_block, draw_block_hash=draw_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default=RPC_URL)
    parser.add_argument("--seller", required=True, help="Expected seller's 0x address")
    parser.add_argument("--buyer", required=True, help="Expected buyer's 0x address")
    parser.add_argument("--listing-tx", required=True, help="Seller's anchor transaction hash")
    parser.add_argument("--request-tx", required=True, help="Buyer's sample fee transaction hash")
    args = parser.parse_args()
    try:
        draw = verify_draw(rpc_client(args.rpc_url), args.seller, args.buyer, args.listing_tx, args.request_tx)
    except (ValueError, URLError, OSError) as exc:
        parser.exit(1, f"Draw verification failed: {exc}\n")
    print(json.dumps(draw, indent=2))


if __name__ == "__main__":
    main()
