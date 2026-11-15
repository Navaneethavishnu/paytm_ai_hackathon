"""Voice input: Sarvam Saaras v4 speech-to-text, then the SAME agent path as chat.

API checked against docs.sarvam.ai + installed sarvamai 0.1.45:
  client.speech_to_text.transcribe(file=(name, bytes, content_type), model="saaras:v4",
                                   language_code="unknown" | "ta-IN" | ...)
  -> .transcript, .language_code, .language_probability   (REST is for clips under 30s)

Spoken order IDs come back as words, e.g. Tamil "ஓஆர்டி 1001" or English "order 1001",
so `normalize` rewrites them to ORD-1001 (and "2400 ரூபாய்" to ₹2400) before intake.
The transcript is treated exactly like typed merchant text: data, not instructions.
"""
import re
from typing import Callable

from app.config import get_settings

MAX_AUDIO_BYTES = 2_000_000          # ~30s of 16 kHz WAV is ~1 MB; m4a is far smaller
ALLOWED_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a",
    "audio/x-m4a", "audio/aac", "audio/ogg", "audio/opus", "audio/webm", "audio/flac", "audio/amr",
}
_EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
        "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/ogg": "ogg",
        "audio/opus": "opus", "audio/webm": "webm", "audio/flac": "flac", "audio/amr": "amr"}


class VoiceError(Exception):
    pass


# ---------------- normalization ----------------
_ORDER_WORDS = (
    r"o\s*\.?\s*r\s*\.?\s*d"                          # ORD, O R D, o.r.d
    r"|order(?:\s*(?:id|number|no\.?|#))?"            # order, order id, order number
    r"|ஓ\s*ஆர்\s*டி|ஓஆர்டி"                           # Tamil spelling of O-R-D
    r"|ஆர்டர்(?:\s*(?:எண்|நம்பர்|ஐடி))?"                # Tamil "order (number/id)"
)
_ORDER = re.compile(rf"(?:{_ORDER_WORDS})[\s:#-]*(\d{{3,10}})", re.I)
_RUPEES = re.compile(r"(?<![₹\d])(\d[\d,]*(?:\.\d+)?)\s*(?:ரூபாய்|ரூ\.?|rupees?|rs\.?)", re.I)


def normalize(text: str) -> str:
    text = _ORDER.sub(lambda m: f"ORD-{m.group(1)}", text)
    return _RUPEES.sub(lambda m: f"₹{m.group(1)}", text)


# ---------------- transcription ----------------
def _sarvam_transcribe(audio: bytes, content_type: str, language: str) -> dict:
    key = get_settings().sarvam_api_key
    if not key or key == "your_sarvam_key_here":
        raise VoiceError("Voice needs SARVAM_API_KEY")
    from sarvamai import SarvamAI
    r = SarvamAI(api_subscription_key=key).speech_to_text.transcribe(
        file=(f"clip.{_EXT.get(content_type, 'wav')}", audio, content_type),
        model="saaras:v4", language_code=language)
    return {"transcript": r.transcript or "", "language_code": r.language_code,
            "language_probability": getattr(r, "language_probability", None)}


_transcriber: Callable[[bytes, str, str], dict] = _sarvam_transcribe


def set_transcriber(fn: Callable[[bytes, str, str], dict] | None):
    """Tests inject a fake; None restores Sarvam."""
    global _transcriber
    _transcriber = fn or _sarvam_transcribe


def transcribe(audio: bytes, content_type: str, language: str = "unknown") -> dict:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in ALLOWED_TYPES:
        raise VoiceError(f"Unsupported audio type '{ct}'")
    if not audio:
        raise VoiceError("Empty audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise VoiceError("Audio too long; keep it under 30 seconds")
    try:
        r = _transcriber(audio, ct, language)
    except VoiceError:
        raise
    except Exception as e:
        raise VoiceError(f"Speech-to-text failed: {type(e).__name__}") from e
    raw = (r.get("transcript") or "").strip()
    if not raw:
        raise VoiceError("Couldn't hear anything in the clip. Please try again.")
    return {**r, "raw_transcript": raw, "transcript": normalize(raw)}
