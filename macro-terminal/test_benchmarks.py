"""Run: python3 test_benchmarks.py   (no network needed). Tests for the Benchmarks (beta) module."""
import unittest
from datetime import date, timedelta

import benchmarks as bm


def days(start, end):
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def fake_closes(end=date(2026, 11, 13), drop=()):
    """Every ticker grows at its own steady pace over weekdays, back eleven years. Used here and by the page tests."""
    start = date(end.year - 11, 1, 1)
    weekdays = [d for d in days(start, end) if d.weekday() < 5]
    out = {}
    for n, t in enumerate(bm.TICKERS):
        if t in drop:
            continue
        rate = 0.02 + 0.01 * n
        first = date(2017, 7, 6) if t == "SMMD" else start  # the real fund's launch
        out[t] = [[d.isoformat(), round(50 * (1 + rate) ** ((d - start).days / 365), 6)] for d in weekdays if d >= first]
    return out


class Weights(unittest.TestCase):
    def test_nested_blends_flatten_to_ticker_weights(self):
        w = bm.flatten(bm.BY_NAME["75% US Equity / 25% Non-US Equity"])
        self.assertAlmostEqual(sum(w.values()), 1)
        self.assertAlmostEqual(w["^SP500TR"], 0.75 * 0.70)
        self.assertAlmostEqual(w["EEM"], 0.25 * 0.20)
        self.assertAlmostEqual(w["EWC"], 0.25 * 0.80 * 0.11)

    def test_every_line_sums_to_one_and_resolves(self):
        for _, name, parts, _ in bm.LINES:
            self.assertAlmostEqual(sum(bm.flatten(parts).values()), 1, msg=name)

    def test_blend_rebalances_at_month_end(self):
        d = [date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 27), date(2026, 3, 2), date(2026, 3, 31)]
        series = {"A": (d, [1, 2, 2, 2, 2]), "B": (d, [1, 1, 1, 1, 2])}
        dates, vals = bm.blend(series, {"A": 0.5, "B": 0.5})
        self.assertEqual(vals[1], 150)  # A doubled in January
        self.assertEqual(vals[-1], 225)  # reset to 50/50 at each month-end, so B doubling in March adds half: 150 x 1.5
        # without rebalancing it would be 100 x (0.5 x 2 + 0.5 x 2) = 200

    def test_blend_uses_only_shared_dates(self):
        a = ([date(2026, 1, 2), date(2026, 1, 5)], [1, 1.1])
        b = ([date(2026, 1, 5)], [1])
        self.assertEqual(bm.blend({"A": a, "B": b}, {"A": 0.5, "B": 0.5})[0], [date(2026, 1, 5)])


class Periods(unittest.TestCase):
    def setUp(self):
        start = date(2018, 1, 1)
        self.dates = days(start, date(2026, 11, 13))
        self.vals = [1.1 ** ((d - start).days / 365) for d in self.dates]  # exactly 10% over any 365 days

    def test_periods(self):
        r = bm.period_returns(self.dates, self.vals, len(self.dates) - 1)
        self.assertEqual(len(r), len(bm.PERIODS))
        self.assertAlmostEqual(r[0], (1.1 ** (1 / 365) - 1) * 100, places=2)  # 1 day
        self.assertAlmostEqual(r[1], (1.1 ** (7 / 365) - 1) * 100, places=2)  # 1 week
        self.assertAlmostEqual(r[2], (1.1 ** (13 / 365) - 1) * 100, places=2)  # MTD: from the October 31 close
        self.assertAlmostEqual(r[3], (1.1 ** (44 / 365) - 1) * 100, places=2)  # QTD: from the September 30 close
        self.assertAlmostEqual(r[4], (1.1 ** (317 / 365) - 1) * 100, places=2)  # YTD: from the December 31 close
        self.assertAlmostEqual(r[5], 10.0, places=2)  # 1 year, 365 days
        self.assertAlmostEqual(r[6], 10.0, delta=0.02)  # 3 years annualised (one leap day inside)
        self.assertAlmostEqual(r[7], 10.0, delta=0.02)  # 5 years annualised
        self.assertIsNone(r[8])  # the history starts in 2018: no 10-year figure, rather than a wrong one

    def test_leap_day(self):
        self.assertEqual(bm.years_back(date(2028, 2, 29), 1), date(2027, 2, 28))


class Build(unittest.TestCase):
    def test_build(self):
        out = bm.build(fake_closes())
        self.assertEqual(out["periods"], bm.PERIODS)
        self.assertEqual(len(out["dates"]), bm.AS_OF_DAYS)
        self.assertEqual(out["dates"][-1], "2026-11-13")
        rows = {r["name"]: r for r in out["lines"]}
        self.assertEqual(len(rows), len(bm.LINES))
        us = rows["70% S&P 500 / 30% Russell 2500"]
        self.assertTrue(us["blend"])
        self.assertEqual(us["source"], "70% ^SP500TR + 30% SMMD")
        self.assertIsNone(us["returns"]["2026-11-13"][8])  # Russell 2500 fund is younger than ten years
        self.assertIsNotNone(rows["S&P 500 (TR)"]["returns"]["2026-11-13"][8])

    def test_a_missing_ticker_empties_only_its_lines(self):
        out = bm.build(fake_closes(drop={"BWX"}))
        rows = {r["name"]: r for r in out["lines"]}
        for name in ("Bloomberg Gbl Agg Ex USD TR USD", "70% Agg / 15% Short/ 15% Intl", "70% Muni / 15% Short Muni / 15% Intl"):
            self.assertEqual((rows[name]["returns"], rows[name]["missing"]), ({}, ["BWX"]))
        self.assertTrue(rows["Bloomberg US Agg Bond TR USD"]["returns"])

    def test_nothing_loaded(self):
        self.assertIsNone(bm.build({}))


if __name__ == "__main__":
    unittest.main()
