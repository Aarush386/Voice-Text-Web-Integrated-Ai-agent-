import dateparser

def validate_datetime(nl_string: str) -> dict:
    """
    Natural language date/time validation.
    Examples it supports:
    - "tomorrow at 7pm"
    - "25 Oct 6pm"
    - "next monday 3pm"
    - "today evening"
    """

    if not nl_string or not isinstance(nl_string, str):
        return {"ok": False, "text": "Couldn't read date/time."}

    dt = dateparser.parse(nl_string)

    if not dt:
        return {"ok": False, "text": "Sorry, couldn't understand that date/time."}

    # Convert to ISO clean format: 2025-10-25 19:00
    iso = dt.strftime("%Y-%m-%d %H:%M")

    return {
        "ok": True,
        "iso": iso,
        "text": f"Using date/time: {iso}"
    }
