"""
Fit and save scalers from training data.

- logreg_scaler.pkl : StandardScaler fitted on all training nodes (for LogisticRegression)
- gnn_scaler.pkl    : RobustScaler fitted on all training nodes (global, for GNN/GCN inference)

Usage:
    python3 save_scalers.py --train mmtc_train.csv --window_size 5 --out_dir .
"""

import argparse
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, RobustScaler

FEATURE_COLS = [
    'RRU.PrbTotDl', 'DRB.UEThpDl', 'DRB.RlcSduDelayDl',
    'DRB.PdcpSduVolumeDL', 'DRB.PdcpSduVolumeUL'
]


def load_features(filepath: str, window_size: int) -> np.ndarray:
    kpm = pd.read_csv(filepath)
    print(f"Loaded {len(kpm)} rows from {filepath}")
    kpm['window'] = np.arange(len(kpm)) // window_size

    all_feats = []
    for _, window in kpm.groupby('window'):
        if len(window) < max(2, window_size // 2):
            continue
        feats = window[FEATURE_COLS].ffill().fillna(0).values.astype(np.float32)
        all_feats.append(feats)

    X = np.concatenate(all_feats, axis=0)
    print(f"Total nodes: {X.shape[0]}, features: {X.shape[1]}")
    return X


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train',       default='mmtc_train.csv')
    parser.add_argument('--window_size', type=int, default=5)
    parser.add_argument('--out_dir',     default='.')
    args = parser.parse_args()

    X = load_features(args.train, args.window_size)

    # StandardScaler for LogisticRegression
    lr_scaler = StandardScaler()
    lr_scaler.fit(X)
    lr_path = f'{args.out_dir}/logreg_scaler.pkl'
    joblib.dump(lr_scaler, lr_path)
    print(f"Saved: {lr_path}")

if __name__ == '__main__':
    main()
