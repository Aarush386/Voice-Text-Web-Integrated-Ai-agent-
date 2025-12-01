from .save_Booking import get_booking_by_id, cancel_booking
def get_booking_by_id_tool(booking_id: str) -> dict:
    return get_booking_by_id(booking_id)
def cancel_booking_tool(booking_id: str) -> dict:
    return cancel_booking(booking_id)