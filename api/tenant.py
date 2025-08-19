import os
from flask import Blueprint, render_template, redirect, url_for, session, flash, jsonify, request, current_app, send_file, abort
import firebase_admin
from firebase_admin import firestore
from io import BytesIO
from docx import Document

from inference_sdk import InferenceHTTPClient

tenant_bp = Blueprint('tenant', __name__, template_folder='templates')
db = firestore.client()

rf_client = InferenceHTTPClient(
    api_url="https://detect.roboflow.com",
    api_key=os.getenv("ROBOFLOW_API_KEY"),
)

@tenant_bp.route('/tenant/dashboard')
def tenant_dashboard():
    if 'username' not in session or session.get('role') != 'tenant':
        return redirect(url_for('auth.login'))
    
    tenant_email = session.get('username')
    tenant_uid = session.get('uid')
    
    requests_query = db.collection('requests') \
                       .where('tenant_email', '==', tenant_email) \
                       .where('status', '==', 'pending') \
                       .stream()
    requests_list = []
    for doc in requests_query:
        req = doc.to_dict()
        req['id'] = doc.id
        requests_list.append(req)
    
    issues_query = db.collection('issues') \
                     .where('tenant', '==', tenant_uid) \
                     .stream()
    issues_list = []
    for doc in issues_query:
        issue = doc.to_dict()
        issue['id'] = doc.id
        issues_list.append(issue)
    
    pending_issues = [issue for issue in issues_list if issue.get('status') == 'pending']
    resolved_issues = [issue for issue in issues_list if issue.get('status') == 'resolved']
    
    tenant_doc = db.collection('users').document(tenant_uid).get().to_dict()
    current_landlord = tenant_doc.get('landlord') if tenant_doc and 'landlord' in tenant_doc else None
    current_landlord_uid = tenant_doc.get('landlord_uid') if tenant_doc and 'landlord_uid' in tenant_doc else None
    
    return render_template(
        'tenant_dashboard.html',
        requests=requests_list,
        current_landlord=current_landlord,
        current_landlord_uid=current_landlord_uid,
        pending_issues=pending_issues,
        resolved_issues=resolved_issues
    )

@tenant_bp.route('/tenant/download_report/<issue_id>')
def download_report(issue_id):
    issue_ref = db.collection("issues").document(issue_id)
    issue = issue_ref.get()
    if not issue.exists:
        abort(404, description="Issue not found.")
    issue_data = issue.to_dict()
    
    ai_advice = issue_data.get("ai_advice")
    if not ai_advice:
        abort(404, description="Legal report not available for this issue.")
    
    document = Document()
    document.add_paragraph(ai_advice)
    file_stream = BytesIO()
    document.save(file_stream)
    file_stream.seek(0)
    
    return send_file(
        file_stream,
        as_attachment=True,
        download_name="legal_report.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@tenant_bp.route('/tenant/solve_issue/<issue_id>', methods=['POST'])
def solve_issue(issue_id):
    """
    Updates the specified issue's status to "resolved" for the current tenant.
    """
    tenant_uid = session.get("uid")
    if not tenant_uid:
        return jsonify({"success": False, "error": "User not logged in"}), 401

    try:
        issue_ref = db.collection("issues").document(issue_id)
        issue = issue_ref.get()
        if not issue.exists:
            return jsonify({"success": False, "error": "Issue not found"}), 404

        issue_data = issue.to_dict()
        if issue_data.get("tenant") != tenant_uid:
            return jsonify({"success": False, "error": "Not authorized"}), 403

        issue_ref.update({"status": "resolved"})

        return redirect(url_for('tenant.tenant_dashboard'))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@tenant_bp.route('/tenant/chat')
def tenant_chat():
    if 'username' not in session or session.get('role') != 'tenant':
        return redirect(url_for('auth.login'))
    tenant_uid = session.get('uid')
    tenant_doc = db.collection('users').document(tenant_uid).get().to_dict()
    current_landlord = tenant_doc.get('landlord') if tenant_doc and 'landlord' in tenant_doc else None
    current_landlord_uid = tenant_doc.get('landlord_uid') if tenant_doc and 'landlord_uid' in tenant_doc else None
    return render_template('tenant_chat.html', current_landlord=current_landlord,
                           current_landlord_uid=current_landlord_uid)

@tenant_bp.route('/accept-request/<request_id>')
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
                        return redirect(url_for('tenant.tenant_dashboard'))
                    db.collection('users').document(landlord_uid)\
                      .collection('tenants').document(tenant_uid).set({
                          'email': tenant_email,
                          'attached_at': firestore.SERVER_TIMESTAMP
                      })
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
        return redirect(url_for('tenant.tenant_dashboard'))
    flash("Unauthorized access", "danger")
    return redirect(url_for('auth.login'))