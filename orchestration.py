import os
import time
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv
load_dotenv()

# ---- Core tools ----
from tools.detect_intent_tool import detect_intent_cached
from tools.slot_extractor import extract_slots_from_text
from tools.validate_datetime_tool import validate_datetime
from tools.save_Booking import init_db, save_booking, get_booking_by_id, cancel_booking
from tools.generate_qr_code import generate_upi_qr
from tools.send_price_catalog import send_price_catalog
from tools.send_location import send_location
from tools.send_whatsapp_text import send_whatsapp_text
from tools.send_owner_msg import notify_owner
from tools.missingInfoTool import request_missing_info
from tools.speech_to_text import transcribe_webm

# ---- Gemini (rewrite only) ----
from google.generativeai import GenerativeModel

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-1.5-flash")
gemini = GenerativeModel(GEMINI_MODEL)
GEMINI_TIMEOUT = 4  # seconds for rewrite only


# ====  DB Init ====
init_db()


# ============================================================
#   LIGHT GEMINI REWRITE (only for reply_text, 1 call per msg)
# ============================================================

def smart_rewrite(core: str, user_text: str) -> str:
    """
    Only rewrite to improve tone, no hallucinations, max 1 call, timed out at 4s.
    If timeout/error → return core unmodified.
    """
    try:
        # style prompt: no emojis, no long paragraphs
        prompt = (
            "Rewrite the reply to sound natural, concise, and helpful. "
            "Do not add emojis. Do not add external facts. "
            "Keep it under 2 sentences. "
            f"User said: {user_text}\n"
            f"Draft reply: {core}\n"
            "Return improved reply only, nothing else."
        )

        # TIME LIMIT
        start = time.time()
        out = gemini.generate_content([prompt])
        if time.time() - start > GEMINI_TIMEOUT:
            return core

        text = (out.text or "").strip()
        # safety filter: if gemini goes off rails:
        if len(text) < 3 or "http" in text or "://" in text:
            return core
        return text

    except Exception:
        return core


# ============================================================
#   SLOTS + FLOW
# ============================================================

REQ_ORDER = [
    ("name", "full name"),
    ("country_code", "country calling code (like +91 or +1)"),
    ("phone", "phone number with that code"),
    ("date", "date"),
    ("time", "time"),
    ("genre", "agent category (gym / salon / restaurant / other)")
]

def missing_slots(slots: Dict[str, Any]) -> List[str]:
    return [k for k, _ in REQ_ORDER if not slots.get(k)]


def split_phone(raw: str) -> Dict[str, str]:
    out = {"country_code": "", "phone": ""}
    if not raw:
        return out
    m = re.search(r"(\+\d{1,3})\D*(\d{6,15})", raw)
    if m:
        out["country_code"] = m.group(1)
        out["phone"] = re.sub(r"\D", "", m.group(2))
        return out
    # fallback digits
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        out["phone"] = digits
    return out


def extract_all_slots(user_text: str, slots: Dict[str, Any]) -> None:
    """
    Robust slot extraction:
    1) rule extract
    2) missingInfoTool
    3) name fallback
    4) phone fallback
    """
    # 1) rule-based
    rule = extract_slots_from_text(user_text) or {}
    for k, v in rule.items():
        if v and not slots.get(k):
            slots[k] = v

    # 2) missing-info-tool
    extra = request_missing_info(user_text, slots) or {}
    for k, v in (extra.get("slots_found") or {}).items():
        if v and not slots.get(k):
            slots[k] = v

    # 3) name fallback: two words
    parts = user_text.strip().split()
    if len(parts) >= 2 and not slots.get("name"):
        if all(p[0].isalpha() for p in parts[:2]):
            slots["name"] = " ".join(parts[:2])

    # 4) phone fallback
    parsed = split_phone(user_text)
    if parsed.get("phone") and not slots.get("phone"):
        slots["phone"] = parsed["phone"]
    if parsed.get("country_code") and not slots.get("country_code"):
        slots["country_code"] = parsed["country_code"]


# ============================================================
#   MAIN FUNCTION
# ============================================================

SESSIONS: Dict[str, Dict[str, Any]] = {}

def run_agent(
    msgs: List[Dict[str, Any]],
    sid: str,
    frontend_phone: Optional[str] = None,
    audio_path: Optional[str] = None,
) -> Dict[str, Any]:

    # ====== start session ======
    sess = SESSIONS.get(sid) or {
        "stage": "idle",
        "slots": {},
        "hist": []
    }
    SESSIONS[sid] = sess

    # ====== transcription ======
    if audio_path:
        user_text = transcribe_webm(audio_path) or "[voice]"
    else:
        user_text = ""
        for m in msgs[::-1]:
            if m.get("role") == "user":
                user_text = m["parts"][0]["text"].strip()
                break

    # ====== phone preload from URL ======
    if frontend_phone and not sess["slots"].get("phone"):
        p = split_phone(frontend_phone)
        if p.get("phone"):
            sess["slots"]["phone"] = p["phone"]
        if p.get("country_code"):
            sess["slots"]["country_code"] = p["country_code"]

    # ====== idle ======
    low = user_text.lower()
    if sess["stage"] == "idle":

        if any(w in low for w in ["book", "ai agent", "call"]):
            sess["stage"] = "collect"

            core = (
                "Great — let's get your booking started. "
                "I'll need your full name, country calling code (like +91 or +1), phone number, "
                "date, time, and agent category (gym / salon / restaurant / other). "
                "You can send these in any order."
            )
            reply = smart_rewrite(core, user_text)

            return {
                "reply_text": reply,
                "structured": {}
            }

        # idle fallback
        core = (
            "I can help you book an AI agent or schedule a call. "
            "Just say 'book an AI agent' or 'book a call' to start."
        )
        reply = smart_rewrite(core, user_text)
        return {"reply_text": reply, "structured": {}}

    # ====== collect ======
    extract_all_slots(user_text, sess["slots"])
    miss = missing_slots(sess["slots"])

    if miss:
        core = (
            f"I saved your details — I still need: "
            + ", ".join(miss)
            + ". Send whichever is easiest next."
        )
        reply = smart_rewrite(core, user_text)
        return {"reply_text": reply, "structured": {}}

    # ====== all slots present → confirm proposal ======
    p = sess["slots"]
    summary = (
        f"Booking summary:\n"
        f"- Name: {p['name']}\n"
        f"- Phone: {p['country_code']}{p['phone']}\n"
        f"- Date & Time: {p['date']} at {p['time']}\n"
        f"- Category: {p['genre']}\n"
        f"Reply 'confirm' to finalize or 'change' if needed."
    )

    # move to confirm stage
    sess["stage"] = "confirm"
    reply = smart_rewrite(summary, user_text)

    return {"reply_text": reply, "structured": {}}


