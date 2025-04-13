# profile.py
from flask import Blueprint, render_template, redirect, url_for, session, flash, request
from firebase_admin import firestore
from werkzeug.security import generate_password_hash



profile_bp = Blueprint('profilepage', __name__, template_folder='templates')
db = firestore.client()


@profile_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    # Ensure user is logged in.
    if 'uid' not in session:
        flash("Please login to access your profile.", "warning")
        return redirect(url_for('auth.login'))
    
    user_id = session.get('uid')
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        flash("User data not found.", "danger")
        return redirect(url_for('auth.login'))
    
    user_data = user_doc.to_dict()

    if request.method == 'POST':
        # Get form data.
        updated_username = request.form.get('username')
        updated_email = request.form.get('email')
        updated_password = request.form.get('password')
        updated_state = request.form.get('state')
        updated_country = request.form.get('country')
        
        # Prepare update dictionary.
        updates = {
            'username': updated_username,
            'email': updated_email,
            'state': updated_state,
            'country': updated_country,
        }
        
        # If the password field is not empty, update the password.
        if updated_password:
            # Hash the new password before storing if you're managing password updates manually.
            # However, if using Firebase Authentication, update password using its dedicated method.
            hashed_password = generate_password_hash(updated_password)
            updates['password'] = hashed_password
        
        # Update Firestore document.
        user_ref.update(updates)
        flash("Profile updated successfully!", "success")
        return redirect(url_for('profilepage.profile'))
    
    # Pass the current user data into the template.
    return render_template("profile.html", user=user_data)
