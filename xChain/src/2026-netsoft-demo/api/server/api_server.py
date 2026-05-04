import time
import socket
import os
import json
import threading
import flask
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, send
from flask_cors import cross_origin
from flask import send_file
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, FileSystemEvent
from plot_generator import generate_charts
from container_host import ContainerHost
import glob
import csv
import shutil

# ── Environment variables ──────────────────────────────────────────────────────
base_dir          = os.environ.get('BASE_DIR', '/results/')
refresh_interval  = int(os.environ.get('REFRESH_INTERVAL', 2))
socket_port       = int(os.environ.get('SOCKET_PORT', 4000))

_MODELS_CONFIG_DEFAULT = json.dumps([
    {"value": "fastinfer", "label": "FastInfer", "color": "#76c893", "backgroundColor": "#ecfdf5", "icon": "/assets/images/icons/fastinf.png", "css_class": "fastinfer-card", "isSelected": True},
    {"value": "cnn",       "label": "CNN",       "color": "#fb8500", "backgroundColor": "#ffb703", "icon": "/assets/images/icons/cnn.png",    "css_class": "cnn-card",       "isSelected": True},
    {"value": "gnn",       "label": "GNN",       "color": "#dd2d4a", "backgroundColor": "",        "icon": "/assets/images/icons/gnn.png",    "css_class": "gnn-card",       "isSelected": False},
    {"value": "lstm",      "label": "LSTM",      "color": "#33658a", "backgroundColor": "",        "icon": "/assets/images/icons/lstm.png",   "css_class": "lstm-card",      "isSelected": False},
])
MODELS_CONFIG_RAW = os.environ.get('MODELS_CONFIG', _MODELS_CONFIG_DEFAULT)

# Ground truth mapping (traffic type → expected inference class)
GROUND_TRUTH_MAP = {
    "vr":     "eMBB",
    "haptic": "URLLC",
    "social": "eMBB",
    "iot":    "mMTC",
}

# ── Build hosts dict from env vars ────────────────────────────────────────────
# Traffic server agent
traffic_hostname = os.environ.get('TRAFFIC_SERVER_HOSTNAME', 'oai-traffic-server')
traffic_commands = {
    "vr":     os.environ.get('TRAFFIC_SERVER_CMD_VR',     'start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/vr.pcap'),
    "haptic": os.environ.get('TRAFFIC_SERVER_CMD_HAPTIC', 'start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/haptic.pcap'),
    "social": os.environ.get('TRAFFIC_SERVER_CMD_SOCIAL', 'start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/social.pcap'),
    "iot":    os.environ.get('TRAFFIC_SERVER_CMD_IOT',    'start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/iot.pcap'),
}

# SmartGW agent
smartgw_hostname = os.environ.get('SMARTGW_HOSTNAME', 'xchain-smartgw-demo')
smartgw_commands = {
    "selected_models": os.environ.get('SMARTGW_CMD_MODELS', 'start:{models}'),
}

hosts = {
    traffic_hostname: ContainerHost(traffic_hostname, traffic_commands),
    smartgw_hostname: ContainerHost(smartgw_hostname, smartgw_commands),
}

print(f"base_dir={base_dir}")
print(f"refresh_interval={refresh_interval}")
print(f"socket_port={socket_port}")
print(f"traffic_server={traffic_hostname}")
print(f"smartgw={smartgw_hostname}")

# ── TCP socket server (agents connect here) ────────────────────────────────────
serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
serversocket.bind(("0.0.0.0", socket_port))
serversocket.listen(5)


def send_socket_message_to_all_clients(msg):
    global IsRunning
    IsRunning = False
    for key, host in hosts.items():
        if host.is_conneced():
            host.send_message(f"{msg}")


def send_socket_command_to_all_clients_START(traffic_type, models):
    print(f"traffic_type={traffic_type} , models={models}")

    for key, host in hosts.items():
        if not host.is_conneced():
            print(f"Host ({host.hostname}) is NOT connected")

    for key, host in hosts.items():
        if key == traffic_hostname:
            client_command = host.get_command(traffic_type)
        elif key == smartgw_hostname:
            client_command = host.get_command('selected_models').format(
                traffic_type=traffic_type, models=models
            )
        else:
            continue

        host.send_message(client_command)
        print(f"Sent to {key}: {client_command}")


def client_listener(connection, address, socketio2):
    socketio2.emit('response', 'msg')
    agent_hostname = None

    while True:
        try:
            data = connection.recv(1024)
            if not data:
                break

            decoded = data.decode().strip()

            # First message from agent is its hostname
            if agent_hostname is None:
                agent_hostname = decoded
                if agent_hostname in hosts:
                    hosts[agent_hostname].connection = connection
                    hosts[agent_hostname].update_last_seen_at()
                    print(f"Agent connected: {agent_hostname}")
                else:
                    print(f"Unknown agent hostname: {agent_hostname}")
            else:
                # Subsequent messages are keep-alive signals
                if agent_hostname in hosts:
                    hosts[agent_hostname].update_last_seen_at()
                    print(f"Keep-alive from {agent_hostname}")

        except Exception as e:
            print(f"Error handling connection from {address}: {e}")
            break

    connection.close()


def start_socket_server(socketio2, aa):
    while True:
        client_connection, client_address = serversocket.accept()
        print(f"Accepted connection from {client_address}")
        client_thread = threading.Thread(
            target=client_listener,
            args=(client_connection, client_address, socketio2)
        )
        client_thread.start()


# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__,
            static_url_path='',
            static_folder='templates/browser')
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

current_exp = {
    "models": "",
    "traffic_type": "vr"
}

IsRunning = False


def write_current_experiment(traffic_type):
    """Write current experiment info to PVC so log_collector sidecars can read it."""
    ground_truth = GROUND_TRUTH_MAP.get(traffic_type, "eMBB")
    started_at = time.time()
    path = os.path.join(base_dir, "current_experiment.txt")
    os.makedirs(base_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"traffic_type={traffic_type}\n")
        f.write(f"ground_truth={ground_truth}\n")
        f.write(f"started_at={started_at}\n")
    print(f"Written current_experiment.txt: traffic_type={traffic_type}, ground_truth={ground_truth}")


@app.route('/api/models', methods=['GET'])
@cross_origin(supports_credentials=True)
def api_get_models():
    try:
        models = json.loads(MODELS_CONFIG_RAW)
    except Exception as e:
        return jsonify({"error": f"Invalid MODELS_CONFIG: {e}"}), 500
    return jsonify(models)


@app.route('/')
@cross_origin(supports_credentials=True)
def index():
    return render_template('browser/index.html')


@app.route('/start', methods=['GET'])
@cross_origin(supports_credentials=True)
def api_start():
    global IsRunning
    IsRunning = True
    start()
    return "started"


@app.route('/start', methods=['POST'])
@cross_origin(supports_credentials=True)
def api_post_start():
    global IsRunning, current_exp
    IsRunning = True
    data = request.json
    current_exp = data
    print("current exp", current_exp)
    start()
    send_websocket_message('events', "started")
    return data


def start():
    reset_stats_files()
    write_current_experiment(current_exp["traffic_type"])
    client_thread = threading.Thread(target=send_periodic_updates, args=())
    client_thread.start()
    send_socket_command_to_all_clients_START(current_exp["traffic_type"], current_exp["models"])
    watch_result_folder_changes(f"{base_dir}{current_exp['traffic_type']}/")


@app.route('/stop')
@cross_origin(supports_credentials=True)
def api_stop():
    send_socket_message_to_all_clients("stop")
    after_exp_finish()
    return "stopped"


@app.route('/current_exp', methods=['GET'])
@cross_origin(supports_credentials=True)
def api_current_exp():
    global current_exp
    return current_exp


@app.route('/hosts')
@cross_origin(supports_credentials=True)
def api_get_hosts():
    result = []
    for key, host in hosts.items():
        result.append({
            "name": host.hostname,
            "is_connected": host.is_conneced(),
        })
    return result


def get_stats():
    result = {}
    data_dir = f"{base_dir}{current_exp['traffic_type']}"

    accuracy_files = glob.glob(os.path.join(data_dir, "*accuracy*"))
    for file_path in accuracy_files:
        accuracy_value = None
        try:
            with open(file_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    accuracy_value = rows[-1].get("accuracy")
        except Exception:
            accuracy_value = None

        file_name = os.path.splitext(os.path.basename(file_path))[0]
        result[file_name] = accuracy_value

    try:
        _mc = json.loads(MODELS_CONFIG_RAW)
        _model_colors = {m["value"]: m.get("foregroundColor", m.get("color", "")) for m in _mc}
    except Exception:
        _model_colors = {}
    generate_charts(current_exp["models"], f"{base_dir}{current_exp['traffic_type']}", model_colors=_model_colors)
    send_websocket_message('events', "update_latency_plot")
    print("stats", result)
    return result


def reset_stats_files():
    folder = f"{base_dir}{current_exp['traffic_type']}/"
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)


@app.route('/stats')
@cross_origin(supports_credentials=True)
def api_get_stats():
    return get_stats()


@app.route('/results/latency')
def get_results_owd():
    filename = f"{base_dir}{current_exp['traffic_type']}/latency_comparison.png"
    return send_file(filename, mimetype='image/png')


# ── WebSocket ──────────────────────────────────────────────────────────────────
@socketio.on('message')
def handle_message(data):
    send_websocket_message('events', data)


@socketio.on('connect')
def test_connect(auth):
    emit('my response', {'data': 'Connected'})


@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected')


def send_websocket_message(event, msg):
    socketio.emit(event, msg)


def send_periodic_updates():
    global IsRunning
    send_websocket_message('statistics', {"count_sent": 0, "count_recv": 0})
    time.sleep(refresh_interval)
    while IsRunning:
        stats = get_stats()
        send_websocket_message('statistics', stats)
        time.sleep(refresh_interval)
    stats = get_stats()
    send_websocket_message('statistics', stats)


def after_exp_finish():
    send_websocket_message('events', "finished")
    send_socket_message_to_all_clients("stop")


folder_observer = Observer()


def watch_result_folder_changes(path):
    print("watching folder", path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    global IsRunning
    IsRunning = True
    patterns = ["*.csv"]
    event_handler = PatternMatchingEventHandler(patterns=patterns, ignore_directories=True, case_sensitive=False)


if __name__ == '__main__':
    client_thread = threading.Thread(target=start_socket_server, args=(socketio, 1))
    client_thread.start()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
