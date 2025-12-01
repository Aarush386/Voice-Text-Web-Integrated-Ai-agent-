# slot_extractor.py — final
import re
from typing import Dict,Any

PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{6,}\d)")
COUNTRY_CODE_RE = re.compile(r"(\+\d{1,3})")
DATE_RE = re.compile(r"\b(\d{1,2}\/\d{1,2}\/\d{2,4}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|tomorrow|today|next\s+\w+)\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2}(:\d{2})?\s?(am|pm)?)\b", re.I)
NAME_RE = re.compile(r"(?:my name is|i am|this is|name[:\s])\s*([A-Za-z][A-Za-z \.]{1,80})", re.I)

GENRES = ["gym","salon","spa","restaurant","plumbing","electrician","other"]
ADDON_KEYWORDS = {"web_integration":["web integration"], "payment_integration":["upi","payment integration"], "whatsapp_integration":["whatsapp integration","whatsapp api"]}

def clean_digits(s:str)->str:
    return re.sub(r"[^\d]","", s or "")

def split_country_and_phone(raw:str)->Dict[str,str]:
    out={"country_code":"","phone":""}
    if not raw: return out
    m = COUNTRY_CODE_RE.search(raw)
    if m:
        out["country_code"] = m.group(1)
        rest = raw[m.end():].strip()
        out["phone"] = clean_digits(rest)
        return out
    digits = clean_digits(raw)
    if digits and len(digits)>=6:
        out["phone"] = digits
    return out

def extract_slots_from_text(text:str)->Dict[str,Any]:
    if not text: return {}
    t = text.strip()
    low = t.lower()
    slots={}
    ph = PHONE_RE.search(t)
    if ph:
        sp = split_country_and_phone(ph.group(1))
        if sp.get("country_code"): slots["country_code"] = sp["country_code"]
        if sp.get("phone"): slots["phone"] = sp["phone"]
    mname = NAME_RE.search(t)
    if mname: slots["name"] = mname.group(1).strip()
    md = DATE_RE.search(t)
    if md: slots["date"] = md.group(1)
    mt = TIME_RE.search(t)
    if mt: slots["time"] = mt.group(1)
    for g in GENRES:
        if g in low: slots["genre"]=g; break
    addons=[]
    for k, kws in ADDON_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                addons.append(k); break
    if addons: slots["addons"]=addons
    return slots
