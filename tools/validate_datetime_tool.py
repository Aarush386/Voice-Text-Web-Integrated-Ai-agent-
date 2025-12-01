from datetime import datetime

def validate_datetime(dt_string):
    try:
        dt = datetime.strptime(dt_string, "%Y-%m-%d %H:%M")
        if dt < datetime.now():
            return {"ok": False, "summary": "This date is in the past. Please provide a future date."}
        return {"ok": True}
    except:
        return {"ok": False, "summary": "Invalid date or time format. Please provide a valid date and time."}
