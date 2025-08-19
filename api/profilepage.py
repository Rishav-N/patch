from flask import Blueprint, render_template, redirect, url_for, session, flash, request, current_app
from werkzeug.security import generate_password_hash

profile_bp = Blueprint("profilepage", __name__, template_folder="templates")

def get_db():
    return current_app.config["DB"]

@profile_bp.route("/profile", methods=["GET", "POST"])
def profile():
    if "uid" not in session:
        flash("Please login to access your profile.", "warning")
        return redirect(url_for("auth.login"))
    
    user_id = session.get("uid")
    user_ref = get_db().collection("users").document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        flash("User data not found.", "danger")
        return redirect(url_for("auth.login"))
    
    user_data = user_doc.to_dict()

    if request.method == "POST":
        updated_username = request.form.get("username")
        updated_email = request.form.get("email")
        updated_password = request.form.get("password")
        updated_state = request.form.get("state")
        updated_country = request.form.get("country")
        
        updates = {
            "username": updated_username,
            "email": updated_email,
            "state": updated_state,
            "country": updated_country,
        }
        
        if updated_password:
            hashed_password = generate_password_hash(updated_password)
            updates["password"] = hashed_password
        
        user_ref.update(updates)
        flash("Profile updated successfully!", "success")
        return redirect(url_for("profilepage.profile"))
    
    return render_template("profile.html", user=user_data)
