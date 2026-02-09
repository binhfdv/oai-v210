# orchestrator.py
import logging, time, pickle, os
import numpy as np
from app_server import (
    load_norm_internal, _call_buffer_update, predict_internal,
    load_model, load_norm_internal, _call_normalize, load_model as http_load_model
)
# We import xapp_control for TCP server helpers
from xapp_control import open_control_socket, receive_from_socket

# Environment-driven configuration
MODEL_PATH = os.getenv("MODEL_PATH", "/mnt/model/model.pt")
NORM_PATH  = os.getenv("NORM_PATH",  "/mnt/model/norm.pkl")
MODEL_TYPE = os.getenv("MODEL_TYPE", "Tv1")  # Tv1, Tv2, CNN
NCLASS     = int(os.getenv("NCLASS", "4"))
ALL_FEATS  = int(os.getenv("ALL_FEATS", "31"))
STREAM_ID  = os.getenv("STREAM_ID", "default")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def init_system():
    # load normalization parameters (call internal function)
    logging.info("Loading normalizer parameters (internal)")
    r = load_norm_internal({"norm_param_path": NORM_PATH, "all_feats_raw": ALL_FEATS})
    num_feats = r["num_feats"]
    slice_len = r["slice_len"]
    logging.info(f"Normalizer ready: num_feats={num_feats}, slice_len={slice_len}")

    # reset buffer
    logging.info("Resetting buffer")
    # Note: reset is in app_server.reset endpoint; we can clear buffers dict directly by calling /reset HTTP or mutate state.
    # To keep it simple use the HTTP endpoint via requests avoided — directly clear:
    from app_server import buffers
    buffers[STREAM_ID] = []
    logging.info(f"Buffer reset for stream {STREAM_ID}")

    # load model via internal call by simulating a JSON request into load_model()
    logging.info("Loading model with slice_len & num_feats from normalizer")
    # load_model is a Flask view; To reuse, call it via the internal helper: we'll call app_server.load_model by creating a dict-like object
    from app_server import load_model as flask_load_model_func
    # The load_model endpoint expects request.json; easiest is to call load_model_internal via app_server's route wrapper is tricky,
    # so we will call the same code path by calling load_model through a helper HTTP-less path:
    from app_server import load_model as load_model_http
    # Instead, we call the /load_model endpoint via a small internal helper:
    from app_server import load_model as load_model_view
    # create a minimal dict and call underlying load_model() via load_model_view
    # But Flask view expects flask.request; simpler: directly call the model-loading logic by importing functions in app_server
    # Build the request dict and call load_model via its function name by using the app_server.load_model function
    # To avoid needing to patch flask.request, reuse load_model by using load_model_internal style:
    from app_server import load_model as _dummy

    # We'll implement the model loading by calling app_server.load_model through a small helper defined in app_server:
    from app_server import load_model as unused  # no-op import to ensure function present

    # Simpler: call load_model endpoint by using load_model_internal logic - but we didn't create a separate internal loader.
    # So, call the Flask endpoint by performing a direct function call using a fake Flask request context.
    try:
        # lazy approach: use the Flask test_request_context to call the view function
        from app_server import app
        with app.test_request_context(json={
            "model_type": MODEL_TYPE,
            "model_path": MODEL_PATH,
            "Nclass": NCLASS,
            "slice_len": slice_len,
            "num_feats": num_feats
        }):
            resp = app.view_functions['load_model']()
            # resp is a Flask response object or tuple; get_json if present
            try:
                data = resp.get_json()
            except:
                data = resp
    except Exception as e:
        logging.exception("Failed to call load_model via test_request_context: %s", e)
        raise

    logging.info(f"Model loaded: {data}")
    return num_feats, slice_len


def main():
    num_feats, slice_len = init_system()

    # open TCP server (your API)
    control_sck = open_control_socket(4200)
    logging.info("Start listening on E2 interface...")

    last_timestamp = 0
    kpi_raw_window = []

    while True:
        data_sck = receive_from_socket(control_sck)
        if not data_sck:
            continue

        data_sck = data_sck.replace(',,', ',')
        if data_sck[0] == 'm':
            data_sck = data_sck[1:]

        kpi_new = np.fromstring(data_sck, sep=',')
        if kpi_new.shape[0] < ALL_FEATS:
            logging.info('Discarding KPI: too short')
            logging.info(f"Received data length: {kpi_new.shape[0]}, data: {data_sck}")
            continue

        ts = kpi_new[0]
        if ts <= last_timestamp:
            continue
        last_timestamp = ts

        # --- normalize step (internal call) ---
        t0 = time.time()
        norm = _call_normalize(kpi_new.tolist())
        t1 = time.time()
        normalize_time_ms = (t1 - t0) * 1000.0

        kpi_norm_vec = norm["normalized"]  # shape: [num_feats]

        # --- update buffer step (internal call) ---
        t0 = time.time()
        buf = _call_buffer_update(STREAM_ID, kpi_norm_vec, slice_len, num_feats)
        t1 = time.time()
        buffer_time_ms = (t1 - t0) * 1000.0

        ready = buf["ready"]
        if not ready:
            logging.info(f"Processing times: normalize={normalize_time_ms:.2f} ms | buffer={buffer_time_ms:.2f} ms | predict=--")
            continue

        window = buf["window"]  # shape [slice_len, num_feats]

        # --- predict step (internal call) ---
        t0 = time.time()
        pred = predict_internal({"window": window})
        t1 = time.time()
        predict_time_ms = (t1 - t0) * 1000.0

        this_class = pred["class"]
        logging.info(f"Predicted class: {this_class}")
        logging.info(
            f"Processing times: normalize={normalize_time_ms:.2f} ms | "
            f"buffer={buffer_time_ms:.2f} ms | predict={predict_time_ms:.2f} ms"
        )

        # optional: keep raw window for pickling
        kpi_raw_window.append(kpi_new.copy())
        if len(kpi_raw_window) > slice_len:
            kpi_raw_window.pop(0)

        try:
            pickle.dump({
                'input': np.array(window),
                'label': this_class,
                'input_raw': kpi_raw_window.copy()
            }, open('/home/class_output__'+str(int(time.time()*1e3))+'.pkl', 'wb'))
        except Exception as e:
            logging.warning(f"Pickle dump failed: {e}")

if __name__ == "__main__":
    main()
