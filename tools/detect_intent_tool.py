# detect_intent_tool.py — final (rules-first, caching)
import re, time
from typing import Dict,Any
_CACHE = {}

_SIMPLE = {
    "book_agent": ["book agent","ai agent","agent for","book an agent","i want an agent","a ai agent"],
    "book_call": ["book a call","book call","phone call","schedule call","call me"],
    "cancel": ["cancel booking","cancel my booking","i want to cancel"],
    "get_catalog": ["catalog","price","pricing","show price","send catalog"],
    "get_location": ["location","address","where are you","map"],
    "pay": ["pay","qr code","upi","pay now"]
}

def detect_intent_cached(text:str, allow_llm:bool=True)->Dict[str,Any]:
    key = text.strip().lower()
    if key in _CACHE and time.time()-_CACHE[key]["ts"]<30:
        return _CACHE[key]["val"]
    val = detect_intent_rules(key)
    _CACHE[key] = {"ts": time.time(), "val": val}
    return val

def detect_intent_rules(text:str)->Dict[str,Any]:
    t = text.lower()
    for intent, phrases in _SIMPLE.items():
        for p in phrases:
            if p in t:
                return {"intent": intent if intent!="get_catalog" else "get_catalog", "confidence": 0.9, "slots":{}}
    # simple fallback small talk
    if any(x in t for x in ("hi","hello","hey","who are you","how are you","wait","hold on")):
        return {"intent":"small_talk","confidence":0.5,"slots":{}}
    return {"intent":"unknown","confidence":0.0,"slots":{}}
