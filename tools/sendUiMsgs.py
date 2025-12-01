def send_ui_msg(session: str, message: str) -> dict:
    try:
        return {"ok": True, "summary": "ui_message_ok"}
    except Exception as e:
        return {"ok": False, "summary": str(e)}