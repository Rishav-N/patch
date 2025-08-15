from ml_model.model import predict_image
from flask import Blueprint, jsonify, request

model_bp = Blueprint('utils', __name__, template_folder='templates')

@model_bp.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['file']
    label = predict_image(file)
    return jsonify({'label': label})
