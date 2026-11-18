"""Local buyer decision screen. Start with python3 desk.py."""
import json
import secrets
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from market import SCENARIOS, evaluate


def screen(receipt):
    seed, scenario, price = (receipt[k] for k in ("seed", "scenario", "price"))
    query = escape(urlencode(dict(seed=seed, scenario=scenario, price=price)))
    options = "".join(f'<option value="{k}" {"selected" if scenario == k else ""}>{v}</option>'
                      for k, v in SCENARIOS.items())
    offers = []
    for offer in receipt["offers"]:
        rows = "".join(f"<tr><td>{r['index']}</td><td>{r['miles']}</td><td>{r['quote']}</td>"
                       f"<td>{'Verified' if r['verified'] else 'Failed'}</td></tr>" for r in offer["samples"])
        score = (f"Held-out error <b>{offer['error']:.2f}</b> · estimated value "
                 f"<b>{offer['value']:.2f} credits</b>") if offer["value"] is not None else "Score withheld because a row failed verification."
        offers.append(f"""<article><h3>{offer['seller']} <small>{offer['decision']}</small></h3>
<p>{score}</p><details><summary>Inspect eight sample rows</summary><table>
<tr><th>Index</th><th>Miles</th><th>Quote</th><th>Proof</th></tr>{rows}</table>
<p>Committed SHA-256 root</p><code>{offer['root']}</code></details></article>""")
    ledger = "".join(f"<tr><td>{x['purpose']}</td><td>{x['seller']}</td><td>{x['amount']}</td>"
                     f"<td>{x['balance']}</td></tr>" for x in receipt["ledger"])
    title = f"Buy {receipt['winner']}." if receipt["winner"] else "Pass on both offers."
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Buyer desk · UBC26</title><link rel="stylesheet" href="/desk.css"><main>
<header><strong>Freight data market</strong><span>UBC26 / Simulated payments</span></header>
<h1>Buyer desk</h1><form action="/"><label>Market conditions<select name="scenario">{options}</select></label>
<label>Dataset price · credits<input name="price" type="number" min="1" max="100" required value="{price}"></label>
<input type="hidden" name="seed" value="{seed}"><button>Evaluate offers</button></form>
<section class="decision"><h2>{title}</h2><p>Baseline quote error <b>{receipt['baseline']:.2f}</b> across 32 held-out jobs.
The agent values a ten-unit reduction in average error at one credit.</p></section>
<div class="columns"><section><h2>Seller evidence</h2>{''.join(offers)}</section>
<section><h2>Wallet receipt</h2><p>Opening balance <b>100 credits</b></p><table>
<tr><th>Item</th><th>Seller</th><th>Paid</th><th>Left</th></tr>{ledger}</table>
<p>Draw seed <code>{seed}</code></p><a href="/receipt?{query}" download="receipt.json">Download receipt</a>
 · <a href="/?scenario={scenario}&amp;price={price}">Draw a fresh sample</a></section></div>
<footer>Synthetic freight quotes · local simulation</footer></main></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/desk.css":
            self.respond("text/css", Path(__file__).with_name("desk.css").read_text())
            return
        if url.path not in ("/", "/receipt"):
            self.send_error(404)
            return
        params = parse_qs(url.query)
        try:
            seed = int(params.get("seed", [secrets.randbits(64)])[0])
            if not 0 <= seed < 2**64:
                raise ValueError
            scenario = params.get("scenario", ["baseline"])[0]
            price = int(params.get("price", [40])[0])
            receipt = evaluate(seed, scenario, price)
        except ValueError:
            self.send_error(400, "Invalid seed, scenario, or price")
            return
        if url.path == "/receipt":
            self.respond("application/json", json.dumps(receipt, indent=2))
        else:
            self.respond("text/html", screen(receipt))

    def respond(self, mime, content):
        data = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("Buyer desk: http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
