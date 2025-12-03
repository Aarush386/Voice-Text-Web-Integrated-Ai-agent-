from flask import Flask, request, jsonify
from orchestration import run_agent
from werkzeug.utils import secure_filename
import tempfile
import os
from flask_cors import CORS
from twilio.twiml.messaging_response import MessagingResponse
from flask import request
from orchestration import run_agent

app = Flask(__name__)
CORS(app)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response 


@app.route("/twilio-webhook", methods=["POST"])
def twilio_webhook():
    from_number = request.form.get("From", "")
    phone = from_number.replace("whatsapp:", "")

    frontend_url = f"https://voiceandtextaiagent.vercel.app/?phone={phone}"

    resp = MessagingResponse()
    resp.message(f"Hey! Tap here to chat with your AI agent:\n{frontend_url}")
    return str(resp)

@app.route("/api/text", methods=["POST"])
def api_text():
    data = request.get_json(force=True)
    sid = data.get("session_id") or data.get("sid")
    msgs = data.get("messages") or []
    frontend_phone = data.get("frontend_phone")
    resp = run_agent(msgs, sid, frontend_phone=frontend_phone)
    return jsonify(resp)


@app.route("/api/voice", methods=["POST"])
def api_voice():
    session = request.form.get("session")
    frontend_phone = request.form.get("frontend_phone")

    if "audio" not in request.files:
        return jsonify({"error": "no audio"}), 400

    audio_file = request.files["audio"]
    filename = secure_filename(audio_file.filename)
    tmp = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmpf:
            audio_path = tmpf.name
            audio_file.save(audio_path)
            tmp = audio_path

        resp = run_agent(
            [],
            session,
            frontend_phone=frontend_phone,
            audio_path=audio_path
        )

        return jsonify({
            "reply_text": resp.get("reply_text"),
            "transcript": resp.get("transcript"),
            "reply_audio_url": resp.get("reply_audio_url"),
            "structured": resp.get("structured", {})
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except:
            pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
