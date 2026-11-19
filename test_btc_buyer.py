"""Check the agent's payment boundary with fictional Arc receipts."""
import unittest
from unittest.mock import patch

from btc_buyer import arc_decision, usdc
import test_purchase
from test_purchase import OFFER
from test_protocol import BUYER, SELLER, LISTING, REQUEST, TOKEN, seller_endpoint
from arc_draw import BTC_LISTING_TAG
from market import tree


class BuyerDecisionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_purchase.FullPurchaseTest()
        self.fixture.setUp()
        self.rows = [[f"BTC-USD:1h:{1704067200 + i * 3600}", 10, 10] for i in range(64)]
        self.fixture.root = tree(self.rows)[-1][0].hex()
        self.fixture.configure()
        tx = self.fixture.responses["eth_getTransactionByHash", (LISTING,)]
        tx["input"] = "0x" + BTC_LISTING_TAG.hex() + self.fixture.root
        self.wallet_reads = []

    def rpc(self, method, params):
        if method in ("eth_gasPrice", "eth_estimateGas", "eth_getBalance"):
            self.wallet_reads.append(method)
            return hex({"eth_gasPrice": 100, "eth_estimateGas": 28000, "eth_getBalance": 10**18}[method])
        return self.fixture.rpc(method, params)

    def run_decision(self, decision):
        from sample_delivery import package
        snapshot = {"rows": self.rows, "manifest": {"root": self.fixture.root}}
        def preview(url, token, draw):
            return package(snapshot, draw)
        with patch("btc_buyer.fetch_preview", side_effect=preview), patch(
                "btc_buyer.price_preview", return_value={"decision": decision}) as price:
            result = arc_decision(self.rpc, "http://127.0.0.1", "buyer-secret", SELLER, BUYER,
                                  LISTING, REQUEST, OFFER, {}, usdc("0.5"), usdc("0.1"))
        self.assertEqual(price.call_args.args[3], 28000 * 100)
        return result

    def test_only_buy_emits_a_gas_bounded_purchase_request(self):
        self.assertNotIn("wallet_request", self.run_decision("pass"))
        tx = self.run_decision("buy")["wallet_request"]["params"][0]
        self.assertEqual((tx["from"], tx["to"], int(tx["value"], 16)), (BUYER, SELLER, 10**17))
        self.assertEqual((int(tx["gas"], 16), int(tx["gasPrice"], 16)), (28000, 100))

    def test_private_sample_to_decision_and_purchased_holdout(self):
        from arc_draw import verify_draw
        from arc_purchase import verify_purchase
        from btc_value import measured_outcome
        from buyer_sample import fetch_purchase
        from sample_delivery import package
        from test_purchase import PURCHASE

        def hours(start, count):
            return [[f"BTC-USD:1h:{1704067200 + i * 3600}", i + 1, i + 2] for i in range(start, start + count)]
        rows = hours(193, 64)
        bench = {"calibration": hours(0, 192), "holdout": hours(258, 64)}
        root = tree(rows)[-1][0].hex()
        self.fixture.responses["eth_getTransactionByHash", (LISTING,)]["input"] = "0x" + BTC_LISTING_TAG.hex() + root
        snapshot = {"manifest": {"root": root}, "rows": rows}
        def deliver_sample(request):
            return package(snapshot, verify_draw(self.rpc, SELLER, BUYER, LISTING, request))
        def deliver_full(payment):
            self.assertEqual(verify_purchase(self.rpc, SELLER, BUYER, LISTING, OFFER, payment)["root"], root)
            return {"rows": rows}
        with seller_endpoint(deliver_sample, deliver_full) as url:
            args = (self.rpc, url, TOKEN, SELLER, BUYER, LISTING, REQUEST, OFFER, bench, usdc("1"))
            self.assertNotIn("wallet_request", arc_decision(*args, 0))
            decision = arc_decision(*args, usdc("1"))
            self.assertEqual(decision["valuation"]["decision"], "buy")
            purchase = verify_purchase(self.rpc, SELLER, BUYER, LISTING, OFFER, PURCHASE)
            full = fetch_purchase(url, TOKEN, purchase)
            preview = [rows[i] for i in decision["draw"]["indices"]]
            self.assertEqual(measured_outcome(preview, full["rows"], bench)["holdout_rows"], 64)

    def test_rejects_fractional_base_units(self):
        with self.assertRaises(ValueError):
            usdc("0.0000000000000000001")
