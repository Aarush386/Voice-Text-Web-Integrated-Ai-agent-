import os
from typing import Dict, Any
import qrcode
from dotenv import load_dotenv

load_dotenv()

PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
QR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media", "qr")

os.makedirs(QR_DIR, exist_ok=True)


def _make_public_url(filename: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/media/qr/{filename}"
    return f"/media/qr/{filename}"


def generate_upi_qr(booking_id: str, amount: float, phone: str) -> Dict[str, Any]:
    """
    Generate static QR image file and return public URL.
    No WhatsApp sending here; orchestration handles only text templates.
    """
    try:
        upi_id = os.getenv("UPI_ID", "demo@upi")
        upi_url = f"upi://pay?pa={upi_id}&pn=AarushAiSolutions&am={amount}&cu=INR&tn=Booking%20{booking_id}"

        filename = f"qr_{booking_id}.png"
        path = os.path.join(QR_DIR, filename)

        img = qrcode.make(upi_url)
        img.save(path)

        return {"ok": True, "public_url": _make_public_url(filename), "summary": "QR generated"}
    except Exception as e:
        return {"ok": False, "summary": f"QR error: {str(e)}"}
