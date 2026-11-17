"""Run: python3 test_macro_terminal.py   (no FRED key or network needed)"""
import json
import math
import random
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from functools import partial
from http.server import ThreadingHTTPServer

import macro_terminal as mt

TODAY = date(2026, 11, 13)


def monthly(n, end=date(2026, 10, 1)):
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def index_series(n, rates):
    """A price-style index growing by rates[i] percent a month."""
    vals, v = [], 100.0
    for i in range(n):
        v *= 1 + rates(i) / 100
        vals.append(v)
    return monthly(n), vals


def fake_raw(today=TODAY, seed=7):
    """Synthetic FRED responses with the right shapes. Used by the tests and to draw the page offline."""
    rng = random.Random(seed)
    obs = {}

    def put(sid, dates, vals):
        obs[sid] = [{"date": d.isoformat(), "value": "%.4f" % v} for d, v in zip(dates, vals)]

    days = [today - timedelta(days=i) for i in range(12 * 366) if (today - timedelta(days=i)).weekday() < 5][::-1]
    weeks = [today - timedelta(days=7 * i + 3) for i in range(12 * 52)][::-1]
    months, quarters = monthly(144), [d for d in monthly(144) if d.month in (1, 4, 7, 10)]
    for f in mt.FACTORS:
        dates = {"d": days, "w": weeks, "m": months, "q": quarters}[f["freq"]]
        if f["kind"] == "level":
            v, vals = rng.uniform(2, 5) / f["scale"], []
            for _ in dates:
                v += rng.gauss(0, 0.02 if f["freq"] == "d" else 0.08) / f["scale"]
                vals.append(v)
        else:
            v, vals, drift = 100000.0, [], rng.uniform(0.1, 0.3)
            for i, _ in enumerate(dates):
                v *= 1 + (drift + 0.15 * math.sin(i / 9 + seed) + rng.gauss(0, 0.1)) / 100
                vals.append(v)
        put(f["id"], dates, vals)
    for i, sid in enumerate(mt.EXTRA):
        if sid not in obs:
            put(sid, days, [3.5 + 0.15 * i + 0.3 * math.sin(j / 60) for j in range(len(days))])
    obs["CPIAUCSL"][-13]["value"] = "."  # a missing month, as October 2025 really was
    put("USREC", months, [1.0 if (d.year, d.month) in ((2020, 3), (2020, 4)) else 0.0 for d in months])
    for sid, shift in (("T10Y3M", 0.0), ("T10Y2Y", 0.3)):  # a curve that inverts and recovers
        put(sid, days, [0.6 + shift + 1.4 * math.sin(j / 400.0) + rng.gauss(0, 0.03) for j in range(len(days))])
    for n, sid in enumerate(("BAMLC0A3CA", "BAMLC0A4CBBB", "BAMLH0A1HYBB")):  # ICE spreads: three years, ordered by quality
        put(sid, days[-780:], [0.7 + 0.45 * n * (1 + n) / 2 + 0.2 * (n + 1) * math.sin(j / 90.0) + rng.gauss(0, 0.01) for j in range(780)])
    release_of = {f["id"]: {"id": 100 + n, "name": f["label"] + " release"}
                  for n, f in enumerate(mt.FACTORS) if f["freq"] != "d"}
    release_dates = {str(r["id"]): [(today + timedelta(days=3 + 2 * n)).isoformat(), "2026-01-09"]
                     for n, r in enumerate(release_of.values())}
    sp, level = [], 20.0
    for i in range((today - date(1949, 12, 1)).days + 1):
        d = date(1949, 12, 1) + timedelta(days=i)
        if d.weekday() < 5:
            level *= 1 + 0.0003 + 0.008 * math.sin(i / 37.0) / 10 + rng.gauss(0, 0.006)
            sp.append([d.isoformat(), round(level, 2)])
    fed = [dict(kind="Policy release", title="Federal Reserve issues FOMC statement", date=(today - timedelta(days=17)).isoformat(),
                link="https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm"),
           dict(kind="Speech", title="A sample speech title for the offline page", date=(today - timedelta(days=4)).isoformat(),
                link="https://www.federalreserve.gov/newsevents/speech/sample.htm")]
    sectors = {sym: [[d.isoformat(), 100 + (n - 5) * 0.12 * j + rng.gauss(0, 0.2)] for j, d in enumerate(days[-63:])]
               for n, sym in enumerate(mt.SECTORS)}
    raw = dict(obs=obs, errors={}, release_of=release_of, release_dates=release_dates, sp500=sp, fed=fed, sectors=sectors)
    if mt.benchmarks:  # benchmarks (beta)
        from test_benchmarks import fake_closes
        raw["benchmarks"] = fake_closes(today)
    return raw


class Maths(unittest.TestCase):
    def test_pct_pace_annualises(self):
        dates, vals = index_series(40, lambda i: 0.25)
        self.assertAlmostEqual(mt.pace(dates, vals, 39, 3, "pct"), (1.0025 ** 12 - 1) * 100, places=6)
        self.assertAlmostEqual(mt.pace(dates, vals, 39, 12, "pct"), (1.0025 ** 12 - 1) * 100, places=6)

    def test_pace_uses_real_months_across_a_gap(self):
        dates, vals = index_series(40, lambda i: 0.25)
        del dates[-2], vals[-2]  # one release never published
        self.assertAlmostEqual(mt.pace(dates, vals, len(vals) - 1, 3, "pct"), (1.0025 ** 12 - 1) * 100, places=6)

    def test_diff_and_level(self):
        dates = monthly(6)
        self.assertEqual(mt.pace(dates, [0, 10, 20, 30, 40, 110], 5, 3, "diff"), 30)
        self.assertEqual(mt.pace(dates, [1, 2, 3, 4, 5, 6], 5, 3, "level"), 5)

    def test_acceleration_scores_with_sign(self):
        # Noise for nine years, then three hot months: the short pace runs ahead of the long one.
        rng = random.Random(1)
        dates, vals = index_series(120, lambda i: 0.6 if i >= 117 else 0.2 + rng.gauss(0, 0.05))
        z = mt.signal(dates, vals, "m", "pct")["z"]
        self.assertGreater(z, mt.THRESHOLD)
        self.assertEqual(mt.score(z, 1), 1)
        self.assertEqual(mt.score(z, -1), -1)
        self.assertEqual(mt.score(0.2, 1), 0)

    def test_too_little_history_is_not_scored(self):
        dates, vals = index_series(20, lambda i: 0.2)
        self.assertIsNone(mt.signal(dates, vals, "m", "pct"))

    def test_probit_matches_the_ny_fed_worked_example(self):
        self.assertAlmostEqual(mt.recession_probit(-0.5), 0.414, places=3)
        self.assertLess(mt.recession_probit(2.0), 0.05)

    def test_bias_bands(self):
        self.assertEqual([mt.bias(s) for s in (0.6, 0.2, 0.0, -0.2, -0.5)],
                         ["Very bullish", "Bullish", "Neutral", "Bearish", "Very bearish"])

    def test_market_score_applies_weights_and_skips(self):
        factors = [dict(id="A", group="growth", score=1), dict(id="B", group="inflation", score=1),
                   dict(id="C", group="inflation", score=None)]
        m = dict(weights=dict(growth=1, inflation=-2), skip=[])
        self.assertAlmostEqual(mt.market_score(m, factors)[0], (1 - 2) / 3)
        self.assertAlmostEqual(mt.market_score(dict(m, skip=["B"]), factors)[0], 1.0)

    def test_combine_and_asof(self):
        a = ([date(2026, 1, 1), date(2026, 1, 2)], [4.0, 4.5])
        b = ([date(2026, 1, 2)], [4.0])
        self.assertEqual(mt.combine(a, b), ([date(2026, 1, 2)], [0.5]))
        self.assertEqual(mt.asof(*a, date(2026, 1, 1)), 4.0)
        self.assertIsNone(mt.asof(*a, date(2025, 1, 1)))


class History(unittest.TestCase):
    def test_election_days(self):
        self.assertEqual([mt.election_day(y).day for y in (1950, 2018, 2022, 2026)], [7, 6, 8, 3])

    def test_midterm_windows_on_a_known_path(self):
        # A market that gains 0.05% every weekday: every window is up, none has a drawdown, 2026 is still running.
        dates, closes, v, d = [], [], 10.0, date(1949, 12, 1)
        while d <= TODAY:
            if d.weekday() < 5:
                v *= 1.0005
                dates.append(d)
                closes.append(v)
            d += timedelta(days=1)
        m = mt.midterm_windows(dates, closes, TODAY)
        self.assertEqual((m["stats"]["n"], m["stats"]["positive"]), (19, 19))
        self.assertEqual(m["windows"][0]["year"], 1950)
        self.assertAlmostEqual(m["windows"][-1]["ret"], (1.0005 ** 261 - 1) * 100, delta=0.2)
        self.assertEqual(m["stats"]["worst_drawdown"], 0)
        self.assertEqual(len(m["stats"]["avg_path"]), 53)
        self.assertEqual((m["current"]["year"], m["current"]["days"], len(m["current"]["path"])), (2026, 10, 2))

    def test_drawdown_is_measured_inside_the_window(self):
        dates = [date(2022, 11, 7) + timedelta(days=i) for i in range(400)]
        closes = [100.0] * 400
        closes[50:60] = [80.0] * 10  # a 20% hole after the 2022 election, then a full recovery
        w = mt.midterm_windows(dates, closes, date(2023, 12, 1))["windows"][0]
        self.assertEqual((w["ret"], w["drawdown"]), (0.0, -20.0))

    def test_recession_history_is_monthly_and_ends_on_the_latest_reading(self):
        dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(70)]
        d, p = mt.recession_history(dates, [1.0] * 40 + [-0.5] * 30)
        self.assertEqual(d[:2], [date(2026, 9, 1), date(2026, 10, 1)])
        self.assertEqual(d[-1], dates[-1])
        self.assertAlmostEqual(p[0], mt.recession_probit(1.0) * 100)
        self.assertAlmostEqual(p[-1], 41.4, places=1)  # the last 21 readings are all -0.5

    def test_sector_returns(self):
        days = [(date(2026, 10, 1) + timedelta(days=i)).isoformat() for i in range(43)]
        closes = {"XLK": [[d, 100.0] for d in days[:-1]] + [[days[-1], 90.0]], "XLE": [[d, 50.0] for d in days[:-1]] + [[days[-1], 55.0]],
                  "SPY": [[d, 400.0] for d in days], "XLV": []}
        got = mt.sector_returns(closes)
        self.assertEqual([(r["label"], r["ret"]) for r in got["sectors"]], [("Energy", 10.0), ("Technology", -10.0)])
        self.assertEqual((got["market"], got["date"]), (0.0, days[-1]))
        self.assertIsNone(mt.sector_returns({"XLV": []}))

    def test_every_regime_has_leanings(self):
        self.assertEqual(set(mt.LEANINGS), {name for name, _ in mt.REGIMES.values()})

    def test_recession_ranges(self):
        d = monthly(6, date(2020, 6, 1))
        self.assertEqual(mt.recession_ranges(d, [0, 0, 1, 1, 0, 0]), [["2020-03-01", "2020-04-01"]])

    def test_views(self):
        dates, vals = index_series(40, lambda i: 0.25)
        cpi = next(f for f in mt.FACTORS if f["id"] == "CPIAUCSL")
        views = mt.views_for(cpi, dates, vals)
        self.assertEqual([v["name"] for v in views], ["y/y", "3m annualised", "level"])
        self.assertAlmostEqual(views[0]["points"][-1][1], (1.0025 ** 12 - 1) * 100, places=3)
        jobs = next(f for f in mt.FACTORS if f["id"] == "PAYEMS")
        self.assertEqual(mt.views_for(jobs, dates, vals)[0]["name"], "monthly change")

    def test_feed_keeps_only_fed_links(self):
        xml = b"""<rss><channel>
          <item><title>FOMC  statement</title><link>https://www.federalreserve.gov/a.htm</link><pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
          <item><title>Elsewhere</title><link>https://example.com/x</link><pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
          <item><title>No date</title><link>https://www.federalreserve.gov/b.htm</link></item></channel></rss>"""
        items = mt.parse_feed(xml, "Policy release")
        self.assertEqual([(i["title"], i["date"]) for i in items], [("FOMC statement", "2026-10-28"), ("No date", None)])

    def test_sp500_history_with_and_without_yfinance(self):
        class Close:
            def dropna(self):
                return self

            def items(self):
                return [(datetime(1950, 1, 3) + timedelta(days=i), 16.0 + i) for i in range(1200)]

        class Fake:
            @staticmethod
            def Ticker(symbol):
                return type("T", (), {"history": lambda self, **kw: {"Close": Close()}})()

        saved = sys.modules.get("yfinance")
        try:
            sys.modules["yfinance"] = Fake
            self.assertEqual(mt.sp500_history()[0], ["1950-01-03", 16.0])
            self.assertEqual(set(mt.sector_history()), set(mt.SECTORS))
            sys.modules["yfinance"] = None  # makes the import fail
            with self.assertRaisesRegex(RuntimeError, "pip install yfinance"):
                mt.sp500_history()
        finally:
            sys.modules.pop("yfinance", None)
            if saved:
                sys.modules["yfinance"] = saved


class Schedule(unittest.TestCase):
    NY = mt.NEW_YORK

    def at(self, *a):
        return datetime(*a, tzinfo=self.NY)

    def test_slots_follow_the_release_times(self):
        tue = self.at(2026, 11, 17, 9, 0)
        self.assertEqual(mt.last_slot(tue), self.at(2026, 11, 17, 8, 37))
        self.assertEqual(mt.next_slot(tue), self.at(2026, 11, 17, 10, 7))
        self.assertEqual(mt.next_slot(self.at(2026, 11, 17, 18, 0)), self.at(2026, 11, 18, 8, 37))

    def test_weekends_carry_friday_evening(self):
        sat = self.at(2026, 11, 21, 12, 0)
        self.assertEqual(mt.last_slot(sat), self.at(2026, 11, 20, 17, 7))
        self.assertEqual(mt.next_slot(sat), self.at(2026, 11, 23, 8, 37))
        self.assertEqual(mt.last_slot(self.at(2026, 11, 23, 7, 0)), self.at(2026, 11, 20, 17, 7))

    @unittest.skipIf(mt.NEW_YORK is None, "no time-zone database")
    def test_times_stay_on_new_york_clock_across_daylight_saving(self):
        self.assertEqual(self.at(2026, 11, 2, 8, 37).utcoffset(), timedelta(hours=-5))
        self.assertEqual(self.at(2026, 10, 30, 8, 37).utcoffset(), timedelta(hours=-4))

    def test_workflow_runs_at_the_same_times(self):
        workflow = (mt.HERE.parent / ".github" / "workflows" / "pages.yml").read_text()
        for h, m in mt.REFRESH_AT:
            self.assertIn('cron: "%d %d * * 1-5"' % (m, h), workflow)
        self.assertEqual(workflow.count('timezone: "America/New_York"'), len(mt.REFRESH_AT))

    def test_export_writes_the_schedule_for_the_hosted_page(self):
        saved = mt.api_key, mt.fetch_all, mt.write_viz
        out = mt.HERE / "snapshot.test.json"
        try:
            mt.api_key, mt.fetch_all = (lambda: "k"), (lambda key, today: fake_raw(today))
            mt.write_viz = lambda *a: None  # replays: test_viz_frames covers them, and must not touch the real data folder
            mt.export(out)
            snap = json.loads(out.read_text())
            self.assertIn("next_refresh", snap)
            self.assertEqual(len(snap["refresh_at"]), len(mt.REFRESH_AT))
        finally:
            mt.api_key, mt.fetch_all, mt.write_viz = saved
            out.unlink(missing_ok=True)

    def test_tick_refreshes_once_then_backs_off_on_failure(self):
        calls = []
        saved = mt.get_snapshot, mt.cached_ts, mt.last_slot
        try:
            mt.last_slot = lambda now: datetime.now(self.NY) - timedelta(minutes=5)
            mt.cached_ts = lambda: time.time() - 3600  # fetched before the scheduled time: due
            mt.get_snapshot = lambda: calls.append(1) or (_ for _ in ()).throw(RuntimeError("down"))
            tried = mt.tick(0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(mt.tick(tried), tried)  # a failure waits RETRY_MINUTES before trying again
            self.assertEqual(len(calls), 1)
            mt.cached_ts = lambda: time.time()  # fetched since the scheduled time: nothing to do
            self.assertEqual(mt.tick(0), 0)
            self.assertEqual(len(calls), 1)
        finally:
            mt.get_snapshot, mt.cached_ts, mt.last_slot = saved


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.snap = mt.build_snapshot(fake_raw(), TODAY)

    def test_everything_is_built_and_serialisable(self):
        s = json.loads(json.dumps(self.snap))
        self.assertEqual(len(s["factors"]), len(mt.FACTORS))
        self.assertTrue(all(f["score"] in (-1, 0, 1) for f in s["factors"]))
        self.assertEqual(len(s["markets"]), len(mt.MARKETS))
        self.assertTrue(all(-1 <= m["score"] <= 1 for m in s["markets"]))
        self.assertIn(s["regime"]["name"], [r[0] for r in mt.REGIMES.values()])
        self.assertEqual(len(s["rates"]["curve"]["now"]), len(mt.CURVE))
        self.assertTrue(0 < s["recession"]["curve"]["probability"] < 1)
        self.assertTrue(s["calendar"] and s["calendar"][0]["date"] >= TODAY.isoformat())
        self.assertEqual(s["errors"], {})
        self.assertEqual(s["recessions"], [["2020-03-01", "2020-04-01"]])
        self.assertEqual(s["midterm"]["stats"]["n"], 19)
        self.assertEqual(s["midterm"]["current"]["year"], 2026)
        self.assertEqual({e["id"] for e in s["extras"]}, {e[0] for e in mt.CHART_EXTRAS})
        credit = next(e for e in s["extras"] if e["id"] == "credit")
        self.assertEqual([v["name"] for v in credit["views"]], ["Baa", "Single-A", "BBB", "BB", "Ladder"])
        self.assertEqual([line["name"] for line in credit["views"][-1]["lines"]], ["BB", "BBB", "Single-A"])
        self.assertTrue(all(v.get("points") or v.get("lines") for v in credit["views"]))
        self.assertEqual(len(s["fed"]), 2)
        self.assertEqual(len(s["regime"]["leanings"]), 3)
        self.assertEqual([m["id"] for m in s["markets"]], ["spx", "ndx", "rut", "eafe", "em", "ust", "agg", "usd", "gold"])
        if mt.benchmarks:  # benchmarks (beta)
            self.assertEqual(len(s["benchmarks"]["lines"]), len(mt.benchmarks.LINES))
        self.assertEqual(len(s["sectors"]["sectors"]), len(mt.SECTORS) - 1)
        self.assertIsNotNone(s["sectors"]["market"])
        prob = next(e for e in s["extras"] if e["id"] == "recprob")["views"][0]["points"]
        self.assertAlmostEqual(prob[-1][1], s["recession"]["curve"]["probability"] * 100, places=1)  # chart ends on the Board's figure

    def test_a_missing_credit_view_drops_alone(self):
        raw = fake_raw()
        del raw["obs"]["BAMLH0A1HYBB"]
        credit = next(e for e in mt.build_snapshot(raw, TODAY)["extras"] if e["id"] == "credit")
        self.assertEqual([v["name"] for v in credit["views"]], ["Baa", "Single-A", "BBB", "Ladder"])
        self.assertEqual([line["name"] for line in credit["views"][-1]["lines"]], ["BBB", "Single-A"])

    def test_the_optional_sources_can_be_missing(self):
        raw = fake_raw()
        del raw["sp500"], raw["fed"], raw["sectors"]
        raw["errors"]["sp500"] = "needs yfinance"
        s = mt.build_snapshot(raw, TODAY)
        self.assertIsNone(s["midterm"])
        self.assertIsNone(s["sectors"])
        self.assertEqual(s["fed"], [])
        self.assertEqual(len(s["markets"]), len(mt.MARKETS))

    def test_a_failed_series_is_reported_not_fatal(self):
        raw = fake_raw()
        del raw["obs"]["UNRATE"]
        raw["errors"]["UNRATE"] = "Bad Request"
        s = mt.build_snapshot(raw, TODAY)
        unrate = next(f for f in s["factors"] if f["id"] == "UNRATE")
        self.assertIsNone(unrate["score"])
        self.assertEqual(s["groups"]["labor"]["scored"], s["groups"]["labor"]["total"] - 1)
        self.assertEqual(s["errors"]["UNRATE"], "Bad Request")

    def test_stale_series_is_shown_but_not_scored(self):
        s = mt.build_snapshot(fake_raw(), TODAY + timedelta(days=200))
        cpi = next(f for f in s["factors"] if f["id"] == "CPIAUCSL")
        self.assertTrue(cpi["stale"])
        self.assertIsNone(cpi["score"])
        self.assertIsNotNone(cpi["value"])


class Server(unittest.TestCase):
    def get(self, path):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s%s" % (self.port, path)) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(mt.Handler, directory=str(mt.HERE / "static")))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.saved = mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, mt.write_viz
        mt.CACHE = mt.HERE / "cache.test.json"
        mt.write_viz = lambda *a: None  # replays: never write the real data folder from a test

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        mt.CACHE.unlink(missing_ok=True)
        mt.CACHE, mt.api_key, mt.fetch_all, mt.last_slot, mt.write_viz = self.saved

    def test_no_key_is_a_setup_answer(self):
        def no_key():
            raise mt.Setup("No FRED key found.")
        mt.api_key = no_key
        code, body = self.get("/api/snapshot")
        self.assertEqual((code, json.loads(body)["error"]), (503, "setup"))

    def test_snapshot_is_cached_and_survives_an_outage(self):
        mt.api_key = lambda: "k"
        mt.fetch_all = lambda key, today: fake_raw(today)
        code, body = self.get("/api/snapshot")
        self.assertEqual(code, 200)

        def down(key, today):
            raise RuntimeError("Could not reach FRED")
        mt.fetch_all = down
        snap = json.loads(body)
        snap["fetched_ts"] -= 3600  # an hour old, and no scheduled time since: still fresh unless a refresh is forced
        mt.CACHE.write_text(json.dumps(snap))
        mt.last_slot = lambda now: now - timedelta(hours=2)
        fresh = json.loads(self.get("/api/snapshot")[1])
        self.assertNotIn("stale_reason", fresh)
        self.assertIn("next_refresh", fresh)
        self.assertEqual(fresh["refresh_at"], ["8:37 AM", "10:07 AM", "5:07 PM"])
        mt.last_slot = lambda now: now - timedelta(minutes=30)  # a scheduled time has passed since the fetch
        self.assertEqual(json.loads(self.get("/api/snapshot")[1])["stale_reason"], "Could not reach FRED")
        self.assertEqual(json.loads(self.get("/api/snapshot?refresh=1")[1])["stale_reason"], "Could not reach FRED")

    def test_static_files_and_no_escape(self):
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/../macro_terminal.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
