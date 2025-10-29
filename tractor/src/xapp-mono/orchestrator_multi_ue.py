import logging, time, pickle, os, queue, threading
import numpy as np
from datetime import datetime
from app_server import (
    load_norm_internal, _call_buffer_update, predict_internal,
    load_model, _call_normalize
)
from xapp_control import open_control_socket, receive_from_socket

# --- Configuration ---
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/model.pt")
NORM_PATH  = os.getenv("NORM_PATH",  "/mnt/model/norm.pkl")
MODEL_TYPE = os.getenv("MODEL_TYPE", "Tv1")
NCLASS     = int(os.getenv("NCLASS", "4"))
ALL_FEATS  = int(os.getenv("ALL_FEATS", "32"))  # now includes the readable timestamp
STREAM_ID  = os.getenv("STREAM_ID", "default")
PORT       = int(os.getenv("PORT", "4200"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Shared queue for incoming data rows
data_queue = queue.Queue()

# Dictionary to track last timestamp per UE (if needed)
last_timestamp_per_ue = {}

def init_system():
    logging.info("Loading normalizer parameters")
    r = load_norm_internal({"norm_param_path": NORM_PATH, "all_feats_raw": ALL_FEATS - 1})  # minus the timestamp
    num_feats = r["num_feats"]
    slice_len = r["slice_len"]
    logging.info(f"Normalizer ready: num_feats={num_feats}, slice_len={slice_len}")

    from app_server import buffers
    buffers[STREAM_ID] = []
    logging.info(f"Buffer reset for stream {STREAM_ID}")

    from app_server import app
    with app.test_request_context(json={
        "model_type": MODEL_TYPE,
        "model_path": MODEL_PATH,
        "Nclass": NCLASS,
        "slice_len": slice_len,
        "num_feats": num_feats
    }):
        resp = app.view_functions['load_model']()
        try:
            data = resp.get_json()
        except:
            data = resp

    logging.info(f"Model loaded: {data}")
    return num_feats, slice_len


def socket_listener(control_sck):
    """Receive data from TCP and enqueue each UE row."""
    logging.info("Socket listener started...")
    while True:
        data = receive_from_socket(control_sck)
        if not data:
            continue

        # Each UE metric row separated by newline
        rows = [r.strip() for r in data.split("\n") if r.strip()]
        recv_time = time.time()

        for r in rows:
            # Drop readable timestamp (first field)
            parts = r.split(",")
            if len(parts) < 2:
                continue

            # remove first column (readable timestamp)
            numeric_line = ",".join(parts[1:])

            # enqueue with received time
            data_queue.put((numeric_line, recv_time))


def processing_worker(num_feats, slice_len):
    """Worker that processes queued KPI data."""
    from app_server import buffers
    logging.info("Processing worker started...")

    kpi_raw_window = []

    while True:
        try:
            data_line, recv_time = data_queue.get(block=True)
            start_proc = time.time()
            queue_wait_ms = (start_proc - recv_time) * 1000.0

            # Convert line to numeric array
            kpi_new = np.fromstring(data_line, sep=',')
            if kpi_new.shape[0] < ALL_FEATS - 1:
                logging.info(f"Discarded: too few features ({kpi_new.shape[0]})")
                data_queue.task_done()
                continue

            ts_int = int(kpi_new[0])  # integer timestamp
            ue_id = kpi_new[2] if kpi_new.shape[0] > 2 else 0

            # optional timestamp filter per UE
            last_ts = last_timestamp_per_ue.get(ue_id, 0)
            if ts_int <= last_ts:
                data_queue.task_done()
                continue
            last_timestamp_per_ue[ue_id] = ts_int

            # Normalize
            t0 = time.time()
            norm = _call_normalize(kpi_new[1:].tolist())  # exclude timestamp
            t1 = time.time()
            normalize_time_ms = (t1 - t0) * 1000.0

            # Buffer update
            t0 = time.time()
            buf = _call_buffer_update(STREAM_ID, norm["normalized"], slice_len, num_feats)
            t1 = time.time()
            buffer_time_ms = (t1 - t0) * 1000.0

            if not buf["ready"]:
                logging.info(
                    f"[UE={ue_id}] queue_wait={queue_wait_ms:.2f} ms | "
                    f"normalize={normalize_time_ms:.2f} ms | buffer={buffer_time_ms:.2f} ms | predict=--"
                )
                data_queue.task_done()
                continue

            window = buf["window"]

            # Predict
            t0 = time.time()
            pred = predict_internal({"window": window})
            t1 = time.time()
            predict_time_ms = (t1 - t0) * 1000.0

            pred_class = pred["class"]
            logging.info(
                f"[UE={ue_id}] Predicted class: {pred_class} | "
                f"queue_wait={queue_wait_ms:.2f} ms | normalize={normalize_time_ms:.2f} ms | "
                f"buffer={buffer_time_ms:.2f} ms | predict={predict_time_ms:.2f} ms"
            )

            # Save sample
            try:
                pickle.dump(
                    {
                        'input': np.array(window),
                        'label': pred_class,
                        'input_raw': kpi_new.copy(),
                        'ue_id': ue_id,
                        'timestamp': ts_int
                    },
                    open(f'/home/class_output_{ue_id}_{ts_int}.pkl', 'wb')
                )
            except Exception as e:
                logging.warning(f"Pickle dump failed: {e}")

            data_queue.task_done()

        except Exception as e:
            logging.error(f"Processing error: {e}")
            time.sleep(0.5)


def main():
    num_feats, slice_len = init_system()
    control_sck = open_control_socket(PORT)
    logging.info(f"Listening on port {PORT}")

    # start listener and worker threads
    t_listener = threading.Thread(target=socket_listener, args=(control_sck,), daemon=True)
    t_worker = threading.Thread(target=processing_worker, args=(num_feats, slice_len), daemon=True)

    t_listener.start()
    t_worker.start()

    t_listener.join()
    t_worker.join()


if __name__ == "__main__":
    main()
