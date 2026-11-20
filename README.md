# Proofdesk

**A verifiable preview for agent data purchases.**

An agent considering a data purchase needs a way to judge whether the data is useful before committing its budget. Some sellers price access as a larger order or package, making a small independent purchase difficult. A seller-provided preview can help, but a hand-picked sample may give a misleading view of the full listing.

Proofdesk coordinates a paid preview whose rows are selected after the seller commits to the dataset. The buyer verifies that the delivered rows belong to that commitment, evaluates their usefulness for its own task, and decides whether the remaining data is worth the price. The approach is intended for different kinds of sellers, data, and agents. The current implementation demonstrates a buyer forecasting Bitcoin price ranges using a fixed 64-row dataset.

## Try the demo

**Requirements:** Python 3 and a modern desktop browser with JavaScript enabled. The Python server uses only the standard library. The interactive replay needs no API key, wallet, testnet funds, or internet connection.

1. Clone or download this repository and open a terminal in its root directory.
2. Start the local server:

   ```sh
   python3 desk.py
   ```

3. Open **[http://127.0.0.1:8765/btc](http://127.0.0.1:8765/btc)**.
4. Click **Verify the preview**. The app reproduces the recorded selection and verifies all eight rows. The buyer recommends buying when its estimated value for the other 56 hours is **28.3¢**, compared with **10.1¢** for the offer and quoted gas.
5. Click **Change one delivered value**, select **#38**, change **191** to **195**, and click **Verify again**. The row fails its Merkle proof and the buyer blocks the purchase before valuation.
6. Expand **View proof & receipt** to inspect the commitment and links to the testnet evidence. Press Ctrl+C in the terminal to stop the server.

[Watch the narrated demo video (2:07)](proofdesk-demo-compatible.mp4).

The screen is an interactive **replay of a recorded Arc Testnet preview**, with verification and the row edit performed in the browser. It does not send a new transaction. The seller's 64 hourly examples are derived from public Coinbase BTC–USD candles, which stand in for a proprietary seller dataset. The preview payment settled on testnet. The full purchase is a recommendation and unsigned payment request, not a completed transaction.

## How it works

1. **Commit.** The seller freezes 64 ordered rows and hashes each indexed row into a SHA-256 Merkle tree. The seller publishes the 32-byte root in an Arc Testnet transaction before the preview is selected.
2. **Pay and draw.** The buyer pays **0.01 test USDC** plus gas for the preview. A deterministic draw combines the listing root, the payment transaction hash, and the hash of the finalized block two heights after the payment. It selects eight distinct positions. The future block makes the selected positions harder to predict before the seller commits.
3. **Deliver and verify.** The seller's authenticated API provides the selected rows and their Merkle paths to the buyer. The buyer independently reproduces the draw and uses each row and its six sibling hashes to reconstruct the committed root. It rejects altered rows or incorrect positions. Adjacent sampled BTC rows also undergo a consistency check.
4. **Evaluate.** The buyer retains the eight verified rows and estimates the value of the other 56 using historical forecasting experiments. The live buyer checks affordability through Arc's USDC contract and compares the estimate with the full listing price plus quoted gas and its remaining budget. When the estimate exceeds the cost and the budget covers it, the buyer produces an unsigned wallet request. A signer must authorize the transaction.

The Merkle check establishes that a delivered row matches the committed listing. The sample draw reduces the seller's ability to hand-select rows after the commitment. The buyer still evaluates whether the sample is useful for its own task.

## Technology and blockchain components

| Component | How Proofdesk uses it |
| --- | --- |
| **Arc Testnet and USDC contract** | The seller anchors the listing root and a full-price offer in transaction input data. The buyer pays the preview fee with native test USDC. For a live purchase decision, the buyer also reads the existing USDC contract's `balanceOf` to check affordability, and checks native balance for gas. Arc records provide replayable payment and draw evidence. |
| **Merkle tree and SHA-256** | A 64-leaf tree commits to the ordered dataset. Six sibling hashes per preview row allow the buyer to check membership without receiving the other rows. Hashing and verification run offchain. |
| **QuickNode Streams** | A historical Arc Testnet block stream delivers the preview payment and the later draw block. The buyer processes the saved stream deliveries and independently checks them against Arc RPC. |
| **Buyer and seller services** | Python implements the authenticated seller API, Arc receipt verification, draw, buyer budget checks, and forecasting-based valuation. The demo's buyer uses a task-specific heuristic and does not require an LLM. |
| **Browser demo** | HTML, CSS, and JavaScript replay the recorded flow and verify sample proofs locally using the browser's Web Crypto API. |
| **Coinbase Exchange data** | Public hourly BTC–USD candles provide a reproducible example dataset for the seller and forecasting task. Coinbase is the data source, while QuickNode supplies onchain events. |

### Arc evidence

The recorded preview uses native transfers and tagged transaction input data between externally owned accounts. The live buyer also calls Arc's existing USDC contract to check the buyer's balance before preparing a full purchase. Proofdesk does not deploy its own contract. The wallet request requires an external signer.

- **Network:** Arc Testnet, chain ID **5042002**.
- **USDC contract used:** [`0x3600000000000000000000000000000000000000`](https://testnet.arcscan.app/address/0x3600000000000000000000000000000000000000). In [`btc_buyer.py`](btc_buyer.py), the live `decide` flow calls `balanceOf(buyer)` using `eth_call` and checks that the balance covers the offer. It uses the native balance separately for the price-plus-gas and budget check. These are two views of the same USDC balance, not separate funds. The contract reports six decimal places and the native interface reports eighteen. The browser replay and recorded transaction evidence predate this balance check.
- **Seller account:** [`0xbdaf6907e159e633939e9db63adc35b2045db61f`](https://testnet.arcscan.app/address/0xbdaf6907e159e633939e9db63adc35b2045db61f).
- **Buyer account:** [`0x565ff030eba37c58a595118f3cc6a3d341b6b414`](https://testnet.arcscan.app/address/0x565ff030eba37c58a595118f3cc6a3d341b6b414).
- **Onchain records:** [listing commitment](https://testnet.arcscan.app/tx/0xd334d50ff26656d8891d5990cffe9c60e1591949d51c7cf72a0f1c070c1889b1), [full-price offer](https://testnet.arcscan.app/tx/0x4f344944b484f2b9ec4dce47c1dfe69e656210652c730f1335880d5278d7103c), and [preview payment](https://testnet.arcscan.app/tx/0x19a8667c21d519f9716aa748658799763125aa0946001907290d828cbfbd956b).
- **Recorded draw and decision:** [`examples/arc-btc-decision.json`](examples/arc-btc-decision.json). The preview payment settled in block **73,152,620**. Block **73,152,622** supplied the future block hash. The preview cost **0.01 test USDC**, plus **0.000573 test USDC** in gas.

To read the recorded buyer account's current contract balance independently, send this read-only request. It requires internet access and returns a hexadecimal 32-byte integer in six-decimal USDC units:

```sh
curl --fail --silent --show-error https://rpc.testnet.arc.io \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x3600000000000000000000000000000000000000","data":"0x70a08231000000000000000000000000565ff030eba37c58a595118f3cc6a3d341b6b414"},"pending"]}'
```

### QuickNode Streams configuration

The recorded BTC preview uses a historical Stream as an onchain data source for discovering the payment and reconstructing the draw.

| Setting | Configuration |
| --- | --- |
| Network and dataset | Arc Testnet, **Block** |
| Range | Blocks **73,152,620–73,152,622**, inclusive |
| Filter | [`quicknode_filter.js`](quicknode_filter.js) retains each block number and hash, and extracts transactions with the sample request tag, listing reference, and exact 0.01 test-USDC value. Retaining the later block even when it contains no matching payment supplies the draw hash. |
| Destination | An HTTPS webhook received one block per delivery. The temporary webhook has been closed. The three captured bodies are available in [`examples/quicknode-btc-stream/`](examples/quicknode-btc-stream/). |
| Purpose | The buyer identifies the recorded paid request and later block from stream deliveries, then independently verifies the chain evidence and computes the same eight positions. |

[QuickNode Stream configuration](https://dashboard.quicknode.com/streams/1ca9b32c-e4aa-4ef5-9a67-01e9bb273acf)

To reproduce the recorded draw from the saved deliveries, run the following from the repository root. This performs read-only Arc RPC calls and requires internet access and a Python installation configured to trust HTTPS certificates.

```sh
python3 quicknode_draw.py \
  --seller 0xbdaf6907e159e633939e9db63adc35b2045db61f \
  --buyer 0x565ff030eba37c58a595118f3cc6a3d341b6b414 \
  --listing-tx 0xd334d50ff26656d8891d5990cffe9c60e1591949d51c7cf72a0f1c070c1889b1 \
  examples/quicknode-btc-stream/*.json
```

The recorded selection is **50, 53, 60, 47, 38, 55, 63, 49**.

If a macOS Python installation reports a certificate verification error for the RPC, configure its trusted certificates. On a system with `/etc/ssl/cert.pem`, you can prefix the command with `SSL_CERT_FILE=/etc/ssl/cert.pem`.

## Decision controls and current scope

The buyer verifies the listing, payment, draw, sample proofs, and offer before valuation. In the live decision flow it reads the existing USDC contract balance, then checks the native balance and configured remaining budget against the offer and estimated gas. A proof failure blocks valuation. A positive recommendation prepares an unsigned request rather than signing or sending a purchase automatically.

The current buyer estimates the incremental value of the other rows by comparing forecast error across historical windows. Its value depends on the buyer's configured reward per basis point and may differ from the eventual result. The eight preview rows remain available to the buyer even when it passes on the full listing.

The testnet preview, commitment, and offer are recorded onchain. The seller service, proof verification, selection calculation, and valuation run offchain. The BTC replay is a single example of the broader data-market workflow. The current prototype has no settled full purchase, and its future-block randomness can be influenced by a block proposer. A seller can withhold delivery, while repeated previews can disclose more of a listing.

Next steps include completing and evaluating a full purchase, adding delivery or refund guarantees, limiting repeated disclosure, strengthening the randomness source, and supporting additional dataset schemas and buyer tasks.

## Hackathon submission

- **Recommended main track:** Agentic Payments and AI. The buyer reads onchain evidence, evaluates a paid data preview, applies a budget, and prepares a payment request.
- **Chain award:** Best use of Arc. Proofdesk's recorded commitment, offer, preview payment, and draw use Arc Testnet. The live buyer uses the existing USDC contract at the address listed above. The recorded preview used native transfers between externally owned accounts.
- **Sponsor bounty:** Best Use of QuickNode Streams. The Stream, filter, webhook destination, captured deliveries, and purpose are documented above.

The [hackathon guide](https://docs.google.com/document/d/1QaySCo7u3VxMVNdk3C5Ab3ewc2E46AuLntti-Uzx5EY/edit) permits **one main track**, **one chain award**, and any qualifying bounties. Consumer Applications has a working frontend and blockchain interaction, though the project is aimed at agent commerce. The DeFi track requires smart-contract interaction, which the recorded native-transfer flow does not demonstrate. ElevenLabs generated narration for the demo video, but audio is not a core Proofdesk product feature.

## Run the tests

```sh
python3 -B -m unittest discover -q
node test_showdown_core.js
node test_quicknode_filter.js
```

The Python suite runs local tests with fixture evidence. Node.js is only needed for the JavaScript tests, not for running the demo.
