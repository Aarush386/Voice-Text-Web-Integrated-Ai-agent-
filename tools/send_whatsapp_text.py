# tools/send_whatsapp_text.py
import os
from typing import Dict, Any
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g., whatsapp:+1415...

def _normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    p = phone.strip()
    if p.startswith("whatsapp:"):
        return p
    if p.startswith("+"):
        return f"whatsapp:{p}"
    if p.isdigit():
        return f"whatsapp:+{p}"
    return p

def send_whatsapp_text(to: str, body: str) -> Dict[str, Any]:
    """
    Returns structured result: {"ok": bool, "summary": str, "sid": optional}
    """
    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM]):
            return {"ok": False, "summary": "twilio_not_configured"}
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        to_norm = _normalize_phone(to)
        msg = client.messages.create(body=body, from_=TWILIO_WHATSAPP_FROM, to=to_norm)
        return {"ok": True, "summary": "sent", "sid": getattr(msg, "sid", None)}
    except Exception as e:
        err = str(e).lower()
        if "400" in err or "invalid" in err or "phone" in err:
            return {"ok": False, "summary": "invalid_phone"}
        if "auth" in err or "credential" in err:
            return {"ok": False, "summary": "twilio_auth_failed"}
        return {"ok": False, "summary": f"twilio_error:{str(e)[:160]}"}

 