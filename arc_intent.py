"""Prepare unsigned wallet parameters for Arc Testnet. Pass --expected-root to check the seller commitment before preparing payment.

python3 arc_intent.py listing --seller 0xADDRESS --root ROOT_HEX
python3 arc_intent.py request --buyer 0xADDRESS --seller 0xADDRESS --listing-tx 0xHASH --expected-root ROOT_HEX

Select the expected chain in the wallet before signing. The wallet estimates gas.
"""
import argparse
import json

from arc_draw import (BTC_DATASET, BTC_LISTING_TAG, CHAIN_ID, FEE_BASE_UNITS, LISTING_TAG,
                      REQUEST_TAG, RPC_URL, hex_data, rpc_client, verify_listing_details)
from arc_purchase import FULL_PRICE_BASE_UNITS, OFFER_TAG, PURCHASE_TAG, verify_offer


def root_hex(value):
    return hex_data(value if value.startswith("0x") else "0x" + value, 32, "listing root")[2:]


def wallet_request(sender, recipient, value, payload):
    tx = {"from": sender, "to": recipient, "value": hex(value), "data": "0x" + payload}
    return dict(chain_id=CHAIN_ID, chain_id_hex=hex(CHAIN_ID), method="eth_sendTransaction", params=[tx])


def purchase_wallet_request(seller, buyer, offer_tx):
    """Encode the full payment after verifying the seller offer."""
    seller = hex_data(seller, 20, "seller")
    buyer = hex_data(buyer, 20, "buyer")
    offer_tx = hex_data(offer_tx, 32, "offer transaction")
    if seller == buyer:
        raise ValueError("Seller and buyer must have distinct addresses")
    return wallet_request(buyer, seller, FULL_PRICE_BASE_UNITS, PURCHASE_TAG.hex() + offer_tx[2:])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("listing", help="Prepare a zero-value seller self-anchor")
    listing.add_argument("--seller", required=True)
    listing.add_argument("--root", required=True, help="32-byte Merkle root, optionally prefixed with 0x")
    listing.add_argument("--dataset", choices=("chicago-taxi", BTC_DATASET), default="chicago-taxi")
    request = commands.add_parser("request", help="Prepare the buyer's fixed native sample fee")
    request.add_argument("--seller", required=True)
    request.add_argument("--buyer", required=True)
    request.add_argument("--listing-tx", required=True)
    request.add_argument("--expected-root", help="Check the finalized seller anchor against this advertised root")
    request.add_argument("--dataset", choices=("chicago-taxi", BTC_DATASET),
                         help="Require this onchain listing schema before preparing payment")
    request.add_argument("--rpc-url", help="Arc testnet RPC for the listing check")
    offer = commands.add_parser("offer", help="Offer the full listing at 0.10 native test USDC")
    offer.add_argument("--seller", required=True)
    offer.add_argument("--listing-tx", required=True)
    purchase = commands.add_parser("purchase", help="Check the finalized full offer and prepare its payment")
    for arg in ("--seller", "--buyer", "--listing-tx", "--offer-tx", "--expected-root"):
        purchase.add_argument(arg, required=True)
    purchase.add_argument("--rpc-url", default=RPC_URL)
    args = parser.parse_args()
    try:
        seller = hex_data(args.seller, 20, "seller")
        if args.command == "listing":
            tag = BTC_LISTING_TAG if args.dataset == BTC_DATASET else LISTING_TAG
            payload = tag.hex() + root_hex(args.root)
            sender, value = seller, 0
        elif args.command == "offer":
            listing_tx = hex_data(args.listing_tx, 32, "listing transaction")
            payload = OFFER_TAG.hex() + listing_tx[2:]
            sender, value = seller, 0
        else:
            sender = hex_data(args.buyer, 20, "buyer")
            if sender == seller:
                raise ValueError("Seller and buyer must have distinct addresses")
            listing_tx = hex_data(args.listing_tx, 32, "listing transaction")
            if args.command == "purchase":
                expected = root_hex(args.expected_root)
                offer_tx = hex_data(args.offer_tx, 32, "offer transaction")
                terms = verify_offer(rpc_client(args.rpc_url), seller, listing_tx, offer_tx)
                if terms["root"] != expected:
                    raise ValueError("Full offer differs from the expected snapshot")
                print(json.dumps(purchase_wallet_request(seller, sender, offer_tx), indent=2))
                return
            else:
                if (args.rpc_url is not None or args.dataset is not None) and args.expected_root is None:
                    raise ValueError("Supply --expected-root when using --dataset or --rpc-url")
                if args.expected_root is not None:
                    expected = root_hex(args.expected_root)
                    _, _, root, dataset = verify_listing_details(rpc_client(args.rpc_url or RPC_URL), seller, listing_tx)
                    if args.dataset and args.dataset != (dataset or "chicago-taxi"):
                        raise ValueError("Finalized listing dataset differs from the expected schema")
                    if root != expected:
                        raise ValueError("Finalized listing root differs from the advertised snapshot")
                payload = REQUEST_TAG.hex() + listing_tx[2:]
                value = FEE_BASE_UNITS
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    print(json.dumps(wallet_request(sender, seller, value, payload), indent=2))


if __name__ == "__main__":
    main()
