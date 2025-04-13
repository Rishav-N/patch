#server.py
from flask import Flask, request, jsonify
from tensorflow.keras.models import load_model
from tensorflow.keras.applications.mobilenet import preprocess_input, decode_predictions
from PIL import Image
import numpy as np
import os

# Initialize Flask app
app = Flask(__name__)

@app.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']

    # Choose which prediction method you want
    model_to_use = request.args.get('model', 'pytorch')  # default is pytorch, can send ?model=roboflow

    if model_to_use == 'roboflow':
        label, confidence = predict_roboflow_image(file)
    else:
        label = predict_pytorch_image(file)
        confidence = None  # your PyTorch model doesn't output confidence directly

    result = {'label': label}
    if confidence is not None:
        result['confidence'] = confidence

    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)