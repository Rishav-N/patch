import os
import time
import eventlet
import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from firebase_admin import auth as admin_auth

auth_bp = Blueprint("auth", __name__, template_folder="templates")

API_KEY = os.environ.get("FIREBASE_WEB_API_KEY")  # set this in Render

def get_db():
    return current_app.config["DB"]

def _timed(label):
    t0 = time.perf_counter()
    def done():
        dt = (time.perf_counter() - t0) * 1000
        print(f"[auth] {label} in {dt:.1f}ms")
    return done

def sign_in_with_password(email: str, password: str, timeout_sec: int = 8):
    """
    Firebase Identity Toolkit REST sign-in. Returns localId (uid) on success.
    Raises ValueError with friendly message on auth failure.
    """
    if not API_KEY:
        raise RuntimeError("FIREBASE_WEB_API_KEY is not set")

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}

    done = _timed("identitytoolkit.signInWithPassword")
    # Hard stop if Google hangs
    with eventlet.Timeout(timeout_sec, False):
        r = requests.post(url, json=payload, timeout=timeout_sec)
    if r is None:
        raise TimeoutError("Auth timeout")
    done()

    if r.status_code == 200:
        data = r.json()
        # data has idToken, refreshToken, localId (uid), etc.
        return data["localId"]
    else:
        try:
            err = r.json().get("error", {})
            msg = (err.get("message") or "AUTH_ERROR").replace("_", " ").title()
        except Exception:
            msg = f"Auth error {r.status_code}"
        raise ValueError(msg)

@auth_bp.route("/")
def home():
    if "username" in session and "role" in session:
        if session.get("role") == "tenant":
            return redirect(url_for("tenant.tenant_dashboard"))
        elif session.get("role") == "landlord":
            return redirect(url_for("landlord.dashboard_landlord"))
    return redirect(url_for("auth.login"))

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]
        try:
            # Create the Firebase Auth user (wrap in short timeout so we don't hang)
            with eventlet.Timeout(12, False):
                user = admin_auth.create_user(email=email, password=password)
            if "user" not in locals():
                return "Signup timeout, try again.", 504

            get_db().collection("users").document(user.uid).set({
                "email": email,
                "role": role,
            })
            flash("Account created. Please log in.", "success")
            return redirect(url_for("auth.login"))
        except Exception as e:
            return f"Error creating user: {e}", 400
    return render_template("signup.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            return "Email and password required.", 400

        # 1) Real auth (validates password) via REST; fast and reliable with eventlet
        try:
            uid = sign_in_with_password(email, password, timeout_sec=8)
        except TimeoutError:
            return "Auth service timed out. Please try again.", 504
        except ValueError as ve:
            return f"Login failed: {ve}", 401
        except Exception as e:
            return f"Auth error: {e}", 502

        # 2) Load the user's role/profile from Firestore with a strict timeout
        try:
            with eventlet.Timeout(8, False):
                snap = get_db().collection("users").document(uid).get()
            if snap is None:
                return "User data timeout.", 504
            user_data = snap.to_dict() if snap.exists else None
            if not user_data:
                return "User data not found, please sign up.", 404
        except Exception as e:
            return f"Firestore error: {e}", 502

        # 3) Set session and redirect
        session["username"] = email
        session["role"] = user_data.get("role")
        session["uid"] = uid

        if session["role"] == "tenant":
            return redirect(url_for("tenant.tenant_dashboard"))
        elif session["role"] == "landlord":
            return redirect(url_for("landlord.dashboard_landlord"))
        return "Unknown user role.", 400

    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
