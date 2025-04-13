from ml_model.model import predict_image
from flask import jsonify, request
@app.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['file']
    label = predict_image(file)
    return jsonify({'label': label})
