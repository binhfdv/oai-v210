#!/usr/bin/env python3
"""
SmartGW Demo Server

Receives KPM rows from tractor-kpm-oai and broadcasts them to all
currently selected model chains. No classification — every row is
forwarded to all active chains simultaneously.

Active chains are determined by polling SELECTED_MODELS_FILE written
by the universal-agent sidecar (AGENT_MODE=file).

Model registry is driven entirely by env vars — no code changes needed
to add or remove models:

  MODELS=fastinfer,cnn,lstm,gnn        # comma-separated list of active models
  MODEL_<NAME>_HOST=<hostname>         # e.g. MODEL_FASTINFER_HOST=xchain-fastinfer
  MODEL_<NAME>_PORT=<port>             # e.g. MODEL_FASTINFER_PORT=4400

Example — add a new model "rnn":
  MODELS=fastinfer,gnn,rnn
  MODEL_RNN_HOST=xchain-rnn
  MODEL_RNN_PORT=4700
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
PORT                 = int(os.getenv("PORT", "4200"))
SELECTED_MODELS_FILE = os.getenv("SELECTED_MODELS_FILE", "/tmp/selected_models.txt")
MODELS_POLL_INTERVAL = int(os.getenv("MODELS_POLL_INTERVAL", "2"))

logging.info(f"[CONFIG] PORT                 = {PORT}")
logging.info(f"[CONFIG] SELECTED_MODELS_FILE = {SELECTED_MODELS_FILE}")
logging.info(f"[CONFIG] MODELS_POLL_INTERVAL = {MODELS_POLL_INTERVAL}s")

# ── Dynamic model registry ─────────────────────────────────────────────────────
# MODELS env var: comma-separated list of model names to register.
# For each name, reads MODEL_<NAME>_HOST and MODEL_<NAME>_PORT.
# Falls back to sensible defaults: host=xchain-<name>, port from CHAIN_DEFAULT_PORTS.
CHAIN_DEFAULT_PORTS = {
    "fastinfer": 4400,
    "cnn":       4300,
    "lstm":      4600,
    "gnn":       4500,
}

_models_env = os.getenv("MODELS", "fastinfer,cnn,lstm,gnn")
_model_names = [m.strip() for m in _models_env.split(",") if m.strip()]

MODEL_TO_CHAIN = {}
for _name in _model_names:
    _key = _name.upper()
    _host = os.getenv(f"MODEL_{_key}_HOST", f"xchain-{_name}")
    _port = int(os.getenv(f"MODEL_{_key}_PORT", str(CHAIN_DEFAULT_PORTS.get(_name, 5000))))
    MODEL_TO_CHAIN[_name] = {"host": _host, "port": _port}
    logging.info(f"[CONFIG] model={_name:12s}  host={_host}  port={_port}")

# ── State ──────────────────────────────────────────────────────────────────────
data_queue    = Queue()
chains_lock   = threading.Lock()
all_sockets   = {}    # model_name -> socket
active_chains = set() # model names currently selected for forwarding
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
    """Connect to all registered models at startup."""
    for model_name, info in MODEL_TO_CHAIN.items():
        try:
            all_sockets[model_name] = connect_socket(info["host"], info["port"], model_name)
        except Exception as e:
            logging.warning(f"[SmartGW] Could not connect to '{model_name}' at startup: {e}")


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

            new_active = set()
            for m in models:
                if m not in MODEL_TO_CHAIN:
                    logging.warning(f"[SmartGW] Unknown model '{m}', skipping")
                    continue
                new_active.add(m)

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

        for model_name in targets:
            sock = all_sockets.get(model_name)
            if sock is None:
                logging.warning(f"[SmartGW] No socket for '{model_name}', skipping")
                continue

            try:
                send_to_socket(sock, line + "\n")
            except Exception as e:
                logging.error(f"[SmartGW] Forward to '{model_name}' failed: {e}")
                info = MODEL_TO_CHAIN.get(model_name)
                if info:
                    try:
                        new_sock = connect_socket(info["host"], info["port"], model_name)
                        all_sockets[model_name] = new_sock
                        send_to_socket(new_sock, line + "\n")
                    except Exception as e2:
                        logging.error(f"[SmartGW] Retry to '{model_name}' failed: {e2}")

        data_queue.task_done()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    connect_all_chains()

    Thread(target=socket_listener,          args=(open_control_socket(PORT),), daemon=True).start()
    Thread(target=forward_worker,                                               daemon=True).start()
    Thread(target=poll_selected_models_file,                                    daemon=True).start()

    logging.info("[SmartGW Demo] Running. Waiting for KPM rows and model selection...")

    while True:
        time.sleep(60)
