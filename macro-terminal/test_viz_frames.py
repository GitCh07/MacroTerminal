"""Run: python3 test_viz_frames.py   (no FRED key or network needed)"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import macro_terminal as mt
import test_macro_terminal as t
import viz_frames as v

v.PACE = 0


def fake_curve():
    """Monthly averages as FRED serves them: 1M from Aug 2001, no 20Y 1987-Sep 1993, and 30Y values even inside its break."""
    months = ["%d-%02d-01" % (y, m) for y in range(1982, 2027) for m in range(1, 13) if (y, m) <= (2026, 11)]
    out = {}
    for k, (label, sid, years) in enumerate(v.MATURITIES):
        rows = []
        for i, d in enumerate(months):
            gone = sid == "DGS20" and "1987-01" <= d < "1993-10"
            if sid == "DGS1MO" and d < "2001-07":
                continue  # FRED returns nothing before a series starts
            # short end above the long end in 2006-07, so both spreads invert there
            y = 5 + 0.1 * k + (1.5 - 0.3 * k if "2006-07" <= d[:7] <= "2007-05" else 0)
            rows.append(dict(date=d, value="." if gone else "%.2f" % y))
        out[sid] = rows
    return out


class Curve(unittest.TestCase):
    def setUp(self):
        self.c = v.curve_frames(fake_curve(), date(2026, 11, 17))

    def test_gaps_stay_empty_and_are_named(self):
        i30, i1 = [m["label"] for m in self.c["maturities"]].index("30Y"), 0
        for m in ("2002-02", "2004-06", "2006-02"):
            self.assertIsNone(self.c["frames"][self.c["months"].index(m)][i30], m)
        self.assertIsNotNone(self.c["frames"][self.c["months"].index("2006-03")][i30])
        self.assertIsNone(self.c["frames"][0][i1])
        notes = {(n["maturity"], n["start"], n["end"]) for n in self.c["notes"]}
        self.assertEqual(notes, {("1M", "1982-01", "2001-06"), ("30Y", "2002-02", "2006-02"), ("20Y", "1987-01", "1993-09")})
        self.assertTrue(all(n["why"] for n in self.c["notes"]))

    def test_every_frame_has_every_maturity_slot(self):
        self.assertEqual(self.c["months"][0], "1982-01")
        self.assertTrue(all(len(f) == len(v.MATURITIES) for f in self.c["frames"]))
        self.assertEqual(len(self.c["frames"]), len(self.c["months"]))

    def test_spreads_and_inversions(self):
        s = self.c["spreads"]["10Y-2Y"]
        self.assertAlmostEqual(s[-1], 0.4, 6)
        self.assertEqual(self.c["inversions"]["10Y-2Y"], [["2006-07", "2007-05"]])
        self.assertEqual(self.c["inversions"]["10Y-3M"], [["2006-07", "2007-05"]])

    def test_month_to_date_comes_from_this_months_days(self):
        monthly = {sid: [o for o in rows if o["date"] < "2026-11"] for sid, rows in fake_curve().items()}
        self.assertFalse(v.curve_frames(monthly, date(2026, 11, 17))["partial"])  # FRED stops at the last full month
        daily = {"DGS10": [dict(date="2026-10-31", value="9"), dict(date="2026-11-02", value="4.00"),
                           dict(date="2026-11-03", value="."), dict(date="2026-11-04", value="4.10")],
                 "DGS2": [dict(date="2026-11-02", value="3.50")]}
        c = v.curve_frames(monthly, date(2026, 11, 17), daily)
        self.assertTrue(c["partial"])
        self.assertEqual(c["months"][-1], "2026-11")
        last = dict(zip([m["label"] for m in c["maturities"]], c["frames"][-1]))
        self.assertEqual((last["10Y"], last["2Y"], last["30Y"]), (4.05, 3.5, None))
        self.assertAlmostEqual(c["spreads"]["10Y-2Y"][-1], 0.55, 6)
        self.assertFalse(v.curve_frames(monthly, date(2026, 11, 17), {"DGS10": []})["partial"])  # no days yet, no frame

    def test_fetch_uses_the_refresh_days_and_asks_only_for_the_rest(self):
        asked, saved = [], mt.fred
        mt.fred = lambda key, path, **p: asked.append((p["series_id"], "frequency" in p)) or {"observations": []}
        try:
            v.fetch_curve("k", date(2026, 11, 17), {"obs": {"DGS10": [dict(date="2026-11-02", value="4")]}})
        finally:
            mt.fred = saved
        self.assertEqual(len([a for a in asked if a[1]]), len(v.MATURITIES))
        self.assertEqual(sorted(sid for sid, monthly in asked if not monthly), sorted(sid for _, sid, _ in v.MATURITIES if sid != "DGS10"))


class Bias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = t.fake_raw()
        cls.b = v.bias_frames(cls.raw, t.TODAY, months=12)

    def test_last_frame_is_the_board(self):
        snap = mt.build_snapshot(self.raw, t.TODAY)
        self.assertEqual(self.b["frames"][-1]["scores"], {m["id"]: m["score"] for m in snap["markets"]})
        self.assertEqual(self.b["frames"][-1]["votes"], {f["id"]: f["score"] for f in snap["factors"]})

    def test_contributions_add_up_to_the_score(self):
        for frame in self.b["frames"]:
            for mid, s in frame["scores"].items():
                self.assertAlmostEqual(sum(frame["contrib"][mid].values()), s, delta=0.003)

    def test_month_ends_and_release_lag_fallback(self):
        self.assertEqual([f["date"] for f in self.b["frames"]][-3:], ["2026-09-30", "2026-10-31", "2026-11-13"])
        self.assertEqual(v.month_ends(date(2026, 3, 5), 2), [date(2026, 1, 31), date(2026, 2, 28)])
        self.assertEqual(set(self.b["method"].values()), {"assumed lag"})
        # With no ALFRED history a past frame sees today's data cut by the assumed lag: rerun one month-end by hand.
        d = date(2026, 6, 30)
        frame = next(f for f in self.b["frames"] if f["date"] == d.isoformat())
        cpi = mt.parse(self.raw["obs"]["CPIAUCSL"])
        keep = [i for i, x in enumerate(cpi[0]) if d - timedelta(days=v.HISTORY_DAYS) <= x <= date(2026, 5, 16)]
        f = next(f for f in mt.FACTORS if f["id"] == "CPIAUCSL")
        self.assertEqual(frame["votes"]["CPIAUCSL"],
                         mt.build_factor(f, [cpi[0][i] for i in keep], [cpi[1][i] for i in keep], d)["score"])


def vintages(obs, revise_after):
    """ALFRED-style rows for monthly observations: each one appears 40 days after its date, and anything dated before
    revise_after is revised up 5% on 2026-03-01."""
    rows = []
    for o in obs:
        if o["value"] == ".":
            continue
        d, val = date.fromisoformat(o["date"]), float(o["value"])
        seen = (d + timedelta(days=40)).isoformat()
        if d < revise_after and seen < "2026-03-01":
            rows.append(dict(date=o["date"], value="%.4f" % (val / 1.05), realtime_start=seen, realtime_end="2026-02-28"))
            rows.append(dict(date=o["date"], value=o["value"], realtime_start="2026-03-01", realtime_end="9999-12-31"))
        else:
            rows.append(dict(date=o["date"], value=o["value"], realtime_start=seen, realtime_end="9999-12-31"))
    return rows


class AsPublished(unittest.TestCase):
    def test_a_past_frame_sees_only_what_was_published_then(self):
        rows = vintages(t.fake_raw()["obs"]["PAYEMS"], date(2025, 12, 1))
        dates, vals = v.as_of(rows, date(2026, 1, 31))
        self.assertEqual(dates[-1], date(2025, 12, 1))  # December, out Jan 10; January not until March
        raw = {o["date"]: float(o["value"]) for o in t.fake_raw()["obs"]["PAYEMS"]}
        self.assertAlmostEqual(vals[-2], raw["2025-11-01"] / 1.05, 3)  # the first print, not today's revised figure
        self.assertAlmostEqual(v.as_of(rows, date(2026, 3, 31))[1][-4], raw["2025-11-01"], 3)

    def test_frames_use_vintages_where_alfred_has_them(self):
        raw = t.fake_raw()
        history = {"PAYEMS": ("vintage", vintages(raw["obs"]["PAYEMS"], date(2025, 12, 1))),
                   "INDPRO": ("error", "Bad Request"), "DGS2": ("current", raw["obs"]["DGS2"])}
        b = v.bias_frames(raw, t.TODAY, months=12, history=history)
        self.assertEqual((b["method"]["PAYEMS"], b["method"]["INDPRO"], b["method"]["DGS2"]),
                         ("as published", "assumed lag", "not revised"))
        self.assertIn("Industrial production", b["note"])
        d = date(2026, 1, 31)
        frame = next(f for f in b["frames"] if f["date"] == d.isoformat())
        f = next(f for f in mt.FACTORS if f["id"] == "PAYEMS")
        dates, vals = v.as_of(history["PAYEMS"][1], d)
        k = next(i for i, x in enumerate(dates) if x >= d - timedelta(days=v.HISTORY_DAYS))
        self.assertEqual(frame["votes"]["PAYEMS"], mt.build_factor(f, dates[k:], vals[k:], d)["score"])
        snap = mt.build_snapshot(raw, t.TODAY)
        self.assertEqual(b["frames"][-1]["scores"], {m["id"]: m["score"] for m in snap["markets"]})

    def test_fetch_history_asks_alfred_for_revised_series_only(self):
        asked, saved = [], mt.fred
        def fake(key, path, **p):
            asked.append(p)
            if p["series_id"] == "ADPMNUSNERSA":
                raise RuntimeError("Bad Request. The series does not exist in ALFRED but may exist in FRED.")
            return {"observations": [], "count": 0}
        mt.fred = fake
        try:
            h = v.fetch_history("k", t.TODAY, months=3)
        finally:
            mt.fred = saved
        self.assertEqual(h["ADPMNUSNERSA"][0], "error")
        self.assertEqual(h["PAYEMS"][0], "vintage")
        self.assertEqual(h["BAA10Y"][0], "current")
        pay = next(p for p in asked if p["series_id"] == "PAYEMS")
        self.assertEqual(pay["vintage_dates"], "2026-08-31,2026-09-30,2026-10-31")
        self.assertEqual(pay["observation_start"], (date(2026, 8, 31) - timedelta(days=v.HISTORY_DAYS)).isoformat())
        self.assertNotIn("vintage_dates", next(p for p in asked if p["series_id"] == "BAA10Y"))


class Files(unittest.TestCase):
    def setUp(self):
        self.saved = mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, v.fetch_curve, v.fetch_history, v.DATA
        self.dir = Path(tempfile.mkdtemp())
        mt.CACHE = self.dir / "cache.json"
        mt.api_key = lambda: "test"
        mt.fetch_all = lambda key, today: t.fake_raw(today)
        v.fetch_curve = lambda key, today, raw=None: (fake_curve(), {})
        v.fetch_history = lambda key, today: {}
        v.DATA = self.dir / "data"

    def tearDown(self):
        mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, v.fetch_curve, v.fetch_history, v.DATA = self.saved

    def test_refresh_rewrites_the_frames(self):
        v.DATA.mkdir()
        (v.DATA / "yield_curve.json").write_text('{"old": true}')
        snap = mt.get_snapshot(force=True)
        mt.VIZ_JOB.join(60)  # built in the background, after the snapshot is already back
        for name in ("yield_curve.json", "bias_history.json", "benchmark_levels.json"):
            body = json.loads((v.DATA / name).read_text())
            self.assertEqual(body["built_for"], snap["fetched_at"], name)
        self.assertNotIn("old", json.loads((v.DATA / "yield_curve.json").read_text()))
        self.assertEqual(list(v.DATA.glob("*.tmp")), [])

    def test_export_writes_the_frames_too(self):
        mt.export(self.dir / "snapshot.json")
        snap = json.loads((self.dir / "snapshot.json").read_text())
        self.assertEqual(json.loads((v.DATA / "bias_history.json").read_text())["built_for"], snap["fetched_at"])

    def test_refresh_does_not_wait_for_the_frames(self):
        gate = __import__("threading").Event()
        v.fetch_history = lambda key, today: gate.wait(5) and {}
        start = __import__("time").time()
        mt.get_snapshot(force=True)
        self.assertLess(__import__("time").time() - start, 4)
        gate.set()
        mt.VIZ_JOB.join(60)

    def test_rate_limit_waits_instead_of_failing(self):
        calls, saved, sleep = [], mt.fred, v.time.sleep
        def fake(key, path, **p):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("Too Many Requests.  Exceeded Rate Limit")
            return {"ok": True}
        mt.fred, v.time.sleep = fake, lambda s: None
        try:
            self.assertEqual(v.paced("k", "x"), {"ok": True})
        finally:
            mt.fred, v.time.sleep = saved, sleep
        self.assertEqual(len(calls), 2)

    def test_one_failing_file_keeps_the_rest(self):
        v.fetch_curve = lambda key, today, raw=None: (_ for _ in ()).throw(RuntimeError("FRED down"))
        errors = v.write_all(t.fake_raw(), "test", t.TODAY, v.DATA)
        self.assertEqual(list(errors), ["yield_curve.json"])
        self.assertTrue((v.DATA / "bias_history.json").exists())


class Levels(unittest.TestCase):
    def test_month_end_levels_line_up(self):
        raw = t.fake_raw()
        out = v.benchmark_levels(raw["benchmarks"])
        self.assertTrue(all(len(line["levels"]) == len(out["months"]) for line in out["lines"]))
        self.assertNotIn("Caerus", json.dumps(out))
        spx = next(line for line in out["lines"] if line["name"] == "S&P 500 (TR)")
        rows = raw["benchmarks"]["^SP500TR"]
        last_oct = [c for d, c in rows if d.startswith("2026-10")][-1]
        first = rows[0][1]
        self.assertAlmostEqual(spx["levels"][out["months"].index("2026-10")], round(100 * last_oct / first, 4), 3)


if __name__ == "__main__":
    unittest.main()
