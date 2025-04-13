# app.py
import os
import smtplib
import datetime
import requests
import openai
from dotenv import load_dotenv
from email.mime.text import MIMEText
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, join_room, emit
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase Admin SDK with your service account key.
cred = credentials.Certificate('firebase_key.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

# Register Blueprints
from auth import auth_bp
from tenant import tenant_bp
from landlord import landlord_bp

app.register_blueprint(auth_bp)
app.register_blueprint(tenant_bp)
app.register_blueprint(landlord_bp)

# Global chat route to redirect based on role.
@app.route('/chat')
def chat():
    from flask import session, redirect, url_for
    if 'username' not in session:
        return redirect(url_for('auth.login'))
    if session.get('role') == 'tenant':
        return redirect(url_for('tenant.tenant_chat'))
    elif session.get('role') == 'landlord':
        return redirect(url_for('landlord.landlord_chat'))
    else:
        return redirect(url_for('auth.login'))

@app.route('/load_chat/<chat_id>')
def load_chat(chat_id):
    from flask import jsonify
    try:
        messages_ref = db.collection('chats').document(chat_id).collection('messages')
        messages_query = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        messages = []
        for doc in messages_query:
            msg = doc.to_dict()
            messages.append(msg)
        messages.reverse()
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})
    
# Socket.IO Events
@socketio.on('join_chat')
def join_chat(data):
    chat_id = data.get('chat_id')
    join_room(chat_id)
    emit('chat_message', {'sender': 'System', 'message': f"Joined chat room: {chat_id}", 'chat_id': chat_id}, room=chat_id)

@socketio.on('send_chat_message')
def handle_send_chat_message(data):
    chat_id = data.get('chat_id')
    sender = data.get('sender')
    message = data.get('message')
    msg_type = data.get('type', "text")
    
    # Use UTC time for live broadcast (JSON serializable)
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
