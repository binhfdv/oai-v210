import socket, time, json, os, csv

ORCH_HOST = os.getenv("ORCH_HOST", "xapp-orchestrator")
ORCH_PORT = int(os.getenv("ORCH_PORT", "4200"))
CSV_PATH = os.getenv("CSV_PATH", "kpis.csv")

def connect_and_stream():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ORCH_HOST, ORCH_PORT))
            print(f"[KPM-sim] Connected to orchestrator at {ORCH_HOST}:{ORCH_PORT}")
            break
        except Exception as e:
            print("[KPM-sim] Waiting for orchestrator...", e)
            time.sleep(1)

    try:
        with open(CSV_PATH, "r") as f:
            reader = csv.reader(f)
            header = next(reader)  # first line
            prev_ts = None
            for line in reader:
                ts = int(line[0])   # assumes first column is Timestamp
                if prev_ts is not None:
                    delay = (ts - prev_ts) / 1000.0
                    if delay > 0:
                        time.sleep(delay)
                prev_ts = ts

                msg = ",".join(line).encode("utf-8")
                s.sendall(msg)
                print(f"[KPM-sim] Sent KPI row at ts={ts}")
    except Exception as e:
        print("[KPM-sim] Stream ended:", e)
    finally:
        s.close()

if __name__ == "__main__":
    connect_and_stream()

2025-10-28T12:26:41.685279,3,1010123456002.0,2.0,1.0,1.0,18.0,1.0,1.0,1.72031630615707,55.49456142101587,4792.096397565113,0.20226417124039517,15.853807005288893,0.0,6.709994766989323,2.6767620197585074,11.697335595249974,771.5226025346772,0.1392692611515817,3.337191897016266,0.0,0.0,6.47131010877158,5.948807504241094,663.8665801816186,267.45055383694245,0.0,0.0,0.0,0.18870372218341483
2025-10-28T12:26:41.683895,3,1010123456002.0,3.0,1.0,1.0,18.0,1.0,1.0,1.72031630615707,55.49456142101587,4792.096397565113,0.20226417124039517,15.853807005288893,0.0,6.709994766989323,2.6767620197585074,11.697335595249974,771.5226025346772,0.1392692611515817,3.337191897016266,0.0,0.0,6.47131010877158,5.948807504241094,663.8665801816186,267.45055383694245,0.0,0.0,0.0,0.18870372218341483