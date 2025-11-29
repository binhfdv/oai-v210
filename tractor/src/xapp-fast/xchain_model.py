import os
import time
import logging
import numpy as np
import threading
from flask import Flask, request, jsonify
from xgboost import Booster

# Import socket logic (same as SmartGW)
from xapp_control import open_control_socket, receive_from_socket

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# -------------------------------------------------
# Load XGBoost Model
# -------------------------------------------------
def load_xgb_model(model_path="xgb_model.json"):
    model = Booster()
    model.load_model(model_path)
    model.set_param({"predictor": "cpu_predictor"})
    model.set_param({"approx_kernel": "true"})
    logging.info("✔ XGBoost model loaded")
    return model


PORT = int(os.getenv("XCHAIN_PORT", "5001"))
DATA_PORT = int(os.getenv("XCHAIN_DATA_PORT", "4400"))
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/xgb_model.json")

model = load_xgb_model(MODEL_PATH)

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
        return 0, np.zeros((1, 17), dtype=float)
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
# XGBoost Prediction
# -------------------------------------------------
def xgb_predict(features, model):
    arr = np.array([features]).reshape((1, 17))
    probs = model.inplace_predict(arr)
    cls = int(np.argmax(probs[0]))
    return cls, probs[0]


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
        t0 = time.perf_counter()
        cls, probs = xgb_predict(features, model)
        latency = (time.perf_counter() - t0) * 1000

        return jsonify({
            "ue_id": ue_id,
            "class": cls,
            "traffic_type": ["eMBB", "mMTC", "URLLC"][cls],
            "probs": [float(x) for x in probs],
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
            cls, probs = xgb_predict(features, model)
            latency = (time.perf_counter() - t0) * 1000
            end = time.perf_counter()

            logging.info(
                f"UE={ue_id} -> "
                f"Predicted class: {['eMBB','mMTC','URLLC'][cls]} | "
                f"Latency={latency:.3f}ms | "
                f"Probs={probs} | "
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
