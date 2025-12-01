import sqlite3
import os
import uuid
import json
from typing import Dict, Any
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.db")
def init_db():
    """Initialize bookings database"""
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                session TEXT,
                phone TEXT,
                name TEXT,
                type TEXT,
                agent_type TEXT,
                base REAL,
                addons TEXT,
                custom TEXT,
                date TEXT,
                time TEXT,
                status TEXT,
                amount REAL
            )
        """)
        con.commit()
def save_booking(
    session: str,
    phone: str,
    name: str,
    booking_type: str,
    agent_type: str,
    base_amount: float,
    addons: list,
    custom_features: list,
    date: str,
    time: str,
    payment_status: str,
    final_amount: float
) -> Dict[str, Any]:
    """
    Save booking to database.
    Returns: {"ok": bool, "booking_id": str, "error": str}
    """
    try:
        bid = uuid.uuid4().hex[:8].upper()
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute(
                """INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bid,
                    session,
                    phone,
                    name,
                    booking_type,
                    agent_type,
                    base_amount,
                    json.dumps(addons or []),
                    json.dumps(custom_features or []),
                    date,
                    time,
                    payment_status,
                    final_amount
                )
            )
            con.commit()
        return {"ok": True, "booking_id": bid}
    except Exception as e:
        return {"ok": False, "error": str(e), "summary": f"Database error: {str(e)}"}
def get_booking_by_id(booking_id: str) -> Dict[str, Any]:
    """
    Retrieve booking by ID.
    Returns: {"ok": bool, "booking": {...}}
    """
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM bookings WHERE booking_id=?", (booking_id,))
            row = cur.fetchone()
        if not row:
            return {"ok": False, "summary": "Booking not found"}
        keys = [
            "booking_id", "session", "phone", "name", "type", "agent_type", "base",
            "addons", "custom", "date", "time", "status", "amount"
        ]
        data = dict(zip(keys, row))
        data["addons"] = json.loads(data["addons"]) if data["addons"] else []
        data["custom"] = json.loads(data["custom"]) if data["custom"] else []
        data["final_amount"] = data["amount"]
        return {"ok": True, "booking": data}
    except Exception as e:
        return {"ok": False, "summary": f"Database error: {str(e)}"}
def cancel_booking(booking_id: str) -> Dict[str, Any]:
    """
    Cancel booking by setting status to 'cancelled'.
    Returns: {"ok": bool, "summary": str}
    """
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute(
                "UPDATE bookings SET status = ? WHERE booking_id = ?",
                ("cancelled", booking_id)
            )
            con.commit()
            changed = cur.rowcount
        if changed:
            return {"ok": True, "summary": f"Booking {booking_id} cancelled"}
        return {"ok": False, "summary": "Booking not found"}
    except Exception as e:
        return {"ok": False, "summary": f"Database error: {str(e)}"}