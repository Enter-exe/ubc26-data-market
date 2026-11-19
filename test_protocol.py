"""Offline protocol smoke tests with synthetic taxi rows and fictional Arc receipts."""
import json
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import HTTPServer
from io import StringIO
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import arc_draw
from arc_draw import verify_draw, verify_listing
from buyer_sample import fetch_preview
from chicago_snapshot import build_snapshot
from sample_delivery import package
from seller_api import main as seller_main, seller_handler


SELLER, BUYER = "0x" + "aa" * 20, "0x" + "bb" * 20
LISTING, REQUEST = "0x" + "11" * 32, "0x" + "22" * 32
TOKEN = "offline-fixture-token"


def fixture_responses(root, extra_transactions=(), finalized_height=13):
    responses = {("eth_chainId", ()): hex(5042002)}
    transactions = [
        (10, LISTING, SELLER, 0, 24_000, 300_000_000_001, b"UBC26:listing:v1:" + bytes.fromhex(root)),
        (11, REQUEST, BUYER, 10**16, 25_001, 400_000_000_001, b"UBC26:sample:v1:" + bytes.fromhex(LISTING[2:])),
    ]
    transactions.extend(extra_transactions)
    for height, tx_hash, sender, value, gas_used, gas_price, data in transactions:
        block_hash = f"0x{height:064x}"
        position = dict(blockHash=block_hash, blockNumber=hex(height), transactionIndex="0x0")
        responses["eth_getTransactionByHash", (tx_hash,)] = {
            **position, "hash": tx_hash, "from": sender, "to": SELLER,
            "type": "0x2", "value": hex(value), "input": "0x" + data.hex(),
        }
        responses["eth_getTransactionReceipt", (tx_hash,)] = dict(
            position, status="0x1", transactionHash=tx_hash,
            gasUsed=hex(gas_used), effectiveGasPrice=hex(gas_price))
        responses["eth_getBlockByNumber", (hex(height), False)] = dict(
            hash=block_hash, number=hex(height), transactions=[tx_hash])
        for address in (BUYER, SELLER):
            responses["eth_getCode", (address, hex(height))] = "0x"
    for height in (13, finalized_height):
        responses.setdefault(("eth_getBlockByNumber", (hex(height), False)), dict(
            hash=f"0x{height:064x}", number=hex(height), transactions=[]))
    responses["eth_getBlockByNumber", ("finalized", False)] = dict(
        responses["eth_getBlockByNumber", (hex(finalized_height), False)])
    return responses


@contextmanager
def seller_endpoint(deliver, deliver_purchase=None):
    with HTTPServer(("127.0.0.1", 0), seller_handler(TOKEN.encode(), deliver, deliver_purchase)) as server:
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

    def test_buyer_total_includes_request_gas_only(self):
        self.assertEqual(self.buyer_draw["request_gas_fee_base_units"], "10000400000025001")
        self.assertEqual(self.buyer_draw["buyer_total_base_units"], "20000400000025001")

    def test_buyer_receives_same_eight_proven_rows_on_retry(self):
        with seller_endpoint(self.deliver) as url:
            delivery = fetch_preview(url, TOKEN, self.buyer_draw)
            self.assertEqual(delivery, fetch_preview(url, TOKEN, self.buyer_draw))
        samples = delivery["samples"]
        self.assertEqual([s["index"] for s in samples], [28, 37, 45, 53, 56, 41, 50, 23])
        for sample in samples:
            self.assertEqual(sample["row"], [f"trip-{sample['index']:02d}", 125, 750])

    def test_pending_draw_returns_retry_delay_then_verified_sample_for_same_hash(self):
        tip = ("eth_getBlockByNumber", ("finalized", False))
        finalized = self.responses[tip]
        self.responses[tip] = self.responses["eth_getBlockByNumber", ("0xb", False)]
        with seller_endpoint(self.deliver) as url:
            request = Request(url + "/sample/" + REQUEST, headers={"Authorization": "Bearer " + TOKEN})
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 202)
                self.assertRegex(response.headers.get("Retry-After", ""), r"^[1-9][0-9]*$")
                self.assertEqual(json.load(response), {"status": "pending"})
            with self.assertRaises(arc_draw.ArcPending):
                fetch_preview(url, TOKEN, self.buyer_draw)
            self.responses[tip] = finalized
            self.assertEqual(fetch_preview(url, TOKEN, self.buyer_draw),
                             self.deliver(REQUEST))

    def test_conflicting_draw_or_malformed_receipt_never_returns_pending(self):
        tip = ("eth_getBlockByNumber", ("finalized", False))
        for key, replacement in [(tip, dict(self.responses[tip], hash="0x" + "ff" * 32)),
                                 (("eth_getTransactionReceipt", (REQUEST,)), [])]:
            with self.subTest(key=key):
                with patch.dict(self.responses, {key: replacement}), seller_endpoint(self.deliver) as url:
                    with self.assertRaises(HTTPError) as error:
                        fetch_preview(url, TOKEN, self.buyer_draw)
                    with error.exception as response:
                        self.assertEqual(response.code, 409)
                        self.assertNotIn(b"trip-", response.read())

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

    def test_pending_transaction_lookup_can_be_retried_with_same_hash(self):
        receipt_key = ("eth_getTransactionReceipt", (REQUEST,))
        with patch.dict(self.responses, {receipt_key: None}):
            with self.assertRaises(arc_draw.ArcPending):
                self.draw(REQUEST)
        transaction = self.responses["eth_getTransactionByHash", (REQUEST,)]
        height = transaction["blockNumber"]
        transaction["blockNumber"] = None
        with self.assertRaisesRegex(arc_draw.ArcPending, "retry with the same hash"):
            self.draw(REQUEST)
        transaction["blockNumber"] = height
        self.assertEqual(self.draw(REQUEST), self.buyer_draw)

    def test_seller_denies_payment_from_another_buyer(self):
        self.responses["eth_getTransactionByHash", (REQUEST,)]["from"] = "0x" + "cc" * 20
        with seller_endpoint(self.deliver) as url, self.assertRaises(HTTPError) as error:
            fetch_preview(url, TOKEN, self.buyer_draw)
        with error.exception as response:
            self.assertEqual(response.code, 409)
            self.assertNotIn(b"trip-", response.read())

    def test_seller_checks_snapshot_before_listening(self):
        def rpc(method, params):
            return self.responses[method, tuple(params)]

        args = ["seller_api.py", "--snapshot", "fixture.json", "--seller", SELLER,
                "--buyer", BUYER, "--listing-tx", LISTING]
        valid_snapshot = json.dumps(self.snapshot)
        self.snapshot["rows"][0][2] += 1
        for contents, can_listen in [(valid_snapshot, True), (json.dumps(self.snapshot), False)]:
            with self.subTest(can_listen=can_listen), patch("sys.argv", args), \
                    patch.dict("os.environ", {"UBC26_BUYER_TOKEN": TOKEN}), \
                    patch("seller_api.Path.read_text", return_value=contents), \
                    patch("seller_api.rpc_client", return_value=rpc), \
                    patch("seller_api.ThreadingHTTPServer") as server:
                if can_listen:
                    with redirect_stdout(StringIO()):
                        seller_main()
                    server.assert_called_once()
                else:
                    with redirect_stderr(StringIO()) as stderr, self.assertRaises(SystemExit):
                        seller_main()
                    self.assertIn("Snapshot differs from the anchored listing", stderr.getvalue())
                    server.assert_not_called()

    def test_buyer_rejects_changed_fare(self):
        def altered(request):
            delivery = self.deliver(request)
            delivery["samples"][0]["row"] = ["trip-28", 125, 751]
            return delivery

        with seller_endpoint(altered) as url, self.assertRaisesRegex(ValueError, "Invalid proof"):
            fetch_preview(url, TOKEN, self.buyer_draw)


if __name__ == "__main__":
    unittest.main()
