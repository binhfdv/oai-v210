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
import threading
import requests
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
ORCH_HOST          = os.getenv("ORCH_HOST",          "xchain-orchestrator")
ORCH_PORT          = int(os.getenv("ORCH_PORT",          "5010"))
ORCH_POLL_INTERVAL = int(os.getenv("ORCH_POLL_INTERVAL", "30"))

# SmartGW listens for KPM-OAI on this port (server)
PORT = int(os.getenv("PORT", "4200"))

logging.info(f"[CONFIG] ORCH_HOST          = {ORCH_HOST}:{ORCH_PORT}")
logging.info(f"[CONFIG] ORCH_POLL_INTERVAL = {ORCH_POLL_INTERVAL}s")
logging.info(f"[CONFIG] SMARTGW LISTEN PORT = {PORT}")

# ---------------------------------------------------------
# Read environment variables for column index selection
# ---------------------------------------------------------
KPM_COL_THPDL = int(os.getenv("KPM_COL_THPDL", "13"))
KPM_COL_THPUL = int(os.getenv("KPM_COL_THPUL", "20"))
KPM_COL_VOLUL = int(os.getenv("KPM_COL_VOLUL", "32"))

logging.info(f"[CONFIG] KPM_COL_THPDL = {KPM_COL_THPDL}")
logging.info(f"[CONFIG] KPM_COL_THPUL = {KPM_COL_THPUL}")
logging.info(f"[CONFIG] KPM_COL_VOLUL = {KPM_COL_VOLUL}")

# incoming queue from socket listener
data_queue = Queue()

# ---------------------------------------------------------
# Routing state (updated by poll thread)
# ---------------------------------------------------------
routing_lock  = threading.Lock()
routing_table = {}   # class -> {"chain": name, "host": host, "port": port}
chain_sockets = {}   # chain_name -> socket


def fetch_routing_table():
    """Fetch routing table from orchestrator. Returns dict or None on failure."""
    try:
        r = requests.get(
            f"http://{ORCH_HOST}:{ORCH_PORT}/routing", timeout=3
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logging.warning(f"[SmartGW] Failed to fetch routing from orchestrator: {e}")
    return None


def poll_orchestrator():
    """Background thread: periodically refresh routing table and open connections to new chains."""
    global routing_table, chain_sockets

    while True:
        new_routing = fetch_routing_table()
        if new_routing:
            with routing_lock:
                for cls, info in new_routing.items():
                    name = info["chain"]
                    if name not in chain_sockets:
                        try:
                            chain_sockets[name] = connect_socket(
                                info["host"], info["port"], name
                            )
                        except Exception as e:
                            logging.warning(
                                f"[SmartGW] Could not connect to chain '{name}': {e}"
                            )
                routing_table = new_routing
            logging.info(f"[SmartGW] Routing table refreshed: {list(routing_table.keys())}")

        time.sleep(ORCH_POLL_INTERVAL)

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
    centroids = model["centroids"]
    centroid_to_class = model["centroid_to_class"]

    # extract to correct order
    x = np.array([x_raw[col] for col in feature_cols], dtype=float)

    # 2. log transform
    if log_method == "log1p":
        x = np.log1p(np.maximum(x, 0))
    elif log_method == "log":
        x = np.log(np.maximum(x, 1e-9))
    elif log_method == "sqrt":
        x = np.sqrt(np.maximum(x, 0))

    # 3. scale
    x = fast_scale(x, scaler)

    # 4. assign cluster
    dists = np.sum((centroids - x) ** 2, axis=1)
    c = int(np.argmin(dists))

    # 5. centroid -> class
    return ["eMBB", "mMTC", "UNKNOWN", "URLLC-mMTC", "URLLC-eMBB"][c] if c < 5 else 'UNKNOWN'
    # return "eMBB-URLLC" if centroid_to_class[c] == 0 else "mMTC-URLLC"


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
                        "DRB.PdcpSduVolumeUL": float(parts[KPM_COL_VOLUL]),
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

    while True:
        x_raw, full_row, _ = data_queue.get()

        start = time.perf_counter()
        try:
            prediction = smartgw_predict_ultrafast(x_raw, model)
        except Exception as e:
            logging.exception(f"Prediction failed: {e}")
            data_queue.task_done()
            continue
        latency_ms = (time.perf_counter() - start) * 1000

        logging.info(
            f"[SmartGW] Class={prediction}  Latency={latency_ms:.3f} ms  UE-Features={x_raw}"
        )

        with routing_lock:
            route = routing_table.get(prediction)
            if route is None:
                logging.warning(
                    f"[SmartGW] No route for class '{prediction}', dropping row"
                )
                data_queue.task_done()
                continue
            chain_name = route["chain"]
            sock = chain_sockets.get(chain_name)

        if sock is None:
            logging.warning(
                f"[SmartGW] No socket for chain '{chain_name}', dropping row"
            )
            data_queue.task_done()
            continue

        try:
            send_to_socket(sock, full_row + "\n")
        except Exception as e:
            logging.error(f"[SmartGW] Forwarding to '{chain_name}' failed: {e}")
            try:
                new_sock = connect_socket(route["host"], route["port"], chain_name)
                with routing_lock:
                    chain_sockets[chain_name] = new_sock
                send_to_socket(new_sock, full_row + "\n")
            except Exception as e2:
                logging.error(f"[SmartGW] Retry forward to '{chain_name}' failed: {e2}")
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
    control_sck = open_control_socket(PORT)

    # initial routing fetch
    initial = fetch_routing_table()
    if initial:
        for cls, info in initial.items():
            name = info["chain"]
            if name not in chain_sockets:
                chain_sockets[name] = connect_socket(info["host"], info["port"], name)
        routing_table.update(initial)
        logging.info(f"[SmartGW] Initial routing loaded: {list(routing_table.keys())}")
    else:
        logging.warning("[SmartGW] Orchestrator unavailable at startup, routing table empty")

    Thread(target=socket_listener,    args=(control_sck,), daemon=True).start()
    Thread(target=classification_worker,                   daemon=True).start()
    Thread(target=poll_orchestrator,                       daemon=True).start()

    app.run(host="0.0.0.0", port=5004)
