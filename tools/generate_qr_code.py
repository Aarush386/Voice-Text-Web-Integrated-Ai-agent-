# tools/generate_qr_code.py
import os, qrcode
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()
MEDIA_DIR = os.getenv("MEDIA_FOLDER", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media"))
os.makedirs(MEDIA_DIR, exist_ok=True)
UPI_VPA = os.getenv("UPI_ID", os.getenv("DEMO_UPI_VPA", "merchant@upi"))
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
def _public_url(filename: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/media/{filename}"
    return f"/media/{filename}"
def generate_upi_qr(booking_id: str, amount: float, phone: str = None) -> Dict[str, Any]:
    try:
        upi_uri = f"upi://pay?pa={UPI_VPA}&pn=Aarush%20AI%20Solutions&am={amount}&cu=INR&tn=Booking%20{booking_id}"
        filename = f"qr_{booking_id}.png"
        file_path = os.path.join(MEDIA_DIR, filename)
        img = qrcode.make(upi_uri)
        img.save(file_path)
        return {"ok": True, "public_url": _public_url(filename), "file_path": file_path, "summary": f"QR generated for {amount}"}
    except Exception as e:
        return {"ok": False, "summary": f"QR generation failed: {str(e)}"}