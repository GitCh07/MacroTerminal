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

## Replays

Board, Rates and Benchmarks each end with a closed section. Nothing for it loads until you open it, so the
terminal loads as it did before the replays existed. Opening one loads that chart only, drawn on the latest
month; press Play to run it month by month. A section you leave open stays open next time.

- Rates, "Yield curve over time": the Treasury curve from 1982 (monthly averages of DGS1MO to DGS30, the current
  month averaged over its days so far), with the six months before it as fading trails, a dashed curve from a
  chosen time earlier, and a scale for the whole history or the last 10 years. Also a 3D surface and a heatmap,
  and the 10Y-2Y and 10Y-3M spreads with inversions shaded. A maturity Treasury did not publish that month is
  left out with a note, never filled in, and so is the 30-year from February 2002 to February 2006, when FRED
  carries only Treasury's estimate of it.
- Board, "How the bias got here": each market's score split into what growth, jobs, inflation and liquidity
  added, for the last 60 month-ends, and a market by month heatmap. Built with the board's own scoring code on
  the figures as they were published at each month-end (FRED's ALFRED archive), so a past month shows the read
  the board would have given then. The last frame is today's board.
- Benchmarks, "Your returns vs. benchmarks over time": paste a return history (a date column, then period
  returns in % per series, monthly or longer) to see its rolling 12-month excess return, growth of 100 and
  up/down capture against up to four benchmark stand-ins. The figures stay in your browser; Caerus columns are
  dropped.

Every replay has play/pause, speed and a date slider, and stops drawing when it is closed, scrolled out of view
or the tab is hidden. An open replay reloads itself when the terminal takes in new data. They are labelled
"Historical replay · not a forecast."

The frames are written to `static/viz/data/*.json` by `viz_frames.py`: by the hosted build right after the
snapshot, and locally in the background after Refresh, so Refresh is no slower. Run locally, press Refresh once
to build them. The replay page lives in `static/viz/` with its own styles and code, loaded in a frame;
`static/viz/components.js` takes frames plus axis settings and can be reused elsewhere.

To remove the replays: delete `viz_frames.py`, `test_viz_frames.py` and `static/viz/`, then the lines marked
"replays" in `macro_terminal.py`, `static/index.html` and `static/app.css`.

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
    python3 test_benchmarks.py
    python3 test_viz_frames.py

Runs offline on synthetic data: the scoring maths, the snapshot build and the server.
