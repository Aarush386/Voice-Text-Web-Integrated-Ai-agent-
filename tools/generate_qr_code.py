# tools/generate_qr_code.py
import os
from typing import Dict, Any
import qrcode
from dotenv import load_dotenv

load_dotenv()

# Example: PUBLIC_BASE_URL = "https://your-railway-app-url.up.railway.app"
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

QR_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "media", "qr"
)
os.makedirs(QR_DIR, exist_ok=True)


def _make_public_url(filename: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/media/qr/{filename}"
    # fallback for local dev
    return f"/media/qr/{filename}"


def generate_upi_qr(booking_id: str, amount: float, phone: str = "") -> Dict[str, Any]:
    """
    Generate static QR image and return public URL.
    - NO WhatsApp sending here.
    - Orchestration will:
        * send text template on WhatsApp
        * expose qr_url to the UI.
    """
    try:
        upi_id = os.getenv("UPI_ID", "demo@upi")
        upi_url = (
            f"upi://pay?pa={upi_id}"
            f"&pn=AarushAiSolutions"
            f"&am={amount}"
            f"&cu=INR"
            f"&tn=Booking%20{booking_id}"
        )

        filename = f"qr_{booking_id}.png"
        path = os.path.join(QR_DIR, filename)

        img = qrcode.make(upi_url)
        img.save(path)

        public_url = _make_public_url(filename)
        return {
            "ok": True,
            "public_url": public_url,
            "qr_url": public_url,
            "summary": "QR generated",
        }
    except Exception as e:
        return {"ok": False, "summary": f"QR error: {str(e)}"}
