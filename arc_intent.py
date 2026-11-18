"""Prepare unsigned wallet parameters for Arc Testnet. Both commands run offline.

python3 arc_intent.py listing --seller 0xADDRESS --root ROOT_HEX
python3 arc_intent.py request --buyer 0xADDRESS --seller 0xADDRESS --listing-tx 0xHASH

Select the expected chain in the wallet before signing. The wallet estimates gas.
"""
import argparse
import json

from arc_draw import CHAIN_ID, FEE_BASE_UNITS, LISTING_TAG, REQUEST_TAG, hex_data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("listing", help="Prepare a zero-value seller self-anchor")
    listing.add_argument("--seller", required=True)
    listing.add_argument("--root", required=True, help="32-byte Merkle root, optionally prefixed with 0x")
    request = commands.add_parser("request", help="Prepare the buyer's fixed native sample fee")
    request.add_argument("--seller", required=True)
    request.add_argument("--buyer", required=True)
    request.add_argument("--listing-tx", required=True)
    args = parser.parse_args()
    try:
        seller = hex_data(args.seller, 20, "seller")
        if args.command == "listing":
            root = args.root if args.root.startswith("0x") else "0x" + args.root
            payload = LISTING_TAG.hex() + hex_data(root, 32, "listing root")[2:]
            sender, value = seller, 0
        else:
            sender = hex_data(args.buyer, 20, "buyer")
            if sender == seller:
                raise ValueError("Seller and buyer must have distinct addresses")
            payload = REQUEST_TAG.hex() + hex_data(args.listing_tx, 32, "listing transaction")[2:]
            value = FEE_BASE_UNITS
    except ValueError as exc:
        parser.error(str(exc))

    tx = {"from": sender, "to": seller, "value": hex(value), "data": "0x" + payload}
    print(json.dumps(dict(chain_id=CHAIN_ID, chain_id_hex=hex(CHAIN_ID),
                          method="eth_sendTransaction", params=[tx]), indent=2))


if __name__ == "__main__":
    main()
