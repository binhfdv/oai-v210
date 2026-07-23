"""KPM Streamer:
    - Streams directly csv metrics from TRACTOR/UNICORN eMBB/mMTC/URLLC traffic
"""

import socket, time, os, csv, logging

ORCH_HOST     = os.getenv("ORCH_HOST",  "xchain-smartgw")
ORCH_PORT     = int(os.getenv("ORCH_PORT", "4200"))
CSV_PATH      = os.getenv("CSV_PATH",   "kpis.csv")
SPEED_FACTOR  = float(os.getenv("SPEED_FACTOR", "1.0"))  # >1 = faster replay
LOG_LEVEL     = os.getenv("LOG_LEVEL",  "INFO").upper()

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
    Reshape one CSV row into the 33-field kpm_colosseum_oai format:
      [0]  timestamp      (pass-through ms int as string)
      [1]  timestamp_ms   (same numeric value)
      [2]  num_ues
      [3]  IMSI
      [4]  RNTI
      [5-9]  slicing_enabled, slice_id, slice_prb, power_multiplier, scheduling_policy
      [10-12] dl_mcs, dl_n_samples, dl_buffer[bytes]
      [13]   tx_brate downlink [Mbps]   ← SmartGW KPM_COL_THPDL=13
      [14-16] tx_pkts dl, tx_errors dl, dl_cqi
      [17-19] ul_mcs, ul_n_samples, ul_buffer[bytes]
      [20]   rx_brate uplink [Mbps]     ← SmartGW KPM_COL_THPUL=20
      [21-27] rx_pkts ul, rx_errors ul, ul_rssi, ul_sinr, phr,
              sum_req_prbs, sum_grant_prbs
      [28-31] dl_pmi, dl_ri, ul_n, ul_turbo_iters
      [32]   ul_vol (ul_buffer / 1000)  ← SmartGW KPM_COL_VOLUL=32
    """
    def g(i, default="0"):
        try:
            v = csv_row[i].strip()
            return v if v != "" else default
        except IndexError:
            return default

    ts_ms = g(0, "0")
    ul_vol = str(float(g(18, "0")) / 1000.0)

    return [
        ts_ms,       # [0]  timestamp
        ts_ms,       # [1]  timestamp_ms
        g(1),        # [2]  num_ues
        g(2),        # [3]  IMSI
        g(3),        # [4]  RNTI
        g(4),        # [5]  slicing_enabled
        g(5),        # [6]  slice_id
        g(6),        # [7]  slice_prb
        g(7),        # [8]  power_multiplier
        g(8),        # [9]  scheduling_policy
        g(9),        # [10] dl_mcs
        g(10),       # [11] dl_n_samples
        g(11),       # [12] dl_buffer [bytes]
        g(12),       # [13] tx_brate downlink [Mbps]  ← SmartGW reads here
        g(13),       # [14] tx_pkts downlink
        g(14),       # [15] tx_errors downlink (%)
        g(15),       # [16] dl_cqi
        g(16),       # [17] ul_mcs
        g(17),       # [18] ul_n_samples
        g(18),       # [19] ul_buffer [bytes]
        g(19),       # [20] rx_brate uplink [Mbps]    ← SmartGW reads here
        g(20),       # [21] rx_pkts uplink
        g(21),       # [22] rx_errors uplink (%)
        g(22),       # [23] ul_rssi
        g(23),       # [24] ul_sinr
        g(24),       # [25] phr
        g(25),       # [26] sum_requested_prbs
        g(26),       # [27] sum_granted_prbs
        g(27),       # [28] dl_pmi
        g(28),       # [29] dl_ri
        g(29),       # [30] ul_n
        g(30),       # [31] ul_turbo_iters
        ul_vol,      # [32] ul_vol                    ← SmartGW reads here
    ]


def load_csv(path: str):
    """Load all data rows (skip header). Returns list of raw string lists."""
    rows = []
    with open(path, "r") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for line in reader:
            if line:
                rows.append(line)
    return rows


def connect():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ORCH_HOST, ORCH_PORT))
            logger.info(f"[KPM-sim] Connected to {ORCH_HOST}:{ORCH_PORT}")
            return s
        except Exception as e:
            logger.warning(f"[KPM-sim] Waiting for SmartGW... {e}")
            time.sleep(1)


def stream_loop(sock, rows):
    """Replay rows repeatedly; re-connect on broken pipe."""
    loop = 0
    while True:
        loop += 1
        logger.info(f"[KPM-sim] Starting replay loop #{loop} ({len(rows)} rows)")
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
                    f"[KPM-sim] Sent ts={ts}  RNTI={out[4]}"
                    f"  thp_dl={out[13]}  thp_ul={out[20]}  ul_vol={out[32]}"
                )
            except (BrokenPipeError, OSError) as e:
                logger.warning(f"[KPM-sim] Connection lost: {e} — reconnecting")
                sock.close()
                return False  # signal caller to reconnect

        logger.info(f"[KPM-sim] Replay loop #{loop} done — restarting")
        prev_ts = None  # reset timing on each loop


if __name__ == "__main__":
    rows = load_csv(CSV_PATH)
    logger.info(f"[KPM-sim] Loaded {len(rows)} rows from {CSV_PATH}")

    while True:
        sock = connect()
        done = stream_loop(sock, rows)
        time.sleep(1)
