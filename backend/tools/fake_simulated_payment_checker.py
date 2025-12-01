
import random
def check_payment_simulated(booking_id: str) -> dict:
    paid = random.choice([True, False, False])
    return {"ok": True, "paid": paid, "summary": f"simulated paid={paid}"}