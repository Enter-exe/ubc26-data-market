"""Check the agent's payment boundary with fictional Arc receipts."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from btc_buyer import USDC_CONTRACT, arc_decision, main, paid_sample, usdc
import test_purchase
from test_purchase import OFFER
from test_protocol import BUYER, SELLER, LISTING, REQUEST, TOKEN, seller_endpoint
from arc_draw import BTC_LISTING_TAG, LISTING_TAG
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
        if method == "eth_call":
            self.wallet_reads.append(method)
            self.assertEqual(params, [{"to": USDC_CONTRACT,
                                       "data": "0x70a08231" + BUYER[2:].zfill(64)}, "pending"])
            return "0x" + (10**6).to_bytes(32, "big").hex()
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
        decision = self.run_decision("buy")
        self.assertEqual(decision["usdc_contract"],
                         {"address": USDC_CONTRACT, "balance_micro_usdc": "1000000"})
        tx = decision["wallet_request"]["params"][0]
        self.assertEqual((tx["from"], tx["to"], int(tx["value"], 16)), (BUYER, SELLER, 10**17))
        self.assertEqual((int(tx["gas"], 16), int(tx["gasPrice"], 16)), (28000, 100))

    def test_contract_balance_blocks_an_unaffordable_offer(self):
        from sample_delivery import package
        snapshot = {"rows": self.rows, "manifest": {"root": self.fixture.root}}

        def low_balance_rpc(method, params):
            if method == "eth_call":
                return "0x" + (99999).to_bytes(32, "big").hex()
            return self.rpc(method, params)

        with patch("btc_buyer.fetch_preview", side_effect=lambda url, token, draw: package(snapshot, draw)), \
                patch("btc_buyer.price_preview") as price:
            result = arc_decision(low_balance_rpc, "http://127.0.0.1", "buyer-secret", SELLER, BUYER,
                                  LISTING, REQUEST, OFFER, {}, usdc("0.5"), usdc("0.1"))
        self.assertEqual(result["valuation"]["decision"], "pass")
        self.assertNotIn("wallet_request", result)
        price.assert_not_called()

    def test_native_balance_preserves_gas_precision_beyond_six_decimals(self):
        from sample_delivery import package
        snapshot = {"rows": self.rows, "manifest": {"root": self.fixture.root}}
        native_balance = 10**17 + 10**11

        def precise_balance_rpc(method, params):
            if method == "eth_call":
                return "0x" + (100000).to_bytes(32, "big").hex()
            if method == "eth_getBalance":
                return hex(native_balance)
            return self.rpc(method, params)

        with patch("btc_buyer.fetch_preview", side_effect=lambda url, token, draw: package(snapshot, draw)), \
                patch("btc_buyer.price_preview", return_value={"decision": "pass"}) as price:
            arc_decision(precise_balance_rpc, "http://127.0.0.1", "buyer-secret", SELLER, BUYER,
                         LISTING, REQUEST, OFFER, {}, usdc("0.5"), usdc("0.1"))
        self.assertEqual(price.call_args.args[4], native_balance)

    def test_malformed_contract_result_stops_the_decision(self):
        from sample_delivery import package
        snapshot = {"rows": self.rows, "manifest": {"root": self.fixture.root}}

        def bad_contract_rpc(method, params):
            return "0x" if method == "eth_call" else self.rpc(method, params)

        with patch("btc_buyer.fetch_preview", side_effect=lambda url, token, draw: package(snapshot, draw)):
            with self.assertRaisesRegex(ValueError, "USDC balanceOf result"):
                arc_decision(bad_contract_rpc, "http://127.0.0.1", "buyer-secret", SELLER, BUYER,
                             LISTING, REQUEST, OFFER, {}, usdc("0.5"), usdc("0.1"))

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

            # Exercise both CLI entry points against the same private seller and fictional Arc receipts.
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                bench_file = path / "benchmark.json"
                bench_file.write_text(json.dumps(bench))
                draw = decision["draw"]
                stream = {"network": "arc-testnet", "dataset": "block", "stream_id": "btc-fixture",
                          "blocks": [{"number": hex(draw["request_block"]), "hash": draw["request_block_hash"],
                                      "requests": [{"hash": REQUEST, "from": BUYER, "to": SELLER, "listing_tx": LISTING}]},
                                     {"number": hex(draw["draw_block"]), "hash": draw["draw_block_hash"], "requests": []}]}
                stream_file = path / "stream.json"
                stream_file.write_text(json.dumps(stream))
                common = ["--seller", SELLER, "--buyer", BUYER, "--listing-tx", LISTING, "--offer-tx", OFFER,
                          "--seller-api", url, "--benchmark", str(bench_file), "--stream-delivery", str(stream_file)]
                for command, flags in [("decide", ["--remaining-budget", "1", "--reward-per-bp", "1"]),
                                       ("assess", ["--purchase-tx", PURCHASE])]:
                    output = io.StringIO()
                    with patch("sys.argv", ["btc_buyer.py", command, *common, *flags]), \
                            patch.dict(os.environ, UBC26_BUYER_TOKEN=TOKEN), \
                            patch("btc_buyer.rpc_client", return_value=self.rpc), redirect_stdout(output):
                        main()
                    receipt = json.loads(output.getvalue())
                    self.assertEqual(receipt["draw"]["indices"], draw["indices"])
                    self.assertEqual(receipt["draw"]["quicknode_streams"]["stream_id"], "btc-fixture")
                    if command == "decide":
                        self.assertEqual(receipt["wallet_request"], decision["wallet_request"])
                    else:
                        self.assertEqual(receipt["outcome"]["holdout_rows"], 64)
                self.fixture.responses["eth_getTransactionByHash", (LISTING,)]["input"] = "0x" + LISTING_TAG.hex() + root
                with patch("btc_buyer.fetch_preview") as fetch, self.assertRaisesRegex(ValueError, "BTC-USD hourly"):
                    paid_sample(self.rpc, url, TOKEN, SELLER, BUYER, LISTING, None, stream_files=[stream_file])
                fetch.assert_not_called()

    def test_rejects_fractional_base_units(self):
        with self.assertRaises(ValueError):
            usdc("0.0000000000000000001")
