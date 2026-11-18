"""Retrieve a paid preview and check it against the buyer's independent Arc read."""
import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from arc_draw import RPC_URL, rpc_client, verify_draw
from sample_delivery import check


class KeepBuyerTokenAtSeller(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_preview(seller_url, token, draw):
    url = urlsplit(seller_url)
    local = url.scheme == "http" and url.hostname in ("127.0.0.1", "::1")
    if (not (local or url.scheme == "https") or not url.hostname or url.username or
            url.password or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("Use the seller HTTPS origin or a loopback HTTP origin")
    req = Request(seller_url.rstrip("/") + "/sample/" + draw["request_tx"],
                  headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with build_opener(KeepBuyerTokenAtSeller()).open(req, timeout=45) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError("Sample response exceeds 64 KiB")
    delivery = json.loads(data)
    check(delivery, draw)
    return delivery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-api", default="http://127.0.0.1:8766")
    parser.add_argument("--rpc-url", default=RPC_URL)
    for arg in ("--seller", "--buyer", "--listing-tx", "--request-tx"):
        parser.add_argument(arg, required=True)
    args = parser.parse_args()
    token = os.environ.get("UBC26_BUYER_TOKEN")
    if not token:
        parser.error("Set UBC26_BUYER_TOKEN for this seller")
    try:
        draw = verify_draw(rpc_client(args.rpc_url), args.seller, args.buyer, args.listing_tx, args.request_tx)
        delivery = fetch_preview(args.seller_api, token, draw)
    except HTTPError as exc:
        parser.exit(1, f"Request failed with HTTP status {exc.code}\n")
    except (OSError, ValueError, IndexError, TypeError, KeyError) as exc:
        parser.exit(1, f"Preview could not be verified: {exc}\n")
    print(json.dumps({"draw": draw, "delivery": delivery}, indent=2))


if __name__ == "__main__":
    main()
