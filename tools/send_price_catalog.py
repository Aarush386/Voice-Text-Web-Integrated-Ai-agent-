import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

CATALOG_PATH = os.getenv(
    "CATALOG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "media", "catalog.jpg"),
)

PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _make_public_url(filename: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/media/{filename}"
    # fallback relative path (frontend is usually on same domain /proxy)
    return f"/media/{filename}"


def send_price_catalog(session: str, phone: str = None) -> Dict[str, Any]:
    """
    Returns:
      { "ok": bool, "public_url": str, "summary": str }
    Media is NOT sent via WhatsApp — only via UI text.
    """
    try:
        if not os.path.exists(CATALOG_PATH):
            return {"ok": False, "summary": "Catalog file not found."}

        filename = os.path.basename(CATALOG_PATH)
        public_url = _make_public_url(filename)

        return {
            "ok": True,
            "catalog_url": public_url,
            "summary": "Catalog ready",
        }
    except Exception as e:
        return {"ok": False, "summary": f"Error accessing catalog: {str(e)}"}
