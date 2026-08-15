"""KPM Streamer:
    Modes (set via MODE env var):
      csv      — replay a static CSV file in a loop (default)
      realtime — poll CLEAN_DIR for live OAI KPM; pair each UE row with the
                 next base row from CSV_PATH (round-robin), then overwrite
                 the 3 KPM metrics (cols 13/20/32) with live OAI values
"""

import socket, time, os, csv, logging
from pathlib import Path
from datetime import datetime

# === Common ===
ORCH_HOST     = os.getenv("ORCH_HOST",  "xchain-smartgw")
ORCH_PORT     = int(os.getenv("ORCH_PORT", "4200"))
MODE          = os.getenv("MODE", "csv")          # "csv" | "realtime"
LOG_LEVEL     = os.getenv("LOG_LEVEL",  "INFO").upper()

# === CSV mode ===
CSV_PATH      = os.getenv("CSV_PATH",   "kpis.csv")
SPEED_FACTOR  = float(os.getenv("SPEED_FACTOR", "1.0"))

# === Real-time mode ===
CLEAN_DIR     = os.getenv("CLEAN_DIR", "/data/clean")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))

logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("kpm-sim")

# ---------------------------------------------------------------------------
# CSV column indices — cleaned format (empty/unnamed cols removed), 31 cols 0-30
# ---------------------------------------------------------------------------
#  0: Timestamp(ms int)   1: num_ues          2: IMSI             3: RNTI
#  4: slicing_enabled     5: slice_id         6: slice_prb        7: power_multiplier
#  8: scheduling_policy   9: dl_mcs          10: dl_n_samples    11: dl_buffer[bytes]
# 12: tx_brate dl[Mbps] 13: tx_pkts dl      14: tx_errors dl(%) 15: dl_cqi
# 16: ul_mcs            17: ul_n_samples     18: ul_buffer[bytes] 19: rx_brate ul[Mbps]
# 20: rx_pkts ul        21: rx_errors ul(%) 22: ul_rssi          23: ul_sinr
# 24: phr               25: sum_req_prbs    26: sum_grant_prbs   27: dl_pmi
# 28: dl_ri             29: ul_n            30: ul_turbo_iters

def build_row(csv_row: list) -> list:
    """
    Reshape one CSV row into the 33-field format:
      [0]  timestamp      (ms int as string)
      [1]  timestamp_ms   (same)
    """
    def g(i, default="0"):
        try:
            v = csv_row[i].strip()
            return v if v != "" else default
        except IndexError:
            return default

    ts_ms  = g(0, "0")
    ul_vol = str(float(g(18, "0")) / 1000.0)

    return [
        ts_ms,   # [0]  timestamp
        ts_ms,   # [1]  timestamp_ms
        g(1),    # [2]  num_ues
        g(2),    # [3]  IMSI
        g(3),    # [4]  RNTI
        g(4),    # [5]  slicing_enabled
        g(5),    # [6]  slice_id
        g(6),    # [7]  slice_prb
        g(7),    # [8]  power_multiplier
        g(8),    # [9]  scheduling_policy
        g(9),    # [10] dl_mcs
        g(10),   # [11] dl_n_samples
        g(11),   # [12] dl_buffer [bytes]
        g(12),   # [13] tx_brate downlink [Mbps]  ← SmartGW KPM_COL_THPDL=13
        g(13),   # [14] tx_pkts downlink
        g(14),   # [15] tx_errors downlink (%)
        g(15),   # [16] dl_cqi
        g(16),   # [17] ul_mcs
        g(17),   # [18] ul_n_samples
        g(18),   # [19] ul_buffer [bytes]
        g(19),   # [20] rx_brate uplink [Mbps]    ← SmartGW KPM_COL_THPUL=20
        g(20),   # [21] rx_pkts uplink
        g(21),   # [22] rx_errors uplink (%)
        g(22),   # [23] ul_rssi
        g(23),   # [24] ul_sinr
        g(24),   # [25] phr
        g(25),   # [26] sum_requested_prbs
        g(26),   # [27] sum_granted_prbs
        g(27),   # [28] dl_pmi
        g(28),   # [29] dl_ri
        g(29),   # [30] ul_n
        g(30),   # [31] ul_turbo_iters
        ul_vol,  # [32] ul_vol                    ← SmartGW KPM_COL_VOLUL=32
    ]


def load_csv(path: str):
    """Load all data rows (skip header). Returns list of raw string lists."""
    rows = []
    with open(path, "r") as f:
        reader = csv.reader(f)
        next(reader)
        for line in reader:
            if line:
                rows.append(line)
    return rows


# ============================================================
# CSV mode
# ============================================================

def stream_loop(sock, rows):
    """Replay rows repeatedly; return False on broken pipe so caller reconnects."""
    loop = 0
    while True:
        loop += 1
        logger.info(f"[csv] Starting replay loop #{loop} ({len(rows)} rows)")
        prev_ts = None

        for csv_row in rows:
            try:
                ts = int(csv_row[0])
            except (ValueError, IndexError):
                continue

            if prev_ts is not None:
                delay = (ts - prev_ts) / 1000.0 / SPEED_FACTOR
                if delay > 0:
                    time.sleep(delay)
            prev_ts = ts

            out = build_row(csv_row)
            msg = (",".join(out) + "\n").encode("utf-8")

            try:
                sock.sendall(msg)
                logger.info(
                    f"[csv] Sent ts={ts}  RNTI={out[4]}"
                    f"  thp_dl={out[13]}  thp_ul={out[20]}  ul_vol={out[32]}"
                )
            except (BrokenPipeError, OSError) as e:
                logger.warning(f"[csv] Connection lost: {e} — reconnecting")
                sock.close()
                return False

        logger.info(f"[csv] Replay loop #{loop} done — restarting")
        prev_ts = None


# ============================================================
# Real-time mode helpers
# ============================================================

_last_sent_ts = None   # latest OAI timestamp already forwarded


def _parse_ts(ts_str):
    if not ts_str:
        return None
    ts_str = ts_str.strip()
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        try:
            return datetime.strptime(ts_str.rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f")
        except Exception:
            return None


def _kbps_to_mbps(x):
    try:
        return float(x) / 1000.0
    except Exception:
        return None


def _get_latest_csv() -> Path | None:
    p = Path(CLEAN_DIR)
    files = list(p.glob("*.csv"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _read_snapshot_by_ue(csv_path: Path):
    """Return (ue_order, ue_last_row) for latest per-UE rows in the OAI clean CSV."""
    global _last_sent_ts
    ue_last, order = {}, []
    latest_ts = _last_sent_ts

    try:
        with open(csv_path, "r") as f:
            for row in csv.DictReader(f):
                rid = row.get('ran_ue_id')
                if not rid:
                    continue
                if rid not in ue_last:
                    order.append(rid)
                ue_last[rid] = row
                ts_val = _parse_ts(row.get('timestamp'))
                if ts_val and (not _last_sent_ts or ts_val > _last_sent_ts):
                    latest_ts = ts_val
    except Exception as e:
        logger.error(f"[realtime] Read error {csv_path}: {e}")

    if latest_ts:
        _last_sent_ts = latest_ts
    return order, ue_last


def realtime_stream_loop(sock, base_rows):
    """
    Poll CLEAN_DIR for live OAI KPM. For each UE row found:
      - pick the next base CSV row (round-robin)
      - build the 33-field row from that base
      - overwrite cols 13 / 20 / 32 with live DRB values from OAI
    Return False on broken pipe so caller reconnects.
    """
    last_csv = None
    rr_idx   = 0   # round-robin index into base_rows

    while True:
        latest = _get_latest_csv()
        if not latest:
            logger.debug(f"[realtime] No CSV in {CLEAN_DIR}, waiting…")
            time.sleep(POLL_INTERVAL)
            continue

        if latest != last_csv:
            last_csv = latest
            logger.info(f"[realtime] Switched to {latest.name}")

        order, ue_last = _read_snapshot_by_ue(latest)
        if not order:
            time.sleep(POLL_INTERVAL)
            continue

        for ue_id in order:
            oai_row = ue_last.get(ue_id)
            if not oai_row:
                continue

            # Base row supplies all structural fields from the training CSV
            base = base_rows[rr_idx % len(base_rows)]
            rr_idx += 1
            out = build_row(base)

            # Overwrite the 3 live KPM metrics with real OAI values
            dl  = _kbps_to_mbps(oai_row.get('DRB.UEThpDl'))
            ul  = _kbps_to_mbps(oai_row.get('DRB.UEThpUl'))
            vol = _kbps_to_mbps(oai_row.get('DRB.PdcpSduVolumeUL'))

            if dl  is not None: out[13] = f"{dl:.6g}"
            if ul  is not None: out[20] = f"{ul:.6g}"
            if vol is not None: out[32] = f"{vol:.6g}"

            msg = (",".join(out) + "\n").encode("utf-8")
            try:
                sock.sendall(msg)
                logger.info(
                    f"[realtime] ue={ue_id}"
                    f"  thp_dl={out[13]}  thp_ul={out[20]}  ul_vol={out[32]}"
                )
            except (BrokenPipeError, OSError) as e:
                logger.warning(f"[realtime] Connection lost: {e} — reconnecting")
                sock.close()
                return False

        time.sleep(POLL_INTERVAL)


# ============================================================
# Common
# ============================================================

def connect():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ORCH_HOST, ORCH_PORT))
            logger.info(f"Connected to {ORCH_HOST}:{ORCH_PORT}")
            return s
        except Exception as e:
            logger.warning(f"Waiting for SmartGW… {e}")
            time.sleep(1)


if __name__ == "__main__":
    logger.info(f"KPM-sim starting  MODE={MODE}")

    # Both modes need the base CSV rows
    rows = load_csv(CSV_PATH)
    logger.info(f"Loaded {len(rows)} base rows from {CSV_PATH}")

    if MODE == "realtime":
        Path(CLEAN_DIR).mkdir(parents=True, exist_ok=True)
        logger.info(f"[realtime] Polling {CLEAN_DIR} every {POLL_INTERVAL}s")
        while True:
            sock = connect()
            realtime_stream_loop(sock, rows)
            time.sleep(1)
    else:
        while True:
            sock = connect()
            stream_loop(sock, rows)
            time.sleep(1)
