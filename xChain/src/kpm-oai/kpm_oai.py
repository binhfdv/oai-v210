import socket
import os
import time
import csv
import logging
from pathlib import Path
from datetime import datetime

# --- Config from env ---
ORCH_HOST = os.getenv("ORCH_HOST", "xchain-smartgw")
ORCH_PORT = int(os.getenv("ORCH_PORT", "4200"))
CLEAN_DIR = os.getenv("CLEAN_DIR", "/data/clean")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))
NUM_UES       = int(os.getenv("NUM_UES", "0"))    # 0 = send whatever is available
LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO").upper()

# Metric fields to extract and send (in order)
METRIC_ORDER = [
    'timestamp', 'gnb_cu_cp_ue_e1ap', 'gnb_cu_ue_f1ap', 'ran_ue_id',
    'DRB.PdcpSduVolumeDL', 'DRB.PdcpSduVolumeUL', 'DRB.RlcSduDelayDl',
    'DRB.UEThpDl', 'DRB.UEThpUl', 'RRU.PrbTotDl', 'RRU.PrbTotUl'
]

last_sent_ts = None  # track the latest timestamp seen

logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("kpm-stream")

def parse_timestamp_safe(ts_str):
    """Parse timestamp safely. Never raise, return datetime or None."""
    if not ts_str:
        return None
    ts_str = ts_str.strip().replace("\r", "").replace("\n", "")
    try:
        # Native ISO 8601 parsing (Python 3.11 supports microseconds)
        return datetime.fromisoformat(ts_str)
    except Exception:
        try:
            # Fallback for compact UTC strings (strip trailing Z)
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1]
            return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f")
        except Exception:
            return None

def build_ue_row(row):
    """Extract the 11 KPM fields in METRIC_ORDER from a CSV row."""
    return [row.get(k, "") for k in METRIC_ORDER]

def get_latest_csv_file():
    p = Path(CLEAN_DIR)
    csv_files = list(p.glob("*.csv"))
    return max(csv_files, key=lambda f: f.stat().st_mtime) if csv_files else None

def read_latest_snapshot_by_ue(csv_path):
    """Read per-UE latest rows from the cleaned CSV, only for rows newer than last_sent_ts."""
    global last_sent_ts
    ue_last, order = {}, []
    latest_ts_seen = last_sent_ts

    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get('timestamp')
                ts_val = parse_timestamp_safe(ts_str)

                rid = row.get('ran_ue_id')
                if not rid or not ts_val:
                    continue

                # Skip rows already sent
                if last_sent_ts and ts_val <= last_sent_ts:
                    continue

                if rid not in ue_last:
                    order.append(rid)
                ue_last[rid] = row

                if not latest_ts_seen or ts_val > latest_ts_seen:
                    latest_ts_seen = ts_val

    except Exception as e:
        logger.error(f"Failed reading {csv_path}: {e}")

    if latest_ts_seen:
        last_sent_ts = latest_ts_seen

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

        if NUM_UES > 0 and num_ues < NUM_UES:
            logger.warning(f"Only {num_ues}/{NUM_UES} UEs ready, skipping")
            time.sleep(POLL_INTERVAL)
            continue

        msg_batch = []

        for ue_id in order:
            row = ue_last.get(ue_id)
            if not row:
                continue
            msg_batch.append(",".join(str(v) for v in build_ue_row(row)))

        if not msg_batch:
            time.sleep(POLL_INTERVAL)
            continue

        final_msg = "\n".join(msg_batch) + "\n"

        try:
            sock.sendall(final_msg.encode("utf-8"))
            logger.info(f"Sent {num_ues} UE metrics in one message")
            logger.info(f"Message content:\n{final_msg}")
            if last_sent_ts:
                logger.info(f"Streaming data up to {last_sent_ts.isoformat()}")
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
