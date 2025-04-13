# ml_model/roboflow_client.py

from inference_sdk import InferenceHTTPClient
import os

# Initialize Roboflow Client
CLIENT = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="OMzWXPHBONpUpBxpEqDG"
)

# Predict Image Function
def predict_image(file):
    temp_path = "temp_upload.jpg"  # Temp save location
    file.save(temp_path)  # Save incoming file
q
    result = CLIENT.infer(temp_path, model_id="classification-house-problems/1")

    # Clean up: Delete temp file
    os.remove(temp_path)

    label = result['predictions'][0]['class'] if result.get('predictions') else "Unknown"
    confidence = result['predictions'][0]['confidence'] if result.get('predictions') else 0

    return label, confidence
