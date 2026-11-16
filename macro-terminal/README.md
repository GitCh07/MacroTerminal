# Macro Terminal

A local read of US macro data from FRED: 21 indicators scored for direction, rolled into a bias for six markets,
with a chart snapshot (credit ladder, curve slope, recession odds, term premium), how the current regime has
tended to play out, last month's sector moves, the post-midterm history of the S&P 500 and the latest from the Fed.

## Run it

1. Put your FRED key in a file named `.env` in this folder (copy the one from your macro dashboard folder, it is the same format):

       FRED_API_KEY=yourkey

2. Start it:

       python3 macro_terminal.py

   It opens http://127.0.0.1:8765 in your browser. Ctrl+C in Terminal stops it.

The core needs no packages. Two panels are optional: the midterm history and the sector moves read prices
through yfinance (`python3 -m pip install yfinance`, already in your macro-env). Without it those panels say so
and everything else works.

Data is cached in `cache.json` for 6 hours; the Refresh button pulls it again.
Keep `.env` out of any GitHub repo.

## Change it

Everything tunable is at the top of `macro_terminal.py`:

- `FACTORS`: the indicators, their FRED series IDs and which way each one counts
- `MARKETS`: how each market weighs growth, jobs, inflation and liquidity
- `THRESHOLD`, `WINDOWS`: how far a pace has to move before it scores
- `CHART_EXTRAS`: extra charts on the Snapshot tab, including the toggle views inside the credit and curve cards
- `LEANINGS`: the one-line notes shown for each regime

Chart choices on the Snapshot tab and the "since last visit" baseline are remembered in your browser.

The Method tab in the app explains the scoring and lists any series that failed to load.

## Test it

    python3 test_macro_terminal.py

Runs offline on synthetic data: the scoring maths, the snapshot build and the server.
