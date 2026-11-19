"""Rehearse full purchases with fictional Arc transactions and a private loopback seller."""
import unittest
from urllib.error import HTTPError

from arc_purchase import verify_offer, verify_purchase
from buyer_sample import fetch_purchase
from market import tree
from test_protocol import BUYER, LISTING, SELLER, TOKEN, fixture_responses, seller_endpoint


OFFER, PURCHASE = "0x" + "33" * 32, "0x" + "44" * 32
PRICE = 10**17


class FullPurchaseTest(unittest.TestCase):
    def setUp(self):
        self.rows = [[f"trip-{i:02d}", 125, 750] for i in range(64)]
        self.root = tree(self.rows)[-1][0].hex()
        self.configure()

    def configure(self, offer_height=12, purchase_height=14, finalized_height=14):
        self.responses = fixture_responses(self.root, [
            (offer_height, OFFER, SELLER, 0, 24_000, 9,
             b"UBC26:offer:v1:" + bytes.fromhex(LISTING[2:])),
            (purchase_height, PURCHASE, BUYER, PRICE, 25_000, 11,
             b"UBC26:purchase:v1:" + bytes.fromhex(OFFER[2:])),
        ], finalized_height)

    def rpc(self, method, params):
        return self.responses[method, tuple(params)]

    def purchase(self, tx=PURCHASE):
        return verify_purchase(self.rpc, SELLER, BUYER, LISTING, OFFER, tx)

    def deliver(self, tx):
        self.purchase(tx)
        return {"rows": self.rows}

    def test_finalized_offer_and_payment_match_the_committed_listing(self):
        offer = verify_offer(self.rpc, SELLER, LISTING, OFFER)
        self.assertEqual(offer["root"], self.root)
        purchase = self.purchase()
        self.assertEqual(purchase["root"], self.root)
        self.assertEqual(purchase["purchase_tx"], PURCHASE)
        self.assertEqual(purchase["price_base_units"], str(PRICE))
        self.assertEqual(purchase["purchase_gas_fee_base_units"], "275000")
        self.assertEqual(purchase["buyer_total_base_units"], str(PRICE + 275_000))

    def test_rejects_invalid_offer_or_payment(self):
        for tx, field, value in [
            (OFFER, "from", BUYER), (OFFER, "value", "0x1"),
            (OFFER, "input", "0x" + b"UBC26:offer:v1:".hex() + OFFER[2:]),
            (PURCHASE, "from", SELLER), (PURCHASE, "to", BUYER),
            (PURCHASE, "value", hex(PRICE - 1)),
            (PURCHASE, "input", "0x" + b"UBC26:purchase:v1:".hex() + LISTING[2:]),
        ]:
            with self.subTest(tx=tx, field=field):
                self.configure()
                self.responses["eth_getTransactionByHash", (tx,)][field] = value
                with self.assertRaises(ValueError):
                    self.purchase()

    def test_requires_ordered_finalized_transactions(self):
        for offer, purchase, tip in [(9, 14, 14), (14, 12, 14), (12, 14, 13)]:
            with self.subTest(offer=offer, purchase=purchase, tip=tip):
                self.configure(offer, purchase, tip)
                with self.assertRaises(ValueError):
                    self.purchase()

    def test_buyer_recovers_all_rows_on_retry(self):
        purchase = self.purchase()
        with seller_endpoint(None, self.deliver) as url:
            for _ in range(2):
                self.assertEqual(fetch_purchase(url, TOKEN, purchase)["rows"], self.rows)

    def test_private_route_requires_an_offer_a_buyer_token_and_a_valid_payment(self):
        purchase = self.purchase()
        for deliver, token, expected in [(None, TOKEN, 404), (self.deliver, "", 401),
                                         (self.deliver, TOKEN, 409)]:
            with self.subTest(status=expected):
                self.responses["eth_getTransactionReceipt", (PURCHASE,)]["status"] = "0x0"
                with seller_endpoint(None, deliver) as url, self.assertRaises(HTTPError) as error:
                    fetch_purchase(url, token, purchase)
                with error.exception as response:
                    self.assertEqual(response.code, expected)
                    self.assertNotIn(b"trip-", response.read())

    def test_buyer_checks_the_root_of_received_rows(self):
        purchase = self.purchase()
        self.rows[0][2] += 1
        with seller_endpoint(None, self.deliver) as url, self.assertRaises(ValueError):
            fetch_purchase(url, TOKEN, purchase)
