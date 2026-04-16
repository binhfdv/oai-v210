"""
LSTM training for xChain traffic classification.
Task: 3-class (eMBB=0, mMTC=1, URLLC=2) from OAI KPM tractor_data.csv

Input:  sliding window of T consecutive KPM rows → shape (T, 17)
Output: class label at the last row of the window

Saves per T:
  lstm_model_T_{T}.pt          model weights + arch metadata
  lstm_scaler_T_{T}.pkl        fitted RobustScaler
  lstm_best_params_T_{T}.json  best Optuna params + test accuracy
"""

import os, json, pickle
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ---------------------------------------------------------------
# Config
# ---------------------------------------------------------------
DATA_PATH = "/home/lapdk/Downloads/tractor_data.csv"
OUT_DIR   = os.path.dirname(os.path.abspath(__file__))
T_VALUES  = [4, 8, 16, 32]
N_TRIALS  = 30
MAX_EPOCHS       = 60
FINAL_MAX_EPOCHS = 120
PATIENCE         = 10
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

# ---------------------------------------------------------------
# Data helpers
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
    Sliding window of size T over the (shuffled) dataframe.
    Each window: shape (T, M), label = class at last row.
    Returns X: (N, T, M) float32,  y: (N,) int64
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
    """Fit RobustScaler on train, apply to all splits. Works on (N, T, M) arrays."""
    N_tr, T_, M = X_tr.shape
    scaler = RobustScaler()
    scaler.fit(X_tr.reshape(-1, M))
    X_tr  = scaler.transform(X_tr.reshape(-1, M)).reshape(-1, T_, M)
    X_val = scaler.transform(X_val.reshape(-1, M)).reshape(X_val.shape)
    X_te  = scaler.transform(X_te.reshape(-1, M)).reshape(X_te.shape)
    return X_tr, X_val, X_te, scaler

# ---------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------
class KPMDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.long)
    def __len__(self):  return len(self.y)
    def __getitem__(self, i): return self.X[i], self.y[i]

# ---------------------------------------------------------------
# Model
# ---------------------------------------------------------------
class LSTMClassifier(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, dropout, num_classes=3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.norm = nn.LayerNorm(hidden_size)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, num_classes),
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.norm(out[:, -1, :])   # last timestep
        return self.head(out)

# ---------------------------------------------------------------
# Train / eval helpers
# ---------------------------------------------------------------
def run_epoch(model, loader, optimizer, criterion):
    model.train()
    total = 0.0
    for X_b, y_b in loader:
        X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
        optimizer.zero_grad()
        loss = criterion(model(X_b), y_b)
        loss.backward()
        optimizer.step()
        total += loss.item()
    return total / len(loader)

def evaluate(model, loader):
    model.eval()
    preds, labels = [], []
    with torch.no_grad():
        for X_b, y_b in loader:
            preds.extend(model(X_b.to(DEVICE)).argmax(1).cpu().tolist())
            labels.extend(y_b.tolist())
    return accuracy_score(labels, preds)

# ---------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------
def train_lstm_pipeline(df, T, n_trials=N_TRIALS):
    print(f"\n{'='*50}\nLSTM  T={T}\n{'='*50}")

    X, y = build_temporal_windows(df, T)
    X_tr, X_val, X_te, y_tr, y_val, y_te = split_windows(X, y)
    X_tr, X_val, X_te, scaler = scale_windows(X_tr, X_val, X_te)

    M = X_tr.shape[2]
    train_ds = KPMDataset(X_tr,  y_tr)
    val_ds   = KPMDataset(X_val, y_val)
    test_ds  = KPMDataset(X_te,  y_te)

    # ---- Optuna ----
    def objective(trial):
        hidden  = trial.suggest_categorical("hidden_size", [64, 128, 256])
        layers  = trial.suggest_int("num_layers", 1, 3)
        dropout = trial.suggest_float("dropout", 0.1, 0.4)
        lr      = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
        bs      = trial.suggest_categorical("batch_size", [64, 128, 256])

        tr_loader  = DataLoader(train_ds, batch_size=bs, shuffle=True)
        val_loader = DataLoader(val_ds,   batch_size=512)

        model     = LSTMClassifier(M, hidden, layers, dropout).to(DEVICE)
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
    tr_loader   = DataLoader(train_ds, batch_size=best["batch_size"], shuffle=True)
    val_loader  = DataLoader(val_ds,   batch_size=512)
    test_loader = DataLoader(test_ds,  batch_size=512)

    model     = LSTMClassifier(M, best["hidden_size"], best["num_layers"], best["dropout"]).to(DEVICE)
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
    model_path  = os.path.join(OUT_DIR, f"lstm_model_T_{T}.pt")
    scaler_path = os.path.join(OUT_DIR, f"lstm_scaler_T_{T}.pkl")
    params_path = os.path.join(OUT_DIR, f"lstm_best_params_T_{T}.json")

    torch.save({
        "model_state": best_state,
        "input_size":  M,
        "hidden_size": best["hidden_size"],
        "num_layers":  best["num_layers"],
        "dropout":     best["dropout"],
        "T":           T,
    }, model_path)
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    with open(params_path, "w") as f:
        json.dump({**best, "test_acc": test_acc, "T": T}, f, indent=2)

    print(f"Saved: {model_path}")
    return model, test_acc


# ---------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------
CLASS_NAMES = {0: "eMBB", 1: "mMTC", 2: "URLLC"}

def load_lstm_model(T, model_dir=OUT_DIR):
    """
    Load a trained LSTM model + scaler for window size T.
    Returns (model, scaler) ready for inference.
    """
    ckpt        = torch.load(os.path.join(model_dir, f"lstm_model_T_{T}.pt"), map_location=DEVICE)
    with open(os.path.join(model_dir, f"lstm_scaler_T_{T}.pkl"), "rb") as f:
        scaler  = pickle.load(f)

    model = LSTMClassifier(
        input_size  = ckpt["input_size"],
        hidden_size = ckpt["hidden_size"],
        num_layers  = ckpt["num_layers"],
        dropout     = ckpt["dropout"],
    ).to(DEVICE)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model, scaler

def lstm_predict(window, model, scaler):
    """
    Predict traffic class for a single KPM window.

    window : array-like of shape (T, M)  — raw (unscaled) KPM values
    Returns:
      class_id  : int   (0=eMBB, 1=mMTC, 2=URLLC)
      class_name: str
      probs     : list[float]  softmax probabilities for each class
    """
    window = np.array(window, dtype=np.float32)          # (T, M)
    T_, M  = window.shape
    scaled = scaler.transform(window.reshape(-1, M)).reshape(1, T_, M)
    x      = torch.tensor(scaled, dtype=torch.float32).to(DEVICE)

    with torch.no_grad():
        logits = model(x)                                # (1, 3)
        probs  = torch.softmax(logits, dim=1)[0].cpu().tolist()
        cls    = int(torch.argmax(logits, dim=1).item())

    return cls, CLASS_NAMES[cls], probs


# ---------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # ---- Inference mode: python train_lstm.py predict <T> ----
    if len(sys.argv) >= 3 and sys.argv[1] == "predict":
        T = int(sys.argv[2])
        print(f"Loading LSTM model T={T} ...")
        model, scaler = load_lstm_model(T)

        # Demo: load data, grab one window, predict
        df    = load_data()
        X, y  = build_temporal_windows(df, T)
        idx   = 0
        raw_window = X[idx]                   # (T, M)  already float32
        # Inverse-transform for a "raw" demo: use the raw values directly
        cls, name, probs = lstm_predict(raw_window, model, scaler)
        print(f"Window {idx}: true={CLASS_NAMES[y[idx]]}  pred={name}  probs={[f'{p:.3f}' for p in probs]}")

    # ---- Training mode (default) ----
    else:
        df = load_data()
        print(f"Data shape: {df.shape}")
        print(f"Class distribution:\n{df['class'].value_counts().sort_index()}")

        for T in T_VALUES:
            train_lstm_pipeline(df, T, n_trials=N_TRIALS)

        print("\nAll LSTM models trained.")
