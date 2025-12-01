import os, time, json, uuid, re, subprocess, tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional
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
from tools.ensure_utils import ensure_phone_present, normalize_phone_full
import speech_recognition as sr
from pydub import AudioSegment

try:
    from google import generativeai as gen
    MODEL_NAME = os.getenv("GEN_MODEL", "gemini-2.5-flash-lite")
    gen.configure(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("googleApiKEY"))
    LLM_AVAILABLE = True
except:
    gen = None
    MODEL_NAME = None
    LLM_AVAILABLE = False

init_db()
LLM_PER_MIN = int(os.getenv("LLM_PER_MINUTE", "15"))
LLM_CALLS = []

def can_call_llm() -> bool:
    now = time.time()
    window = [t for t in LLM_CALLS if now - t < 60]
    if len(window) >= LLM_PER_MIN:
        return False
    window.append(now)
    LLM_CALLS[:] = window
    return True

def safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        chunk = text[start:end+1]
        return json.loads(chunk)
    except:
        return None

ALLOWED_INTENTS = {
    "book_agent", "book_call", "cancel",
    "get_catalog", "get_location", "pay",
    "confirm", "small_talk", "unknown"
}

def llm_interpret(text: str, snapshot: Dict[str, Any]):
    fallback = detect_intent_cached(text, allow_llm=False)
    if not LLM_AVAILABLE or not can_call_llm():
        return fallback
    system = (
        "Return ONLY JSON. No explanations. Schema:\n"
        "{"
        "\"intent\": string,"
        "\"confidence\": number (0-1),"
        "\"slots\": object,"
        "\"style_hints\": {\"formality\":\"formal|informal\",\"uses_slang\":true|false}"
        "}\n"
        "Allowed intents: book_agent, book_call, cancel, get_catalog, get_location, pay, confirm, small_talk, unknown."
    )
    user_prompt = f"User: {text}\nSnapshot: {json.dumps(snapshot)}\nReturn ONLY the JSON."
    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content(
            [{"role": "user", "parts": [{"text": user_prompt}]}],
            generation_config={"temperature": 0.0, "max_output_tokens": 150}
        )
        candidate = resp.candidates[0]
        raw = candidate.content.parts[0].text
        parsed = safe_json_parse(raw)
        if not parsed:
            return fallback
        intent = parsed.get("intent", "unknown")
        if intent not in ALLOWED_INTENTS:
            parsed["intent"] = "unknown"
        parsed.setdefault("confidence", 0.0)
        parsed.setdefault("slots", {})
        parsed.setdefault("style_hints", {"formality": "formal", "uses_slang": False})
        return parsed
    except:
        return fallback

def llm_rewrite(core: str, user_text: str, style_hints: dict, snapshot: dict) -> str:
    if not LLM_AVAILABLE or not can_call_llm():
        return core
    tokens = re.findall(r"[A-Za-z0-9\+\-\:]{3,}", core)
    system = (
        "Rewrite the assistant message into the user's tone. "
        "DO NOT change numbers, dates, times, amounts, booking IDs. "
        "NO emojis. Output ONLY text."
    )
    prompt = f"CORE: {core}\nUSER: {user_text}\nSTYLE: {json.dumps(style_hints)}"
    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content(
            [{"role":"user","parts":[{"text":prompt}]}],
            generation_config={"temperature":0.1, "max_output_tokens":150}
        )
        out = resp.candidates[0].content.parts[0].text
        for t in tokens:
            if t in core and t not in out:
                return core
        return out.strip()
    except:
        return core

SESSIONS: Dict[str, Dict[str, Any]] = {}

def start_session(sid: str, frontend_phone: Optional[str]):
    s = SESSIONS.get(sid)
    if not s:
        s = {"stage":"idle","slots":{}, "proposed":None, "last_booking":None, "hist":[]}
        SESSIONS[sid] = s
    if frontend_phone:
        parsed = normalize_phone_full(frontend_phone)
        if parsed.get("country_code") and not s["slots"].get("country_code"):
            s["slots"]["country_code"] = parsed["country_code"]
        if parsed.get("phone") and not s["slots"].get("phone"):
            s["slots"]["phone"] = parsed["phone"]
    return s

def small_talk(user: str, session):
    u = user.lower()
    if any(x in u for x in ["hi", "hello", "hey"]):
        return "Hello! How can I assist you today?"
    if "who are you" in u:
        return "I'm the AI assistant for Aarush AI Solutions. I help with bookings and information."
    if any(x in u for x in ["wait", "hold on", "one sec", "bro", "hmm"]):
        return "Sure, take your time — I’m here."
    return None

FX = float(os.getenv("FX_USD_TO_INR","80"))
CURRENCY = "₹"

PRICES_USD = {
    "gym": 200, "salon":180, "restaurant":250, "other":180
}

ADDON_USD = {
    "web_integration":100,
    "payment_integration":100,
    "whatsapp_integration":50
}

def to_inr(usd): 
    return usd * FX

def round_500(x): 
    return int(round(x/500)*500)

def price_calc(genre, addons):
    base = PRICES_USD.get(genre,180)
    add = sum(ADDON_USD.get(a,0) for a in (addons or []))
    total = to_inr(base + add)
    return round_500(total)

REQ_ORDER = [
    ("mode", "Would you like to book a call or book an AI agent?"),
    ("name", "Please provide your full name."),
    ("country_code", "Please provide your country code like +91 or +1."),
    ("phone", "Please provide your phone number."),
    ("date", "What date would you like?"),
    ("time", "What time works for you?"),
    ("genre", "Which agent type (gym/salon/restaurant/other)?")
]

def next_missing(slots):
    for k,_ in REQ_ORDER:
        if not slots.get(k):
            return k
    return None

def question_for(k):
    for kk, q in REQ_ORDER:
        if kk == k:
            return q
    return f"Please provide {k}."

def transcribe_audio(webm_path):
    wav_path = webm_path.replace(".webm", ".wav")
    try:
        AudioSegment.from_file(webm_path).export(wav_path, format="wav")
    except:
        return ""
    try:
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = r.record(source)
        text = r.recognize_google(audio)
    except:
        text = ""
    try:
        os.remove(wav_path)
    except:
        pass
    return text.strip()

def run_agent(msgs, sid, frontend_phone=None, audio_path=None):
    sess = start_session(sid, frontend_phone)
    transcript = None
    if audio_path:
        transcript = transcribe_audio(audio_path)
        user_text = transcript if transcript else "[voice]"
    else:
        user_text = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                user_text = m["parts"][0].get("text","")
                break
    if not user_text:
        return {"reply_text":"I didn't catch that — please repeat.",
                "transcript":None, "reply_audio_url":None, "structured":{}}
    sess["hist"].append({"role":"user","text":user_text})
    snapshot={"stage":sess["stage"],"slots":sess["slots"],"last_booking":sess["last_booking"]}
    interpretation = llm_interpret(user_text, snapshot)
    intent = interpretation.get("intent","unknown")
    hints = interpretation.get("style_hints",{})
    try:
        rule = extract_slots_from_text(user_text)
        for k,v in rule.items():
            if v and not sess["slots"].get(k):
                sess["slots"][k]=v
    except:
        pass
    for k,v in interpretation.get("slots",{}).items():
        if v and not sess["slots"].get(k):
            sess["slots"][k]=v
    if sess["stage"]=="idle":
        sm = small_talk(user_text, sess)
        if sm:
            return {
                "reply_text": sm,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {}
            }
    if intent in ("book_call","book_agent") or any(x in user_text.lower() for x in ["book","reserve"]):
        sess["stage"]="collect"
        if intent=="book_call":
            sess["slots"]["mode"]="call"
        elif intent=="book_agent":
            sess["slots"]["mode"]="agent"
    if sess["stage"]=="collect":
        if sess["slots"].get("phone") and not sess["slots"].get("confirmed_phone"):
            cc = sess["slots"].get("country_code","")
            p = sess["slots"]["phone"]
            display = f"{cc}{p}"
            core = f"I see your phone number is {display}. Would you like to continue with this number? Reply yes or provide a different country code and phone."
            out = llm_rewrite(core, user_text, hints, snapshot)
            sess["slots"]["asked_confirm"]=True
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url": None,
                "structured": {}
            }
        if sess["slots"].get("asked_confirm"):
            if user_text.lower() in ("yes","y","yeah","confirm"):
                sess["slots"]["confirmed_phone"]=True
                sess["slots"].pop("asked_confirm",None)
                core = "Great — what's your full name?"
                out = llm_rewrite(core, user_text, hints, snapshot)
                return {"reply_text": out, "transcript": transcript, "reply_audio_url":None, "structured":{}}
            mcc = re.search(r"(\+\d{1,3})", user_text)
            mph = re.search(r"(\d{6,15})", user_text.replace(" ",""))
            if mcc and mph:
                sess["slots"]["country_code"]=mcc.group(1)
                sess["slots"]["phone"]=mph.group(1)
                sess["slots"]["confirmed_phone"]=True
                sess["slots"].pop("asked_confirm",None)
                core = "Thanks, updated your number. What's your full name?"
                out=llm_rewrite(core,user_text,hints,snapshot)
                return {"reply_text": out, "transcript": transcript, "reply_audio_url":None, "structured":{}}
        miss = next_missing(sess["slots"])
        if miss:
            q = question_for(miss)
            out = llm_rewrite(q, user_text, hints, snapshot)
            return {
                "reply_text": out,
                "transcript": transcript,
                "reply_audio_url":None,
                "structured": {}
            }
        dt = f"{sess['slots']['date']} {sess['slots']['time']}"
        valid = validate_datetime(dt)
        if not valid["ok"]:
            sess["slots"].pop("date",None)
            sess["slots"].pop("time",None)
            core = valid["summary"]
            out = llm_rewrite(core, user_text, hints, snapshot)
            return {"reply_text":out,"transcript":transcript,"reply_audio_url":None,"structured":{}}
        genre = sess["slots"].get("genre","other")
        addons = sess["slots"].get("addons",[])
        amount = price_calc(genre,addons)
        prop = {
            "name": sess["slots"]["name"],
            "country_code": sess["slots"]["country_code"],
            "phone": sess["slots"]["phone"],
            "date": sess["slots"]["date"],
            "time": sess["slots"]["time"],
            "genre": genre,
            "addons": addons,
            "amount_inr": amount
        }
        sess["proposed"]=prop
        sess["stage"]="confirm"
        core = (
            f"Proposal: {genre.title()} for {CURRENCY}{amount} on {prop['date']} at {prop['time']}. "
            "Reply 'confirm' to book or 'change' to modify."
        )
        out = llm_rewrite(core, user_text, hints, snapshot)
        return {
            "reply_text": out,
            "transcript": transcript,
            "reply_audio_url": None,
            "structured": {"proposal": prop}
        }
    if sess["stage"]=="confirm":
        low = user_text.lower()
        if "change" in low:
            sess["stage"]="collect"
            return {"reply_text":"Okay — what would you like to change?",
                    "transcript": transcript,
                    "reply_audio_url":None, "structured":{}}
        if "confirm" in low or low in ("yes","y","book"):
            p = sess["proposed"]
            saved = save_booking(
                session=sid,
                phone=p["phone"],
                name=p["name"],
                booking_type="agent" if sess["slots"]["mode"]=="agent" else "call",
                agent_type=p["genre"],
                base_amount=0,
                addons=p.get("addons",[]),
                custom_features=sess["slots"].get("custom_features",[]),
                date=p["date"],
                time=p["time"],
                payment_status="pending",
                final_amount=p["amount_inr"]
            )
            bid = saved.get("booking_id")
            sess["last_booking"]=bid
            sess["slots"]["booking_id"]=bid
            sess["stage"]="booked"
            try:
                notify_owner(f"New booking {bid}: {p['genre']} for {p['amount_inr']}")
            except:
                pass
            full_phone = sess["slots"]["country_code"] + sess["slots"]["phone"]
            send_whatsapp_text(
                to=full_phone,
                body=f"Hello {p['name']}, your booking is confirmed. ID: {bid}. Date: {p['date']} at {p['time']}."
            )
            core = f"Booking confirmed! ID: {bid}. Amount {CURRENCY}{p['amount_inr']}."
            if sess["slots"]["mode"]=="agent":
                core += " Would you like to pay now using UPI (QR) or pay offline?"
            out = llm_rewrite(core, user_text, hints, snapshot)
            return {"reply_text":out,"transcript":transcript,"reply_audio_url":None,"structured":{"booking_id":bid}}
        return {
            "reply_text":"Please reply 'confirm' or 'change'.",
            "transcript": transcript,
            "reply_audio_url":None,
            "structured":{}
        }
    low = user_text.lower()
    if "pay" in low or "qr" in low:
        bid = sess.get("last_booking")
        if not bid:
            return {"reply_text":"No booking found.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        bk = get_booking_by_id(bid)
        amount = bk["booking"]["final_amount"]
        full_phone = sess["slots"]["country_code"] + sess["slots"]["phone"]
        qr = generate_upi_qr(bid, amount, full_phone)
        url = qr.get("public_url")
        send_whatsapp_text(to=full_phone, body=f"Scan to pay {CURRENCY}{amount}: {url}")
        return {"reply_text":f"QR sent to your WhatsApp: {url}",
                "transcript":transcript,
                "reply_audio_url":None,
                "structured":{"qr_url":url}}
    if "catalog" in low or "price" in low:
        full_phone = sess["slots"]["country_code"] + sess["slots"]["phone"]
        res = send_price_catalog(sid, full_phone)
        url = res.get("public_url")
        send_whatsapp_text(full_phone, f"Catalog: {url}")
        return {"reply_text":f"Catalog sent to WhatsApp.","transcript":transcript,"reply_audio_url":None,"structured":{"catalog_url":url}}
    if "location" in low or "address" in low:
        full_phone = sess["slots"]["country_code"] + sess["slots"]["phone"]
        res = send_location(sid, full_phone)
        url = res.get("public_url")
        send_whatsapp_text(full_phone, f"Our location: {url}")
        return {"reply_text":"Location sent to WhatsApp.","transcript":transcript,"reply_audio_url":None,"structured":{"location_url":url}}
    if "cancel" in low:
        bid = sess["slots"].get("booking_id")
        if not bid:
            return {"reply_text":"Please provide your booking ID.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        cancel_booking(bid)
        sess["stage"]="idle"
        return {"reply_text":f"Booking {bid} cancelled.","transcript":transcript,"reply_audio_url":None,"structured":{"cancelled":bid}}
    info = request_missing_info(user_text, sess["slots"])
    if info.get("slots_found"):
        for k,v in info["slots_found"].items():
            sess["slots"][k] = v
        return {"reply_text":"Got it! Anything else?","transcript":transcript,
                "reply_audio_url":None,"structured":{}}
    return {
        "reply_text": "I can help with bookings, pricing, location, and payments. What would you like to do?",
        "transcript": transcript,
        "reply_audio_url": None,
        "structured": {}
    }
