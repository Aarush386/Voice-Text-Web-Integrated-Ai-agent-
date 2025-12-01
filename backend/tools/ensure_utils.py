from typing import Dict, Any
import re
def ensure_phone_present(slots: Dict[str, Any]) -> bool:
    phone = slots.get("phone")
    if not phone:
        return False
    digits = re.sub(r"[^\d]", "", phone)
    return digits.isdigit() and len(digits) >= 6
def normalize_phone_full(raw: str) -> Dict[str, str]:
    out = {"country_code": "", "phone": ""}
    if not raw:
        return out
    raw = raw.strip()
    cc = re.search(r"(\+\d{1,3})", raw)
    if cc:
        out["country_code"] = cc.group(1)
        remainder = raw[cc.end():]
        digits = re.sub(r"[^\d]", "", remainder)
        out["phone"] = digits
        return out
    digits = re.sub(r"[^\d]", "", raw)
    if digits:
        out["phone"] = digits
    return out