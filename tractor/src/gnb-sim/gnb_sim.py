import socket, time, json, os, csv

ORCH_HOST = os.getenv("ORCH_HOST", "xapp-orchestrator")
ORCH_PORT = int(os.getenv("ORCH_PORT", "4200"))
CSV_PATH = os.getenv("CSV_PATH", "kpis.csv")

def connect_and_stream():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ORCH_HOST, ORCH_PORT))
            print(f"[gNB-sim] Connected to orchestrator at {ORCH_HOST}:{ORCH_PORT}")
            break
        except Exception as e:
            print("[gNB-sim] Waiting for orchestrator...", e)
            time.sleep(1)

    try:
        with open(CSV_PATH, "r") as f:
            reader = csv.DictReader(f)
            prev_ts = None
            for row in reader:
                ts = int(row["Timestamp"])
                if prev_ts is not None:
                    delay = (ts - prev_ts) / 1000.0
                    if delay > 0:
                        time.sleep(delay)
                prev_ts = ts

                msg = json.dumps(row).encode("utf-8")
                s.sendall(msg)
                print(f"[gNB-sim] Sent KPI row at ts={ts}")
    except Exception as e:
        print("[gNB-sim] Stream ended:", e)
    finally:
        s.close()

if __name__ == "__main__":
    connect_and_stream()
