# app.py
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']
        session['username'] = username
        session['role'] = role

        if role == 'tenant':
            return redirect(url_for('tenant_dashboard'))
        else:
            return redirect(url_for('landlord_dashboard'))

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
