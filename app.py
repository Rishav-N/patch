# app.py
from flask import Flask, render_template
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
