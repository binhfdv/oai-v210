import os
import time
import logging
import pickle
import threading
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from collections import deque
from flask import Flask, request, jsonify
from torch_geometric.nn import SAGEConv, global_mean_pool
from xapp_control import open_control_socket, receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PORT       = int(os.getenv("XCHAIN_PORT", "5003"))
DATA_PORT  = int(os.getenv("XCHAIN_DATA_PORT", "4500"))
MODEL_DIR  = os.getenv("MODEL_DIR", "/mnt/model")
T          = int(os.getenv("T", "32"))

WINDOWS = {}   # ue_id -> deque of scaled feature vectors (zero-padded)

FEATURE_INDEXES = [9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 30]
CLASS_NAMES     = ["eMBB", "mMTC", "URLLC"]


# ── Model definition (must match training) ────────────────────────────────────
class GNNClassifier(nn.Module):
    def __init__(self, in_dim, hidden_dim, num_layers, dropout, num_classes=3):
        super().__init__()
        self.convs = nn.ModuleList()
        self.bns   = nn.ModuleList()
        self.convs.append(SAGEConv(in_dim, hidden_dim, aggr='mean'))
        self.bns.append(nn.BatchNorm1d(hidden_dim))
        for _ in range(num_layers - 1):
            self.convs.append(SAGEConv(hidden_dim, hidden_dim, aggr='mean'))
            self.bns.append(nn.BatchNorm1d(hidden_dim))
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, num_classes),
        )

    def forward(self, x, edge_index, batch):
        for conv, bn in zip(self.convs, self.bns):
            x = F.relu(bn(conv(x, edge_index)))
            x = self.dropout(x)
        x = global_mean_pool(x, batch)
        return self.head(x)


# ── Load model + edge_index + scaler ─────────────────────────────────────────
def load_model(model_dir, T):
    ckpt = torch.load(os.path.join(model_dir, f"gnn_model_T_{T}.pt"), map_location="cpu")
    edge_index = torch.load(os.path.join(model_dir, f"gnn_edge_index_T_{T}.pt"), map_location="cpu")
    with open(os.path.join(model_dir, f"gnn_scaler_T_{T}.pkl"), "rb") as f:
        scaler = pickle.load(f)

    model = GNNClassifier(
        in_dim     = ckpt["in_dim"],
        hidden_dim = ckpt["hidden_dim"],
        num_layers = ckpt["num_layers"],
        dropout    = ckpt["dropout"],
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    logging.info(f"GNN model T={T} loaded from {model_dir}")
    return model, edge_index, scaler

model, edge_index, scaler = load_model(MODEL_DIR, T)
M = scaler.center_.shape[0]   # number of KPI features (17)


# ── Window builder with zero-padding (in scaled space) ───────────────────────
def get_window(ue_id, scaled_features):
    if ue_id not in WINDOWS:
        buf = deque([np.zeros(M, dtype=np.float32)] * T, maxlen=T)
        WINDOWS[ue_id] = buf
    WINDOWS[ue_id].append(np.array(scaled_features, dtype=np.float32))
    return np.array(WINDOWS[ue_id], dtype=np.float32)   # (T, M)


# ── Inference ─────────────────────────────────────────────────────────────────
def gnn_predict(window):
    """
    window: (T, M) numpy array
    Graph: M nodes, each with T-dim features → node_feats shape (M, T)
    """
    node_feats = torch.tensor(window.T, dtype=torch.float32)   # (M, T)
    batch      = torch.zeros(M, dtype=torch.long)               # all nodes in 1 graph
    with torch.no_grad():
        logits = model(node_feats, edge_index, batch)           # (1, 3)
        cls    = int(torch.argmax(logits, dim=1).item())
    return cls


# ── Row parser ────────────────────────────────────────────────────────────────
def parse_sample(row_data):
    if isinstance(row_data, (bytes, bytearray)):
        row_data = row_data.decode("utf-8", errors="ignore")
    parts = row_data.strip().split(",")
    if len(parts) < 31:
        logging.warning(f"Malformed row (len={len(parts)})")
        return 0, [0.0] * M
    parts = parts[1:]
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
        cls = gnn_predict(window)
        latency = (time.perf_counter() - t0) * 1000
        return jsonify({"ue_id": ue_id, "class": cls,
                        "traffic_type": CLASS_NAMES[cls],
                        "latency_ms": round(latency, 3)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Socket listener ───────────────────────────────────────────────────────────
def socket_listener(control_sck):
    logging.info(f"GNN xApp listening on port {DATA_PORT}")
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
                cls = gnn_predict(window)
                latency = (time.perf_counter() - t0) * 1000
                e2e = (time.perf_counter() - t_e2e) * 1000
                logging.info(f"UE={ue_id} -> Predicted class: {CLASS_NAMES[cls]} | Latency={latency:.3f}ms | End2end={e2e:.3f}ms")
        except Exception as e:
            logging.error(f"Socket error: {e}")


if __name__ == "__main__":
    control_sck = open_control_socket(DATA_PORT)
    threading.Thread(target=socket_listener, args=(control_sck,), daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
