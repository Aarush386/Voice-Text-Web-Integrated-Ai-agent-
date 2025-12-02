# tools/send_whatsapp_text.py — text-only robust wrapper
import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")


def _normalize(to: str) -> str:
    if not to:
        return ""
    s = to.strip()
    if s.startswith("whatsapp:"):
        s = s.replace("whatsapp:", "")
    return "whatsapp:" + s


def send_whatsapp_text(to: str, body: str) -> Dict[str, Any]:
    """
    Text-only WhatsApp sending. No media.
    """
    try:
        if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
            return {"ok": False, "summary": "twilio_not_configured"}

        from twilio.rest import Client

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        to_norm = _normalize(to)
        msg = client.messages.create(body=body, from_=TWILIO_WHATSAPP_FROM, to=to_norm)
        return {"ok": True, "summary": "sent", "sid": getattr(msg, "sid", None)}
    except Exception as e:
        err = str(e).lower()
        if "invalid" in err or "phone" in err:
            return {"ok": False, "summary": "invalid_phone"}
        if "auth" in err:
            return {"ok": False, "summary": "twilio_auth_failed"}
        return {"ok": False, "summary": "twilio_error:" + str(e)[:160]}
