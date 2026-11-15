import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import TopBar from "./components/TopBar.jsx";
import Chat, { demoPin } from "./components/Chat.jsx";
import Timeline from "./components/Timeline.jsx";
import CustomerPhone from "./components/CustomerPhone.jsx";

const DEFAULT_TOKEN = import.meta.env.VITE_OPS_TOKEN || "demo-ops-token";
const tokenFromStorage = () => { try { return localStorage.getItem("msa.token") || DEFAULT_TOKEN; } catch { return DEFAULT_TOKEN; } };

export default function App() {
  // ----- shared state (React re-renders the page whenever these change) -----
  const [merchants, setMerchants] = useState([]);
  const [mid, setMid] = useState("M1001");
  const [pin, setPin] = useState("0001");
  const [token, setTokenState] = useState(tokenFromStorage);
  const [llm, setLlm] = useState("");
  const [stats, setStats] = useState(null);

  const [caseId, setCaseId] = useState(null);       // the case shown in chat + timeline
  const [view, setView] = useState(null);           // GET /cases/{id}
  const [events, setEvents] = useState([]);         // GET /cases/{id}/events, accumulated
  const [pending, setPending] = useState(null);     // merchant bubble shown before the server echoes it
  const [busy, setBusy] = useState(false);          // a request is in flight
  const [error, setError] = useState("");
  const [voiceIds, setVoiceIds] = useState(() => new Set());
  const [pollKey, setPollKey] = useState(0);        // bump to (re)start polling
  const [opsKey, setOpsKey] = useState(0);
  const [leftTab, setLeftTab] = useState("merchant"); // merchant chat | customer phone (Case 4)
  const [vpa, setVpa] = useState("vasanth@oksbi");
  const lastId = useRef(0);

  const setToken = (t) => { setTokenState(t); try { localStorage.setItem("msa.token", t); } catch { /* ignore */ } };

  // ----- load merchants + LLM mode once; open #case=CASE-XXXX links -----
  useEffect(() => {
    api.merchants().then(setMerchants).catch((e) => setError(e.message));
    api.health().then((h) => setLlm(h.llm)).catch(() => {});
    const m = window.location.hash.match(/^#case=(CASE-[0-9A-F]{8})(&customer)?$/);
    if (m) { openCase(m[1]); if (m[2]) setLeftTab("customer"); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ----- stats strip every 3s -----
  useEffect(() => {
    const tick = () => api.stats().then(setStats).catch(() => {});
    tick();
    const t = setInterval(tick, 3000);
    return () => clearInterval(t);
  }, []);

  // ----- live timeline: poll events + case view about once a second -----
  useEffect(() => {
    if (!caseId) return;
    let stop = false;
    let timer;
    async function pull() {
      const ev = await api.events(caseId, lastId.current);
      if (stop || !ev.events.length) return ev;
      lastId.current = ev.events[ev.events.length - 1].id;
      setEvents((xs) => [...xs, ...ev.events]);
      return ev;
    }
    async function tick() {
      try {
        const ev = await pull();
        const v = await api.getCase(caseId);
        if (stop) return;
        setView(v);
        // Keep the merchant picker on the case's merchant (e.g. a case opened from Ops or a link).
        if (v.mid) setMid((cur) => { if (cur !== v.mid) setPin(demoPin(v.mid)); return v.mid; });
        if (v.messages?.length) setPending(null);
        const waiting = v.status === "waiting_approval" || v.status === "waiting_customer";
        const finished = !v.running && !ev.running && !waiting;
        if (finished) { await pull(); return; }      // one last pull so no trailing event is missed
      } catch (e) {
        if (!stop) setError(e.message);
      }
      if (!stop) timer = setTimeout(tick, 900);
    }
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [caseId, pollKey]);

  // Show a case from scratch (new case, proactive case, or one opened from Ops).
  const openCase = useCallback((id) => {
    lastId.current = 0;
    setEvents([]);
    setView(null);
    setCaseId(id);
    setPollKey((k) => k + 1);
  }, []);

  async function run(fn) {
    setBusy(true);
    setError("");
    try { return await fn(); }
    catch (e) { setError(e.message); setPending(null); }
    finally { setBusy(false); }
  }

  // ----- merchant actions -----
  const followUp = view?.status === "needs_info" && !view?.running;

  const send = (text) => run(async () => {
    setPending({ text, voice: false });
    if (followUp) {
      await api.sendMessage(caseId, text);
      setPollKey((k) => k + 1);
    } else {
      const r = await api.createCase(mid, pin, text);
      openCase(r.case_id);
    }
  });

  const sendVoice = (blob) => run(async () => {
    setPending({ text: "🎤 transcribing…", voice: true });
    const r = followUp ? await api.voiceMessage(caseId, blob) : await api.voiceCase(mid, pin, blob);
    setVoiceIds((s) => new Set(s).add(r.case_id));
    setPending({ text: r.transcript, voice: true });
    if (followUp) setPollKey((k) => k + 1);
    else openCase(r.case_id);
  });

  const sendSample = () => run(async () => {
    setMid("M1001");
    setPin("0001");
    setPending({ text: "🎤 transcribing Tamil sample…", voice: true });
    const blob = await (await fetch("/case1_tamil.wav")).blob();
    const r = await api.voiceCase("M1001", "0001", new Blob([blob], { type: "audio/wav" }));
    setVoiceIds((s) => new Set(s).add(r.case_id));
    setPending({ text: r.transcript, voice: true });
    openCase(r.case_id);
  });

  const newCase = () => { setCaseId(null); setView(null); setEvents([]); setPending(null); };

  // ----- ops actions -----
  const proactive = () => run(async () => {
    try {
      const r = await api.payoutFailed(token, "PO-1001");
      setMid("M1001");
      setPin(demoPin("M1001"));
      setPending(null);
      openCase(r.case_id);
    } catch (e) {
      if (e.status === 409) throw new Error("PO-1001 isn't failed any more (already fixed). Press Reset demo first.");
      throw e;
    }
  });

  const reset = () => {
    if (!window.confirm("Reset all demo data and saved cases?")) return;
    run(async () => {
      await api.reset(token);
      newCase();
      setVoiceIds(new Set());
      setOpsKey((k) => k + 1);
      setStats(await api.stats());
    });
  };

  const onDecided = (id) => (id === caseId ? setPollKey((k) => k + 1) : openCase(id));

  // Case 4: the payment system reports a double payment. Show the CUSTOMER's phone.
  const doublePayment = () => run(async () => {
    try {
      const r = await api.duplicatePayment(token, "ORD-6002");
      setVpa("vasanth@oksbi");
      setLeftTab("customer");
      setPending(null);
      openCase(r.case_id);
    } catch (e) {
      if (e.status === 409) throw new Error("That double payment was already handled. Press Reset to replay it.");
      throw e;
    }
  });

  const tabs = (
    <div className="tabs" role="tablist">
      <button role="tab" aria-selected={leftTab === "merchant"} className={leftTab === "merchant" ? "on" : ""} onClick={() => setLeftTab("merchant")}>Merchant</button>
      <button role="tab" aria-selected={leftTab === "customer"} className={leftTab === "customer" ? "on" : ""} onClick={() => setLeftTab("customer")}>Customer</button>
    </div>
  );

  const shownView = view && { ...view, voice: voiceIds.has(caseId) };

  return (
    <div className="app">
      <TopBar stats={stats} llm={llm} onProactive={proactive} onDouble={doublePayment} onReset={reset} busy={busy} />
      {error && (
        <div className="error banner" role="alert">
          {error} <button className="link" onClick={() => setError("")}>dismiss</button>
        </div>
      )}
      <main className="grid">
        {leftTab === "merchant" ? (
          <Chat tabs={tabs} merchants={merchants} mid={mid} setMid={setMid} pin={pin} setPin={setPin}
            view={shownView} pending={pending} busy={busy}
            onSend={send} onVoice={sendVoice} onSample={sendSample} onNewCase={newCase} />
        ) : (
          <CustomerPhone tabs={tabs} vpa={vpa} setVpa={setVpa} opsToken={token}
            onOpenCase={openCase} onDecided={onDecided} onError={setError} />
        )}
        <Timeline caseId={caseId} view={view} events={events}
          ops={{ token, setToken, onDecided, onOpen: openCase, refreshKey: opsKey }} merchants={merchants} />
      </main>
    </div>
  );
}
