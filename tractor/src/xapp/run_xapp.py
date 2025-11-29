import logging, time, pickle, os, queue, threading
import numpy as np
from datetime import datetime
from collections import defaultdict
import requests
from xapp_control import open_control_socket, receive_from_socket

# service URLs (Docker DNS names)
NORMALIZER = os.getenv("NORMALIZER_URL", "http://xapp-normalizer:5002")
BUFFER     = os.getenv("BUFFER_URL",     "http://xapp-buffer:5005")
MODEL      = os.getenv("MODEL_URL",      "http://xapp-model:5003")

MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/model.pt")
NORM_PATH  = os.getenv("NORM_PATH",  "/mnt/model/norm.pkl")
MODEL_TYPE = os.getenv("MODEL_TYPE", "Tv1")  # Tv1, Tv2, CNN
NCLASS     = int(os.getenv("NCLASS", "4"))
ALL_FEATS  = int(os.getenv("ALL_FEATS", "31"))
STREAM_ID  = os.getenv("STREAM_ID", "default")
DATA_PORT  = int(os.getenv("DATA_PORT", "4300"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

logging.info(f"Configuration: MODEL_PATH={MODEL_PATH}, NORM_PATH={NORM_PATH},\n"
             f"MODEL_TYPE={MODEL_TYPE}, NCLASS={NCLASS}, ALL_FEATS={ALL_FEATS},\n"
             f"STREAM_ID={STREAM_ID}, DATA_PORT={DATA_PORT}")

data_queue = queue.Queue()
last_timestamp_per_ue = {}

def post_json_retry(url, payload, retries=10, delay=2):
    for i in range(retries):
        try:
            r = requests.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            if "num_feats" in data and "slice_len" in data:
                return data
        except (requests.exceptions.JSONDecodeError, requests.exceptions.ConnectionError):
            print(f"Service not ready at {url}, retrying {i+1}/{retries}...")
            time.sleep(delay)
    raise RuntimeError(f"Failed to get valid JSON from {url}")


def init_system():
    # call normalizer ONCE with retry logic
    r = post_json_retry(f"{NORMALIZER}/load_norm", {
        "norm_param_path": NORM_PATH,
        "all_feats_raw": ALL_FEATS
    })
    num_feats = r["num_feats"]
    slice_len = r["slice_len"]
    logging.info(f"Normalizer ready: num_feats={num_feats}, slice_len={slice_len}")

    # reset buffer
    logging.info("Resetting buffer")
    r = requests.post(f"{BUFFER}/reset", json={"stream": STREAM_ID})
    r.raise_for_status()
    resp = r.json()
    logging.info(f"Buffer reset: status={resp['status']}, stream ID={resp['stream']}")

    # load model with params from normalizer
    logging.info("Loading model with slice_len & num_feats from normalizer")
    r = requests.post(f"{MODEL}/load_model", json={
        "model_type": MODEL_TYPE,
        "model_path": MODEL_PATH,
        "Nclass": NCLASS,
        "slice_len": slice_len,
        "num_feats": num_feats
    })
    r.raise_for_status()
    m = r.json()
    logging.info(f"Model loaded: {m}")

    return num_feats, slice_len


def socket_listener(control_sck):
    """Receive data from TCP and enqueue each complete UE row."""
    logging.info("Socket listener started...")

    buffer = ""  # holds leftover partial data between recv calls

    while True:
        try:
            data = receive_from_socket(control_sck)
            batch_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            logging.info(f"Received new batch with ID: {batch_id}")
            logging.info(f"\n\nData received: {data}\n\n")
            if not data:
                continue

            # Append new chunk to buffer
            buffer += data

            # Process all complete rows (terminated by newline)
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                if not line:
                    continue

                # Parse one complete row
                recv_time = time.perf_counter()
                parts = line.split(",")

                if len(parts) < ALL_FEATS + 1:
                    ue_id = 0
                    logging.info(f"[UE={ue_id}] Skipping malformed row: {line}")
                    continue

                numeric_line = ",".join(parts[1:])  # remove readable timestamp
                data_queue.put((batch_id, numeric_line, recv_time, 1))

        except Exception as e:
            logging.exception(f"Socket listener error: {e}")
            time.sleep(0.5)


def processing_worker(num_feats, slice_len):
    logging.info("Processing worker started...")

    batch_stats = defaultdict(lambda: {
        "queue_wait": 0.0,
        "normalize": 0.0,
        "buffer": 0.0,
        "predict": 0.0,
        "count": 0,
        "expected": 0,
        "start_time": None,
    })

    while True:
        try:
            batch_id, data_line, recv_time, batch_size = data_queue.get(block=True)
            start_proc = time.perf_counter()
            queue_wait_ms = (start_proc - recv_time) * 1000.0

            stats = batch_stats[batch_id]
            if stats["start_time"] is None:
                stats["start_time"] = recv_time
                stats["expected"] = batch_size

            kpi_new = np.fromstring(data_line, sep=',')
            if kpi_new.shape[0] < ALL_FEATS:
                logging.info(f"Discarded short feature row ({kpi_new.shape[0]} features): {data_line}")
                stats["count"] += 1
                data_queue.task_done()
                if stats["count"] >= stats["expected"]:
                    log_batch_summary(batch_id, stats)
                    del batch_stats[batch_id]
                continue

            ts_int = int(kpi_new[0])
            ue_id = kpi_new[3]

            last_ts = last_timestamp_per_ue.get(ue_id, 0)
            if ts_int <= last_ts:
                stats["count"] += 1
                data_queue.task_done()
                if stats["count"] >= stats["expected"]:
                    log_batch_summary(batch_id, stats)
                    del batch_stats[batch_id]
                continue
            last_timestamp_per_ue[ue_id] = ts_int

            # Normalize
            t0 = time.perf_counter()
            norm = requests.post(f"{NORMALIZER}/normalize", json={"kpi": kpi_new.tolist()}).json()
            t1 = time.perf_counter()
            normalize_time_ms = (t1 - t0) * 1000.0

            # Buffer update
            t0 = time.perf_counter()
            buf = requests.post(f"{BUFFER}/update", json={
                "stream": STREAM_ID,
                "kpi": norm["normalized"],
                "slice_len": slice_len,
                "num_feats": num_feats
            }).json()
            t1 = time.perf_counter()
            buffer_time_ms = (t1 - t0) * 1000.0

            if not buf["ready"]:
                logging.info(
                    f"[UE={ue_id}] queue_wait={queue_wait_ms:.2f} ms | "
                    f"normalize={normalize_time_ms:.2f} ms | buffer={buffer_time_ms:.2f} ms | predict=--"
                )
                stats["count"] += 1
                data_queue.task_done()
                if stats["count"] >= stats["expected"]:
                    log_batch_summary(batch_id, stats)
                    del batch_stats[batch_id]
                continue

            # Predict
            t0 = time.perf_counter()
            pred = requests.post(f"{MODEL}/predict", json={
                "window": buf["window"]
            }).json()
            t1 = time.perf_counter()
            predict_time_ms = (t1 - t0) * 1000.0
            pred_class = pred["class"]

            logging.info(
                f"[UE={ue_id}] Predicted class: {pred_class} | "
                f"queue_wait={queue_wait_ms:.2f} ms | normalize={normalize_time_ms:.2f} ms | "
                f"buffer={buffer_time_ms:.2f} ms | predict={predict_time_ms:.2f} ms"
            )

            stats["queue_wait"] += queue_wait_ms
            stats["normalize"] += normalize_time_ms
            stats["buffer"] += buffer_time_ms
            stats["predict"] += predict_time_ms
            stats["count"] += 1

            if stats["count"] >= stats["expected"]:
                log_batch_summary(batch_id, stats)
                del batch_stats[batch_id]

            try:
                pickle.dump(
                    {
                        'input': np.array(buf["window"]),
                        'label': pred_class,
                        'input_raw': kpi_new.copy(),
                        'ue_id': ue_id,
                        'timestamp': ts_int
                    },
                    open(f'/home/class_output_{ue_id}_{ts_int}.pkl', 'wb')
                )
            except Exception as e:
                logging.info(f"Pickle dump failed: {e}")

            data_queue.task_done()

        except Exception as e:
            logging.error(f"Processing error: {e}")
            time.sleep(0.5)


def log_batch_summary(batch_id, stats):
    total_stage = (
        stats["queue_wait"] + stats["normalize"] + stats["buffer"] + stats["predict"]
    )
    end2end = (time.perf_counter() - stats["start_time"]) * 1000.0
    logging.info(
        f"[BATCH KPM {batch_id}] Completed {stats['count']} UEs | "
        f"queue_wait={stats['queue_wait']:.2f} ms | normalize={stats['normalize']:.2f} ms | "
        f"buffer={stats['buffer']:.2f} ms | predict={stats['predict']:.2f} ms | "
        f"total_stage={total_stage:.2f} ms | end2end={end2end:.2f} ms"
    )


def main():
    num_feats, slice_len = init_system()

    # open TCP server (your API)
    control_sck = open_control_socket(DATA_PORT)
    logging.info(f"Listening on port {DATA_PORT}")
    logging.info("Start listening on E2 interface...")

    t_listener = threading.Thread(target=socket_listener, args=(control_sck,), daemon=True)
    t_worker = threading.Thread(target=processing_worker, args=(num_feats, slice_len), daemon=True)
    t_listener.start()
    t_worker.start()
    t_listener.join()
    t_worker.join()

    # last_timestamp = 0
    # kpi_raw_window = []

    # while True:
    #     data_sck = receive_from_socket(control_sck)
    #     if not data_sck:
    #         continue

    #     data_sck = data_sck.replace(',,', ',')
    #     if data_sck[0] == 'm':
    #         # (rare in sim) multi-part framing not used; just fall through
    #         data_sck = data_sck[1:]

    #     kpi_new = np.fromstring(data_sck, sep=',')
    #     if kpi_new.shape[0] < ALL_FEATS:
    #         logging.info('Discarding KPI: too short')
    #         logging.info(f"Received data length: {kpi_new.shape[0]}, data: {data_sck}")
    #         continue

    #     ts = kpi_new[0]
    #     if ts <= last_timestamp:
    #         continue
    #     last_timestamp = ts

    #     # --- normalize step ---
    #     t0 = time.time()
    #     norm = requests.post(f"{NORMALIZER}/normalize", json={"kpi": kpi_new.tolist()}).json()
    #     t1 = time.time()
    #     normalize_time_ms = (t1 - t0) * 1000.0

    #     kpi_norm_vec = norm["normalized"]  # shape: [num_feats]

    #     # --- update buffer step ---
    #     t0 = time.time()
    #     buf = requests.post(f"{BUFFER}/update", json={
    #         "stream": STREAM_ID,
    #         "kpi": kpi_norm_vec,
    #         "slice_len": slice_len,
    #         "num_feats": num_feats
    #     }).json()
    #     t1 = time.time()
    #     buffer_time_ms = (t1 - t0) * 1000.0

    #     ready = buf["ready"]
    #     if not ready:
    #         logging.info(f"Processing times: normalize={normalize_time_ms:.2f} ms | buffer={buffer_time_ms:.2f} ms | predict=--")
    #         continue

    #     window = buf["window"]  # shape [slice_len, num_feats]

    #     # --- predict step ---
    #     t0 = time.time()
    #     pred = requests.post(f"{MODEL}/predict", json={
    #         "window": window
    #     }).json()
    #     t1 = time.time()
    #     predict_time_ms = (t1 - t0) * 1000.0

    #     this_class = pred["class"]
    #     logging.info(f"Predicted class: {this_class}")
    #     logging.info(
    #         f"Processing times: normalize={normalize_time_ms:.2f} ms | "
    #         f"buffer={buffer_time_ms:.2f} ms | predict={predict_time_ms:.2f} ms"
    #     )

    #     # optional: keep raw window for pickling
    #     kpi_raw_window.append(kpi_new.copy())
    #     if len(kpi_raw_window) > slice_len:
    #         kpi_raw_window.pop(0)

    #     try:
    #         pickle.dump({
    #             'input': np.array(window),
    #             'label': this_class,
    #             'input_raw': kpi_raw_window.copy()
    #         }, open('/home/class_output__'+str(int(time.time()*1e3))+'.pkl', 'wb'))
    #     except Exception as e:
    #         logging.warning(f"Pickle dump failed: {e}")

if __name__ == "__main__":
    main()
