# orchestration.py — FINAL (drop-in)
import os, time, json, uuid, re, subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

# tools
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
from tools.ensure_utils import ensure_phone_present, normalize_phone_full, ensure_phone_digits

# STT (pydub + speech_recognition) — fail safe
from pydub import AudioSegment
import speech_recognition as sr

# optional LLM (Gemini) - always conservative
try:
    from google import generativeai as gen
    MODEL_NAME = os.getenv("GEN_MODEL","gemini-2.5-flash-lite")
    gen.configure(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("googleApiKEY"))
    LLM_AVAILABLE = True
except Exception:
    gen = None
    MODEL_NAME = None
    LLM_AVAILABLE = False

init_db()

LLM_PER_MIN = int(os.getenv("LLM_PER_MINUTE","15"))
LLM_CALLS: List[float] = []
def can_call_llm() -> bool:
    now=time.time()
    window=[t for t in LLM_CALLS if now-t<60]
    if len(window)>=LLM_PER_MIN: return False
    window.append(now); LLM_CALLS[:] = window; return True

def safe_json_parse(text:str)->Optional[Dict[str,Any]]:
    try:
        s=text.find("{"); e=text.rfind("}")
        if s==-1 or e==-1: return None
        return json.loads(text[s:e+1])
    except Exception:
        return None

ALLOWED_INTENTS = {"book_agent","book_call","cancel","get_catalog","get_location","pay","confirm","small_talk","unknown"}

def llm_interpret(text:str, snapshot:Dict[str,Any])->Dict[str,Any]:
    fallback = detect_intent_cached(text, allow_llm=False)
    if not LLM_AVAILABLE or not can_call_llm(): return fallback
    system = ("Return EXACTLY one JSON object and nothing else. Schema: "
              '{"intent":"string","confidence":0-1,"slots":{},"style_hints":{}}'
              " Allowed intents: " + ",".join(sorted(ALLOWED_INTENTS)))
    prompt = f"User: {text}\nSnapshot:{json.dumps(snapshot)}\nReturn ONLY JSON."
    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content([{"role":"user","parts":[{"text":prompt}]}], generation_config={"temperature":0.0,"max_output_tokens":160})
        out = resp.candidates[0].content.parts[0].text
        parsed = safe_json_parse(out)
        if not parsed: return fallback
        parsed.setdefault("confidence",0.0); parsed.setdefault("slots",{}); parsed.setdefault("style_hints",{})
        if parsed.get("intent") not in ALLOWED_INTENTS: parsed["intent"]="unknown"
        return parsed
    except Exception:
        return fallback

def llm_rewrite(core:str, user_text:str, style_hints:Dict[str,Any], snapshot:Dict[str,Any]) -> str:
    if not LLM_AVAILABLE or not can_call_llm(): return core
    tokens = re.findall(r"[A-Za-z0-9\+\-\:\.]{2,}", core)
    system = "Rewrite core_text to match user's tone. DO NOT change numbers, dates, booking IDs, or phone numbers. No emojis. Output only text."
    prompt = f"CORE: {core}\nUSER: {user_text}\nSTYLE: {json.dumps(style_hints)}"
    try:
        model = gen.GenerativeModel(model_name=MODEL_NAME, system_instruction=system)
        resp = model.generate_content([{"role":"user","parts":[{"text":prompt}]}], generation_config={"temperature":0.12,"max_output_tokens":200})
        out = resp.candidates[0].content.parts[0].text
        for t in tokens:
            if t in core and t not in out: return core
        return out.strip()
    except Exception:
        return core

# SESSIONS
SESSIONS: Dict[str,Dict[str,Any]] = {}
def start_session(sid:str, frontend_phone:Optional[str]=None)->Dict[str,Any]:
    s = SESSIONS.get(sid)
    if not s:
        s = {"stage":"idle","slots":{},"proposed":None,"last_booking":None,"hist":[]}
        SESSIONS[sid] = s
    if frontend_phone:
        parsed = normalize_phone_full(frontend_phone)
        if parsed.get("country_code") and not s["slots"].get("country_code"): s["slots"]["country_code"]=parsed["country_code"]
        if parsed.get("phone") and not s["slots"].get("phone"): s["slots"]["phone"]=parsed["phone"]
    return s

def small_talk_response(text:str)->Optional[str]:
    t=(text or "").lower()
    if any(x in t for x in ("hi","hello","hey")): return "Hello! How can I assist you today?"
    if "who are you" in t: return "I'm the AI assistant for Aarush AI Solutions. I help with bookings and info."
    if any(x in t for x in ("wait","hold on","one sec","hmm","bro")): return "Sure — take your time."
    return None

FX_USD_TO_INR = float(os.getenv("FX_USD_TO_INR","80"))
CURRENCY = os.getenv("CURRENCY_INR","₹")
PRICES_USD = {"gym":200,"salon":180,"restaurant":250,"other":180}
ADDON_USD = {"web_integration":100,"payment_integration":100,"whatsapp_integration":50}
def price_calc(genre:str, addons:List[str])->int:
    base = PRICES_USD.get(genre, PRICES_USD["other"]); addons_sum=sum(ADDON_USD.get(a,0) for a in (addons or []))
    total = (base+addons_sum) * FX_USD_TO_INR
    return int(round(total/500.0))*500

REQ_ORDER = [
    ("mode","Would you like to book a call or book an AI agent?"),
    ("name","Please provide your full name."),
    ("country_code","Please provide your country code like +91 or +1."),
    ("phone","Please provide your phone number."),
    ("date","Which date would you like?"),
    ("time","Which time would you like?"),
    ("genre","Which agent type? (gym/salon/restaurant/other)")
]

def next_missing(slots:Dict[str,Any])->Optional[str]:
    for k,_ in REQ_ORDER:
        if not slots.get(k): return k
    return None
def q_for_slot(k:str)->str:
    for kk,q in REQ_ORDER:
        if kk==k: return q
    return f"Please provide {k}."

# TRANSCRIBE webm -> wav -> speech_recognition
def transcribe_audio(webm_path:str)->str:
    wav_path = webm_path.replace(".webm",".wav")
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
    try: os.remove(wav_path)
    except: pass
    return text.strip()

def get_user_text(msgs:List[Dict[str,Any]])->str:
    if not msgs: return ""
    for m in reversed(msgs):
        if m.get("role")=="user" and m.get("parts"):
            return m["parts"][0].get("text","").strip()
    return ""

def run_agent(msgs:List[Dict[str,Any]], sid:str, frontend_phone:Optional[str]=None, audio_path:Optional[str]=None) -> Dict[str,Any]:
    sess = start_session(sid, frontend_phone)
    transcript = None
    if audio_path:
        transcript = transcribe_audio(audio_path)
        user_text = transcript if transcript else "[voice]"
    else:
        user_text = get_user_text(msgs)

    if not user_text:
        return {"reply_text":"I didn't catch that — please repeat.","transcript":None,"reply_audio_url":None,"structured":{}}

    sess["hist"].append({"role":"user","text":user_text,"ts":datetime.utcnow().isoformat()})
    snapshot = {"stage":sess["stage"], "slots": sess["slots"], "last_booking": sess.get("last_booking")}

    # First, quick RULE-based interpretation (fast) and then conservative LLM
    interpretation = llm_interpret(user_text, snapshot)
    intent = interpretation.get("intent","unknown")
    style_hints = interpretation.get("style_hints",{})

    # RULE slot extractor first
    try:
        rule_slots = extract_slots_from_text(user_text)
        for k,v in (rule_slots or {}).items():
            if v and not sess["slots"].get(k): sess["slots"][k]=v
    except Exception:
        pass
    # merge LLM slots conservatively
    for k,v in (interpretation.get("slots") or {}).items():
        if v and not sess["slots"].get(k): sess["slots"][k]=v

    # small talk idle
    small = small_talk_response(user_text)
    if small and sess["stage"]=="idle":
        out = llm_rewrite(small, user_text, style_hints, snapshot) if LLM_AVAILABLE and can_call_llm() else small
        return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}

    # small talk during booking: acknowledge then continue
    if small and sess["stage"]!="idle":
        miss = next_missing(sess["slots"])
        reply = small + (" — now, about your booking, " + q_for_slot(miss) if miss else "")
        return {"reply_text": reply, "transcript": transcript, "reply_audio_url": None, "structured": {}}

    # trigger booking: RULES: any "agent" word => book_agent (Option A)
    low = user_text.lower()
    if any(w in low for w in ("book agent","ai agent","a ai agent","agent","i want an agent","book an agent")) or intent=="book_agent":
        sess["stage"]="collect"; sess["slots"]["mode"]="agent"
    elif any(w in low for w in ("book a call","book call","call","phone call")) or intent=="book_call":
        sess["stage"]="collect"; sess["slots"]["mode"]="call"
    elif intent in ("book_agent","book_call"):
        sess["stage"]="collect"

    # collect logic
    if sess["stage"]=="collect":
        # ensure phone confirm if auto-detected and not confirmed
        if sess["slots"].get("phone") and not sess["slots"].get("confirmed_phone") and not sess["slots"].get("asked_confirm"):
            cc = sess["slots"].get("country_code",""); display = f"{cc}{sess['slots']['phone']}" if cc else sess["slots"]["phone"]
            core = f"I see your number is {display}. Use this number? Reply 'yes' to confirm or send a different +countrycode and phone."
            sess["slots"]["asked_confirm"]=True
            out = llm_rewrite(core, user_text, style_hints, snapshot) if LLM_AVAILABLE and can_call_llm() else core
            return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}

        # handle confirm replacement
        if sess["slots"].get("asked_confirm") and not sess["slots"].get("confirmed_phone"):
            l = user_text.lower().strip()
            if l in ("yes","y","yeah","confirm"):
                sess["slots"]["confirmed_phone"]=True; sess["slots"].pop("asked_confirm",None)
                core="Great — could you provide your full name?"
                out = llm_rewrite(core,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else core
                return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}
            # parse replacement
            mcc = re.search(r"(\+\d{1,3})", user_text)
            mph = re.search(r"(\d{6,15})", user_text.replace(" ",""))
            if mcc and mph:
                sess["slots"]["country_code"]=mcc.group(1); sess["slots"]["phone"]=re.sub(r"[^\d]","",mph.group(1))
                sess["slots"]["confirmed_phone"]=True; sess["slots"].pop("asked_confirm",None)
                core="Thanks — updated phone. What's your full name?"
                out = llm_rewrite(core,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else core
                return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}
            return {"reply_text":"Please reply 'yes' to use detected number, or provide country code like +1 and phone.","transcript":transcript,"reply_audio_url":None,"structured":{}}

        # quick mode inference if missing (robust)
        if not sess["slots"].get("mode"):
            if any(w in low for w in ("agent","ai agent","book agent")): sess["slots"]["mode"]="agent"
            if any(w in low for w in ("call","book a call","phone call")): sess["slots"]["mode"]="call"

        miss = next_missing(sess["slots"])
        if miss:
            q = q_for_slot(miss)
            out = llm_rewrite(q,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else q
            return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}

        # validate date/time
        dt = f"{sess['slots'].get('date','')} {sess['slots'].get('time','')}".strip()
        if dt:
            v = validate_datetime(dt)
            if not v.get("ok",False):
                sess["slots"].pop("date",None); sess["slots"].pop("time",None)
                core = v.get("summary","Invalid date/time")
                out = llm_rewrite(core,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else core
                return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured": {}}

        # compose proposal & move to confirm
        genre = sess["slots"].get("genre","other"); addons = sess["slots"].get("addons",[])
        amount = price_calc(genre,addons)
        prop = {"name":sess["slots"].get("name"), "country_code":sess["slots"].get("country_code",""), "phone":sess["slots"].get("phone",""), "date":sess["slots"].get("date"), "time":sess["slots"].get("time"), "genre":genre, "addons":addons, "amount_inr":amount}
        sess["proposed"] = prop; sess["stage"]="confirm"
        core = f"Proposal: {prop['genre'].title()} for {CURRENCY}{prop['amount_inr']} on {prop['date']} at {prop['time']}. Reply 'confirm' to book or 'change' to edit."
        out = llm_rewrite(core,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else core
        return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured":{"proposal":prop}}

    # confirm stage
    if sess["stage"]=="confirm":
        low = user_text.lower()
        if "change" in low:
            sess["stage"]="collect"; return {"reply_text":"Okay — what would you like to change?","transcript":transcript,"reply_audio_url":None,"structured":{}}
        if any(x in low for x in ("confirm","yes","book now","i confirm")):
            p = sess.get("proposed",{})
            saved = save_booking(session=sid, phone=p.get("phone",""), name=p.get("name",""), booking_type="agent" if sess["slots"].get("mode")=="agent" else "call", agent_type=p.get("genre",""), base_amount=0.0, addons=p.get("addons",[]), custom_features=sess["slots"].get("custom_features",[]), date=p.get("date"), time=p.get("time"), payment_status="pending", final_amount=p.get("amount_inr",0))
            if not saved.get("ok"): return {"reply_text":"Couldn't save booking. Try again later.","transcript":transcript,"reply_audio_url":None,"structured":{}}
            bid = saved.get("booking_id"); sess["last_booking"]=bid; sess["slots"]["booking_id"]=bid; sess["stage"]="booked"
            try: notify_owner(f"New booking {bid}: {p.get('genre')} for {p.get('amount_inr')}") 
            except: pass
            full_phone = (sess["slots"].get("country_code","") or "") + (sess["slots"].get("phone","") or "")
            try: send_whatsapp_text(to=full_phone, body=f"Congrats — your booking is confirmed. ID: {bid}. Date: {p.get('date')} at {p.get('time')}.")
            except: pass
            core = f"Booking confirmed. ID: {bid}. Amount: {CURRENCY}{p.get('amount_inr')}."
            if sess["slots"].get("mode")=="agent": core += " Would you like to pay now using UPI (QR) or pay offline?"
            out = llm_rewrite(core,user_text,style_hints,snapshot) if LLM_AVAILABLE and can_call_llm() else core
            return {"reply_text": out, "transcript": transcript, "reply_audio_url": None, "structured":{"booking_id":bid}}

        return {"reply_text":"Please reply 'confirm' to finalize or 'change' to modify.","transcript":transcript,"reply_audio_url":None,"structured":{}}

    # post-booking actions: QR, catalog, location, cancel (UI displays media; WhatsApp gets text-only template)
    low = user_text.lower()
    if any(x in low for x in ("generate qr","pay now","pay online","qr code","pay")):
        bid = sess.get("last_booking") or sess["slots"].get("booking_id")
        if not bid: return {"reply_text":"No booking available to pay for.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        bk = get_booking_by_id(bid)
        if not bk.get("ok"): return {"reply_text":"Booking not found.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        amt = bk["booking"].get("final_amount")
        qr = generate_upi_qr(booking_id=bid, amount=amt, phone=(sess["slots"].get("country_code","") + sess["slots"].get("phone","")))
        if not qr.get("ok"): return {"reply_text":"Couldn't create QR now.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        url = qr.get("public_url")
        try: send_whatsapp_text(to=(sess["slots"].get("country_code","")+sess["slots"].get("phone","")), body=f"Payment QR is ready in the app for Booking ID {bid}.")
        except: pass
        return {"reply_text":"QR ready — open the app to scan.", "transcript":transcript, "reply_audio_url":None, "structured":{"qr_url":url}}

    if any(x in low for x in ("catalog","price","pricing","menu","show price","send catalog")):
        try: res = send_price_catalog(session=sid, phone=(sess.get("slots",{}).get("country_code","") + sess.get("slots",{}).get("phone","")))
        except: res={"ok":False}
        if not res.get("ok"): return {"reply_text":"Couldn't prepare the catalog right now. Try again later.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        url = res.get("public_url")
        try: send_whatsapp_text(to=(sess.get("slots",{}).get("country_code","")+sess.get("slots",{}).get("phone","")), body="The price catalog is available in the app for your convenience.")
        except: pass
        return {"reply_text":"I've prepared the price catalog — check it in the app.", "transcript":transcript, "reply_audio_url":None, "structured":{"catalog_url":url}}

    if any(x in low for x in ("location","address","where are you","map")):
        try: res = send_location(session=sid, phone=(sess.get("slots",{}).get("country_code","") + sess.get("slots",{}).get("phone","")))
        except: res={"ok":False}
        if not res.get("ok"): return {"reply_text":"Couldn't fetch location right now.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        url = res.get("public_url")
        try: send_whatsapp_text(to=(sess.get("slots",{}).get("country_code","") + sess.get("slots",{}).get("phone","")), body="We've shared location details in the app.")
        except: pass
        return {"reply_text":"Location is ready — check your app.", "transcript":transcript, "reply_audio_url":None, "structured":{"location_url":url}}

    if any(x in low for x in ("cancel booking","cancel my booking","i want to cancel")):
        bid = sess["slots"].get("booking_id") or sess.get("last_booking")
        if not bid: return {"reply_text":"Please provide booking ID to cancel.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        out = cancel_booking(booking_id=bid)
        if not out.get("ok"): return {"reply_text":"Couldn't cancel booking. Try again later.","transcript":transcript,"reply_audio_url":None,"structured":{}}
        sess["stage"]="idle"
        try: send_whatsapp_text(to=(sess.get("slots",{}).get("country_code","") + sess.get("slots",{}).get("phone","")), body=f"Your booking {bid} has been cancelled.")
        except: pass
        return {"reply_text":f"Booking {bid} cancelled.","transcript":transcript,"reply_audio_url":None,"structured":{"cancelled":bid}}

    # fallback extraction
    info = request_missing_info(user_text, sess["slots"])
    if info.get("slots_found"):
        for k,v in info["slots_found"].items():
            if not sess["slots"].get(k): sess["slots"][k]=v
        return {"reply_text":"Got it — noted. Anything else or shall we continue?", "transcript":transcript, "reply_audio_url":None, "structured":{}}

    return {"reply_text":"I can help with bookings, pricing, location, and payments. What would you like to do?", "transcript":transcript, "reply_audio_url":None, "structured":{}}
