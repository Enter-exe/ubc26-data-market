# Proofdesk demo video

[Watch the finished walkthrough (2:07, captioned MP4)](proofdesk-demo-compatible.mp4)

The recording opens on the BTC listing. At **0:06** the vendor example establishes the purchase minimum. At **0:27** it explains the Merkle tree, committed root, proof path and future-block draw. At **1:06** the walkthrough verifies the preview. At **1:13** the agent prices the remaining hours. At **1:29** the presenter edits row 38, and at **1:37** the proof fails and the agent blocks the purchase. At **1:50** the video explains how the approach extends to other data and agents, and what a proof establishes.

## Live presentation script

Allow 90 seconds with pauses for the audience. Open the [BTC demo](showdown.html) on its initial screen and keep a second tab ready with the [Tick Data Store](https://www.tickdata.com/tickdatastore) minimum-order paragraph.

| Time | Picture and action | Spoken script |
| --- | --- | --- |
| 0:00–0:15 | Frame the vendor’s $1,000 minimum alongside its custom-date-range option. Cut to the BTC listing. | “Why can’t an agent just buy eight hours of data and try it? Sometimes it can. But even if you choose your own date range, this historical data vendor sets a thousand-dollar minimum on your first order.” |
| 0:15–0:30 | Show the 64 neutral squares. Keep the buyer panel in frame. | “A preview could help you decide. But who picked the examples? Here, public Bitcoin data stands in for a proprietary archive. The seller committed to all 64 hourly records before it knew which eight the buyer would get.” |
| 0:30–0:45 | Click **Verify the preview**. Follow the selected squares, then hold on the verified count. Briefly overlay the preview receipt. | “Our buyer already paid one cent in test USDC, plus gas. Two Arc blocks later, the draw selected eight positions. This browser just reproduced the selection and checked each delivered row against the seller’s original commitment.” |
| 0:45–1:00 | Frame the estimated value and cost together. | “All eight match. The agent keeps those rows. Based on past forecasting runs, it values the *other* 56 at about 28 cents. Buying them costs about ten cents with gas, so it recommends buying. Only the preview payment settled.” |
| 1:00–1:15 | Click **Change one delivered value**. Choose row **#38**, read its original range, then enter a different whole number. Click **Verify again**. | “Let’s see whether that check actually does anything. I’ll change the delivered price range for row 38. Same seller commitment, same eight positions. Let’s check them again.” |
| 1:15–1:30 | Hold on the failed row and the original and edited verdicts. | “Seven still match. Row 38 fails, so the agent stops before it prices the archive. The buyer still has to judge whether the data is useful. Now it can tell whether the trial it judged came from the archive on offer.” |

## Recording notes

- Frame the page so the verdict, both prices and failed-row number are legible at playback size. Pause after **Verify again** so the audience can read the comparison.
- Keep **Arc Testnet replay** visible and caption the receipt “Recorded preview payment.” The edit happens locally during the demo.
- The vendor example illustrates a real purchase minimum. The demo seller is independent. If asked why a seller would offer a preview, the premise is that a limited trial could help close a larger sale. Repeated sampling remains an open seller-policy question.

## Evidence for captions

- Tick Data lists a $1,000 new-customer minimum and supports custom date ranges. [Tick Data Store](https://www.tickdata.com/tickdatastore)
- The recorded buyer paid 0.01 test USDC for the preview plus 0.000573 in gas. [Arc Testnet preview payment](https://testnet.arcscan.app/tx/0x19a8667c21d519f9716aa748658799763125aa0946001907290d828cbfbd956b)
- The estimated additional value was 0.2828125 test USDC. The price plus quoted gas was 0.1005834 test USDC. [Recorded BTC buyer decision](examples/arc-btc-decision.json)
