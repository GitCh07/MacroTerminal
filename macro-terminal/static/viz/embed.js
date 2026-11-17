// Replays for Macro Terminal: a closed section at the foot of Board, Rates and Benchmarks. Nothing loads until one
// is opened; opening it loads static/viz/ in a frame, so its code and styles never touch the terminal's.
(() => {
  const SECTIONS = {
    board: ["bias", "How the bias got here"],
    rates: ["curve", "Yield curve over time"],
    benchmarks: ["bench", "Your returns vs. benchmarks over time"],
  };
  const isOpen = (view) => { try { return localStorage.getItem("mt.replay." + view) === "open"; } catch { return false; } };
  const remember = (view, open) => { try { localStorage.setItem("mt.replay." + view, open ? "open" : "closed"); } catch { /* not kept */ } };
  let host = null, frame = null, shown = null;

  function route() {
    const key = (location.hash.slice(1) || "board").split("/")[0];
    if (key === shown) return;
    host?.remove();  // leaving a tab drops its replay, and with it every timer and listener inside
    host = frame = null;
    shown = key;
    if (!SECTIONS[key]) return;
    const [view, title] = SECTIONS[key];
    host = document.createElement("section");
    host.className = "container replay";
    host.id = "viz-host";
    host.innerHTML = `<details><summary>${title}</summary><p class="muted replay__wait" role="status">Loading the chart.</p></details>`;
    const box = host.firstElementChild;
    box.addEventListener("toggle", () => {
      remember(view, box.open);
      if (!box.open || frame) return;  // closing keeps the frame, so reopening is instant; a closed frame draws nothing
      frame = document.createElement("iframe");
      frame.className = "replay__frame";
      frame.title = title;
      frame.src = "viz/index.html?view=" + view;
      box.append(frame);
    });
    document.getElementById("app").after(host);
    box.open = isOpen(view);
  }

  addEventListener("message", (e) => {
    if (!frame || e.source !== frame.contentWindow || e.origin !== location.origin || e.data?.mtviz !== "height") return;
    frame.style.height = e.data.h + "px";
    host.querySelector(".replay__wait")?.remove();
  });
  // When the terminal takes in new data, an open replay waits for its matching frames and reloads.
  let seen = null;
  new MutationObserver(() => {
    const now = typeof S !== "undefined" && S ? S.fetched_at : null;
    if (seen && now && now !== seen && frame) frame.contentWindow.postMessage({ mtviz: "refresh", for: now }, location.origin);
    seen = now || seen;
  }).observe(document.getElementById("updated"), { childList: true, characterData: true, subtree: true });
  addEventListener("hashchange", route);
  route();
})();
