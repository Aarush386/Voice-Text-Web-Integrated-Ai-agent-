import os
from typing import Dict, Any
from twilio.rest import Client
from dotenv import load_dotenv
load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
OWNER_WHATSAPP_TO = os.getenv("OWNER_WHATSAPP_TO")  
def _normalize_phone(phone: str) -> str:
    """Normalize phone to WhatsApp format"""
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
def notify_owner(message: str) -> Dict[str, Any]:
    """
    Send notification to owner via WhatsApp.
    Returns: {"ok": bool, "summary": str, "sid": str}
    """
    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, OWNER_WHATSAPP_TO]):
            return {
                "ok": False,
                "summary": "twilio_not_configured"
            }
        to_normalized = _normalize_phone(OWNER_WHATSAPP_TO)
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=to_normalized
        )
        if msg and hasattr(msg, "sid"):
            return {
                "ok": True,
                "summary": "sent",
                "sid": msg.sid
            }
        return {
            "ok": False,
            "summary": "twilio_send_failed"
        }
    except Exception as e:
        error_str = str(e).lower()
        if "400" in error_str or "phone" in error_str:
            return {
                "ok": False,
                "summary": "invalid_owner_phone"
            }
        if "credentials" in error_str or "auth" in error_str:
            return {
                "ok": False,
                "summary": "twilio_auth_failed"
            }
        return {
            "ok": False,
            "summary": f"notification_failed: {str(e)[:100]}"
        }