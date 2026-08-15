#!/usr/bin/env python3
"""
Universal Agent — xChain sidecar container.

AGENT_MODE selects the operating mode:

  exec          : run a command payload as a subprocess           (demo)
  file          : write a payload to AGENT_OUTPUT_FILE            (demo)
  log_collector : tail model log, parse predictions, write CSVs   (demo)
  preprocessing : pass-through inbound gateway for TRACTOR        (journal)
  filtering     : DDM-based skip/complaint gate for UNICORN        (journal)
  enhancer      : online KPM denoising sidecar before CNN/XGBoost (journal)

Journal modes expose an HTTP server; demo modes connect to xchain-gui-server via TCP.

Environment variables — common:
  AGENT_MODE          exec | file | log_collector | preprocessing | filtering | enhancer

Environment variables — preprocessing mode:
  AGENT_PORT          HTTP port this agent listens on              default: 5100
  MODEL_HOST          TRACTOR model host (localhost in sidecar)    default: localhost
  MODEL_PORT          TRACTOR model HTTP port                      default: 5000
  PEER_AGENT_HOST     Filtering agent host (xchain-unicorn)        default: ""
  PEER_AGENT_PORT     Filtering agent HTTP port                    default: 5101

Environment variables — filtering mode:
  AGENT_PORT          HTTP port this agent listens on              default: 5101
  MODEL_HOST          UNICORN model host (localhost in sidecar)    default: localhost
  MODEL_PORT          UNICORN model HTTP port                      default: 5004
  PEER_AGENT_HOST     Preprocessing agent host (tractor-mono)      default: ""
  PEER_AGENT_PORT     Preprocessing agent HTTP port                default: 5100
  CONTEXT_LABEL       Operator-set overlap context                 default: urllc-mmtc
  DRIFT_DETECTOR      none | ddm | adwin | eddm | ph               default: ddm
  URLLC_CLASS         Expected TRACTOR label for URLLC traffic      default: URLLC

Environment variables — enhancer mode:
  AGENT_DATA_PORT     TCP port to receive rows from SmartGW        default: 4301
  ENHANCER_OUT_HOST   Downstream model host (required)
  ENHANCER_OUT_PORT   Downstream model TCP port                    default: 4300
  ENHANCER_SKIP_COLS  Comma-separated column indices to skip       default: 0,1,2,3,4
  IMPUTE_ENABLED      Forward-fill zeros per feature per UE        default: true
  SMOOTH_ALPHA        EMA alpha (0=disabled)                       default: 0.3
  CLIP_SIGMA          Clip at mean±k*std (0=disabled)              default: 3.0
  CLIP_WARMUP         Rows before clipping activates per UE        default: 20

Environment variables — demo modes:
  DEMO_SERVER_HOST    xchain-gui-server hostname (required)
  DEMO_SERVER_PORT    default: 4000
  AGENT_HOSTNAME      default: container hostname
  AGENT_OUTPUT_FILE   (file mode)  default: /tmp/selected_models.txt
  MODEL_NAME          (log_collector mode)
  MODEL_TYPE          (log_collector mode)
  LOG_FILE            (log_collector mode)  default: /model-logs/model.log
  RESULTS_DIR         (log_collector mode)  default: /results
"""

import os
import re
import csv
import json
import sys
import math
import time
import random
import shlex
import signal
import socket
import threading
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Common config ──────────────────────────────────────────────────────────────
AGENT_MODE = os.environ.get('AGENT_MODE', '')
AGENT_PORT       = int(os.environ.get('AGENT_PORT',       '5100'))
AGENT_DATA_PORT  = int(os.environ.get('AGENT_DATA_PORT',  '4301'))  # TCP, receives rows from SmartGW


# ── Demo-mode config ───────────────────────────────────────────────────────────
DEMO_SERVER_HOST  = os.environ.get('DEMO_SERVER_HOST', '')
DEMO_SERVER_PORT  = int(os.environ.get('DEMO_SERVER_PORT', '4000'))
AGENT_HOSTNAME    = os.environ.get('AGENT_HOSTNAME', '') or socket.gethostname()
AGENT_OUTPUT_FILE = os.environ.get('AGENT_OUTPUT_FILE', '/tmp/selected_models.txt')
MODEL_NAME        = os.environ.get('MODEL_NAME', '')
MODEL_TYPE        = os.environ.get('MODEL_TYPE', '')
LOG_FILE          = os.environ.get('LOG_FILE',   '/model-logs/model.log')
RESULTS_DIR       = os.environ.get('RESULTS_DIR', '/results')
ACCURACY_MODE     = os.environ.get('ACCURACY_MODE', 'real')
AGENT_PARAM_A     = float(os.environ.get('AGENT_PARAM_A', '50'))
AGENT_PARAM_B     = float(os.environ.get('AGENT_PARAM_B', '0.98'))

# ── Enhancer-mode config ──────────────────────────────────────────────────────
ENHANCER_OUT_HOST  = os.environ.get('ENHANCER_OUT_HOST', '')
ENHANCER_OUT_PORT  = int(os.environ.get('ENHANCER_OUT_PORT', '4300'))
ENHANCER_SKIP_COLS = {int(c) for c in os.environ.get('ENHANCER_SKIP_COLS', '0,1,2,3,4').split(',')}
IMPUTE_ENABLED     = os.environ.get('IMPUTE_ENABLED', 'true').lower() == 'true'
SMOOTH_ALPHA       = float(os.environ.get('SMOOTH_ALPHA', '0.3'))
CLIP_SIGMA         = float(os.environ.get('CLIP_SIGMA',  '3.0'))
CLIP_WARMUP        = int(os.environ.get('CLIP_WARMUP',   '20'))

# ── Journal-mode config ────────────────────────────────────────────────────────
MODEL_HOST       = os.environ.get('MODEL_HOST',       'localhost')
MODEL_PORT       = os.environ.get('MODEL_PORT',       '5000')
PEER_AGENT_HOST  = os.environ.get('PEER_AGENT_HOST',  '')
PEER_AGENT_PORT  = os.environ.get('PEER_AGENT_PORT',  '5101')
CONTEXT_LABEL    = os.environ.get('CONTEXT_LABEL',    'urllc-mmtc')
DRIFT_DETECTOR   = os.environ.get('DRIFT_DETECTOR', 'ddm').lower()
URLLC_CLASS      = os.environ.get('URLLC_CLASS', 'URLLC')
# DDM/EDDM: lower thresholds → triggers faster (default: warning=2.0, drift=3.0)
DDM_WARNING_THRESHOLD = float(os.environ.get('DDM_WARNING_THRESHOLD', '2.0'))
DDM_DRIFT_THRESHOLD   = float(os.environ.get('DDM_DRIFT_THRESHOLD',   '3.0'))
# ADWIN: higher delta → triggers faster (default: 0.002)
ADWIN_DELTA           = float(os.environ.get('ADWIN_DELTA',           '0.002'))

# preprocessing-specific: must match TRACTOR's T and NCLASS env vars
TRACTOR_T            = int(os.environ.get('TRACTOR_T',     '16'))
TRACTOR_CLASS_NAMES  = os.environ.get('TRACTOR_CLASS_NAMES', 'eMBB,mMTC,URLLC,control').split(',')
# model cycling on complaint — comma-separated T values to rotate through
TRACTOR_T_OPTIONS    = [int(x) for x in os.environ.get('TRACTOR_T_OPTIONS', str(TRACTOR_T)).split(',')]
# model path pattern — {T} is replaced with the selected T value
TRACTOR_MODEL_PATH   = os.environ.get('TRACTOR_MODEL_PATH',   '/mnt/model/model.{T}.cnn.pt')
TRACTOR_MODEL_TYPE   = os.environ.get('TRACTOR_MODEL_TYPE',   'CNN')
TRACTOR_NUM_FEATS    = int(os.environ.get('TRACTOR_NUM_FEATS', '17'))
TRACTOR_NCLASS       = int(os.environ.get('TRACTOR_NCLASS',    '4'))

# mutable preprocessing state — updated on complaint
_preproc_state = {
    "T":        TRACTOR_T,
    "T_index":  TRACTOR_T_OPTIONS.index(TRACTOR_T) if TRACTOR_T in TRACTOR_T_OPTIONS else 0,
}

# per-UE window buffers: ue_id -> deque of normalized vectors
_ue_windows: dict = {}
_ue_windows_lock = threading.Lock()

# ── Demo shared state ──────────────────────────────────────────────────────────
connected        = False
client_socket    = None
current_process  = None


# ==============================================================================
# MODE: exec  (demo)
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
        start_new_session=True,
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
# MODE: file  (demo)
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
# MODE: log_collector  (demo)
# ==============================================================================

CNN_PRED_RE  = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[UE=[\d.]+\] Predicted class: (\w+)')
CNN_BATCH_RE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[BATCH KPM .+\] .+end2end=([\d.]+) ms')
XGB_RE       = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO UE=[\d.]+ -> '
    r'Predicted class: (\w+) \| Latency=[\d.]+ms \| End2end=([\d.]+)ms'
)

_experiment_lock     = threading.Lock()
_current_traffic     = None
_current_gt          = None
_current_started_at  = None
_correct             = 0
_total               = 0
_acc_writer          = None
_lat_writer          = None
_acc_file            = None
_lat_file            = None


def read_current_experiment():
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
    global _acc_writer, _lat_writer, _acc_file, _lat_file, _correct, _total
    for fh in (_acc_file, _lat_file):
        if fh:
            try:
                fh.close()
            except Exception:
                pass
    _correct = _total = 0
    out_dir  = os.path.join(RESULTS_DIR, traffic_type)
    os.makedirs(out_dir, exist_ok=True)
    _acc_file   = open(os.path.join(out_dir, f'{MODEL_NAME}_accuracy.csv'), 'w', newline='')
    _lat_file   = open(os.path.join(out_dir, f'{MODEL_NAME}_latency.csv'),  'w', newline='')
    _acc_writer = csv.writer(_acc_file)
    _lat_writer = csv.writer(_lat_file)
    _acc_writer.writerow(['timestamp', 'accuracy'])
    _lat_writer.writerow(['timestamp', 'latency_ms'])
    print(f"[agent:log_collector] New CSVs for traffic={traffic_type}")


def record_prediction(ts, pred_cls, end2end_ms):
    global _correct, _total
    with _experiment_lock:
        if _acc_writer is None or _lat_writer is None:
            return
        _total   += 1
        _correct += 1 if pred_cls == _current_gt else 0
        if ACCURACY_MODE == 'simulate':
            base     = 0.50 + AGENT_PARAM_B * (1 - math.exp(-_total / AGENT_PARAM_A))
            accuracy = round(min(base + random.uniform(-0.01, 0.01), 1.0), 6)
        else:
            accuracy = round(_correct / _total, 6)
        _acc_writer.writerow([ts, accuracy])
        _lat_writer.writerow([ts, end2end_ms])
        _acc_file.flush();  os.fsync(_acc_file.fileno())
        _lat_file.flush();  os.fsync(_lat_file.fileno())


def poll_experiment_file():
    global _current_traffic, _current_gt, _current_started_at
    while True:
        traffic_type, ground_truth, started_at = read_current_experiment()
        if traffic_type and (
            traffic_type != _current_traffic or
            ground_truth != _current_gt or
            started_at   != _current_started_at
        ):
            print(f"[agent:log_collector] Experiment changed → traffic={traffic_type} gt={ground_truth}")
            with _experiment_lock:
                _current_traffic    = traffic_type
                _current_gt         = ground_truth
                _current_started_at = started_at
                reset_csv_writers(traffic_type)
        time.sleep(2)


def tail_log_file():
    print(f"[agent:log_collector] Waiting for log file: {LOG_FILE}")
    while not os.path.exists(LOG_FILE):
        time.sleep(1)
    print(f"[agent:log_collector] Tailing {LOG_FILE}")
    pending_pred = None
    with open(LOG_FILE, 'r') as f:
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
# Demo TCP client — shared by exec / file / log_collector
# ==============================================================================

def handle_msg(data: str):
    data  = data.strip()
    if len(data) < 2:
        return
    parts   = data.split(':', 1)
    cmd     = parts[0].upper()
    payload = parts[1].strip() if len(parts) > 1 else ''
    print(f"[agent] Command={cmd}  Payload='{payload}'")
    if cmd == 'START':
        if AGENT_MODE == 'exec':   exec_start(payload)
        elif AGENT_MODE == 'file': file_start(payload)
    elif cmd == 'STOP':
        if AGENT_MODE == 'exec':   exec_stop()
        elif AGENT_MODE == 'file': file_stop()
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
# MODE: preprocessing  (journal)
# ==============================================================================

def _preprocessing_handle_row(req, raw_row: str, encoding: dict):
    """
    normalize (via TRACTOR /normalize) → window (agent-side buffer) → predict → forward.
    """
    base = f"http://{MODEL_HOST}:{MODEL_PORT}"

    # Parse CSV row into float list; non-numeric fields (e.g. timestamp) become 0.0
    parts = raw_row.split(',')
    kpi_raw = []
    for p in parts:
        try:
            kpi_raw.append(float(p.strip()))
        except ValueError:
            kpi_raw.append(0.0)

    ue_id = parts[2].strip() if len(parts) > 3 else "default"
    ts    = parts[0].strip() if parts else "?"

    logging.info(f"[preprocessing] ROW received  ue={ue_id}  ts={ts}  fields={len(parts)}")

    # Step 1: normalize via TRACTOR /normalize
    try:
        r = req.post(f"{base}/normalize", json={"kpi": kpi_raw}, timeout=5)
        normalized = r.json()["normalized"]
        logging.info(f"[preprocessing] NORMALIZE ok  ue={ue_id}  feats={len(normalized)}")
    except Exception as e:
        logging.warning(f"[preprocessing] NORMALIZE failed  ue={ue_id}  error={e}")
        return

    # Step 2: window buffer (agent-side, per UE) — T may change on complaint
    from collections import deque
    current_T = _preproc_state["T"]
    with _ue_windows_lock:
        if ue_id not in _ue_windows:
            _ue_windows[ue_id] = deque(maxlen=current_T)
        _ue_windows[ue_id].append(normalized)
        buf_len = len(_ue_windows[ue_id])

    logging.info(f"[preprocessing] BUFFER  ue={ue_id}  size={buf_len}/{current_T}")

    if buf_len < current_T:
        return  # window not full yet

    with _ue_windows_lock:
        window = list(_ue_windows[ue_id])

    window = list(_ue_windows[ue_id])

    # Step 3: predict via TRACTOR /predict
    try:
        r = req.post(f"{base}/predict", json={"window": window}, timeout=5)
        pred = r.json()
    except Exception as e:
        logging.warning(f"[preprocessing] PREDICT failed  ue={ue_id}  error={e}")
        return

    cls = pred.get("class", -1)
    traffic_type = TRACTOR_CLASS_NAMES[cls] if 0 <= cls < len(TRACTOR_CLASS_NAMES) else str(cls)
    result = {"class": cls, "traffic_type": traffic_type}

    logging.info(f"[preprocessing] PREDICT result  ue={ue_id}  class={cls}  traffic_type={traffic_type}")
    print("RESULT " + json.dumps({
        "event":        "tractor_predict",
        "t":            time.time(),
        "ue":           ue_id,
        "class":        cls,
        "traffic_type": traffic_type,
        "T":            _preproc_state["T"],
    }), flush=True)

    # Forward to filtering agent
    if PEER_AGENT_HOST:
        try:
            req.post(
                f"http://{PEER_AGENT_HOST}:{PEER_AGENT_PORT}/filter",
                json={"classification": result, "row": raw_row, "encoding": encoding},
                timeout=5,
            )
            logging.info(f"[preprocessing] FORWARD to filtering agent  ue={ue_id}"
                         f"  peer={PEER_AGENT_HOST}:{PEER_AGENT_PORT}")
        except Exception as e:
            logging.warning(f"[preprocessing] FORWARD failed  ue={ue_id}  error={e}")


def _preprocessing_tcp_listener():
    """TCP server: receives raw CSV rows from SmartGW (same protocol as model servers)."""
    import requests as req
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", AGENT_DATA_PORT))
    srv.listen(5)
    logging.info(f"[preprocessing] TCP listener on port {AGENT_DATA_PORT}")

    while True:
        try:
            conn, addr = srv.accept()
            logging.info(f"[preprocessing] TCP connection from {addr}")
            threading.Thread(
                target=_preprocessing_tcp_client,
                args=(req, conn),
                daemon=True,
            ).start()
        except Exception as e:
            logging.error(f"[preprocessing] TCP accept error: {e}")
            time.sleep(0.5)


def _preprocessing_tcp_client(req, conn):
    buffer = ""
    with conn:
        while True:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    threading.Thread(
                        target=_preprocessing_handle_row,
                        args=(req, line, {}),   # encoding={} placeholder
                        daemon=True,
                    ).start()
            except Exception as e:
                logging.warning(f"[preprocessing] TCP client error: {e}")
                break


def _make_preprocessing_http_app():
    from flask import Flask, request, jsonify
    import requests as req

    app = Flask("preprocessing-agent-http")

    @app.route("/infer", methods=["POST"])
    def infer():
        """Direct HTTP call path (e.g., for testing or orchestrator-level routing)."""
        data     = request.get_json(force=True) or {}
        kpm_row  = data.get("row", "")
        encoding = data.get("encoding", {})
        threading.Thread(
            target=_preprocessing_handle_row,
            args=(req, kpm_row, encoding),
            daemon=True,
        ).start()
        return '', 204

    @app.route("/complaint", methods=["POST"])
    def complaint():
        data = request.get_json(force=True) or {}
        reason  = data.get("reason", "")
        context = data.get("context", "")
        logging.warning(f"[preprocessing] Complaint received: reason={reason}  context={context}")

        if reason == "drift_detected" and len(TRACTOR_T_OPTIONS) > 1:
            old_idx = _preproc_state["T_index"]
            # Advance T — clamp at last option, do not wrap back to T=4
            new_idx = min(old_idx + 1, len(TRACTOR_T_OPTIONS) - 1)
            if new_idx == old_idx:
                logging.info("[preprocessing] Already at max T — complaint ignored")
                return jsonify({"status": "at_max_T"}), 200
            new_T   = TRACTOR_T_OPTIONS[new_idx]
            _preproc_state["T_index"] = new_idx
            _preproc_state["T"]       = new_T

            logging.warning(
                f"[preprocessing] Switching TRACTOR T: {TRACTOR_T_OPTIONS[old_idx]} → {new_T}"
                f"  (options={TRACTOR_T_OPTIONS})"
            )

            # Reset all per-UE windows so they rebuild with the new T
            with _ue_windows_lock:
                _ue_windows.clear()
            logging.info("[preprocessing] UE windows reset for new T")
            print("RESULT " + json.dumps({
                "event": "model_switch",
                "t":     time.time(),
                "old_T": TRACTOR_T_OPTIONS[old_idx],
                "new_T": new_T,
            }), flush=True)

            # Tell TRACTOR to load the new model
            model_path = TRACTOR_MODEL_PATH.replace("{T}", str(new_T))
            base = f"http://{MODEL_HOST}:{MODEL_PORT}"
            try:
                r = req.post(f"{base}/load_model", json={
                    "model_type": TRACTOR_MODEL_TYPE,
                    "model_path": model_path,
                    "Nclass":     TRACTOR_NCLASS,
                    "slice_len":  new_T,
                    "num_feats":  TRACTOR_NUM_FEATS,
                }, timeout=10)
                if r.status_code == 200:
                    logging.warning(
                        f"[preprocessing] TRACTOR model reloaded: T={new_T}  path={model_path}"
                        f"  response={r.json()}"
                    )
                else:
                    logging.warning(
                        f"[preprocessing] TRACTOR /load_model returned {r.status_code} "
                        f"(model file may not exist): path={model_path} — "
                        f"buffer uses T={new_T} but TRACTOR model unchanged"
                    )
            except Exception as e:
                logging.warning(f"[preprocessing] TRACTOR model reload skipped: {e}")

            return jsonify({
                "status": "model_switched",
                "old_T":  TRACTOR_T_OPTIONS[old_idx],
                "new_T":  new_T,
            }), 200

        return jsonify({"status": "acknowledged"}), 200

    @app.route("/test", methods=["POST"])
    def test_ddm():
        """
        Synthetic DDM test: bypass TRACTOR, directly forward fake classifications
        to the filtering agent at a controlled ratio.

        Body (all optional):
          n_baseline  int   rows with traffic_type=URLLC_CLASS (error=0)   default: 30
          n_errors    int   rows with traffic_type=error_type  (error=1)   default: 40
          error_type  str   non-URLLC class to inject                      default: eMBB
          interval    float seconds between sends                           default: 0.05
        """
        data        = request.get_json(force=True) or {}
        n_baseline  = int(data.get("n_baseline",  30))
        n_errors    = int(data.get("n_errors",    40))
        error_type  = data.get("error_type", "eMBB")
        interval    = float(data.get("interval", 0.05))
        fake_row    = "0,0,0,1001,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"

        def _run():
            peer = f"http://{PEER_AGENT_HOST}:{PEER_AGENT_PORT}/filter"
            logging.info(
                f"[test] Starting DDM test → {peer}  "
                f"baseline={n_baseline}×{URLLC_CLASS}  errors={n_errors}×{error_type}"
            )
            import requests as _req

            def _send(traffic_type, cls_int):
                try:
                    _req.post(peer, json={
                        "classification": {"class": cls_int, "traffic_type": traffic_type},
                        "row": fake_row,
                        "encoding": {},
                    }, timeout=8)
                except Exception as e:
                    logging.warning(f"[test] send failed ({traffic_type}): {e}")

            for i in range(n_baseline):
                logging.info(f"[test] baseline {i+1}/{n_baseline}  type={URLLC_CLASS} (error=0)")
                _send(URLLC_CLASS, 2)
                time.sleep(interval)

            for i in range(n_errors):
                logging.info(f"[test] error    {i+1}/{n_errors}  type={error_type} (error=1)")
                _send(error_type, 0)
                time.sleep(interval)

            logging.info("[test] DDM test complete — check filtering agent logs")

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({
            "status": "started",
            "n_baseline": n_baseline, "n_errors": n_errors,
            "error_type": error_type, "interval": interval,
        }), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "mode": "preprocessing",
                        "data_port": AGENT_DATA_PORT}), 200

    return app


def start_preprocessing():
    logging.info(
        f"[preprocessing] Starting — http={AGENT_PORT}  tcp={AGENT_DATA_PORT}  "
        f"model=localhost:{MODEL_PORT}  peer={PEER_AGENT_HOST}:{PEER_AGENT_PORT}"
    )
    threading.Thread(target=_preprocessing_tcp_listener, daemon=False).start()
    _make_preprocessing_http_app().run(host="0.0.0.0", port=AGENT_PORT)


# ==============================================================================
# MODE: filtering  (journal)
# ==============================================================================

def _make_detector():
    if DRIFT_DETECTOR == "none":
        return None
    try:
        from river import drift as rd
        from river.drift import binary as rd_binary

        if DRIFT_DETECTOR in ("ddm", "eddm"):
            cls = rd_binary.DDM if DRIFT_DETECTOR == "ddm" else rd_binary.EDDM
            det = cls(warning_threshold=DDM_WARNING_THRESHOLD,
                      drift_threshold=DDM_DRIFT_THRESHOLD)
            logging.info(
                f"[filtering] Drift detector: {DRIFT_DETECTOR} ({cls.__name__})"
                f"  warning={DDM_WARNING_THRESHOLD}  drift={DDM_DRIFT_THRESHOLD}"
            )
        elif DRIFT_DETECTOR == "adwin":
            det = rd.ADWIN(delta=ADWIN_DELTA)
            logging.info(f"[filtering] Drift detector: adwin  delta={ADWIN_DELTA}")
        elif DRIFT_DETECTOR == "ph":
            det = rd.PageHinkley()
            logging.info(f"[filtering] Drift detector: PageHinkley (default params)")
        else:
            det = rd_binary.DDM(warning_threshold=DDM_WARNING_THRESHOLD,
                                drift_threshold=DDM_DRIFT_THRESHOLD)
            logging.info(f"[filtering] Unknown detector '{DRIFT_DETECTOR}', using DDM")

        return det
    except ImportError:
        logging.error("[filtering] river not installed — drift detection disabled")
        return None


def _make_filtering_app():
    import requests as req
    from flask import Flask, request, jsonify

    detector      = _make_detector()
    detector_lock = threading.Lock()
    context       = {"label": CONTEXT_LABEL}   # mutable so /context can update it

    app = Flask("filtering-agent")

    @app.route("/filter", methods=["POST"])
    def filter_route():
        data           = request.get_json(force=True) or {}
        classification = data.get("classification", {})
        kpm_row        = data.get("row", "")
        encoding       = data.get("encoding", {})

        traffic_type = classification.get("traffic_type", "")

        # DDM error signal: 1 if context is URLLC-overlap but TRACTOR says not URLLC
        if "urllc" in context["label"].lower():
            error = 0 if traffic_type == URLLC_CLASS else 1
            _update_detector(req, detector, detector_lock, error, context["label"])

        # Skip: if TRACTOR did not classify as URLLC, UNICORN is not needed
        if traffic_type != URLLC_CLASS:
            logging.info(f"[filtering] Skip — traffic_type={traffic_type!r}")
            print("RESULT " + json.dumps({
                "event":        "filter_skip",
                "t":            time.time(),
                "traffic_type": traffic_type,
            }), flush=True)
            return '', 204

        # Forward to UNICORN model on localhost
        try:
            resp   = req.post(
                f"http://{MODEL_HOST}:{MODEL_PORT}/predict",
                json={"row": kpm_row},
                timeout=5,
            )
            result = resp.json()
            logging.info(f"[filtering] UNICORN result: {result}")
            print("RESULT " + json.dumps({
                "event":       "unicorn_predict",
                "t":           time.time(),
                "ue":          result.get("ue_id"),
                "application": result.get("application"),
                "class":       result.get("class"),
            }), flush=True)
        except Exception as e:
            logging.warning(f"[filtering] UNICORN call failed: {e}")

        return '', 204

    @app.route("/context", methods=["POST"])
    def set_context():
        data = request.get_json(force=True) or {}
        context["label"] = data.get("context_label", context["label"])
        logging.info(f"[filtering] Context updated: {context['label']}")
        return jsonify({"status": "ok", "context_label": context["label"]}), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status":          "ok",
            "mode":            "filtering",
            "context_label":   context["label"],
            "drift_detector":  DRIFT_DETECTOR,
        }), 200

    return app


COMPLAINT_COOLDOWN     = int(os.environ.get('COMPLAINT_COOLDOWN',     '15'))   # seconds between complaints
COMPLAINT_ERROR_STREAK = int(os.environ.get('COMPLAINT_ERROR_STREAK', '20'))   # consecutive errors to re-complain

_filter_state = {
    "consecutive_errors":  0,
    "last_complaint_time": 0.0,
}


def _update_detector(req, detector, lock, error, ctx_label):
    if detector is None:
        return
    with lock:
        # track consecutive errors for post-reset re-complaint
        if error == 1:
            _filter_state["consecutive_errors"] += 1
        else:
            _filter_state["consecutive_errors"] = 0

        complaint_sent = False

        if detector is not None:
            detector.update(error)
            if detector.drift_detected:
                logging.warning(f"[filtering] DDM drift detected  context={ctx_label}")
                complaint_sent = True

        # fallback: DDM resets after drift and gets stuck at p=1,s=0 with 100% errors
        # (1+0 > 1+k*0 is never True) — re-complain on persistent error streak
        if (not complaint_sent
                and _filter_state["consecutive_errors"] >= COMPLAINT_ERROR_STREAK
                and time.time() - _filter_state["last_complaint_time"] > COMPLAINT_COOLDOWN):
            logging.warning(
                f"[filtering] Persistent error streak ({_filter_state['consecutive_errors']}) "
                f"after DDM reset — re-complaining  context={ctx_label}"
            )
            complaint_sent = True

        if complaint_sent:
            _filter_state["consecutive_errors"]  = 0
            _filter_state["last_complaint_time"] = time.time()
            print("RESULT " + json.dumps({
                "event":   "complaint",
                "t":       time.time(),
                "context": ctx_label,
            }), flush=True)
            _send_complaint(req, ctx_label)


def _send_complaint(req, ctx_label):
    if not PEER_AGENT_HOST:
        logging.warning("[filtering] No PEER_AGENT_HOST set — complaint dropped")
        return
    try:
        req.post(
            f"http://{PEER_AGENT_HOST}:{PEER_AGENT_PORT}/complaint",
            json={"reason": "drift_detected", "context": ctx_label},
            timeout=5,
        )
        logging.info(f"[filtering] Complaint sent to {PEER_AGENT_HOST}:{PEER_AGENT_PORT}")
    except Exception as e:
        logging.warning(f"[filtering] Complaint failed: {e}")


def start_filtering():
    app = _make_filtering_app()
    logging.info(
        f"[filtering] Starting — port={AGENT_PORT}  "
        f"model=localhost:{MODEL_PORT}  peer={PEER_AGENT_HOST}:{PEER_AGENT_PORT}  "
        f"context={CONTEXT_LABEL}  detector={DRIFT_DETECTOR}"
    )
    app.run(host="0.0.0.0", port=AGENT_PORT)


# ==============================================================================
# MODE: enhancer  (journal)
# ==============================================================================
#
# Pipeline: SmartGW → [TCP AGENT_DATA_PORT] → enhance → [TCP ENHANCER_OUT_HOST:PORT] → model
#
# Per-UE state (all learned online, no offline calibration):
#   last_known : list[float]  last non-zero value per feature  (imputation)
#   n          : int          row count                        (Welford)
#   mean       : list[float]  running mean per feature         (Welford / clipping)
#   M2         : list[float]  running sum of sq. deviations    (Welford / clipping)
#   ema        : list[float]  last EMA value per feature       (smoothing)

# Config — 8 new env vars under the enhancer block (IN/OUT port, skip cols, impute, alpha, sigma, warmup)

# _enh_process(fields) — the core transform: iterates feature columns only, applies imputation → Welford update + clip → EMA, returns the cleaned field list

# _enh_connect_downstream() — opens TCP to ENHANCER_OUT_HOST:PORT, retries every 2s

# _enh_forward(line) — sends a cleaned row, reconnects automatically on broken pipe

# _enh_handle_client(conn) — reads newline-delimited rows from SmartGW, calls _enh_process, forwards

# start_enhancer() — wires everything together, binds TCP listener on AGENT_DATA_PORT

# To deploy for CNN: set AGENT_MODE=enhancer, ENHANCER_OUT_HOST=<cnn-host>, ENHANCER_OUT_PORT=<cnn-tcp-port>. Same pattern for XGBoost with different out host/port.

_enh_state: dict = {}        # ue_id -> per-UE dict
_enh_state_lock = threading.Lock()

# shared outbound socket to downstream model
_enh_out_sock     = None
_enh_out_sock_lock = threading.Lock()


def _enh_get_ue(ue_id: str, n_feats: int) -> dict:
    if ue_id not in _enh_state:
        _enh_state[ue_id] = {
            "n":          0,
            "last_known": [0.0] * n_feats,
            "mean":       [0.0] * n_feats,
            "M2":         [0.0] * n_feats,
            "ema":        [None] * n_feats,
        }
    return _enh_state[ue_id]


def _enh_process(fields: list[str]) -> list[str]:
    """
    Apply imputation → clipping → EMA smoothing to one CSV row.
    Non-feature columns (ENHANCER_SKIP_COLS) are passed through unchanged.
    Logs a per-row summary of every feature that was modified.
    """
    n_cols   = len(fields)
    feat_idx = [i for i in range(n_cols) if i not in ENHANCER_SKIP_COLS]
    if not feat_idx:
        return fields

    try:
        ue_id = fields[4].strip()
    except IndexError:
        ue_id = "default"

    changes = []   # (col, original, final, tags) — collected inside lock, logged outside

    with _enh_state_lock:
        ue = _enh_get_ue(ue_id, len(feat_idx))
        ue["n"] += 1
        n = ue["n"]

        out = list(fields)
        for fi, col in enumerate(feat_idx):
            try:
                original = float(fields[col])
            except ValueError:
                continue

            x    = original
            tags = []

            # ── 1. Imputation: forward-fill zeros ──────────────────────────
            if IMPUTE_ENABLED and x == 0.0:
                x = ue["last_known"][fi]
                if x != 0.0:
                    tags.append("imputed")
            else:
                ue["last_known"][fi] = x

            # ── 2. Clipping: Welford update then symmetric clip ────────────
            if CLIP_SIGMA > 0:
                delta          = x - ue["mean"][fi]
                ue["mean"][fi] += delta / n
                ue["M2"][fi]   += delta * (x - ue["mean"][fi])
                if n >= CLIP_WARMUP and n > 1:
                    std    = math.sqrt(ue["M2"][fi] / n)
                    lo     = ue["mean"][fi] - CLIP_SIGMA * std
                    hi     = ue["mean"][fi] + CLIP_SIGMA * std
                    x_clip = max(lo, min(hi, x))
                    if x_clip != x:
                        tags.append(f"clipped[{lo:.4g},{hi:.4g}]")
                    x = x_clip

            # ── 3. EMA smoothing ───────────────────────────────────────────
            if SMOOTH_ALPHA > 0:
                if ue["ema"][fi] is None:
                    ue["ema"][fi] = x
                else:
                    ue["ema"][fi] = SMOOTH_ALPHA * x + (1 - SMOOTH_ALPHA) * ue["ema"][fi]
                x = ue["ema"][fi]
                tags.append("ema")

            out[col] = f"{x:.6g}"

            if tags:
                changes.append((col, original, x, tags))

    # ── Per-row summary log ────────────────────────────────────────────────────
    if changes:
        parts = [f"col{col}:{orig:.4g}→{final:.4g}({','.join(t)})"
                 for col, orig, final, t in changes]
        logging.info(f"[enhancer] ue={ue_id} row={n}  " + "  ".join(parts))
    else:
        logging.debug(f"[enhancer] ue={ue_id} row={n}  no changes")

    return out


def _enh_connect_downstream():
    global _enh_out_sock
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ENHANCER_OUT_HOST, ENHANCER_OUT_PORT))
            with _enh_out_sock_lock:
                _enh_out_sock = s
            logging.info(f"[enhancer] Connected to downstream {ENHANCER_OUT_HOST}:{ENHANCER_OUT_PORT}")
            return
        except Exception as e:
            logging.warning(f"[enhancer] Downstream not ready: {e} — retrying in 2s")
            time.sleep(2)


def _enh_forward(line: str):
    global _enh_out_sock
    msg = (line + "\n").encode("utf-8")
    while True:
        with _enh_out_sock_lock:
            sock = _enh_out_sock
        if sock is None:
            time.sleep(0.1)
            continue
        try:
            sock.sendall(msg)
            return
        except (BrokenPipeError, OSError) as e:
            logging.warning(f"[enhancer] Downstream send failed: {e} — reconnecting")
            with _enh_out_sock_lock:
                _enh_out_sock = None
            _enh_connect_downstream()


def _enh_handle_client(conn):
    buf = ""
    with conn:
        while True:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    fields  = line.split(",")
                    cleaned = _enh_process(fields)
                    out_row = ",".join(cleaned)
                    logging.debug(f"[enhancer] {line[:80]} → {out_row[:80]}")
                    _enh_forward(out_row)
            except Exception as e:
                logging.warning(f"[enhancer] Client error: {e}")
                break


def start_enhancer():
    if not ENHANCER_OUT_HOST:
        logging.error("[enhancer] ENHANCER_OUT_HOST is not set — cannot start")
        return

    threading.Thread(target=_enh_connect_downstream, daemon=True).start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", AGENT_DATA_PORT))
    srv.listen(5)
    logging.info(
        f"[enhancer] Listening on :{AGENT_DATA_PORT}  →  {ENHANCER_OUT_HOST}:{ENHANCER_OUT_PORT}"
        f"  impute={IMPUTE_ENABLED}  alpha={SMOOTH_ALPHA}  clip_sigma={CLIP_SIGMA}"
        f"  clip_warmup={CLIP_WARMUP}  skip_cols={sorted(ENHANCER_SKIP_COLS)}"
    )
    while True:
        try:
            conn, addr = srv.accept()
            logging.info(f"[enhancer] Connection from {addr}")
            threading.Thread(target=_enh_handle_client, args=(conn,), daemon=True).start()
        except Exception as e:
            logging.error(f"[enhancer] Accept error: {e}")
            time.sleep(0.5)


# ==============================================================================
# MAIN
# ==============================================================================

DEMO_MODES    = ('exec', 'file', 'log_collector')
JOURNAL_MODES = ('preprocessing', 'filtering', 'enhancer')
ALL_MODES     = DEMO_MODES + JOURNAL_MODES

if __name__ == '__main__':
    if AGENT_MODE not in ALL_MODES:
        print(f'[agent] ERROR: AGENT_MODE must be one of {ALL_MODES}, got: {AGENT_MODE!r}')
        sys.exit(1)

    print(f"[agent] Mode={AGENT_MODE}")

    if AGENT_MODE == 'preprocessing':
        start_preprocessing()

    elif AGENT_MODE == 'filtering':
        start_filtering()

    elif AGENT_MODE == 'enhancer':
        start_enhancer()

    else:
        # Demo modes — require DEMO_SERVER_HOST
        if not DEMO_SERVER_HOST:
            print('[agent] ERROR: DEMO_SERVER_HOST is not set')
            sys.exit(1)

        if AGENT_MODE == 'log_collector':
            if not MODEL_NAME or not MODEL_TYPE:
                print('[agent] ERROR: log_collector requires MODEL_NAME and MODEL_TYPE')
                sys.exit(1)
            start_log_collector()

        if AGENT_MODE == 'file':
            file_stop()

        while True:
            run_client()
            print('[agent] Disconnected. Reconnecting in 2s...')
            time.sleep(2)
