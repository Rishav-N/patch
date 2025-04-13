# app.py
import os
import datetime
from google import genai
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, redirect, url_for
from flask_socketio import SocketIO, join_room, emit
import firebase_admin
from firebase_admin import credentials, firestore
from inference_sdk import InferenceHTTPClient

# Initialize Firebase
cred = credentials.Certificate('firebase_key.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

load_dotenv()
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

# Roboflow Client
rf_client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="OMzWXPHBONpUpBxpEqDG"  # replace with your real API key
)

# Blueprints
from auth import auth_bp
from tenant import tenant_bp
from landlord import landlord_bp

app.register_blueprint(auth_bp)
app.register_blueprint(tenant_bp)
app.register_blueprint(landlord_bp)


# Route: Role-Based Chat Redirection
@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('auth.login'))
    if session.get('role') == 'tenant':
        return redirect(url_for('tenant.tenant_chat'))
    elif session.get('role') == 'landlord':
        return redirect(url_for('landlord.landlord_chat'))
    return redirect(url_for('auth.login'))


# Helper function to get advice from OpenAI
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
            f"- Clearly state possible legal consequences (such as withholding rent, small claims court, health department complaints) "
            f"if the landlord fails to act\n"
            f"- Be written in a formal, professional tone\n"
            f"- Assume the tenant wants to stay polite but firm\n\n"
            f"Output the complete legal letter ready to be copied and sent."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}]
        )
        
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "Unable to generate advice at the moment."

# Helper function to get advice from OpenAI
def get_ai_days_from_label(state, label):
    try:
        prompt = (
            f"Act as a legal expert specializing in housing and tenant rights. I need you to determine"
            f"the statutory period—the number of days a landlord has to fix an issue in a rented living "
            f"space before a tenant can file a legal claim—based on state law."
            f"State: {state} Issue: {label}"
            f"Please provide: "
            f"1. The specific number of days (or the range of days) the law grants for the landlord "
            f"to address this issue before a legal claim can be filed."
            f"Output the answer AS ONE INTEGER NOTHING MORE NOTHING LESS" 
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": prompt}]
        )
        
        return int(response.text.strip())
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "Unable to generate advice at the moment."
    
# Route: Upload Image -> Run Model -> Return Label
@app.route('/upload_image', methods=['POST'])
def upload_image():
    chat_id = request.args.get('chat_id')

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})

    file = request.files['file']
    temp_dir = 'temp_uploads'
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)

    try:
        # Roboflow Classification
        prediction = rf_client.infer(temp_path, model_id="classification-house-problems/1")
        label = prediction['predictions'][0]['class'] if prediction['predictions'] else "Unknown"

        print(f"Inferred Label: {label}")

        # Clean up
        os.remove(temp_path)
        current_user = session.get('username')
        state = session.get('state')  


        return jsonify({
            'success': True,
            'label': label
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/addIssue', methods=['POST'])
def add_issue():
    """
    Expects a JSON payload with a key 'label'. Retrieves the current user's uid from the session,
    fetches additional user details (e.g. state) from Firestore, and uses the data along with the label
    to generate legal advice using get_ai_advice_from_label. The resulting advice is stored with the
    issue along with tenant and status.
    """
    try:
        # Get JSON data from the request.
        data = request.get_json(force=True)
        label = data.get("label")
        
        if not label:
            return jsonify({"success": False, "error": "Missing 'label' field"}), 400

        # Retrieve the current user from the session.
        current_user = session.get("uid")
        if not current_user:
            return jsonify({"success": False, "error": "User not logged in"}), 400

        # Retrieve additional details (like state and username) about the current user from Firestore.
        user_doc = db.collection('users').document(current_user).get()
        if not user_doc.exists:
            return jsonify({"success": False, "error": "User data not found"}), 404
        user_data = user_doc.to_dict()
        state = user_data.get("state")
        username = user_data.get("username", current_user)

        if not state:
            return jsonify({"success": False, "error": "User state not found"}), 400

        # Get AI advice using the helper function.
        ai_advice = get_ai_advice_from_label(username, state, label)
        num_days = get_ai_days_from_label(state, label)

        # Prepare the data to be stored as an issue.
        issue_data = {
            "label": label,
            "tenant": current_user,  # current user as the tenant
            "status": "pending",
            "ai_advice": ai_advice,
            "days": num_days
        }

        # Add the issue to the 'issues' collection in Firestore.
        db.collection("issues").add(issue_data)

        # Return success response.
        return jsonify({"success": True, "label": label, "tenant": current_user}), 200

    except Exception as e:
        # In case of error, return a failure response with error message.
        return jsonify({"success": False, "error": str(e)}), 500



# Route: Load Chat Messages
@app.route('/load_chat/<chat_id>')
def load_chat(chat_id):
    try:
        messages_ref = db.collection('chats').document(chat_id).collection('messages')
        messages_query = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        messages = [doc.to_dict() for doc in messages_query]
        messages.reverse()
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})


# Socket.IO: Chat Join
@socketio.on('join_chat')
def join_chat(data):
    chat_id = data.get('chat_id')
    join_room(chat_id)
    emit('chat_message', {'sender': 'System', 'message': f"Joined chat room: {chat_id}", 'chat_id': chat_id}, room=chat_id)
     
# Socket.IO: Send Chat Message
@socketio.on('send_chat_message')
def handle_send_chat_message(data):
    chat_id = data.get('chat_id')
    sender = data.get('sender')
    message = data.get('message')
    msg_type = data.get('type', "text")

    live_timestamp = datetime.datetime.utcnow().isoformat()

    live_message_data = {
        'sender': sender,
        'message': message,
        'type': msg_type,
        'timestamp': live_timestamp,
        'chat_id': chat_id
    }

    store_message_data = {
        'sender': sender,
        'message': message,
        'type': msg_type,
        'timestamp': firestore.SERVER_TIMESTAMP,
        'chat_id': chat_id
    }

    db.collection('chats').document(chat_id).collection('messages').add(store_message_data)
    emit('chat_message', live_message_data, room=chat_id)
    enforce_message_limit(chat_id)


def enforce_message_limit(chat_id, limit=10):
    messages_ref = db.collection('chats').document(chat_id).collection('messages')
    messages = list(messages_ref.order_by('timestamp').stream())
    if len(messages) > limit:
        num_to_delete = len(messages) - limit   
        for i in range(num_to_delete):
            messages[i].reference.delete()

if __name__ == '__main__':
    socketio.run(app, debug=True)
