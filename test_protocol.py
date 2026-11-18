"""Offline protocol smoke tests with synthetic taxi rows and fictional Arc receipts."""
import unittest
from contextlib import contextmanager
from http.server import HTTPServer
from threading import Thread
from urllib.error import HTTPError

from arc_draw import verify_draw, verify_listing
from buyer_sample import fetch_preview
from chicago_snapshot import build_snapshot
from sample_delivery import package
from seller_api import seller_handler


SELLER, BUYER = "0x" + "aa" * 20, "0x" + "bb" * 20
LISTING, REQUEST = "0x" + "11" * 32, "0x" + "22" * 32
TOKEN = "offline-fixture-token"


def fixture_responses(root):
    responses = {("eth_chainId", ()): hex(5042002)}
    transactions = [
        (10, LISTING, SELLER, 0, b"UBC26:listing:v1:" + bytes.fromhex(root)),
        (11, REQUEST, BUYER, 10**16, b"UBC26:sample:v1:" + bytes.fromhex(LISTING[2:])),
    ]
    for height, tx_hash, sender, value, data in transactions:
        block_hash = f"0x{height:064x}"
        position = dict(blockHash=block_hash, blockNumber=hex(height), transactionIndex="0x0")
        responses["eth_getTransactionByHash", (tx_hash,)] = {
            **position, "hash": tx_hash, "from": sender, "to": SELLER,
            "type": "0x2", "value": hex(value), "input": "0x" + data.hex(),
        }
        responses["eth_getTransactionReceipt", (tx_hash,)] = dict(
            position, status="0x1", transactionHash=tx_hash)
        responses["eth_getBlockByNumber", (hex(height), False)] = dict(
            hash=block_hash, number=hex(height), transactions=[tx_hash])
        for address in (BUYER, SELLER):
            responses["eth_getCode", (address, hex(height))] = "0x"
    for tag in ("finalized", "0xd"):
        responses["eth_getBlockByNumber", (tag, False)] = dict(
            hash=f"0x{13:064x}", number="0xd", transactions=[])
    return responses


@contextmanager
def seller_endpoint(deliver):
    with HTTPServer(("127.0.0.1", 0), seller_handler(TOKEN.encode(), deliver)) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()


class ListingVerificationTest(unittest.TestCase):
    root = "ab" * 32

    def verify(self, responses):
        def rpc(method, params):
            return responses[method, tuple(params)]
        return verify_listing(rpc, SELLER, LISTING)

    def test_returns_anchor_position_hash_and_lowercase_root(self):
        responses = fixture_responses(self.root)
        anchor = responses["eth_getTransactionByHash", (LISTING,)]
        anchor["input"] = "0x" + anchor["input"][2:].upper()
        self.assertEqual(self.verify(responses), ((10, 0), f"0x{10:064x}", self.root))

    def test_rejects_wrong_chain(self):
        responses = fixture_responses(self.root)
        responses["eth_chainId", ()] = "0x1"
        with self.assertRaises(ValueError):
            self.verify(responses)

    def test_rejects_invalid_anchors(self):
        cases = [
            ("wrong signer", "eth_getTransactionByHash", (LISTING,), {"from": BUYER}),
            ("failed receipt", "eth_getTransactionReceipt", (LISTING,), {"status": "0x0"}),
            ("missing from block", "eth_getBlockByNumber", ("0xa", False), {"transactions": []}),
            ("unfinalized", "eth_getBlockByNumber", ("finalized", False), {"number": "0x9"}),
            ("conflicting finalized tip", "eth_getBlockByNumber", ("finalized", False),
             {"number": "0xa", "hash": "0x" + "ff" * 32}),
        ]
        for label, method, params, changes in cases:
            with self.subTest(label):
                responses = fixture_responses(self.root)
                responses[method, params].update(changes)
                with self.assertRaises(ValueError):
                    self.verify(responses)


class ProtocolSmokeTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_snapshot([
            dict(trip_id=f"trip-{i:02d}", trip_miles="1.25", fare="7.50")
            for i in reversed(range(64))
        ])
        self.responses = fixture_responses(self.snapshot["manifest"]["root"])
        self.buyer_draw = self.draw(REQUEST)

    def draw(self, request):
        def rpc(method, params):
            return self.responses[method, tuple(params)]
        return verify_draw(rpc, SELLER, BUYER, LISTING, request)

    def deliver(self, request):
        return package(self.snapshot, self.draw(request))

    def test_buyer_receives_same_eight_proven_rows_on_retry(self):
        with seller_endpoint(self.deliver) as url:
            delivery = fetch_preview(url, TOKEN, self.buyer_draw)
            self.assertEqual(delivery, fetch_preview(url, TOKEN, self.buyer_draw))
        samples = delivery["samples"]
        self.assertEqual([s["index"] for s in samples], [28, 37, 45, 53, 56, 41, 50, 23])
        for sample in samples:
            self.assertEqual(sample["row"], [f"trip-{sample['index']:02d}", 125, 750])

    def test_seller_denies_wrong_token_and_failed_payment(self):
        with seller_endpoint(self.deliver) as url:
            for token, status in [("wrong", 401), (TOKEN, 409)]:
                if token == TOKEN:
                    self.responses["eth_getTransactionReceipt", (REQUEST,)]["status"] = "0x0"
                with self.assertRaises(HTTPError) as error:
                    fetch_preview(url, token, self.buyer_draw)
                with error.exception as response:
                    self.assertEqual(response.code, status)
                    self.assertNotIn(b"trip-", response.read())

    def test_buyer_rejects_changed_fare(self):
        def altered(request):
            delivery = self.deliver(request)
            delivery["samples"][0]["row"] = ["trip-28", 125, 751]
            return delivery

        with seller_endpoint(altered) as url, self.assertRaisesRegex(ValueError, "Invalid proof"):
            fetch_preview(url, TOKEN, self.buyer_draw)


if __name__ == "__main__":
    unittest.main()
