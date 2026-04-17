#!/usr/bin/env python3
"""
SmartGW Demo Server

Receives KPM rows from tractor-kpm-oai and broadcasts them to all
currently selected model chains. No classification — every row is
forwarded to all active chains simultaneously.

Active chains are determined by polling SELECTED_MODELS_FILE written
by the universal-agent sidecar (AGENT_MODE=file).

Model → chain mapping:
  fastinfer   → xchain-fastinfer  (port FASTINFER_PORT)
  cnn         → tractor-mono      (port TRACTOR_PORT)
  lstm        → xchain-lstm       (port LSTM_PORT)
  gnn         → xchain-gnn        (port GNN_PORT)
"""
import time
import logging
import socket
import os
import threading
from queue import Queue
from threading import Thread

from xapp_control import open_control_socket, receive_from_socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Environment variables ──────────────────────────────────────────────────────
PORT                  = int(os.getenv("PORT", "4200"))
SELECTED_MODELS_FILE  = os.getenv("SELECTED_MODELS_FILE",  "/tmp/selected_models.txt")
MODELS_POLL_INTERVAL  = int(os.getenv("MODELS_POLL_INTERVAL", "2"))

FASTINFER_HOST = os.getenv("FASTINFER_HOST", "xchain-fastinfer")
FASTINFER_PORT = int(os.getenv("FASTINFER_PORT", "4400"))

TRACTOR_HOST = os.getenv("TRACTOR_HOST", "tractor-mono")
TRACTOR_PORT = int(os.getenv("TRACTOR_PORT", "4300"))

LSTM_HOST = os.getenv("LSTM_HOST", "xchain-lstm")
LSTM_PORT = int(os.getenv("LSTM_PORT", "4600"))

GNN_HOST = os.getenv("GNN_HOST", "xchain-gnn")
GNN_PORT = int(os.getenv("GNN_PORT", "4500"))

logging.info(f"[CONFIG] PORT                 = {PORT}")
logging.info(f"[CONFIG] SELECTED_MODELS_FILE = {SELECTED_MODELS_FILE}")
logging.info(f"[CONFIG] MODELS_POLL_INTERVAL = {MODELS_POLL_INTERVAL}s")
logging.info(f"[CONFIG] FASTINFER            = {FASTINFER_HOST}:{FASTINFER_PORT}")
logging.info(f"[CONFIG] TRACTOR              = {TRACTOR_HOST}:{TRACTOR_PORT}")
logging.info(f"[CONFIG] LSTM                 = {LSTM_HOST}:{LSTM_PORT}")
logging.info(f"[CONFIG] GNN                  = {GNN_HOST}:{GNN_PORT}")

# ── Chain registry — all known chains ─────────────────────────────────────────
# Maps model name (from GUI) → chain connection info
MODEL_TO_CHAIN = {
    "fastinfer": {"chain": "fastinfer", "host": FASTINFER_HOST, "port": FASTINFER_PORT},
    "cnn":       {"chain": "tractor",   "host": TRACTOR_HOST,   "port": TRACTOR_PORT},
    "lstm":      {"chain": "lstm",      "host": LSTM_HOST,      "port": LSTM_PORT},
    "gnn":       {"chain": "gnn",       "host": GNN_HOST,       "port": GNN_PORT},
}

# ── State ──────────────────────────────────────────────────────────────────────
data_queue    = Queue()
chains_lock   = threading.Lock()
all_sockets   = {}    # chain_name -> socket (all connected at startup)
active_chains = set() # chain names currently selected for forwarding
_last_models  = None  # track last file content to detect changes


# ── Socket helpers ─────────────────────────────────────────────────────────────

def connect_socket(host, port, label):
    """Connect with retry backoff. Returns a connected socket."""
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.settimeout(None)
            logging.info(f"[SmartGW] Connected to {label} at {host}:{port}")
            return s
        except Exception as e:
            logging.warning(f"[SmartGW] Cannot connect to {label} at {host}:{port}: {e}. Retrying in 2s.")
            try:
                s.close()
            except Exception:
                pass
            time.sleep(2)


def send_to_socket(sock, message: str):
    try:
        sock.sendall(message.encode("utf-8"))
    except Exception as e:
        logging.error(f"[SmartGW] Socket send error: {e}")
        try:
            sock.close()
        except Exception:
            pass
        raise


def connect_all_chains():
    """Connect to all known chains at startup and keep connections open."""
    seen_chains = {}  # chain_name -> info (deduplicate cnn+lstm → tractor once)
    for _, info in MODEL_TO_CHAIN.items():
        seen_chains[info["chain"]] = {"host": info["host"], "port": info["port"]}

    for chain_name, conn in seen_chains.items():
        try:
            all_sockets[chain_name] = connect_socket(conn["host"], conn["port"], chain_name)
        except Exception as e:
            logging.warning(f"[SmartGW] Could not connect to chain '{chain_name}' at startup: {e}")


# ── File poll thread ───────────────────────────────────────────────────────────

def read_selected_models() -> list:
    try:
        with open(SELECTED_MODELS_FILE, "r") as f:
            content = f.read().strip()
        if not content:
            return []
        return [m.strip() for m in content.split(",") if m.strip()]
    except FileNotFoundError:
        return []
    except Exception as e:
        logging.warning(f"[SmartGW] Could not read models file: {e}")
        return []


def poll_selected_models_file():
    global active_chains, _last_models

    while True:
        models = read_selected_models()

        if models != _last_models:
            logging.info(f"[SmartGW] Model selection changed: {_last_models} → {models}")
            _last_models = models

            # resolve to unique chain names
            new_active = set()
            for m in models:
                info = MODEL_TO_CHAIN.get(m)
                if info is None:
                    logging.warning(f"[SmartGW] Unknown model '{m}', skipping")
                    continue
                new_active.add(info["chain"])

            with chains_lock:
                active_chains = new_active

            logging.info(f"[SmartGW] Active chains: {active_chains}")

        time.sleep(MODELS_POLL_INTERVAL)


# ── Socket listener — receives KPM rows from tractor-kpm-oai ──────────────────

def socket_listener(control_sck):
    logging.info("Socket listener started (receiving KPM rows)...")
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
                data_queue.put(line)

        except Exception as e:
            logging.exception(f"[SmartGW] Socket listener error: {e}")
            time.sleep(0.3)


# ── Forward worker — broadcast to all active chains ────────────────────────────

def forward_worker():
    logging.info("Forward worker running...")

    while True:
        line = data_queue.get()

        with chains_lock:
            targets = set(active_chains)

        if not targets:
            logging.debug("[SmartGW] No active chains — dropping row")
            data_queue.task_done()
            continue

        for chain_name in targets:
            sock = all_sockets.get(chain_name)
            if sock is None:
                logging.warning(f"[SmartGW] No socket for chain '{chain_name}', skipping")
                continue

            try:
                send_to_socket(sock, line + "\n")
            except Exception as e:
                logging.error(f"[SmartGW] Forward to '{chain_name}' failed: {e}")
                # find reconnect info
                conn = next(
                    ({"host": v["host"], "port": v["port"]}
                     for v in MODEL_TO_CHAIN.values()
                     if v["chain"] == chain_name),
                    None,
                )
                if conn:
                    try:
                        new_sock = connect_socket(conn["host"], conn["port"], chain_name)
                        all_sockets[chain_name] = new_sock
                        send_to_socket(new_sock, line + "\n")
                    except Exception as e2:
                        logging.error(f"[SmartGW] Retry to '{chain_name}' failed: {e2}")

        data_queue.task_done()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    connect_all_chains()

    Thread(target=socket_listener,          args=(open_control_socket(PORT),), daemon=True).start()
    Thread(target=forward_worker,                                               daemon=True).start()
    Thread(target=poll_selected_models_file,                                    daemon=True).start()

    logging.info("[SmartGW Demo] Running. Waiting for KPM rows and model selection...")

    # keep main thread alive
    while True:
        time.sleep(60)
