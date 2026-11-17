"""Replays: precomputed frames for the views in static/viz/. The browser only draws them.

Written after each refresh that builds the snapshot (export for the hosted copy; in the background after
get_snapshot locally), to static/viz/data/*.json. Optional: if this file is missing the terminal runs as before.

To remove the replays: delete this file, test_viz_frames.py and static/viz/, then the lines marked "replays" in
macro_terminal.py, static/index.html and static/app.css.
"""
import bisect
import json
import os
import time
from datetime import date, timedelta

import macro_terminal as mt

try:  # benchmarks (beta)
    import benchmarks
except ImportError:
    benchmarks = None

DATA = mt.HERE / "static" / "viz" / "data"

# Treasury constant-maturity yields, monthly averages. Years drive the x-axis spacing.
MATURITIES = [("1M", "DGS1MO", 1 / 12), ("3M", "DGS3MO", 0.25), ("6M", "DGS6MO", 0.5), ("1Y", "DGS1", 1),
              ("2Y", "DGS2", 2), ("3Y", "DGS3", 3), ("5Y", "DGS5", 5), ("7Y", "DGS7", 7), ("10Y", "DGS10", 10),
              ("20Y", "DGS20", 20), ("30Y", "DGS30", 30)]
CURVE_START = "1982-01-01"  # the first full year with the 3-month bill, so both spreads run from the first frame
GAP_WHY = {"DGS1MO": "FRED's 1-month series starts on the last day of July 2001",
           "DGS20": "Treasury dropped the 20-year series from 1987 and brought it back in October 1993",
           "DGS30": "Treasury discontinued the 30-year series from February 18, 2002 to February 9, 2006"}
# FRED still returns DGS30 values inside its own stated break, and Treasury published only an estimate then (the 20-year
# plus an extrapolation factor), so every month touching the break is left out rather than drawn as if it were the series.
BREAKS = {"DGS30": ("2002-02", "2006-02")}

# Past bias frames use each release as it stood at that month-end (FRED's ALFRED vintages). Daily market series are
# not revised, so they use today's data, cut one day back. A series ALFRED cannot serve falls back to today's data
# cut by an assumed release lag (days after the observation date); the page names any that did.
VINTAGE_FREQS = ("w", "m", "q")
LAG_DAYS = {"d": 1, "w": 6, "m": 45, "q": 120}
HISTORY_DAYS = 12 * 366  # what the board fetches, so each past frame sees the same span before its own date
BIAS_MONTHS = 60
PACE = 0.6  # seconds between replay requests, to stay under FRED's 120 a minute after the main refresh


def paced(key, path, **params):
    """mt.fred, spaced out, and waiting out the rate limit instead of failing on it."""
    for wait in (PACE, 30, 60):
        time.sleep(wait)
        try:
            return mt.fred(key, path, **params)
        except RuntimeError as e:
            if not any(w in str(e).lower() for w in ("rate limit", "too many")) or wait == 60:
                raise


def month(d):
    return d.isoformat()[:7]


def runs(months, flags):
    """[[first month, last month], ...] for each unbroken run of True."""
    out, start = [], None
    for i, (m, on) in enumerate(zip(months, flags)):
        if on and start is None:
            start = m
        if start is not None and (not on or i == len(months) - 1):
            out.append([start, m if on else months[i - 1]])
            start = None
    return out


def kept(sid, d):
    a, b = BREAKS.get(sid, ("", ""))
    return not a <= d[:7] <= b


def curve_frames(observations, today, daily=None):
    """observations: {series id: FRED monthly observations}. A month with no value stays None, never interpolated.
    daily: {series id: daily observations}; FRED's monthly averages stop at the last full month, so this month's
    days so far are averaged into a final month-to-date frame."""
    by_sid = {sid: {o["date"][:7]: float(o["value"]) for o in obs if o["value"] not in (".", "") and kept(sid, o["date"])}
              for sid, obs in observations.items()}
    months = sorted({m for got in by_sid.values() for m in got if m >= CURVE_START[:7]})
    frames = [[by_sid.get(sid, {}).get(m) for _, sid, _ in MATURITIES] for m in months]
    now = month(today)
    if daily and now not in months:
        mtd = []
        for _, sid, _ in MATURITIES:
            vals = [float(o["value"]) for o in daily.get(sid, []) if o["date"][:7] == now and o["value"] not in (".", "")
                    and kept(sid, o["date"])]
            mtd.append(round(sum(vals) / len(vals), 2) if vals else None)
        if any(v is not None for v in mtd):
            months.append(now)
            frames.append(mtd)
    labels = [t for t, _, _ in MATURITIES]

    def spread(long, short):
        i, j = labels.index(long), labels.index(short)
        return [None if f[i] is None or f[j] is None else round(f[i] - f[j], 3) for f in frames]

    spreads = {"10Y-2Y": spread("10Y", "2Y"), "10Y-3M": spread("10Y", "3M")}
    notes = []
    for k, (label, sid, _) in enumerate(MATURITIES):
        for a, b in runs(months, [f[k] is None for f in frames]):
            notes.append(dict(maturity=label, start=a, end=b, why=GAP_WHY.get(sid, "no value from FRED")))
    return dict(
        title="Treasury yield curve, monthly average", unit="%", source="FRED, Treasury constant-maturity yields",
        maturities=[dict(label=t, sid=sid, years=round(y, 4)) for t, sid, y in MATURITIES],
        months=months, frames=frames, partial=bool(months) and months[-1] == month(today),
        spreads=spreads, inversions={k: runs(months, [v is not None and v < 0 for v in s]) for k, s in spreads.items()},
        notes=notes)


def fetch_curve(key, today, raw=None):
    """Monthly averages for every maturity, plus this month's daily readings (from the refresh where it has them)."""
    monthly, daily, first = {}, {}, today.replace(day=1).isoformat()
    for _, sid, _ in MATURITIES:
        monthly[sid] = paced(key, "series/observations", series_id=sid, observation_start=CURVE_START,
                             frequency="m", aggregation_method="avg")["observations"]
        obs = (raw or {}).get("obs", {}).get(sid)
        if obs is None:
            obs = paced(key, "series/observations", series_id=sid, observation_start=first)["observations"]
        daily[sid] = [o for o in obs if o["date"] >= first]
    return monthly, daily


def month_ends(today, n):
    """The last day of each of the n months before today's month, oldest first."""
    out, d = [], today.replace(day=1)
    for _ in range(n):
        d -= timedelta(days=1)
        out.append(d)
        d = d.replace(day=1)
    return out[::-1]


def fetch_history(key, today, months=BIAS_MONTHS):
    """Per factor: ("vintage", rows) holding each month-end's published values, ("current", observations) for daily
    series, or ("error", message) when ALFRED could not serve it."""
    ends = month_ends(today, months)
    start = (ends[0] - timedelta(days=HISTORY_DAYS)).isoformat()
    out = {}
    for f in mt.FACTORS:
        try:
            if f["freq"] in VINTAGE_FREQS:
                got = paced(key, "series/observations", series_id=f["id"], observation_start=start, output_type=1,
                            vintage_dates=",".join(d.isoformat() for d in ends))
                if got.get("count", 0) > len(got["observations"]):
                    raise RuntimeError("more revisions than one request returns")
                out[f["id"]] = ("vintage", got["observations"])
            else:
                out[f["id"]] = ("current", paced(key, "series/observations", series_id=f["id"], observation_start=start)["observations"])
        except Exception as e:
            out[f["id"]] = ("error", str(e) or type(e).__name__)
    return out


def as_of(rows, d):
    """The series as published on day d: every observation whose real-time period covers d."""
    v, pts = d.isoformat(), {}
    for r in rows:
        if r["realtime_start"] <= v <= r["realtime_end"] and r["value"] not in (".", ""):
            pts[r["date"]] = float(r["value"])
    keys = sorted(pts)
    return [date.fromisoformat(k) for k in keys], [pts[k] for k in keys]


def bias_frames(raw, today, months=BIAS_MONTHS, history=None):
    """Market scores at past month-ends from the same build_factor and market_score the board uses.
    history (from fetch_history) gives each past frame the figures published by then; without it, today's data cut
    by an assumed release lag. The last frame is today on the full data, so it matches the snapshot exactly."""
    series = {sid: mt.parse(obs) for sid, obs in raw["obs"].items()}
    series = {sid: s for sid, s in series.items() if s[0]}
    history = history or {}
    method = {}
    for f in mt.FACTORS:
        kind = history.get(f["id"], ("none",))[0]
        method[f["id"]] = "as published" if kind == "vintage" else "not revised" if kind == "current" and f["freq"] == "d" else "assumed lag"
    current = {sid: mt.parse(got) for sid, (kind, got) in history.items() if kind == "current"}
    frames = []
    for d in month_ends(today, months) + [today]:
        factors = []
        for f in mt.FACTORS:
            kind, got = history.get(f["id"], ("none", None))
            if d == today:
                dates, vals = series.get(f["id"], ([], []))
            elif kind == "vintage":
                dates, vals = as_of(got, d)
            else:
                dates, vals = current.get(f["id"]) or series.get(f["id"], ([], []))
                n = bisect.bisect_right(dates, d - timedelta(days=LAG_DAYS[f["freq"]]))
                dates, vals = dates[:n], vals[:n]
            if d != today:  # the span the board itself would have fetched on that day
                k = bisect.bisect_left(dates, d - timedelta(days=HISTORY_DAYS))
                dates, vals = dates[k:], vals[k:]
            factors.append(mt.build_factor(f, dates, vals, d) if dates else dict(f, score=None))
        scores, contrib = {}, {}
        for m in mt.MARKETS:
            s, groups = mt.market_score(m, factors)
            used = sum(abs(m["weights"][g]) for g in groups)
            scores[m["id"]] = round(s, 3)
            contrib[m["id"]] = {g: round(v / used, 4) for g, v in groups.items()}  # sums to the score
        frames.append(dict(date=d.isoformat(), scores=scores, contrib=contrib,
                           votes={f["id"]: f["score"] for f in factors}))
    return dict(
        title="Market bias, month by month", today=today.isoformat(), lag_days=LAG_DAYS, method=method,
        markets=[dict(id=m["id"], label=m["label"], weights=m["weights"]) for m in mt.MARKETS],
        groups=[dict(id=g, label=label) for g, (label, _, _) in mt.GROUPS.items()],
        factors=[dict(id=f["id"], label=f["label"], group=f["group"]) for f in mt.FACTORS],
        thresholds=[[0.5, "very bullish"], [0.2, "bullish"], [-0.2, "neutral"], [-0.5, "bearish"]],
        frames=frames,
        note="Each past month uses the figures as they were published by that month-end (FRED's ALFRED archive), so "
             "it is the read the board would have given then. Daily market series are not revised and use today's data. "
             "The last frame is today's board." + (
                 " Not in ALFRED here, so today's figures with an assumed release delay: %s." % ", ".join(
                     f["label"] for f in mt.FACTORS if method[f["id"]] == "assumed lag")
                 if "assumed lag" in method.values() else ""))


def benchmark_levels(closes):
    """Month-end levels for each benchmark line (blends rebalanced monthly, as on the Benchmarks tab).
    The latest month is the last close so far."""
    series = {t: ([date.fromisoformat(d) for d, _ in rows], [c for _, c in rows]) for t, rows in closes.items() if rows}
    lines, asof = [], None
    for category, name, parts, note in benchmarks.LINES:
        weights = benchmarks.flatten(parts)
        if any(t not in series for t in weights):
            continue
        dates, vals = benchmarks.blend(series, weights)
        ends = {}
        for d, v in zip(dates, vals):
            ends[month(d)] = round(v, 4)  # later days overwrite, so each month keeps its last close
        lines.append(dict(name=name, category=category, blend=len(parts) > 1, levels=ends))
        asof = max(asof or dates[-1], dates[-1])
    months = sorted({m for line in lines for m in line["levels"]})
    for line in lines:
        line["levels"] = [line["levels"].get(m) for m in months]
    return dict(title="Benchmark month-end levels", asof=asof.isoformat() if asof else None, months=months,
                lines=lines) if lines else None


def write(path, body):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, separators=(",", ":")))
    os.replace(tmp, path)  # a page loading mid-write sees the old file or the new one, never half of one


def write_all(raw, key, today, out=None, built_for=None):
    """Writes every frame file it can; one that fails keeps yesterday's copy. Returns {file: error}.
    built_for: the snapshot's fetched_at, so an open page can tell when the frames for new data have landed."""
    out = out or DATA
    out.mkdir(parents=True, exist_ok=True)
    def curve():
        monthly, daily = fetch_curve(key, today, raw)
        return curve_frames(monthly, today, daily)

    jobs = {"yield_curve.json": curve,
            "bias_history.json": lambda: bias_frames(raw, today, history=fetch_history(key, today))}
    if benchmarks and raw.get("benchmarks"):
        jobs["benchmark_levels.json"] = lambda: benchmark_levels(raw["benchmarks"])
    errors = {}
    for name, job in jobs.items():
        try:
            body = job()
            if body:
                write(out / name, dict(body, generated=today.isoformat(), built_for=built_for))
        except Exception as e:
            errors[name] = str(e) or type(e).__name__
    return errors
