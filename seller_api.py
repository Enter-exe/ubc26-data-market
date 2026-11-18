"""Serve one buyer's paid samples on loopback. Share the bearer token privately."""
import argparse
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from arc_draw import RPC_URL, hex_data, rpc_client, verify_draw
from sample_delivery import package


def seller_handler(token, deliver):
    class SampleHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            # Request targets can contain credentials sent by mistake.
            pass

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            headers = self.headers.get_all("Authorization", [])
            scheme, _, supplied = headers[0].partition(" ") if len(headers) == 1 else ("", "", "")
            if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode("latin-1"), token):
                self.reply(401, {"error": "Buyer authentication required"})
                return
            match = re.fullmatch(r"/sample/(0x[0-9a-fA-F]{64})", self.path)
            if not match:
                self.reply(404, {"error": "Unknown sample route"})
                return
            try:
                delivery = deliver(match.group(1))
            except OSError:
                self.reply(503, {"error": "Arc RPC unavailable"})
                return
            except (ValueError, TypeError, KeyError, IndexError):
                self.reply(409, {"error": "Could not verify a finalized draw against this listing"})
                return
            self.reply(200, delivery)

    return SampleHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--seller", required=True)
    parser.add_argument("--buyer", required=True)
    parser.add_argument("--listing-tx", required=True)
    parser.add_argument("--rpc-url", default=RPC_URL)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    token = os.environ.get("UBC26_BUYER_TOKEN", "")
    if not re.fullmatch(r"[!-~]+", token):
        parser.error("Set UBC26_BUYER_TOKEN to a secret printable ASCII token without spaces")
    try:
        seller = hex_data(args.seller, 20, "seller")
        buyer = hex_data(args.buyer, 20, "buyer")
        if seller == buyer:
            raise ValueError("Seller and buyer must have distinct addresses")
        listing = hex_data(args.listing_tx, 32, "listing transaction")
        rpc = rpc_client(args.rpc_url)
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))

        def deliver(request_tx):
            draw = verify_draw(rpc, seller, buyer, listing, request_tx)
            return package(snapshot, draw)

        handler = seller_handler(token.encode("ascii"), deliver)
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Seller API listening on http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except (OSError, ValueError, OverflowError) as exc:
        parser.exit(1, f"Seller API failed: {exc}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
