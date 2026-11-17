"""Animations: precomputed frames for the replay views in static/viz/. The browser only draws them.

Written by the same refresh that builds the snapshot (export for the hosted copy, get_snapshot locally), to
static/viz/data/*.json. Optional: if this file is missing the terminal runs exactly as before.

To remove animations: delete this file, test_viz_frames.py and static/viz/, then the lines marked "animations" in
macro_terminal.py, static/index.html and static/app.js.
"""
import bisect
import json
import os
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
GAP_WHY = {"DGS1MO": "FRED's 1-month series starts July 2001",
           "DGS20": "Treasury dropped the 20-year from 1987 and brought it back in October 1993",
           "DGS30": "Treasury stopped issuing the 30-year bond from February 2002 to February 2006"}

# shortcut: one assumed release lag per frequency (days after the observation date), not each release's real date.
# Good to a few weeks; FRED keeps revised figures, so a past frame is not the exact read that was live then.
LAG_DAYS = {"d": 1, "w": 6, "m": 45, "q": 120}
BIAS_MONTHS = 60


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


def curve_frames(observations, today):
    """observations: {series id: FRED monthly observations}. A month with no value stays None, never interpolated."""
    by_sid = {sid: {o["date"][:7]: float(o["value"]) for o in obs if o["value"] not in (".", "")}
              for sid, obs in observations.items()}
    months = sorted({m for got in by_sid.values() for m in got if m >= CURVE_START[:7]})
    frames = [[by_sid.get(sid, {}).get(m) for _, sid, _ in MATURITIES] for m in months]
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


def fetch_curve(key):
    out = {}
    for _, sid, _ in MATURITIES:
        out[sid] = mt.fred(key, "series/observations", series_id=sid, observation_start=CURVE_START,
                           frequency="m", aggregation_method="avg")["observations"]
    return out


def month_ends(today, n):
    """The last day of each of the n months before today's month, oldest first."""
    out, d = [], today.replace(day=1)
    for _ in range(n):
        d -= timedelta(days=1)
        out.append(d)
        d = d.replace(day=1)
    return out[::-1]


def bias_frames(raw, today, months=BIAS_MONTHS):
    """Market scores at past month-ends from the same build_factor and market_score the board uses.
    The last frame is today on the full data, so it matches the snapshot exactly."""
    series = {sid: mt.parse(obs) for sid, obs in raw["obs"].items()}
    series = {sid: s for sid, s in series.items() if s[0]}
    frames = []
    for d in month_ends(today, months) + [today]:
        factors = []
        for f in mt.FACTORS:
            dates, vals = series.get(f["id"], ([], []))
            n = len(dates) if d == today else bisect.bisect_right(dates, d - timedelta(days=LAG_DAYS[f["freq"]]))
            factors.append(mt.build_factor(f, dates[:n], vals[:n], d) if n else dict(f, score=None))
        scores, contrib = {}, {}
        for m in mt.MARKETS:
            s, groups = mt.market_score(m, factors)
            used = sum(abs(m["weights"][g]) for g in groups)
            scores[m["id"]] = round(s, 3)
            contrib[m["id"]] = {g: round(v / used, 4) for g, v in groups.items()}  # sums to the score
        frames.append(dict(date=d.isoformat(), scores=scores, contrib=contrib,
                           votes={f["id"]: f["score"] for f in factors}))
    return dict(
        title="Market bias, month by month", today=today.isoformat(), lag_days=LAG_DAYS,
        markets=[dict(id=m["id"], label=m["label"], weights=m["weights"]) for m in mt.MARKETS],
        groups=[dict(id=g, label=label) for g, (label, _, _) in mt.GROUPS.items()],
        factors=[dict(id=f["id"], label=f["label"], group=f["group"]) for f in mt.FACTORS],
        thresholds=[[0.5, "very bullish"], [0.2, "bullish"], [-0.2, "neutral"], [-0.5, "bearish"]],
        frames=frames,
        note="Rebuilt from today's FRED data, which includes revisions, with each release assumed to land %s days "
             "(monthly) or %s days (quarterly) after its period starts. The last frame is today's board."
             % (LAG_DAYS["m"], LAG_DAYS["q"]))


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


def write_all(raw, key, today, out=None):
    """Writes every frame file it can; one that fails keeps yesterday's copy. Returns {file: error}."""
    out = out or DATA
    out.mkdir(parents=True, exist_ok=True)
    jobs = {"yield_curve.json": lambda: curve_frames(fetch_curve(key), today),
            "bias_history.json": lambda: bias_frames(raw, today)}
    if benchmarks and raw.get("benchmarks"):
        jobs["benchmark_levels.json"] = lambda: benchmark_levels(raw["benchmarks"])
    errors = {}
    for name, job in jobs.items():
        try:
            body = job()
            if body:
                write(out / name, dict(body, generated=today.isoformat()))
        except Exception as e:
            errors[name] = str(e) or type(e).__name__
    return errors
