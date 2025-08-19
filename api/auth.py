from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
import firebase_admin
from firebase_admin import auth  # keep admin auth; don't rebuild Firestore here

auth_bp = Blueprint("auth", __name__, template_folder="templates")

def get_db():
    # Reuse the client created in api/index.py:
    # app.config["DB"] is set there to the REST Firestore client.
    return current_app.config["DB"]

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
            user = auth.create_user(email=email, password=password)
            get_db().collection("users").document(user.uid).set({
                "email": email,
                "role": role,
            })
            return redirect(url_for("auth.login"))
        except Exception as e:
            # Optionally use flash() to show on page
            return f"Error creating user: {e}"
    return render_template("signup.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["username"]
        password = request.form["password"]  # NOTE: you're not verifying this server-side
        try:
            user = auth.get_user_by_email(email)
            snap = get_db().collection("users").document(user.uid).get()
            user_data = snap.to_dict() if snap.exists else None
            if not user_data:
                return "User data not found, please sign up."

            # Set session
            session["username"] = email
            session["role"] = user_data.get("role")
            session["uid"] = user.uid

            if session.get("role") == "tenant":
                return redirect(url_for("tenant.tenant_dashboard"))
            elif session.get("role") == "landlord":
                return redirect(url_for("landlord.dashboard_landlord"))
            else:
                return "Unknown user role."
        except Exception as e:
            return f"Login failed: {e}"
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
