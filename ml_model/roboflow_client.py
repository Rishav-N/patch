from inference_sdk import InferenceHTTPClient
import os

CLIENT = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="OMzWXPHBONpUpBxpEqDG"
)

def predict_image(file):
    temp_path = "temp_upload.jpg"  
    file.save(temp_path)  

    result = CLIENT.infer(temp_path, model_id="classification-house-problems/1")

    os.remove(temp_path)

    label = result['predictions'][0]['class'] if result.get('predictions') else "Unknown"
    confidence = result['predictions'][0]['confidence'] if result.get('predictions') else 0

    return label, confidence
