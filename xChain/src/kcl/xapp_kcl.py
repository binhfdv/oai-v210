"""
xApp KCL — Dual xApp (LabelingxApp GNN + ResourcexApp DDQN) TCP inference server.
Receives KPM metrics, classifies UE load (Light/Medium/Heavy), allocates PRBs.

Pipeline: TCP recv → parse CSV → round buffer (NUM_UES lines) → GNN classification → DDQN PRB allocation → log

Buffering: lines are keyed by ran_ue_id. A duplicate ran_ue_id signals a new
batch — the current round is flushed first, ensuring each inference round
contains exactly one row per UE all from the same kpm_oai batch (no mixing).
"""

import os
import socket
import logging
import pickle
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv
from sklearn.preprocessing import RobustScaler

# --- Config ---
LISTEN_PORT    = int(os.getenv("LISTEN_PORT", "4500"))
MODELS_DIR     = os.getenv("MODELS_DIR", "/models")
LABELING_MODEL = os.getenv("LABELING_MODEL", "labeling_xapp.pth")
RESOURCE_MODEL = os.getenv("RESOURCE_MODEL", "resource_xapp.pth")
SCALER_FILE    = os.getenv("SCALER_FILE", "scaler.pkl")
NUM_UES        = int(os.getenv("NUM_UES", "1"))   # expected UEs per timestamp
LOG_LEVEL      = os.getenv("LOG_LEVEL", "INFO").upper()

# 5 features used by the GNN
FEATURE_COLS = [
    'RRU.PrbTotDl', 'DRB.UEThpDl', 'DRB.RlcSduDelayDl',
    'DRB.PdcpSduVolumeDL', 'DRB.PdcpSduVolumeUL'
]

# 11 fields sent by kpm-oai (in order)
KPM_FIELDS = [
    'timestamp', 'gnb_cu_cp_ue_e1ap', 'gnb_cu_ue_f1ap', 'ran_ue_id',
    'DRB.PdcpSduVolumeDL', 'DRB.PdcpSduVolumeUL', 'DRB.RlcSduDelayDl',
    'DRB.UEThpDl', 'DRB.UEThpUl', 'RRU.PrbTotDl', 'RRU.PrbTotUl'
]

LOAD_LABELS = ['Light', 'Medium', 'Heavy']
ACTION_MAP  = {0: 0.2, 1: 0.5, 2: 0.8}

logging.basicConfig(level=LOG_LEVEL, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("xapp-kcl")

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
logger.info(f"Using device: {device}")


# --- Model Definitions (must match training architecture) ---

class LabelingxApp(nn.Module):
    """GNN (SAGEConv) — classifies each UE as Light / Medium / Heavy load."""

    def __init__(self, in_dim: int, hidden_dim: int = 64):
        super().__init__()
        self.conv1 = SAGEConv(in_dim, hidden_dim)
        self.conv2 = SAGEConv(hidden_dim, hidden_dim)
        self.conv3 = SAGEConv(hidden_dim, hidden_dim // 2)
        self.bn1 = nn.BatchNorm1d(hidden_dim)
        self.bn2 = nn.BatchNorm1d(hidden_dim)
        self.bn3 = nn.BatchNorm1d(hidden_dim // 2)
        self.dropout = nn.Dropout(0.2)
        self.load_head = nn.Sequential(
            nn.Linear(hidden_dim // 2, 32),
            nn.ReLU(),
            nn.Linear(32, 3)
        )
        self.embeddings = None

    def forward(self, x, edge_index):
        h = F.relu(self.bn1(self.conv1(x, edge_index)))
        h = F.relu(self.bn2(self.conv2(h, edge_index)))
        h = F.relu(self.bn3(self.conv3(h, edge_index)))
        h = self.dropout(h)
        self.embeddings = h.detach()
        return self.load_head(h)


class ResourcexApp:
    """DDQN — selects PRB allocation action (20% / 50% / 80%) per UE."""

    def __init__(self):
        self.action_dim = 3
        self.q_net = nn.Sequential(
            nn.Linear(8, 128), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, 3)
        )

    def act(self, state: np.ndarray, epsilon: float = 0.0) -> int:
        if np.random.rand() < epsilon:
            return np.random.randint(self.action_dim)
        state_t = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            return self.q_net(state_t).argmax().item()


# --- Preprocessor ---

class KPMPreprocessor:
    def __init__(self, scaler=None):
        self.scaler = scaler or RobustScaler()
        self._fitted = scaler is not None

    def transform_to_graph(self, df: pd.DataFrame) -> Data:
        features = df[FEATURE_COLS].copy()
        for col in FEATURE_COLS:
            features[col] = pd.to_numeric(features[col], errors='coerce')
        features = features.ffill().fillna(0.0)

        if not self._fitted:
            scaled = self.scaler.fit_transform(features.values)
            self._fitted = True
            logger.info("RobustScaler fitted on first batch")
        else:
            scaled = self.scaler.transform(features.values)

        n = len(df)
        # Cyclic graph: every node connects to its neighbours
        if n == 1:
            src, dst = [0], [0]
        else:
            src = list(range(n)) + list(range(1, n)) + list(range(n - 1)) + [0, n - 1]
            dst = list(range(n)) + list(range(n - 1)) + list(range(1, n)) + [n - 1, 0]

        edge_index = torch.tensor([src, dst], dtype=torch.long).to(device)
        x = torch.tensor(scaled, dtype=torch.float).to(device)
        return Data(x=x, edge_index=edge_index)


# --- Inference Engine ---

class DualxAppInference:
    def __init__(self, labeling_path: str, resource_path: str, scaler=None):
        self.labeling = LabelingxApp(in_dim=len(FEATURE_COLS)).to(device)
        self.labeling.load_state_dict(torch.load(labeling_path, map_location=device))
        self.labeling.eval()

        self.resource = ResourcexApp()
        self.resource.q_net.load_state_dict(torch.load(resource_path, map_location=device))
        self.resource.q_net.eval()

        self.preprocessor = KPMPreprocessor(scaler=scaler)
        logger.info(f"LabelingxApp loaded from {labeling_path}")
        logger.info(f"ResourcexApp loaded from {resource_path}")

    def predict(self, df: pd.DataFrame) -> dict:
        graph = self.preprocessor.transform_to_graph(df)

        with torch.no_grad():
            logits = self.labeling(graph.x, graph.edge_index)
            load_preds = logits.argmax(dim=1).cpu().numpy()
            embeddings = self.labeling.embeddings.cpu().numpy()

        features = df[FEATURE_COLS].apply(pd.to_numeric, errors='coerce').fillna(0.0)
        prb   = features['RRU.PrbTotDl'].values
        tput  = features['DRB.UEThpDl'].values
        delay = features['DRB.RlcSduDelayDl'].values

        actions, allocations = [], []
        for i, load in enumerate(load_preds):
            # 8D RL state (must match training construction exactly)
            state = np.array([
                float(load),
                prb[i]   / 100.0,
                tput[i]  / 20.0,
                delay[i] / 0.01,
                embeddings[i, 0],
                (prb[i]   / 100.0) * 0.1,
                (tput[i]  / 20.0)  * 0.1,
                (delay[i] / 0.01)  * 0.1,
            ], dtype=np.float32)
            a = self.resource.act(state)
            actions.append(a)
            allocations.append(ACTION_MAP[a])

        # Normalize if sum exceeds 1.0
        total = sum(allocations)
        if total > 1.0:
            allocations = [a / total for a in allocations]

        return {
            'load_labels': [LOAD_LABELS[p] for p in load_preds],
            'allocations': allocations,
            'actions': actions,
            'num_ues': len(df),
        }


# --- TCP Server ---


def _flush_round(round_buf: dict, engine: DualxAppInference):
    """Run inference on a complete round and log results."""
    rows = sorted(round_buf.values(), key=lambda r: r.get('ran_ue_id', ''))
    df = pd.DataFrame(rows)
    result = engine.predict(df)
    ts = rows[0]['timestamp']
    for i in range(result['num_ues']):
        r = df.iloc[i]
        logger.info(
            f"[{ts}] UE {i + 1}/{NUM_UES} | "
            f"ran_ue_id={r['ran_ue_id']} | "
            f"PRB={r['RRU.PrbTotDl']} "
            f"ThpDl={r['DRB.UEThpDl']} "
            f"ThpUl={r['DRB.UEThpUl']} "
            f"RlcDelay={r['DRB.RlcSduDelayDl']} "
            f"VolDL={r['DRB.PdcpSduVolumeDL']} "
            f"VolUL={r['DRB.PdcpSduVolumeUL']} | "
            f"Load: {result['load_labels'][i]:6s} | "
            f"PRB alloc: {result['allocations'][i]:.0%}"
        )


def handle_client(conn, addr, engine: DualxAppInference):
    logger.info(f"Client connected: {addr} | expecting NUM_UES={NUM_UES} per round")
    buf = ""
    round_buf = {}   # ran_ue_id → row for the current round (one entry per UE)

    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data.decode('utf-8')

            if '\n' not in buf:
                continue

            complete, buf = buf.rsplit('\n', 1)

            for line in complete.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) != len(KPM_FIELDS):
                    logger.warning(f"Skipping malformed line: expected {len(KPM_FIELDS)} fields, got {len(parts)}")
                    continue
                row = dict(zip(KPM_FIELDS, parts))
                ue_id = row.get('ran_ue_id', '')

                # A duplicate ran_ue_id means a new kpm batch is starting
                if ue_id in round_buf:
                    if len(round_buf) == NUM_UES:
                        _flush_round(round_buf, engine)
                    else:
                        logger.warning(
                            f"Incomplete round ({len(round_buf)}/{NUM_UES} UEs) "
                            f"before new batch — discarding"
                        )
                    round_buf = {}

                round_buf[ue_id] = row

                # Full round collected — run inference
                if len(round_buf) == NUM_UES:
                    _flush_round(round_buf, engine)
                    round_buf = {}

    except Exception as e:
        logger.error(f"Error with client {addr}: {e}")
    finally:
        conn.close()
        logger.info(f"Client disconnected: {addr}")


def load_engine() -> DualxAppInference:
    labeling_path = os.path.join(MODELS_DIR, LABELING_MODEL)
    resource_path = os.path.join(MODELS_DIR, RESOURCE_MODEL)
    scaler_path   = os.path.join(MODELS_DIR, SCALER_FILE)

    scaler = None
    if os.path.exists(scaler_path):
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        logger.info(f"Scaler loaded from {scaler_path}")
    else:
        logger.warning(f"scaler.pkl not found at {scaler_path} — will fit on first batch received")

    return DualxAppInference(labeling_path, resource_path, scaler=scaler)


def start_server(engine: DualxAppInference):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', LISTEN_PORT))
    srv.listen(5)
    logger.info(f"xApp KCL listening on port {LISTEN_PORT}")
    while True:
        conn, addr = srv.accept()
        handle_client(conn, addr, engine)


if __name__ == "__main__":
    engine = load_engine()
    start_server(engine)
