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
            # Build the set of chains needed by the new routing
            needed = {info["chain"]: info for info in new_routing.values()
                      if "host" in info}

            # Connect to any chain that has no live socket — outside the lock
            new_sockets = {}
            for name, info in needed.items():
                with routing_lock:
                    existing = chain_sockets.get(name)
                if existing is None:
                    new_sockets[name] = connect_socket(info["host"], info["port"], name)

            # Swap routing_table and patch chain_sockets atomically (brief lock)
            with routing_lock:
                chain_sockets.update(new_sockets)
                old_routing = routing_table.copy()
                routing_table = new_routing

            # Log only when routing_table actually changed
            changed = {cls: info["chain"] for cls, info in new_routing.items()
                       if old_routing.get(cls, {}).get("chain") != info.get("chain")}
            connected = [n for n in needed if chain_sockets.get(n) is not None]
            pending   = [n for n in needed if chain_sockets.get(n) is None]
            if changed:
                logging.info(f"[SmartGW] Routing changed: {changed}")
            logging.info(f"[SmartGW] Routing active — chains: connected={connected}  pending={pending}")

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


def connect_socket(host, port, label, max_retries=3, retry_interval=2):
    """
    Try up to max_retries times. Returns a connected socket or None.
    Callers should treat None as "not yet reachable — retry on next poll".
    """
    for attempt in range(1, max_retries + 1):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.settimeout(None)
            logging.info(f"[SmartGW] Connected to {label} at {host}:{port}")
            return s
        except Exception as e:
            logging.warning(
                f"[SmartGW] Connection to {label} at {host}:{port} failed "
                f"(attempt {attempt}/{max_retries}): {e}"
            )
            try:
                s.close()
            except Exception:
                pass
            if attempt < max_retries:
                time.sleep(retry_interval)
    logging.warning(f"[SmartGW] Giving up on {label} — will retry on next routing poll")
    return None


def classification_worker():
    logging.info("Classifier worker running...")

    while True:
        x_raw, full_row, _ = data_queue.get()

        start = time.perf_counter()
        try:
            if x_raw.get("DRB.UEThpUl", 0) == 0 and x_raw.get("DRB.UEThpDl", 0) == 0 and x_raw.get("DRB.PdcpSduVolumeUL", 0) == 0:
                prediction = "UNKNOWN"
            else:
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
            new_sock = connect_socket(route["host"], route["port"], chain_name)
            with routing_lock:
                chain_sockets[chain_name] = new_sock  # None if unreachable
            if new_sock is not None:
                try:
                    send_to_socket(new_sock, full_row + "\n")
                except Exception as e2:
                    logging.error(f"[SmartGW] Retry forward to '{chain_name}' failed: {e2}")
            else:
                logging.warning(f"[SmartGW] Chain '{chain_name}' unreachable — dropping row, will reconnect on next poll")
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

    # initial routing fetch — connect outside any lock; failed chains retried by poll_orchestrator
    initial = fetch_routing_table()
    if initial:
        needed = {info["chain"]: info for info in initial.values() if "host" in info}
        for name, info in needed.items():
            chain_sockets[name] = connect_socket(info["host"], info["port"], name)
        routing_table.update(initial)
        connected = [n for n, s in chain_sockets.items() if s is not None]
        pending   = [n for n in needed if chain_sockets.get(n) is None]
        logging.info(f"[SmartGW] Initial routing — connected={connected}  pending={pending}")
        logging.info(f"[SmartGW] Routes: { {cls: info.get('chain') for cls, info in initial.items()} }")
    else:
        logging.warning("[SmartGW] Orchestrator unavailable at startup, routing table empty")

    Thread(target=socket_listener,    args=(control_sck,), daemon=True).start()
    Thread(target=classification_worker,                   daemon=True).start()
    Thread(target=poll_orchestrator,                       daemon=True).start()

    app.run(host="0.0.0.0", port=5004)
