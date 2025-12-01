from typing import Dict, Any
def ensure_phone_present(slots: Dict[str,Any]) -> bool:
    phone = slots.get("phone")
    if not phone:
        return False
    p = phone.replace("+","").replace(" ","").replace("-","")
    return p.isdigit() and len(p) >= 8
def format_proposal(proposal: Dict[str,Any]) -> str:
    return (f"Booking proposal: {proposal.get('genre')} for {proposal.get('final_amount')} USD. "
            f"Date: {proposal.get('date')} at {proposal.get('time')}. Name: {proposal.get('name')}.")