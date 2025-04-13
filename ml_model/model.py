import torch
import torchvision.transforms as transforms
from PIL import Image

model = torch.load('resnet18_model.pth', map_location=torch.device('cpu'))
model.eval()

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
])

def predict_image(image_file):
    img = Image.open(image_file).convert('RGB')
    img = transform(img).unsqueeze(0)

    with torch.no_grad():
        output = model(img)
        _, predicted = torch.max(output, 1)

    classes = ['mold', 'pest', 'structural_damage']  
    label = classes[predicted.item()]
    return label
