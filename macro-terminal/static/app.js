"use strict";
// Macro Terminal front end. Every figure comes from /api/snapshot; nothing is calculated here except layout.

const app = document.getElementById("app");
const refreshBtn = document.getElementById("refresh");
const LOCAL = /^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname);
const updated = document.getElementById("updated");
let S = null;          // the snapshot
let market = "spx";    // selected market on the board

// Preferences live in this browser only. Storage can be blocked, so every call is guarded.
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem("mt." + key)) ?? fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem("mt." + key, JSON.stringify(value)); } catch (e) { /* private mode: keep going */ } },
};
const DEFAULT_CHARTS = ["PAYEMS", "UNRATE", "PCEPILFE", "CPIAUCSL", "DGS10", "slope", "credit", "recprob", "GDPC1"];
const freshPrefs = () => ({ ids: [...DEFAULT_CHARTS], view: {}, range: 5, shade: true });
let prefs = Object.assign(freshPrefs(), store.get("snapshot", {}));
// Charts that were merged into one card keep their place in a saved layout.
prefs.ids = [...new Set(prefs.ids.map((id) => ({ "10y2y": "slope", "10y3m": "slope" }[id] || id)))];
const RAMP = ["", "line--ago", "line--old"];  // one hue stepped in lightness, always in this order
const VIEW_LABELS = { "y/y": "Year on year", "3m annualised": "3-month pace", "q/q annualised": "Quarterly pace", "level": "Level", "monthly change": "Monthly change" };
const SIDE_SOURCES = { sp500: "S&P 500 history", sectors: "Sector prices", fed: "Fed feeds" };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, dp = 1) => v == null ? "n/a" : (+v.toFixed(dp) || 0).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }).replace("-", "−");
const signed = (v, dp = 0) => v == null ? "n/a" : (+v.toFixed(dp) > 0 ? "+" : "") + num(v, dp);
const at = (iso) => new Date(iso + "T12:00:00");
const day = (iso) => at(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const month = (iso) => at(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
const stamp = (d, freq) => freq === "q" ? "Q" + (Math.floor(d.getMonth() / 3) + 1) + " " + d.getFullYear()
  : freq === "m" ? d.toLocaleDateString("en-US", { month: "short", year: "numeric" })
  : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const period = (f) => f.date ? stamp(at(f.date), f.freq) : "n/a";
const val = (f, v, plus) => v == null ? "n/a" : (plus ? signed(v, f.dp) : num(v, f.dp)) + f.unit;
const paces = (f) => f.freq === "q" ? ["Latest quarter, annualised", "Last four quarters"]
  : f.freq === "w" ? ["4-week average", "1-year average"]
  : f.freq === "d" ? ["1-month average", "1-year average"]
  : f.kind === "pct" ? ["Last 3 months, annualised", "Last 12 months"] : ["3-month average", "12-month average"];
const wordFor = (f, score) => score > 0 ? S.groups[f.group].up_word : score < 0 ? S.groups[f.group].down_word : "steady";
const word = (f) => f.score == null ? (f.stale ? "stale" : "not scored") : wordFor(f, f.score);
const catalog = () => [
  // A factor already drawn inside a multi-view chart (Baa in the credit chart) is not offered twice.
  ...S.factors.filter((f) => f.views.length && !S.extras.some((e) => e.views.length > 1 && e.sources.includes(f.id))).map((f) => ({ id: f.id, label: f.label, freq: f.freq, group: S.groups[f.group].label, views: f.views })),
  ...S.extras.map((e) => ({ ...e, group: "Rates and markets" })),
];

function meter(v) {  // v from -1 to +1, drawn from the zero line
  const w = Math.min(50, Math.abs(v) * 50).toFixed(1);
  return `<div class="meter" aria-hidden="true">${v ? `<span class="${v > 0 ? "pos" : "neg"}" style="width:${w}%"></span>` : ""}</div>`;
}

// ---------- charts: inline SVG drawn for the data ----------

function ticks(lo, hi, n = 4) {
  const raw = (hi - lo) / n || 1, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-6; t += step) out.push(Math.abs(t) < step * 1e-6 ? 0 : t);
  return out;
}

function scale(values, pad) {
  const tk = ticks(Math.min(...values) - pad, Math.max(...values) + pad);
  return { tk, lo: Math.min(tk[0], Math.min(...values) - pad), hi: Math.max(tk[tk.length - 1], Math.max(...values) + pad) };
}

const path = (pts, x, y) => pts.map((p, i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join("");

function spark(f) {
  const all = f.views.length ? f.views[0].points : [];
  const from = all.length ? at(all[all.length - 1][0]).getTime() - 5 * 365.25 * 864e5 : 0;
  const pts = all.filter((p) => at(p[0]).getTime() >= from);
  if (pts.length < 2) return "";
  const vs = pts.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs);
  const x = (i) => 1 + (i / (pts.length - 1)) * 118, y = (v) => 26 - ((v - lo) / (hi - lo || 1)) * 24;
  return `<svg class="spark" viewBox="0 0 120 28" aria-hidden="true"><path class="line line--thin" d="${path(pts.map((p, i) => [i, p[1]]), x, y)}"/></svg>`;
}

// One or more time series with gridlines, optional recession shading and a hover readout.
function drawChart(box, c, view, o) {
  const end = (l) => l.pts[l.pts.length - 1];
  let lines = (view.lines || [{ name: "", points: view.points }]).map((l) => ({ name: l.name, pts: l.points.map((p) => [at(p[0]).getTime(), p[1]]) }));
  const t1 = Math.max(...lines.map((l) => end(l)[0])), from = o.years ? t1 - o.years * 365.25 * 864e5 : -Infinity;
  lines = lines.map((l) => ({ ...l, pts: l.pts.filter((p) => p[0] >= from) })).filter((l) => l.pts.length > 1);
  if (!lines.length) { box.innerHTML = `<p class="muted">No history to draw.</p>`; return; }
  const W = Math.max(280, box.clientWidth), H = o.height, L = 56, R = 16, T = 12, B = 28;
  const vs = lines.flatMap((l) => l.pts.map((p) => p[1])), { tk, lo, hi } = scale(vs, (Math.max(...vs) - Math.min(...vs)) * 0.08 || 1);
  const t0 = Math.min(...lines.map((l) => l.pts[0][0]));
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const dp = tk.some((t) => t % 1) ? Math.max(1, view.dp) : 0;
  let g = o.shade ? S.recessions.map(([a, b]) => {
    const x0 = Math.max(at(a).getTime(), t0), x1 = Math.min(at(b).getTime() + 31 * 864e5, t1);  // the range names months: shade to the end of the last
    return x1 > x0 ? `<rect class="shade" x="${x(x0).toFixed(1)}" y="${T}" width="${(x(x1) - x(x0)).toFixed(1)}" height="${H - T - B}"/>` : "";
  }).join("") : "";
  g += tk.map((t) => `<line class="grid${t === 0 ? " grid--zero" : ""}" x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="axis" x="${L - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${num(t, dp)}${view.unit}</text>`).join("");
  const y0 = new Date(t0).getFullYear() + 1, y1 = new Date(t1).getFullYear();
  const every = Math.max(1, Math.ceil((y1 - y0 + 1) / Math.floor((W - L - R) / 52)));  // thin the year labels on narrow charts
  for (let yr = y1; yr >= y0; yr -= every) g += `<text class="axis" x="${x(new Date(yr, 0, 1).getTime()).toFixed(1)}" y="${H - 8}" text-anchor="middle">${yr}</text>`;
  const span = o.years ? `${o.years} ${o.years === 1 ? "year" : "years"}` : "all history";
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Chart of ${esc(c.label)}, ${esc(view.name)}, ${span} to ${stamp(new Date(t1), c.freq)}">${g}
    <line class="cursor" y1="${T}" y2="${H - B}" hidden/>${lines.map((l, i) => `<path class="line ${RAMP[i] ?? "line--old"}" d="${path(l.pts, x, y)}"/>`).reverse().join("")}<circle class="dot" r="3.5"/></svg>`;

  const svg = box.firstElementChild, rule = svg.querySelector(".cursor"), dot = svg.querySelector(".dot");
  const near = (l, t) => l.pts.reduce((best, p) => Math.abs(p[0] - t) < Math.abs(best[0] - t) ? p : best);
  const show = (t, hovering) => {
    const p = near(lines[0], t);  // the first line leads: the rule and the dot follow it
    o.readout.innerHTML = lines.map((l) => { const q = near(l, p[0]); return `<span>${l.name ? `<span class="muted">${esc(l.name)}</span> ` : ""}${view.name === "monthly change" ? signed(q[1], view.dp) : num(q[1], view.dp)}${view.unit}</span>`; }).join("")
      + `<span class="muted">${stamp(new Date(p[0]), c.freq)}</span>`;
    dot.setAttribute("cx", x(p[0]).toFixed(1)); dot.setAttribute("cy", y(p[1]).toFixed(1));
    rule.setAttribute("x1", x(p[0]).toFixed(1)); rule.setAttribute("x2", x(p[0]).toFixed(1));
    rule.toggleAttribute("hidden", !hovering);
  };
  box.onpointermove = (e) => {
    const r = svg.getBoundingClientRect();
    show(t0 + (((e.clientX - r.left) * (W / r.width) - L) / (W - L - R)) * (t1 - t0), true);
  };
  box.onpointerleave = () => show(t1, false);
  show(t1, false);
}

function curveChart(c, width) {
  const W = Math.max(320, width), H = 280, L = 44, R = 16, T = 12, B = 28;
  const { tk, lo, hi } = scale([...c.now, ...c.three_months, ...c.one_year].filter((v) => v != null), 0.1);
  const x = (i) => L + (i / (c.tenors.length - 1)) * (W - L - R), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const series = (vals) => path(vals.map((v, i) => [i, v]).filter((p) => p[1] != null), x, y);
  const g = tk.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="axis" x="${L - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${num(t, 1)}%</text>`).join("")
    + c.tenors.map((t, i) => `<text class="axis" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${t}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Chart of the Treasury yield curve now, three months ago and one year ago">${g}<path class="line line--old" d="${series(c.one_year)}"/><path class="line line--ago" d="${series(c.three_months)}"/><path class="line" d="${series(c.now)}"/></svg>`;
}

function midtermChart(m, width) {
  const W = Math.max(300, width), H = 380, L = 48, R = 16, T = 12, B = 28, cur = m.current;
  const { tk, lo, hi } = scale(m.windows.flatMap((w) => w.path).concat(cur ? cur.path : []), 2);
  const x = (wk) => L + (wk / 52) * (W - L - R), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const line = (p, cls) => `<path class="line ${cls}" d="${path(p.map((v, i) => [i, v]), x, y)}"/>`;
  const g = tk.map((t) => `<line class="grid${t === 0 ? " grid--zero" : ""}" x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="axis" x="${L - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${signed(t)}%</text>`).join("")
    + [["Election", 0, "start"], ["3 months", 13, "middle"], ["6 months", 26, "middle"], ["9 months", 39, "middle"], ["12 months", 52, "end"]]
      .map(([label, wk, anchor]) => `<text class="axis axis--name" x="${x(wk).toFixed(1)}" y="${H - 8}" text-anchor="${anchor}">${label}</text>`).join("");
  const end = cur && cur.path.length ? `<circle class="dot" cx="${x(cur.path.length - 1).toFixed(1)}" cy="${y(cur.path[cur.path.length - 1]).toFixed(1)}" r="4"/>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Chart of the S&amp;P 500 over the 12 months after each midterm election since 1950, with the average and the ${cur ? cur.year : "latest"} window">${g}
    ${m.windows.map((w) => line(w.path, "line--old line--thin")).join("")}${line(m.stats.avg_path, "line--ago")}${cur ? line(cur.path, "") : ""}${end}</svg>`;
}

function regimeMap(r) {
  const p = (v) => 140 + Math.max(-1.6, Math.min(1.6, v)) * 62.5;  // +/-1.6 typical moves fills the box
  const label = (name, x, y, anchor) => `<text class="axis axis--name${r.name === name ? " axis--on" : ""}" x="${x}" y="${y}" text-anchor="${anchor}">${name}</text>`;
  return `<svg viewBox="0 0 280 280" role="img" aria-label="Chart of the regime: growth momentum ${signed(r.growth, 2)}, inflation momentum ${signed(r.inflation, 2)}, which is ${esc(r.name)}">
    <rect class="grid" x="40" y="40" width="200" height="200" fill="none"/>
    <line class="grid grid--zero" x1="140" x2="140" y1="40" y2="240"/><line class="grid grid--zero" x1="40" x2="240" y1="140" y2="140"/>
    ${label("Stagflation", 48, 58, "start")}${label("Reflation", 232, 58, "end")}${label("Slowdown", 48, 230, "start")}${label("Goldilocks", 232, 230, "end")}
    <text class="axis axis--name" x="140" y="262" text-anchor="middle">Growth and jobs momentum</text>
    <text class="axis axis--name" x="140" y="28" text-anchor="middle">Inflation momentum</text>
    <circle class="dot" cx="${p(r.growth).toFixed(1)}" cy="${(280 - p(r.inflation)).toFixed(1)}" r="6"/></svg>`;
}

// ---------- what changed since the last visit ----------

const fingerprint = () => ({
  at: S.fetched_at, regime: S.regime ? S.regime.name : null,
  bias: Object.fromEntries(S.markets.map((m) => [m.id, m.bias])),
  score: Object.fromEntries(S.factors.map((f) => [f.id, f.score])),
  date: Object.fromEntries(S.factors.filter((f) => f.freq === "m" || f.freq === "q").map((f) => [f.id, f.date])),
});

function changes() {
  const was = store.get("seen", null);
  if (!was) { store.set("seen", fingerprint()); return ""; }  // first visit: nothing to compare with yet
  const out = [];
  if (was.regime && S.regime && was.regime !== S.regime.name) out.push(`The regime moved from ${esc(was.regime)} to ${esc(S.regime.name)}.`);
  S.markets.forEach((m) => { if (was.bias[m.id] && was.bias[m.id] !== m.bias) out.push(`${esc(m.label)} went from ${esc(was.bias[m.id].toLowerCase())} to ${m.bias.toLowerCase()}.`); });
  S.factors.forEach((f) => {
    if (was.date[f.id] && f.date && was.date[f.id] !== f.date) out.push(`New ${esc(f.label)} data for ${period(f)}: ${val(f, f.value, f.kind === "diff")}.`);
    if (f.score != null && was.score[f.id] != null && was.score[f.id] !== f.score) out.push(`${esc(f.label)} now reads ${word(f)}, was ${wordFor(f, was.score[f.id])}.`);
  });
  if (!out.length) { store.set("seen", fingerprint()); return ""; }
  return `<section class="notice changes"><h2>Since ${esc(new Date(was.at).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" }))}</h2>
    <ul>${out.map((t) => `<li>${t}</li>`).join("")}</ul><div><button class="btn" type="button" data-seen>Mark as seen</button></div></section>`;
}

// ---------- views ----------

function notices() {
  const out = [];
  if (S.stale_reason) out.push(`FRED could not be reached, so this is the read from ${esc(new Date(S.fetched_at).toLocaleString())}. ${esc(S.stale_reason)}`);
  const failed = Object.keys(S.errors).filter((k) => !SIDE_SOURCES[k]).length;
  if (failed) out.push(`${failed} series could not be loaded and ${failed === 1 ? "is" : "are"} left out of the scores. The <a href="#method">Method view</a> lists which.`);
  return out.map((t) => `<p class="notice" role="status">${t}</p>`).join("");
}

function midterm() {
  const m = S.midterm, intro = `<h2>The year after a midterm</h2>`;
  if (!m) return `<section>${intro}<p class="notice">${esc(S.errors.sp500 || "S&P 500 history did not load. Press Refresh to try again.")}</p></section>`;
  const s = m.stats, cur = m.current;
  const stats = [
    [`${s.positive} of ${s.n}`, "Windows that ended higher", "S&P 500, 12 months from election day, price only"],
    [`${signed(s.mean, 1)}%`, "Average 12-month return", `Median ${signed(s.median, 1)}%, from ${signed(s.low, 1)}% to ${signed(s.high, 1)}%`],
    [`${num(s.avg_drawdown, 1)}%`, "Average worst drop along the way", `Deepest was ${num(s.worst_drawdown, 1)}%, after the ${s.worst_year} vote`],
    cur && [`${signed(cur.ret, 1)}%`, `The ${cur.year} window so far`, `${cur.days} days in. The average window stood at ${signed(s.avg_path[cur.path.length - 1], 1)}% by now`],
  ].filter(Boolean).map((c) => `<li><span class="reading">${c[0]}</span><strong>${c[1]}</strong><span class="muted">${c[2]}</span></li>`).join("");
  const rows = m.windows.map((w) => `<tr><th scope="row">${day(w.date)}</th><td class="num">${signed(w.ret, 1)}%</td><td class="num">${num(w.drawdown, 1)}%</td></tr>`).join("");
  const key = (cls, label) => `<li><svg viewBox="0 0 20 4" aria-hidden="true"><path class="line ${cls}" d="M0 2H20"/></svg>${label}</li>`;
  return `<section>${intro}<p>What the S&amp;P 500 did in the 12 months after each midterm since 1950, against the window that ${cur ? "opened on " + day(cur.date) : "closed most recently"}.</p>
    <div class="panels midterm">
      <figure><div class="chart" data-chart="midterm"></div>
        <ul class="legend">${cur ? key("", cur.year + " so far") : ""}${key("line--ago", "Average of " + s.n)}${key("line--old line--thin", "Each past window")}</ul></figure>
      <div class="midterm__side"><ul class="checks">${stats}</ul>
        <p class="muted">${s.n} cases is a small sample, and each had its own rates, earnings and recession backdrop. Treat this as a base rate to weigh, not a forecast.</p>
      </div>
    </div>
    <details><summary>Every window since 1950</summary><div class="scroll"><table><thead><tr><th>Election day</th><th class="num">12-month return</th><th class="num">Worst drop inside</th></tr></thead><tbody>${rows}</tbody></table></div></details></section>`;
}

function sectorBars(sec) {
  const all = sec.sectors.map((r) => r.ret).concat(sec.market == null ? [] : [sec.market], [0]);
  const lo = Math.min(...all), span = (Math.max(...all) - lo) || 1, pos = (v) => (((v - lo) / span) * 100).toFixed(1);
  const mark = sec.market == null ? "" : `<i class="hbar__ref" style="left:${pos(sec.market)}%"></i>`;
  return `<ul class="bars">${sec.sectors.map((r) => `<li><span>${esc(r.label)}</span>
    <div class="hbar" aria-hidden="true"><span class="${r.ret >= 0 ? "pos" : "neg"}" style="left:${pos(Math.min(0, r.ret))}%;width:${((Math.abs(r.ret) / span) * 100).toFixed(1)}%"></span><i class="hbar__zero" style="left:${pos(0)}%"></i>${mark}</div>
    <span class="measured">${signed(r.ret, 1)}%</span></li>`).join("")}</ul>
    <p class="card__note muted">SPDR sector funds, price return over the month to ${day(sec.date)}.${sec.market == null ? "" : ` The dashed line is the S&amp;P 500 fund at ${signed(sec.market, 1)}%.`}</p>`;
}

function leanings() {
  const r = S.regime;
  if (!r) return "";
  const lean = (test) => S.markets.filter(test).map((m) => esc(m.label)).join(", ") || "none";
  const rows = r.leanings.concat([["This terminal now", `Leaning bullish: ${lean((m) => m.score >= 0.2)}. Leaning bearish: ${lean((m) => m.score <= -0.2)}. Neutral: ${lean((m) => Math.abs(m.score) < 0.2)}.`]])
    .map(([head, line], i) => `<li><strong>${esc(head)}</strong><span>${i < r.leanings.length ? esc(line) : line}</span></li>`).join("");
  return `<section><h2>How a ${esc(r.name.toLowerCase())} phase has tended to play out</h2>
    <p>What history says about this mix of growth and inflation, beside what actually led last month.</p>
    <div class="panels lean">
      <div class="lean__side"><ul class="rows">${rows}</ul>
        <p class="card__note muted">The first three lines are averages across past cycles from the Merrill Lynch Investment Clock, which calls this phase ${esc(r.clock)}. The clock places a phase by growth against trend and this terminal by momentum, so the match is approximate, and cycles can skip a phase or run backwards. It describes history and is not a recommendation.</p></div>
      <div class="lean__side"><h3>Sector moves, last month</h3>${S.sectors ? sectorBars(S.sectors) : `<p class="notice">${esc(S.errors.sectors || "Sector prices did not load. Press Refresh to try again.")}</p>`}</div>
    </div></section>`;
}

function board() {
  const m = S.markets.find((x) => x.id === market) || S.markets[0];
  const r = S.regime, rec = S.recession;
  const pulse = Object.values(S.groups).map((g) => `<li><span class="reading">${signed(g.net)}</span><strong>${esc(g.label)}: ${g.word}</strong><span class="muted">${g.up} up, ${g.down} down of ${g.scored} scored</span></li>`).join("");
  const checks = [
    rec.curve && [`${num(rec.curve.probability * 100, 0)}%`, "Chance of recession within 12 months", `NY Fed yield-curve model, 10-year minus 3-month at ${signed(rec.curve.spread, 2)} points`],
    rec.sahm && [num(rec.sahm.value, 2), "Sahm rule", `Signals a recession at 0.50. ${month(rec.sahm.date)}`],
    rec.smoothed && [`${num(rec.smoothed.value, 1)}%`, "Chance the economy was already in recession", `Chauvet-Piger model, ${month(rec.smoothed.date)}`],
    S.gdpnow && [`${num(S.gdpnow.value, 1)}%`, "GDP growth this quarter, tracked", "Atlanta Fed GDPNow, annualised"],
  ].filter(Boolean).map((c) => `<li><span class="reading">${c[0]}</span><strong>${c[1]}</strong><span class="muted">${c[2]}</span></li>`).join("");

  const tiles = S.markets.map((x) => `<a class="market" href="#board/${x.id}" ${x.id === m.id ? 'aria-current="true"' : ""}>
      <span class="market__name">${esc(x.label)}</span>
      <span class="chip ${x.score >= 0.2 ? "chip--pos" : x.score <= -0.2 ? "chip--neg" : ""}">${x.bias}</span>
      ${meter(x.score)}<span class="measured muted">${signed(x.score, 2)}</span></a>`).join("");

  const groups = Object.entries(S.groups).map(([key, g]) => {
    const w = m.weights[key];
    const rows = S.factors.filter((f) => f.group === key).map((f) => {
      const used = w !== 0 && f.score != null && !m.skip.includes(f.id);
      const c = used ? f.score * Math.sign(w) : 0;
      return `<li><a href="#indicators/${f.id}">${esc(f.label)}</a>${used ? meter(c) : `<span class="muted">${f.score == null ? word(f) : "not used"}</span>`}<span class="measured">${used ? signed(c) : ""}</span></li>`;
    }).join("");
    const net = S.factors.filter((f) => f.group === key && f.score != null && !m.skip.includes(f.id)).reduce((a, f) => a + f.score * Math.sign(w), 0);
    const how = w === 0 ? "Not part of this market's score" : `${g.word[0].toUpperCase() + g.word.slice(1)}, which ${net > 0 ? "helps" : net < 0 ? "hurts" : "is neutral for"} ${esc(m.label)}${Math.abs(w) > 1 ? ". Double weight" : ""}`;
    return `<div class="group"><div class="group__head"><h3>${esc(g.label)}</h3><span class="measured">${w === 0 ? "" : "net " + signed(net)}</span></div><p class="muted">${how}</p><ul class="factors">${rows}</ul></div>`;
  }).join("");

  return `${notices()}
  <section class="panels top">
    <div class="top__read"><h1>${r ? esc(r.name) : "No regime read"}</h1>
      <p class="lead">${r ? esc(r.blurb) + (r.weak ? " Both readings sit close to zero, so hold this one loosely." : "") : "Too few indicators loaded to place the economy."}</p>
      <ul class="pulse">${pulse}</ul></div>
    ${r ? `<figure class="top__map">${regimeMap(r)}<figcaption>Each axis is the average momentum of its indicators, in typical moves.</figcaption></figure>` : "<div></div>"}
    <div><h2>Cycle checks</h2><ul class="checks">${checks || '<li class="muted">Not loaded.</li>'}</ul></div>
  </section>
  ${changes()}
  <section><h2>Market bias</h2><p>What the macro data alone says for each market. Pick one to see what is behind it.</p>
    <div class="panels markets">${tiles}</div></section>
  <section id="ledger"><h2>What is driving ${esc(m.label)}</h2><p>${esc(m.note)}</p>
    <div class="panels groups">${groups}</div></section>
  ${leanings()}
  ${midterm()}`;
}

function snapshot() {
  const cat = catalog(), byId = Object.fromEntries(cat.map((c) => [c.id, c]));
  const shown = prefs.ids.map((id) => byId[id]).filter(Boolean);
  const cards = shown.map((c) => {
    const v = c.views.find((x) => x.name === prefs.view[c.id]) || c.views[0];
    const toggle = c.views.length > 1 ? `<div class="seg" role="group" aria-label="How to show ${esc(c.label)}">${c.views.map((x) =>
      `<button type="button" aria-pressed="${x === v}" data-view="${c.id}|${esc(x.name)}">${VIEW_LABELS[x.name] || esc(x.name)}</button>`).join("")}</div>` : v.name === "level" ? "" : `<p class="card__view muted">${esc(v.name[0].toUpperCase() + v.name.slice(1))}</p>`;
    const note = (v.lines ? `<ul class="legend">${v.lines.map((l, i) => `<li><svg viewBox="0 0 20 4" aria-hidden="true"><path class="line ${RAMP[i] ?? "line--old"}" d="M0 2H20"/></svg>${esc(l.name)}</li>`).join("")}</ul>` : "")
      + (v.note ? `<p class="card__note muted">${esc(v.note)}</p>` : "");
    return `<article class="card"><div class="card__head"><h2>${esc(c.label)}</h2><button class="quiet" type="button" data-remove="${c.id}" aria-label="Remove ${esc(c.label)}">Remove</button></div>
      <p class="readout measured"></p>${toggle}${note}<div class="chart" data-chart="${c.id}"></div></article>`;
  }).join("");
  const groups = [...new Set(cat.map((c) => c.group))];
  const options = groups.map((g) => `<optgroup label="${esc(g)}">${cat.filter((c) => c.group === g && !prefs.ids.includes(c.id)).map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}</optgroup>`).join("");
  return `${notices()}<section><h1>Snapshot</h1><p>The main series side by side on one time axis. Move over a chart to read any point. Max reaches back to 1980 where FRED has it.</p>
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Time range">${[1, 5, 10, 0].map((y) => `<button type="button" aria-pressed="${prefs.range === y}" data-range="${y}">${y ? y + (y === 1 ? " year" : " years") : "Max"}</button>`).join("")}</div>
      <button class="btn" type="button" aria-pressed="${prefs.shade}" data-shade>Recession shading</button>
      <label class="visually-hidden" for="add">Add a chart</label>
      <select class="select" id="add" name="add" autocomplete="off"><option value="">Add a chart</option>${options}</select>
      <button class="btn" type="button" data-reset>Reset charts</button>
    </div></section>
  ${cards ? `<section class="charts">${cards}</section>` : `<section class="state"><p>No charts selected. Add one from the list above, or reset to the starting set.</p></section>`}`;
}

function indicators(open) {
  const tables = Object.entries(S.groups).map(([key, g]) => {
    const rows = S.factors.filter((f) => f.group === key).map((f) => {
      const isOpen = f.id === open, [shortLabel, longLabel] = paces(f);
      const sentence = f.z == null ? "There is not enough history to score this one." :
        `${shortLabel}: ${val(f, f.short, f.kind === "diff")}. ${longLabel}: ${val(f, f.long, f.kind === "diff")}. The gap is ${num(Math.abs(f.z), 1)} typical moves ${f.z >= 0 ? "above" : "below"} zero, so it reads as ${word(f)}${f.stale ? " but is too old to count" : ""}.`;
      return `<tr id="row-${f.id}"><th scope="row"><button class="rowbtn" type="button" aria-expanded="${isOpen}" data-open="${f.id}">${esc(f.label)}</button></th>
        <td class="num">${val(f, f.value, f.kind === "diff")}<small>${esc(f.basis)}</small></td><td>${period(f)}</td>
        <td class="num">${val(f, f.short, f.kind === "diff")}</td><td class="num">${val(f, f.long, f.kind === "diff")}</td>
        <td>${spark(f)}</td><td><span class="chip">${word(f)}</span></td><td>${f.next_release ? day(f.next_release) : '<span class="muted">n/a</span>'}</td></tr>
        ${isOpen && f.views.length ? `<tr class="detail"><td colspan="8"><div class="detail__in"><div><p class="readout measured"></p><div class="chart" data-chart="${f.id}"></div></div>
          <div class="detail__text"><p>${esc(f.why)}</p><p class="muted">${sentence}</p>
          <p><a class="nowrap" href="https://fred.stlouisfed.org/series/${f.id}" target="_blank" rel="noopener">Open ${f.id} on FRED</a></p></div></div></td></tr>` : ""}`;
    }).join("");
    return `<section><h2>${esc(g.label)}</h2><div class="scroll"><table class="fixed">
      <thead><tr><th>Indicator</th><th class="num">Latest</th><th>Period</th><th class="num">Short pace</th><th class="num">Year pace</th><th>Five years</th><th>Read</th><th>Next release</th></tr></thead>
      <tbody>${rows}</tbody></table></div></section>`;
  }).join("");
  return `${notices()}<section><h1>Indicators</h1><p>Each indicator is read by comparing its recent pace with its pace over the past year. Select one for its chart and why it matters.</p></section>${tables}`;
}

function rates() {
  const R = S.rates;
  if (!R.curve) return `${notices()}<section class="state"><h1>Rates</h1><p>The Treasury yields did not load. Press Refresh to try again.</p></section>`;
  const change = (r, v) => v == null ? "n/a" : r.kind === "rate" ? signed(v * 100, 0) + " bp" : signed(v, 1);
  const rows = R.board.map((r) => `<tr><th scope="row">${esc(r.label)}</th><td class="num">${num(r.value, r.kind === "rate" ? 2 : 1)}${r.kind === "rate" ? "%" : ""}</td><td class="num">${change(r, r.month)}</td><td class="num">${change(r, r.year)}</td><td>${day(r.date)}</td></tr>`).join("");
  const key = (cls, label) => `<li><svg viewBox="0 0 20 4" aria-hidden="true"><path class="line ${cls}" d="M0 2H20"/></svg>${label}</li>`;
  const find = (label) => R.board.find((r) => r.label === label);
  const stat = (label, note) => { const r = find(label); return r ? `<li><span class="reading">${signed(r.value * 100, 0)} bp</span><strong>${label}</strong><span class="muted">${note}</span></li>` : ""; };
  const fed = S.fed.map((i) => `<li><a href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.title)}</a><span class="feed__meta muted"><span class="measured">${i.date ? day(i.date) : "n/a"}</span><span>${esc(i.kind)}</span></span></li>`).join("");
  return `${notices()}<section><h1>Rates</h1><p>Where policy is, what the curve is pricing, and how tight money is.</p></section>
  <section class="panels rates">
    <figure><h2>Treasury yield curve</h2><div class="chart" data-chart="curve"></div>
      <ul class="legend">${key("", day(R.curve.dates.now))}${key("line--ago", "Three months earlier")}${key("line--old", "One year earlier")}</ul></figure>
    <div><h2>Policy and slope</h2><ul class="checks">
      ${R.target ? `<li><span class="reading">${num(R.target.low, 2)} to ${num(R.target.high, 2)}%</span><strong>Fed funds target range</strong><span class="muted">In effect ${day(R.target.date)}</span></li>` : ""}
      ${stat("10-year minus 2-year", "Below zero means the market expects cuts")}
      ${stat("10-year minus 3-month", "The slope the recession model uses")}</ul></div>
  </section>
  <section><h2>Rates and conditions</h2><div class="scroll"><table>
    <thead><tr><th>Measure</th><th class="num">Latest</th><th class="num">1 month</th><th class="num">1 year</th><th>As of</th></tr></thead>
    <tbody>${rows}</tbody></table></div></section>
  <section><h2>From the Fed</h2><p>The latest policy releases and speeches, from the Federal Reserve's own feeds.</p>
    ${fed ? `<ul class="feed">${fed}</ul>`
      : `<p class="notice">${esc(S.errors.fed ? "The Fed feeds did not load: " + S.errors.fed : "The Fed feeds returned nothing. Press Refresh to try again.")}</p>`}</section>`;
}

function calendar() {
  const rows = S.calendar.map((c) => `<tr><td class="num">${at(c.date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</td>
    <th scope="row">${esc(c.release)}${c.date === S.today ? ' <span class="chip">today</span>' : ""}</th><td>${c.indicators.map(esc).join(", ")}</td></tr>`).join("");
  return `${notices()}<section><h1>Release calendar</h1><p>Scheduled releases for the scored indicators over the next 45 days, from FRED's release calendar.</p></section>
  <section>${rows ? `<div class="scroll"><table><thead><tr><th class="num">Date</th><th>Release</th><th>Moves these indicators</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : `<p class="notice">FRED returned no scheduled dates for these releases. Agencies publish schedules in batches, so press Refresh another day.</p>`}</section>`;
}

function method() {
  const M = S.method, keys = Object.keys(S.groups);
  const weights = S.markets.map((m) => `<tr><th scope="row">${esc(m.label)}</th>${keys.map((k) => `<td class="num">${signed(m.weights[k])}</td>`).join("")}<td>${esc(m.note)}</td></tr>`).join("");
  const health = S.factors.map((f) => `<tr><th scope="row">${esc(f.label)}</th><td><a href="https://fred.stlouisfed.org/series/${f.id}" target="_blank" rel="noopener">${f.id}</a></td><td>${esc(S.groups[f.group].label)}</td><td>${period(f)}</td>
    <td>${S.errors[f.id] ? "Failed: " + esc(S.errors[f.id]) : f.stale ? "Stale, not scored" : f.score == null ? "Too little history" : "Scored"}</td></tr>`).join("");
  const other = Object.entries(S.errors).filter(([id]) => !S.factors.some((f) => f.id === id)).map(([id, e]) => `<li>${SIDE_SOURCES[id] || `<code>${esc(id)}</code>`}: ${esc(e)}</li>`).join("");
  return `<section class="prose"><h1>Method</h1>
    <p>The macro figures come from FRED, the St. Louis Fed's database, through your own API key. Nothing is estimated or filled in: a series that fails or goes stale drops out of the scores and is listed below.</p>
    <h2>How to read the numbers</h2>
    <p>The scores are votes and averages on scales this terminal builds. None of them is a percentage, a probability or a return.</p>
    <div class="scroll"><table><thead><tr><th>Number</th><th>Where it shows</th><th>What it means</th></tr></thead><tbody>
      <tr><th scope="row">+1, 0, −1</th><td>Beside each indicator on the Board</td><td class="wrap">One vote. +1: clearly moving the way that helps the chosen market. −1: clearly moving the way that hurts it. 0: no clear change. The vote is flipped to suit the market, so inflation heating up shows as −1 for stocks.</td></tr>
      <tr><th scope="row">net +3, net −2</th><td>Top of each group</td><td class="wrap">The votes in that group added up. Net +3 from five indicators could be four up and one down.</td></tr>
      <tr><th scope="row">+0.30, −0.45</th><td>Under each market</td><td class="wrap">The market's overall score, from −1.00 to +1.00. +1.00 would mean every indicator it uses votes in its favour, −1.00 every one against. +0.30 is a vote that leans about a third of the way to fully bullish.</td></tr>
      <tr><th scope="row">+0.40 on the regime map</th><td>The dot's position</td><td class="wrap">Average momentum in typical moves: how far the indicators are speeding up or slowing down against their own normal swing. Zero is the dividing line between regimes.</td></tr>
    </tbody></table></div>
    <p>A figure that is a real reading carries its unit: % for rates and inflation, bp (basis points, 0.01 of a percentage point) for changes in rates, k or m for jobs in thousands or millions. A few readings are index levels with no unit: the Philly Fed surveys (above zero means more firms growing than shrinking), consumer sentiment, financial conditions (zero is average, below zero is looser), the dollar index and the VIX.</p>
    <h2>How an indicator is scored</h2>
    <ol class="steps">
      <li>Measure its recent pace: the last ${M.windows.m[0]} months for monthly data, ${M.windows.w[0]} weeks for weekly, about a month for daily, the latest quarter for GDP.</li>
      <li>Measure its pace over the past year the same way, and take the gap between the two.</li>
      <li>Divide that gap by a typical gap for that indicator over the last ten years (a median-based scale, so 2020 does not distort it).</li>
      <li>Past ${M.threshold} typical moves in either direction it scores +1 or −1. Inside that band it scores 0.</li>
    </ol>
    <p>The score says which way the indicator is moving against its own recent trend. It does not compare a release with economists' forecasts, which FRED does not carry.</p>
    <h2>How a market bias is built</h2>
    <p>Each group's score is the average of its indicators. A market's score is the weighted average of the four groups, from −1 to +1: at 0.2 it reads bullish, at 0.5 very bullish, and the same below zero. The weights are judgement, not estimates, and you can change them in the MARKETS table of macro_terminal.py.</p>
    <div class="scroll"><table><thead><tr><th>Market</th>${keys.map((k) => `<th class="num">${esc(S.groups[k].label)}</th>`).join("")}<th>Why</th></tr></thead><tbody>${weights}</tbody></table></div>
    <h2>Credit spreads</h2>
    <p>Credit is scored on the Baa spread: Moody's Baa corporate yield minus the 10-year Treasury, which FRED carries back decades. The single-A, BB and high-yield spreads are ICE BofA indices, measured against the whole Treasury curve with ratings averaged across Moody's, S&amp;P and Fitch. Since April 2026 FRED keeps only three years of ICE data and licenses it for internal use, so those spreads are shown but not scored.</p>
    <h2>The midterm panel and the Fed feed</h2>
    <p>FRED is licensed to carry only ten years of the S&amp;P 500, so the midterm panel reads daily closes back to 1950 from Yahoo Finance through the yfinance package. Each window runs from the close on election day, or the last close before it in the years the exchange shut for the vote, to the close one year later. Returns are price only, with no dividends, so other sources that count from month-end or include dividends will differ a little.</p>
    <p>Sector moves use the SPDR sector funds from the same Yahoo source. Policy releases and speeches come straight from the Federal Reserve's public feeds. All three are optional: if one fails, the rest of the terminal is unaffected.</p>
    <h2>Credit spreads and the regime notes</h2>
    <p>The bias score reads credit through Moody's Baa yield over the 10-year Treasury, because its history runs back decades. The Single-A, BBB and BB lines are ICE BofA indices, which bucket bonds by the average of Moody's, S&amp;P and Fitch ratings and measure the spread against the whole Treasury curve. FRED now keeps only three years of them, so they are for reading the ladder, not for scoring, and Baa is not drawn on the same axis because it is built a different way.</p>
    <p>The lines under "how a phase has tended to play out" restate the Merrill Lynch Investment Clock, a study of which asset classes and equity styles led in each mix of growth and inflation. They describe averages across past cycles. They are not a call on this one.</p>
    <h2>What this cannot tell you</h2>
    <p>It reads macro data only: no valuations, positioning, earnings or price trend. Strong jobs data is scored as good for stocks, which fails when the Fed is tightening into strength. The regime map and the recession checks are published models with well-known misses. The 12-month recession chance applies the New York Fed's published coefficients to the last month of the 10-year minus 3-month spread, so it can sit slightly off the Fed's own monthly figure. Use it to frame a view, then test that view elsewhere.</p>
  </section>
  <section><h2>Data health</h2><p>Loaded ${esc(new Date(S.fetched_at).toLocaleString())}. Data is reused for ${M.cache_hours} hours unless you press Refresh.</p>
    <div class="scroll"><table><thead><tr><th>Indicator</th><th>FRED series</th><th>Group</th><th>Latest period</th><th>Status</th></tr></thead><tbody>${health}</tbody></table></div>
    ${other ? `<p>Also failed on this load:</p><ul class="steps">${other}</ul>` : ""}</section>`;
}

// ---------- routing and loading ----------

function render() {
  const [view, arg] = (location.hash.slice(1) || "board").split("/");
  document.querySelectorAll(".tabs a").forEach((a) => a.getAttribute("href") === "#" + view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  if (!S) return;
  if (view === "board" && arg) market = arg;
  const views = { board, snapshot, indicators: () => indicators(arg), rates, calendar, method };
  app.innerHTML = (views[view] || board)();
  // An open row lives inside a table that may scroll sideways: hold it to the visible width.
  app.querySelectorAll(".detail__in").forEach((d) => { d.style.maxWidth = d.closest(".scroll").clientWidth - 48 + "px"; });
  const byId = Object.fromEntries(catalog().map((c) => [c.id, c]));
  app.querySelectorAll("[data-chart]").forEach((box) => {
    const id = box.dataset.chart, c = byId[id];
    if (id === "curve") box.innerHTML = curveChart(S.rates.curve, box.clientWidth);
    else if (id === "midterm") box.innerHTML = midtermChart(S.midterm, box.clientWidth);
    else if (view === "snapshot") drawChart(box, c, c.views.find((x) => x.name === prefs.view[id]) || c.views[0], { years: prefs.range, shade: prefs.shade, height: 200, readout: box.parentNode.querySelector(".readout") });
    else drawChart(box, S.factors.find((f) => f.id === id), S.factors.find((f) => f.id === id).views[0], { years: 5, shade: prefs.shade, height: 240, readout: box.parentNode.querySelector(".readout") });
  });
  if (view === "indicators" && arg) document.getElementById("row-" + arg)?.scrollIntoView({ block: "center" });
  if (view === "board" && arg && render.last !== location.hash) document.getElementById("ledger")?.scrollIntoView({ block: "nearest" });
  render.last = location.hash;
}

function fail(body) {
  const setup = body.error === "setup";
  app.innerHTML = `<section class="state" role="alert"><h1>${setup ? "Add your FRED key" : "FRED did not answer"}</h1><p>${esc(body.message)}</p>
    ${setup ? `<ol class="steps"><li>Get a free key at <a href="https://fredaccount.stlouisfed.org/apikeys" target="_blank" rel="noopener">fredaccount.stlouisfed.org/apikeys</a>, or reuse the one from your macro dashboard.</li>
      <li>In the folder that holds <code>macro_terminal.py</code>, create a file named <code>.env</code> with one line: <code>FRED_API_KEY=yourkey</code></li><li>Press Refresh.</li></ol>`
    : `<p class="muted">Check your connection, then press Refresh.</p>`}</section>`;
}

async function load(force) {
  refreshBtn.disabled = true;
  refreshBtn.textContent = "Refreshing";
  try {
    // Run locally, the Python server answers /api/snapshot. Hosted (GitHub Pages), a scheduled job writes snapshot.json.
    const url = LOCAL ? "/api/snapshot" + (force ? "?refresh=1" : "") : "snapshot.json?t=" + Date.now();
    const res = await fetch(url, { cache: "no-store" });
    const body = await res.json();
    if (res.ok) {
      S = body;
      updated.textContent = "Data loaded " + new Date(S.fetched_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      render();
    } else if (!S) fail(body);
    else { S.stale_reason = body.message; render(); }
  } catch (e) {
    if (!S) fail({ error: "fetch", message: LOCAL ? "The local server is not responding. Start it again with: python3 macro_terminal.py" : "The data file could not be loaded. Try again in a minute." });
  }
  refreshBtn.disabled = false;
  refreshBtn.textContent = "Refresh";
}

function setPrefs(change) {
  change();
  store.set("snapshot", prefs);
  render();
}

app.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  const d = t.dataset;
  if (d.open) location.hash = t.getAttribute("aria-expanded") === "true" ? "indicators" : "indicators/" + d.open;
  else if ("range" in d) setPrefs(() => { prefs.range = +d.range; });
  else if ("shade" in d) setPrefs(() => { prefs.shade = !prefs.shade; });
  else if (d.view) setPrefs(() => { const [id, name] = d.view.split("|"); prefs.view[id] = name; });
  else if (d.remove) setPrefs(() => { prefs.ids = prefs.ids.filter((id) => id !== d.remove); });
  else if ("reset" in d) setPrefs(() => { prefs = freshPrefs(); });
  else if ("seen" in d) { store.set("seen", fingerprint()); render(); }
});
app.addEventListener("change", (e) => {
  if (e.target.id === "add" && e.target.value) setPrefs(() => { prefs.ids.push(e.target.value); });
});
refreshBtn.addEventListener("click", () => load(true));
window.addEventListener("hashchange", render);
let resizing;
window.addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(render, 150); });
render();
load(false);
