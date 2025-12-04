import os
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv
load_dotenv()

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


from google.generativeai import GenerativeModel

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
gemini = GenerativeModel(GEMINI_MODEL)
GEMINI_TIMEOUT = 4  

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Aarush AI Solutions")
CURRENCY = os.getenv("CURRENCY", "₹")
AGENT_BASE_INR = int(os.getenv("AGENT_BASE_INR", "15000"))
CALL_BASE_INR = int(os.getenv("CALL_BASE_INR", "0"))

# DB init
init_db()



def smart_rewrite(core: str, user_text: str) -> str:
    """
    Only rewrite to improve tone, no hallucinations, max 1 call, timed out at 4s.
    If timeout/error → return core unmodified.
    """
    try:
        prompt = (
            "Rewrite the reply to sound natural, concise, and human-like, matching the user's tone. "
            "If the user is casual (e.g. says 'bro', 'dude', 'yaar'), you can be slightly casual, "
            "but stay professional and not cringey. "
            "Do not add emojis. Do not add external world facts. "
            "Keep it under 2 sentences. "
            f"User said: {user_text}\n"
            f"Draft reply: {core}\n"
            "Return improved reply only, nothing else."
        )

        start = time.time()
        out = gemini.generate_content([prompt])
        if time.time() - start > GEMINI_TIMEOUT:
            return core

        text = (out.text or "").strip()
        if len(text) < 3:
            return core
        return text
    except Exception:
        return core



REQ_ORDER = [
    ("name", "full name"),
    ("country_code", "country calling code (like +91 or +1)"),
    ("phone", "phone number with that code"),
    ("date", "date"),
    ("time", "time"),
    ("genre", "agent category (gym / salon / restaurant / other)"),
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
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        out["phone"] = digits
    return out

def extract_all_slots(user_text: str, slots: Dict[str, Any]) -> List[str]:
    """
    Robust slot extraction:
    1) rule extract
    2) missingInfoTool
    3) name fallback
    4) phone fallback
    Returns list of slot keys that were newly filled this turn.
    """
    before = dict(slots)
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

    changed = []
    for k, _ in REQ_ORDER:
        if slots.get(k) and slots.get(k) != before.get(k):
            changed.append(k)
    return changed

def slot_human_name(slot: str) -> str:
    mapping = {
        "name": "your full name",
        "country_code": "your country calling code (like +91 or +1)",
        "phone": "your phone number",
        "date": "the date",
        "time": "the time",
        "genre": "the agent category (gym / salon / restaurant / other)",
    }
    return mapping.get(slot, slot)

def price_for(mode: str, genre: str) -> int:
    if mode == "call":
        return CALL_BASE_INR
    return AGENT_BASE_INR


# ============================================================
#   SMALL TALK / CLASSIFICATION
# ============================================================

def small_talk_basic(text: str) -> Optional[str]:
    t = (text or "").lower()
    if any(w in t for w in ["hi", "hello", "hey"]):
        return f"Hey — I’m the AI assistant for {BUSINESS_NAME}. How can I help?"
    if "how are you" in t:
        return "I’m doing well and ready to help with your bookings."
    if "who are you" in t:
        return (
            f"I’m the AI assistant for {BUSINESS_NAME}. "
            "I can help you book an AI agent, schedule a call, share pricing or send our location."
        )
    if any(w in t for w in ["wait", "hold on", "one sec", "hmm"]):
        return "Sure — take your time."
    return None

def classify_question(text: str) -> Optional[str]:
    """
    Returns: 'external', 'personality', 'company', 'random', or None.
    """
    t = (text or "").lower()
    if not t:
        return None

    # company / Aarush questions
    if "aarush ai" in t or "aarush ai solutions" in t or "what do you do" in t or "your services" in t:
        return "company"

    # external world
    if any(k in t for k in ["president", "prime minister", "capital of", "weather", "time in "]):
        return "external"
    if t.startswith("who is ") or "who is the" in t:
        return "external"

    # personality
    if "do you like" in t or "what do you like" in t or "your favourite" in t or "your favorite" in t:
        return "personality"
    if "are you human" in t or "are you conscious" in t:
        return "personality"

    # random
    if "?" in t:
        return "random"
    return None


# ============================================================
#   MAIN SESSION + AGENT
# ============================================================

SESSIONS: Dict[str, Dict[str, Any]] = {}

def get_user_text(msgs: List[Dict[str, Any]]) -> str:
    for m in reversed(msgs):
        if m.get("role") == "user" and m.get("parts"):
            return (m["parts"][0].get("text") or "").strip()
    return ""

def ensure_session(sid: str, frontend_phone: Optional[str]) -> Dict[str, Any]:
    sess = SESSIONS.get(sid)
    if not sess:
        sess = {
            "stage": "idle",           # idle | collect | confirm | payment | done
            "slots": {},
            "hist": [],
            "pending_proposal": None,
            "last_booking_id": None,
        }
        SESSIONS[sid] = sess

    # pre-fill phone from URL once
    if frontend_phone and not sess["slots"].get("phone"):
        parsed = split_phone(frontend_phone)
        if parsed.get("phone"):
            sess["slots"]["phone"] = parsed["phone"]
        if parsed.get("country_code"):
            sess["slots"]["country_code"] = parsed["country_code"]

    return sess


def run_agent(
    msgs: List[Dict[str, Any]],
    sid: str,
    frontend_phone: Optional[str] = None,
    audio_path: Optional[str] = None,
) -> Dict[str, Any]:

    sess = ensure_session(sid, frontend_phone)

    # ---- transcription or plain text ----
    if audio_path:
        user_text = transcribe_webm(audio_path) or "[voice message]"
    else:
        user_text = get_user_text(msgs)

    if not user_text:
        return {
            "reply_text": "I didn’t quite catch that — could you type it again?",
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    low = user_text.lower()
    sess["hist"].append({"ts": datetime.utcnow().isoformat(), "user": user_text})

    # ---- intent detection ----
    intent_info = detect_intent_cached(user_text, allow_llm=False)
    intent = intent_info.get("intent", "unknown")

    # --------------------------------------------------------
    # GLOBAL: company questions (any stage)
    # --------------------------------------------------------
    qtype = classify_question(user_text)
    if qtype == "company":
        core = (
            f"{BUSINESS_NAME} builds custom AI agents for businesses. "
            "They can answer customer queries, generate leads, and handle bookings over voice, chat, or WhatsApp."
        )
        miss = missing_slots(sess["slots"])
        if sess["stage"] == "collect" and miss:
            core += f" For your current booking, I still need: {', '.join(slot_human_name(m) for m in miss)}."
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # GLOBAL: catalog (price list) — works even mid-booking
    # --------------------------------------------------------
    if intent == "get_catalog" or any(k in low for k in ["price", "pricing", "catalog"]):
        res = send_price_catalog(session=sid, phone=None)
        if not res.get("ok"):
            core = "I couldn’t prepare the price catalog right now. Please try again in a bit."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        url = res.get("catalog_url") or res.get("public_url")
        core = f"Here’s the pricing catalog for our AI agents: {url}"
        miss = missing_slots(sess["slots"])
        if sess["stage"] in ("collect", "confirm") and miss:
            core += f" For your booking, I still need: {', '.join(slot_human_name(m) for m in miss)}."
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {"catalog_url": url} if url else {},
        }

    # --------------------------------------------------------
    # GLOBAL: location — works even mid-booking
    # --------------------------------------------------------
    if intent == "get_location" or any(k in low for k in ["location", "address", "where are you"]):
        res = send_location(session=sid, phone=None)
        if not res.get("ok"):
            core = "I couldn’t fetch the office location right now. Please try again later."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }
        url = res.get("location_url")
        txt = res.get("text", "Here’s our office location.")
        core = f"{txt}. You can open it here: {url}"
        miss = missing_slots(sess["slots"])
        if sess["stage"] in ("collect", "confirm") and miss:
            core += f" For your booking, I still need: {', '.join(slot_human_name(m) for m in miss)}."
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {"location_url": url} if url else {},
        }

    # --------------------------------------------------------
    # GLOBAL: small talk
    # --------------------------------------------------------
    if intent == "small_talk":
        base = small_talk_basic(user_text)
        if not base:
            base = "I’m here and listening."
        miss = missing_slots(sess["slots"])
        if sess["stage"] == "collect" and miss:
            base += f" For your booking, I still need: {', '.join(slot_human_name(m) for m in miss)}."
        reply = smart_rewrite(base, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # GLOBAL: payment intent (any stage) → pay for last booking
    # --------------------------------------------------------
    if intent == "pay" or any(k in low for k in ["upi", "qr code", "pay now", "payment"]):
        bid = sess.get("last_booking_id")
        if not bid:
            core = "I don’t see a recent booking to pay for yet. Once you confirm a booking, I can generate a UPI QR for it."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        bk = get_booking_by_id(bid)
        if not bk.get("ok"):
            core = "I couldn’t find that booking right now. Please try again in a moment."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        booking = bk["booking"]
        amount = booking.get("final_amount", price_for(booking.get("type", "agent"), booking.get("agent_type", "other")))
        cc = sess["slots"].get("country_code", "") or ""
        ph = sess["slots"].get("phone", "") or ""
        full_phone = ph if ph.startswith("+") else f"{cc}{ph}" if ph else ""

        qr = generate_upi_qr(booking_id=str(bid), amount=amount, phone=full_phone)
        if not qr.get("ok"):
            core = "I couldn’t generate the payment QR right now. Please try again later."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        url = qr.get("qr_url") or qr.get("public_url")

        if full_phone:
            try:
                send_whatsapp_text(
                    to=full_phone,
                    body=f"Your payment QR for Booking ID {bid} is ready in the web app. Amount: {CURRENCY}{amount}.",
                )
            except Exception:
                pass

        core = f"Here’s your UPI QR for Booking ID {bid}. You can scan it to pay {CURRENCY}{amount} now, or pay offline later."
        reply = smart_rewrite(core, user_text)
        sess["stage"] = "done"
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {"qr_url": url} if url else {},
        }

    # --------------------------------------------------------
    # STAGE: idle → decide booking mode
    # --------------------------------------------------------
    if sess["stage"] == "idle":
        # decide between agent / call
        mode = None
        if intent == "book_agent" or "ai agent" in low or "book an agent" in low:
            mode = "agent"
        elif intent == "book_call" or "book a call" in low or ("call" in low and "back" not in low):
            mode = "call"

        if mode:
            sess["stage"] = "collect"
            sess["slots"]["mode"] = mode

            cc = sess["slots"].get("country_code", "")
            ph = sess["slots"].get("phone", "")
            if ph:
                disp = f"{cc}{ph}" if cc else ph
                core = (
                    f"Great — let’s book your {mode}. I see your phone as {disp}. "
                    "You can use this or send a different number.\n"
                    "I’ll need your full name, country calling code (like +91 or +1), phone number, date, time, "
                    "and agent category (gym / salon / restaurant / other). You can send these in any order."
                )
            else:
                core = (
                    f"Great — let’s book your {mode}. "
                    "I’ll need your full name, country calling code (like +91 or +1), phone number, date, time, "
                    "and agent category (gym / salon / restaurant / other). You can send these in any order."
                )
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        # idle generic
        core = (
            f"I’m the AI assistant for {BUSINESS_NAME}. "
            "I can book an AI agent for your business, schedule a call, show pricing, or send our location. "
            "What would you like to do?"
        )
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # STAGE: collect → gather fields in any order
    # --------------------------------------------------------
    if sess["stage"] == "collect":
        filled_now = extract_all_slots(user_text, sess["slots"])

        # validate date+time as soon as both are present
        if sess["slots"].get("date") and sess["slots"].get("time"):
            dt_str = f"{sess['slots']['date']} {sess['slots']['time']}"
            v = validate_datetime(dt_str)
            if not v.get("ok", True):
                sess["slots"].pop("date", None)
                sess["slots"].pop("time", None)
                core = v.get("summary", "The date and time don’t look valid. Please send a future date and time.")
                reply = smart_rewrite(core, user_text)
                return {
                    "reply_text": reply,
                    "transcript": None,
                    "reply_audio_url": None,
                    "structured": {},
                }

        miss = missing_slots(sess["slots"])

        if miss:
            if filled_now:
                nice_filled = ", ".join(slot_human_name(s) for s in filled_now)
                nice_miss = ", ".join(slot_human_name(m) for m in miss)
                core = f"Got it — I’ve saved your {nice_filled}. I still need: {nice_miss}. Send whichever is easiest next."
            else:
                # classification for non-slot questions mid-flow
                q = classify_question(user_text)
                nice_miss = ", ".join(slot_human_name(m) for m in miss)
                if q == "external":
                    core = (
                        "I don’t have access to general external information like presidents or world facts. "
                        f"For your booking, I still need: {nice_miss}."
                    )
                elif q == "personality":
                    core = (
                        "I’m an AI agent without human-style feelings or opinions. "
                        f"For your booking, I still need: {nice_miss}."
                    )
                elif q == "random":
                    core = (
                        "I’m mainly focused on helping with your booking, pricing, and our AI agents. "
                        f"Right now I still need: {nice_miss}."
                    )
                else:
                    core = (
                        f"I’m not sure which detail that was. For your booking, I still need: {nice_miss}. "
                        "You can send any one of these."
                    )
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        # all slots present → move to confirm
        p = sess["slots"]
        mode = p.get("mode", "agent")
        amount = price_for(mode, p.get("genre", "other"))
        sess["pending_proposal"] = {
            "name": p["name"],
            "country_code": p["country_code"],
            "phone": p["phone"],
            "date": p["date"],
            "time": p["time"],
            "genre": p["genre"],
            "mode": mode,
            "final_amount": amount,
        }
        sess["stage"] = "confirm"

        core = (
            "Just confirming — you’d like a "
            f"{'AI agent' if mode == 'agent' else 'call'} with these details:\n"
            f"- Name: {p['name']}\n"
            f"- Phone: {p['country_code']}{p['phone']}\n"
            f"- Date & time: {p['date']} at {p['time']}\n"
            f"- Category: {p['genre']}\n"
            f"- Estimated total: {CURRENCY}{amount}\n"
            "Reply 'confirm' to finalize, or 'change' if you want to edit anything."
        )
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # STAGE: confirm → confirm or change
    # --------------------------------------------------------
    if sess["stage"] == "confirm":
        if "change" in low:
            sess["stage"] = "collect"
            core = "No problem — tell me what you’d like to change (name, phone, date, time, or agent category)."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        if any(w in low for w in ["confirm", "yes, book", "yes please", "yes", "book it"]):
            p = sess.get("pending_proposal") or {}
            mode = p.get("mode", "agent")
            amount = p.get("final_amount", price_for(mode, p.get("genre", "other")))
            cc = p.get("country_code", "")
            ph = p.get("phone", "")
            full_phone = ph if ph.startswith("+") else f"{cc}{ph}" if ph else ""

            saved = save_booking(
                session=sid,
                phone=full_phone,
                name=p.get("name", ""),
                booking_type=mode,
                agent_type=p.get("genre", ""),
                base_amount=0.0,
                addons=[],
                custom_features=[],
                date=p.get("date"),
                time=p.get("time"),
                payment_status="pending",
                final_amount=amount,
            )
            if not saved.get("ok"):
                core = "I couldn’t save your booking just now. Please try again in a moment."
                reply = smart_rewrite(core, user_text)
                return {
                    "reply_text": reply,
                    "transcript": None,
                    "reply_audio_url": None,
                    "structured": {},
                }

            bid = saved.get("booking_id")
            sess["last_booking_id"] = bid

            # notify owner
            try:
                notify_owner(
                    f"New booking {bid}: {mode} ({p.get('genre')}) on {p.get('date')} at {p.get('time')} for {p.get('name')}."
                )
            except Exception:
                pass

            # WhatsApp confirmation to user
            if full_phone:
                try:
                    send_whatsapp_text(
                        to=full_phone,
                        body=(
                            f"Hello {p.get('name')}, your booking is confirmed.\n"
                            f"Booking ID: {bid}\n"
                            f"Date: {p.get('date')} at {p.get('time')}\n"
                            f"Type: {mode} ({p.get('genre')})\n"
                            f"Amount: {CURRENCY}{amount} (payment pending)."
                        ),
                    )
                except Exception:
                    pass

            sess["stage"] = "payment"

            core = (
                f"Booking confirmed. Your Booking ID is {bid} and the total is {CURRENCY}{amount}. "
                "Would you like to pay now using a UPI QR code, or pay offline at the time of service?"
            )
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {"booking_id": bid},
            }

        # unclear
        core = "To continue, reply 'confirm' to finalize your booking, or 'change' to adjust any detail."
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # STAGE: payment → choose UPI or offline
    # --------------------------------------------------------
    if sess["stage"] == "payment":
        bid = sess.get("last_booking_id")
        if not bid:
            sess["stage"] = "idle"
            core = "I don’t see a booking in progress. You can say 'book an AI agent' or 'book a call' to start."
            reply = smart_rewrite(core, user_text)
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        want_upi = any(k in low for k in ["upi", "qr", "online", "pay now"])
        want_offline = any(k in low for k in ["offline", "cash", "later"])

        bk = get_booking_by_id(bid)
        booking = bk["booking"] if bk.get("ok") else {}
        amount = booking.get("final_amount", price_for(booking.get("type", "agent"), booking.get("agent_type", "other")))
        cc = sess["slots"].get("country_code", "") or ""
        ph = sess["slots"].get("phone", "") or ""
        full_phone = ph if ph.startswith("+") else f"{cc}{ph}" if ph else ""

        if want_upi:
            qr = generate_upi_qr(booking_id=str(bid), amount=amount, phone=full_phone)
            if not qr.get("ok"):
                core = "I couldn’t generate the payment QR right now. Please try again later."
                reply = smart_rewrite(core, user_text)
                return {
                    "reply_text": reply,
                    "transcript": None,
                    "reply_audio_url": None,
                    "structured": {},
                }

            url = qr.get("qr_url") or qr.get("public_url")

            if full_phone:
                try:
                    send_whatsapp_text(
                        to=full_phone,
                        body=f"Your payment QR for Booking ID {bid} is ready in the web app. Amount: {CURRENCY}{amount}.",
                    )
                except Exception:
                    pass

            core = f"Here’s your UPI QR for Booking ID {bid}. You can scan it to pay {CURRENCY}{amount} now."
            reply = smart_rewrite(core, user_text)
            sess["stage"] = "done"
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {"qr_url": url} if url else {},
            }

        if want_offline:
            core = (
                f"Got it — you can pay {CURRENCY}{amount} offline at the time of service. "
                "If you want a UPI QR later, just say 'send payment QR for my booking'."
            )
            reply = smart_rewrite(core, user_text)
            sess["stage"] = "done"
            return {
                "reply_text": reply,
                "transcript": None,
                "reply_audio_url": None,
                "structured": {},
            }

        # unclear in payment stage → hint
        core = (
            "Would you like to pay now using a UPI QR code, or pay offline at the time of service? "
            "You can say 'UPI' or 'offline'."
        )
        reply = smart_rewrite(core, user_text)
        return {
            "reply_text": reply,
            "transcript": None,
            "reply_audio_url": None,
            "structured": {},
        }

    # --------------------------------------------------------
    # STAGE: done / fallback
    # --------------------------------------------------------
    core = (
        f"I can help you with new bookings, pricing, location, or payments. "
        "You can say 'book an AI agent', 'book a call', 'show price catalog', or 'send office location'."
    )
    reply = smart_rewrite(core, user_text)
    return {
        "reply_text": reply,
        "transcript": None,
        "reply_audio_url": None,
        "structured": {},
    }
