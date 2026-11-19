"""Exercise the BTC-specific onchain schema tag and its row encoding."""
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import arc_intent
from arc_draw import verify_draw, verify_listing
from arc_purchase import verify_purchase
from market import tree
from sample_delivery import check, check_full_rows, package
from test_protocol import SELLER, BUYER, LISTING, REQUEST, fixture_responses
from test_purchase import OFFER, PURCHASE, PRICE


class BtcProtocolTest(unittest.TestCase):
    def setUp(self):
        self.rows = [[f"BTC-USD:1h:{1704067200 + 3600*i}", i+1, i+2] for i in range(64)]
        self.root = tree(self.rows)[-1][0].hex()
        self.responses = fixture_responses(self.root, [
            (12, OFFER, SELLER, 0, 24000, 9, b"UBC26:offer:v1:" + bytes.fromhex(LISTING[2:])),
            (14, PURCHASE, BUYER, PRICE, 25000, 11, b"UBC26:purchase:v1:" + bytes.fromhex(OFFER[2:])),
        ], 14)

    def rpc(self, method, params):
        return self.responses[method, tuple(params)]

    def test_btc_anchor_reaches_buyer_preview_and_purchase(self):
        argv = ["arc_intent.py", "listing", "--dataset", "btc-usd-hourly", "--seller", SELLER, "--root", self.root]
        with patch("sys.argv", argv), redirect_stdout(StringIO()) as output:
            arc_intent.main()
        anchor = json.loads(output.getvalue())["params"][0]["data"]
        self.assertEqual(anchor, "0x" + b"UBC26:btc-usd-hourly:v1:".hex() + self.root)
        self.responses["eth_getTransactionByHash", (LISTING,)]["input"] = anchor
        self.assertEqual(verify_listing(self.rpc, SELLER, LISTING)[2], self.root)
        draw = verify_draw(self.rpc, SELLER, BUYER, LISTING, REQUEST)
        self.assertEqual(draw["dataset"], "btc-usd-hourly")
        delivery = package({"manifest": {"root": self.root}, "rows": self.rows}, draw)
        check(delivery, draw)
        purchase = verify_purchase(self.rpc, SELLER, BUYER, LISTING, OFFER, PURCHASE)
        self.assertEqual(purchase["dataset"], "btc-usd-hourly")
        check_full_rows(self.rows, purchase["root"], purchase["dataset"])

    def test_market_sample_payment_requires_matching_finalized_schema_and_root(self):
        argv = ["arc_intent.py", "request", "--buyer", BUYER, "--seller", SELLER, "--listing-tx", LISTING,
                "--dataset", "btc-usd-hourly"]
        for tag, extra, failure in [
            (b"UBC26:btc-usd-hourly:v1:", [], "--expected-root"),
            (b"UBC26:listing:v1:", ["--expected-root", self.root], "dataset"),
            (b"UBC26:btc-usd-hourly:v1:", ["--expected-root", "00" * 32], "root"),
            (b"UBC26:btc-usd-hourly:v1:", ["--expected-root", self.root], None),
        ]:
            with self.subTest(tag=tag, extra=extra), patch("sys.argv", argv + extra), \
                    patch.object(arc_intent, "rpc_client", return_value=self.rpc), \
                    redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
                self.responses["eth_getTransactionByHash", (LISTING,)]["input"] = "0x" + tag.hex() + self.root
                if failure:
                    with self.assertRaises(SystemExit):
                        arc_intent.main()
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn(failure, stderr.getvalue())
                else:
                    arc_intent.main()
                    self.assertEqual(json.loads(stdout.getvalue())["params"][0]["value"], hex(10**16))

    def test_legacy_draw_keeps_its_original_shape(self):
        self.assertNotIn("dataset", verify_draw(self.rpc, SELLER, BUYER, LISTING, REQUEST))

    def test_unknown_listing_tag_rejected(self):
        self.responses["eth_getTransactionByHash", (LISTING,)]["input"] = "0x" + b"UBC26:listing:v9:".hex() + self.root
        with self.assertRaises(ValueError):
            verify_listing(self.rpc, SELLER, LISTING)

    def test_full_delivery_rejects_invalid_hour_and_discontinuity(self):
        for row_id in ["trip-3", "BTC-USD:1h:1704067201", self.rows[2][0]]:
            with self.subTest(row_id=row_id):
                rows = self.rows.copy()
                rows[1] = [row_id, 2, 3]
                with self.assertRaises(ValueError):
                    check_full_rows(rows, tree(rows)[-1][0].hex(), "btc-usd-hourly")

    def test_valid_membership_does_not_override_inconsistent_hour_at_drawn_index(self):
        draw = verify_draw(self.rpc, SELLER, BUYER, LISTING, REQUEST)
        rows = self.rows.copy()
        index = draw["indices"][0]
        rows[index] = rows[(index + 1) % 64]
        root = tree(rows)[-1][0].hex()
        draw.update(root=root, dataset="btc-usd-hourly")
        delivery = package({"manifest": {"root": root}, "rows": rows}, draw)
        with self.assertRaisesRegex(ValueError, "positions"):
            check(delivery, draw)

    def test_unsigned_purchase_targets_validated_offer(self):
        envelope = arc_intent.purchase_wallet_request(SELLER, BUYER, OFFER)
        self.assertEqual(envelope["params"], [{"from": BUYER, "to": SELLER, "value": hex(PRICE),
                                             "data": "0x" + b"UBC26:purchase:v1:".hex() + OFFER[2:]}])
