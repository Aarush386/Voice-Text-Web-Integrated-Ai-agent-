# tools/detect_intent_tool.py
import time, json, re
from typing import Dict,Any
from dotenv import load_dotenv
load_dotenv()
try:
    from google import generativeai as gen
    GEN_KEY = True
except Exception:
    gen = None
    GEN_KEY = False
_CACHE={}
_CACHE_TTL=20.0
_SIMPLE = {
    "book_agent": ["book agent","book an agent","i want an agent","i want to book an agent"],
    "book_call": ["book a call","book call","schedule call","schedule a call"],
    "show_catalog": ["catalog","price","pricing","price list","menu","show price"],
    "get_location": ["location","where are you","address","map","office"],
    "cancel_booking": ["cancel booking","cancel my booking","i want to cancel"],
    "generate_qr": ["generate qr","pay now","pay online","qr code","payment"],
    "confirm": ["confirm","yes","book now","save booking","confirm booking"],
    "small_talk": ["hi","hello","how are you","who are you","what is this","hmm","wait"]
}
def _norm(s:str)->str:
    return (s or "").strip().lower()
def _rule(text:str)->Dict[str,Any]:
    t=_norm(text)
    for intent,kws in _SIMPLE.items():
        for k in kws:
            if k in t:
                return {"intent":intent,"confidence":0.95,"slots":{}}
    return {"intent":"unknown","confidence":0.0,"slots":{}}
def detect_intent_cached(text:str, allow_llm:bool=False, llm_fn=None)->Dict[str,Any]:
    key=_norm(text)
    now=time.time()
    e=_CACHE.get(key)
    if e and now-e["ts"]<_CACHE_TTL:
        return e["val"]
    rule=_rule(text)
    if rule["confidence"]>0.0:
        _CACHE[key]={"ts":now,"val":rule}
        return rule
    if allow_llm and GEN_KEY and llm_fn:
        try:
            out = llm_fn(text)
            if isinstance(out,dict) and out.get("intent"):
                _CACHE[key]={"ts":now,"val":out}
                return out
        except Exception:
            pass
    _CACHE[key]={"ts":now,"val":rule}
    return rule
if __name__=="__main__":
    print(detect_intent_cached("I want to book an agent for my restaurant on 25 Oct at 7pm"))