"""
TCP streamer for cleaned OAI KPM data with timestamp as first metric.

- Reads latest CSV from CLEAN_DIR (default /data/clean).
- Builds a 31-element metric vector per UE from default TRACTOR EMBB values,
  replacing mapped values from OAI per UE.
- Prepends the original timestamp from the cleaned CSV as the first field.
- Streams each UE vector as a comma-separated string to a single TCP client.
"""

import socket
import os
import time
import csv
import logging
from pathlib import Path
from copy import deepcopy

# --- Config from env ---
ORCH_HOST = os.getenv("ORCH_HOST", "xapp-orchestrator")
ORCH_PORT = int(os.getenv("ORCH_PORT", "4200"))
CLEAN_DIR = os.getenv("CLEAN_DIR", "/data/clean")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("kpm-stream")

# --- Default TRACTOR EMBB metric set ---
DEFAULT_METRICS = {
    'num_ues': 1.0,
    'IMSI': 1010123456002.0,
    'RNTI': 75.09719588863386,
    'slicing_enabled': 1.0,
    'slice_id': 1.0,
    'slice_prb': 18.0,
    'power_multiplier': 1.0,
    'scheduling_policy': 1.0,
    'dl_mcs': 1.72031630615707,
    'dl_n_samples': 55.49456142101587,
    'dl_buffer [bytes]': 4792.096397565113,
    'tx_brate downlink [Mbps]': 0.20226417124039517,
    'tx_pkts downlink': 15.853807005288893,
    'tx_errors downlink (%)': 0.0,
    'dl_cqi': 6.709994766989323,
    'ul_mcs': 2.6767620197585074,
    'ul_n_samples': 11.697335595249974,
    'ul_buffer [bytes]': 771.5226025346772,
    'rx_brate uplink [Mbps]': 0.1392692611515817,
    'rx_pkts uplink': 3.337191897016266,
    'rx_errors uplink (%)': 0.0,
    'ul_rssi': 0.0,
    'ul_sinr': 6.47131010877158,
    'phr': 5.948807504241094,
    'sum_requested_prbs': 663.8665801816186,
    'sum_granted_prbs': 267.45055383694245,
    'dl_pmi': 0.0,
    'dl_ri': 0.0,
    'ul_n': 0.0,
    'ul_turbo_iters': 0.18870372218341483
}

# Metric order for streaming (without timestamp)
METRIC_ORDER = [
    'num_ues', 'IMSI', 'RNTI', 'slicing_enabled', 'slice_id', 'slice_prb',
    'power_multiplier', 'scheduling_policy', 'dl_mcs', 'dl_n_samples',
    'dl_buffer [bytes]', 'tx_brate downlink [Mbps]', 'tx_pkts downlink',
    'tx_errors downlink (%)', 'dl_cqi', 'ul_mcs', 'ul_n_samples',
    'ul_buffer [bytes]', 'rx_brate uplink [Mbps]', 'rx_pkts uplink',
    'rx_errors uplink (%)', 'ul_rssi', 'ul_sinr', 'phr',
    'sum_requested_prbs', 'sum_granted_prbs', 'dl_pmi', 'dl_ri',
    'ul_n', 'ul_turbo_iters'
]

# --- Helpers ---
def to_float_safe(x):
    try:
        return float(x)
    except Exception:
        return None

def convert_kbps_to_mbps(x):
    try:
        return float(x) / 1000.0
    except Exception:
        return None

def convert_kb_to_mbps(x):
    try:
        return float(x) / 1000.0
    except Exception:
        return None


def build_ue_vector_from_row(clean_row):
    """Builds full metric list (timestamp + 31 metrics) for one UE."""
    ue_metrics = deepcopy(DEFAULT_METRICS)

    # Replace RNTI
    ran = clean_row.get('ran_ue_id')
    if ran:
        ue_metrics['RNTI'] = to_float_safe(ran) or ran

    # Downlink throughput
    dl_val = clean_row.get('DRB.UEThpDl') or clean_row.get('DRB.PdcpSduVolumeDL')
    if dl_val:
        ue_metrics['tx_brate downlink [Mbps]'] = convert_kbps_to_mbps(dl_val) or convert_kb_to_mbps(dl_val) or ue_metrics['tx_brate downlink [Mbps]']

    # Uplink throughput
    ul_val = clean_row.get('DRB.UEThpUl') or clean_row.get('DRB.PdcpSduVolumeUL')
    if ul_val:
        ue_metrics['rx_brate uplink [Mbps]'] = convert_kbps_to_mbps(ul_val) or convert_kb_to_mbps(ul_val) or ue_metrics['rx_brate uplink [Mbps]']

    # Compose ordered list
    values = [ue_metrics.get(k, "") for k in METRIC_ORDER]

    # Prepend timestamp from OAI cleaned CSV
    timestamp = clean_row.get('timestamp', '')
    return [timestamp] + values


def get_latest_csv_file():
    p = Path(CLEAN_DIR)
    csv_files = list(p.glob("*.csv"))
    return max(csv_files, key=lambda f: f.stat().st_mtime) if csv_files else None


def read_latest_snapshot_by_ue(csv_path):
    ue_last, order = {}, []
    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = row.get('ran_ue_id')
                if not rid:
                    continue
                if rid not in ue_last:
                    order.append(rid)
                ue_last[rid] = row
    except Exception as e:
        logger.error(f"Failed reading {csv_path}: {e}")
    return order, ue_last


def start_client():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ORCH_HOST, ORCH_PORT))
            logger.info(f"Connected to Tractor at {ORCH_HOST}:{ORCH_PORT}")
            stream_loop(s)
        except Exception as e:
            logger.warning(f"Connection failed, retrying... {e}")
            time.sleep(2)
        finally:
            s.close()

def stream_loop(sock):
    while True:
        latest = get_latest_csv_file()
        if not latest:
            time.sleep(POLL_INTERVAL)
            continue

        order, ue_last = read_latest_snapshot_by_ue(latest)
        if not order:
            time.sleep(POLL_INTERVAL)
            continue

        num_ues = len(order)
        for ue_id in order:
            row = ue_last.get(ue_id)
            if not row: continue
            metrics = build_ue_vector_from_row(row)
            metrics[1] = num_ues  # overwrite num_ues
            msg = ",".join(str(v) for v in metrics) + "\n"
            try:
                sock.sendall(msg.encode("utf-8"))
            except BrokenPipeError:
                logger.info("Server disconnected")
                return
            except Exception as e:
                logger.error(f"Send failed: {e}")
                return

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    Path(CLEAN_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("KPM Streamer started (TCP client)")
    start_client()