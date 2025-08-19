import eventlet
eventlet.monkey_patch()  # MUST be first

import os
import sys
import json
import datetime
import tempfile
import time

from google import genai
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, redirect, url_for, g
from flask_socketio import SocketIO, join_room, emit
import firebase_admin
from firebase_admin import credentials, firestore as firestore_admin
# If you keep using inference_sdk, leave this import; otherwise you can remove and use requests instead.
from inference_sdk import InferenceHTTPClient

# Make parent folder importable (so blueprints at repo root work when this file is under /api)
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

load_dotenv()

# --- Firebase Admin / Firestore (REST transport to avoid gRPC stalls in eventlet) ---
sa_json = os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
sa = json.loads(sa_json)
cred = credentials.Certificate(sa)
firebase_admin.initialize_app(cred)


db = firestore_admin.client()

# --- Env & Gemini ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- Flask / Socket.IO ---
app = Flask(
    __name__,
    static_folder="../static",          # serve static from repo /static
    template_folder="../templates"      # serve templates from repo /templates
)
app.config["DB"] = db
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-in-env")
socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins=[o.strip() for o in os.getenv("SOCKETIO_CORS", "*").split(",") if o.strip()],
    ping_interval=25,   # seconds between client pings
    ping_timeout=60     # time to wait for pong before disconnect
)

# --- simple health check ---
@app.get("/_ping")
def _ping():
    return "ok", 200

# --- request timing (helps debug stalls) ---
@app.before_request
def _start_timer():
    g._t0 = time.perf_counter()

@app.after_request
def _log_timing(resp):
    try:
        dt = (time.perf_counter() - g._t0) * 1000
        print(f"{request.method} {request.path} -> {resp.status_code} in {dt:.1f}ms")
    except Exception:
        pass
    return resp

# --- Roboflow ---
rf_client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=os.getenv("ROBOFLOW_API_KEY"),
)

# --- Blueprints ---
from .auth import auth_bp
from .tenant import tenant_bp
from .landlord import landlord_bp
from .profilepage import profile_bp

app.register_blueprint(auth_bp)
app.register_blueprint(tenant_bp)
app.register_blueprint(landlord_bp)
app.register_blueprint(profile_bp)


@app.route("/chat")
def chat():
    if "username" not in session:
        return redirect(url_for("auth.login"))
    if session.get("role") == "tenant":
        return redirect(url_for("tenant.tenant_chat"))
    elif session.get("role") == "landlord":
        return redirect(url_for("landlord.landlord_chat"))
    return redirect(url_for("auth.login"))


def get_ai_advice_from_label(user, state, label):
    try:
        prompt = (
            f"Act as a legal expert in housing and tenant rights.\n\n"
            f"Create a formal legal complaint letter that a tenant named '{user}' "
            f"living in the state of '{state}' can send to their landlord.\n\n"
            f"The complaint is about the following issue: '{label}'.\n\n"
            f"The letter should:\n"
            f"- Mention relevant state-specific tenant rights and repair laws (for {state})\n"
            f"- Formally demand that the landlord fixes the issue\n"
            f"- Specify a reasonable time frame for repair (e.g., 7 days)\n"
            f"- Clearly state possible legal consequences (such as withholding rent, "
            f"  small claims court, health department complaints) if the landlord fails to act\n"
            f"- Be written in a formal, professional tone\n"
            f"- Assume the tenant wants to stay polite but firm\n\n"
            f"Output the complete legal letter ready to be copied and sent."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "Unable to generate advice at the moment."


def get_ai_days_from_label(state, label):
    try:
        prompt = (
            "Act as a legal expert specializing in housing and tenant rights. "
            "I need you to determine the statutory period—the number of days a landlord has to fix an issue "
            "in a rented living space before a tenant can file a legal claim—based on state law."
            f"State: {state} Issue: {label}"
            "Please provide: "
            "1. The specific number of days (or the range of days) the law grants for the landlord "
            "to address this issue before a legal claim can be filed."
            "Output the answer AS ONE INTEGER NOTHING MORE NOTHING LESS"
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}],
        )
        return int(response.text.strip())
    except Exception as e:
        print(f"Gemini API error: {e}")
        return 7  # safe default


@app.route("/upload_image", methods=["POST"])
def upload_image():
    chat_id = request.args.get("chat_id")

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"})

    file = request.files["file"]

    # Use a guaranteed-writable temp location in serverless environments
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file.save(tmp.name)
        temp_path = tmp.name

    try:
        prediction = rf_client.infer(temp_path, model_id="classification-house-problems/1")
        label = prediction.get("predictions", [{}])[0].get("class", "Unknown")

        # Pull any needed session fields (optional)
        _current_user = session.get("username")
        _state = session.get("state")

        return jsonify({"success": True, "label": label})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


@app.route("/addIssue", methods=["POST"])
def add_issue():
    """
    Expects a JSON payload with a key 'label'. Retrieves the current user's uid from the session,
    fetches additional user details (e.g. state) from Firestore, and uses the data along with the label
    to generate legal advice using get_ai_advice_from_label. The resulting advice is stored with the
    issue along with tenant and status.
    """
    try:
        data = request.get_json(force=True)
        label = data.get("label")

        if not label:
            return jsonify({"success": False, "error": "Missing 'label' field"}), 400

        current_user = session.get("uid")
        if not current_user:
            return jsonify({"success": False, "error": "User not logged in"}), 400

        user_doc = db.collection("users").document(current_user).get()
        if not user_doc.exists:
            return jsonify({"success": False, "error": "User data not found"}), 404

        user_data = user_doc.to_dict()
        state = user_data.get("state")
        username = user_data.get("username", current_user)

        if not state:
            return jsonify({"success": False, "error": "User state not found"}), 400

        ai_advice = get_ai_advice_from_label(username, state, label)
        num_days = get_ai_days_from_label(state, label)

        issue_data = {
            "label": label,
            "tenant": current_user,
            "status": "pending",
            "ai_advice": ai_advice,
            "days": num_days,
            "created_at": firestore_admin.SERVER_TIMESTAMP,  # keep SERVER_TIMESTAMP from admin SDK
        }

        db.collection("issues").add(issue_data)

        return jsonify({"success": True, "label": label, "tenant": current_user}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/load_chat/<chat_id>")
def load_chat(chat_id):
    try:
        messages_ref = db.collection("chats").document(chat_id).collection("messages")
        messages_query = (
            messages_ref.order_by("timestamp", direction=firestore_admin.Query.DESCENDING)
            .limit(10)
            .get()   # WAS: .stream() -> change to .get() for eager fetch under eventlet
        )
        messages = [doc.to_dict() for doc in messages_query]
        messages.reverse()
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})


@socketio.on("join_chat")
def join_chat(data):
    chat_id = data.get("chat_id")
    join_room(chat_id)
    emit(
        "chat_message",
        {"sender": "System", "message": f"Joined chat room: {chat_id}", "chat_id": chat_id},
        room=chat_id,
    )


@socketio.on("send_chat_message")
def handle_send_chat_message(data):
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    message = data.get("message")
    msg_type = data.get("type", "text")

    live_timestamp = datetime.datetime.utcnow().isoformat()

    live_message_data = {
        "sender": sender,
        "message": message,
        "type": msg_type,
        "timestamp": live_timestamp,
        "chat_id": chat_id,
    }

    store_message_data = {
        "sender": sender,
        "message": message,
        "type": msg_type,
        "timestamp": firestore_admin.SERVER_TIMESTAMP,
        "chat_id": chat_id,
    }

    db.collection("chats").document(chat_id).collection("messages").add(store_message_data)
    emit("chat_message", live_message_data, room=chat_id)
    enforce_message_limit(chat_id)


def enforce_message_limit(chat_id, limit=10):
    messages_ref = db.collection("chats").document(chat_id).collection("messages")
    messages = list(messages_ref.order_by("timestamp").get())  # WAS: .stream()
    if len(messages) > limit:
        num_to_delete = len(messages) - limit
        for i in range(num_to_delete):
            messages[i].reference.delete()


if __name__ == "__main__":
    socketio.run(app, debug=True)
