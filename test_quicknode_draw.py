"""Offline checks for discovery from filtered QuickNode Streams block deliveries."""
import unittest

from arc_draw import verify_draw
from quicknode_draw import from_deliveries
from test_protocol import BUYER, LISTING, REQUEST, SELLER, fixture_responses


class StreamDrawTest(unittest.TestCase):
    def setUp(self):
        self.responses = fixture_responses("ab" * 32)
        self.request = {"hash": REQUEST, "from": BUYER, "to": SELLER, "listing_tx": LISTING}
        self.payment = {"number": "0xb", "hash": f"0x{11:064x}", "requests": [self.request]}
        self.future = {"number": "0xd", "hash": f"0x{13:064x}", "requests": []}

    def batch(self, *blocks):
        return {"network": "arc-testnet", "dataset": "block", "stream_id": "test-stream", "blocks": list(blocks)}

    def rpc(self, method, params):
        return self.responses[method, tuple(params)]

    def read(self, *deliveries):
        return from_deliveries(deliveries, SELLER, BUYER, LISTING, self.rpc)

    def test_replayed_or_out_of_order_batches_produce_one_verified_payment(self):
        payment = dict(self.payment, requests=[dict(self.request, **{"from": SELLER, "hash": "0x" + "ef" * 32}),
                                               self.request])
        receipt = self.read(self.batch(self.future), self.batch(payment), self.batch(payment, self.future))
        self.assertEqual(receipt.pop("quicknode_streams"), {
            "network": "arc-testnet", "dataset": "block", "stream_id": "test-stream"})
        self.assertEqual(receipt, verify_draw(self.rpc, SELLER, BUYER, LISTING, REQUEST))

    def test_requires_consistent_deliveries_and_one_matching_request(self):
        original = self.batch(self.payment, self.future)
        for invalid in [
            [self.batch(self.payment)],
            [self.batch(self.future)],
            [self.batch(self.payment, dict(self.future, requests=[dict(self.request, hash="0x" + "ee" * 32)]))],
            [original, self.batch(dict(self.payment, requests=[]))],
            [original, self.batch(dict(self.payment, hash="0x" + "ee" * 32))],
            [self.batch(self.payment), dict(self.batch(self.future), stream_id="another")],
            [dict(original, network="ethereum-mainnet")],
            [dict(original, dataset="logs")],
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.read(*invalid)

    def test_canonical_rpc_checks_payment_and_both_stream_hashes(self):
        for i in range(2):
            blocks = [self.payment.copy(), self.future.copy()]
            blocks[i]["hash"] = "0x" + "99" * 32
            with self.subTest(block=i), self.assertRaises(ValueError):
                self.read(self.batch(*blocks))
        self.responses["eth_getTransactionReceipt", (REQUEST,)]["status"] = "0x0"
        with self.assertRaisesRegex(ValueError, "successful receipt"):
            self.read(self.batch(self.payment, self.future))
