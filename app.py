# app.py
import os
import openai
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit
import firebase_admin
from firebase_admin import credentials, auth, firestore
import requests
from flask import jsonify
from dotenv import load_dotenv
import base64

load_dotenv()
openai.api_key = os.environ.get('OPENAI_API_KEY')

cred = credentials.Certificate('firebase_key.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

issues = [
    {
        'id': 1,
        'title': 'Mold on ceiling',
        'description': 'Been here for 2 weeks',
        'tenant': 'tenant1',
        'landlord': 'landlord1',
        'status': 'Pending'
    },
    {
        'id': 2,
        'title': 'Water leak in kitchen',
        'description': 'Leak under sink',
        'tenant': 'tenant2',
        'landlord': 'landlord1',
        'status': 'Pending'
    },
    # Add more issues here for testing
]

# App routes
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

        try:
            user = auth.create_user(email=email, password=password)

            db.collection('users').document(user.uid).set({
                'email': email,
                'role': role,
            })
            
            # Auto-login: Set session immediately
            session['username'] = email
            session['role'] = role

            # Redirect to the right dashboard
            if role == 'tenant':
                return redirect(url_for('tenant_dashboard'))
            else:
                return redirect(url_for('landlord_dashboard'))

        except Exception as e:
            return f"Error creating user: {e}"

    return render_template('signup.html')

#add routes that listens for POST requests at /upload-image. 
#returns in an JSON format
@app.route('/upload-image', methods=['POST'])
def upload_image():
    # Check if the POST request actually includes a file
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']

    # The URL of the model server that will predict the result
    model_server_url = 'http://localhost:5000/predict'  # Your model server URL
    try:
        # Send the uploaded file to the model server
        response = requests.post(
            model_server_url,
            files={'file': (file.filename, file.stream, file.mimetype)}
        )

        # If the model server responded successfully (HTTP 200 OK)
        if response.status_code == 200:
            # Parse prediction from model server
            prediction = response.json()
            label = prediction.get('label')
            confidence = prediction.get('confidence')

            file.stream.seek(0)  # reset file stream before reusing
            advice = get_ai_advice_with_image(file)

            # Return the prediction result to the user in a nice format
            return jsonify({
                'analysis': f"{label} ({confidence:.2f} confidence)",
                'advice': advice
                })
        else:
            return jsonify({'error': 'Failed to get prediction'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

def check_openai_balance():
    try:
        response = openai.Billing.retrieve()
        hard_limit_usd = response.get('hard_limit_usd', 0)
        total_usage_usd = response.get('total_usage', 0)

        remaining_balance = hard_limit_usd - (total_usage_usd / 100)
        return remaining_balance
    except Exception as e:
        print(f"Failed to check OpenAI balance: {e}")
        return None
    
def get_ai_advice_with_image(file):
    balance = check_openai_balance()
    if balance is not None and balance < 0.50:
        return "AI advice not available at the moment. Please contact support."

    try:
        # Convert file to base64
        file_bytes = file.read()
        base64_image = base64.b64encode(file_bytes).decode('utf-8')

        response = openai.ChatCompletion.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Give a short friendly advice based on this apartment issue image."},
                        {
                            "type": "image",
                            "image": {
                                "base64": base64_image,
                                "mime_type": file.mimetype  # example: 'image/jpeg'
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )

        advice = response['choices'][0]['message']['content']
        return advice

    except Exception as e:
        print(f"OpenAI Vision error: {e}")
        return "AI image advice could not be generated at this time."

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        role = request.form['role']

        # Get user by email
        try:
            user = auth.get_user_by_email(email)
            user_data = db.collection('users').document(user.uid).get().to_dict()

            if user_data['role'] != role:
                return "Incorrect role selected"

            session['username'] = email
            session['role'] = role

            if role == 'tenant':
                return redirect(url_for('tenant_dashboard'))
            else:
                return redirect(url_for('landlord_dashboard'))

        except Exception as e:
            return f"Login failed: {e}"

    return render_template('login.html')

@app.route('/tenant/dashboard')
def tenant_dashboard():
    if 'username' not in session or session.get('role') != 'tenant':
        return redirect(url_for('login'))

    user_issues = [issue for issue in issues if issue['tenant'] == session['username']]
    return render_template('tenant_dashboard.html', issues=user_issues)


@app.route('/landlord/dashboard')
def landlord_dashboard():
    if 'username' not in session or session.get('role') != 'landlord':
        return redirect(url_for('login'))

    user_issues = [issue for issue in issues if issue['landlord'] == session['username']]
    return render_template('landlord_dashboard.html', issues=user_issues)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route


@socketio.on('join')
def on_join(data):
    room = data.get('room')
    join_room(room)
    username = data.get('username')
    # Notify others in the room that a new user has joined
    emit('message', {'username': 'System', 'msg': f'{username} has joined the chat.'}, room=room)

@socketio.on('message')
def handle_message(data):
    room = data.get('room')
    # Broadcast the received message to all users in the room
    emit('message', data, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)
