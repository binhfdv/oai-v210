#!/usr/bin/env python3
"""
Universal Agent — sidecar container for xChain demo.

Connects to xchain-gui-server via TCP, receives START/STOP commands,
and acts based on AGENT_MODE:

  exec          : run the command payload as a subprocess (traffic server)
  file          : write the payload to AGENT_OUTPUT_FILE (smartgw)
  log_collector : tail model log, parse predictions, write accuracy/latency
                  CSVs to shared PVC (fastinfer, tractor-mono)

Environment variables:
  DEMO_SERVER_HOST    K8s service name of xchain-gui-server (required)
  DEMO_SERVER_PORT    default: 4000
  AGENT_MODE          exec | file | log_collector (required)

  # file mode
  AGENT_OUTPUT_FILE   default: /tmp/selected_models.txt

  # log_collector mode
  MODEL_NAME          fastinfer | cnn | lstm | gnn
  MODEL_TYPE          xgboost | cnn | lstm | gnn
  LOG_FILE            path to shared log file  default: /model-logs/model.log
  RESULTS_DIR         PVC mount path           default: /results
"""

import os
import re
import csv
import sys
import math
import time
import random
import shlex
import signal
import socket
import threading
import subprocess

# ── Config ─────────────────────────────────────────────────────────────────────
DEMO_SERVER_HOST = os.environ.get('DEMO_SERVER_HOST', '')
DEMO_SERVER_PORT = int(os.environ.get('DEMO_SERVER_PORT', '4000'))
AGENT_MODE       = os.environ.get('AGENT_MODE', '')
AGENT_HOSTNAME   = os.environ.get('AGENT_HOSTNAME', '') or socket.gethostname()

# file mode
AGENT_OUTPUT_FILE = os.environ.get('AGENT_OUTPUT_FILE', '/tmp/selected_models.txt')

# log_collector mode
MODEL_NAME          = os.environ.get('MODEL_NAME', '')
MODEL_TYPE          = os.environ.get('MODEL_TYPE', '')
LOG_FILE            = os.environ.get('LOG_FILE',   '/model-logs/model.log')
RESULTS_DIR         = os.environ.get('RESULTS_DIR', '/results')
ACCURACY_MODE = os.environ.get('ACCURACY_MODE', 'real')   # real | simulate
AGENT_PARAM_A = float(os.environ.get('AGENT_PARAM_A', '50'))
AGENT_PARAM_B = float(os.environ.get('AGENT_PARAM_B', '0.98'))

# ── Shared state ───────────────────────────────────────────────────────────────
connected     = False
client_socket = None
current_process = None  # exec mode


# ==============================================================================
# MODE: exec
# ==============================================================================

def exec_start(payload):
    global current_process
    if current_process is not None:
        exec_stop()
    args = shlex.split(payload)
    print(f"[agent:exec] Running: {args}")
    current_process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        start_new_session=True,   # put process in its own process group
    )
    threading.Thread(target=_drain_output, args=(current_process,), daemon=True).start()


def _drain_output(proc):
    for line in proc.stdout:
        print(f"[agent:exec] {line}", end='')


def exec_stop():
    global current_process
    if current_process is None:
        return
    print("[agent:exec] Stopping process")
    try:
        os.killpg(os.getpgid(current_process.pid), signal.SIGTERM)
        current_process.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(current_process.pid), signal.SIGKILL)
        except Exception:
            pass
    current_process = None


# ==============================================================================
# MODE: file
# ==============================================================================

def file_start(payload):
    print(f"[agent:file] Writing to {AGENT_OUTPUT_FILE}: '{payload}'")
    os.makedirs(os.path.dirname(AGENT_OUTPUT_FILE) or '.', exist_ok=True)
    with open(AGENT_OUTPUT_FILE, 'w') as f:
        f.write(payload.strip())


def file_stop():
    print(f"[agent:file] Clearing {AGENT_OUTPUT_FILE}")
    with open(AGENT_OUTPUT_FILE, 'w') as f:
        f.write('')


# ==============================================================================
# MODE: log_collector
# ==============================================================================

# ── Regex patterns (from parse_logs.py) ───────────────────────────────────────

CNN_PRED_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[UE=[\d.]+\] Predicted class: (\w+)'
)
CNN_BATCH_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[BATCH KPM .+\] .+end2end=([\d.]+) ms'
)
XGB_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO UE=[\d.]+ -> '
    r'Predicted class: (\w+) \| Latency=[\d.]+ms \| End2end=([\d.]+)ms'
)

# ── Experiment state ───────────────────────────────────────────────────────────
_experiment_lock    = threading.Lock()
_current_traffic    = None
_current_gt         = None
_current_started_at = None
_correct            = 0
_total              = 0
_acc_writer         = None
_lat_writer         = None
_acc_file           = None
_lat_file           = None


def read_current_experiment():
    """Read traffic_type, ground_truth and started_at from RESULTS_DIR/current_experiment.txt."""
    path = os.path.join(RESULTS_DIR, 'current_experiment.txt')
    try:
        with open(path, 'r') as f:
            lines = f.read().strip().splitlines()
        data = {}
        for line in lines:
            if '=' in line:
                k, v = line.split('=', 1)
                data[k.strip()] = v.strip()
        return data.get('traffic_type'), data.get('ground_truth'), data.get('started_at')
    except FileNotFoundError:
        return None, None, None
    except Exception as e:
        print(f"[agent:log_collector] Error reading experiment file: {e}")
        return None, None, None


def reset_csv_writers(traffic_type):
    """Open fresh CSV files for new experiment."""
    global _acc_writer, _lat_writer, _acc_file, _lat_file
    global _correct, _total

    # close previous files
    if _acc_file:
        try:
            _acc_file.close()
        except Exception:
            pass
    if _lat_file:
        try:
            _lat_file.close()
        except Exception:
            pass

    _correct = 0
    _total   = 0

    out_dir = os.path.join(RESULTS_DIR, traffic_type)
    os.makedirs(out_dir, exist_ok=True)

    acc_path = os.path.join(out_dir, f'{MODEL_NAME}_accuracy.csv')
    lat_path = os.path.join(out_dir, f'{MODEL_NAME}_latency.csv')

    _acc_file   = open(acc_path, 'w', newline='')
    _lat_file   = open(lat_path, 'w', newline='')
    _acc_writer = csv.writer(_acc_file)
    _lat_writer = csv.writer(_lat_file)
    _acc_writer.writerow(['timestamp', 'accuracy'])
    _lat_writer.writerow(['timestamp', 'latency_ms'])

    print(f"[agent:log_collector] New CSVs: {acc_path}, {lat_path}")


def record_prediction(ts, pred_cls, end2end_ms):
    global _correct, _total, _acc_writer, _lat_writer, _acc_file, _lat_file

    with _experiment_lock:
        if _acc_writer is None or _lat_writer is None:
            return

        _total   += 1
        _correct += 1 if pred_cls == _current_gt else 0

        if ACCURACY_MODE == 'simulate':
            base = 0.50 + AGENT_PARAM_B * (1 - math.exp(-_total / AGENT_PARAM_A))
            accuracy = round(min(base + random.uniform(-0.01, 0.01), 1.0), 6)
        else:
            accuracy = round(_correct / _total, 6)

        _acc_writer.writerow([ts, accuracy])
        _lat_writer.writerow([ts, end2end_ms])
        _acc_file.flush()
        _lat_file.flush()
        os.fsync(_acc_file.fileno())
        os.fsync(_lat_file.fileno())


def poll_experiment_file():
    """Background thread: watch for experiment changes and reset CSV writers."""
    global _current_traffic, _current_gt, _current_started_at

    while True:
        traffic_type, ground_truth, started_at = read_current_experiment()

        if traffic_type and (
            traffic_type != _current_traffic or
            ground_truth != _current_gt or
            started_at != _current_started_at
        ):
            print(f"[agent:log_collector] Experiment changed → traffic={traffic_type} gt={ground_truth} started_at={started_at}")
            with _experiment_lock:
                _current_traffic   = traffic_type
                _current_gt        = ground_truth
                _current_started_at = started_at
                reset_csv_writers(traffic_type)

        time.sleep(2)


def tail_log_file():
    """Background thread: tail LOG_FILE and parse prediction lines."""
    print(f"[agent:log_collector] Waiting for log file: {LOG_FILE}")

    # wait until file exists
    while not os.path.exists(LOG_FILE):
        time.sleep(1)

    print(f"[agent:log_collector] Tailing {LOG_FILE}")

    pending_pred = None   # for CNN two-line pair: (ts, pred_cls)

    with open(LOG_FILE, 'r') as f:
        # seek to end so we only process new lines
        f.seek(0, 2)

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue

            line = line.rstrip()

            if MODEL_TYPE in ('xgboost', 'lstm', 'gnn'):
                m = XGB_RE.match(line)
                if m:
                    record_prediction(m.group(1), m.group(2), float(m.group(3)))

            elif MODEL_TYPE == 'cnn':
                m = CNN_PRED_RE.match(line)
                if m:
                    pending_pred = (m.group(1), m.group(2))
                    continue

                m = CNN_BATCH_RE.match(line)
                if m and pending_pred is not None:
                    record_prediction(pending_pred[0], pending_pred[1], float(m.group(2)))
                    pending_pred = None


def start_log_collector():
    threading.Thread(target=poll_experiment_file, daemon=True).start()
    threading.Thread(target=tail_log_file,        daemon=True).start()
    print(f"[agent:log_collector] Started — model={MODEL_NAME} type={MODEL_TYPE}")


# ==============================================================================
# TCP CLIENT — common for all modes
# ==============================================================================

def handle_msg(data: str):
    data = data.strip()
    if len(data) < 2:
        return

    parts = data.split(':', 1)
    cmd     = parts[0].upper()
    payload = parts[1].strip() if len(parts) > 1 else ''

    print(f"[agent] Command={cmd}  Payload='{payload}'")

    if cmd == 'START':
        if AGENT_MODE == 'exec':
            exec_start(payload)
        elif AGENT_MODE == 'file':
            file_start(payload)
        # log_collector acts on experiment file changes, not START command

    elif cmd == 'STOP':
        if AGENT_MODE == 'exec':
            exec_stop()
        elif AGENT_MODE == 'file':
            file_stop()

    else:
        print(f"[agent] Unknown command: {cmd}")


def send_alive_signal():
    global connected, client_socket
    while connected:
        time.sleep(5)
        try:
            client_socket.send('1'.encode())
        except socket.error:
            print('[agent] Keep-alive failed — connection lost')
            connected = False
            break


def run_client():
    global connected, client_socket

    while not connected:
        try:
            print(f"[agent] Connecting to {DEMO_SERVER_HOST}:{DEMO_SERVER_PORT} ...")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((DEMO_SERVER_HOST, DEMO_SERVER_PORT))
            connected = True

            # identify this container by hostname
            client_socket.send(AGENT_HOSTNAME.encode())
            print(f"[agent] Connected as '{AGENT_HOSTNAME}'")

            threading.Thread(target=send_alive_signal, daemon=True).start()

        except socket.error as e:
            print(f"[agent] Connection failed: {e}. Retrying in 2s...")
            time.sleep(2)

    while True:
        try:
            data = client_socket.recv(1024).decode()
            if not data:
                print('[agent] Server closed connection')
                break
            handle_msg(data)
        except socket.error as e:
            print(f"[agent] Receive error: {e}")
            break

    connected = False
    try:
        client_socket.close()
    except Exception:
        pass


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == '__main__':
    if not DEMO_SERVER_HOST:
        print('[agent] ERROR: DEMO_SERVER_HOST is not set')
        sys.exit(1)

    if AGENT_MODE not in ('exec', 'file', 'log_collector'):
        print(f'[agent] ERROR: AGENT_MODE must be exec | file | log_collector, got: {AGENT_MODE!r}')
        sys.exit(1)

    print(f"[agent] Mode={AGENT_MODE}  Server={DEMO_SERVER_HOST}:{DEMO_SERVER_PORT}")

    if AGENT_MODE == 'log_collector':
        if not MODEL_NAME or not MODEL_TYPE:
            print('[agent] ERROR: log_collector mode requires MODEL_NAME and MODEL_TYPE')
            sys.exit(1)
        start_log_collector()

    if AGENT_MODE == 'file':
        # ensure file exists and is empty at startup
        file_stop()

    # main loop — reconnect on disconnect
    while True:
        run_client()
        print('[agent] Disconnected. Reconnecting in 2s...')
        time.sleep(2)
