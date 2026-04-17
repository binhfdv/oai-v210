import os
import time
import logging
import pickle
import threading
import numpy as np
import torch
import torch.nn as nn
from collections import deque
from flask import Flask, request, jsonify
from xapp_control import open_control_socket, receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PORT       = int(os.getenv("XCHAIN_PORT", "5002"))
DATA_PORT  = int(os.getenv("XCHAIN_DATA_PORT", "4600"))
MODEL_DIR  = os.getenv("MODEL_DIR", "/mnt/model")
T          = int(os.getenv("T", "32"))

WINDOWS = {}   # ue_id -> deque of scaled feature vectors (zero-padded)

FEATURE_INDEXES = [9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 30]
CLASS_NAMES     = ["eMBB", "mMTC", "URLLC"]


# ── Model definition (must match training) ────────────────────────────────────
class LSTMClassifier(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, dropout, num_classes=3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.norm = nn.LayerNorm(hidden_size)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, num_classes),
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.norm(out[:, -1, :])
        return self.head(out)


# ── Load model + scaler ───────────────────────────────────────────────────────
def load_model(model_dir, T):
    ckpt   = torch.load(os.path.join(model_dir, f"lstm_model_T_{T}.pt"), map_location="cpu")
    with open(os.path.join(model_dir, f"lstm_scaler_T_{T}.pkl"), "rb") as f:
        scaler = pickle.load(f)

    model = LSTMClassifier(
        input_size  = ckpt["input_size"],
        hidden_size = ckpt["hidden_size"],
        num_layers  = ckpt["num_layers"],
        dropout     = ckpt["dropout"],
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    logging.info(f"LSTM model T={T} loaded from {model_dir}")
    return model, scaler

model, scaler = load_model(MODEL_DIR, T)
M = scaler.center_.shape[0]   # number of features (17)


# ── Window builder with zero-padding (in scaled space) ───────────────────────
def get_window(ue_id, scaled_features):
    """
    Maintain a rolling buffer per UE.
    New buffer is pre-filled with zeros (= scaled median → neutral padding).
    Returns (T, M) numpy array immediately from sample 1.
    """
    if ue_id not in WINDOWS:
        buf = deque([np.zeros(M, dtype=np.float32)] * T, maxlen=T)
        WINDOWS[ue_id] = buf
    WINDOWS[ue_id].append(np.array(scaled_features, dtype=np.float32))
    return np.array(WINDOWS[ue_id], dtype=np.float32)   # (T, M)


# ── Inference ─────────────────────────────────────────────────────────────────
def lstm_predict(window):
    x = torch.tensor(window, dtype=torch.float32).unsqueeze(0)  # (1, T, M)
    with torch.no_grad():
        logits = model(x)
        cls = int(torch.argmax(logits, dim=1).item())
    return cls


# ── Row parser ────────────────────────────────────────────────────────────────
def parse_sample(row_data):
    if isinstance(row_data, (bytes, bytearray)):
        row_data = row_data.decode("utf-8", errors="ignore")
    parts = row_data.strip().split(",")
    if len(parts) < 31:
        logging.warning(f"Malformed row (len={len(parts)})")
        return 0, [0.0] * M
    parts = parts[1:]   # drop timestamp
    ue_id = float(parts[3])
    try:
        raw = [float(parts[i]) for i in FEATURE_INDEXES]
    except Exception as e:
        raise ValueError(f"Feature extraction failed: {e}")
    scaled = scaler.transform(np.array(raw, dtype=np.float32).reshape(1, -1))[0].tolist()
    return ue_id, scaled


# ── REST endpoint ─────────────────────────────────────────────────────────────
@app.route("/predict", methods=["POST"])
def predict_route():
    data = request.get_json()
    if "row" not in data:
        return jsonify({"error": "Missing 'row'"}), 400
    try:
        ue_id, scaled = parse_sample(data["row"])
        window = get_window(ue_id, scaled)
        t0  = time.perf_counter()
        cls = lstm_predict(window)
        latency = (time.perf_counter() - t0) * 1000
        return jsonify({"ue_id": ue_id, "class": cls,
                        "traffic_type": CLASS_NAMES[cls],
                        "latency_ms": round(latency, 3)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Socket listener ───────────────────────────────────────────────────────────
def socket_listener(control_sck):
    logging.info(f"LSTM xApp listening on port {DATA_PORT}")
    while True:
        try:
            msg = receive_from_socket(control_sck)
            if not msg:
                continue
            for line in msg.splitlines():
                line = line.strip()
                if not line:
                    continue
                t_e2e = time.perf_counter()
                ue_id, scaled = parse_sample(line)
                window = get_window(ue_id, scaled)
                t0 = time.perf_counter()
                cls = lstm_predict(window)
                latency = (time.perf_counter() - t0) * 1000
                e2e = (time.perf_counter() - t_e2e) * 1000
                logging.info(f"UE={ue_id} -> Predicted class: {CLASS_NAMES[cls]} | Latency={latency:.3f}ms | End2end={e2e:.3f}ms")
        except Exception as e:
            logging.error(f"Socket error: {e}")


if __name__ == "__main__":
    control_sck = open_control_socket(DATA_PORT)
    threading.Thread(target=socket_listener, args=(control_sck,), daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
