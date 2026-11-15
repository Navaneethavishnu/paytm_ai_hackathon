"""Merchant replies: facts, safe templates and the reply validator.

Rule: the merchant is only ever told facts that came from tool results.
  1. `build_facts` picks the facts for this outcome from case state (code, not LLM).
  2. The LLM may phrase them in the merchant's language.
  3. `validate_reply` rejects the LLM text if it contains ANY number or ID that is
     not in the facts. Then a fixed template is sent instead.
"""
import re
from datetime import datetime

# ---------- formatting ----------

def inr(amount: float | str) -> str:
    """Indian grouping: 2400 -> 2,400 ; 100000 -> 1,00,000 ; 1499.5 -> 1,499.50"""
    a = float(amount)
    whole, frac = divmod(round(a * 100), 100)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        s = head + "," + tail
    return s + (f".{int(frac):02d}" if frac else "")


def nice_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y").lstrip("0")


# ---------- facts ----------

def outcome_of(state: dict) -> str:
    if state.get("status") == "needs_info":
        return "pick_order" if state.get("order_choices") else "need_order"
    if state.get("status") == "escalated":
        return "escalated"
    code = (state.get("diagnosis") or {}).get("code")
    if state.get("status") == "waiting_approval":
        return "refund_waiting" if code == "DUPLICATE_CHARGE" else "approval_waiting"
    if (state.get("approval") or {}).get("decision") == "reject":
        return "refund_rejected" if code == "DUPLICATE_CHARGE" else "escalated"
    if code == "PAYOUT_FAILED_TRANSIENT":
        return "payout_retried"
    if code == "DUPLICATE_CHARGE":
        return "refunded"
    return {"SETTLED": "settled", "PAYOUT_PENDING_IN_WINDOW": "pending",
            "TXN_FAILED": "txn_failed", "NOT_FOUND": "not_found"}.get(code, "escalated")


def build_facts(state: dict) -> dict:
    out = outcome_of(state)
    d = (state.get("diagnosis") or {}).get("data") or {}
    v = state.get("verification") or {}
    bank = (state.get("merchant") or {}).get("bank_account", "")
    f: dict = {"outcome": out}
    if out in ("need_order", "pick_order"):
        return f
    if out == "escalated":
        f["ticket_id"] = state.get("ticket_id") or ""
        return f
    f["order_id"] = state.get("order_id")
    if out == "approval_waiting":
        return f
    if out == "refund_rejected":
        f.update(duplicate_order_id=d["refund_order"], ticket_id=state.get("ticket_id") or "")
        return f
    if out == "payout_retried":
        f.update(amount=inr(v["amount"]), utr=v["utr"], bank_account=bank)
    elif out == "settled":
        f.update(amount=inr(d["payout_amount"]), utr=d["utr"], bank_account=bank)
    elif out == "pending":
        f.update(amount=inr(d["payout_amount"]), expected_date=nice_date(d["expected_date"]))
    elif out in ("refunded", "refund_waiting"):
        f.update(duplicate_order_id=d["refund_order"], amount=inr(d["amount"]))
        if out == "refunded":
            f["refund_id"] = v.get("refund_id", "")
    return f


# ---------- templates (always safe: only fact placeholders) ----------

TEMPLATES = {
    "need_order": {
        "en-IN": "Please share the order ID (for example ORD-1234) so I can check it.",
        "ta-IN": "சரிபார்க்க உங்கள் ஆர்டர் எண்ணைப் பகிரவும் (உதா: ORD-1234).",
    },
    # No numbers in the text: the order list itself is shown as buttons, built from the tool result.
    "pick_order": {
        "en-IN": "I found your recent payments below. Tap the order you mean, or type the order ID.",
        "ta-IN": "உங்கள் சமீபத்திய பணப்பரிவர்த்தனைகளைக் கீழே காட்டியுள்ளேன். சரியான ஆர்டரைத் தொடவும், அல்லது ஆர்டர் எண்ணை எழுதவும்.",
    },
    "payout_retried": {
        "en-IN": "Your ₹{amount} for order {order_id} had failed at the bank. I retried it and it has now reached your account {bank_account}. UTR: {utr}.",
        "ta-IN": "ஆர்டர் {order_id} க்கான ₹{amount} வங்கியில் தோல்வியடைந்திருந்தது. மீண்டும் அனுப்பப்பட்டு, இப்போது உங்கள் கணக்கு {bank_account} க்கு வந்துவிட்டது. UTR: {utr}.",
    },
    "settled": {
        "en-IN": "₹{amount} for order {order_id} has already been sent to your account {bank_account}. UTR: {utr}.",
        "ta-IN": "ஆர்டர் {order_id} க்கான ₹{amount} ஏற்கனவே உங்கள் கணக்கு {bank_account} க்கு அனுப்பப்பட்டுவிட்டது. UTR: {utr}.",
    },
    "pending": {
        "en-IN": "₹{amount} for order {order_id} is scheduled and will reach your bank on {expected_date}. Nothing is wrong.",
        "ta-IN": "ஆர்டர் {order_id} க்கான ₹{amount} {expected_date} அன்று உங்கள் வங்கிக் கணக்கில் வரவு வைக்கப்படும். எந்தச் சிக்கலும் இல்லை.",
    },
    "txn_failed": {
        "en-IN": "The customer's payment for order {order_id} failed, so no money was collected and there is nothing to settle.",
        "ta-IN": "ஆர்டர் {order_id} க்கான வாடிக்கையாளர் பணம் செலுத்துதல் தோல்வியடைந்தது. எனவே தீர்வு செய்ய தொகை எதுவும் இல்லை.",
    },
    "not_found": {
        "en-IN": "I couldn't find order {order_id} on your account. Please check the order ID and send it again.",
        "ta-IN": "உங்கள் கணக்கில் ஆர்டர் {order_id} கிடைக்கவில்லை. ஆர்டர் எண்ணைச் சரிபார்த்து மீண்டும் அனுப்பவும்.",
    },
    "refunded": {
        "en-IN": "Order {duplicate_order_id} was a duplicate charge. ₹{amount} has been refunded to the customer. Refund ID: {refund_id}.",
        "ta-IN": "ஆர்டர் {duplicate_order_id} ஒரு இரட்டைக் கட்டணம். ₹{amount} வாடிக்கையாளருக்குத் திருப்பி அளிக்கப்பட்டது. ரீஃபண்ட் ஐடி: {refund_id}.",
    },
    "refund_waiting": {
        "en-IN": "Order {duplicate_order_id} looks like a duplicate charge. A refund of ₹{amount} is waiting for approval from our operations team.",
        "ta-IN": "ஆர்டர் {duplicate_order_id} இரட்டைக் கட்டணமாகத் தெரிகிறது. ₹{amount} ரீஃபண்ட் எங்கள் செயல்பாட்டுக் குழுவின் ஒப்புதலுக்காகக் காத்திருக்கிறது.",
    },
    "approval_waiting": {
        "en-IN": "I've found the issue with order {order_id}. The fix needs a quick approval from our operations team, and I'll update you once it's done.",
        "ta-IN": "ஆர்டர் {order_id} இல் உள்ள சிக்கலைக் கண்டறிந்துள்ளேன். தீர்வுக்கு எங்கள் செயல்பாட்டுக் குழுவின் ஒப்புதல் தேவை. முடிந்ததும் உங்களுக்குத் தெரிவிப்பேன்.",
    },
    "refund_rejected": {
        "en-IN": "Our operations team reviewed the possible duplicate charge on order {duplicate_order_id} and did not approve an automatic refund. A specialist will follow up with you (ticket {ticket_id}).",
        "ta-IN": "ஆர்டர் {duplicate_order_id} இல் உள்ள இரட்டைக் கட்டணத்தை எங்கள் குழு சரிபார்த்தது, தானியங்கி ரீஃபண்டுக்கு ஒப்புதல் அளிக்கவில்லை. ஒரு நிபுணர் உங்களைத் தொடர்புகொள்வார் (டிக்கெட் {ticket_id}).",
    },
    "escalated": {
        "en-IN": "I've passed your request to a specialist (ticket {ticket_id}). They will follow up with you.",
        "ta-IN": "உங்கள் கோரிக்கை ஒரு நிபுணரிடம் அனுப்பப்பட்டுள்ளது (டிக்கெட் {ticket_id}). அவர்கள் உங்களைத் தொடர்புகொள்வார்கள்.",
    },
}


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def skeleton(outcome: str, language: str = "en-IN") -> str:
    """The template with {placeholders} still in it. The LLM rephrases THIS, so it never
    sees real amounts/IDs, and the same rephrasing can be cached across cases."""
    t = TEMPLATES[outcome]
    return t.get(language, t["en-IN"])


def fill_skeleton(text: str, facts: dict, outcome: str) -> tuple[str | None, str]:
    """Put facts into an LLM-rephrased skeleton. Every placeholder must survive exactly once."""
    want = set(_PLACEHOLDER.findall(TEMPLATES[outcome]["en-IN"]))
    got = _PLACEHOLDER.findall(text)
    if set(got) != want or len(got) != len(want):
        return None, f"placeholders changed: wanted {sorted(want)}, got {sorted(got)}"
    if re.search(r"\d", _PLACEHOLDER.sub("", text)):
        return None, "rephrasing added digits"
    return _PLACEHOLDER.sub(lambda m: str(facts[m.group(1)]), text), "ok"


def template_reply(facts: dict, language: str) -> str:
    t = TEMPLATES[facts["outcome"]]
    text = t.get(language, t["en-IN"]).format(**{k: v for k, v in facts.items() if k != "outcome"})
    return text.replace(" (ticket )", "").replace(" (டிக்கெட் )", "")   # ticket system was down


# ---------- validator ----------

_NUM = re.compile(r"\d+(?:\.\d+)?")
_ID = re.compile(r"\b(?:ORD-\d+|PO-\d+|TXN\d+|UTR[A-Z0-9]+|RF[A-Z0-9]+|TCK[A-Z0-9]+|M\d{4}|XXXX\d{4})\b")


def _numbers(text: str) -> set[str]:
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    out = set()
    for n in _NUM.findall(text):
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


# Indic script blocks. A reply may only use the merchant's script (plus Latin for IDs).
_SCRIPTS = {"ta-IN": (0x0B80, 0x0BFF), "hi-IN": (0x0900, 0x097F)}
_INDIC = (0x0900, 0x0DFF)        # Devanagari .. Sinhala, covers Malayalam/Telugu/Kannada etc.


def _script_ok(reply: str, language: str) -> tuple[bool, str]:
    own = _SCRIPTS.get(language)
    indic = [c for c in reply if _INDIC[0] <= ord(c) <= _INDIC[1]]
    foreign = [c for c in indic if not (own and own[0] <= ord(c) <= own[1])]
    if foreign:
        return False, f"wrong script for {language}"
    if own and not indic:
        return False, f"no {language} script in reply"
    return True, "ok"


def validate_reply(reply: str, facts: dict, language: str = "en-IN") -> tuple[bool, str]:
    """True only if the reply is in the right language/script and every number and ID appears in the facts."""
    if not reply or not reply.strip():
        return False, "empty"
    if len(reply) > 700:
        return False, "too long"
    ok, why = _script_ok(reply, language)
    if not ok:
        return False, why
    fact_text = " ".join(str(v) for v in facts.values())
    extra_nums = _numbers(reply) - _numbers(fact_text)
    if extra_nums:
        return False, f"numbers not in evidence: {sorted(extra_nums)}"
    extra_ids = set(_ID.findall(reply)) - set(_ID.findall(fact_text))
    if extra_ids:
        return False, f"IDs not in evidence: {sorted(extra_ids)}"
    return True, "ok"


# ---------- Case 4: proactive duplicate payment (customer decides) ----------
# Fixed templates, no LLM: these messages are about moving a customer's money.

NOTICES = {
    "asked": {
        "customer": "You paid ₹{amount} twice to {merchant} for bill {invoice} (at {keep_time} and {refund_time}). "
                    "Was the second payment a mistake? Choose Keep both or Refund one.",
        "merchant": "Heads-up: a customer paid ₹{amount} twice for bill {invoice} ({keep_order} and {refund_order}). "
                    "We've asked the customer whether to refund one. No action needed from you.",
    },
    "kept": {
        "customer": "Got it. Both payments of ₹{amount} to {merchant} are kept.",
        "merchant": "The customer confirmed both payments for bill {invoice} are intended. No refund.",
    },
    "kept_no_reply": {
        "customer": "We didn't hear back, so both payments of ₹{amount} to {merchant} are kept. You can still raise a request in the app.",
        "merchant": "The customer did not reply about bill {invoice}. Both payments are kept and no refund was made.",
    },
    "refund_review": {
        "customer": "Thanks. Your refund of ₹{amount} for the duplicate payment is being reviewed by our team.",
        "merchant": "The customer asked to refund duplicate payment {refund_order} (₹{amount}). It is waiting for our operations team's approval.",
    },
    "refunded": {
        "customer": "Done. ₹{amount} for the duplicate payment to {merchant} has been refunded. Refund ID: {refund_id}.",
        "merchant": "At the customer's request, duplicate payment {refund_order} (₹{amount}, bill {invoice}) was refunded. Refund ID: {refund_id}.",
    },
    "refund_rejected": {
        "customer": "Our team reviewed the duplicate payment of ₹{amount} and could not refund it automatically. A specialist will contact you.",
        "merchant": "Our operations team did not approve the refund for duplicate payment {refund_order}. A specialist will follow up.",
    },
    "escalated": {
        "customer": "We're checking your payment to {merchant}. A specialist will contact you.",
    },
}


def _hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")


def duplicate_facts(state: dict) -> dict:
    d = (state.get("diagnosis") or {}).get("data") or {}
    v = state.get("verification") or {}
    return {
        "amount": inr(d.get("amount", 0)), "merchant": (state.get("merchant") or {}).get("name") or "the merchant",
        "invoice": d.get("invoice") or "the same bill", "keep_order": d.get("keep_order", ""),
        "refund_order": d.get("refund_order", ""),
        "keep_time": _hhmm(d["keep_time"]) if d.get("keep_time") else "",
        "refund_time": _hhmm(d["refund_time"]) if d.get("refund_time") else "",
        "refund_id": v.get("refund_id", ""),
    }


def notice(outcome: str, to: str, facts: dict) -> str | None:
    t = NOTICES[outcome].get(to)
    return t.format(**facts) if t else None
