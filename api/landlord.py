from flask import Blueprint, render_template, redirect, url_for, session, flash, request, current_app
import smtplib, os
from email.mime.text import MIMEText
from firebase_admin import auth, firestore  # keep auth; reuse db from index.py

landlord_bp = Blueprint("landlord", __name__, template_folder="templates")

def get_db():
    return current_app.config["DB"]

@landlord_bp.route("/landlord/dashboard")
def dashboard_landlord():
    if "username" in session and session.get("role") == "landlord":
        landlord_uid = session.get("uid")

        tenants_ref = get_db().collection("users").document(landlord_uid).collection("tenants")
        tenants_docs = tenants_ref.get()  # REST .get() instead of .stream()
        tenants = []
        for doc in tenants_docs:
            t = doc.to_dict()
            t["uid"] = doc.id
            tenants.append(t)

        selected_tenant_email = request.args.get("tenant_email")

        landlord_issues = []
        for tenant in tenants:
            issues_query = get_db().collection("issues").where("tenant", "==", tenant["uid"]).get()
            for doc in issues_query:
                issue = doc.to_dict()
                issue["id"] = doc.id
                issue["tenant_email"] = tenant.get("email")
                landlord_issues.append(issue)

        return render_template(
            "landlord_dashboard.html",
            tenants=tenants,
            landlord_issues=landlord_issues,
            selected_tenant_email=selected_tenant_email
        )
    else:
        flash("You must be logged in as a landlord to access that page.", "danger")
        return redirect(url_for("auth.login"))

@landlord_bp.route("/landlord/chat")
def landlord_chat():
    if "username" not in session or session.get("role") != "landlord":
        return redirect(url_for("auth.login"))
    landlord_uid = session.get("uid")
    tenants_ref = get_db().collection("users").document(landlord_uid).collection("tenants")
    tenants_docs = tenants_ref.get()
    tenants = []
    for doc in tenants_docs:
        t = doc.to_dict()
        t["uid"] = doc.id
        tenants.append(t)
    return render_template("landlord_chat.html", tenants=tenants)

@landlord_bp.route("/send-request", methods=["POST"])
def send_request():
    if "username" in session and session.get("role") == "landlord":
        tenant_email = request.form.get("tenant_email")
        landlord_email = session.get("username")
        landlord_uid = session.get("uid")
        print("Landlord:", landlord_email, "is sending a request to tenant:", tenant_email)

        if not tenant_email:
            flash("Tenant email is missing.", "danger")
            return redirect(url_for("landlord.dashboard_landlord"))

        subject = "Request from your Landlord"
        body = "You have received a request from your landlord. Please log in to your dashboard to view the request."
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = landlord_email
        msg["To"] = tenant_email

        try:
            smtp = smtplib.SMTP("smtp.gmail.com", 587)
            smtp.starttls()
            smtp.login(os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_PASSWORD"))
            smtp.sendmail(landlord_email, [tenant_email], msg.as_string())
            smtp.quit()
            print("Email sent successfully to", tenant_email)

            result = get_db().collection("requests").add({
                "tenant_email": tenant_email,
                "landlord_email": landlord_email,
                "landlord_uid": landlord_uid,
                "status": "pending",
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            print("Firestore request added with document ID:", result[1].id)
            flash("Request sent successfully!", "success")

        except Exception as e:
            print("Error sending request:", e)
            flash(f"Error sending request: {e}", "danger")
    else:
        flash("Unauthorized access", "danger")

    return redirect(url_for("landlord.dashboard_landlord"))
