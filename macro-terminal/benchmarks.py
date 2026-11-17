"""Benchmarks (beta): a firm's benchmark lines rebuilt from ETF total returns, over the periods a performance report uses.

Free sources do not carry Bloomberg, MSCI or Russell index returns, so each line stands in with the ETF that tracks it
(or the index itself where Yahoo has it), using dividend-adjusted closes. Blends rebalance to their weights each month.
Periods follow the firm report they were checked against (see period_returns), so the figures line up with it.

To remove the beta: delete this file and static/benchmarks.js, then the lines marked "benchmarks (beta)" in
macro_terminal.py, static/index.html and static/app.js.
"""
import bisect
from datetime import date, timedelta

PERIODS = ["1 day", "1 week", "MTD", "QTD", "YTD", "1 year", "3 years", "5 years", "10 years"]
AS_OF_DAYS = 30  # trading days of history kept, so an upload dated a few weeks back can still be compared

# (category, name as it appears in the firm's report, parts, note). A part is a ticker or another line's name, with a
# weight. Names match the report so an uploaded table lines up with these rows.
EAFE_CANADA = "MSCI EAFE + Canada"
LINES = [
    ("Equity", "75% US Equity / 25% Non-US Equity",
     [("70% S&P 500 / 30% Russell 2500", 0.75), ("80% MSCI EAFE + Canada / 20% MSCI EM", 0.25)], None),
    ("US Equity", "70% S&P 500 / 30% Russell 2500", [("S&P 500 (TR)", 0.70), ("Russell 2500 TR USD", 0.30)], None),
    ("US Large Cap", "S&P 500 (TR)", [("^SP500TR", 1)], "The index itself, with dividends."),
    ("US Smid Cap", "Russell 2500 TR USD", [("SMMD", 1)], "iShares Russell 2500 ETF. Launched July 2017, so no 10-year figure yet."),
    ("US Real Estate", "DJ US Select REIT TR USD", [("RWR", 1)], "SPDR Dow Jones REIT ETF, which tracks the capped version of the index."),
    ("Non-US Equity", "80% MSCI EAFE + Canada / 20% MSCI EM", [(EAFE_CANADA, 0.80), ("MSCI EM NR USD", 0.20)], None),
    ("International Developed", "iShares MSCI EAFE ETF", [("EFA", 1)], "The ETF itself."),
    ("International Developed", "MSCI EAFE Small Cap NR USD", [("SCZ", 1)], "iShares MSCI EAFE Small-Cap ETF."),
    ("Emerging", "MSCI EM NR USD", [("EEM", 1)], "iShares MSCI Emerging Markets ETF."),
    ("Fixed Income", "70% Agg / 15% Short/ 15% Intl",
     [("Bloomberg US Agg Bond TR USD", 0.70), ("Bloomberg Short Treasury TR USD", 0.15), ("Bloomberg Gbl Agg Ex USD TR USD", 0.15)], None),
    ("Aggregate Fixed", "Bloomberg US Agg Bond TR USD", [("AGG", 1)], "iShares Core US Aggregate Bond ETF."),
    ("Short Duration Fixed", "Bloomberg Short Treasury TR USD", [("SHV", 1)], "iShares Short Treasury Bond ETF, an ICE index over the same maturities."),
    ("Long Duration Treasury", "Bloomberg US Treasury 20+ Yr TR USD", [("TLT", 1)], "iShares 20+ Year Treasury Bond ETF, an ICE index over the same maturities."),
    ("High Yield", "Bloomberg High Yield Corporate TR USD", [("JNK", 1)], "SPDR Bloomberg High Yield Bond ETF, the index's more liquid subset."),
    ("EM Debt - Hard", "iShares JP Morgan USD Em Mkts Bd ETF", [("EMB", 1)], "The ETF itself."),
    ("EM Debt - Local", "VanEck JPMorgan EMLcl Ccy Bd ETF", [("EMLC", 1)], "The ETF itself."),
    ("International Fixed", "Bloomberg Gbl Agg Ex USD TR USD", [("BWX", 1)],
     "SPDR Bloomberg International Treasury Bond ETF: unhedged like the index, but government bonds only."),
    ("Muni Fixed", "70% Muni / 15% Short Muni / 15% Intl",
     [("Bloomberg Municipal TR USD", 0.70), ("Bloomberg Muni 1-5 Yr Blend(1-6) TR USD", 0.15), ("Bloomberg Gbl Agg Ex USD TR USD", 0.15)], None),
    ("Municipal", "Bloomberg Municipal TR USD", [("TFI", 1)], "SPDR Nuveen Bloomberg Municipal Bond ETF, 1-25 year bonds."),
    ("Municipal Short Term", "Bloomberg Muni 1-5 Yr Blend(1-6) TR USD", [("SHM", 1)], "SPDR Nuveen short-term muni ETF, an ICE 1-5 year index."),
]
# Not a row in the report, only a building block. shortcut: Canada at a fixed 11% share of EAFE + Canada, roughly its
# weight in MSCI World ex USA; it drifts with markets, so check the gap on the 80/20 line.
PARTS = {EAFE_CANADA: [("EFA", 0.89), ("EWC", 0.11)]}

BY_NAME = {name: parts for _, name, parts, _ in LINES}
BY_NAME.update(PARTS)


def flatten(parts, scale=1.0):
    """Nested blends -> {ticker: weight}. Every blend rebalances at the same month-ends, so nesting adds nothing."""
    out = {}
    for part, weight in parts:
        inner = flatten(BY_NAME[part], scale * weight) if part in BY_NAME else {part: scale * weight}
        for ticker, w in inner.items():
            out[ticker] = out.get(ticker, 0) + w
    return out


TICKERS = sorted({t for _, _, parts, _ in LINES for t in flatten(parts)})


def blend(series, weights):
    """Monthly-rebalanced index from daily closes, on the dates every part shares. series: {ticker: (dates, closes)}."""
    shared = set.intersection(*(set(series[t][0]) for t in weights))
    dates = sorted(shared)
    if not dates:
        return [], []
    close = {t: dict(zip(*series[t])) for t in weights}
    level, out, anchor, start = 100.0, [], dates[0], 100.0
    for d in dates:
        if (d.year, d.month) != (anchor.year, anchor.month):  # first day of a new month: rebalance at last month's close
            start = out[-1]
            anchor = prev
        level = start * sum(w * close[t][d] / close[t][anchor] for t, w in weights.items())
        out.append(level)
        prev = d
    return dates, out


def years_back(d, n):
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 29 February
        return d.replace(year=d.year - n, day=28)


def month_end_before(d):
    return date(d.year, d.month, 1) - timedelta(days=1)


def period_returns(dates, vals, i):
    """Returns in percent at dates[i] for each of PERIODS, measured from the close on or before each start date.

    Matches the firm report (checked on the funds that are their own benchmark, within 0.05 points on average): 1, 3,
    5 and 10 years start at the month-end before the date that many years back, so "1 year" on 16 November runs from
    31 October a year earlier. 1 year is cumulative; longer periods are annualised over the actual time elapsed."""
    d = dates[i]

    def ret(start, annualise=False):
        j = bisect.bisect_right(dates, start) - 1
        if j < 0:  # history does not reach back far enough: no figure rather than a wrong one
            return None
        r = vals[i] / vals[j]
        return round(((r ** (365.25 / (d - start).days) if annualise else r) - 1) * 100, 2)

    quarter = date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    return [ret(dates[i - 1]) if i else None, ret(d - timedelta(days=7)), ret(month_end_before(d)),
            ret(quarter - timedelta(days=1)), ret(date(d.year, 1, 1) - timedelta(days=1)),
            ret(month_end_before(years_back(d, 1)))] + [ret(month_end_before(years_back(d, n)), True) for n in (3, 5, 10)]


def build(closes):
    """closes: {ticker: [[iso date, adjusted close], ...]}. Lines whose prices are missing come back empty, not wrong."""
    series = {t: ([date.fromisoformat(d) for d, _ in rows], [c for _, c in rows]) for t, rows in closes.items() if rows}
    lines, all_dates = [], set()
    for category, name, parts, note in LINES:
        weights = flatten(parts)
        missing = sorted(t for t in weights if t not in series)
        row = dict(category=category, name=name, blend=len(parts) > 1, note=note, returns={},
                   source=" + ".join("%g%% %s" % (round(w * 100, 1), t) for t, w in sorted(weights.items(), key=lambda x: -x[1]))
                   if len(weights) > 1 else next(iter(weights)), missing=missing)
        if not missing:
            dates, vals = blend(series, weights)
            for i in range(max(1, len(dates) - AS_OF_DAYS), len(dates)):
                row["returns"][dates[i].isoformat()] = period_returns(dates, vals, i)
            all_dates.update(row["returns"])
        lines.append(row)
    return dict(periods=PERIODS, dates=sorted(all_dates), lines=lines) if all_dates else None
