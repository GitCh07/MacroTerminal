// Animations toggle for Macro Terminal. Off by default: off, this adds one header button and runs nothing else.
// On, the Board, Rates and Benchmarks tabs each get their replay below the view, loaded from static/viz/ in a frame,
// so its code and styles never touch the terminal's.
(() => {
  const KEY = "mt.animations";
  const read = () => { try { return localStorage.getItem(KEY) === "on"; } catch { return false; } };
  const save = (on) => { try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* not saved */ } };
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn";
  btn.textContent = "Animations";
  document.getElementById("refresh").before(btn);
  let on = read(), host = null, frame = null;

  const REPLAYS = { board: ["bias", "Replay of why each market's bias moved"], rates: ["curve", "Replay of the Treasury yield curve"],
    benchmarks: ["bench", "Benchmarks over time"] };
  function route() {
    const v = REPLAYS[(location.hash.slice(1) || "board").split("/")[0]], src = on && v ? "viz/index.html?view=" + v[0] : null;
    if (frame && frame.dataset.src === src) return;
    host?.remove();  // leaving a view drops its frame, and with it every timer and listener inside
    host = frame = null;
    if (!src) return;
    host = document.createElement("div");
    host.className = "container";
    host.id = "viz-host";
    frame = document.createElement("iframe");
    frame.dataset.src = frame.src = src;
    frame.title = v[1];
    frame.style.cssText = "display:block;width:100%;height:640px;border:0";
    host.append(frame);
    document.getElementById("app").after(host);
  }
  function set(next) {
    on = next;
    btn.setAttribute("aria-pressed", on);
    route();
  }
  btn.addEventListener("click", () => { save(!on); set(!on); });
  addEventListener("hashchange", route);
  addEventListener("message", (e) => {
    if (frame && e.source === frame.contentWindow && e.origin === location.origin && e.data?.mtviz === "height") frame.style.height = e.data.h + "px";
  });
  set(on);
})();
