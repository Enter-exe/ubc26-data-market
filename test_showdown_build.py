import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ShowdownBuildTests(unittest.TestCase):
    def test_offline_build_reuses_classic_replay_without_rewriting_it(self):
        source = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("build_demo.py", "demo.html"):
                shutil.copyfile(source / name, root / name)
            classic = (root / "demo.html").read_bytes()
            (root / "showdown-ui.html").write_text("<!--SHOWDOWN_DATA-->\n<!--SHOWDOWN_CORE-->")
            (root / "showdown-core.js").write_text("const demo = true;")
            subprocess.run([sys.executable, "-B", "build_demo.py", "--showdown"], check=True,
                           cwd=root, env={**os.environ, "PYTHONPATH": str(source)})
            page = (root / "showdown.html").read_text()
            self.assertEqual((root / "demo.html").read_bytes(), classic)
            self.assertIn("<script>const demo = true;</script>", page)
            opening = '<script type="application/json" id="recorded-runs">'
            payload = classic.decode().split(opening, 1)[1].split("</script>", 1)[0]
            self.assertIn(opening + payload + "</script>", page)

    def test_quicknode_build_reproduces_the_paid_draw_and_preserves_classic(self):
        import json
        from arc_draw import BTC_LISTING_TAG
        from market import tree
        from quicknode_draw import from_deliveries
        from test_btc_value import rows
        from test_protocol import BUYER, LISTING, REQUEST, SELLER, fixture_responses

        listing = rows(192, 64)
        root_hash = tree(listing)[-1][0].hex()
        responses = fixture_responses(root_hash)
        responses["eth_getTransactionByHash", (LISTING,)]["input"] = "0x" + BTC_LISTING_TAG.hex() + root_hash
        stream = dict(network="arc-testnet", dataset="block", stream_id="test-stream", blocks=[
            dict(number="0xb", hash=f"0x{11:064x}", requests=[
                {"hash": REQUEST, "from": BUYER, "to": SELLER, "listing_tx": LISTING}]),
            dict(number="0xd", hash=f"0x{13:064x}", requests=[]),
        ])
        draw = from_deliveries([stream], SELLER, BUYER, LISTING, lambda m, p: responses[m, tuple(p)])
        source = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("build_demo.py", "demo.html", "showdown-ui.html", "showdown-core.js"):
                shutil.copyfile(source / name, root / name)
            classic = (root / "demo.html").read_bytes()
            (root / "snapshot.json").write_text(json.dumps(dict(manifest=dict(root=root_hash), rows=listing)))
            (root / "benchmark.json").write_text(json.dumps(dict(calibration=rows(0, 192))))
            command = [sys.executable, "-B", "build_demo.py", "--snapshot", "snapshot.json",
                       "--benchmark", "benchmark.json", "--btc-draw", "draw.json"]
            def run(receipt):
                (root / "draw.json").write_text(json.dumps(receipt))
                return subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": str(source)},
                                      capture_output=True, text=True)
            result = run(draw)
            self.assertEqual(result.returncode, 0, result.stderr)
            page = (root / "showdown.html").read_text()
            data = json.loads(page.split('id="recorded-runs">', 1)[1].split("</script>", 1)[0])
            self.assertEqual(data["btc_draw"]["request_tx"], REQUEST)
            self.assertEqual([s["index"] for s in data["samples"]], draw["indices"])
            self.assertEqual(data["runs"]["0.20"]["mode"], "modeled")
            for invalid in (dict(draw, dataset="taxi"), dict(draw, root="99" * 32),
                            dict(draw, indices=draw["indices"][::-1]), dict(draw, quicknode_streams={}),
                            dict(draw, draw_block=12)):
                with self.subTest(receipt=invalid):
                    self.assertNotEqual(run(invalid).returncode, 0)
                    self.assertEqual((root / "showdown.html").read_text(), page)
            bare_draw = dict(draw)
            del bare_draw["quicknode_streams"]
            self.assertEqual(run(bare_draw).returncode, 0)
            def payload():
                return json.loads((root / "showdown.html").read_text().split('id="recorded-runs">', 1)[1].split("</script>", 1)[0])
            self.assertNotIn("quicknode_streams", payload()["btc_draw"])
            from btc_buyer import listing_start, usdc
            from btc_value import price_preview
            from arc_purchase import FULL_PRICE_BASE_UNITS
            selected = [listing[i] for i in bare_draw["indices"]]
            offer = {key: draw[key] for key in ("chain_id", "dataset", "root", "seller", "listing_tx")}
            offer.update(offer_tx="0x" + "4a" * 32, price_base_units=str(FULL_PRICE_BASE_UNITS))
            for reward in (usdc("0.20"), 0):
                valuation = price_preview(selected, dict(calibration=rows(0, 192)), FULL_PRICE_BASE_UNITS,
                                          583400000000000, usdc("0.20"), reward,
                                          listing_start=listing_start(draw, selected))
                decision = dict(mode="arc-testnet", offer=offer, draw=bare_draw, valuation=valuation)
                built = run(decision)
                self.assertEqual(built.returncode, 0, built.stderr)
                self.assertEqual(payload()["runs"]["0.20"]["valuation"], valuation)
                self.assertEqual(payload()["runs"]["0.20"]["mode"], "recorded")
                self.assertEqual(payload()["btc_draw"]["offer_tx"], offer["offer_tx"])
                self.assertNotEqual(run(dict(decision, valuation=dict(valuation, estimated_value_base_units="1"))).returncode, 0)
            limited = dict(decision="pass", reason="Full price exceeds remaining funds",
                           price_base_units=str(FULL_PRICE_BASE_UNITS), available_base_units="1")
            self.assertEqual(run(dict(decision, valuation=limited)).returncode, 0)
            self.assertNotEqual(run(dict(decision, offer=dict(offer, listing_tx="0x" + "44" * 32))).returncode, 0)
            live_page = (root / "showdown.html").read_bytes()
            subprocess.run([sys.executable, "-B", "build_demo.py", "--showdown"], check=True, cwd=root,
                           env={**os.environ, "PYTHONPATH": str(source)})
            self.assertEqual((root / "showdown.html").read_bytes(), live_page)
            self.assertEqual((root / "demo.html").read_bytes(), classic)
