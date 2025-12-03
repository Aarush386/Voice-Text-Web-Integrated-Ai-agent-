import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

MAP_LINK = os.getenv("MAP_GOOGLE_LINK", "https://maps.google.com/?q=40.7128,-74.0060")
ADDRESS = os.getenv("OFFICE_ADDRESS", "496 - Lakeview Street, New York")


def send_location(session: str, phone: str = None) -> Dict[str, Any]:
    """
    Returns:
      { "ok": bool, "public_url": str, "text": str, "summary": str }
    No media via WhatsApp; UI uses public_url.
    """
    try:
        if not MAP_LINK or not MAP_LINK.startswith("http"):
            return {"ok": False, "summary": "Map link not configured properly"}

        text = f"Location: {ADDRESS}"
        return {
            "ok": True,
            "location_url": MAP_LINK,
            "text": text,
            "summary": "Location ready",
        }
    except Exception as e:
        return {"ok": False, "summary": f"Error getting location: {str(e)}"}
