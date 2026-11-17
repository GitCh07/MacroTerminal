"""Run: python3 test_viz_frames.py   (no FRED key or network needed)"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import macro_terminal as mt
import test_macro_terminal as t
import viz_frames as v


def fake_curve():
    """Monthly averages with the real gaps: 1M from Jul 2001, no 30Y Mar 2002-Jan 2006, no 20Y 1987-Sep 1993."""
    months = ["%d-%02d-01" % (y, m) for y in range(1982, 2027) for m in range(1, 13) if (y, m) <= (2026, 11)]
    out = {}
    for k, (label, sid, years) in enumerate(v.MATURITIES):
        rows = []
        for i, d in enumerate(months):
            gone = ((sid == "DGS1MO" and d < "2001-07") or (sid == "DGS30" and "2002-03" <= d < "2006-02")
                    or (sid == "DGS20" and "1987-01" <= d < "1993-10"))
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
        frame = self.c["frames"][self.c["months"].index("2004-06")]
        self.assertIsNone(frame[i30])
        self.assertIsNone(self.c["frames"][0][i1])
        notes = {(n["maturity"], n["start"], n["end"]) for n in self.c["notes"]}
        self.assertEqual(notes, {("1M", "1982-01", "2001-06"), ("30Y", "2002-03", "2006-01"), ("20Y", "1987-01", "1993-09")})
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

    def test_current_month_is_flagged_partial(self):
        self.assertTrue(self.c["partial"])
        self.assertFalse(v.curve_frames(fake_curve(), date(2026, 12, 2))["partial"])


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

    def test_month_ends_and_release_lag(self):
        self.assertEqual([f["date"] for f in self.b["frames"]][-3:], ["2026-09-30", "2026-10-31", "2026-11-13"])
        self.assertEqual(v.month_ends(date(2026, 3, 5), 2), [date(2026, 1, 31), date(2026, 2, 28)])
        # A past frame must not see a reading released after it: rerun one month-end on data cut by hand.
        d = date(2026, 6, 30)
        frame = next(f for f in self.b["frames"] if f["date"] == d.isoformat())
        cpi = mt.parse(self.raw["obs"]["CPIAUCSL"])
        n = sum(x <= date(2026, 5, 16) for x in cpi[0])
        f = next(f for f in mt.FACTORS if f["id"] == "CPIAUCSL")
        self.assertEqual(frame["votes"]["CPIAUCSL"], mt.build_factor(f, cpi[0][:n], cpi[1][:n], d)["score"])


class Files(unittest.TestCase):
    def setUp(self):
        self.saved = mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, v.fetch_curve, v.DATA
        self.dir = Path(tempfile.mkdtemp())
        mt.CACHE = self.dir / "cache.json"
        mt.api_key = lambda: "test"
        mt.fetch_all = lambda key, today: t.fake_raw(today)
        v.fetch_curve = lambda key: fake_curve()
        v.DATA = self.dir / "data"

    def tearDown(self):
        mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, v.fetch_curve, v.DATA = self.saved

    def test_refresh_rewrites_the_frames(self):
        v.DATA.mkdir()
        (v.DATA / "yield_curve.json").write_text('{"old": true}')
        mt.get_snapshot(force=True)
        for name in ("yield_curve.json", "bias_history.json", "benchmark_levels.json"):
            body = json.loads((v.DATA / name).read_text())
            self.assertIn("generated", body, name)
        self.assertNotIn("old", json.loads((v.DATA / "yield_curve.json").read_text()))
        self.assertEqual(list(v.DATA.glob("*.tmp")), [])

    def test_export_writes_the_frames_too(self):
        mt.export(self.dir / "snapshot.json")
        self.assertTrue((v.DATA / "bias_history.json").exists())

    def test_one_failing_file_keeps_the_rest(self):
        v.fetch_curve = lambda key: (_ for _ in ()).throw(RuntimeError("FRED down"))
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
