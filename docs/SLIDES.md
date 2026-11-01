# Pitch deck

**File:** [Minimol_Storage_Pitch.pptx](Minimol_Storage_Pitch.pptx), 15 slides, 16:9. Speaker notes are on every slide.

**Rebuilding:** the deck is generated from [deck/build_deck.js](deck/build_deck.js).
- Edit the script, not the .pptx, so numbers stay in sync with [RESULTS.md](RESULTS.md).
- Rebuild with:
  ```bash
  cd docs/deck && npm ci && npm run build
  ```
- When the multi-laptop numbers arrive, update the figures in the script and rebuild.

**Design:** it follows gdgc.hackmol.com.
- The four Google colours: blue `#4285F4`, red `#EA4335`, yellow `#FBBC05`, green `#34A853`.
- Dark `#222222` headings with one accent-coloured phrase.
- A faint grid on white, and rounded blocks with a dark outline.
- Icons sit in white circles. Coloured dots replace bullets.
- Fonts are Arial, so the deck looks the same on every laptop.

## Outline and timing (about 5 minutes with the live demo)

| # | Title | Message | Evidence on the slide | Time |
|---|---|---|---|---|
| 1 | Store. Survive. Heal. | What it is in one breath | 4-block motif | 0:20 |
| 2 | Your cloud has one owner | The problem | 3 problem cards | 0:20 |
| 3 | One program on every laptop | The 4 pillars | 2×2 colour blocks | 0:20 |
| 4 | How a file travels | Pipeline order and why | 6-step flow | 0:20 |
| 5 | No server. Every node is equal | Architecture | Mesh diagram + node layers | 0:20 |
| 6 | Slow peers get no new chunks | Placement works | Chart: copies per node, 0% vs 21.7% | live |
| 7 | Downloads ask the fastest holder | Retrieval works | Chart: 0.146 s vs 1.697 s, 11.6× | live |
| 8 | Kill a node. Watch it heal | Self-repair | Timeline, detection and repair times, 27/27 | live |
| 9 | Change 1%, send 1% | Delta sync | Chart: 0.19 MB of 20.2 MB | live |
| 10 | Lose your laptop, not your files | Keys and recovery | Flow + protections | live |
| 11 | Measured, not promised | All results at once | 6 stat tiles + conditions | 0:20 |
| 12 | Where we fit | Honest comparison | Table vs Drive, IPFS, Syncthing, Storj, Tahoe-LAFS | Q&A |
| 13 | What you'll see live | Demo plan | 8 numbered steps | before the demo |
| 14 | Honest limits, clear next steps | Limits → roadmap | Today vs Next | 0:20 |
| 15 | Store. Survive. Heal. | Close + questions | Team roles, repo | — |

Slides 6–10 can be shown during the live demo, or used as backup if a step fails.
