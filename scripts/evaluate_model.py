"""Quantitative evaluation of the Random Forest gesture classifier.

Reports everything an IEEE Results section needs:
  - dataset summary (per-class counts, class imbalance)
  - hold-out 80/20 accuracy
  - per-class precision / recall / F1 (classification_report)
  - stratified k-fold cross-validation (mean +/- std)
  - confusion matrix (counts + row-normalised), saved as PNG

Does NOT overwrite the deployed model (assets/models/gesture_classifier.pkl).
Run:  python scripts/evaluate_model.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "gesture_data.csv"
OUT_DIR = PROJECT_ROOT / "data" / "presentation_charts"
N_ESTIMATORS = 100
RANDOM_STATE = 42

# Label map mirrors game/gestures.py _GESTURE_LABEL_MAP
LABEL_NAMES = {0: "Sword", 1: "Fist", 2: "Stop", 3: "SpeedUp", 4: "Skill"}


def main() -> None:
    df = pd.read_csv(DATA_PATH, header=None)
    x = df.iloc[:, 1:].to_numpy()
    y = df.iloc[:, 0].to_numpy().astype(int)

    present = sorted(set(y))
    names = [LABEL_NAMES.get(c, str(c)) for c in present]

    print("=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    print(f"Samples: {len(y)}    Feature dim: {x.shape[1]}")
    counts = {c: int((y == c).sum()) for c in present}
    for c in present:
        print(f"  label {c} ({LABEL_NAMES.get(c, '?')}): {counts[c]}")
    imbalance = max(counts.values()) / max(1, min(counts.values()))
    print(f"Classes present: {len(present)}    Imbalance ratio (max/min): {imbalance:.1f}x")

    # --- Hold-out 80/20 (stratified) ---
    x_tr, x_te, y_tr, y_te = train_test_split(
        x, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )
    clf = RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE)
    clf.fit(x_tr, y_tr)
    y_pred = clf.predict(x_te)
    acc = accuracy_score(y_te, y_pred)

    print("\n" + "=" * 60)
    print("HOLD-OUT 80/20 (stratified)")
    print("=" * 60)
    print(f"Test accuracy: {acc * 100:.2f}%  (n_test={len(y_te)})\n")
    print(classification_report(y_te, y_pred, target_names=names, digits=4, zero_division=0))

    # --- Stratified k-fold CV ---
    k = min(5, min(counts.values()))
    print("=" * 60)
    print(f"STRATIFIED {k}-FOLD CROSS-VALIDATION")
    print("=" * 60)
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=RANDOM_STATE)
    cv = cross_val_score(
        RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE),
        x, y, cv=skf, scoring="accuracy",
    )
    print(f"Fold accuracies: {[f'{v*100:.2f}%' for v in cv]}")
    print(f"Mean: {cv.mean()*100:.2f}%  Std: {cv.std()*100:.2f}%")

    # --- Confusion matrices ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cm = confusion_matrix(y_te, y_pred, labels=present)

    fig, ax = plt.subplots(figsize=(7, 6))
    ConfusionMatrixDisplay(cm, display_labels=names).plot(cmap="Blues", ax=ax, colorbar=True)
    ax.set_title(f"Confusion Matrix (counts) — acc {acc*100:.1f}%")
    plt.tight_layout()
    counts_path = OUT_DIR / "eval_confusion_counts.png"
    plt.savefig(counts_path, dpi=150)
    plt.close(fig)

    cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True).clip(min=1)
    fig, ax = plt.subplots(figsize=(7, 6))
    ConfusionMatrixDisplay(cm_norm, display_labels=names).plot(
        cmap="Blues", ax=ax, colorbar=True, values_format=".2f"
    )
    ax.set_title("Confusion Matrix (row-normalised recall)")
    plt.tight_layout()
    norm_path = OUT_DIR / "eval_confusion_normalized.png"
    plt.savefig(norm_path, dpi=150)
    plt.close(fig)

    print("\nSaved:")
    print(f"  {counts_path}")
    print(f"  {norm_path}")


if __name__ == "__main__":
    main()
