# tools/validate_datetime_tool.py  (slightly updated)
from datetime import datetime
import dateparser
def validate_datetime(dt_text: str) -> dict:
    """
    Validate and parse datetime string.
    Returns: {"ok": bool, "summary": str, "past": bool, "parsed": str}
    Simplified: no timezone conversions (per product decision).
    """
    if not dt_text or not dt_text.strip():
        return {"ok": False, "summary": "No date/time provided.", "past": False}
    try:
        dt = dateparser.parse(dt_text, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False})
        if not dt:
            return {"ok": False, "summary": f"Could not understand '{dt_text}'. Please use a clear format like 'Dec 5 at 6pm'.", "past": False}
        now = datetime.now()
        if dt <= now:
            return {"ok": False, "summary": f"'{dt_text}' appears to be in the past. Please provide a future date/time.", "past": True, "parsed": dt.isoformat()}
        return {"ok": True, "parsed": dt.isoformat(), "summary": "Date/time is valid"}
    except Exception as e:
        return {"ok": False, "summary": f"Invalid date/time format: {dt_text}", "past": False}