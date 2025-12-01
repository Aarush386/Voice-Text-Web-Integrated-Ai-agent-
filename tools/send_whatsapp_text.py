# tools/send_whatsapp_text.py - robust text-only wrapper
import os
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID","")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN","")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM","whatsapp:+14155238886")  # default sandbox

def _normalize_phone(raw: str) -> str:
    if not raw: return ""
    s = raw.strip()
    if s.startswith("whatsapp:"):
        s = s.replace("whatsapp:","")
    if not s.startswith("+"):
        # leave it as-is; orchestration ensures country_code slot is used
        s = s
    return "whatsapp:" + s

def send_whatsapp_text(to: str, body: str) -> Dict[str, Any]:
    """
    Send a text-only WhatsApp message via Twilio.
    Returns {"ok": bool, "summary": str}
    """
    try:
        if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
            return {"ok": False, "summary": "twilio_not_configured"}
        # lazy import to avoid import errors in environments without twilio
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        to_norm = _normalize_phone(to)
        msg = client.messages.create(body=body, from_=TWILIO_WHATSAPP_FROM, to=to_norm)
        return {"ok": True, "summary": "sent", "sid": getattr(msg,"sid",None)}
    except Exception as e:
        err = str(e).lower()
        if "invalid" in err or "phone" in err:
            return {"ok": False, "summary": "invalid_phone"}
        if "auth" in err:
            return {"ok": False, "summary": "twilio_auth_failed"}
        return {"ok": False, "summary": f"twilio_error:{str(e)[:160]}"}
