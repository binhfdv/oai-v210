"""
GNN (feature graph) training for xChain traffic classification.
Task: 3-class (eMBB=0, mMTC=1, URLLC=2) from OAI KPM tractor_data.csv

Graph construction (Option A — feature graph):
  - 17 nodes, one per KPI feature
  - Node features: KPI values over T timesteps → shape (T,) per node
  - Edges: pairs of KPIs with |Pearson correlation| > CORR_THRESHOLD
            (computed once from training windows, reused for all splits)
  - Graph-level classification (global mean pool → FC → 3 classes)

One graph per sliding window. Same T values as XGBoost: {4, 8, 16, 32}.

Saves per T:
  gnn_model_T_{T}.pt          model weights + arch metadata
  gnn_edge_index_T_{T}.pt     edge_index tensor (reuse at inference)
  gnn_scaler_T_{T}.pkl        fitted RobustScaler
  gnn_best_params_T_{T}.json  best Optuna params + test accuracy
"""

import os, json, pickle
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.loader import DataLoader as GeoDataLoader
from torch_geometric.nn import SAGEConv, global_mean_pool
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ---------------------------------------------------------------
# Config
# ---------------------------------------------------------------
DATA_PATH      = "/home/lapdk/Downloads/tractor_data.csv"
OUT_DIR        = os.path.dirname(os.path.abspath(__file__))
T_VALUES       = [4, 8, 16, 32]
CORR_THRESHOLD = 0.5          # |Pearson| > threshold → edge between KPI nodes
N_TRIALS       = 20
MAX_EPOCHS       = 60
FINAL_MAX_EPOCHS = 120
PATIENCE         = 10
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

# ---------------------------------------------------------------
# Data helpers  (same pipeline as XGBoost / LSTM)
# ---------------------------------------------------------------
def clean_feature_names(df):
    df = df.copy()
    df.columns = (
        df.columns
        .str.replace('[', '', regex=False).str.replace(']', '', regex=False)
        .str.replace('(', '', regex=False).str.replace(')', '', regex=False)
        .str.replace('%', 'pct', regex=False).str.replace(' ', '_', regex=False)
        .str.replace('/', '_', regex=False).str.replace('-', '_', regex=False)
    )
    return df

def load_data():
    df = pd.read_csv(DATA_PATH)
    df = df[df["class"] != 3]
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    return clean_feature_names(df)

def build_temporal_windows(df, T, label_col="class"):
    """
    Returns X: (N, T, M) float32  — NOT flattened
            y: (N,)       int64
    Label is the class at the last row of each window.
    """
    values = df.drop(columns=[label_col]).values.astype(np.float32)
    labels = df[label_col].values.astype(np.int64)
    X, y = [], []
    for i in range(len(df) - T + 1):
        X.append(values[i:i+T])
        y.append(labels[i + T - 1])
    return np.array(X), np.array(y)

def split_windows(X, y):
    """90 / 5 / 5  train / val / test  (stratified)."""
    X_tr, X_tmp, y_tr, y_tmp = train_test_split(X, y, test_size=0.10, random_state=0, stratify=y)
    X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.50, random_state=0, stratify=y_tmp)
    return X_tr, X_val, X_te, y_tr, y_val, y_te

def scale_windows(X_tr, X_val, X_te):
    """
    Fit RobustScaler on train timesteps (N*T, M),
    apply to all splits. Preserves (N, T, M) shape.
    """
    N_tr, T_, M = X_tr.shape
    scaler = RobustScaler()
    scaler.fit(X_tr.reshape(-1, M))
    X_tr  = scaler.transform(X_tr.reshape(-1, M)).reshape(-1, T_, M)
    X_val = scaler.transform(X_val.reshape(-1, M)).reshape(X_val.shape)
    X_te  = scaler.transform(X_te.reshape(-1, M)).reshape(X_te.shape)
    return X_tr, X_val, X_te, scaler

# ---------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------
def build_edge_index(X_train, threshold=CORR_THRESHOLD):
    """
    Build a static KPI-feature graph from training data.

    X_train: (N, T, M)
    Flatten to (N*T, M), compute (M, M) Pearson correlation matrix,
    add a directed edge (i→j) for every pair where |corr(i,j)| > threshold.

    Returns edge_index: LongTensor of shape (2, E)
    """
    N, T_, M = X_train.shape
    flat = X_train.reshape(-1, M)           # (N*T, M)
    corr = np.corrcoef(flat.T)              # (M, M)
    np.fill_diagonal(corr, 0.0)             # no self-loops
    rows, cols = np.where(np.abs(corr) > threshold)
    edge_index = torch.tensor(np.stack([rows, cols]), dtype=torch.long)
    print(f"  Feature graph: {M} nodes, {edge_index.shape[1]} edges "
          f"(|corr|>{threshold})")
    return edge_index

def windows_to_graphs(X, y, edge_index):
    """
    Convert (N, T, M) windows to a list of PyG Data objects.

    Each graph:
      x          : (M, T)  — node i has its T KPI values as features
      edge_index : (2, E)  — shared static graph structure
      y          : (1,)    — traffic class label
    """
    graphs = []
    for i in range(len(X)):
        node_feats = torch.tensor(X[i].T, dtype=torch.float32)   # (M, T)
        graphs.append(Data(
            x=node_feats,
            edge_index=edge_index,
            y=torch.tensor([y[i]], dtype=torch.long),
        ))
    return graphs

# ---------------------------------------------------------------
# Model
# ---------------------------------------------------------------
class GNNClassifier(nn.Module):
    """
    Stack of SAGEConv layers → global mean pooling → MLP head.
    in_dim  = T  (each node's feature vector has T values)
    """
    def __init__(self, in_dim, hidden_dim, num_layers, dropout, num_classes=3):
        super().__init__()
        self.convs = nn.ModuleList()
        self.bns   = nn.ModuleList()

        self.convs.append(SAGEConv(in_dim, hidden_dim, aggr='mean'))
        self.bns.append(nn.BatchNorm1d(hidden_dim))
        for _ in range(num_layers - 1):
            self.convs.append(SAGEConv(hidden_dim, hidden_dim, aggr='mean'))
            self.bns.append(nn.BatchNorm1d(hidden_dim))

        self.dropout = nn.Dropout(dropout)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, num_classes),
        )

    def forward(self, x, edge_index, batch):
        for conv, bn in zip(self.convs, self.bns):
            x = F.relu(bn(conv(x, edge_index)))
            x = self.dropout(x)
        x = global_mean_pool(x, batch)   # (batch_size, hidden_dim)
        return self.head(x)

# ---------------------------------------------------------------
# Train / eval helpers
# ---------------------------------------------------------------
def run_epoch(model, loader, optimizer, criterion):
    model.train()
    total = 0.0
    for batch in loader:
        batch = batch.to(DEVICE)
        optimizer.zero_grad()
        out  = model(batch.x, batch.edge_index, batch.batch)
        loss = criterion(out, batch.y.view(-1))
        loss.backward()
        optimizer.step()
        total += loss.item()
    return total / len(loader)

def evaluate(model, loader):
    model.eval()
    preds, labels = [], []
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(DEVICE)
            out = model(batch.x, batch.edge_index, batch.batch)
            preds.extend(out.argmax(1).cpu().tolist())
            labels.extend(batch.y.view(-1).cpu().tolist())
    return accuracy_score(labels, preds)

# ---------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------
def train_gnn_pipeline(df, T, n_trials=N_TRIALS):
    print(f"\n{'='*50}\nGNN (feature graph)  T={T}\n{'='*50}")

    X, y = build_temporal_windows(df, T)
    X_tr, X_val, X_te, y_tr, y_val, y_te = split_windows(X, y)
    X_tr, X_val, X_te, scaler = scale_windows(X_tr, X_val, X_te)

    # Build graph topology from training data only
    edge_index = build_edge_index(X_tr)
    edge_index_dev = edge_index.to(DEVICE)

    M = X_tr.shape[2]   # number of KPI features (17)
    # in_dim for GNN nodes = T (each node has T timestep values)
    in_dim = T

    train_graphs = windows_to_graphs(X_tr,  y_tr,  edge_index)
    val_graphs   = windows_to_graphs(X_val, y_val, edge_index)
    test_graphs  = windows_to_graphs(X_te,  y_te,  edge_index)

    # ---- Optuna ----
    def objective(trial):
        hidden  = trial.suggest_categorical("hidden_dim", [64, 128, 256])
        layers  = trial.suggest_int("num_layers", 1, 3)
        dropout = trial.suggest_float("dropout", 0.1, 0.4)
        lr      = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
        bs      = trial.suggest_categorical("batch_size", [64, 128, 256])

        tr_loader  = GeoDataLoader(train_graphs, batch_size=bs, shuffle=True)
        val_loader = GeoDataLoader(val_graphs,   batch_size=512)

        model     = GNNClassifier(in_dim, hidden, layers, dropout).to(DEVICE)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
        criterion = nn.CrossEntropyLoss()

        best_acc, no_improve = 0.0, 0
        for _ in range(MAX_EPOCHS):
            run_epoch(model, tr_loader, optimizer, criterion)
            acc = evaluate(model, val_loader)
            if acc > best_acc:
                best_acc = acc
                no_improve = 0
            else:
                no_improve += 1
            if no_improve >= PATIENCE:
                break
        return best_acc

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    best = study.best_trial.params
    print(f"Best params: {best}")
    print(f"Best val acc: {study.best_value:.4f}")

    # ---- Final model ----
    tr_loader   = GeoDataLoader(train_graphs, batch_size=best["batch_size"], shuffle=True)
    val_loader  = GeoDataLoader(val_graphs,   batch_size=512)
    test_loader = GeoDataLoader(test_graphs,  batch_size=512)

    model     = GNNClassifier(in_dim, best["hidden_dim"], best["num_layers"], best["dropout"]).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=best["lr"])
    criterion = nn.CrossEntropyLoss()

    best_acc, best_state, no_improve = 0.0, None, 0
    for epoch in range(FINAL_MAX_EPOCHS):
        run_epoch(model, tr_loader, optimizer, criterion)
        acc = evaluate(model, val_loader)
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
        if no_improve >= PATIENCE * 2:
            break
        if (epoch + 1) % 10 == 0:
            print(f"  epoch {epoch+1:3d}  val_acc={acc:.4f}  best={best_acc:.4f}")

    model.load_state_dict(best_state)
    test_acc = evaluate(model, test_loader)
    print(f"Test accuracy: {test_acc:.4f}")

    # ---- Save ----
    model_path  = os.path.join(OUT_DIR, f"gnn_model_T_{T}.pt")
    edge_path   = os.path.join(OUT_DIR, f"gnn_edge_index_T_{T}.pt")
    scaler_path = os.path.join(OUT_DIR, f"gnn_scaler_T_{T}.pkl")
    params_path = os.path.join(OUT_DIR, f"gnn_best_params_T_{T}.json")

    torch.save({
        "model_state": best_state,
        "in_dim":      in_dim,
        "hidden_dim":  best["hidden_dim"],
        "num_layers":  best["num_layers"],
        "dropout":     best["dropout"],
        "T":           T,
        "M":           M,
    }, model_path)
    torch.save(edge_index, edge_path)
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    with open(params_path, "w") as f:
        json.dump({**best, "test_acc": test_acc, "T": T,
                   "num_edges": edge_index.shape[1],
                   "corr_threshold": CORR_THRESHOLD}, f, indent=2)

    print(f"Saved: {model_path}")
    return model, test_acc


# ---------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------
CLASS_NAMES = {0: "eMBB", 1: "mMTC", 2: "URLLC"}

def load_gnn_model(T, model_dir=OUT_DIR):
    """
    Load a trained GNN model + edge_index + scaler for window size T.
    Returns (model, edge_index, scaler) ready for inference.
    """
    ckpt = torch.load(os.path.join(model_dir, f"gnn_model_T_{T}.pt"), map_location=DEVICE)
    edge_index = torch.load(os.path.join(model_dir, f"gnn_edge_index_T_{T}.pt"), map_location=DEVICE)
    with open(os.path.join(model_dir, f"gnn_scaler_T_{T}.pkl"), "rb") as f:
        scaler = pickle.load(f)

    model = GNNClassifier(
        in_dim     = ckpt["in_dim"],
        hidden_dim = ckpt["hidden_dim"],
        num_layers = ckpt["num_layers"],
        dropout    = ckpt["dropout"],
    ).to(DEVICE)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model, edge_index, scaler

def gnn_predict(window, model, edge_index, scaler):
    """
    Predict traffic class for a single KPM window.

    window     : array-like of shape (T, M)  — raw (unscaled) KPM values
    edge_index : LongTensor (2, E) from load_gnn_model()
    Returns:
      class_id  : int   (0=eMBB, 1=mMTC, 2=URLLC)
      class_name: str
      probs     : list[float]  softmax probabilities for each class
    """
    window = np.array(window, dtype=np.float32)           # (T, M)
    T_, M  = window.shape
    scaled = scaler.transform(window.reshape(-1, M)).reshape(T_, M)

    # Build single graph: nodes=(M, T), edge_index=(2, E), batch=zeros(M)
    node_feats = torch.tensor(scaled.T, dtype=torch.float32).to(DEVICE)   # (M, T)
    batch      = torch.zeros(M, dtype=torch.long).to(DEVICE)

    with torch.no_grad():
        logits = model(node_feats, edge_index.to(DEVICE), batch)           # (1, 3)
        probs  = torch.softmax(logits, dim=1)[0].cpu().tolist()
        cls    = int(torch.argmax(logits, dim=1).item())

    return cls, CLASS_NAMES[cls], probs


# ---------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # ---- Inference mode: python train_gnn.py predict <T> ----
    if len(sys.argv) >= 3 and sys.argv[1] == "predict":
        T = int(sys.argv[2])
        print(f"Loading GNN model T={T} ...")
        model, edge_index, scaler = load_gnn_model(T)

        # Demo: load data, grab one window, predict
        df   = load_data()
        X, y = build_temporal_windows(df, T)
        idx  = 0
        raw_window = X[idx]                   # (T, M) float32
        cls, name, probs = gnn_predict(raw_window, model, edge_index, scaler)
        print(f"Window {idx}: true={CLASS_NAMES[y[idx]]}  pred={name}  probs={[f'{p:.3f}' for p in probs]}")

    # ---- Training mode (default) ----
    else:
        df = load_data()
        print(f"Data shape: {df.shape}")
        print(f"Class distribution:\n{df['class'].value_counts().sort_index()}")

        for T in T_VALUES:
            train_gnn_pipeline(df, T, n_trials=N_TRIALS)

        print("\nAll GNN models trained.")
