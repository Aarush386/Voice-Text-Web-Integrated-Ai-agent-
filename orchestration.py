# orchestration.py — final patched version
import os
import time
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

# ---- Tool imports ----
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

import speech_recognition as sr
from pydub import AudioSegment

# ---- Optional Gemini LLM (for interpret + rewrite only) ----
try:
    from google import generativeai as gen
    MODEL_NAME = os.getenv("GEN_MODEL", "gemini-2.5-flash-lite")
    gen.configure(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("googleApiKEY"))
    LLM_AVAILABLE = True
except Exception:
    gen = None
    MODEL_NAME = None
    LLM_AVAILABLE = False

# ---- Init DB ----
init_db()

# ---- LLM Budget ----
LLM_PER_MIN = int(os.getenv("LLM_PER_MINUTE", "15"))
LLM_CALLS: List[float] = []


def can_call_llm() -> bool:
    now = time.time()
    window = [t for t in LLM_CALLS if now - t < 60]
    if len(window) >= LLM_PER_MIN:
        return False
    window.append(now)
    LLM_CALLS[:] = window
    return True


def llm_interpret(text: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM #1: interpret intent + slots + style.
    Returns: {intent, confidence, slots, style_hints{formality, uses_slang}}
    Falls back to detect_intent_cached if LLM not available / budget hit.
    """
    if not LLM_AVAILABLE or not can_call_llm():
        return detect_intent_cached(text, allow_llm=False)

    system = (
        "You are an intent and style extractor for an AI agent that books calls or AI agents. "
        "Return ONLY JSON with keys:\n"
        "intent: string,\n"
        "confidence: number 0-1,\n"
        "slots: object,\n"
        "style_hints: {formality: 'formal'|'informal', uses_slang: true|false}.\n"
        "Allowed intents: book_agent, book_call, cancel, get_catalog, get_location, pay, confirm, small_talk, unknown.\n"
        "No explanations, no extra text, no emojis."
    )

    user_prompt = f"User message: '''{text}'''\nSession snapshot: {json.dumps(snapshot)}\nReturn ONLY the JSON."

    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content(
            [{"role": "user", "parts": [{"text": user_prompt}]}],
            generation_config={"temperature": 0.0, "max_output_tokens": 256},
        )
        cand = resp.candidates[0]
        raw = cand.content.parts[0].text if getattr(cand, "content", None) else getattr(cand, "text", "")
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            js = raw[start : end + 1]
            parsed = json.loads(js)
            parsed.setdefault("slots", {})
            parsed.setdefault("style_hints", {})
            return parsed
    except Exception:
        pass

    return detect_intent_cached(text, allow_llm=False)


def llm_rewrite(core_text: str, user_text: str, style_hints: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    """
    LLM #2: rewrite core_text into human tone matching user (Option M).
    - DOES NOT change facts, amounts, booking IDs.
    - NO emojis.
    """
    if not LLM_AVAILABLE or not can_call_llm():
        return core_text

    formality = style_hints.get("formality", "formal")
    allow_slang = bool(style_hints.get("uses_slang", False))

    system = (
        "You are a rewrite assistant. Rephrase the given 'core_text' into a human-like response "
        "matching the user's tone.\n"
        "- Do NOT change factual content, numbers or booking IDs.\n"
        "- Do NOT add emojis.\n"
        "- If user is formal, keep it formal and confident.\n"
        "- If informal, you may be casual but keep it clean and professional.\n"
        "Return only the final text."
    )

    prompt = (
        f"CORE_TEXT: '''{core_text}'''\n"
        f"USER_TEXT: '''{user_text}'''\n"
        f"STYLE_HINTS: formality={formality}, allow_slang={allow_slang}"
    )

    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content(
            [{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"temperature": 0.25, "max_output_tokens": 200},
        )
        cand = resp.candidates[0]
        out = cand.content.parts[0].text if getattr(cand, "content", None) else getattr(cand, "text", "")
        # Strip emoji range + non-printables
        filtered = "".join(ch for ch in out if ord(ch) < 0x1F600 or ord(ch) > 0x1F64F)
        filtered = "".join(c for c in filtered if c.isprintable())
        return filtered.strip() or core_text
    except Exception:
        return core_text


# ---- Session handling ----
SESSIONS: Dict[str, Dict[str, Any]] = {}


def start_session(sid: str, frontend_phone: Optional[str] = None) -> Dict[str, Any]:
    s = SESSIONS.get(sid)
    if not s:
        s = {
            "stage": "idle",
            "slots": {},
            "proposed": None,
            "last_booking": None,
            "hist": [],
        }
        SESSIONS[sid] = s

    # Pre-filled phone from frontend (Twilio URL) if available
    if frontend_phone and not s["slots"].get("phone"):
        s["slots"]["phone"] = frontend_phone

    return s


# ---- Small talk (with mid-flow continuation) ----
def small_talk_response(text: str) -> Optional[str]:
    t = (text or "").lower()
    if any(x in t for x in ("hi", "hello", "hey")):
        return "Hello — how can I assist you today?"
    if any(x in t for x in ("how are you", "how r you")):
        return "I'm doing well and ready to help with your bookings or AI agent."
    if any(x in t for x in ("who are you", "what is this")):
        return f"I'm the AI assistant for {os.getenv('BUSINESS_NAME','Aarush AI Solutions')}. I can help you book a call or an AI agent and answer questions about our services."
    if any(x in t for x in ("wait", "hold on", "one sec", "hmm", "bro")):
        return "Sure — take your time."
    return None


# ---- Pricing helpers ----
FX_USD_TO_INR = float(os.getenv("FX_USD_TO_INR", "80"))
CURRENCY = os.getenv("CURRENCY_INR", "₹")

PRICES_USD = {
    "gym": float(os.getenv("GENRE_GYM_PRICE", "200")),
    "salon": float(os.getenv("GENRE_SALON_PRICE", "180")),
    "restaurant": float(os.getenv("GENRE_RESTAURANT_PRICE", "250")),
    "other": float(os.getenv("GENRE_OTHER_PRICE", "180")),
}
ADDON_USD = {
    "web_integration": float(os.getenv("ADDON_WEB_INTEGRATION_PRICE", "100")),
    "payment_integration": float(os.getenv("ADDON_UPI_INTEGRATION_PRICE", "100")),
    "whatsapp_integration": float(os.getenv("ADDON_WHATSAPP_INTEGRATION_PRICE", "50")),
}


def price_calc(genre: str, addons: List[str]) -> int:
    base = PRICES_USD.get(genre, PRICES_USD["other"])
    addons_sum = sum(ADDON_USD.get(a, 0.0) for a in (addons or []))
    total_inr = (base + addons_sum) * FX_USD_TO_INR
    # Round to nearest 500
    return int(round(total_inr / 500.0)) * 500


# Required slot order
REQ_ORDER = [
    ("mode", "Would you like to book a call or book an AI agent?"),
    ("name", "Please provide your full name."),
    ("country_code", "Please provide your country code like +91 or +1."),
    ("phone", "Please provide your phone number."),
    ("date", "Which date would you like?"),
    ("time", "Which time would you like?"),
    ("genre", "Which agent type? (gym/salon/restaurant/other)"),
]


def next_missing(slots: Dict[str, Any]) -> Optional[str]:
    for k, _ in REQ_ORDER:
        if not slots.get(k):
            return k
    return None


def q_for_slot(k: str) -> str:
    for kk, q in REQ_ORDER:
        if kk == k:
            return q
    return f"Please provide {k}."


# ---- Voice transcription ----
def transcribe_audio(webm_path: str) -> str:
    wav_path = webm_path.replace(".webm", ".wav")
    try:
        AudioSegment.from_file(webm_path).export(wav_path, format="wav")
    except Exception:
        return ""
    try:
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as src:
            audio = r.record(src)
        text = r.recognize_google(audio)
    except Exception:
        text = ""
    try:
        os.remove(wav_path)
    except Exception:
        pass
    return text.strip()


def get_user_text(msgs: List[Dict[str, Any]]) -> str:
    if not msgs:
        return ""
    for m in reversed(msgs):
        if m.get("role") == "user" and m.get("parts"):
            return (m["parts"][0].get("text") or "").strip()
    return ""


# ---- MAIN: run_agent ----
def run_agent(
    msgs: List[Dict[str, Any]],
    sid: str,
    frontend_phone: Optional[str] = None,
    audio_path: Optional[str] = None,
) -> Dict[str, Any]:
    sess = start_session(sid, frontend_phone)
    transcript = None

    # Voice vs text
    if audio_path:
        transcript = transcribe_audio(audio_path)
        user_text = transcript if transcript else "[voice]"
    else:
        user_text = get_user_text(msgs)

    if not user_text:
        return {
            "reply_text": "I didn't catch that — please repeat.",
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {},
        }

    # Log history
    sess["hist"].append(
        {"role": "user", "text": user_text, "ts": datetime.utcnow().isoformat()}
    )

    snapshot = {
        "stage": sess["stage"],
        "slots": sess["slots"],
        "last_booking": sess.get("last_booking"),
    }

    # Interpret with LLM, but conservative
    interpretation = llm_interpret(user_text, snapshot)
    intent = interpretation.get("intent", "unknown")
    style_hints = interpretation.get("style_hints", {}) or {}

    # Merge slots: rule-based + LLM + missingInfoTool
    try:
        rule_slots = extract_slots_from_text(user_text) or {}
        for k, v in rule_slots.items():
            if v and not sess["slots"].get(k):
                sess["slots"][k] = v
    except Exception:
        pass

    for k, v in (interpretation.get("slots") or {}).items():
        if v and not sess["slots"].get(k):
            sess["slots"][k] = v

    try:
        extra = request_missing_info(user_text, sess["slots"])
        for k, v in (extra.get("slots_found") or {}).items():
            if v and not sess["slots"].get(k):
                sess["slots"][k] = v
    except Exception:
        pass

    # Small-talk with mid-flow continuation
    small = small_talk_response(user_text)
    if small:
        if sess["stage"] != "idle":
            miss = next_missing(sess["slots"])
            if miss:
                follow = q_for_slot(miss)
                reply = f"{small} — now, about your booking, {follow}"
            else:
                reply = small
        else:
            reply = small

        # No need to spend rewrite budget here, keep deterministic
        return {
            "reply_text": reply,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {},
        }

    low = user_text.lower()

    # ---- GLOBAL QUICK ACTIONS (catalog/location/cancel/pay keyword) ----
    # We still allow these anywhere in the flow.

    # Price catalog (UI only, no WhatsApp media)
    if any(x in low for x in ("catalog", "pricing", "price", "show price", "price list", "menu")) and intent in (
        "get_catalog",
        "unknown",
    ):
        try:
            res = send_price_catalog(session=sid, phone=None)
        except Exception:
            res = {"ok": False}
        if not res.get("ok"):
            msg = "Couldn't prepare the catalog right now. Please try again a bit later."
        else:
            url = res.get("public_url")
            msg = f"Here's the pricing catalog for our AI agents: {url}"
        core = msg
        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {"catalog_url": url},
        }

    # Location (UI only, URL/text)
    if any(x in low for x in ("location", "office", "address", "where are you")) and intent in (
        "get_location",
        "unknown",
    ):
        try:
            res = send_location(session=sid, phone=None)
        except Exception:
            res = {"ok": False}
        if not res.get("ok"):
            core = "I couldn't fetch the office location right now. Please try again later."
        else:
            url = res.get("public_url")
            text = res.get("text", "")
            core = f"{text}. You can open it here: {url}"
        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {"location_url": url},
        }

    # ---- Stage: IDLE ----
    if sess["stage"] == "idle":
        # Bookings
        if any(w in low for w in ("book an ai agent", "book a ai agent", "ai agent", "agent")) or intent == "book_agent":
            sess["stage"] = "collect"
            sess["slots"]["mode"] = "agent"
            core = (
                "Great — let's book your AI agent. I'll need a few details to get started. "
                "First, what's your full name?"
            )
            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        if any(w in low for w in ("book a call", "book call", "call with you", "call")) or intent == "book_call":
            sess["stage"] = "collect"
            sess["slots"]["mode"] = "call"
            core = (
                "Sure — let's book a call to discuss your custom AI agent. "
                "To start, could you share your full name?"
            )
            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        # Cancel booking from idle
        if "cancel" in low and sess.get("last_booking"):
            bid = sess["last_booking"]
            try:
                cancel_booking(bid)
                core = f"Booking ID {bid} has been cancelled."
            except Exception:
                core = "I couldn't cancel that booking right now. Please try again later."
            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        # Generic idle answer
        core = (
            "I can help you book a call, book an AI agent, share our pricing, or send the office location. "
            "What would you like to do?"
        )
        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {},
        }

    # ---- Stage: COLLECT (gathering booking details) ----
    if sess["stage"] == "collect":
        # If mode somehow not set, infer from text
        if not sess["slots"].get("mode"):
            if any(w in low for w in ("agent", "ai agent", "book agent")) or intent == "book_agent":
                sess["slots"]["mode"] = "agent"
            elif any(w in low for w in ("call", "phone call", "book a call")) or intent == "book_call":
                sess["slots"]["mode"] = "call"

        # Confirm auto-detected phone once
        if sess["slots"].get("phone") and not sess["slots"].get("confirmed_phone") and not sess["slots"].get(
            "asked_confirm"
        ):
            cc = sess["slots"].get("country_code", "")
            disp = f"{cc}{sess['slots']['phone']}" if cc else sess["slots"]["phone"]
            core = (
                f"I see your number as {disp}. Do you want to use this for WhatsApp confirmations? "
                "Reply 'yes' to confirm, or send a different number like '+1 5551234567'."
            )
            sess["slots"]["asked_confirm"] = True
            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        # Handle reply to that confirm
        if sess["slots"].get("asked_confirm") and not sess["slots"].get("confirmed_phone"):
            l = low.strip()
            if l in ("yes", "y", "yeah", "yup", "confirm"):
                sess["slots"]["confirmed_phone"] = True
                sess["slots"].pop("asked_confirm", None)
                core = "Great — what's your full name?"
                out = llm_rewrite(core, user_text, style_hints, snapshot)
                return {
                    "reply_text": out,
                    "transcript": transcript,
                    "reply_audio_url": None,
                    "structured": {},
                }

            # Parse a replacement +country_code and phone
            mcc = re.search(r"(\+\d{1,3})", user_text)
            mph = re.search(r"(\d{6,15})", re.sub(r"\D", "", user_text))
            if mcc and mph:
                sess["slots"]["country_code"] = mcc.group(1)
                sess["slots"]["phone"] = mph.group(1)
                sess["slots"]["confirmed_phone"] = True
                sess["slots"].pop("asked_confirm", None)
                core = "Thanks — updated your number. What's your full name?"
                out = llm_rewrite(core, user_text, style_hints, snapshot)
                return {
                    "reply_text": out,
                    "transcript": transcript,
                    "reply_audio_url": None,
                    "structured": {},
                }

            return {
                "reply_text": "Please reply 'yes' to use the detected number, or send a new one with country code like '+1 5551234567'.",
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        # Normal collect: ask next missing slot
        miss = next_missing(sess["slots"])
        if miss:
            q = q_for_slot(miss)
            out = llm_rewrite(q, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        # If we reach here, we have all slots → validate date/time
        dt = f"{sess['slots'].get('date','')} {sess['slots'].get('time','')}".strip()
        if dt:
            v = validate_datetime(dt)
            if not v.get("ok", False):
                sess["slots"].pop("date", None)
                sess["slots"].pop("time", None)
                core = v.get("summary", "The date and time don't look valid. Please share a clear date and time.")
                out = llm_rewrite(core, user_text, style_hints, snapshot)
                return {
                    "reply_text": out,
                    "transcript": transcript,
                    "reply_audio_url": None,
                    "structured": {},
                }

        # Build proposal and switch to confirm
        genre = sess["slots"].get("genre", "other")
        addons = sess["slots"].get("addons", [])
        amount_inr = price_calc(genre, addons)
        prop = {
            "name": sess["slots"].get("name"),
            "country_code": sess["slots"].get("country_code", ""),
            "phone": sess["slots"].get("phone", ""),
            "date": sess["slots"].get("date"),
            "time": sess["slots"].get("time"),
            "genre": genre,
            "addons": addons,
            "amount_inr": amount_inr,
        }
        sess["proposed"] = prop
        sess["stage"] = "confirm"

        core = (
            f"Here's your booking proposal: {prop['genre'].title()} AI agent "
            f"for {CURRENCY}{prop['amount_inr']} on {prop['date']} at {prop['time']}. "
            "Reply 'confirm' to book, or 'change' if you want to edit something."
        )
        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {"proposal": prop},
        }

    # ---- Stage: CONFIRM ----
    if sess["stage"] == "confirm":
        low = user_text.lower()

        if "change" in low:
            sess["stage"] = "collect"
            core = "No problem — what would you like to change in your booking details?"
            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        if any(x in low for x in ("confirm", "yes, book", "book now", "i confirm", "yes")):
            p = sess.get("proposed") or {}
            saved = save_booking(
                session=sid,
                phone=p.get("phone", ""),
                name=p.get("name", ""),
                booking_type="agent" if sess["slots"].get("mode") == "agent" else "call",
                agent_type=p.get("genre", ""),
                base_amount=0.0,
                addons=p.get("addons", []),
                custom_features=sess["slots"].get("custom_features", []),
                date=p.get("date"),
                time=p.get("time"),
                payment_status="pending",
                final_amount=p.get("amount_inr", 0),
            )

            if not saved.get("ok"):
                return {
                    "reply_text": "I couldn't save your booking just now. Please try again in a moment.",
                    "transcript": transcript,
                    "reply_audio_url": None,
                    "structured": {},
                }

            bid = saved.get("booking_id")
            sess["last_booking"] = bid
            sess["slots"]["booking_id"] = bid
            sess["stage"] = "booked"

            # Notify owner (WhatsApp text only)
            try:
                notify_owner(
                    f"New booking {bid}: {p.get('genre')} for {p.get('amount_inr')} on {p.get('date')} at {p.get('time')}."
                )
            except Exception:
                pass

            # Customer confirmation template on WhatsApp (text only)
            full_phone = (sess["slots"].get("country_code", "") or "") + (sess["slots"].get("phone", "") or "")
            if full_phone:
                try:
                    send_whatsapp_text(
                        to=full_phone,
                        body=(
                            f"Hello {p.get('name')}, your booking is confirmed.\n"
                            f"Booking ID: {bid}\n"
                            f"Date: {p.get('date')} at {p.get('time')}.\n"
                            f"Type: {p.get('genre')} AI agent."
                        ),
                    )
                except Exception:
                    pass

            core = f"Booking confirmed. Your Booking ID is {bid}. Total: {CURRENCY}{p.get('amount_inr')}."
            if sess["slots"].get("mode") == "agent":
                core += " If you'd like, you can pay online using UPI (QR) or keep it as offline payment."

            out = llm_rewrite(core, user_text, style_hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {"booking_id": bid},
            }

        # Not clear confirm/change
        return {
            "reply_text": "Please reply 'confirm' to finalize your booking or 'change' to edit the details.",
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {},
        }

    # ---- Post-booking actions (any stage) ----
    low = user_text.lower()

    # Payment / QR (UI only; WhatsApp gets text template)
    if any(x in low for x in ("generate qr", "pay now", "pay online", "qr code", "upi", "pay")):
        bid = sess.get("last_booking") or sess["slots"].get("booking_id")
        if not bid:
            return {
                "reply_text": "I couldn't find a booking to pay for. Please book first, then ask for payment.",
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        bk = get_booking_by_id(bid)
        if not bk.get("ok"):
            return {
                "reply_text": "I couldn't find that booking right now. Please try again later.",
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        amt = bk["booking"].get("final_amount", 0)
        full_phone = (sess["slots"].get("country_code", "") or "") + (sess["slots"].get("phone", "") or "")

        qr = generate_upi_qr(booking_id=bid, amount=amt, phone=full_phone)
        if not qr.get("ok"):
            return {
                "reply_text": "I couldn't prepare the QR code right now. Please try again in a bit.",
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }

        url = qr.get("public_url")
        # WhatsApp: text only, no media
        if full_phone:
            try:
                send_whatsapp_text(
                    to=full_phone,
                    body=f"Your payment QR for Booking ID {bid} is ready in the web app. Amount: {CURRENCY}{amt}.",
                )
            except Exception:
                pass

        core = f"Your payment QR is ready in the app for Booking ID {bid}. Amount: {CURRENCY}{amt}."
        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {"qr_url": url},
        }

    # Cancel / update booking (simple cancel)
    if "cancel" in low or "delete booking" in low:
        bid = sess.get("last_booking") or sess["slots"].get("booking_id")
        if not bid:
            return {
                "reply_text": "I couldn't find a booking to cancel. If you have a Booking ID, please share it.",
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {},
            }
        try:
            cancel_booking(bid)
            core = f"Booking ID {bid} has been cancelled."
        except Exception:
            core = "I couldn't cancel that booking right now. Please try again later."

        out = llm_rewrite(core, user_text, style_hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {},
        }

    # Fallback if nothing matched
    core = (
        "I can help you book a call, book an AI agent, see pricing, get our office location, "
        "or handle payment for an existing booking. What would you like to do next?"
    )
    out = llm_rewrite(core, user_text, style_hints, snapshot)
    return {
        "reply_text": out,
        "transcript": transcript,
        "reply_audio_url": None,
        "structured": {},
    }
