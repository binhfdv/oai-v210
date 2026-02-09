from flask import Flask, request, jsonify
import torch, numpy as np, os, json
from python.ORAN_models import TransformerNN, TransformerNN_v2, ConvNN

app = Flask(__name__)
model = None
device = "cpu"
slice_len = None
num_feats = None

@app.route("/load_model", methods=["POST"])
def load_model():
    global model, device, slice_len, num_feats
    data = request.json
    model_type = data["model_type"]    # "Tv1" | "Tv2" | "CNN" | "ViT"
    model_path = data["model_path"]
    Nclass     = int(data.get("Nclass", 4))
    slice_len  = int(data.get("slice_len"))
    num_feats  = int(data.get("num_feats"))

    if model_type == "Tv1":
        model = TransformerNN(classes=Nclass, slice_len=slice_len, num_feats=num_feats, use_pos=False, nhead=1, custom_enc=True)
    elif model_type == "Tv2":
        model = TransformerNN_v2(classes=Nclass, slice_len=slice_len, num_feats=num_feats, use_pos=False, nhead=1, custom_enc=True)
    elif model_type == "CNN":
        model = ConvNN(classes=Nclass, slice_len=slice_len, num_feats=num_feats)
    else:
        return jsonify({"error": "ViT/other not supported"}), 400

    if torch.cuda.is_available():
        device = "cuda"
        state = torch.load(model_path, map_location="cuda:0")["model_state_dict"]
    else:
        device = "cpu"
        state = torch.load(model_path, map_location="cpu")["model_state_dict"]
    model.load_state_dict(state)
    model.to(device)
    model.eval()

    # warm up
    with torch.no_grad():
        x = torch.rand(1, slice_len, num_feats, device=device)
        _ = model(x)

    return jsonify({"status": "ok", "device": device})

@app.route("/predict", methods=["POST"])
def predict():
    global model, device, slice_len, num_feats
    if model is None:
        return jsonify({"error": "model not loaded"}), 400

    window = np.array(request.json["window"], dtype=np.float32)  # [slice_len, num_feats]
    if window.shape != (slice_len, num_feats):
        return jsonify({"error": f"bad shape {window.shape}, expected {(slice_len, num_feats)}"}), 400

    with torch.no_grad():
        t = torch.tensor(window, device=device).unsqueeze(0)  # [1, slice_len, num_feats]
        logits = model(t)
        cls = int(logits.argmax(1).item())
    return jsonify({"class": cls})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
