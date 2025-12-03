# tools/slot_extractor.py
import re
from typing import Dict, Any

PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{6,}\d)")
DATE_HINT_RE = re.compile(
    r"\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|\d{1,2}\/\d{1,2}\/?\d{0,4})\b",
    re.I,
)
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm)?)\b", re.I)

# Explicit “my name is …” style detection
NAME_RE = re.compile(
    r"(?:my name is|i am|this is|name[:\s])\s*([A-Za-z][A-Za-z ]{1,60})",
    re.I,
)

# Extra plain-name fallback (no keywords)
PLAIN_NAME_RE = re.compile(
    r"^[A-Za-z][A-Za-z\.]+(?: [A-Za-z][A-Za-z\.]+){0,3}$"
)

GENRES = ["gym", "salon", "spa", "restaurant", "plumbing", "electrician", "other"]

ADDONS_KEYWORDS = {
    "web_integration": ["web integration", "web integration+"],
    "payment_integration": ["upi", "payment integration", "payment gateway"],
    "whatsapp_integration": ["whatsapp integration", "whatsapp api"],
}


def clean_phone(raw: str) -> str:
    if not raw:
        return ""
    p = re.sub(r"[^\d\+]", "", raw)
    return p


def extract_slots_from_text(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    t = text.strip()
    low = t.lower()
    slots: Dict[str, Any] = {}

    # PHONE
    ph = PHONE_RE.search(t)
    if ph:
        slots["phone"] = clean_phone(ph.group(1))

    # NAME via explicit pattern
    mname = NAME_RE.search(t)
    if mname:
        slots["name"] = mname.group(1).strip()

    # DATE
    d = DATE_HINT_RE.search(t)
    if d:
        slots["date"] = d.group(1)

    # TIME (only if looks like time, not just "7")
    tm = TIME_RE.search(t)
    if tm and (":" in tm.group(1) or re.search(r"\b(am|pm)\b", tm.group(1), re.I)):
        slots["time"] = tm.group(1)

    # GENRE
    for g in GENRES:
        if g in low:
            slots["genre"] = g
            break

    # ADDONS
    addons = []
    for k, kws in ADDONS_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                addons.append(k)
                break
    if addons:
        slots["addons"] = addons

    # custom features phrase
    m_custom = re.search(
        r"(?:custom|feature|add-on|addons?)[:\-]?\s*(.+)$", t, re.I
    )
    if m_custom:
        val = m_custom.group(1).strip()
        if val:
            slots["custom_features"] = val

    # Plain-name fallback: if NO name yet & text is just a name-like string
    if "name" not in slots:
        if PLAIN_NAME_RE.match(t) and not any(
            kw in low
            for kw in ["book", "agent", "call", "price", "catalog", "location"]
        ):
            slots["name"] = t.strip()

    return slots


if __name__ == "__main__":
    print(
        extract_slots_from_text(
            "My name is Aarush Verma, phone +919876543210, I want an agent for restaurant on 25 Oct at 7 pm"
        )
    )
    print(extract_slots_from_text("Aarush Verma"))
