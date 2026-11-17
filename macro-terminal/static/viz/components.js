// Generic replay components: frames and axis config in, pixels out. Nothing here knows about yields or markets,
// so the file can be lifted into another project as is. Canvas only, no libraries.

const reduced = matchMedia("(prefers-reduced-motion: reduce)");

// Colours come from CSS custom properties, so the stylesheet stays the one place they are set.
const tokens = new Map();
export function token(name) {
  if (!tokens.has(name)) tokens.set(name, getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim());
  return tokens.get(name);
}

// ---------- colour ramps (interpolated in OKLab so steps look even) ----------

const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

function oklab(hex) {
  const n = parseInt(hex.slice(1), 16), [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((v) => toLin(v / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

function hex([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
    s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map((c) => Math.round(Math.min(1, Math.max(0, toSrgb(c))) * 255).toString(16).padStart(2, "0")).join("");
}

// stops: hex colours spread evenly over 0..1. Returns t -> hex.
export function ramp(stops) {
  const labs = stops.map(oklab);
  return (t) => {
    const x = Math.min(1, Math.max(0, t)) * (labs.length - 1), i = Math.min(labs.length - 2, Math.floor(x)), f = x - i;
    return hex(labs[i].map((v, k) => v + (labs[i + 1][k] - v) * f));
  };
}

// ---------- layout helpers ----------

export function niceTicks(lo, hi, count = 5) {
  const step0 = (hi - lo) / count, p = 10 ** Math.floor(Math.log10(step0)), m = step0 / p;
  const step = (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p, out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
  return out;
}

export function extent(values, pad = 0.06, include = []) {
  const vs = values.concat(include).filter((v) => v != null && isFinite(v));
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (lo === hi) { lo -= 1; hi += 1; }
  const p = (hi - lo) * pad;
  return [lo - p, hi + p];
}

// A canvas that tracks its box's width and the screen's pixel density, and redraws on resize.
export function stage(el, height, label) {
  const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", label);
  el.append(canvas);
  const s = { canvas, ctx, w: 0, h: height, draw: () => {} };
  const size = () => {
    const r = devicePixelRatio || 1, w = el.clientWidth;
    if (!w) return;
    s.w = w;
    canvas.width = Math.round(w * r); canvas.height = Math.round(height * r);
    canvas.style.width = w + "px"; canvas.style.height = height + "px";
    ctx.setTransform(r, 0, 0, r, 0, 0);
    s.draw();
  };
  s.ro = new ResizeObserver(size);
  s.ro.observe(el);
  return s;
}

// A hover readout over a stage: html(x, y) returns the tooltip's markup, or null to hide it.
export function hover(s, html) {
  const tip = document.createElement("div");
  tip.className = "v-tip";
  tip.hidden = true;
  s.canvas.parentNode.style.position = "relative";
  s.canvas.parentNode.append(tip);
  s.canvas.addEventListener("pointermove", (e) => {
    const r = s.canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, body = html(x, y);
    tip.hidden = !body;
    if (!body) return;
    tip.innerHTML = body;
    const left = x + 14 + tip.offsetWidth > s.w ? x - 14 - tip.offsetWidth : x + 14;
    tip.style.transform = `translate(${Math.max(0, left)}px, ${Math.max(0, y - tip.offsetHeight - 10)}px)`;
  });
  s.canvas.addEventListener("pointerleave", () => { tip.hidden = true; });
}

// The value axis takes the room its widest label needs, so long units never clip.
function grid(ctx, s, box, ys, y, fmt) {
  ctx.font = `12px ${token("v-font-mono")}`;
  box.l = Math.max(44, Math.ceil(Math.max(...ys.map((t) => ctx.measureText(fmt(t)).width))) + 16);
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (const t of ys) {
    ctx.strokeStyle = token("v-rule");
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(box.l, Math.round(y(t)) + 0.5); ctx.lineTo(s.w - box.r, Math.round(y(t)) + 0.5); ctx.stroke();
    ctx.fillStyle = token("v-muted");
    ctx.fillText(fmt(t), box.l - 8, y(t));
  }
}

function line(ctx, pts, color, width = 2, dash = []) {
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash); ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.beginPath();
  let pen = false;
  for (const p of pts) {
    if (!p) { pen = false; continue; }
    pen ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    pen = true;
  }
  ctx.stroke(); ctx.setLineDash([]);
}

function dot(ctx, x, y, color, r = 5) {
  ctx.beginPath(); ctx.arc(x, y, r + 2, 0, 7); ctx.fillStyle = token("v-paper"); ctx.fill();
  ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fillStyle = color; ctx.fill();
}

// Room for the longest row label, measured in the chart's own font.
function fitLabels(ctx, box, rows) {
  ctx.font = `12px ${token("v-font-mono")}`;
  if (!box.fixed) box.l = Math.ceil(Math.max(...rows.map((r) => ctx.measureText(r).width))) + 20;
}

const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const lerp = (a, b, f) => (a == null ? null : b == null || !f ? a : a + (b - a) * f);

// ---------- player: play/pause, speed and a date scrubber over any list of frames ----------

export function player(root, { labels, onFrame, start = labels.length - 1, fps = 6, name = "frame" }) {
  const n = labels.length;
  root.classList.add("v-player");
  root.innerHTML = `<button type="button" class="v-btn v-btn--primary" data-play>Play</button>
    <label class="v-field">Speed <select data-speed><option value="0.5">0.5x</option><option value="1" selected>1x</option><option value="2">2x</option><option value="4">4x</option></select></label>
    <input class="v-scrub" type="range" min="0" max="${n - 1}" step="1" value="${start}" aria-label="Choose the ${name}" data-scrub>
    <output class="v-at" data-at></output>`;
  const btn = root.querySelector("[data-play]"), range = root.querySelector("[data-scrub]"), at = root.querySelector("[data-at]");
  let t = start, playing = false, speed = 1, visible = true, raf = 0, last = 0;

  const show = () => {
    const i = Math.floor(t), f = reduced.matches || i >= n - 1 ? 0 : t - i;
    range.value = i;
    at.textContent = labels[i];
    onFrame(i, f);
  };
  const frame = (now) => {
    raf = 0;
    if (!playing || !visible || document.hidden) return;
    t = Math.min(n - 1, t + Math.min(0.1, Math.max(0, now - last) / 1000) * fps * speed);  // a frame's timestamp can predate wake()
    last = now;
    if (t >= n - 1) set(false);
    show();
    if (playing) raf = requestAnimationFrame(frame);
  };
  // The loop runs only while playing, on screen and in a visible tab. Anything else leaves no frame scheduled.
  const wake = () => {
    if (raf || !playing || !visible || document.hidden) return;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  };
  const sleep = () => { cancelAnimationFrame(raf); raf = 0; };
  function set(on) {
    playing = on;
    btn.textContent = on ? "Pause" : "Play";
    btn.setAttribute("aria-pressed", on);
    on ? wake() : sleep();
  }
  btn.addEventListener("click", () => {
    if (!playing && t >= n - 1) t = 0;
    set(!playing);
    show();
  });
  root.querySelector("[data-speed]").addEventListener("change", (e) => { speed = +e.target.value; });
  range.addEventListener("input", () => { t = +range.value; show(); });
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible ? wake() : sleep(); });
  io.observe(root.closest("section") || root);
  const onVis = () => (document.hidden ? sleep() : wake());
  document.addEventListener("visibilitychange", onVis);
  show();
  return {
    get index() { return Math.floor(t); },
    redraw: show,
    destroy() { sleep(); io.disconnect(); document.removeEventListener("visibilitychange", onVis); },
  };
}

// ---------- profile: one line across categories per frame, with ghost trails and a reference frame ----------
// cfg: { x: [labels], frames: [[value|null per label]], unit, ghosts, colors: {current, ghost, reference} }

export function profile(el, cfg) {
  const s = stage(el, cfg.height || 320, cfg.label);
  const box = { l: 52, r: 16, t: 14, b: 30 };
  const [lo, hi] = extent(cfg.frames.flat(), 0.06, cfg.include || []);
  const ys = niceTicks(lo, hi);
  const x = (k) => box.l + (k / (cfg.x.length - 1)) * (s.w - box.l - box.r);
  const y = (v) => box.t + (1 - (v - lo) / (hi - lo)) * (s.h - box.t - box.b);
  const pts = (vals) => vals.map((v, k) => (v == null ? undefined : [x(k), y(v)])).filter(Boolean);
  let state = { i: cfg.frames.length - 1, f: 0, ref: null };

  s.draw = () => {
    const { ctx } = s, { i, f, ref } = state, cur = cfg.frames[i].map((v, k) => lerp(v, cfg.frames[i + 1]?.[k], f));
    ctx.clearRect(0, 0, s.w, s.h);
    grid(ctx, s, box, ys, y, (t) => t.toFixed(Math.abs(hi - lo) < 4 ? 1 : 0) + cfg.unit);
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    cfg.x.forEach((label, k) => {
      ctx.fillStyle = cur[k] == null ? token("v-rule-2") : token("v-muted");
      ctx.fillText(label, x(k), s.h - 8);
    });
    for (let g = cfg.ghosts || 0; g >= 1; g--) {
      if (i - g < 0) continue;
      ctx.globalAlpha = 0.5 * (1 - g / ((cfg.ghosts || 0) + 1));
      line(ctx, pts(cfg.frames[i - g]), cfg.colors.ghost, 1.5);
    }
    ctx.globalAlpha = 1;
    if (ref != null && cfg.frames[ref]) line(ctx, pts(cfg.frames[ref]), cfg.colors.reference, 2, [6, 5]);
    const now = pts(cur);
    line(ctx, now, cfg.colors.current, 2.5);
    now.forEach(([px, py]) => dot(ctx, px, py, cfg.colors.current, 4));
  };
  hover(s, (mx) => {
    const k = Math.round(((mx - box.l) / (s.w - box.l - box.r)) * (cfg.x.length - 1));
    if (k < 0 || k >= cfg.x.length) return null;
    const v = cfg.frames[state.i][k], r = state.ref != null ? cfg.frames[state.ref]?.[k] : null;
    return `<strong>${esc(cfg.x[k])}</strong><span>${v == null ? "not published" : v.toFixed(2) + cfg.unit}</span>`
      + (state.ref != null ? `<span class="v-muted">${cfg.refLabel?.(state.ref) || "reference"}: ${r == null ? "n/a" : r.toFixed(2) + cfg.unit}</span>` : "");
  });
  return { show(i, f, ref) { state = { i, f, ref }; s.draw(); } };
}

// ---------- series: lines over time, shaded ranges, a zero line and a cursor synced to the player ----------
// cfg: { dates: [labels], series: [{label, values, color}], shade: [[from index, to index, color]], unit, zero }

export function series(el, cfg) {
  const s = stage(el, cfg.height || 220, cfg.label);
  const box = { l: 52, r: 16, t: 12, b: 28 };
  const n = cfg.dates.length;
  const [lo, hi] = extent(cfg.series.flatMap((x) => x.values), 0.08, cfg.zero ? [0] : []);
  const ys = niceTicks(lo, hi, 4);
  const x = (i) => box.l + (n > 1 ? i / (n - 1) : 0.5) * (s.w - box.l - box.r);
  const y = (v) => box.t + (1 - (v - lo) / (hi - lo)) * (s.h - box.t - box.b);
  let state = { i: n - 1, f: 0 };
  const every = Math.max(1, Math.ceil(n / 8));

  s.draw = () => {
    const { ctx } = s;
    ctx.clearRect(0, 0, s.w, s.h);
    grid(ctx, s, box, ys, y, (t) => t.toFixed(cfg.dp ?? 1) + cfg.unit);
    for (const [a, b, color] of cfg.shade || []) {
      ctx.fillStyle = color;
      ctx.fillRect(x(a) - 0.5, box.t, Math.max(1, x(b) - x(a) + 1), s.h - box.t - box.b);
    }
    if (cfg.zero && lo < 0 && hi > 0) line(ctx, [[box.l, y(0)], [s.w - box.r, y(0)]], token("v-ink-2"), 1);
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic"; ctx.fillStyle = token("v-muted");
    for (let i = 0; i < n; i += every) ctx.fillText(cfg.tick ? cfg.tick(i) : cfg.dates[i], x(i), s.h - 8);
    for (const sr of cfg.series) {
      const pts = sr.values.map((v, i) => (v == null ? null : [x(i), y(v)]));
      line(ctx, pts, sr.color, 2);
      if (n <= 40) pts.forEach((p) => p && dot(ctx, p[0], p[1], sr.color, 3));
    }
    const { i, f } = state, cx = x(i + f);
    line(ctx, [[cx, box.t], [cx, s.h - box.b]], token("v-ink-2"), 1, [2, 3]);
    for (const sr of cfg.series) {
      const v = lerp(sr.values[i], sr.values[i + 1], f);
      if (v != null) dot(ctx, cx, y(v), sr.color, 5);
    }
  };
  hover(s, (mx) => {
    const i = Math.round(((mx - box.l) / (s.w - box.l - box.r)) * (n - 1));
    if (i < 0 || i >= n) return null;
    return `<strong>${esc(cfg.dates[i])}</strong>` + cfg.series.map((sr) => `<span><i class="v-key" style="--key:${sr.color}"></i>${esc(sr.label)}: ${sr.values[i] == null ? "n/a" : sr.values[i].toFixed(cfg.dp ?? 2) + cfg.unit}</span>`).join("");
  });
  return { show(i, f) { state = { i, f }; s.draw(); } };
}

// ---------- heatmap: rows by columns, colour = value, with a cursor column ----------
// cfg: { rows: [labels], cols: [labels], value(r, c), color(v), fmt(v), tick(c) }

export function heatmap(el, cfg) {
  const rowH = cfg.rowH || 22, s = stage(el, cfg.rows.length * rowH + 34, cfg.label);
  const box = { l: cfg.left || 52, fixed: !!cfg.left, r: 16, t: 6, b: 28 };
  const nc = cfg.cols.length, every = Math.max(1, Math.ceil(nc / 8));
  const x = (c) => box.l + (c / nc) * (s.w - box.l - box.r);
  let cur = nc - 1, cells = null;

  const paint = () => {  // cells change only with the width, so they are drawn once onto a buffer
    cells = document.createElement("canvas");
    const r = devicePixelRatio || 1, g = cells.getContext("2d");
    cells.width = s.canvas.width; cells.height = s.canvas.height;
    g.setTransform(r, 0, 0, r, 0, 0);
    const gap = nc < 120 ? 2 : 0;
    cfg.rows.forEach((_, ri) => {
      for (let c = 0; c < nc; c++) {
        const v = cfg.value(ri, c);
        g.fillStyle = v == null ? token("v-paper-3") : cfg.color(v);
        g.fillRect(x(c), box.t + ri * rowH, Math.max(1, x(c + 1) - x(c) - gap), rowH - 2);
      }
    });
    cells.w = s.w;
  };
  s.draw = () => {
    const { ctx } = s;
    if (!cells || cells.w !== s.w) { fitLabels(ctx, box, cfg.rows); paint(); }
    ctx.clearRect(0, 0, s.w, s.h);
    ctx.drawImage(cells, 0, 0, s.w, s.h);
    ctx.font = `12px ${token("v-font-mono")}`;
    ctx.fillStyle = token("v-muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    cfg.rows.forEach((label, ri) => ctx.fillText(label, box.l - 8, box.t + ri * rowH + rowH / 2 - 1));
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    for (let c = 0; c < nc; c += every) ctx.fillText(cfg.tick ? cfg.tick(c) : cfg.cols[c], x(c + 0.5), s.h - 8);
    ctx.strokeStyle = token("v-ink"); ctx.lineWidth = 2;
    ctx.strokeRect(x(cur), box.t - 2, Math.max(2, x(cur + 1) - x(cur)), cfg.rows.length * rowH + 2);
  };
  hover(s, (mx, my) => {
    const c = Math.floor(((mx - box.l) / (s.w - box.l - box.r)) * nc), ri = Math.floor((my - box.t) / rowH);
    if (c < 0 || c >= nc || ri < 0 || ri >= cfg.rows.length) return null;
    return `<strong>${esc(cfg.rows[ri])}</strong><span>${esc(cfg.cols[c])}</span><span>${cfg.fmt(cfg.value(ri, c))}</span>`;
  });
  return { show(i) { cur = i; s.draw(); } };
}

// ---------- surface: frames stacked in depth (x = category, depth = time, height = value), oblique projection ----------
// cfg: { x: [labels], frames, dates, window, color(v), current }

export function surface(el, cfg) {
  const s = stage(el, cfg.height || 360, cfg.label);
  const [lo, hi] = extent(cfg.frames.flat(), 0.02, [0]);
  const win = cfg.window || 120;
  let cur = cfg.frames.length - 1;

  s.draw = () => {
    const { ctx } = s, nx = cfg.x.length, depthX = Math.min(220, s.w * 0.28), depthY = 120;
    const l = 52, r = 16 + depthX, base = s.h - 34, top = 14 + depthY;
    const px = (k, z) => l + (k / (nx - 1)) * (s.w - l - r) + z * depthX;  // z: 0 front (now) .. 1 back (oldest)
    const py = (v, z) => base - ((v - lo) / (hi - lo)) * (base - top) - z * depthY;
    ctx.clearRect(0, 0, s.w, s.h);
    const first = Math.max(0, cur - win + 1);
    for (let i = first; i <= cur; i++) {  // back to front, so the newest curves sit on top
      const z = cur === first ? 0 : (cur - i) / win, vals = cfg.frames[i];
      const known = vals.filter((v) => v != null);
      if (!known.length) continue;
      const pts = vals.map((v, k) => (v == null ? undefined : [px(k, z), py(v, z)])).filter(Boolean);
      ctx.globalAlpha = 0.35 + 0.65 * (1 - z);
      line(ctx, pts, i === cur ? cfg.current : cfg.color(known.reduce((a, b) => a + b, 0) / known.length), i === cur ? 2.5 : 1);
    }
    ctx.globalAlpha = 1;
    ctx.font = `12px ${token("v-font-mono")}`; ctx.fillStyle = token("v-muted"); ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    cfg.x.forEach((label, k) => ctx.fillText(label, px(k, 0), s.h - 10));
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const t of niceTicks(lo, hi, 4)) ctx.fillText(t.toFixed(0) + (cfg.unit || ""), l - 8, py(t, 0));
    ctx.textAlign = "left";
    ctx.fillText(cfg.dates[first], px(nx - 1, (cur - first) / win) + 6, py(lo, (cur - first) / win));
    ctx.fillText(cfg.dates[cur], px(nx - 1, 0) + 6, py(lo, 0));
  };
  return { show(i) { cur = i; s.draw(); } };
}

// ---------- bars: a diverging stacked bar per row, parts in a fixed order, total marked ----------
// cfg: { rows: [labels], parts: [{label, color}], domain: [-1, 1], frames: [[[part values per row]]], totals: [[per row]] }

export function bars(el, cfg) {
  const rowH = 30, s = stage(el, cfg.rows.length * rowH + 30, cfg.label);
  const box = { l: cfg.left || 120, fixed: !!cfg.left, r: 64, t: 4, b: 26 };
  const [lo, hi] = cfg.domain;
  const x = (v) => box.l + ((v - lo) / (hi - lo)) * (s.w - box.l - box.r);
  let state = { i: cfg.frames.length - 1, f: 0 };

  s.draw = () => {
    const { ctx } = s, { i, f } = state;
    ctx.clearRect(0, 0, s.w, s.h);
    fitLabels(ctx, box, cfg.rows);
    for (const t of niceTicks(lo, hi, 4)) {
      line(ctx, [[Math.round(x(t)) + 0.5, box.t], [Math.round(x(t)) + 0.5, s.h - box.b]], token(t === 0 ? "v-ink-2" : "v-rule"), 1);
      ctx.fillStyle = token("v-muted"); ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
      ctx.fillText((t > 0 ? "+" : "") + t.toFixed(1), x(t), s.h - 8);
    }
    cfg.rows.forEach((label, ri) => {
      const yTop = box.t + ri * rowH + 6, h = rowH - 12;
      ctx.fillStyle = token("v-ink-2"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(label, box.l - 10, yTop + h / 2);
      let pos = 0, neg = 0;
      cfg.parts.forEach((part, k) => {
        const v = lerp(cfg.frames[i][ri][k], cfg.frames[i + 1]?.[ri][k], f) || 0;
        if (!v) return;
        const a = v > 0 ? pos : neg + v, b = v > 0 ? pos + v : neg;
        v > 0 ? (pos += v) : (neg += v);
        ctx.fillStyle = part.color;
        ctx.fillRect(x(a) + 1, yTop, Math.max(1, x(b) - x(a) - 2), h);  // 2px gap between parts
      });
      const total = lerp(cfg.totals[i][ri], cfg.totals[i + 1]?.[ri], f);
      if (total == null) return;
      ctx.fillStyle = token("v-ink");
      ctx.fillRect(x(total) - 1, yTop - 4, 2, h + 8);
      ctx.textAlign = "left";
      ctx.fillText((total > 0 ? "+" : "") + total.toFixed(2), s.w - box.r + 10, yTop + h / 2);
    });
  };
  hover(s, (mx, my) => {
    const ri = Math.floor((my - box.t) / rowH);
    if (ri < 0 || ri >= cfg.rows.length) return null;
    const vals = cfg.frames[state.i][ri];
    return `<strong>${esc(cfg.rows[ri])}: ${cfg.totals[state.i][ri].toFixed(2)}</strong>` + cfg.parts.map((p, k) => `<span><i class="v-key" style="--key:${p.color}"></i>${esc(p.label)} ${vals[k] == null ? "not used" : (vals[k] >= 0 ? "+" : "") + vals[k].toFixed(2)}</span>`).join("");
  });
  return { show(i, f) { state = { i, f }; s.draw(); } };
}

// ---------- scatter: one dot per entity moving frame by frame, with a short trail ----------
// cfg: { points: [{label, color, frames: [[x, y] | null]}], x: {label, ref}, y: {label, ref}, unit, trail }

export function scatter(el, cfg) {
  const s = stage(el, cfg.height || 320, cfg.label);
  const box = { l: 56, r: 16, t: 14, b: 40 };
  const all = cfg.points.flatMap((p) => p.frames.filter(Boolean));
  const [xl, xh] = extent(all.map((p) => p[0]), 0.1, [cfg.x.ref]), [yl, yh] = extent(all.map((p) => p[1]), 0.1, [cfg.y.ref]);
  const x = (v) => box.l + ((v - xl) / (xh - xl)) * (s.w - box.l - box.r);
  const y = (v) => box.t + (1 - (v - yl) / (yh - yl)) * (s.h - box.t - box.b);
  let state = { i: (cfg.points[0]?.frames.length || 1) - 1, f: 0 };

  s.draw = () => {
    const { ctx } = s, { i, f } = state;
    ctx.clearRect(0, 0, s.w, s.h);
    const dp = (lo, hi) => (hi - lo < 5 ? 1 : 0);
    grid(ctx, s, box, niceTicks(yl, yh, 4), y, (t) => t.toFixed(dp(yl, yh)) + cfg.unit);
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    for (const t of niceTicks(xl, xh, 5)) ctx.fillText(t.toFixed(dp(xl, xh)) + cfg.unit, x(t), s.h - 22);
    ctx.fillText(cfg.x.label, box.l + (s.w - box.l - box.r) / 2, s.h - 4);
    ctx.save(); ctx.translate(12, box.t + (s.h - box.t - box.b) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(cfg.y.label, 0, 0); ctx.restore();
    line(ctx, [[x(cfg.x.ref), box.t], [x(cfg.x.ref), s.h - box.b]], token("v-ink-2"), 1, [3, 4]);
    line(ctx, [[box.l, y(cfg.y.ref)], [s.w - box.r, y(cfg.y.ref)]], token("v-ink-2"), 1, [3, 4]);
    for (const p of cfg.points) {
      const trail = p.frames.slice(Math.max(0, i - (cfg.trail || 6)), i + 1).map((q) => (q ? [x(q[0]), y(q[1])] : null));
      ctx.globalAlpha = 0.45; line(ctx, trail, p.color, 1.5); ctx.globalAlpha = 1;
      const a = p.frames[i], b = p.frames[i + 1];
      if (!a) continue;
      const q = b && f ? [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f] : a;
      dot(ctx, x(q[0]), y(q[1]), p.color, 6);
    }
  };
  hover(s, (mx, my) => {
    let best = null, dist = 24;
    for (const p of cfg.points) {
      const q = p.frames[state.i];
      if (!q) continue;
      const d = Math.hypot(x(q[0]) - mx, y(q[1]) - my);
      if (d < dist) { dist = d; best = [p, q]; }
    }
    return best && `<strong>${esc(best[0].label)}</strong><span>${cfg.y.label}: ${best[1][1].toFixed(0)}${cfg.unit}</span><span>${cfg.x.label}: ${best[1][0].toFixed(0)}${cfg.unit}</span>`;
  });
  return { show(i, f) { state = { i, f }; s.draw(); } };
}
