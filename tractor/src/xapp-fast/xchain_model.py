import os
import time
import logging
import numpy as np
import threading
from flask import Flask, request, jsonify
from xgboost import Booster
from collections import deque

# Import socket logic (same as SmartGW)
from xapp_control import open_control_socket, receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WINDOWS = {}   # key: ue_id, value: deque(maxlen=T)

PORT = int(os.getenv("XCHAIN_PORT", "5001"))
DATA_PORT = int(os.getenv("XCHAIN_DATA_PORT", "4400"))
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/xgb_model.json")
T = int(os.getenv("T", "1"))


def build_prediction_window(ue_id, features, T):
    """
    ue_id     : float or int
    features  : list of 17 floats
    T         : window size

    Returns:
        - None, len(win)    if window not full yet
        - flattened vec     if window has size T
    """
    if ue_id not in WINDOWS:
        WINDOWS[ue_id] = deque(maxlen=T)

    win = WINDOWS[ue_id]
    win.append(features)

    # Not enough samples yet
    if len(win) < T:
        return None, len(win)

    # Convert to numpy (faster than Python list-flatten)
    arr = np.array(win, dtype=np.float32)  # shape = (T, 17)
    return arr.reshape(-1), len(win)       # flatten to (T*17,) 


def load_fast_booster(model_path):
    booster = Booster()
    booster.load_model(model_path)
    booster.set_param({"verbosity": 0})

    # forces fast CPU path
    booster.set_param({"predictor": "cpu_predictor"})
    booster.set_param({"approx_kernel": "true"})

    return booster


def xgb_predict(sample_flat, booster):
    arr = np.array(sample_flat, dtype=np.float32).reshape(1, -1)

    # raw logits, zero overhead
    logits = booster.inplace_predict(arr, iteration_range=(0, 0))

    # return only argmax → no softmax → faster
    cls = int(np.argmax(logits[0]))  
    return cls

model = load_fast_booster(MODEL_PATH)

# -------------------------------------------------
# DATA PROCESSING CONFIG
# -------------------------------------------------
FEATURE_INDEXES = [9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 30]


# -------------------------------------------------
# SAFE PARSER
# -------------------------------------------------
def parse_sample(row_data):
    """
    row_data may be:
        - bytes (from socket)
        - str   (from REST API)
    """

    # --- FIX: decode socket bytes ---
    if isinstance(row_data, (bytes, bytearray)):
        row_data = row_data.decode("utf-8", errors="ignore")

    row_data = row_data.strip()
    parts = row_data.split(",")

    if len(parts) < 31:  # minimal length check
        # raise ValueError(f"Malformed row (len={len(parts)}): {row_data}")
        logging.warning(f"Malformed row (len={len(parts)}): {row_data}")
        return 0, [0.0]*17
    # Remove timestamp (index 0)
    parts = parts[1:]

    # UE ID at index 3
    ue_id = float(parts[3])

    # Extract 17 features safely
    try:
        features = [float(parts[i]) for i in FEATURE_INDEXES]
    except Exception as e:
        raise ValueError(f"Feature extraction failed: {e} | Row={parts}")

    return ue_id, features


# -------------------------------------------------
# REST API TEST ENDPOINT
# -------------------------------------------------
@app.route("/predict", methods=["POST"])
def predict_route():
    data = request.get_json()

    if "row" not in data:
        return jsonify({"error": "Missing 'row'"}), 400

    try:
        ue_id, features = parse_sample(data["row"])
        flatT, lenT = build_prediction_window(ue_id, features, T)

        if flatT is None:
            return jsonify({
                "ue_id": ue_id,
                "class": None,
                "traffic_type": None,
                "latency_ms": 0.0,
                "status": f"waiting for T window ({lenT}/{T})"
            })
        
        t0 = time.perf_counter()
        cls = xgb_predict(flatT, model)
        latency = (time.perf_counter() - t0) * 1000

        return jsonify({
            "ue_id": ue_id,
            "class": cls,
            "traffic_type": ["eMBB", "mMTC", "URLLC"][cls],
            "latency_ms": round(latency, 3)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------------------------------
# BACKGROUND THREAD TO RECEIVE SOCKET DATA
# -------------------------------------------------
def socket_listener(control_sck):
    """Receives rows directly from SmartGW using control socket."""

    logging.info(f"✔ XChain listening on socket {DATA_PORT}")

    while True:
        try:
            msg = receive_from_socket(control_sck)
            if not msg:
                continue

            start = time.perf_counter()
            t0 = time.perf_counter()
            ue_id, features = parse_sample(msg)
            flatT, lenT = build_prediction_window(ue_id, features, T)
            if flatT is None:
                logging.info(f"UE={ue_id} -> Waiting for T window ({lenT}/{T})")
                continue
            cls = xgb_predict(flatT, model)
            latency = (time.perf_counter() - t0) * 1000
            end = time.perf_counter()

            logging.info(
                f"UE={ue_id} -> "
                f"Predicted class: {['eMBB','mMTC','URLLC'][cls]} | "
                f"Latency={latency:.3f}ms | "
                f"End2end={(end - start)*1000:.3f}ms\n"
            )

        except Exception as e:
            logging.error(f"Socket processing error: {e}")
            continue


# -------------------------------------------------
# START SOCKET THREAD + FLASK
# -------------------------------------------------
if __name__ == "__main__":
    control_sck = open_control_socket(DATA_PORT)
    
    threading.Thread(target=socket_listener, args=(control_sck,), daemon=True).start()

    app.run(host="0.0.0.0", port=PORT)
