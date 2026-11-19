"""Retrieve a paid preview or full purchase and verify it against an independent Arc read."""
import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from arc_draw import ArcPending, RPC_URL, rpc_client, verify_draw
from arc_purchase import verify_purchase
from sample_delivery import check, check_full_rows


class KeepBuyerTokenAtSeller(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_delivery(seller_url, token, path):
    url = urlsplit(seller_url)
    local = url.scheme == "http" and url.hostname in ("127.0.0.1", "::1")
    if (not (local or url.scheme == "https") or not url.hostname or url.username or
            url.password or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("Use the seller HTTPS origin or a loopback HTTP origin")
    req = Request(seller_url.rstrip("/") + path,
                  headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with build_opener(KeepBuyerTokenAtSeller()).open(req, timeout=45) as response:
        status = response.status
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError("Seller response exceeds 64 KiB")
    delivery = json.loads(data)
    if status == 202 and isinstance(delivery, dict) and delivery.get("status") == "pending":
        raise ArcPending("Seller is waiting for Arc confirmation")
    if status != 200:
        raise ValueError(f"Unexpected seller delivery response (HTTP {status})")
    return delivery


def fetch_preview(seller_url, token, draw):
    delivery = fetch_delivery(seller_url, token, "/sample/" + draw["request_tx"])
    check(delivery, draw)
    return delivery


def fetch_purchase(seller_url, token, purchase):
    delivery = fetch_delivery(seller_url, token, "/purchase/" + purchase["purchase_tx"])
    rows = delivery["rows"]
    check_full_rows(rows, purchase["root"], purchase.get("dataset"))
    return {"rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-api", default="http://127.0.0.1:8766")
    parser.add_argument("--rpc-url", default=RPC_URL)
    for arg in ("--seller", "--buyer", "--listing-tx"):
        parser.add_argument(arg, required=True)
    payment = parser.add_mutually_exclusive_group(required=True)
    payment.add_argument("--request-tx", help="Sample payment transaction")
    payment.add_argument("--purchase-tx", help="Full purchase transaction")
    parser.add_argument("--offer-tx", help="Seller offer for the full purchase")
    args = parser.parse_args()
    if (args.purchase_tx is None) != (args.offer_tx is None):
        parser.error("Use --offer-tx and --purchase-tx together")
    token = os.environ.get("UBC26_BUYER_TOKEN")
    if not token:
        parser.error("Set UBC26_BUYER_TOKEN for this seller")
    try:
        rpc = rpc_client(args.rpc_url)
        if args.purchase_tx is not None:
            purchase = verify_purchase(rpc, args.seller, args.buyer, args.listing_tx, args.offer_tx, args.purchase_tx)
            receipt = {"purchase": purchase, "delivery": fetch_purchase(args.seller_api, token, purchase)}
        else:
            draw = verify_draw(rpc, args.seller, args.buyer, args.listing_tx, args.request_tx)
            receipt = {"draw": draw, "delivery": fetch_preview(args.seller_api, token, draw)}
    except ArcPending as exc:
        parser.exit(75, f"{exc}. Repeat this read with the same transaction hash.\n")
    except HTTPError as exc:
        parser.exit(1, f"Request failed with HTTP status {exc.code}\n")
    except (OSError, ValueError, IndexError, TypeError, KeyError) as exc:
        parser.exit(1, f"Delivery could not be verified: {exc}\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
