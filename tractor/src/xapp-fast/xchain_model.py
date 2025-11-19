import os
import json
import time
import logging
import numpy as np
import threading
from flask import Flask, request, jsonify
from xgboost import Booster

# Import socket logic (same as SmartGW)
from xapp_control import open_control_socket, receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# -------------------------------------------------
# Load XGBoost Model
# -------------------------------------------------
def load_xgb_model(model_path="xgb_model.json"):
    model = Booster()
    model.load_model(model_path)
    model.set_param({"predictor": "cpu_predictor"})
    model.set_param({"approx_kernel": "true"})  # enables fast pred

    logging.info("✔ XGBoost model loaded")
    return model


PORT = int(os.getenv("XCHAIN_PORT", "5001"))
DATA_PORT = int(os.getenv("XCHAIN_DATA_PORT", "4400"))

MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/xgb_model.json")

model = load_xgb_model(MODEL_PATH)


# -------------------------------------------------
# DATA PROCESSING LOGIC
# -------------------------------------------------
FEATURE_INDEXES = [9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 30]


def parse_sample(row_str):
    """
    Parse incoming traffic string.
    Example row:
    timestamp,1763543,1,0,1.0,0,0,0,...
    """

    parts = row_str.strip().split(",")

    # Remove index 0 (timestamp)
    parts = parts[1:]

    # UE ID at index 3
    ue_id = int(float(parts[3]))

    # Extract 17 XGBoost features
    features = [float(parts[i]) for i in FEATURE_INDEXES]

    return ue_id, features


def xgb_predict(features, model):
    arr = np.array([features]).reshape((1, 17))
    probs = model.inplace_predict(arr)
    cls = int(np.argmax(probs[0]))
    return cls, probs[0]


# -------------------------------------------------
# FLASK API for SmartGW → XChain
# -------------------------------------------------
@app.route("/predict", methods=["POST"])
def predict_route():
    data = request.get_json()

    if "row" not in data:
        return jsonify({"error": "Missing 'row'"}), 400

    try:
        ue_id, features = parse_sample(data["row"])

        t0 = time.perf_counter()
        cls, probs = xgb_predict(features, model)
        latency = (time.perf_counter() - t0) * 1000

        return jsonify({
            "ue_id": ue_id,
            "class": cls,
            "probs": [float(x) for x in probs],
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
            start = time.perf_counter()
            msg = receive_from_socket(control_sck)
            if not msg:
                continue

            row = msg.decode("utf-8")

            t0 = time.perf_counter()
            ue_id, features = parse_sample(row)
            cls, probs = xgb_predict(features, model)
            latency = (time.perf_counter() - t0) * 1000

            logging.info(
                f"UE={ue_id} -> "
                f"Predicted class: {['eMBB','mMTC','URLLC'][cls]} | "
                f"Latency={latency:.3f}ms | "
                f"Probs={probs} | "
                f"End2end={(time.perf_counter() - start)*1000:.3f}ms\n"
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
