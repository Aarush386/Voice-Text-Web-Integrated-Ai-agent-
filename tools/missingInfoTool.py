from typing import Dict, Any
from .slot_extractor import extract_slots_from_text
def request_missing_info(user_text: str, current_slots: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract new slots from user text and return any not already in current_slots.
    Returns: {"slots_found": dict}
    This is used by orchestration as a fallback slot extraction step.
    """
    found = extract_slots_from_text(user_text)
    if not found:
        return {"slots_found": {}}
    slots_found = {}
    for key, value in found.items():
        if value and not current_slots.get(key):
            slots_found[key] = value
    return {"slots_found": slots_found}