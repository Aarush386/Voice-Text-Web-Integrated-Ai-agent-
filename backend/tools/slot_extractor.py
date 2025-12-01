import re
from typing import Dict,Any
PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{6,}\d)")
COUNTRY_CODE_RE = re.compile(r"(\+\d{1,3})")
DATE_HINT_RE = re.compile(r"\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|\d{1,2}\/\d{1,2}\/?\d{0,4}|tomorrow|today|next\s+\w+)\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm)?)\b", re.I)
NAME_RE = re.compile(r"(?:my name is|i am|this is|name[:\s])\s*([A-Za-z][A-Za-z \.]{1,80})", re.I)
GENRES = ["gym","salon","spa","restaurant","plumbing","electrician","other"]
ADDONS_KEYWORDS = {
    "web_integration":["web integration","web integration+"],
    "payment_integration":["upi","payment integration","payment gateway","pay"],
    "whatsapp_integration":["whatsapp integration","whatsapp api","whatsapp"]
}
def clean_phone(raw:str)->str:
    if not raw: return ""
    p=re.sub(r"[^\d]", "", raw)
    return p
def split_country_and_phone(raw:str)->Dict[str,str]:
    out={"country_code":"","phone":""}
    if not raw: return out
    raw=raw.strip()
    m_cc = COUNTRY_CODE_RE.search(raw)
    if m_cc:
        out["country_code"]=m_cc.group(1)
        rest = raw[m_cc.end():].strip()
        out["phone"]=clean_phone(rest) if rest else ""
        return out
    digits = clean_phone(raw)
    if digits and len(digits) > 6:
        out["phone"]=digits
    return out
def extract_slots_from_text(text:str)->Dict[str,Any]:
    if not text: return {}
    t=text.strip()
    low=t.lower()
    slots={}
    ph_match = PHONE_RE.search(t)
    if ph_match:
        s = ph_match.group(1)
        sp = split_country_and_phone(s)
        if sp.get("phone"):
            if sp.get("country_code"): slots["country_code"]=sp.get("country_code")
            slots["phone"]=sp.get("phone")
    mname=NAME_RE.search(t)
    if mname:
        slots["name"]=mname.group(1).strip()
    d=DATE_HINT_RE.search(t)
    if d: slots["date"]=d.group(1)
    tm=TIME_RE.search(t)
    if tm and (":" in tm.group(1) or re.search(r"\b(am|pm)\b", tm.group(1), re.I)):
        slots["time"]=tm.group(1)
    for g in GENRES:
        if g in low:
            slots["genre"]=g
            break
    addons=[]
    for k,kws in ADDONS_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                addons.append(k)
                break
    if addons: slots["addons"]=addons
    m_custom=re.search(r"(?:custom|feature|add-on|addons?)[:\-]?\s*(.+)$", t, re.I)
    if m_custom:
        val=m_custom.group(1).strip()
        if val: slots["custom_features"]=val
    return slots
if __name__=="__main__":
    print(extract_slots_from_text("My name is Aarush Verma, phone +919876543210, I want an agent for restaurant on 25 Oct at 7 pm with web integration"))