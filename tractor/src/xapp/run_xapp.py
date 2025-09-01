import logging, time, pickle, os
import numpy as np
import torch
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
            # (rare in sim) multi-part framing not used; just fall through
            data_sck = data_sck[1:]

        kpi_new = np.fromstring(data_sck, sep=',')
        if kpi_new.shape[0] < ALL_FEATS:
            logging.info('Discarding KPI: too short')
            continue

        ts = kpi_new[0]
        if ts <= last_timestamp:
            continue
        last_timestamp = ts

        # normalize one KPI vector -> filtered+normalized vector
        norm = requests.post(f"{NORMALIZER}/normalize", json={"kpi": kpi_new.tolist()}).json()
        kpi_norm_vec = norm["normalized"]  # shape: [num_feats]

        # update buffer
        buf = requests.post(f"{BUFFER}/update", json={
            "stream": STREAM_ID,
            "kpi": kpi_norm_vec,
            "slice_len": slice_len,
            "num_feats": num_feats
        }).json()

        ready = buf["ready"]
        if not ready:
            continue

        window = buf["window"]  # shape [slice_len, num_feats]

        # predict
        pred = requests.post(f"{MODEL}/predict", json={
            "window": window
        }).json()

        this_class = pred["class"]
        logging.info(f"Predicted class: {this_class}")

        # optional: keep raw window for pickling (like your original)
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
