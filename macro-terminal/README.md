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

It refreshes itself while running: weekdays at 8:37 AM, 10:07 AM and 5:07 PM New York time, just after the
main releases land, and on start-up or wake if it missed one. An open page checks back every five minutes and
when you return to the tab. The Refresh button pulls everything now. Data is kept in `cache.json`.

## Benchmarks (beta)

The Benchmarks tab rebuilds the benchmark lines from ETF total returns (via yfinance) and can compare them with
your own figures: paste the table from your report, or choose a CSV. Pasted figures are read and kept in your
browser only, never sent anywhere or written to this repo, and lines named Caerus are dropped. The Gap view shows
how far each stand-in is from your figures. Periods follow the firm report it was checked against: 1, 3, 5 and
10 years start at the month-end before the date that many years back.

To remove the beta: delete `benchmarks.py`, `test_benchmarks.py` and `static/benchmarks.js`, then the lines marked
"benchmarks (beta)" in `macro_terminal.py`, `static/index.html`, `static/app.js` and `test_macro_terminal.py`.
The terminal runs and its tests pass without them.

## Hosted copy (GitHub Pages)

`.github/workflows/pages.yml` rebuilds the data on GitHub's servers at the same weekday times, with the
`FRED_API_KEY` repo secret, and publishes the page. No laptop needed. GitHub can start scheduled runs late,
and stops them in a repo with no activity for 60 days. To refresh by hand: Actions tab, "Publish to GitHub
Pages", Run workflow. To change the times, edit `REFRESH_AT` in `macro_terminal.py` and the three cron lines
in the workflow together (a test checks they match).
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
