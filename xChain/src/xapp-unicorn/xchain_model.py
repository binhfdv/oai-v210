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
from xapp_control import receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PORT       = int(os.getenv("XCHAIN_PORT",      "5004"))
DATA_PORT  = int(os.getenv("XCHAIN_DATA_PORT", "4700"))
MODEL_DIR  = os.getenv("MODEL_DIR",  "/mnt/model")
MODEL_ARCH = os.getenv("MODEL_ARCH", "ForwConvNet")   # ForwConvNet | ResConvNet
OOD_INDEX    = int(os.getenv("OOD_INDEX",    "5"))        # 4 | 5
SLICE_LEN    = int(os.getenv("SLICE_LEN",    "64"))
SUBTRACE_LEN = int(os.getenv("SUBTRACE_LEN", "200"))

NUM_FEATURES    = 17
NUM_CLASSES     = 5   # always 5 ID classes (one class is OOD)
ALL_CLASSES     = ["CallofDuty", "Facebook", "Meet", "Zoom", "Teams", "Twitch"]
ID_CLASS_NAMES  = [c for i, c in enumerate(ALL_CLASSES) if i != OOD_INDEX]

# Same 17 features as xapp-gnn — extracted after parts[1:] strips the leading timestamp
FEATURE_INDEXES = [9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 30]

BUFFERS      = {}   # ue_id -> deque(maxlen=SUBTRACE_LEN), slides on every new row
BUFFERS_LOCK = threading.Lock()


# ── Model definitions (must match unicorn/code/models.py) ────────────────────

class ResConvNet(nn.Module):
    """Input shape: (b, 1, 64, 17)"""
    def __init__(self, num_classes):
        super().__init__()
        p, ch = 0.25, 32
        self.conv1   = nn.Conv2d(1,  ch, kernel_size=(7, 7), padding="same")
        self.conv2   = nn.Conv2d(ch, ch, kernel_size=(5, 5), padding="same")
        self.pool1   = nn.MaxPool2d((2, 2))
        self.pool2   = nn.MaxPool2d((3, 3), padding=1)
        self.hidden1 = nn.Linear(128, 128)
        self.hidden2 = nn.Linear(128, 128)
        self.hidden3 = nn.Linear(128, 64)
        self.out     = nn.Linear(64, num_classes)
        self.drop    = nn.Dropout(p)
        self.relu    = nn.ReLU()

    def forward(self, x):
        x = self.relu(self.conv1(x));  x = self.pool1(x)
        a = x
        x = self.relu(self.conv2(x));  x = self.relu(self.conv2(x));  x = torch.add(x, a);  x = self.pool2(x);  x = self.drop(x)
        b = x
        x = self.relu(self.conv2(x));  x = self.relu(self.conv2(x));  x = torch.add(x, b);  x = self.pool2(x);  x = self.drop(x)
        x = x.view(x.size(0), -1)
        x = self.drop(self.hidden1(x))
        x = self.drop(self.hidden2(x));  feature = x
        x = self.drop(self.hidden3(x))
        return feature, self.out(x)


class ForwConvNet(nn.Module):
    """Input shape: (b, 1, 64, 17)"""
    def __init__(self, num_classes):
        super().__init__()
        p, ch = 0.25, 32
        self.conv1   = nn.Conv2d(1,  ch, kernel_size=(5, 5), padding="same")
        self.conv2   = nn.Conv2d(ch, ch, kernel_size=(3, 3), padding="same")
        self.pool1   = nn.MaxPool2d((2, 2))
        self.hidden1 = nn.Linear(512, 256)
        self.hidden2 = nn.Linear(256, 128)
        self.hidden3 = nn.Linear(128, 64)
        self.out     = nn.Linear(64, num_classes)
        self.drop    = nn.Dropout(p)
        self.relu    = nn.ReLU()

    def forward(self, x):
        x = self.relu(self.conv1(x));  x = self.pool1(x)
        x = self.relu(self.conv2(x));  x = self.pool1(x)
        x = self.relu(self.conv2(x));  x = self.pool1(x)
        x = self.drop(x)
        x = x.view(x.size(0), -1)
        x = self.drop(self.hidden1(x))
        x = self.drop(self.hidden2(x));  feature = x
        x = self.drop(self.hidden3(x))
        return feature, self.out(x)


# ── Load model + normalisation params ────────────────────────────────────────

def load_assets(model_dir, arch, ood_index):
    weight_path = os.path.join(model_dir, f"weights-ICMLCN{ood_index}-{arch}-5ids-oodindex{ood_index}.pt")
    norm_path   = os.path.join(model_dir, f"ICMLCN{ood_index}_global_cols_maxmin.pkl")

    cls = ResConvNet if arch == "ResConvNet" else ForwConvNet
    net = cls(NUM_CLASSES)
    net.load_state_dict(torch.load(weight_path, map_location="cpu", weights_only=True))
    net.eval()

    with open(norm_path, "rb") as f:
        norm_params = pickle.load(f)

    logging.info(f"UNICORN loaded: arch={arch}  ood_index={ood_index}  id_classes={ID_CLASS_NAMES}")
    return net, norm_params


model, norm_params = load_assets(MODEL_DIR, MODEL_ARCH, OOD_INDEX)


# ── Feature normalisation (min-max per column) ────────────────────────────────

def normalize(raw):
    out = []
    for i, val in enumerate(raw):
        col_max = norm_params[i]["max"]
        col_min = norm_params[i]["min"]
        out.append((val - col_min) / (col_max - col_min) if col_max != col_min else 0.0)
    return out


# ── Per-UE subtrace accumulator ───────────────────────────────────────────────

def accumulate_row(ue_id, norm_features):
    """Append one row to the sliding deque. Returns a (SUBTRACE_LEN, NUM_FEATURES)
    array on every call once the buffer is full; returns None during warmup."""
    with BUFFERS_LOCK:
        if ue_id not in BUFFERS:
            BUFFERS[ue_id] = deque(maxlen=SUBTRACE_LEN)
        BUFFERS[ue_id].append(np.array(norm_features, dtype=np.float32))
        if len(BUFFERS[ue_id]) < SUBTRACE_LEN:
            return None
        return np.array(BUFFERS[ue_id], dtype=np.float32)


# ── Inference ─────────────────────────────────────────────────────────────────

def unicorn_predict(subtrace):
    """subtrace: (SUBTRACE_LEN, NUM_FEATURES)
    Mirrors test_model.py: stride-1 sliding window of SLICE_LEN rows, logits
    summed across all windows, argmax of the sum → class index."""
    t = torch.tensor(subtrace, dtype=torch.float32)  # (SUBTRACE_LEN, 17)
    prob_sum = None
    with torch.no_grad():
        start = 0
        while start <= t.shape[0] - SLICE_LEN:
            x = t[start:start + SLICE_LEN].unsqueeze(0).unsqueeze(0)  # (1,1,64,17)
            feature, logits = model(x)
            prob_sum = logits if prob_sum is None else prob_sum + logits
            start += 1
    cls = int(torch.argmax(prob_sum, dim=1).item())
    return cls, prob_sum.squeeze(0).tolist(), feature.squeeze(0).tolist()


# ── Row parser (same format as kpm_colosseum_oai: 33 fields) ─────────────────

def parse_sample(row_data):
    if isinstance(row_data, (bytes, bytearray)):
        row_data = row_data.decode("utf-8", errors="ignore")
    parts = row_data.strip().split(",")
    logging.info(f"[RAW] nfields={len(parts)}  row={row_data.strip()[:120]}")
    if len(parts) < 31:
        logging.warning(f"Malformed row (len={len(parts)})")
        return 0, [0.0] * NUM_FEATURES
    parts  = parts[1:]                                         # drop leading timestamp string
    ue_id  = float(parts[1])                                   # RNTI
    raw    = [float(parts[i]) for i in FEATURE_INDEXES]
    feat_names = [norm_params[i]["name"] for i in range(NUM_FEATURES)]
    logging.info(f"[PARSED] ue={ue_id}  " + "  ".join(f"{n}={v:.4f}" for n, v in zip(feat_names, raw)))
    return ue_id, normalize(raw)


# ── REST endpoint ─────────────────────────────────────────────────────────────

@app.route("/predict", methods=["POST"])
def predict_route():
    data = request.get_json()
    if "row" not in data:
        return jsonify({"error": "Missing 'row'"}), 400
    try:
        ue_id, norm = parse_sample(data["row"])
        subtrace = accumulate_row(ue_id, norm)
        if subtrace is None:
            buf_len = len(BUFFERS.get(ue_id, []))
            return jsonify({"status": "buffering", "buffer_len": buf_len}), 202
        t0 = time.perf_counter()
        cls, logits, feature = unicorn_predict(subtrace)
        latency = (time.perf_counter() - t0) * 1000
        return jsonify({
            "ue_id":        ue_id,
            "class":        cls,
            "application":  ID_CLASS_NAMES[cls],
            # "logits":       logits,
            "latency_ms":   round(latency, 3),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Socket listener ───────────────────────────────────────────────────────────

def socket_listener():
    import socket as _socket
    logging.info(f"UNICORN xApp TCP listener ready on port {DATA_PORT} (waiting for xApp)")
    server = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    server.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    server.bind(('', DATA_PORT))
    server.listen(5)
    control_sck, client_addr = server.accept()
    logging.info(f"xApp connected: {client_addr[0]}:{client_addr[1]}")
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
                ue_id, norm = parse_sample(line)
                subtrace = accumulate_row(ue_id, norm)
                if subtrace is None:
                    continue
                t0 = time.perf_counter()
                cls, _, _ = unicorn_predict(subtrace)
                latency = (time.perf_counter() - t0) * 1000
                e2e     = (time.perf_counter() - t_e2e) * 1000
                logging.info(
                    f"UE={ue_id} -> Predicted class: {ID_CLASS_NAMES[cls]} | "
                    f"Latency={latency:.3f}ms | End2end={e2e:.3f}ms"
                )
        except Exception as e:
            logging.error(f"Socket error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Thread(target=socket_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
