from flask import Flask, request, jsonify
from orchestration import run_agent
from werkzeug.utils import secure_filename
import tempfile
import os
from flask_cors import CORS

app = Flask(__name__, static_folder="media")
CORS(app)

@app.route("/api/text", methods=["POST"])
def api_text():
    data = request.get_json() or {}
    session = data.get("session_id")
    messages = data.get("messages", [])
    frontend_phone = data.get("frontend_phone", None)
    resp = run_agent(messages, session, frontend_phone)
    return jsonify({
        "reply_text": resp.get("reply_text"),
        "transcript": resp.get("transcript"),
        "reply_audio_url": resp.get("reply_audio_url"),
        "structured": resp.get("structured", {})
    })

@app.route("/api/voice", methods=["POST"])
def api_voice():
    session = request.form.get("session")
    frontend_phone = request.form.get("frontend_phone", None)

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
            [{"role": "user", "parts": [{"text": "[voice message]"}]}],
            session,
            frontend_phone,
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
