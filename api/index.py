# api/index.py
import os, sys, json, tempfile, datetime
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, redirect, url_for
import firebase_admin
from firebase_admin import credentials, firestore
from inference_sdk import InferenceHTTPClient
from google import genai

# Make parent folder importable (so blueprints at repo root work when this file is under /api)
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# ---- Secrets & clients ----
load_dotenv()

# Firebase Admin: read service account JSON from ENV (DO NOT use a file path on Vercel)
sa_json = os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
cred = credentials.Certificate(json.loads(sa_json))
firebase_admin.initialize_app(cred)
db = firestore.client()

# Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Flask
app = Flask(
    __name__,
    static_folder="../static",          # serve static from repo /static
    template_folder="../templates"      # in case your blueprints render templates
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-in-env")

# Roboflow (moved key to ENV)
rf_client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=os.getenv("ROBOFLOW_API_KEY", "")  # set in the platform
)

# ---- Blueprints (must exist at repo root): auth.py, tenant.py, landlord.py, profilepage.py ----
from auth import auth_bp
from tenant import tenant_bp
from landlord import landlord_bp
from profilepage import profile_bp

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
            f"- Clearly state possible legal consequences (withholding rent, small claims court, health dept.)\n"
            f"- Be written in a formal, professional tone\n"
            f"- Assume the tenant wants to stay polite but firm\n\n"
            f"Output the complete legal letter ready to be copied and sent."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}]
        )
        return (getattr(response, "text", None) or "").strip()
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "Unable to generate advice at the moment."


def get_ai_days_from_label(state, label):
    try:
        prompt = (
            "Act as a legal expert specializing in housing and tenant rights. "
            "Determine the statutory period—the number of days a landlord has to fix an issue "
            "before a tenant can file a legal claim—based on state law.\n"
            f"State: {state}\nIssue: {label}\n"
            "Provide ONLY one integer (days)."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}]
        )
        value = (getattr(response, "text", None) or "").strip()
        return int(value)
    except Exception as e:
        print(f"Gemini API error: {e}")
        return 7  # safe default


@app.route("/upload_image", methods=["POST"])
def upload_image():
    chat_id = request.args.get("chat_id")  # currently unused but kept for compatibility

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
    Expects JSON with 'label'. Reads user uid from session, fetches state from Firestore,
    generates AI advice + days, and stores an issue doc.
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
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        db.collection("issues").add(issue_data)

        return jsonify({"success": True, "label": label, "tenant": current_user}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/load_chat/<chat_id>")
def load_chat(chat_id):
    try:
        messages_ref = (
            db.collection("chats")
              .document(chat_id)
              .collection("messages")
        )
        messages_query = (
            messages_ref
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(10)
            .stream()
        )
        messages = [doc.to_dict() for doc in messages_query]
        messages.reverse()
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})


# No Socket.IO in serverless (Vercel Python) — use HTTP endpoints + Firestore listeners on the client.


# Local dev convenience (ignored by Vercel)
if __name__ == "__main__":
    app.run(port=5000, debug=True)
