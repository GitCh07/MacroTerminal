"use strict";
// Benchmarks (beta). Loaded after app.js and uses its helpers (S, esc, num, signed, day, store, app, render).
// Uploaded figures are parsed and kept in this browser only: nothing here sends them anywhere.
// To remove the beta, delete this file and the lines marked "benchmarks (beta)" in index.html and app.js.

const BM_KEY = "benchmarks.upload";
const bm = { source: "etf", asOf: null, editing: false, draft: "", error: "" };

// Header text in a report -> position in the period list. Unknown headers simply don't line up for the gap view.
const BM_HEADERS = { "1d": 0, "1day": 0, "day": 0, "1w": 1, "1wk": 1, "1week": 1, "week": 1, "mtd": 2, "monthtodate": 2,
  "qtd": 3, "quartertodate": 3, "ytd": 4, "yeartodate": 4, "1y": 5, "1yr": 5, "1year": 5, "12m": 5, "12month": 5,
  "3y": 6, "3yr": 6, "3year": 6, "5y": 7, "5yr": 7, "5year": 7, "10y": 8, "10yr": 8, "10year": 8 };
const bmKey = (label) => label.toLowerCase().replace(/annuali[sz]ed|\(.*?\)|return|trailing|ann\b/g, "").replace(/[^a-z0-9]/g, "")
  .replace(/years?$|yrs$/, "year").replace(/months?$/, "month").replace(/weeks?$/, "week").replace(/days?$/, "day");
const bmName = (s) => s.toLowerCase().replace(/\s+/g, " ").trim();

function bmCells(line) {
  if (line.includes("\t")) return line.split("\t");
  const out = [];  // CSV with quoted fields
  line.replace(/\s*(?:"((?:[^"]|"")*)"|([^,]*))\s*(?:,|$)/g, (m, quoted, plain) => { if (m) out.push(quoted != null ? quoted.replace(/""/g, '"') : plain); return ""; });
  return out;
}

// A number, null for a "not available" cell, undefined for text.
function bmNumber(cell) {
  const s = cell.trim().replace(/[−–]/g, "-").replace(/%$/, "").replace(/,/g, "");
  if (/^-?\s*(n\/?a|na|—|-)$/i.test(s)) return null;
  const neg = s.match(/^\((.*)\)$/);
  const v = s === "" ? NaN : Number(neg ? "-" + neg[1] : s);
  return Number.isFinite(v) ? v : undefined;
}

// Pasted cells or a CSV -> rows of category, name and figures. Caerus lines are dropped here, before anything is kept.
function bmParse(text) {
  const rows = [], headers = [];
  let dropped = 0;
  text.split(/\r?\n/).filter((l) => l.trim()).forEach((line) => {
    const cells = bmCells(line).map((c) => c.trim());
    let k = 0;
    while (k < cells.length && bmNumber(cells[cells.length - 1 - k]) !== undefined) k++;
    const text = cells.slice(0, cells.length - k).filter(Boolean);
    if (!k) { if (text.length >= 3 && !rows.length) headers.splice(0, headers.length, ...text); return; }
    if (!text.length) return;
    const name = text[text.length - 1], category = text.length > 1 ? text[0] : "";
    if (/caerus/i.test(name + " " + category)) { dropped++; return; }
    rows.push({ category, name, values: cells.slice(cells.length - k).map(bmNumber) });
  });
  if (!rows.length) return { error: "No rows with figures were found. Paste the table cells, with each line's name followed by its returns." };
  const n = Math.max(...rows.map((r) => r.values.length));
  const labels = headers.length >= n ? headers.slice(-n) : n === S.benchmarks.periods.length ? S.benchmarks.periods : null;
  const columns = (labels || rows[0].values.map((_, i) => "Column " + (i + 1))).map((label) => ({ label, period: BM_HEADERS[bmKey(label)] ?? null }));
  return { rows, columns, assumed: headers.length < n, dropped };
}

const bmSaved = () => store.get(BM_KEY, null);
const bmCell = (v, dp, plus) => v == null ? '<span class="muted">n/a</span>' : (plus ? signed(v, dp) : num(v, dp));

function bmTable(head, rows, foot) {
  return `<div class="scroll"><table class="bm-table"><thead><tr><th>Category</th><th>Benchmark</th>${head.map((h) => `<th class="num">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody>${foot || ""}</table></div>`;
}

function bmRow(cls, category, name, cells) {
  return `<tr${cls ? ` class="${cls}"` : ""}><td>${esc(category)}</td><th scope="row">${esc(name)}</th>${cells.map((c) => `<td class="num">${c}</td>`).join("")}</tr>`;
}

// The latest proxy date on or before a given day, so figures are compared at the same close.
const bmDateFor = (iso) => S.benchmarks.dates.filter((d) => d <= iso).pop() || null;

function bmEtf(B) {
  const asOf = B.dates.includes(bm.asOf) ? bm.asOf : B.dates[B.dates.length - 1];
  const rows = B.lines.map((l) => bmRow(l.blend ? "bm-blend" : "", l.category, l.name,
    (l.returns[asOf] || B.periods.map(() => null)).map((v) => bmCell(v, 2))));
  const dates = B.dates.slice().reverse().map((d) => `<option value="${d}"${d === asOf ? " selected" : ""}>${day(d)}</option>`).join("");
  return { controls: `<label class="bm-field"><span>As of</span><select class="select" id="bm-asof" name="bm-asof">${dates}</select></label>`,
    body: bmTable(B.periods, rows), note: "ETF and index total returns with dividends reinvested, cumulative up to a year and annualised beyond." };
}

function bmUploadView(U) {
  const rows = U.rows.map((r) => bmRow("", r.category, r.name, r.values.map((v) => bmCell(v, 2))));
  return { body: bmTable(U.columns.map((c) => c.label), rows),
    note: `Your figures${U.asOf ? " as of " + day(U.asOf) : ""}, saved in this browser ${new Date(U.savedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" })}.` };
}

function bmGap(B, U) {
  if (!U.asOf) return { body: `<p class="notice">Add the date your figures are as of, so both sides are measured to the same close.</p>` };
  const asOf = bmDateFor(U.asOf);
  if (!asOf) return { body: `<p class="notice">Your figures are dated ${day(U.asOf)}, earlier than the ${B.dates.length} trading days kept here. Upload a more recent table to compare.</p>` };
  const byName = Object.fromEntries(B.lines.map((l) => [bmName(l.name), l]));
  const cols = U.columns.map((c, i) => ({ ...c, i })).filter((c) => c.period != null);
  const gaps = cols.map(() => []);
  const rows = [], unmatched = [];
  U.rows.forEach((r) => {
    const line = byName[bmName(r.name)], proxy = line && line.returns[asOf];
    if (!proxy) { unmatched.push(r.name); return; }
    rows.push(bmRow(line.blend ? "bm-blend" : "", r.category, r.name, cols.map((c, j) => {
      const mine = r.values[c.i], theirs = proxy[c.period];
      if (mine == null || theirs == null) return bmCell(null);
      gaps[j].push(Math.abs(theirs - mine));
      return signed(theirs - mine, 2);
    })));
  });
  const median = (xs) => { if (!xs.length) return null; const s = xs.slice().sort((a, b) => a - b), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const foot = `<tfoot><tr><td></td><th scope="row">Typical gap, either way</th>${gaps.map((g) => `<td class="num">${bmCell(median(g), 2)}</td>`).join("")}</tr></tfoot>`;
  return { body: rows.length ? bmTable(cols.map((c) => c.label), rows, foot) : `<p class="notice">None of your lines matched a benchmark here by name.</p>`,
    note: `Stand-in minus your figure, in percentage points, at the ${day(asOf)} close.${asOf !== U.asOf ? ` Your date, ${day(U.asOf)}, was not a trading day here, so the close before it is used.` : ""}${unmatched.length ? ` No stand-in for: ${unmatched.map(esc).join(", ")}.` : ""}` };
}

function bmEditor(U) {
  return `<section class="panels bm-edit" aria-labelledby="bm-edit-title"><div>
    <h2 id="bm-edit-title">${U ? "Replace your figures" : "Add your figures"}</h2>
    <p class="muted">Copy the table from your report and paste it below, or choose a CSV. It is read and kept in this browser only. Lines named Caerus are left out.</p>
    <label class="bm-field bm-field--wide"><span>Table</span><textarea class="bm-paste" id="bm-paste" name="bm-paste" rows="8" spellcheck="false" placeholder="Category, benchmark name, then its returns, one line each">${esc(bm.draft)}</textarea></label>
    <div class="toolbar">
      <label class="bm-field"><span>Or a file</span><input class="select" type="file" id="bm-file" name="bm-file" accept=".csv,.tsv,.txt,text/csv,text/plain"></label>
      <label class="bm-field"><span>Figures as of</span><input class="select" type="date" id="bm-date" name="bm-date" value="${esc((U && U.asOf) || "")}"></label>
    </div>
    ${bm.error ? `<p class="notice" role="alert">${esc(bm.error)}</p>` : ""}
    <div class="toolbar"><button class="btn btn--primary" type="button" data-bm-save>Save figures</button>${U ? `<button class="btn" type="button" data-bm-cancel>Cancel</button>` : ""}</div>
  </div></section>`;
}

function benchmarksView() {
  const B = S.benchmarks, U = bmSaved();
  const intro = `<section><h1>Benchmarks <span class="chip">Beta</span></h1>
    <p>The benchmark lines rebuilt from ETF total returns, beside your own figures and the gap between them. Check the gap before relying on a line.</p></section>`;
  if (!B) return notices() + intro + `<p class="notice">${esc(S.errors.benchmarks || "Benchmark prices did not load. Press Refresh to try again.")}</p>`;
  const source = U ? bm.source : "etf";
  const view = source === "upload" ? bmUploadView(U) : source === "gap" ? bmGap(B, U) : bmEtf(B);
  const seg = [["etf", "ETF stand-ins"], ["upload", "Your figures"], ["gap", "Gap"]].map(([id, label]) =>
    `<button type="button" aria-pressed="${source === id}" data-bm-source="${id}"${!U && id !== "etf" ? " disabled" : ""}>${label}</button>`).join("");
  const status = U ? `${U.rows.length} lines${U.asOf ? " as of " + day(U.asOf) : ""}${U.dropped ? `, ${U.dropped} Caerus ${U.dropped === 1 ? "line" : "lines"} left out` : ""}${U.assumed ? `. No header row, so the columns are read as ${U.columns.map((c) => c.label).join(", ")}` : ""}.` : "";
  const notes = B.lines.filter((l) => l.note || l.missing.length).map((l) =>
    `<li><strong>${esc(l.name)}</strong>: ${l.missing.length ? `price data missing for ${esc(l.missing.join(", "))}, so this line is empty. ` : ""}${esc(l.note || "")}</li>`).join("");
  return `${notices()}${intro}
  <section><div class="toolbar">
      <div class="seg" role="group" aria-label="What to show">${seg}</div>${view.controls || ""}
      <button class="btn" type="button" data-bm-edit>${U ? "Replace your figures" : "Add your figures"}</button>
      ${U ? `<button class="quiet" type="button" data-bm-clear>Remove your figures</button>` : ""}
    </div>${status ? `<p class="muted bm-status">${esc(status)}</p>` : ""}</section>
  ${bm.editing || (!U && bm.draft) ? bmEditor(U) : ""}
  <section>${view.body}${view.note ? `<p class="card__note muted">${view.note}</p>` : ""}</section>
  <section><details><summary>How each stand-in is built</summary><ul class="bm-notes">
    <li>Periods follow the firm report they were checked against: 1, 3, 5 and 10 years start at the month-end before the date that many years back. 1 year is cumulative; longer periods are annualised.</li>
    <li>Blends rebalance to their weights at each month-end. MSCI EAFE + Canada is 89% EFA and 11% EWC, close to Canada's share of MSCI World ex USA.</li>
    <li>International lines: the ETFs price at the New York close, while MSCI indexes close in each market's own hours. A late move in New York can open a gap of half a point or more over a few days, which fades over longer periods.</li>${notes}</ul></details></section>`;
}

app.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  const d = t.dataset;
  if (d.bmSource) { bm.source = d.bmSource; render(); }
  else if ("bmEdit" in d) { bm.editing = true; bm.error = ""; render(); document.getElementById("bm-paste")?.focus(); }
  else if ("bmCancel" in d) { bm.editing = false; bm.draft = ""; bm.error = ""; render(); }
  else if ("bmClear" in d) { store.set(BM_KEY, null); bm.source = "etf"; render(); }
  else if ("bmSave" in d) {
    const parsed = bmParse(bm.draft);
    if (parsed.error) { bm.error = parsed.error; render(); return; }
    const asOf = document.getElementById("bm-date")?.value || null;
    store.set(BM_KEY, { ...parsed, asOf, savedAt: new Date().toISOString() });
    Object.assign(bm, { editing: false, draft: "", error: "", source: asOf ? "gap" : "upload" });
    render();
  }
});
app.addEventListener("input", (e) => { if (e.target.id === "bm-paste") bm.draft = e.target.value; });
app.addEventListener("change", (e) => {
  if (e.target.id === "bm-asof") { bm.asOf = e.target.value; render(); }
  if (e.target.id === "bm-file" && e.target.files[0]) {
    const file = e.target.files[0];
    if (/\.xlsx?$/i.test(file.name)) { bm.error = "Excel files can't be read here. Save it as CSV, or copy the cells and paste them."; render(); return; }
    if (file.size > 500000) { bm.error = "That file is larger than a benchmark table should be."; render(); return; }
    file.text().then((text) => { bm.draft = text; bm.error = ""; bm.editing = true; render(); });
  }
});
