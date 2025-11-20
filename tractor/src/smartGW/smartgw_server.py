#!/usr/bin/env python3
"""
SmartGW
- SERVER: listens for KPM-OAI on PORT (accepts one client via open_control_socket)
- CLIENT: connects to TRACTOR and XCHAIN and streams classified rows via TCP
"""
import pickle
import time
import logging
import socket
import os
from flask import Flask, request, jsonify
import numpy as np
from queue import Queue
from threading import Thread

from xapp_control import open_control_socket, receive_from_socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------
# Load SmartGW model (pickled dict)
# ---------------------------
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/smartgw.pkl")
with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)

# verify feature columns exist
feature_cols = model["feature_cols"]

# ---------------------------------------------------------
# Read environment variables (with safe defaults)
# ---------------------------------------------------------
TRACTOR_HOST = os.getenv("TRACTOR_HOST", "tractor-orchestrator")
TRACTOR_PORT = int(os.getenv("TRACTOR_PORT", "4300"))

XCHAIN_HOST = os.getenv("XCHAIN_HOST", "xchain-model")
XCHAIN_PORT = int(os.getenv("XCHAIN_PORT", "4400"))

# SmartGW listens for KPM-OAI on this port (server)
PORT = int(os.getenv("PORT", "4200"))

logging.info(f"[CONFIG] TRACTOR_HOST = {TRACTOR_HOST}:{TRACTOR_PORT}")
logging.info(f"[CONFIG] XCHAIN_HOST  = {XCHAIN_HOST}:{XCHAIN_PORT}")
logging.info(f"[CONFIG] SMARTGW LISTEN PORT = {PORT}")

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
# SOCKET LISTENER — receives traffic from KPM-OAI (server side)
# ======================================================
def socket_listener(control_sck):
    logging.info("Socket listener started (receiving KPM-OAI)...")
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
                if len(parts) < 31:
                    logging.warning(f"Skipping malformed row: {line}")
                    continue

                # parse KPM features used by KMeans
                try:
                    x_raw = {
                        "DRB.UEThpDl": float(parts[KPM_COL_THPDL]),
                        "DRB.UEThpUl": float(parts[KPM_COL_THPUL]),
                    }
                    recv_time = time.time()
                    # enqueue full raw CSV line (string) so we can forward it unchanged
                    data_queue.put((x_raw, line, recv_time))
                except Exception as e:
                    logging.exception(f"Parsing error: {e}")

        except Exception as e:
            logging.exception(f"Socket listener error: {e}")
            time.sleep(0.3)


# ======================================================
# WORKER: classify + forward traffic (client sockets)
# ======================================================
def send_to_socket(sock, message: str):
    try:
        sock.sendall(message.encode("utf-8"))
    except Exception as e:
        logging.error(f"Socket send error: {e}")
        # close socket to force reconnect upstream
        try:
            sock.close()
        except Exception:
            pass
        raise


def connect_socket(host, port, label):
    """
    Persistent connect with backoff. Returns a connected socket.
    """
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.settimeout(None)
            logging.info(f"[SmartGW] Connected to {label} at {host}:{port}")
            return s
        except Exception as e:
            logging.warning(f"[SmartGW] Connection to {label} at {host}:{port} failed: {e}. Retrying in 2s.")
            try:
                s.close()
            except Exception:
                pass
            time.sleep(2)


def classification_worker():
    logging.info("Classifier worker running...")

    # Establish long-lived connections to tractor & xchain
    tractor_socket = connect_socket(TRACTOR_HOST, TRACTOR_PORT, "TRACTOR")
    xchain_socket = connect_socket(XCHAIN_HOST, XCHAIN_PORT, "XCHAIN")

    while True:
        x_raw, full_row, recv_time = data_queue.get()

        # prediction
        start = time.perf_counter()
        try:
            prediction = smartgw_predict_ultrafast(x_raw, model)
        except Exception as e:
            logging.exception(f"Prediction failed: {e}")
            # skip forwarding malformed
            data_queue.task_done()
            continue
        latency_ms = (time.perf_counter() - start) * 1000

        logging.info(
            f"[SmartGW] Class={prediction}  Latency={latency_ms:.3f} ms  UE-Features={x_raw}"
        )

        # forward via socket, choosing target
        try:
            if prediction == "eMBB":
                send_to_socket(tractor_socket, full_row + "\n")
            else:
                send_to_socket(xchain_socket, full_row + "\n")
        except Exception as e:
            logging.error(f"[SmartGW] Forwarding error: {e}")

            # reconnect the appropriate socket and retry once
            try:
                if prediction == "eMBB":
                    tractor_socket = connect_socket(TRACTOR_HOST, TRACTOR_PORT, "TRACTOR")
                    send_to_socket(tractor_socket, full_row + "\n")
                else:
                    xchain_socket = connect_socket(XCHAIN_HOST, XCHAIN_PORT, "XCHAIN")
                    send_to_socket(xchain_socket, full_row + "\n")
            except Exception as e2:
                logging.error(f"[SmartGW] Retry forward failed: {e2}")

        finally:
            data_queue.task_done()


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
    # SmartGW acts as SERVER for KPM-OAI (one accept is fine here, your open_control_socket does exactly that)
    control_sck = open_control_socket(PORT)

    # start listener for incoming KPM rows (this will read from the accepted socket)
    Thread(target=socket_listener, args=(control_sck,), daemon=True).start()

    # start classifier worker (consumer + client sockets)
    Thread(target=classification_worker, daemon=True).start()

    # small debug HTTP endpoint for manual testing
    app.run(host="0.0.0.0", port=5004)
