# auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import firebase_admin
from firebase_admin import auth, firestore

auth_bp = Blueprint('auth', __name__, template_folder='templates')
db = firestore.client()

@auth_bp.route('/')
def home():
    if 'username' in session and 'role' in session:
        if session.get('role') == 'tenant':
            return redirect(url_for('tenant.tenant_dashboard'))
        elif session.get('role') == 'landlord':
            return redirect(url_for('landlord.dashboard_landlord'))
    return redirect(url_for('auth.login'))

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        try:
            # Create user in Firebase Authentication.
            user = auth.create_user(email=email, password=password)
            # Store the user in Firestore using the UID as document ID.
            db.collection('users').document(user.uid).set({
                'email': email,
                'role': role,
            })
            return redirect(url_for('auth.login'))
        except Exception as e:
            return f"Error creating user: {e}"
    return render_template('signup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['username']
        password = request.form['password']  # (Password validation is not shown.)
        try:
            user = auth.get_user_by_email(email)
            user_data = db.collection('users').document(user.uid).get().to_dict()
            if not user_data:
                return "User data not found, please sign up."
            # Save email, role, and UID in session.
            session['username'] = email
            session['role'] = user_data.get('role')
            session['uid'] = user.uid
            if session.get('role') == 'tenant':
                return redirect(url_for('tenant.tenant_dashboard'))
            elif session.get('role') == 'landlord':
                return redirect(url_for('landlord.dashboard_landlord'))
            else:
                return "Unknown user role."
        except Exception as e:
            return f"Login failed: {e}"
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
