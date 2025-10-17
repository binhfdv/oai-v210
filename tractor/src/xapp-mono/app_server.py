# app_server.py
from flask import Flask, request, jsonify
import numpy as np
import pickle
import torch
from python.ORAN_models import TransformerNN, TransformerNN_v2, ConvNN
from python.visual_xapp_inference import process_norm_params

app = Flask(__name__)

# --- Buffer state (from buffer service) ---
buffers = {}  # stream_id -> list of vectors

@app.route("/reset", methods=["POST"])
def reset():
    stream = request.json.get("stream", "default")
    buffers[stream] = []
    return jsonify({"status": "reset", "stream": stream})
 
@app.route("/update", methods=["POST"])
def update():
    stream = request.json.get("stream", "default")
    kpi = request.json["kpi"]  # normalized vector [num_feats]
    slice_len = int(request.json["slice_len"])
    num_feats = int(request.json["num_feats"])

    buf = buffers.setdefault(stream, [])
    buf.append(kpi)
    if len(buf) > slice_len:
        buf.pop(0)

    ready = len(buf) == slice_len
    return jsonify({"ready": ready, "window": buf if ready else []})

# --- Normalizer state & endpoints (from normalizer service) ---
colsparams = None
indexes_to_keep = None
map_feat2KPI = None
num_feats = None
slice_len = None

@app.route("/load_norm", methods=["POST"])
def load_norm():
    global colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len
    norm_param_path = request.json.get("norm_param_path")
    if not norm_param_path:
        return {"error": "norm_param_path is required"}, 400

    all_feats_raw = int(request.json.get("all_feats_raw", 31))
    colsparam_dict = pickle.load(open(norm_param_path, "rb"))
    colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len, _ = process_norm_params(all_feats_raw, colsparam_dict)
    return jsonify({"status": "ok", "num_feats": int(num_feats), "slice_len": int(slice_len)})

@app.route("/normalize", methods=["POST"])
def normalize():
    global colsparams, indexes_to_keep
    if colsparams is None or indexes_to_keep is None:
        return {"error": "normalizer not loaded"}, 400

    kpi = np.array(request.json["kpi"], dtype=float)
    kpi_filt = kpi[indexes_to_keep]
    # normalize -> single vector (num_feats,)
    for f in range(kpi_filt.shape[0]):
        mn, mx = colsparams[f]['min'], colsparams[f]['max']
        if kpi_filt[f] < mn: kpi_filt[f] = mn
        if kpi_filt[f] > mx: kpi_filt[f] = mx
        denom = (mx - mn) if (mx - mn) != 0 else 1.0
        kpi_filt[f] = (kpi_filt[f] - mn) / denom
    return jsonify({"normalized": kpi_filt.tolist()})

# --- Model state & endpoints (from model service) ---
model = None
device = "cpu"
_model_slice_len = None
_model_num_feats = None

@app.route("/load_model", methods=["POST"])
def load_model():
    global model, device, _model_slice_len, _model_num_feats
    data = request.json
    model_type = data["model_type"]    # "Tv1" | "Tv2" | "CNN" | "ViT"
    model_path = data["model_path"]
    Nclass     = int(data.get("Nclass", 4))
    _model_slice_len  = int(data.get("slice_len"))
    _model_num_feats  = int(data.get("num_feats"))

    if model_type == "Tv1":
        model = TransformerNN(classes=Nclass, slice_len=_model_slice_len, num_feats=_model_num_feats, use_pos=False, nhead=1, custom_enc=True)
    elif model_type == "Tv2":
        model = TransformerNN_v2(classes=Nclass, slice_len=_model_slice_len, num_feats=_model_num_feats, use_pos=False, nhead=1, custom_enc=True)
    elif model_type == "CNN":
        model = ConvNN(classes=Nclass, slice_len=_model_slice_len, num_feats=_model_num_feats)
    else:
        return jsonify({"error": "ViT/other not supported"}), 400

    # load weights
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
        x = torch.rand(1, _model_slice_len, _model_num_feats, device=device)
        _ = model(x)

    return jsonify({"status": "ok", "device": device})

@app.route("/predict", methods=["POST"])
def predict():
    global model, device, _model_slice_len, _model_num_feats
    if model is None:
        return jsonify({"error": "model not loaded"}), 400

    window = np.array(request.json["window"], dtype=np.float32)  # [slice_len, num_feats]
    if window.shape != (_model_slice_len, _model_num_feats):
        return jsonify({"error": f"bad shape {window.shape}, expected {(_model_slice_len, _model_num_feats)}"}), 400

    with torch.no_grad():
        t = torch.tensor(window, device=device).unsqueeze(0)  # [1, slice_len, num_feats]
        logits = model(t)
        cls = int(logits.argmax(1).item())
    return jsonify({"class": cls})

# Expose these helpers so orchestrator can call them directly (non-HTTP)
def _call_load_norm(norm_param_path, all_feats_raw=31):
    req = {"norm_param_path": norm_param_path, "all_feats_raw": all_feats_raw}
    return load_norm_internal(req)

def load_norm_internal(req):
    # internal helper used by orchestrator (same logic as /load_norm)
    global colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len
    norm_param_path = req.get("norm_param_path")
    if not norm_param_path:
        raise ValueError("norm_param_path is required")

    all_feats_raw = int(req.get("all_feats_raw", 31))
    colsparam_dict = pickle.load(open(norm_param_path, "rb"))
    colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len, _ = process_norm_params(all_feats_raw, colsparam_dict)
    return {"status": "ok", "num_feats": int(num_feats), "slice_len": int(slice_len)}

def _call_normalize(kpi_list):
    req = {"kpi": kpi_list}
    # return normalized list
    r = normalize_internal(req)
    return r

def normalize_internal(req):
    global colsparams, indexes_to_keep
    if colsparams is None or indexes_to_keep is None:
        raise RuntimeError("normalizer not loaded")
    kpi = np.array(req["kpi"], dtype=float)
    kpi_filt = kpi[indexes_to_keep]
    for f in range(kpi_filt.shape[0]):
        mn, mx = colsparams[f]['min'], colsparams[f]['max']
        if kpi_filt[f] < mn: kpi_filt[f] = mn
        if kpi_filt[f] > mx: kpi_filt[f] = mx
        denom = (mx - mn) if (mx - mn) != 0 else 1.0
        kpi_filt[f] = (kpi_filt[f] - mn) / denom
    return {"normalized": kpi_filt.tolist()}

def _call_buffer_update(stream, kpi_vec, slice_len_val, num_feats_val):
    req = {"stream": stream, "kpi": kpi_vec, "slice_len": slice_len_val, "num_feats": num_feats_val}
    return update_internal(req)

def update_internal(req):
    stream = req.get("stream", "default")
    kpi = req["kpi"]
    slice_len = int(req["slice_len"])
    num_feats = int(req["num_feats"])
    buf = buffers.setdefault(stream, [])
    buf.append(kpi)
    if len(buf) > slice_len:
        buf.pop(0)
    ready = len(buf) == slice_len
    return {"ready": ready, "window": buf if ready else []}

def _call_model_predict(window):
    req = {"window": window}
    return predict_internal(req)

def predict_internal(req):
    global model, device, _model_slice_len, _model_num_feats
    if model is None:
        raise RuntimeError("model not loaded")
    window = np.array(req["window"], dtype=np.float32)
    if window.shape != (_model_slice_len, _model_num_feats):
        raise ValueError(f"bad shape {window.shape}, expected {(_model_slice_len, _model_num_feats)}")
    with torch.no_grad():
        t = torch.tensor(window, device=device).unsqueeze(0)
        logits = model(t)
        cls = int(logits.argmax(1).item())
    return {"class": cls}
