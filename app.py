# app.py
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit
import firebase_admin
from firebase_admin import credentials, auth, firestore
import requests
from flask import jsonify


cred = credentials.Certificate('firebase_key.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

# -----------------------------
# Helper functions
# -----------------------------
def get_chat_id(landlord_uid, tenant_uid):
    """Generate a unique chat room ID based on landlord and tenant UIDs."""
    return f"{landlord_uid}_{tenant_uid}"

def enforce_message_limit(chat_id, limit=10):
    """Keep only the last `limit` messages in a chat room by deleting the oldest ones."""
    messages_ref = db.collection('chats').document(chat_id).collection('messages')
    messages = list(messages_ref.order_by('timestamp').stream())
    if len(messages) > limit:
        num_to_delete = len(messages) - limit
        for i in range(num_to_delete):
            messages[i].reference.delete()

# -----------------------------
# Routes for signup, login, home, logout
# -----------------------------
@app.route('/')
def home():
    if 'username' in session and 'role' in session:
        if session.get('role') == 'tenant':
            return redirect(url_for('tenant_dashboard'))
        elif session.get('role') == 'landlord':
            return redirect(url_for('dashboard_landlord'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        try:
            # Create user in Firebase Authentication.
            user = auth.create_user(email=email, password=password)
            # Store user in Firestore using UID as the document ID.
            db.collection('users').document(user.uid).set({
                'email': email,
                'role': role,
            })

            return redirect(url_for('login'))

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

            # Return the prediction result to the user in a nice format
            return jsonify({'analysis': f"{label} ({confidence:.2f} confidence)"})
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
        email = request.form['username']
        password = request.form['password']  # Password validation not shown.
        try:
            user = auth.get_user_by_email(email)
            user_data = db.collection('users').document(user.uid).get().to_dict()
            if not user_data:
                return "User data not found, please sign up."
            session['username'] = email
            session['role'] = user_data.get('role')
            session['uid'] = user.uid
            if session.get('role') == 'tenant':
                return redirect(url_for('tenant_dashboard'))
            elif session.get('role') == 'landlord':
                return redirect(url_for('dashboard_landlord'))
            else:
                return "Unknown user role."
        except Exception as e:
            return f"Login failed: {e}"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -----------------------------
# Dashboard Routes (non-chat)
# -----------------------------
@app.route('/tenant/dashboard')
def tenant_dashboard():
    if 'username' not in session or session.get('role') != 'tenant':
        return redirect(url_for('login'))
    tenant_email = session.get('username')
    tenant_uid = session.get('uid')
    # Query pending requests.
    requests_query = db.collection('requests') \
                        .where('tenant_email', '==', tenant_email) \
                        .where('status', '==', 'pending') \
                        .stream()
    requests_list = []
    for doc in requests_query:
        req = doc.to_dict()
        req['id'] = doc.id
        requests_list.append(req)
    tenant_doc = db.collection('users').document(tenant_uid).get().to_dict()
    current_landlord = tenant_doc.get('landlord') if tenant_doc and 'landlord' in tenant_doc else None
    current_landlord_uid = tenant_doc.get('landlord_uid') if tenant_doc and 'landlord_uid' in tenant_doc else None
    return render_template('tenant_dashboard.html', requests=requests_list, current_landlord=current_landlord, current_landlord_uid=current_landlord_uid)

@app.route('/landlord/dashboard')
def dashboard_landlord():
    if 'username' in session and session.get('role') == 'landlord':
        landlord_uid = session.get('uid')
        tenants_ref = db.collection('users').document(landlord_uid).collection('tenants')
        tenants_docs = tenants_ref.stream()
        tenants = []
        for doc in tenants_docs:
            tenant = doc.to_dict()
            tenant['uid'] = doc.id
            tenants.append(tenant)
        return render_template('landlord_dashboard.html', tenants=tenants)
    else:
        flash("You must be logged in as a landlord to access that page.", "danger")
        return redirect(url_for('login'))

# -----------------------------
# Chat Routes
# -----------------------------

@app.route('/chat') 
def chat():
    if 'username' not in session:
       return redirect(url_for('login'))
    if session.get('role') == 'tenant':
       return redirect(url_for('tenant_chat'))
    elif session.get('role') == 'landlord':
       return redirect(url_for('landlord_chat'))
    else:
       return redirect(url_for('login'))

@app.route('/tenant/chat')
def tenant_chat():
    # Only accessible for tenant.
    if 'username' not in session or session.get('role') != 'tenant':
        return redirect(url_for('login'))
    tenant_uid = session.get('uid')
    tenant_doc = db.collection('users').document(tenant_uid).get().to_dict()
    # current_landlord and its uid are assumed stored in tenant's doc if attached.
    current_landlord = tenant_doc.get('landlord') if tenant_doc else None
    current_landlord_uid = tenant_doc.get('landlord_uid') if tenant_doc and 'landlord_uid' in tenant_doc else None
    return render_template('tenant_chat.html', current_landlord=current_landlord, current_landlord_uid=current_landlord_uid)

@app.route('/landlord/chat')
def landlord_chat():
    # Only accessible for landlord.
    if 'username' not in session or session.get('role') != 'landlord':
        return redirect(url_for('login'))
    landlord_uid = session.get('uid')
    # Retrieve list of attached tenants.
    tenants_ref = db.collection('users').document(landlord_uid).collection('tenants')
    tenants_docs = tenants_ref.stream()
    tenants = []
    for doc in tenants_docs:
        t = doc.to_dict()
        t['uid'] = doc.id
        tenants.append(t)
    return render_template('landlord_chat.html', tenants=tenants)

@app.route('/load_chat/<chat_id>')
def load_chat(chat_id):
    try:
        messages_ref = db.collection('chats').document(chat_id).collection('messages')
        # Query last 10 messages (ordered by timestamp descending) and then reverse them.
        messages_query = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        messages = []
        for doc in messages_query:
            msg = doc.to_dict()
            # Optionally, format the timestamp here.
            messages.append(msg)
        messages.reverse()  # oldest first
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})

@app.route('/upload_image', methods=['POST'])
def upload_image():
    # This is a placeholder implementation.
    chat_id = request.args.get('chat_id')
    file = request.files.get('file')
    if file:
        # Here you would save the file to Firebase Storage or another hosting service.
        # For now, we simulate a successful upload by returning a dummy URL.
        image_url = "https://via.placeholder.com/150"  # Replace with actual image URL.
        return jsonify({"success": True, "image_url": image_url})
    return jsonify({"success": False, "error": "No file uploaded"})

# -----------------------------
# Request Route
# -----------------------------
@app.route('/accept-request/<request_id>')
def accept_request(request_id):
    if 'username' in session and session.get('role') == 'tenant':
        tenant_email = session.get('username')
        tenant_uid = session.get('uid')
        try:
            request_ref = db.collection('requests').document(request_id)
            request_doc = request_ref.get()
            if request_doc.exists:
                req_data = request_doc.to_dict()
                if req_data.get('tenant_email') == tenant_email and req_data.get('status') == 'pending':
                    request_ref.update({'status': 'accepted'})
                    landlord_uid = req_data.get('landlord_uid')
                    if not landlord_uid:
                        flash("Landlord UID missing in request.", "danger")
                        return redirect(url_for('tenant_dashboard'))
                    # Add tenant to landlord's 'tenants' subcollection.
                    db.collection('users').document(landlord_uid).collection('tenants').document(tenant_uid).set({
                        'email': tenant_email,
                        'attached_at': firestore.SERVER_TIMESTAMP
                    })
                    # Update tenant's document with associated landlord.
                    db.collection('users').document(tenant_uid).update({
                        'landlord': req_data.get('landlord_email'),
                        'landlord_uid': landlord_uid
                    })
                    flash("Request accepted. You are now attached to your landlord.", "success")
                else:
                    flash("Request is no longer available or invalid.", "warning")
            else:
                flash("Request not found.", "danger")
        except Exception as e:
            flash(f"Error accepting request: {e}", "danger")
        return redirect(url_for('tenant_dashboard'))
    flash("Unauthorized access", "danger")
    return redirect(url_for('login'))

@app.route('/send-request', methods=['POST'])
def send_request():
    if 'username' in session and session.get('role') == 'landlord':
        tenant_email = request.form.get('tenant_email')
        landlord_email = session.get('username')
        landlord_uid = session.get('uid')
        
        print("Landlord:", landlord_email, "is sending a request to tenant:", tenant_email)
        
        if not tenant_email:
            flash("Tenant email is missing.", "danger")
            return redirect(url_for('dashboard_landlord'))
        
        # Prepare the email.
        subject = "Request from your Landlord"
        body = "You have received a request from your landlord. Please log in to your dashboard to view the request."
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = landlord_email  # Ideally, use a valid sender email.
        msg['To'] = tenant_email

        try:
            smtp = smtplib.SMTP('smtp.gmail.com', 587)
            smtp.starttls()
            smtp.login(os.environ.get('GMAIL_USER'), os.environ.get('GMAIL_PASSWORD'))
            smtp.sendmail(landlord_email, [tenant_email], msg.as_string())
            smtp.quit()
            print("Email sent successfully to", tenant_email)
            
            # Create the request in Firestore including the landlord's UID.
            result = db.collection('requests').add({
                'tenant_email': tenant_email,
                'landlord_email': landlord_email,
                'landlord_uid': landlord_uid,
                'status': 'pending',
                'timestamp': firestore.SERVER_TIMESTAMP
            })
            print("Firestore request added with document ID:", result[1].id)
            
            flash("Request sent successfully!", "success")
        except Exception as e:
            print("Error sending request:", e)
            flash(f"Error sending request: {e}", "danger")
    else:
        flash("Unauthorized access", "danger")
    
    return redirect(url_for('dashboard_landlord'))

# -----------------------------
# Socket.IO Events
# -----------------------------
@socketio.on('join_chat')
def join_chat(data):
    chat_id = data.get('chat_id')
    join_room(chat_id)
    emit('chat_message', {'sender': 'System', 'message': f"Joined chat room: {chat_id}", 'chat_id': chat_id}, room=chat_id)

import datetime  # add at the top if not already imported

@socketio.on('send_chat_message')
def handle_send_chat_message(data):
    chat_id = data.get('chat_id')
    sender = data.get('sender')
    message = data.get('message')
    msg_type = data.get('type', "text")
    
    # Use UTC time for live broadcast (JSON serializable)
    live_timestamp = datetime.datetime.utcnow().isoformat()
    
    # Create message data for live broadcast (without the Firestore sentinel)
    live_message_data = {
        'sender': sender,
        'message': message,
        'type': msg_type,
        'timestamp': live_timestamp,
        'chat_id': chat_id
    }
    
    # Data to store in Firestore (using SERVER_TIMESTAMP)
    store_message_data = {
        'sender': sender,
        'message': message,
        'type': msg_type,
        'timestamp': firestore.SERVER_TIMESTAMP,
        'chat_id': chat_id
    }
    
    # Save the message in Firestore under chats/{chat_id}/messages.
    db.collection('chats').document(chat_id).collection('messages').add(store_message_data)
    
    # Broadcast the new message to all users in the room.
    emit('chat_message', live_message_data, room=chat_id)
    
    # Enforce that only the last 10 messages are kept.
    enforce_message_limit(chat_id)



# -----------------------------
# Run the App
# -----------------------------
if __name__ == '__main__':
    socketio.run(app, debug=True)
