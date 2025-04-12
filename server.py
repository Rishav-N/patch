from flask import Flask, request, jsonify
from tensorflow.keras.models import load_model
from tensorflow.keras.applications.mobilenet import preprocess_input, decode_predictions
from PIL import Image
import numpy as np
import os

# Initialize Flask app
app = Flask(__name__)

# Load the trained MobileNet model
model = load_model('model.h5') #You got to change this

# Make sure upload folder exists
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@app.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    #so
    file = request.files['file']
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    # Preprocess the image
    img = Image.open(filepath).convert('RGB')
    img = img.resize((224, 224))  # MobileNet expects 224x224
    img_array = np.array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)  # Important for MobileNet

    # Predict. Use the model and get the results.
    preds = model.predict(img_array)
    predicted_class = np.argmax(preds[0])
    confidence = float(np.max(preds[0]))

    # You need a label mapping
    class_labels = ['mold', 'water_damage', 'floor_damage']  # Example
    label = class_labels[predicted_class]

    # Clean up uploaded file
    os.remove(filepath)

    # Return prediction
    return jsonify({
        'label': label,
        'confidence': confidence
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)