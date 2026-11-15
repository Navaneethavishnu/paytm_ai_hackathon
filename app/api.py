"""FastAPI backend. The Expo app (Step 5) is just a client of these endpoints.

Run:  .venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
      (0.0.0.0 so a phone on the same Wi-Fi can reach it; http://<laptop-LAN-IP>:8000)

Merchant endpoints: POST /cases, POST /cases/{id}/messages, GET /cases/{id}, GET /cases/{id}/events,
                    POST /cases/voice, POST /cases/{id}/voice  (raw audio body; Sarvam Saaras v4)
Ops endpoints (X-Ops-Token): GET /approvals, POST /approvals/{id}, POST /demo/reset, POST /events/payout-failed,
                             POST /events/duplicate-payment, POST /cases/{id}/customer-no-reply
Customer endpoints (Case 4): GET /customer/inbox?vpa=, POST /customer/decisions/{id} (one-time token + hash)
Demo helpers: GET /demo/merchants, GET /stats, GET /health

Cases run in a background thread so the app can poll /events and watch the timeline fill in live.
"""
import logging
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import audit, voice
from app import mock_systems as ms
from app.agent import graph as agent
from app.config import get_settings
from app.db import session_scope
from app.llm import OfflineLLM, get_llm
from app.models import AuditEvent, Merchant, Payout, Transaction
from app.seed import reset_and_seed

log = logging.getLogger("msa")
MAX_BODY_BYTES = 16_000

app = FastAPI(title="Merchant Success AI", version="0.4")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Ops-Token", "X-Mid", "X-Phone-Last4", "X-Language"])


# ---------------- LLMs (lazy; offline if no key) ----------------
_LLMS: tuple | None = None


def llms() -> tuple:
    global _LLMS
    if _LLMS is None:
        s = get_settings()
        try:
            _LLMS = (OfflineLLM(), OfflineLLM()) if s.llm_offline else (get_llm(), get_llm(purpose="reply"))
        except RuntimeError as e:          # no API key: still demo-able with deterministic fallbacks
            log.warning("LLM unavailable (%s); running offline", e)
            _LLMS = (OfflineLLM(), OfflineLLM())
    return _LLMS


def set_llms(llm, reply_llm=None):
    """Tests / demo mode can inject models."""
    global _LLMS
    _LLMS = (llm, reply_llm or llm)


# ---------------- background runner ----------------
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="case")
_RUNNING: set[str] = set()
_ERRORS: dict[str, str] = {}
_LOCK = threading.Lock()


def _submit(case_id: str, fn, /, *args, **kwargs):
    with _LOCK:
        if case_id in _RUNNING:
            raise HTTPException(409, "case is already being processed")
        _RUNNING.add(case_id)
        _ERRORS.pop(case_id, None)

    def job():
        try:
            fn(*args, **kwargs)
        except Exception as e:  # never lose a case silently
            log.exception("case %s crashed", case_id)
            _ERRORS[case_id] = type(e).__name__
            audit.log(case_id, "error", "agent_crash", {"error": f"{type(e).__name__}: {str(e)[:200]}"})
        finally:
            with _LOCK:
                _RUNNING.discard(case_id)
    _POOL.submit(job)


# ---------------- guards ----------------
_HITS: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now, q = time.monotonic(), _HITS[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= get_settings().rate_limit_per_min:
        raise HTTPException(429, "Too many requests. Try again in a minute.")
    q.append(now)


def require_ops(x_ops_token: str | None = Header(default=None)):
    if not x_ops_token or x_ops_token != get_settings().ops_token:
        raise HTTPException(401, "Ops token required")


@app.middleware("http")
async def limit_body(request: Request, call_next):
    limit = voice.MAX_AUDIO_BYTES if request.url.path.endswith("/voice") else MAX_BODY_BYTES
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    return await call_next(request)


# ---------------- schemas ----------------
MID = Field(pattern=r"^M\d{4}$")


class NewCase(BaseModel):
    mid: str = MID
    phone_last4: str = Field(pattern=r"^\d{4}$")
    text: str = Field(min_length=1, max_length=1000)


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=64)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


class PayoutFailed(BaseModel):
    payout_id: str = Field(pattern=r"^PO-\d{1,10}$")


# ---------------- views ----------------
def case_view(case_id: str) -> dict:
    """What the merchant app and timeline may see. No raw evidence."""
    s = agent.get_case(case_id)
    running = case_id in _RUNNING
    if not s and not running and case_id not in _ERRORS:
        raise HTTPException(404, "case not found")
    pd, d = s.get("policy_decision") or {}, s.get("diagnosis") or {}
    return {
        "case_id": case_id, "running": running, "error": _ERRORS.get(case_id),
        "status": s.get("status", "open"), "source": s.get("source", "merchant"), "trigger": s.get("trigger"),
        "mid": s.get("mid"), "order_id": s.get("order_id"), "language": s.get("language"),
        "messages": s.get("messages", []), "reply": s.get("reply"),
        "diagnosis": d.get("code"),
        "policy": {"tier": pd.get("tier"), "rule_id": pd.get("rule_id"), "reason": pd.get("reason")} if pd else None,
        "approval": s.get("approval"), "ticket_id": s.get("ticket_id"),
        "verification": s.get("verification"), "citation": s.get("citation"),
    }


# ---------------- merchant endpoints ----------------
@app.get("/health")
def health():
    return {"ok": True, "llm": type(llms()[0]).__name__}


@app.get("/demo/merchants")
def demo_merchants():
    with session_scope() as s:
        return [{"mid": m.mid, "name": m.name, "language": m.language, "city": m.city}
                for m in s.query(Merchant).order_by(Merchant.mid)]


@app.post("/cases", status_code=202, dependencies=[Depends(rate_limit)])
def create_case(body: NewCase):
    case_id = agent.new_case_id()
    llm, reply_llm = llms()
    _submit(case_id, agent.run_case, body.text, body.mid, body.phone_last4,
            llm=llm, reply_llm=reply_llm, case_id=case_id)
    return {"case_id": case_id, "status": "open", "running": True}


@app.post("/cases/{case_id}/messages", status_code=202, dependencies=[Depends(rate_limit)])
def add_message(case_id: str, body: NewMessage):
    s = agent.get_case(case_id)
    if not s:
        raise HTTPException(404, "case not found")
    if s.get("status") != "needs_info":
        raise HTTPException(409, f"case is {s.get('status')}; start a new case for a new issue")
    llm, reply_llm = llms()
    _submit(case_id, agent.continue_case, case_id, body.text, llm=llm, reply_llm=reply_llm)
    return {"case_id": case_id, "running": True}


# ---------------- voice (Step 6) ----------------
# Raw audio body (no multipart dependency): Expo's FileSystem.uploadAsync(BINARY_CONTENT) sends exactly this.
# mid / phone digits travel in headers, never in the URL, so they don't land in access logs.
_MID_RE, _PIN_RE = re.compile(r"^M\d{4}$"), re.compile(r"^\d{4}$")


async def _transcribe_request(request: Request) -> dict:
    audio = await request.body()
    try:
        return await run_in_threadpool(voice.transcribe, audio, request.headers.get("content-type", ""),
                                       request.headers.get("x-language", "unknown"))
    except voice.VoiceError as e:
        raise HTTPException(400, str(e))


@app.post("/cases/voice", status_code=202, dependencies=[Depends(rate_limit)])
async def create_case_by_voice(request: Request, x_mid: str = Header(), x_phone_last4: str = Header()):
    if not _MID_RE.match(x_mid) or not _PIN_RE.match(x_phone_last4):
        raise HTTPException(422, "X-Mid must look like M1001 and X-Phone-Last4 must be 4 digits")
    stt = await _transcribe_request(request)
    case_id = agent.new_case_id()
    audit.log(case_id, "tool", "speech_to_text", {"model": "saaras:v4", "language": stt["language_code"],
                                                 "raw": stt["raw_transcript"], "normalized": stt["transcript"]})
    llm, reply_llm = llms()
    _submit(case_id, agent.run_case, stt["transcript"], x_mid, x_phone_last4,
            llm=llm, reply_llm=reply_llm, case_id=case_id)
    return {"case_id": case_id, "running": True, "transcript": stt["transcript"],
            "language_code": stt["language_code"]}


@app.post("/cases/{case_id}/voice", status_code=202, dependencies=[Depends(rate_limit)])
async def add_voice_message(case_id: str, request: Request):
    s = agent.get_case(case_id)
    if not s:
        raise HTTPException(404, "case not found")
    if s.get("status") != "needs_info":
        raise HTTPException(409, f"case is {s.get('status')}; start a new case for a new issue")
    stt = await _transcribe_request(request)
    audit.log(case_id, "tool", "speech_to_text", {"model": "saaras:v4", "language": stt["language_code"],
                                                 "raw": stt["raw_transcript"], "normalized": stt["transcript"]})
    llm, reply_llm = llms()
    _submit(case_id, agent.continue_case, case_id, stt["transcript"], llm=llm, reply_llm=reply_llm)
    return {"case_id": case_id, "running": True, "transcript": stt["transcript"]}


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    return case_view(case_id)


@app.get("/cases/{case_id}/events")
def get_events(case_id: str, after: int = 0):
    """Timeline. The app polls this every ~1s with the last event id it has seen."""
    return {"case_id": case_id, "running": case_id in _RUNNING, "events": audit.events(case_id, after_id=after)}


# ---------------- ops endpoints ----------------
def _cases_with(kind: str, name: str) -> list[str]:
    with session_scope() as s:
        rows = s.query(AuditEvent.case_id).filter_by(kind=kind, name=name).distinct().all()
        return [r[0] for r in rows]


@app.get("/approvals", dependencies=[Depends(require_ops)])
def pending_approvals():
    out = []
    for cid in _cases_with("approval", "requested"):
        s = agent.get_case(cid)
        if s.get("status") == "waiting_approval" and cid not in _RUNNING:
            out.append({"case_id": cid, "mid": s["mid"], "order_id": s.get("order_id"),
                        "pack": s["approval_request"]["pack"], "evidence_hash": s["approval_request"]["hash"]})
    return out


@app.post("/approvals/{case_id}", dependencies=[Depends(require_ops)])
def decide_approval(case_id: str, body: Decision):
    if case_id in _RUNNING:
        raise HTTPException(409, "case is being processed")
    llm, reply_llm = llms()
    try:
        agent.decide(case_id, body.decision, body.reviewer, body.evidence_hash, llm=llm, reply_llm=reply_llm)
    except agent.ApprovalError as e:
        raise HTTPException(409 if "not waiting" in str(e) else 400, str(e))
    return case_view(case_id)


@app.post("/demo/reset", dependencies=[Depends(require_ops)])
def demo_reset():
    if _RUNNING:
        raise HTTPException(409, "wait for running cases to finish")
    reset_and_seed()
    agent.reset_checkpoints()
    _ERRORS.clear()
    _HITS.clear()
    return {"ok": True}


@app.post("/events/payout-failed", status_code=202, dependencies=[Depends(require_ops)])
def payout_failed(body: PayoutFailed):
    """Proactive mode: a system event opens a case with no merchant message. Same graph."""
    with session_scope() as s:
        p = s.get(Payout, body.payout_id)
        if p is None:
            raise HTTPException(404, "payout not found")
        if p.status != "FAILED":
            raise HTTPException(409, f"payout is {p.status}, not FAILED")
        t = s.query(Transaction).filter(Transaction.txn_id == p.txn_ids[0]).one()
        m = s.get(Merchant, p.mid)
        mid, order_id, reason, lang = p.mid, t.order_id, p.failure_reason, m.language
    case_id = agent.new_case_id()
    text = f"System event: payout {body.payout_id} for order {order_id} failed ({reason})."
    llm, reply_llm = llms()
    _submit(case_id, agent.run_case, text, mid, llm=llm, reply_llm=reply_llm,
            case_id=case_id, source="system", language=lang, trigger="payout_failed")
    return {"case_id": case_id, "status": "open", "running": True}


# ---------------- Case 4: proactive duplicate payment, customer decides ----------------
class DuplicateEvent(BaseModel):
    order_id: str = Field(pattern=r"^ORD-\d{1,10}$")


class CustomerDecision(BaseModel):
    decision: Literal["keep", "refund"]
    token: str = Field(pattern=r"^[0-9a-f]{16}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


_VPA_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}@[A-Za-z]{2,32}$")


@app.post("/events/duplicate-payment", status_code=202, dependencies=[Depends(require_ops)])
def duplicate_payment(body: DuplicateEvent):
    """The payment system saw the same customer pay the same bill twice. Nobody complained:
    open a case that asks the CUSTOMER whether to keep both or refund one."""
    with session_scope() as s:
        t = s.query(Transaction).filter_by(order_id=body.order_id).one_or_none()
        if t is None:
            raise HTTPException(404, "order not found")
        mid, lang = t.mid, s.get(Merchant, t.mid).language
    if not ms.find_duplicate_payments(mid, body.order_id)["duplicates"]:
        raise HTTPException(409, "no duplicate payment for this order (or it was already handled)")
    case_id = agent.new_case_id()
    text = f"System event: duplicate payment detected on order {body.order_id} at {mid}."
    llm, reply_llm = llms()
    _submit(case_id, agent.run_case, text, mid, llm=llm, reply_llm=reply_llm, case_id=case_id,
            source="system", language=lang, trigger="duplicate_payment")
    return {"case_id": case_id, "status": "open", "running": True}


@app.get("/customer/inbox", dependencies=[Depends(rate_limit)])
def customer_inbox(vpa: str):
    """The customer's phone. DEMO-GRADE identity: in production this is the customer's logged-in
    payments app, and the one-time token arrives by push notification."""
    if not _VPA_RE.match(vpa):
        raise HTTPException(422, "vpa must look like name@bank")
    out = []
    for cid in _cases_with("customer", "asked"):
        s = agent.get_case(cid)
        if s.get("customer_vpa") != vpa:
            continue                                   # only YOUR payments
        ask = s.get("customer_ask") or {}
        pending = s.get("status") == "waiting_customer" and cid not in _RUNNING
        out.append({"case_id": cid, "status": s.get("status"), "merchant": (s.get("merchant") or {}).get("name"),
                    "messages": s.get("customer_messages", []),
                    "ask": {"token": ask["token"], "evidence_hash": ask["hash"]} if pending else None})
    return out


@app.post("/customer/decisions/{case_id}", dependencies=[Depends(rate_limit)])
def customer_decision(case_id: str, body: CustomerDecision):
    if case_id in _RUNNING:
        raise HTTPException(409, "case is being processed")
    llm, reply_llm = llms()
    try:
        agent.customer_decide(case_id, body.decision, body.evidence_hash, token=body.token, llm=llm, reply_llm=reply_llm)
    except agent.ApprovalError as e:
        raise HTTPException(409 if "not waiting" in str(e) else 403, str(e))
    return case_view(case_id)


@app.post("/cases/{case_id}/customer-no-reply", dependencies=[Depends(require_ops)])
def customer_no_reply(case_id: str):
    """Ops/scheduler records that the customer never answered: keep both, no money moves."""
    s = agent.get_case(case_id)
    if not s or s.get("status") != "waiting_customer":
        raise HTTPException(409, "case is not waiting for the customer")
    llm, reply_llm = llms()
    agent.customer_decide(case_id, "no_response", s["customer_ask"]["hash"], by_ops=True, llm=llm, reply_llm=reply_llm)
    return case_view(case_id)


@app.get("/stats")
def stats():
    """Demo-session counters for the app's top bar."""
    c = {"cases": 0, "auto_resolved": 0, "approved": 0, "rejected": 0, "escalated": 0, "waiting": 0, "open": 0}
    for cid in _cases_with("node", "start"):
        c["cases"] += 1
        s = agent.get_case(cid)
        st, appr = s.get("status"), (s.get("approval") or {}).get("decision")
        if appr == "approve":
            c["approved"] += 1
        elif appr == "reject":
            c["rejected"] += 1
        elif st == "resolved":
            c["auto_resolved"] += 1
        elif st == "escalated":
            c["escalated"] += 1
        elif st in ("waiting_approval", "waiting_customer"):
            c["waiting"] += 1
        else:
            c["open"] += 1
    return c
