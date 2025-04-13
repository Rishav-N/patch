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
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"text": f" : {label}."}]
        )
        return response.text.strip()
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

        advice = get_ai_advice_from_label(label)

        full_message = f"Issue detected: {label}.\nAdvice: {advice}"

        message_data = {
            'sender': 'AI Assistant',
            'message': full_message,
            'type': 'analysis',
            'timestamp': firestore.SERVER_TIMESTAMP,
            'chat_id': chat_id
        }
        db.collection('chats').document(chat_id).collection('messages').add(message_data)


        # Return label + optional static image URL
        image_url = f'/static/uploads/{file.filename}'  # Optional if you want to store image long-term

        return jsonify({'success': True, 'label': label, 'image_url': image_url})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/addIssue', methods=['POST'])
def add_issue():
    """
    Expects a JSON payload with a key 'label'. The currently logged-in user
    is retrieved from the session and added to the issue. This endpoint creates
    a new issue document in Firestore with the label, the current user as the tenant,
    and sets the status to 'pending'.
    """
    try:
        # Get JSON data from the request.
        data = request.get_json(force=True)
        label = data.get("label")
        
        if not label:
            return jsonify({"success": False, "error": "Missing 'label' field"}), 400

        # Retrieve the current user from the session.
        # You can store the user identifier in session when the user logs in.
        current_user = session.get("uid")  # or session.get("current_user"), as appropriate.
        if not current_user:
            return jsonify({"success": False, "error": "User not logged in"}), 400

        # Prepare the data to be stored as an issue.
        issue_data = {
            "label": label,
            "tenant": current_user,  # Adding the current user from the session as the tenant.
            "status": "pending"
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
