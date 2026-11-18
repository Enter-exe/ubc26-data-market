# UBC26 · Try-before-you-buy data market for agents

A buyer can inspect a few records but needs to decide whether the remaining records are worth their price. This demo makes that decision visible. Two sellers offer freight quotes. The buyer pays a small sample fee to each, checks where the rows came from, measures their usefulness on its own pricing task, then buys the qualifying offer with the largest estimated surplus.

## Run the first demo

Run `python3 market.py` with Python 3.8 or later. It uses the standard library and runs offline. The terminal shows each seller’s commitment, the buyer’s sampled indices, proof results, prediction errors, prices, decision, and remaining balance.

For the interactive buyer desk, run `python3 desk.py` and open [the local demo](http://127.0.0.1:8765). Change the price with the same sample to see when the buyer walks away. The scenario selector can replace both offers with stale data or alter one regional quote after commitment. Expand a seller to inspect each row and its verification result. Download the JSON receipt for the full proof paths, wallet ledger and replay settings. Reproduce a draw with `python3 market.py --seed 26 --scenario baseline --price 40 --json`, substituting the values in your receipt. Each evaluation starts a separate simulated wallet.

Each synthetic seller commits one quote per lane across the same public catalog of 64 freight lanes. The buyer has a separate benchmark quote on each lane. For each verified sample it can fit a rate per mile, use the sampled quotes as route-specific lookups, or combine both sellers' retained rows. It picks the lowest mean absolute error among those strategies and the existing baseline. This is the buyer's alternative to making a purchase.

The estimated error of a full listing is its average quote error on the eight randomly sampled lanes. The purchase rule converts the projected reduction **beyond the best retained strategy** into credits (ten error units per credit), checks the asking price and budget, and buys at most one listing. After delivery it verifies the Merkle root and reports the measured error across all lanes. A small sample can misestimate full-listing error. The same private benchmark selects the retained strategy and measures performance, so these figures describe the demo benchmark rather than independent production performance.

For a contrasting run, choose **One rate fits every route**. A good sample can teach the agent enough to keep its credits. Receipt version 2 records retained, projected and delivered errors. Version 1 receipts can be replayed with the CLI at commit `482aebc`.

This demonstrates a purchase rule under controlled conditions. A valid proof establishes membership in the committed dataset. Label quality, representative sampling across buyers, and the value of unseen rows are separate questions. All participants run in one process. The wallet is simulated, and rerunning the script starts a fresh session.

## Hackathon scope

The original project proposed two sellers of labeled truck images. The image datasets are currently unavailable. Freight quote prediction provides a stand-in with a measurable loss until licensed data and a separate buyer benchmark are available.

| Milestone | Deliverable | Acceptance criterion |
| --- | --- | --- |
| 1 · Offline buying decision (implemented) | Two commitments, paid samples, proof checks, held-out evaluation, buy or pass, full delivery | A single run explains each decision using measured error and accounts for both fees and the purchase. |
| 2 · Inspectable demo | Buyer and seller boundaries, a replayable decision receipt, and a UI showing samples, scores, price, and wallet history | A viewer can trace which rows and proof root drove a purchase. A changed row fails verification. A run with two poor offers ends without a purchase. |
| 3 · Testnet settlement | Register a listing commitment, collect a sample fee, and settle one full purchase on a test network | Receipt links show successful transactions. A retry can recover the same purchase without another charge. |
| 4 · Real evaluation | Use licensed records, a private holdout, and repeated draws at several sample sizes | Report variation in sample decisions and compare them with measured utility after full delivery. |

The larger protocol adds seller collateral, verifiable random sampling, learning curves, and chunked payments with a dispute mechanism. Prioritize these once the end-to-end purchase is demonstrable. Repeated small purchases could expose much of a listing. A deployed market needs a per-listing disclosure and pricing policy before offering valuable data.

## Proposed hackathon entry

Enter Agentic Payments & AI and opt in to Best use of Arc. The proposed testnet milestone is to pay each sample fee in test USDC, verify the returned rows, and buy only when the estimated utility covers the price and gas within the buyer's remaining budget. Link confirmed transaction hashes to the corresponding listing and receipt. Document the contracts used, decision rule, seller allowlist and spending limits. The current demo uses simulated credits.

The track and Arc awards can stack ($2,000 and $1,000), alongside an overall award and qualifying bounties. Solana is an alternative chain award ($1,500). Teams select one chain award. Submit a public repo, working demo, technical README and 2–3 minute video by November 20 at noon Central. Finalists must attend the November 21 closing ceremony in person for prizes. [Official guide](https://docs.google.com/document/d/1QaySCo7u3VxMVNdk3C5Ab3ewc2E46AuLntti-Uzx5EY/edit) · [Devpost](https://ubc-hackathon-2026.devpost.com/)
