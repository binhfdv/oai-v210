import pickle
import time
import logging
import requests
import os
from flask import Flask, request, jsonify
import numpy as np
from queue import Queue
from threading import Thread

from xapp_control import open_control_socket, receive_from_socket


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# ---------------------------
# Load SmartGW model
# ---------------------------
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/smartgw.pkl")

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)

feature_cols = model["feature_cols"]  # ['DRB.UEThpDl', 'DRB.UEThpUl']

# ---------------------------------------------------------
# Read environment variables (with safe defaults)
# ---------------------------------------------------------
ORCH_HOST = os.getenv("ORCH_HOST", "orchestrator")
ORCH_PORT = os.getenv("ORCH_PORT", "5000")

XCHAIN_HOST = os.getenv("XCHAIN_HOST", "xchain-orchestrator")
XCHAIN_PORT = os.getenv("XCHAIN_PORT", "5001")

PORT       = int(os.getenv("PORT", "4200"))
# ---------------------------------------------------------
# Construct final URLs
# ---------------------------------------------------------
ORCH_URL = f"http://{ORCH_HOST}:{ORCH_PORT}"
XCHAIN_URL = f"http://{XCHAIN_HOST}:{XCHAIN_PORT}"

logging.info(f"[CONFIG] ORCH_URL   = {ORCH_URL}")
logging.info(f"[CONFIG] XCHAIN_URL = {XCHAIN_URL}")

# ---------------------------------------------------------
# Read environment variables for column index selection
# ---------------------------------------------------------
KPM_COL_THPDL = int(os.getenv("KPM_COL_THPDL", "13"))
KPM_COL_THPUL = int(os.getenv("KPM_COL_THPUL", "20"))

logging.info(f"[CONFIG] KPM_COL_THPDL = {KPM_COL_THPDL}")
logging.info(f"[CONFIG] KPM_COL_THPUL = {KPM_COL_THPUL}")

# incoming queue from socket listener
data_queue = Queue()

app = Flask(__name__)


# ======================================================
# FAST SCALE + FAST KMEANS Prediction (your code)
# ======================================================

def fast_scale(x, scaler):
    if hasattr(scaler, "mean_"):
        return (x - scaler.mean_) / scaler.scale_
    else:
        return (x - scaler.data_min_) / scaler.data_range_


def smartgw_predict_ultrafast(x_raw, model):
    feature_cols = model["feature_cols"]
    log_method = model["log_method"]
    scaler = model["scaler"]
    centroids = model["kmeans"].cluster_centers_
    centroid_to_class = model["centroid_to_class"]

    # extract to correct order
    x = np.array([x_raw[col] for col in feature_cols], dtype=float)

    # 2. log transform
    if log_method == "log1p":
        x = np.log1p(np.maximum(x, 0))
    elif log_method == "log":
        x = np.log(np.maximum(x, 1e-9))

    # 3. scale
    x = fast_scale(x, scaler)

    # 4. assign cluster
    dists = np.sum((centroids - x) ** 2, axis=1)
    c = int(np.argmin(dists))

    # 5. centroid -> class
    return "eMBB" if centroid_to_class[c] == 0 else "mMTC-URLLC"


# ======================================================
# SOCKET LISTENER — receives traffic from KPM-OAI
# ======================================================
def socket_listener(control_sck):
    logging.info("Socket listener started...")
    buffer = ""

    while True:
        try:
            data = receive_from_socket(control_sck)
            if not data:
                continue

            buffer += data

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                parts = line.split(",")

                if len(parts) < 31:  # need at least index 20
                    logging.warning(f"Skipping malformed row: {line}")
                    continue

                # extract raw features
                try:
                    x_raw = {
                        "DRB.UEThpDl": float(parts[KPM_COL_THPDL]),
                        "DRB.UEThpUl": float(parts[KPM_COL_THPUL]),
                    }

                    recv_time = time.time()
                    data_queue.put((x_raw, parts, recv_time))

                except Exception as e:
                    logging.exception(f"Parsing error: {e}")

        except Exception as e:
            logging.exception(f"Socket listener error: {e}")
            time.sleep(0.3)


# ======================================================
# WORKER: classify + forward traffic
# ======================================================
def classification_worker():
    logging.info("Classifier worker running...")

    while True:
        x_raw, full_row, recv_time = data_queue.get()

        start = time.perf_counter()
        prediction = smartgw_predict_ultrafast(x_raw, model)
        latency_ms = (time.perf_counter() - start) * 1000

        logging.info(
            f"[SmartGW] Class={prediction}  Latency={latency_ms:.3f} ms  Features={x_raw}"
        )

        # forward traffic to the proper orchestrator
        try:
            if prediction == "eMBB":
                requests.post(ORCH_URL, json={"row": full_row})
            else:
                requests.post(XCHAIN_URL, json={"row": full_row})

        except Exception as e:
            logging.error(f"Forwarding error: {e}")


# ======================================================
# OPTIONAL DEBUG ENDPOINT
# ======================================================
@app.route("/predict", methods=["POST"])
def test_predict():
    data = request.json
    start = time.perf_counter()
    pred = smartgw_predict_ultrafast(data, model)
    latency_ms = (time.perf_counter() - start) * 1000
    return jsonify({"prediction": pred, "latency_ms": latency_ms})


# ======================================================
# MAIN
# ======================================================
if __name__ == "__main__":
    # socket to KPM-OAI
    control_sck = open_control_socket(PORT)

    Thread(target=socket_listener, args=(control_sck,), daemon=True).start()
    Thread(target=classification_worker, daemon=True).start()

    app.run(host="0.0.0.0", port=5004)
