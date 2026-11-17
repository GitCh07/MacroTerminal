// Macro Terminal replays. Draws the frames the refresh job writes to data/*.json; the only math here is
// for figures the user pastes in, which never leave the browser.
import { token, ramp, player, profile, series, heatmap, surface, bars, scatter } from "./components.js";

const root = document.getElementById("viz");
const view = new URLSearchParams(location.search).get("view");
const TAG = "Historical replay · not a forecast.";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const month = (m) => MONTHS[+m.slice(5, 7) - 1] + " " + m.slice(0, 4);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const signed = (v, dp = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(dp);
const store = {  // browser storage can be missing or full; a replay never depends on it
  get(k) { try { return JSON.parse(localStorage.getItem("mtviz." + k)); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem("mtviz." + k) : localStorage.setItem("mtviz." + k, JSON.stringify(v)); } catch { /* not saved */ } },
};
const players = [];

async function data(name) {
  const res = await fetch("data/" + name, { cache: "no-cache" });
  if (!res.ok) throw new Error(name);
  return res.json();
}

function missing(el, what) {
  el.innerHTML = `<section class="v-section"><h2>${what}</h2><p class="v-muted">The replay data has not been built yet. Run locally, press Refresh in the terminal once; the hosted copy writes it on its next scheduled rebuild.</p></section>`;
}

const cats = () => [1, 2, 3, 4, 5].map((n) => token("v-cat-" + n));
const seq = () => ramp([token("v-seq-lo"), token("v-seq-hi")]);
const diverging = () => ramp([token("v-neg"), token("v-mid"), token("v-pos")]);

// ---------- Part A: the yield curve ----------

async function curve(el) {
  let d;
  try { d = await data("yield_curve.json"); } catch { return missing(el, "Treasury yield curve"); }
  const n = d.months.length, x = d.maturities.map((m) => m.label);
  const labels = d.months.map((m, i) => month(m) + (d.partial && i === n - 1 ? ", month to date" : ""));
  const c = cats(), colors = { current: token("v-current"), ghost: token("v-current"), reference: token("v-reference") };
  let mode = "curve", ref = 12, scale = "all", chart;
  el.innerHTML = `<section class="v-section" aria-labelledby="v-curve-h">
    <div class="v-head"><h2 id="v-curve-h">Treasury yield curve</h2><p class="v-tag">${TAG}</p></div>
    <div class="v-controls">
      <div data-player></div>
      <div class="v-seg" role="group" aria-label="Chart type">
        <button type="button" class="v-btn" data-mode="curve" aria-pressed="true">Curve</button>
        <button type="button" class="v-btn" data-mode="surface" aria-pressed="false">3D surface</button>
        <button type="button" class="v-btn" data-mode="heat" aria-pressed="false">Heatmap</button>
      </div>
      <label class="v-field" data-refbox>Compare with <select data-ref>
        ${[3, 6, 12, 24, 60, 120].map((k) => `<option value="${k}" ${k === 12 ? "selected" : ""}>${k < 24 ? k + " months" : k / 12 + " years"} ago</option>`).join("")}
        <option value="0">nothing</option></select></label>
      <label class="v-field" data-scalebox>Scale <select data-scale><option value="all">1982 to now</option><option value="recent">Last 10 years</option></select></label>
    </div>
    <div class="v-chart" data-main></div>
    <p class="v-legend" data-legend></p>
    <p class="v-note" data-note></p>
    <p class="v-readout" data-readout></p>
    <h3>Spreads</h3>
    <div class="v-chart" data-spreads></div>
    <p class="v-legend"><span><i class="v-key" style="--key:${c[0]}"></i>10-year minus 2-year</span><span><i class="v-key" style="--key:${c[1]}"></i>10-year minus 3-month</span><span><i class="v-key v-key--band"></i>shaded where that spread was below zero (inverted)</span></p>
    <p class="v-source">Monthly averages of FRED's daily constant-maturity yields (DGS1MO to DGS30), January 1982 on; the latest month averages the days so far and is marked month to date. A maturity with no published value is left out of that month, never filled in; so is the 30-year from February 2002 to February 2006, when Treasury published only an estimate of it.</p>
  </section>`;
  const q = (s) => el.querySelector(s), main = q("[data-main]");
  const legends = {
    curve: () => `<span><i class="v-key" style="--key:${colors.current}"></i>the month shown</span><span><i class="v-key v-key--ghost" style="--key:${colors.current}"></i>the six months before it</span>${ref ? `<span><i class="v-key v-key--dash" style="--key:${colors.reference}"></i>${ref < 24 ? ref + " months" : ref / 12 + " years"} earlier</span>` : ""}`,
    surface: () => `<span>The last ten years up to the month shown, oldest at the back. Line colour follows the average yield, darker is lower.</span>`,
    heat: () => `<span>Each column is a month, each row a maturity. Darker is a lower yield; the outlined column is the month shown. Gaps are left dark.</span>`,
  };
  const build = () => {
    main.innerHTML = "";
    q("[data-refbox]").hidden = q("[data-scalebox]").hidden = mode !== "curve";
    q("[data-legend]").innerHTML = legends[mode]();
    if (mode === "curve") chart = profile(main, { label: "Animated Treasury yield curve", x, frames: d.frames, unit: "%", ghosts: 6, colors, include: [0], refLabel: (r) => labels[r], domain: scale === "recent" ? d.frames.slice(-120).flat() : null });
    else if (mode === "surface") { const color = seq(); chart = surface(main, { label: "Yield surface: maturity across, time in depth, yield up", x, frames: d.frames, dates: labels, window: 120, unit: "%", color: (v) => color(v / 10), current: colors.current }); }
    else {
      const top = Math.max(...d.frames.flat().filter((v) => v != null)), color = seq();
      chart = heatmap(main, { label: "Heatmap of Treasury yields by maturity and month", rows: x, cols: labels, rowH: 20, left: 44, value: (r, k) => d.frames[k][r], color: (v) => color(v / top), fmt: (v) => (v == null ? "not published" : v.toFixed(2) + "%"), tick: (k) => d.months[k].slice(0, 4) });
    }
  };
  const runs = (ranges, color) => ranges.map(([a, b]) => [d.months.indexOf(a), d.months.indexOf(b), color]);
  const spreads = series(q("[data-spreads]"), {
    label: "10-year minus 2-year and 10-year minus 3-month spreads over time", dates: labels, unit: "%", zero: true, dp: 2,
    tick: (i) => d.months[i].slice(0, 4),
    series: [{ label: "10Y − 2Y", values: d.spreads["10Y-2Y"], color: c[0] }, { label: "10Y − 3M", values: d.spreads["10Y-3M"], color: c[1] }],
    shade: [...runs(d.inversions["10Y-2Y"], token("v-band-1")), ...runs(d.inversions["10Y-3M"], token("v-band-2"))],
  });
  const frame = (i, f) => {
    chart.show(i, f, ref && i - ref >= 0 ? i - ref : null);
    spreads.show(i, f);
    const gone = d.notes.filter((g) => g.start <= d.months[i] && d.months[i] <= g.end);
    q("[data-note]").textContent = gone.length ? "Left out this month: " + gone.map((g) => `${g.maturity} (${g.why})`).join("; ") + "." : "";
    const v = d.frames[i], at = (t) => v[x.indexOf(t)];
    q("[data-readout]").textContent = `${labels[i]}: ` + ["3M", "2Y", "10Y", "30Y"].map((t) => `${t} ${at(t) == null ? "n/a" : at(t).toFixed(2) + "%"}`).join(", ")
      + ["10Y-2Y", "10Y-3M"].map((k) => d.spreads[k][i] == null ? "" : `; ${k.replace("-", " minus ")} ${signed(d.spreads[k][i])} pts`).join("") + ".";
  };
  build();
  const p = player(q("[data-player]"), { labels, onFrame: frame, fps: 8, name: "month" });
  players.push(p);
  el.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.mode;
    el.querySelectorAll("[data-mode]").forEach((o) => o.setAttribute("aria-pressed", o === b));
    build(); p.redraw();
  }));
  q("[data-scale]").addEventListener("change", (e) => { scale = e.target.value; build(); p.redraw(); });
  q("[data-ref]").addEventListener("change", (e) => { ref = +e.target.value; q("[data-legend]").innerHTML = legends[mode](); p.redraw(); });
}

// ---------- Part B: why the bias moved ----------

async function bias(el) {
  let d;
  try { d = await data("bias_history.json"); } catch { return missing(el, "Why the bias moved"); }
  const c = cats(), div = diverging();
  const rows = d.markets.map((m) => m.label), parts = d.groups.map((g, k) => ({ label: g.label, color: c[k] }));
  const labels = d.frames.map((f, i) => (i === d.frames.length - 1 ? "Today" : month(f.date.slice(0, 7))));
  const word = (s) => (d.thresholds.find(([t]) => s >= t) || [null, "very bearish"])[1];
  el.innerHTML = `<section class="v-section" aria-labelledby="v-bias-h">
    <div class="v-head"><h2 id="v-bias-h">Why the bias moved</h2><p class="v-tag">${TAG}</p></div>
    <p class="v-muted">Each bar is a market's score split into what each group added. The tick is the total, from −1 to +1, the same number the board shows.</p>
    <div class="v-controls"><div data-player></div></div>
    <div class="v-chart" data-bars></div>
    <p class="v-legend">${parts.map((p) => `<span><i class="v-key" style="--key:${p.color}"></i>${p.label}</span>`).join("")}<span><i class="v-key v-key--tick"></i>total score</span></p>
    <p class="v-readout" data-why></p>
    <h3>Every market, every month</h3>
    <div class="v-chart" data-heat></div>
    <p class="v-legend"><span><i class="v-key" style="--key:${token("v-neg")}"></i>bearish</span><span><i class="v-key" style="--key:${token("v-mid")}"></i>neutral</span><span><i class="v-key" style="--key:${token("v-pos")}"></i>bullish</span><span>Colour is full from ±0.6. The outlined column is the month shown.</span></p>
    <p class="v-source">${esc(d.note)}</p>
  </section>`;
  const q = (s) => el.querySelector(s);
  const chart = bars(q("[data-bars]"), {
    label: "Factor contributions to each market's bias score", rows, parts, domain: [-1, 1],
    frames: d.frames.map((f) => d.markets.map((m) => d.groups.map((g) => f.contrib[m.id][g.id] ?? null))),
    totals: d.frames.map((f) => d.markets.map((m) => f.scores[m.id])),
  });
  const heat = heatmap(q("[data-heat]"), {
    label: "Bias score by market and month", rows, cols: labels, rowH: 22,
    value: (r, k) => d.frames[k].scores[d.markets[r].id], color: (v) => div((Math.max(-0.6, Math.min(0.6, v)) / 0.6 + 1) / 2),  // full colour from ±0.6, past the very bullish/bearish line
    fmt: (v) => `${signed(v)} (${word(v)})`, tick: (k) => labels[k],
  });
  const frame = (i, f) => {
    chart.show(i, f); heat.show(i);
    if (!i) { q("[data-why]").textContent = `${labels[i]}: the first month in this replay.`; return; }
    const now = d.frames[i], before = d.frames[i - 1];
    const moves = d.markets.map((m) => {
      const delta = now.scores[m.id] - before.scores[m.id];
      const by = d.groups.map((g) => [g.label, (now.contrib[m.id][g.id] || 0) - (before.contrib[m.id][g.id] || 0)])
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
      return { m, delta, by };
    }).filter((x) => Math.abs(x.delta) >= 0.005).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 3);
    q("[data-why]").textContent = moves.length
      ? `${labels[i]}, against ${labels[i - 1]}: ` + moves.map(({ m, delta, by }) => `${m.label} ${signed(delta)} to ${word(now.scores[m.id])}, mostly ${by[0].toLowerCase()} (${signed(by[1])})`).join("; ") + "."
      : `${labels[i]}: no market's score changed from ${labels[i - 1]}.`;
  };
  players.push(player(q("[data-player]"), { labels, onFrame: frame, fps: 3, name: "month" }));
}

// ---------- Part C: uploaded figures against the benchmarks ----------

// Paste or CSV: a date column, then one column of period returns in percent per series. Caerus is dropped.
function parse(text) {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) throw new Error("Paste a header row and at least two dated rows.");
  const cut = (l) => l.split(lines[0].includes("\t") ? "\t" : ",").map((c) => c.trim().replace(/^"|"$/g, ""));
  const head = cut(lines[0]), keep = head.map((h, k) => k > 0 && h && !/caerus/i.test(h));
  const dropped = head.filter((h, k) => k > 0 && /caerus/i.test(h)).length;
  const rows = lines.slice(1).map(cut).map((r) => {
    const raw = r[0], m = raw.match(/^(\d{4})-(\d{1,2})/) || raw.match(/^(\d{1,2})\/\d{1,2}\/(\d{2,4})$/);
    if (!m) throw new Error(`"${raw}" is not a date. Use 2026-10-31 or 10/31/2026.`);
    const [y, mo] = raw.includes("/") ? [m[2].length === 2 ? "20" + m[2] : m[2], m[1]] : [m[1], m[2]];
    const num = (s) => { const t = (s || "").replace(/[%\s,]/g, ""); const neg = /^\(.*\)$/.test(t); const v = parseFloat(t.replace(/[()]/g, "")); return isFinite(v) ? (neg ? -v : v) : null; };
    return { month: `${y}-${String(mo).padStart(2, "0")}`, values: r.map(num) };
  }).sort((a, b) => (a.month < b.month ? -1 : 1));
  if (new Set(rows.map((r) => r.month)).size !== rows.length) throw new Error("Two rows fall in the same month. Use one row per period, monthly or longer.");
  const names = head.filter((_, k) => keep[k]);
  if (!names.length) throw new Error(dropped ? "Only Caerus columns were found, and those are left out." : "No series columns were found after the date column.");
  return { names, dropped, months: rows.map((r) => r.month), returns: names.map((n) => rows.map((r) => r.values[head.indexOf(n)])) };
}

const gap = (a, b) => (+b.slice(0, 4) - +a.slice(0, 4)) * 12 + (+b.slice(5, 7) - +a.slice(5, 7));
const back = (m, k) => { const t = +m.slice(0, 4) * 12 + +m.slice(5, 7) - 1 - k; return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`; };

// Each uploaded row covers the time since the row before; the first row is assumed to cover the usual gap.
function compare(u, si, levels, line) {
  const level = (m) => { const k = levels.months.indexOf(m); return k < 0 ? null : line.levels[k]; };
  const steps = u.months.map((m, k) => (k ? gap(u.months[k - 1], m) : null));
  const usual = steps.slice(1).sort((a, b) => a - b)[Math.floor((steps.length - 1) / 2)] || 1;
  const starts = u.months.map((m, k) => (k ? u.months[k - 1] : back(m, usual)));
  const r = u.returns[si].map((v) => (v == null ? null : v / 100));
  const b = u.months.map((m, k) => { const a = level(starts[k]), z = level(m); return a && z ? z / a - 1 : null; });
  const index = [], bIndex = [], excess = [], capture = [];
  let lv = 100, blv = 100, ok = true;
  for (let k = 0; k < u.months.length; k++) {
    ok = ok && r[k] != null && b[k] != null;
    lv = ok ? lv * (1 + r[k]) : null; blv = ok ? blv * (1 + b[k]) : null;
    index.push(lv); bIndex.push(blv);
    let span = 0, j = k, grow = 1;  // trailing rows that add up to exactly twelve months
    while (j >= 0 && span < 12 && r[j] != null) { span += j ? gap(u.months[j - 1], u.months[j]) : usual; grow *= 1 + r[j]; j--; }
    const b0 = level(back(u.months[k], 12)), b1 = level(u.months[k]);
    excess.push(span === 12 && b0 && b1 ? ((grow - 1) - (b1 / b0 - 1)) * 100 : null);
    const pick = (up) => { const ks = []; for (let t = 0; t <= k; t++) if (r[t] != null && b[t] != null && (up ? b[t] > 0 : b[t] < 0)) ks.push(t); return ks; };
    const ratio = (ks) => { if (!ks.length) return null; const g = (xs) => xs.reduce((a, x) => a * (1 + x), 1) ** (1 / xs.length) - 1; return (g(ks.map((t) => r[t])) / g(ks.map((t) => b[t]))) * 100; };
    const up = ratio(pick(true)), down = ratio(pick(false));
    capture.push(up != null && down != null ? [down, up] : null);
  }
  return { index, bIndex, excess, capture, usual };
}

async function bench(el) {
  let levels;
  try { levels = await data("benchmark_levels.json"); } catch { return missing(el, "Benchmarks over time"); }
  const names = levels.lines.map((l) => l.name);
  let u = store.get("series"), sel = store.get("choice") || {};
  el.innerHTML = `<section class="v-section" aria-labelledby="v-bench-h">
    <div class="v-head"><h2 id="v-bench-h">Over time, against the benchmarks</h2><p class="v-tag">${TAG}</p></div>
    <p class="v-muted">Paste a return history to compare: a date column, then one column of period returns in percent per series, monthly or longer. It stays in this browser and is never sent anywhere. Caerus columns are left out.</p>
    <details class="v-upload" ${u ? "" : "open"}><summary>Returns to compare</summary>
      <textarea data-paste rows="6" spellcheck="false" aria-label="Paste returns" placeholder="Date, Your series&#10;2025-12-31, 1.20&#10;2026-01-31, -0.85"></textarea>
      <div class="v-row"><button type="button" class="v-btn v-btn--primary" data-use>Use these figures</button>
        <label class="v-btn v-file">Choose a CSV<input type="file" accept=".csv,.tsv,.txt" data-file></label>
        <button type="button" class="v-btn" data-clear ${u ? "" : "hidden"}>Remove them</button></div>
      <p class="v-note" data-msg role="status"></p></details>
    <div data-out></div></section>`;
  const q = (s) => el.querySelector(s), msg = q("[data-msg]");
  const use = (text) => {
    try { u = parse(text); store.set("series", u); msg.textContent = `Loaded ${u.names.length} series over ${u.months.length} periods.` + (u.dropped ? ` Left out ${u.dropped} Caerus column${u.dropped > 1 ? "s" : ""}.` : ""); q("[data-clear]").hidden = false; draw(); }
    catch (e) { msg.textContent = e.message; }
  };
  q("[data-use]").addEventListener("click", () => use(q("[data-paste]").value));
  q("[data-file]").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) use(await f.text()); });
  q("[data-clear]").addEventListener("click", () => { u = null; store.set("series", null); q("[data-clear]").hidden = true; msg.textContent = "Removed from this browser."; draw(); });

  function draw() {
    while (players.length > 0) players.pop().destroy();
    const out = q("[data-out]");
    if (!u) { out.innerHTML = ""; return; }
    const si = Math.min(sel.series || 0, u.names.length - 1);
    const picked = (sel.benchmarks || []).filter((n) => names.includes(n));
    const chosen = picked.length ? picked : [names.includes(u.names[si]) ? u.names[si] : "S&P 500 (TR)", "Bloomberg US Agg Bond TR USD"].filter((n, k, a) => names.includes(n) && a.indexOf(n) === k);
    const c = cats(), colorOf = (k) => c[k + 1];
    const results = chosen.map((n) => compare(u, si, levels, levels.lines.find((l) => l.name === n)));
    const labels = u.months.map(month);
    out.innerHTML = `<div class="v-controls">
        <label class="v-field">Series <select data-series>${u.names.map((n, k) => `<option value="${k}" ${k === si ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <fieldset class="v-picks"><legend>Benchmarks, up to four</legend>${names.map((n) => `<label><input type="checkbox" value="${esc(n)}" ${chosen.includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("")}</fieldset>
      </div>
      <div class="v-controls"><div data-player></div></div>
      <h3>Rolling 12-month excess return, in percentage points</h3><div class="v-chart" data-excess></div>
      <h3>Growth of 100</h3><div class="v-chart" data-index></div>
      <h3>Up and down capture</h3><div class="v-chart" data-capture></div><p class="v-note" data-capnote></p>
      <p class="v-legend"><span><i class="v-key" style="--key:${c[0]}"></i>${esc(u.names[si])}</span>${chosen.map((n, k) => `<span><i class="v-key" style="--key:${colorOf(k)}"></i>${esc(n)}</span>`).join("")}</p>
      <p class="v-source">Points sit only on the dates you uploaded, ${results[0]?.usual === 1 ? "monthly" : `every ${results[0]?.usual} months`}. Excess is the series' trailing 12-month return minus the benchmark's, in percentage points, shown once twelve months are covered. Capture compares the series with the benchmark in the periods the benchmark rose (up) or fell (down), since the first upload; 100 means it moved one for one. Benchmarks are the ETF stand-ins from the Benchmarks tab at month-end closes, through ${esc(levels.asof)}.</p>`;
    out.querySelector("[data-series]").addEventListener("change", (e) => { sel = { ...sel, series: +e.target.value }; store.set("choice", sel); draw(); });
    out.querySelectorAll(".v-picks input").forEach((box) => box.addEventListener("change", () => {
      const on = [...out.querySelectorAll(".v-picks input:checked")].map((b) => b.value);
      if (on.length > 4) { box.checked = false; return; }
      sel = { ...sel, benchmarks: on }; store.set("choice", sel); draw();
    }));
    if (!results.length) return;
    const ex = series(out.querySelector("[data-excess]"), { label: "Rolling 12-month excess return against each benchmark", dates: labels, unit: "", zero: true, dp: 2,
      series: results.map((r, k) => ({ label: chosen[k], values: r.excess, color: colorOf(k) })) });
    const ix = series(out.querySelector("[data-index]"), { label: "Growth of 100, the series against each benchmark", dates: labels, unit: "", dp: 1,
      series: [{ label: u.names[si], values: results[0].index, color: c[0] }, ...results.map((r, k) => ({ label: chosen[k], values: r.bIndex, color: colorOf(k) }))] });
    const cap = scatter(out.querySelector("[data-capture]"), { label: "Up capture against down capture for each benchmark", unit: "%", trail: 6,
      x: { label: "Down capture", ref: 100 }, y: { label: "Up capture", ref: 100 },
      points: results.map((r, k) => ({ label: chosen[k], color: colorOf(k), frames: r.capture })) });
    const capNote = out.querySelector("[data-capnote]");
    players.push(player(out.querySelector("[data-player]"), { labels, fps: 3, name: "period", onFrame: (i, f) => {
      ex.show(i, f); ix.show(i, f); cap.show(i, f);
      const none = chosen.filter((_, k) => !results[k].capture[i]);
      capNote.textContent = none.length ? `No dot yet for ${none.join(", ")}: capture needs at least one period where that benchmark rose and one where it fell.` : "";
    } }));
  }
  draw();
}

// ---------- boot ----------

// The terminal says when it has new data; reload once the frames built for that data are in place.
addEventListener("message", (e) => {
  if (e.source !== parent || e.origin !== location.origin || e.data?.mtviz !== "refresh") return;
  const file = { bias: "bias_history.json", bench: "benchmark_levels.json" }[view] || "yield_curve.json";
  let tries = 0;
  const check = async () => {
    try { if ((await data(file)).built_for === e.data.for) return location.reload(); } catch { /* not there yet */ }
    if (++tries < 36) setTimeout(check, 5000);  // locally the frames build a little after the snapshot; give it three minutes
  };
  check();
});

(async () => {
  await ({ curve, bias, bench }[view] || curve)(root);
  // Tell the terminal how tall this page is, so its frame shows everything without a second scrollbar.
  const tell = () => parent !== window && parent.postMessage({ mtviz: "height", h: Math.ceil(document.body.getBoundingClientRect().height) }, location.origin);
  new ResizeObserver(tell).observe(document.body);
  tell();
})();
