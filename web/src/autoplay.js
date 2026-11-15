// Demo autoplay for recording the video: open http://localhost:5173/?autoplay
// It resets the demo once, then each press of → (Right arrow, Page Down or Space) runs the next step,
// clicking the real buttons in the real app, so you can talk at your own pace while screen-recording.
// Hands-free: ?autoplay&auto=8 runs every step by itself, 8 seconds apart. Esc stops it.
// Nothing here changes how the app works when ?autoplay is not in the URL.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (sel, root = document) => root.querySelector(sel);
const byText = (sel, text, root = document) =>
  [...root.querySelectorAll(sel)].find((el) => el.textContent.trim().startsWith(text) && !el.disabled);

async function waitFor(fn, what, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await sleep(200);
  }
  throw new Error(`Autoplay: timed out waiting for ${what}`);
}

// A short ring around whatever gets "clicked", so viewers can see it in the recording.
function flash(el) {
  el.scrollIntoView({ block: "nearest" });
  el.classList.add("autoplay-click");
  setTimeout(() => el.classList.remove("autoplay-click"), 900);
}
async function click(el) { flash(el); await sleep(450); el.click(); }

// React-controlled inputs/selects need the native setter + an event React listens to.
function setValue(el, value, event) {
  const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
  el.dispatchEvent(new Event(event, { bubbles: true }));
}

const chip = (label) => waitFor(() => byText(".prompts .chip", label), `chip "${label}"`);
const caseDone = (cls) => waitFor(() => !$(".typing") && $(`.chat-panel .outcome${cls}`), "the case to finish");
const reviewOps = () => waitFor(() => byText("button", "Review in Ops approvals"), "the case to pause for Ops");

async function signIn(mid) {
  const tab = byText(".tabs button", "Merchant");
  if (tab && !tab.classList.contains("on")) await click(tab);
  const sel = await waitFor(() => $("#merchant"), "the merchant picker");
  flash(sel);
  setValue(sel, mid, "change");
  await sleep(700);
}

async function approve() {
  const box = await waitFor(() => $("#reviewer"), "the reviewer box");
  if (!box.value.trim()) setValue(box, "Navaneethamahavishnu", "input");
  await sleep(300);
  await click(await waitFor(() => byText(".ops-embedded .btn.approve", "Approve"), "the Approve button"));
}

// Seconds after the first → press at which each step starts (timed mode). Matches VIDEO_SCRIPT.md.
const TIMED_AT = [20, 50, 66, 76, 82, 98, 116, 125, 130, 138];
const END_AT = 175;
const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const STEPS = [
  ["Case 1 · Tamil payout (R-07)", async () => {
    await signIn("M1001");
    await click(await chip("Payout missing (Tamil)"));
    await caseDone(".ok");
  }],
  ["Case 2 · ₹12,000 charged twice (R-22 pauses)", async () => {
    await signIn("M1002");
    await click(await chip("Charged twice ₹12,000"));
    await reviewOps();
  }],
  ["Case 2 · open Ops approvals", async () => { await click(await reviewOps()); }],
  ["Case 2 · Approve", async () => { await approve(); await caseDone(".ok"); }],
  ["Case 3 · someone else's order (G-01)", async () => {
    await signIn("M1003");
    await click(await chip("Someone else's order"));
    await caseDone(".esc");
  }],
  ["Case 4 · ₹7,200 double payment, ask the customer", async () => {
    await click(await waitFor(() => byText(".tabs button", "Customer"), "the Customer tab"));
    const sel = await waitFor(() => $("#vpa"), "the customer picker");
    flash(sel);
    setValue(sel, "lalitha@okaxis", "change");
    await sleep(700);
    await click(await waitFor(() => byText("button", "⚡ Simulate double payment (ORD-6004)"), "the simulate button"));
    await waitFor(() => byText("button", "Refund one"), "the customer's question");
  }],
  ["Case 4 · customer taps Refund one (R-22 pauses)", async () => {
    await click(byText("button", "Refund one"));
    await reviewOps();
  }],
  ["Case 4 · open Ops approvals", async () => { await click(await reviewOps()); }],
  ["Case 4 · Approve", async () => {
    await approve();
    await waitFor(() => $(".gnode.k-people.visited.current"), "both parties to be notified");
  }],
  ["History", async () => { await click(await waitFor(() => byText('[role="tab"]', "History"), "the History tab")); }],
];

export function startAutoplay() {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("autoplay")) return;

  // First load: reset the demo once, then reload into a clean app.
  if (params.get("autoplay") !== "go") {
    let token = "demo-ops-token";
    try { token = localStorage.getItem("msa.token") || import.meta.env.VITE_OPS_TOKEN || token; } catch { /* default */ }
    fetch("/api/demo/reset", { method: "POST", headers: { "X-Ops-Token": token } })
      .then((r) => {
        if (!r.ok) throw new Error(`reset failed (${r.status}). Check the Ops token in the Ops approvals tab.`);
        const keep = new URLSearchParams();
        keep.set("autoplay", "go");
        for (const k of ["auto", "timed"]) if (params.has(k)) keep.set(k, params.get(k) || "1");
        window.location.replace(`${window.location.pathname}?${keep}`);
      })
      .catch((e) => alert(`Autoplay: ${e.message}`));
    return;
  }

  let i = 0, busy = false, stopped = false;
  const hint = document.createElement("div");
  hint.className = "autoplay-hint";
  document.body.appendChild(hint);
  const show = () => {
    hint.textContent = i < STEPS.length ? `→ next: ${STEPS[i][0]}  (${i + 1}/${STEPS.length})` : "Autoplay finished";
  };
  show();

  async function next() {
    if (stopped || busy || i >= STEPS.length) return;
    busy = true;
    hint.classList.add("running");
    try {
      await STEPS[i][1]();
      i += 1;
    } catch (err) {
      console.error(err);
      alert(`${err.message}\nFix it by hand, then press → to retry this step.`);
    } finally {
      busy = false;
      hint.classList.remove("running");
      show();
    }
  }

  // ?timed: press → once to start the clock; each step then fires at a fixed second (fits a 3:00 video).
  const timed = params.has("timed");
  let t0 = null;
  async function runTimed() {
    t0 = Date.now();
    const tick = setInterval(() => {
      if (stopped) return clearInterval(tick);
      const sec = Math.floor((Date.now() - t0) / 1000);
      const at = TIMED_AT[i];
      hint.textContent = i < STEPS.length
        ? `${fmt(sec)} · ${STEPS[i][0]} in ${Math.max(0, at - sec)}s`
        : `${fmt(sec)} · finished, wrap up by ${fmt(END_AT)}`;
    }, 250);
    while (!stopped && i < STEPS.length) {
      const wait = t0 + TIMED_AT[i] * 1000 - Date.now();
      if (wait > 0) await sleep(wait);
      const before = i;
      await next();
      if (i === before) break;
    }
  }

  window.addEventListener("keydown", (e) => {
    if (stopped) return;
    if (e.key === "Escape") { stopped = true; hint.remove(); return; }
    if (!["ArrowRight", "PageDown", " "].includes(e.key)) return;
    if (e.target.matches?.("input, textarea, select")) return;
    e.preventDefault();
    if (timed) { if (t0 === null) runTimed(); return; }
    next();
  });
  if (timed) hint.textContent = "Timed run: start recording, then press → to start the clock";
  if (params.get("timed") === "now") runTimed();        // starts the clock on load (used for testing)

  const auto = Number(params.get("auto"));
  if (auto > 0) {
    (async () => {
      await sleep(auto * 1000);
      while (!stopped && i < STEPS.length) {
        const before = i;
        await next();
        if (i === before) break;          // a step failed: stop the hands-free run
        await sleep(auto * 1000);
      }
    })();
  }
}
