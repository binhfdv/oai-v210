import logging, time, pickle, os, queue, threading
import numpy as np
from datetime import datetime
from collections import defaultdict
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
ALL_FEATS  = int(os.getenv("ALL_FEATS", "31"))
STREAM_ID  = os.getenv("STREAM_ID", "default")
PORT       = int(os.getenv("PORT", "5000"))
DATA_PORT  = int(os.getenv("DATA_PORT", "4300"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

logging.info(f"Configuration: MODEL_PATH={MODEL_PATH}, NORM_PATH={NORM_PATH},\n"
             f"MODEL_TYPE={MODEL_TYPE}, NCLASS={NCLASS}, ALL_FEATS={ALL_FEATS},\n"
             f"STREAM_ID={STREAM_ID}, PORT={PORT}, DATA_PORT={DATA_PORT}")

data_queue = queue.Queue()
last_timestamp_per_ue = {}

def init_system():
    logging.info("Loading normalizer parameters")
    r = load_norm_internal({"norm_param_path": NORM_PATH, "all_feats_raw": ALL_FEATS})
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
    from app_server import buffers
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
            norm = _call_normalize(kpi_new.tolist())
            t1 = time.perf_counter()
            normalize_time_ms = (t1 - t0) * 1000.0

            # Buffer update
            t0 = time.perf_counter()
            buf = _call_buffer_update(STREAM_ID, norm["normalized"], slice_len, num_feats)
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
            pred = predict_internal({"window": buf["window"]})
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
    control_sck = open_control_socket(DATA_PORT)
    logging.info(f"Listening on port {DATA_PORT}")

    t_listener = threading.Thread(target=socket_listener, args=(control_sck,), daemon=True)
    t_worker = threading.Thread(target=processing_worker, args=(num_feats, slice_len), daemon=True)
    t_listener.start()
    t_worker.start()
    t_listener.join()
    t_worker.join()


if __name__ == "__main__":
    main()
