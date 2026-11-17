#!/usr/bin/env python3
"""Macro Terminal: a local read of US macro data from FRED, scored into a bias per market.

Run:   python3 macro_terminal.py        then open http://127.0.0.1:8765
Needs: a file named .env beside this script containing  FRED_API_KEY=yourkey
No packages to install. Everything you would tune is in the tables below.
"""
import bisect
import json
import os
import ssl
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import NormalDist
from xml.etree import ElementTree

try:  # benchmarks (beta): an optional module; delete benchmarks.py and the terminal runs without it
    import benchmarks
except ImportError:
    benchmarks = None

try:
    from zoneinfo import ZoneInfo
    NEW_YORK = ZoneInfo("America/New_York")
except Exception:  # shortcut: no time-zone database, so REFRESH_AT is read as this machine's local time
    NEW_YORK = None

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache.json"
PORT = 8765
# Weekday refresh times, New York time: just after the 8:30 and 10:00 releases, and once the day's rates have posted.
# Off the top of the hour, when GitHub's scheduler is busiest. Keep in step with .github/workflows/pages.yml.
REFRESH_AT = [(8, 37), (10, 7), (17, 7)]
RETRY_MINUTES = 15   # wait before trying again after a refresh fails
THRESHOLD = 0.5      # a factor scores once its pace gap passes half a typical move
MIN_HISTORY = 24     # gap observations needed before a factor is scored
CALENDAR_DAYS = 45

# Short window, long window (in observations) and days before a series counts as stale.
WINDOWS = {"d": (21, 252), "w": (4, 52), "m": (3, 12), "q": (1, 4)}
STALE_DAYS = {"d": 10, "w": 21, "m": 120, "q": 220}  # JOLTS and Michigan sentiment run about 100 days behind just before a release

# Group: (label, word when the score is positive, word when negative).
GROUPS = {
    "growth": ("Growth", "strengthening", "softening"),
    "labor": ("Jobs", "strengthening", "softening"),
    "inflation": ("Inflation", "heating", "cooling"),
    "liquidity": ("Liquidity and rates", "loosening", "tightening"),
}


def F(id, label, group, freq, kind, sign, unit, dp, scale, basis, why):
    return dict(id=id, label=label, group=group, freq=freq, kind=kind, sign=sign,
                unit=unit, dp=dp, scale=scale, basis=basis, why=why)


# kind: pct = annualised % change, diff = change per month, level = average level.
# sign: +1 when a rising reading pushes the group score up (stronger growth, stronger jobs,
# hotter inflation, looser conditions); -1 when it pushes it down.
FACTORS = [
    F("GDPC1", "Real GDP", "growth", "q", "pct", 1, "%", 1, 1, "q/q annualised",
      "The broadest measure of output. Late and revised, so it confirms a turn more than it signals one."),
    F("INDPRO", "Industrial production", "growth", "m", "pct", 1, "%", 1, 1, "y/y",
      "Hard output from factories, mines and utilities. The most cyclical part of the economy."),
    F("GACDFSA066MSFRBPHI", "Philly Fed manufacturing", "growth", "m", "level", 1, "", 1, 1, "diffusion index",
      "A timely survey of factory activity, above zero means more firms growing than shrinking. Regional, standing in for the ISM index that FRED does not carry."),
    F("GABNDIF066MSFRBPHI", "Philly Fed services", "growth", "m", "level", 1, "", 1, 1, "diffusion index",
      "Service firms on their own activity. Regional, standing in for the ISM services index. Services are most of US output."),
    F("RRSFS", "Real retail sales", "growth", "m", "pct", 1, "%", 1, 1, "y/y",
      "Goods spending after inflation. The consumer is about two thirds of GDP."),
    F("UMCSENT", "Consumer sentiment", "growth", "m", "level", 1, "", 1, 1, "index",
      "The University of Michigan survey of how households feel about their finances and the economy. Leads spending at turning points, noisy in between."),
    F("PAYEMS", "Nonfarm payrolls", "labor", "m", "diff", 1, "k", 0, 1, "monthly change",
      "Jobs added each month. The single most market-moving release."),
    F("UNRATE", "Unemployment rate", "labor", "m", "level", -1, "%", 1, 1, "rate",
      "Moves slowly, then quickly. A rise of half a point from its low has marked every recession since 1970."),
    F("ICSA", "Initial jobless claims", "labor", "w", "level", -1, "k", 0, 0.001, "weekly",
      "New unemployment filings. The timeliest read on layoffs, published every Thursday."),
    F("ADPMNUSNERSA", "ADP private payrolls", "labor", "m", "diff", 1, "k", 0, 0.001, "monthly change",
      "A private-sector count from payroll records. Arrives two days before the official report."),
    F("JTSJOL", "Job openings (JOLTS)", "labor", "m", "level", 1, "m", 2, 0.001, "openings",
      "Labor demand. Openings fall before hiring does."),
    F("CPIAUCSL", "CPI", "inflation", "m", "pct", 1, "%", 1, 1, "y/y",
      "Headline consumer prices. Drives real incomes and the public mood on inflation."),
    F("CPILFESL", "Core CPI", "inflation", "m", "pct", 1, "%", 1, 1, "y/y",
      "CPI without food and energy. A cleaner read on the underlying trend."),
    F("PPIFIS", "PPI final demand", "inflation", "m", "pct", 1, "%", 1, 1, "y/y",
      "Prices received by producers. Pipeline pressure that can reach consumers later."),
    F("PCEPI", "PCE price index", "inflation", "m", "pct", 1, "%", 1, 1, "y/y",
      "The Fed's 2% target is written in this index."),
    F("PCEPILFE", "Core PCE", "inflation", "m", "pct", 1, "%", 1, 1, "y/y",
      "The measure the Fed watches most closely when setting rates."),
    F("NFCI", "Financial conditions", "liquidity", "w", "level", -1, "", 2, 1, "index",
      "The Chicago Fed index: a blend of 105 measures of risk, credit and leverage. Below zero is looser than average."),
    F("BAA10Y", "Baa corporate spread", "liquidity", "d", "level", -1, "%", 2, 1, "over 10-year",
      "Moody's Baa bond yield minus the 10-year Treasury: the price of the lowest investment-grade credit. Widens when credit stress builds, and its history runs back decades."),
    F("DFII10", "10-year real yield", "liquidity", "d", "level", -1, "%", 2, 1, "yield",
      "The inflation-adjusted cost of long-term money. The discount rate behind growth stocks and gold."),
    F("DGS2", "2-year Treasury yield", "liquidity", "d", "level", -1, "%", 2, 1, "yield",
      "The market's view of where the Fed will be over the next two years."),
    F("DTWEXBGS", "Broad dollar index", "liquidity", "d", "level", -1, "", 1, 1, "index",
      "A stronger dollar tightens conditions for the rest of the world and for US multinationals."),
]

# How each market reads the four groups. Positive weight: a rising group score helps the market.
# These are judgement calls, kept in one place so you can argue with them.
MARKETS = [
    dict(id="spx", label="S&P 500", weights=dict(growth=1, labor=1, inflation=-1, liquidity=1), skip=[],
         note="Earnings follow growth and jobs. Hotter inflation keeps rates high, looser conditions lift multiples."),
    dict(id="ndx", label="Nasdaq 100", weights=dict(growth=1, labor=1, inflation=-1, liquidity=2), skip=[],
         note="Long-duration cash flows, so liquidity and real yields carry double weight."),
    dict(id="rut", label="Russell 2000", weights=dict(growth=2, labor=1, inflation=-1, liquidity=2), skip=[],
         note="Small caps are more cyclical and more dependent on credit, so growth and liquidity carry double weight."),
    dict(id="eafe", label="MSCI EAFE", weights=dict(growth=1, labor=0, inflation=-1, liquidity=1), skip=[],
         note="Developed markets outside North America, read through US data only: solid US demand, cooler US inflation and looser conditions, a weaker dollar among them, have tended to lift them in dollar terms. Their own growth and inflation are not in this read."),
    dict(id="em", label="MSCI EM", weights=dict(growth=1, labor=0, inflation=-1, liquidity=2), skip=[],
         note="Emerging markets, read through US data only. More exposed than developed markets to the dollar and to credit conditions, so liquidity carries double weight. Local growth and inflation are not in this read."),
    dict(id="ust", label="10-year Treasuries", weights=dict(growth=-1, labor=-1, inflation=-2, liquidity=0), skip=[],
         note="Read as bond prices. Strong activity and, above all, hotter inflation push yields up and prices down."),
    dict(id="agg", label="US Agg bonds", weights=dict(growth=-1, labor=-1, inflation=-2, liquidity=1), skip=[],
         note="Read as bond prices. Mostly Treasuries and agency mortgages, so it moves with rates; its corporate share also gains when credit spreads tighten and conditions loosen."),
    dict(id="usd", label="US dollar", weights=dict(growth=1, labor=1, inflation=1, liquidity=-1), skip=["DTWEXBGS"],
         note="A US-only read: strength and inflation at home mean a firmer Fed and higher US yields. Currencies are relative, so treat this as half the picture."),
    dict(id="gold", label="Gold", weights=dict(growth=-1, labor=0, inflation=1, liquidity=2), skip=[],
         note="Driven mostly by real yields and the dollar, with a bid from inflation and from weaker growth."),
]

CURVE = [("1M", "DGS1MO"), ("3M", "DGS3MO"), ("6M", "DGS6MO"), ("1Y", "DGS1"),
         ("2Y", "DGS2"), ("5Y", "DGS5"), ("10Y", "DGS10"), ("30Y", "DGS30")]
EXTRA = [s for _, s in CURVE] + ["DFEDTARL", "DFEDTARU", "T5YIFR", "MORTGAGE30US", "VIXCLS",
                                 "SAHMREALTIME", "RECPROUSM156N", "GDPNOW", "USREC", "T10Y3M", "T10Y2Y", "THREEFYTP10",
                                 "BAMLC0A3CA", "BAMLC0A4CBBB", "BAMLH0A1HYBB", "BAMLH0A0HYM2"]
LONG = ("BAA10Y", "T10Y3M", "T10Y2Y", "USREC")  # fetched back to 1980 so the Max range shows past cycles

# Extra charts on the Snapshot tab: id, label, unit, decimals, then the views a toggle switches between:
# (view name, source, note shown under the toggle). A source is one series (or a value computed in
# build_snapshot), or a list of (line name, series) drawn together on one axis.
ICE_NOTE = "ICE BofA index, ratings averaged across Moody's, S&P and Fitch. Spread over the whole Treasury curve. FRED keeps only three years."
CHART_EXTRAS = [
    ("credit", "Corporate credit spreads", "%", 2, [
        ("Baa", "BAA10Y", "Moody's Baa yield minus the 10-year Treasury, the lowest investment-grade rung (BBB on S&P's scale). Long bonds, long history."),
        ("Single-A", "BAMLC0A3CA", ICE_NOTE), ("BBB", "BAMLC0A4CBBB", ICE_NOTE), ("BB", "BAMLH0A1HYBB", ICE_NOTE),
        ("Ladder", [("BB", "BAMLH0A1HYBB"), ("BBB", "BAMLC0A4CBBB"), ("Single-A", "BAMLC0A3CA")],
         "One method on one axis, so the gaps are the price of each step down in quality. BB to BBB is the line between junk and investment grade. ICE BofA indices, of which FRED keeps only three years.")]),
    ("slope", "Yield curve slope", "%", 2, [
        ("Both", [("10-year minus 3-month", "10y3m"), ("10-year minus 2-year", "10y2y")], "Below zero the curve is inverted."),
        ("10Y minus 2Y", "10y2y", "Below zero the curve is inverted."),
        ("10Y minus 3M", "10y3m", "Below zero the curve is inverted. This is the slope the recession model reads.")]),
    ("recprob", "Recession probability, 12 months ahead", "%", 0, [
        ("level", "recprob", "New York Fed yield-curve model, on each month's average 10-year minus 3-month spread.")]),
    ("DGS10", "10-year Treasury yield", "%", 2, [("level", "DGS10", None)]),
    ("THREEFYTP10", "10-year term premium", "%", 2, [
        ("level", "THREEFYTP10", "Kim-Wright estimate from the Federal Reserve Board: the extra yield for holding a 10-year bond instead of rolling short bills.")]),
    ("breakeven", "10-year breakeven inflation", "%", 2, [("level", "breakeven", None)]),
    ("T5YIFR", "5-year, 5-year forward inflation", "%", 2, [("level", "T5YIFR", None)]),
    ("MORTGAGE30US", "30-year mortgage rate", "%", 2, [("level", "MORTGAGE30US", None)]),
    ("BAMLH0A0HYM2", "High-yield credit spread", "%", 2, [("level", "BAMLH0A0HYM2", ICE_NOTE)]),
    ("VIXCLS", "VIX", "", 1, [("level", "VIXCLS", None)]),
]
MONTHLY_CHARTS = ("recprob",)

# SPDR sector funds for the one-month return bars, with SPY as the market line.
SECTORS = {"XLK": "Technology", "XLC": "Communication Services", "XLY": "Consumer Discretionary", "XLF": "Financials",
           "XLI": "Industrials", "XLB": "Materials", "XLE": "Energy", "XLV": "Health Care", "XLP": "Consumer Staples",
           "XLU": "Utilities", "XLRE": "Real Estate", "SPY": "S&P 500"}

FED_FEEDS = [("Policy release", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
             ("Speech", "https://www.federalreserve.gov/feeds/speeches.xml")]

REGIMES = {  # (growth up, inflation up)
    (True, False): ("Goldilocks", "Activity is picking up while inflation cools. Historically the friendliest mix for stocks and bonds together."),
    (True, True): ("Reflation", "Activity and inflation are both picking up. Tends to favour cyclicals and commodities over bonds."),
    (False, True): ("Stagflation", "Activity is slowing while inflation picks up. The hardest mix for stocks and bonds together."),
    (False, False): ("Slowdown", "Activity and inflation are both cooling. Tends to favour bonds and defensive stocks."),
}

# What each phase has tended to look like, from the Merrill Lynch Investment Clock (Trevor Greetham).
# Regime: (the clock's own name for the phase, [(heading, one line)]). History described, nothing advised.
LEANINGS = {
    "Goldilocks": ("Recovery", [
        ("Asset classes", "Stocks have historically been the best asset class in this phase."),
        ("Equity leadership", "Cyclical growth has tended to lead, with rate-sensitive areas such as banks and consumer discretionary doing well early."),
        ("Rates", "Inflation is still falling, so policy tends to stay easy and long-duration assets hold up.")]),
    "Reflation": ("Overheat", [
        ("Asset classes", "Commodities have historically been the best asset class. Stocks still rise but lag the phase before."),
        ("Equity leadership", "Cyclical value has tended to lead, such as industrials and basic materials."),
        ("Rates", "Central banks lean against inflation, so yields tend to rise and the curve to flatten.")]),
    "Stagflation": ("Stagflation", [
        ("Asset classes", "Cash has historically held up best, with stocks and bonds both under pressure."),
        ("Equity leadership", "Defensive value has tended to lead."),
        ("Rates", "Policy tends to stay tight until inflation breaks, which has often inverted the curve.")]),
    "Slowdown": ("Reflation", [
        ("Asset classes", "Bonds have historically been the best asset class in this phase."),
        ("Equity leadership", "Defensive growth has tended to lead, and rate-sensitive areas start to respond as policy eases."),
        ("Rates", "Central banks cut, so yields tend to fall, short rates fastest, and the curve steepens.")]),
}


# ---------- the maths (pure functions, covered by test_macro_terminal.py) ----------

def parse(observations):
    """FRED observations -> (dates, values) ascending, with missing readings dropped."""
    rows = [(date.fromisoformat(o["date"]), float(o["value"])) for o in observations if o["value"] not in (".", "")]
    return [d for d, _ in rows], [v for _, v in rows]


def pace(dates, vals, i, n, kind):
    """The reading at index i measured over the previous n observations."""
    if kind == "level":
        return sum(vals[i - n + 1:i + 1]) / n
    # Real months between the two dates, so a skipped release (October 2025 CPI) does not distort the rate.
    months = (dates[i].year - dates[i - n].year) * 12 + dates[i].month - dates[i - n].month
    if kind == "pct":
        return ((vals[i] / vals[i - n]) ** (12 / months) - 1) * 100
    return (vals[i] - vals[i - n]) / months


def signal(dates, vals, freq, kind):
    """Short pace, long pace and how unusual the gap between them is against the last ten years."""
    short_n, long_n = WINDOWS[freq]
    start = max(long_n, bisect.bisect_left(dates, dates[-1] - timedelta(days=3653)))
    gaps = [pace(dates, vals, i, short_n, kind) - pace(dates, vals, i, long_n, kind) for i in range(start, len(vals))]
    if len(gaps) < MIN_HISTORY:
        return None
    mid = statistics.median(gaps)
    # Median absolute deviation, not standard deviation: 2020 would otherwise swamp every scale.
    typical = 1.4826 * statistics.median(abs(g - mid) for g in gaps)
    if typical == 0:
        return None
    last = len(vals) - 1
    return dict(short=pace(dates, vals, last, short_n, kind), long=pace(dates, vals, last, long_n, kind),
                z=gaps[-1] / typical)


def score(z, sign):
    return sign * ((z > THRESHOLD) - (z < -THRESHOLD))


def bias(s):
    if s >= 0.5:
        return "Very bullish"
    if s >= 0.2:
        return "Bullish"
    if s > -0.2:
        return "Neutral"
    if s > -0.5:
        return "Bearish"
    return "Very bearish"


def market_score(market, factors):
    """Weighted mean of group scores, from -1 to +1. Groups with nothing scored drop out."""
    total = weight_sum = 0
    groups = {}
    for g, w in market["weights"].items():
        scores = [f["score"] for f in factors if f["group"] == g and f["score"] is not None and f["id"] not in market["skip"]]
        if not scores or w == 0:
            continue
        mean = sum(scores) / len(scores)
        groups[g] = mean * w
        total += mean * w
        weight_sum += abs(w)
    return (total / weight_sum if weight_sum else 0), groups


def recession_probit(spread):
    """NY Fed yield-curve model (Estrella and Trubin 2006): chance of recession twelve months ahead."""
    return NormalDist().cdf(-0.5333 - 0.6330 * spread)


def asof(dates, vals, d):
    i = bisect.bisect_right(dates, d) - 1
    return vals[i] if i >= 0 else None


def combine(a, b):
    """a minus b on the dates both series share."""
    other = dict(zip(*b))
    rows = [(d, v - other[d]) for d, v in zip(*a) if d in other]
    return [d for d, _ in rows], [v for _, v in rows]


def thin(points):
    """A daily series keeps one point a week: plenty for a chart, and the latest is always kept."""
    return points[::-5][::-1] if len(points) > 1500 else points


def views_for(f, dates, vals):
    """Every way a series can be drawn. The first is the default and the one the tables quote."""
    k, kind = f["scale"], f["kind"]

    def rate(n, as_kind, scale=1):
        return [(dates[i], pace(dates, vals, i, n, as_kind) * scale) for i in range(n, len(vals))]

    level = [(d, v * k) for d, v in zip(dates, vals)]
    if kind == "level":
        out = [(f["basis"], f["unit"], f["dp"], level)]
    elif kind == "diff":
        out = [("monthly change", f["unit"], f["dp"], rate(1, "diff", k)), ("y/y", "%", 1, rate(12, "pct")),
               ("level", "m", 1, [(d, v / 1000) for d, v in level])]
    elif f["freq"] == "q":
        out = [("q/q annualised", "%", 1, rate(1, "pct")), ("y/y", "%", 1, rate(4, "pct")), ("level", "", 1, level)]
    else:
        out = [("y/y", "%", 1, rate(12, "pct")), ("3m annualised", "%", 1, rate(3, "pct")), ("level", "", 1, level)]
    return [dict(name=name, unit=unit, dp=dp, points=[[d.isoformat(), round(v, 4)] for d, v in thin(points)])
            for name, unit, dp, points in out]


def recession_ranges(dates, flags):
    """USREC months flagged 1 -> [first month, last month] pairs, for shading charts."""
    out, inside = [], False
    for d, v in zip(dates, flags):
        if v >= 0.5 and inside:
            out[-1][1] = d.isoformat()
        elif v >= 0.5:
            out.append([d.isoformat(), d.isoformat()])
        inside = v >= 0.5
    return out


def recession_history(dates, spreads):
    """Yield-curve recession chance through time: the probit on each month's average spread.
    The last point uses the latest 21 readings, so it equals the figure on the Board."""
    months = {}
    for d, v in zip(dates, spreads):
        months.setdefault(d.replace(day=1), []).append(v)
    out = [(m, recession_probit(statistics.mean(vs)) * 100) for m, vs in sorted(months.items())][:-1]
    out.append((dates[-1], recession_probit(statistics.mean(spreads[-21:])) * 100))
    return [d for d, _ in out], [v for _, v in out]


def sector_returns(closes):
    """One-month price return for each sector fund, best first, with the S&P 500 fund as the market line."""
    got = {}
    for symbol, rows in closes.items():
        dates, vals = [date.fromisoformat(d) for d, _ in rows], [c for _, c in rows]
        base = asof(dates, vals, dates[-1] - timedelta(days=30)) if dates else None
        if base:
            got[symbol] = (round((vals[-1] / base - 1) * 100, 2), rows[-1][0])
    sectors = sorted((dict(symbol=sym, label=SECTORS[sym], ret=ret) for sym, (ret, _) in got.items() if sym != "SPY"),
                     key=lambda r: -r["ret"])
    if not sectors:
        return None
    return dict(sectors=sectors, market=got["SPY"][0] if "SPY" in got else None, date=max(d for _, d in got.values()))


def election_day(year):
    """The Tuesday after the first Monday of November."""
    return next(date(year, 11, d) for d in range(2, 9) if date(year, 11, d).weekday() == 1)


def midterm_windows(dates, closes, today):
    """S&P 500 price return over the 12 months after each midterm since 1950, plus the window still running."""
    windows = []
    for year in range(1950, today.year + 1, 4):
        start = election_day(year)
        i0 = bisect.bisect_right(dates, start) - 1  # the NYSE shut on election days until 1968: use the close before
        if i0 < 0 or start > dates[-1]:
            continue
        end = start.replace(year=year + 1)
        i1 = bisect.bisect_right(dates, end) - 1
        base, peak, drop = closes[i0], closes[i0], 0.0
        for c in closes[i0:i1 + 1]:
            peak = max(peak, c)
            drop = min(drop, c / peak - 1)
        path = [round((asof(dates, closes, start + timedelta(days=7 * w)) / base - 1) * 100, 2)
                for w in range(53) if start + timedelta(days=7 * w) <= dates[-1]]
        windows.append(dict(year=year, date=start.isoformat(), complete=end <= dates[-1], days=(dates[i1] - start).days,
                            ret=round((closes[i1] / base - 1) * 100, 2), drawdown=round(drop * 100, 2), path=path))
    done = [w for w in windows if w["complete"]]
    if not done:
        return None
    rets = [w["ret"] for w in done]
    deepest = min(done, key=lambda w: w["drawdown"])
    stats = dict(n=len(done), positive=sum(r > 0 for r in rets), mean=round(statistics.mean(rets), 1),
                 median=round(statistics.median(rets), 1), low=min(rets), high=max(rets),
                 avg_drawdown=round(statistics.mean(w["drawdown"] for w in done), 1),
                 worst_drawdown=deepest["drawdown"], worst_year=deepest["year"],
                 avg_path=[round(statistics.mean(w["path"][i] for w in done), 2) for i in range(53)])
    return dict(windows=done, current=next((w for w in windows if not w["complete"]), None), stats=stats)


def parse_feed(xml, kind):
    """RSS -> items. Only links back to federalreserve.gov survive, so a feed can never plant another address."""
    items = []
    for item in ElementTree.fromstring(xml).iter("item"):
        link = (item.findtext("link") or "").strip()
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            when = None
        if link.startswith("https://www.federalreserve.gov/"):
            items.append(dict(kind=kind, title=" ".join((item.findtext("title") or "").split()), link=link, date=when))
    return items


# ---------- snapshot ----------

def build_factor(f, dates, vals, today):
    short_n, long_n = WINDOWS[f["freq"]]
    sig = signal(dates, vals, f["freq"], f["kind"]) if len(vals) > long_n else None
    stale = (today - dates[-1]).days > STALE_DAYS[f["freq"]]
    views = views_for(f, dates, vals)
    pk = f["scale"] if f["kind"] != "pct" else 1
    out = dict(f, date=dates[-1].isoformat(), stale=stale, views=views,
               value=views[0]["points"][-1][1] if views[0]["points"] else None,
               short=None, long=None, z=None, score=None)
    if sig:
        out.update(short=sig["short"] * pk, long=sig["long"] * pk, z=round(sig["z"], 2),
                   score=None if stale else score(sig["z"], f["sign"]))
    return out


def build_snapshot(raw, today):
    """raw: {"obs": {id: observations}, "errors": {id: message}, "release_of": {id: {id, name}}, "release_dates": {release_id: [dates]}}"""
    series = {sid: parse(obs) for sid, obs in raw["obs"].items()}
    series = {sid: s for sid, s in series.items() if s[0]}
    errors = dict(raw.get("errors", {}))

    factors = []
    for f in FACTORS:
        if f["id"] in series:
            factors.append(build_factor(f, *series[f["id"]], today))
        else:
            errors.setdefault(f["id"], "No observations returned")
            factors.append(dict(f, date=None, stale=True, value=None, views=[], short=None, long=None, z=None, score=None))

    groups = {}
    for g, (label, up, down) in GROUPS.items():
        scored = [f for f in factors if f["group"] == g and f["score"] is not None]
        net = sum(f["score"] for f in scored)
        groups[g] = dict(label=label, net=net, scored=len(scored), total=sum(f["group"] == g for f in factors),
                         up=sum(f["score"] > 0 for f in scored), down=sum(f["score"] < 0 for f in scored),
                         word=up if net > 0 else down if net < 0 else "steady", up_word=up, down_word=down)

    markets = []
    for m in MARKETS:
        s, by_group = market_score(m, factors)
        markets.append(dict(m, score=round(s, 3), bias=bias(s), groups=by_group))

    def momentum(names):
        zs = [max(-2, min(2, f["z"] * f["sign"])) for f in factors if f["group"] in names and f["score"] is not None]
        return sum(zs) / len(zs) if zs else None
    gx, iy = momentum(("growth", "labor")), momentum(("inflation",))
    regime = None
    if gx is not None and iy is not None:
        name, blurb = REGIMES[(gx > 0, iy > 0)]
        regime = dict(name=name, blurb=blurb, growth=round(gx, 2), inflation=round(iy, 2),
                      weak=abs(gx) < 0.25 and abs(iy) < 0.25, clock=LEANINGS[name][0], leanings=LEANINGS[name][1])

    def latest(sid):
        return dict(date=series[sid][0][-1].isoformat(), value=series[sid][1][-1]) if sid in series else None

    recession = dict(sahm=latest("SAHMREALTIME"), smoothed=latest("RECPROUSM156N"), curve=None)
    rates = dict(curve=None, board=[], target=None)
    computed = dict(series)
    if "DGS10" in series:
        d10 = series["DGS10"]
        now = d10[0][-1]
        marks = {"now": now, "three_months": now - timedelta(days=91), "one_year": now - timedelta(days=365)}
        rates["curve"] = dict(
            tenors=[t for t, sid in CURVE if sid in series],
            dates={k: v.isoformat() for k, v in marks.items()},
            **{k: [asof(*series[sid], d) for _, sid in CURVE if sid in series] for k, d in marks.items()})
        # FRED's own spread series carry the long history; the subtraction is the fallback if one fails.
        if "DGS2" in series:
            computed["10y2y"] = series.get("T10Y2Y") or combine(d10, series["DGS2"])
        if "DGS3MO" in series:
            computed["10y3m"] = series.get("T10Y3M") or combine(d10, series["DGS3MO"])
            computed["recprob"] = recession_history(*computed["10y3m"])
            spread = statistics.mean(computed["10y3m"][1][-21:])
            recession["curve"] = dict(spread=round(spread, 2), probability=round(recession_probit(spread), 4),
                                      date=computed["10y3m"][0][-1].isoformat())
        if "DFII10" in series:
            computed["breakeven"] = combine(d10, series["DFII10"])
        board = [("3-month Treasury", "DGS3MO", "rate"), ("2-year Treasury", "DGS2", "rate"),
                 ("10-year Treasury", "DGS10", "rate"), ("30-year Treasury", "DGS30", "rate"),
                 ("10-year minus 2-year", "10y2y", "rate"), ("10-year minus 3-month", "10y3m", "rate"),
                 ("10-year real yield (TIPS)", "DFII10", "rate"), ("10-year breakeven inflation", "breakeven", "rate"),
                 ("5-year, 5-year forward inflation", "T5YIFR", "rate"), ("30-year mortgage", "MORTGAGE30US", "rate"),
                 ("Baa corporate spread", "BAA10Y", "rate"), ("Single-A corporate spread", "BAMLC0A3CA", "rate"),
                 ("BBB corporate spread", "BAMLC0A4CBBB", "rate"), ("10-year term premium", "THREEFYTP10", "rate"),
                 ("BB corporate spread", "BAMLH0A1HYBB", "rate"), ("High-yield credit spread", "BAMLH0A0HYM2", "rate"),
                 ("VIX", "VIXCLS", "index"),
                 ("Broad dollar index", "DTWEXBGS", "index")]
        for label, sid, kind in board:
            if sid not in computed or not computed[sid][0]:
                continue
            ds, vs = computed[sid]
            last, m1, y1 = vs[-1], asof(ds, vs, ds[-1] - timedelta(days=30)), asof(ds, vs, ds[-1] - timedelta(days=365))
            rates["board"].append(dict(label=label, kind=kind, value=last, date=ds[-1].isoformat(),
                                       month=None if m1 is None else last - m1, year=None if y1 is None else last - y1))
    if "DFEDTARL" in series and "DFEDTARU" in series:
        rates["target"] = dict(low=series["DFEDTARL"][1][-1], high=series["DFEDTARU"][1][-1],
                               date=series["DFEDTARU"][0][-1].isoformat())

    # Release calendar: the next published date for each indicator's release.
    calendar = {}
    for f in factors:
        rel = raw.get("release_of", {}).get(f["id"])
        f["next_release"] = None
        if not rel:
            continue
        ahead = sorted(d for d in raw.get("release_dates", {}).get(str(rel["id"]), [])
                       if today.isoformat() <= d <= (today + timedelta(days=CALENDAR_DAYS)).isoformat())
        if ahead:
            f["next_release"] = ahead[0]
        for d in ahead:
            calendar.setdefault((d, rel["name"]), []).append(f["label"])
    calendar = [dict(date=d, release=name, indicators=labels) for (d, name), labels in sorted(calendar.items())]

    def points(sid):
        return [[d.isoformat(), round(v, 4)] for d, v in thin(list(zip(*computed[sid])))]

    extras = []
    for cid, label, unit, dp, options in CHART_EXTRAS:
        views, sources = [], []
        for name, source, note in options:  # a view whose series failed is dropped, the rest of the chart stays
            view = dict(name=name, unit=unit, dp=dp, note=note)
            if isinstance(source, str):
                sources.append(source)
                if source in computed and computed[source][0]:
                    views.append(dict(view, points=points(source)))
            else:
                lines = [dict(name=line, points=points(sid)) for line, sid in source if sid in computed and computed[sid][0]]
                if len(lines) > 1:
                    views.append(dict(view, lines=lines))
        if views:
            extras.append(dict(id=cid, label=label, freq="m" if cid in MONTHLY_CHARTS else "d", sources=sources, views=views))

    midterm = None
    if raw.get("sp500"):
        midterm = midterm_windows([date.fromisoformat(d) for d, _ in raw["sp500"]], [c for _, c in raw["sp500"]], today)

    return dict(
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"), fetched_ts=time.time(),
        today=today.isoformat(), factors=factors, groups=groups, markets=markets, regime=regime,
        recession=recession, rates=rates, calendar=calendar, gdpnow=latest("GDPNOW"), errors=errors,
        extras=extras, midterm=midterm, fed=raw.get("fed", []),
        sectors=sector_returns(raw["sectors"]) if raw.get("sectors") else None,
        benchmarks=benchmarks.build(raw["benchmarks"]) if benchmarks and raw.get("benchmarks") else None,  # benchmarks (beta)
        recessions=recession_ranges(*series["USREC"]) if "USREC" in series else [],
        method=dict(threshold=THRESHOLD, windows=WINDOWS, stale_days=STALE_DAYS))


# ---------- FRED ----------

try:  # python.org builds on macOS ship without root certificates; certifi comes with requests
    import certifi
    SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL = ssl.create_default_context()


class Setup(Exception):
    pass


def api_key():
    key = os.environ.get("FRED_API_KEY", "")
    env = HERE / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "FRED_API_KEY":
                key = value
    key = key.strip().strip("\"'")
    if not key or key == "yourkey":
        raise Setup("No FRED key found yet. It takes one line in one file.")
    return key


def fred(key, path, **params):
    url = "https://api.stlouisfed.org/fred/%s?%s" % (path, urllib.parse.urlencode(dict(params, api_key=key, file_type="json")))
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=20, context=SSL) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                message = json.load(e)["error_message"]
            except Exception:
                message = "FRED answered HTTP %s" % e.code
            if e.code != 429 or attempt == 2:  # 429 is the rate limit: wait and try once more
                raise RuntimeError(message.replace(key, "(key)")) from None
        except OSError as e:  # URLError, and the bare socket timeout older Pythons raise mid-read
            if attempt == 2:
                raise RuntimeError("Could not reach FRED: %s" % getattr(e, "reason", e)) from None
        time.sleep(2)


YAHOO_LOCK = threading.Lock()


def yahoo_closes(symbol, adjusted=False, **window):
    """Daily closes from Yahoo through yfinance, if it is installed. adjusted: reinvest dividends, for total returns."""
    try:
        import yfinance
    except ImportError:
        raise RuntimeError("Needs the yfinance package. In Terminal: python3 -m pip install yfinance") from None
    with YAHOO_LOCK:  # yfinance keeps a SQLite cache; two threads at once fail with "database is locked"
        close = yfinance.Ticker(symbol).history(auto_adjust=adjusted, **window)["Close"].dropna()
    return [[ts.date().isoformat(), float(v)] for ts, v in close.items()]


def sp500_history():
    """S&P 500 closes since 1950. FRED is licensed to carry only ten years of the index."""
    rows = yahoo_closes("^GSPC", start="1949-12-01")
    if len(rows) < 1000:
        raise RuntimeError("Yahoo returned too little S&P 500 history. Press Refresh to try again.")
    return rows


def sector_history():
    closes = {symbol: yahoo_closes(symbol, period="3mo") for symbol in SECTORS}
    if not any(closes.values()):
        raise RuntimeError("Yahoo returned no sector prices. Press Refresh to try again.")
    return closes


def benchmark_history():
    """Dividend-adjusted closes for the Benchmarks (beta) tab. A ticker that fails leaves its lines empty."""
    start = (date.today() - timedelta(days=11 * 366)).isoformat()
    closes = {}
    for symbol in benchmarks.TICKERS:
        try:
            closes[symbol] = yahoo_closes(symbol, adjusted=True, start=start)
        except Exception:
            closes[symbol] = []
    if not any(closes.values()):
        raise RuntimeError("Yahoo returned no benchmark prices. Press Refresh to try again.")
    return closes


def fed_feed():
    items = []
    for kind, url in FED_FEEDS:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (macro-terminal, local)"})
        with urllib.request.urlopen(request, timeout=20, context=SSL) as r:
            items += parse_feed(r.read(2000000), kind)
    return sorted(items, key=lambda i: i["date"] or "", reverse=True)[:12]


def fetch_all(key, today):
    recent = (today - timedelta(days=12 * 366)).isoformat()  # ten years of gaps plus the long window
    wanted = {sid: "1980-01-01" if sid in LONG else recent for sid in [f["id"] for f in FACTORS] + EXTRA}
    raw = dict(obs={}, errors={}, release_of={}, release_dates={})

    def observations(item):
        sid, start = item
        try:
            return sid, fred(key, "series/observations", series_id=sid, observation_start=start)["observations"]
        except Exception as e:
            return sid, e

    def release(sid):
        try:
            r = fred(key, "series/release", series_id=sid)["releases"][0]
            return sid, dict(id=r["id"], name=r["name"])
        except Exception:
            return sid, None

    def release_dates(rid):
        try:
            got = fred(key, "release/dates", release_id=rid, include_release_dates_with_no_data="true",
                       sort_order="desc", limit=400)["release_dates"]
            return rid, [d["date"] for d in got]
        except Exception:
            return rid, []

    with ThreadPoolExecutor(6) as pool:  # FRED allows 120 requests a minute; this run makes about 70
        # Not FRED: optional, never fatal.
        sides = {"sp500": pool.submit(sp500_history), "sectors": pool.submit(sector_history), "fed": pool.submit(fed_feed)}
        if benchmarks:  # benchmarks (beta)
            sides["benchmarks"] = pool.submit(benchmark_history)
        for sid, got in pool.map(observations, wanted.items()):
            if isinstance(got, Exception):
                raw["errors"][sid] = str(got)
            else:
                raw["obs"][sid] = got
        if not raw["obs"]:
            raise RuntimeError(next(iter(raw["errors"].values())))
        scheduled = [f["id"] for f in FACTORS if f["freq"] != "d" and f["id"] in raw["obs"]]
        raw["release_of"] = {sid: rel for sid, rel in pool.map(release, scheduled) if rel}
        ids = sorted({rel["id"] for rel in raw["release_of"].values()})
        raw["release_dates"] = {str(rid): dates for rid, dates in pool.map(release_dates, ids)}
        for name, job in sides.items():
            try:
                raw[name] = job.result()
            except Exception as e:
                raw["errors"][name] = str(e) or type(e).__name__
    return raw


# ---------- server ----------

LOCK = threading.Lock()


def ny_now():
    return datetime.now(NEW_YORK)


def slots(now):
    """Scheduled refresh times from a week before now to a week after, weekdays only."""
    days = (now.date() + timedelta(days=n) for n in range(-7, 8))
    return [datetime(d.year, d.month, d.day, h, m, tzinfo=now.tzinfo) for d in days if d.weekday() < 5 for h, m in REFRESH_AT]


def last_slot(now):
    return max(s for s in slots(now) if s <= now)


def next_slot(now):
    return min(s for s in slots(now) if s > now)


def schedule_info(now):
    """What the page shows about the schedule. Added on the way out, not cached: the schedule moves on even when the data does not."""
    return dict(next_refresh=next_slot(now).isoformat(),
                refresh_at=["%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM") for h, m in REFRESH_AT])


def cached_ts():
    try:
        return json.loads(CACHE.read_text()).get("fetched_ts", 0)
    except (OSError, ValueError):
        return 0


def tick(tried):
    """One step of the scheduler: refresh if a scheduled time has passed since the last good fetch.
    Returns when a refresh was last attempted, so a failure waits RETRY_MINUTES before the next try."""
    if cached_ts() < last_slot(ny_now()).timestamp() and time.time() - tried > RETRY_MINUTES * 60:
        tried = time.time()
        try:
            get_snapshot()
        except Exception:
            pass  # a missing key or a FRED outage is shown on the page when it next asks
    return tried


def keep_fresh():
    # Checks every minute, so a refresh missed while the laptop slept runs soon after it wakes.
    tried = 0
    while True:
        tried = tick(tried)
        time.sleep(60)


def get_snapshot(force=False):
    with LOCK:
        cached = None
        if CACHE.exists():
            try:
                cached = json.loads(CACHE.read_text())
            except ValueError:
                pass
        if cached:
            fetched = cached.get("fetched_ts", 0)
            # Fresh until the next scheduled time passes. The 60s floor stops a double click refetching.
            if time.time() - fetched < 60 or (not force and fetched >= last_slot(ny_now()).timestamp()):
                return cached
        try:
            snap = build_snapshot(fetch_all(api_key(), date.today()), date.today())
        except Exception as e:
            if cached and not isinstance(e, Setup):
                return dict(cached, stale_reason=str(e))  # FRED is down: yesterday's read beats none
            raise
        CACHE.write_text(json.dumps(snap))
        return snap


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path != "/api/snapshot":
            return super().do_GET()
        try:
            now = ny_now()
            code, body = 200, dict(get_snapshot(force="refresh=1" in query), **schedule_info(now))
        except Setup as e:
            code, body = 503, dict(error="setup", message=str(e))
        except Exception as e:
            code, body = 502, dict(error="fetch", message=str(e))
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def export(path):
    """Write one fresh snapshot to a file, for hosting the front end as a static site (see .github/workflows/pages.yml)."""
    today = date.today()
    raw = fetch_all(api_key(), today)
    for name, message in raw["errors"].items():
        print("Warning: %s did not load: %s" % (name, message))
    Path(path).write_text(json.dumps(dict(build_snapshot(raw, today), **schedule_info(ny_now()))))
    print("Wrote %s" % path)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--export":
        export(sys.argv[2] if len(sys.argv) > 2 else HERE / "static" / "snapshot.json")
        return
    try:
        # 127.0.0.1 only: nothing else on the network can reach this.
        server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(HERE / "static")))
    except OSError:
        sys.exit("Port %s is in use. Macro Terminal may already be running: open http://127.0.0.1:%s" % (PORT, PORT))
    url = "http://127.0.0.1:%s" % PORT
    threading.Thread(target=keep_fresh, daemon=True).start()
    print("Macro Terminal is running at %s  (Ctrl+C to stop)" % url)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
