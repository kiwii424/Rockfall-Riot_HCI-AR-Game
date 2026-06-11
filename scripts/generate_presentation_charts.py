"""Generate ML model visualization charts for presentation."""
from pathlib import Path

import joblib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "gesture_data.csv"
MODEL_PATH = PROJECT_ROOT / "assets" / "models" / "gesture_classifier.pkl"
OUT_DIR = PROJECT_ROOT / "data" / "presentation_charts"
OUT_DIR.mkdir(exist_ok=True)

LABEL_NAMES = {0: "Sword", 1: "Fist", 2: "Stop", 3: "Speed Up", 4: "Skill"}
COLORS = ["#E63946", "#457B9D", "#2DC653", "#F4A261", "#9B5DE5"]

plt.rcParams.update({"font.size": 12, "figure.dpi": 150})


def load_data():
    df = pd.read_csv(DATA_PATH, header=None)
    x = df.iloc[:, 1:].values
    y = df.iloc[:, 0].values.astype(int)
    return x, y


def actual_classes(y):
    return sorted(np.unique(y).tolist())


def load_model():
    return joblib.load(MODEL_PATH)


# ── Chart 1: Dataset class distribution ─────────────────────────────────────
def chart_class_distribution(y):
    classes = actual_classes(y)
    labels = [LABEL_NAMES[i] for i in classes]
    counts = [np.sum(y == i) for i in classes]
    colors = [COLORS[i] for i in classes]
    total = sum(counts)

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, counts, color=colors, edgecolor="white", linewidth=1.5)
    for bar, count in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{count}\n({count/total*100:.1f}%)",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax.set_title("Dataset Class Distribution", fontsize=16, fontweight="bold", pad=15)
    ax.set_xlabel("Gesture Class")
    ax.set_ylabel("Sample Count")
    ax.set_ylim(0, max(counts) * 1.2)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "1_class_distribution.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  Total samples: {total}")
    for i, (label, count) in enumerate(zip(labels, counts)):
        print(f"  {label}: {count} ({count/total*100:.1f}%)")


# ── Chart 2: Confusion matrix ────────────────────────────────────────────────
def chart_confusion_matrix(model, x, y):
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )
    y_pred = model.predict(x_test)
    cm = confusion_matrix(y_test, y_pred)

    fig, ax = plt.subplots(figsize=(8, 7))
    disp = ConfusionMatrixDisplay(
        confusion_matrix=cm,
        display_labels=[LABEL_NAMES[i] for i in sorted(np.unique(y))],
    )
    disp.plot(cmap="Blues", ax=ax, colorbar=False)
    ax.set_title("Confusion Matrix (Test Set)", fontsize=16, fontweight="bold", pad=15)
    ax.set_xlabel("Predicted Label", fontsize=12)
    ax.set_ylabel("True Label", fontsize=12)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "2_confusion_matrix.png", bbox_inches="tight")
    plt.close(fig)

    score = model.score(x_test, y_test)
    print(f"  Test accuracy: {score*100:.2f}%")
    print(classification_report(y_test, y_pred, target_names=[LABEL_NAMES[i] for i in sorted(np.unique(y))]))


# ── Chart 3: Per-class precision / recall / F1 ──────────────────────────────
def chart_per_class_metrics(model, x, y):
    from sklearn.metrics import precision_recall_fscore_support

    classes = actual_classes(y)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )
    y_pred = model.predict(x_test)
    prec, rec, f1, _ = precision_recall_fscore_support(y_test, y_pred, labels=classes)

    labels = [LABEL_NAMES[i] for i in classes]
    x_pos = np.arange(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar(x_pos - width, prec, width, label="Precision", color="#457B9D", alpha=0.9)
    ax.bar(x_pos, rec, width, label="Recall", color="#2DC653", alpha=0.9)
    ax.bar(x_pos + width, f1, width, label="F1-Score", color="#E63946", alpha=0.9)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score")
    ax.set_title("Per-Class Precision / Recall / F1-Score", fontsize=16, fontweight="bold", pad=15)
    ax.legend(loc="lower right")
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for i, (p, r, f) in enumerate(zip(prec, rec, f1)):
        ax.text(i - width, p + 0.02, f"{p:.2f}", ha="center", fontsize=9)
        ax.text(i, r + 0.02, f"{r:.2f}", ha="center", fontsize=9)
        ax.text(i + width, f + 0.02, f"{f:.2f}", ha="center", fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "3_per_class_metrics.png", bbox_inches="tight")
    plt.close(fig)


# ── Chart 4: Cross-validation scores ────────────────────────────────────────
def chart_cross_validation(model, x, y):
    from sklearn.ensemble import RandomForestClassifier

    fresh_model = RandomForestClassifier(n_estimators=100, random_state=42)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(fresh_model, x, y, cv=cv, scoring="accuracy")

    fig, ax = plt.subplots(figsize=(8, 5))
    fold_labels = [f"Fold {i+1}" for i in range(len(scores))]
    fold_colors = (COLORS * 2)[: len(scores)]
    bars = ax.bar(fold_labels, scores * 100, color=fold_colors, alpha=0.85, edgecolor="white")
    ax.axhline(scores.mean() * 100, color="#E63946", linestyle="--", linewidth=2, label=f"Mean: {scores.mean()*100:.2f}%")
    ax.fill_between(
        range(len(scores)),
        (scores.mean() - scores.std()) * 100,
        (scores.mean() + scores.std()) * 100,
        alpha=0.1,
        color="#E63946",
    )

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"{score*100:.2f}%",
            ha="center",
            fontsize=11,
        )

    ax.set_ylim(0, 115)
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("5-Fold Cross-Validation Accuracy", fontsize=16, fontweight="bold", pad=15)
    ax.legend(fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "4_cross_validation.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  CV scores: {scores*100}")
    print(f"  Mean: {scores.mean()*100:.2f}% ± {scores.std()*100:.2f}%")


# ── Chart 5: Feature importance (top 20) ────────────────────────────────────
def chart_feature_importance(model):
    importances = model.feature_importances_
    # 21 landmarks × 2 (x,y) = 42 features
    landmark_names = [
        "Wrist", "Thumb CMC", "Thumb MCP", "Thumb IP", "Thumb Tip",
        "Index MCP", "Index PIP", "Index DIP", "Index Tip",
        "Middle MCP", "Middle PIP", "Middle DIP", "Middle Tip",
        "Ring MCP", "Ring PIP", "Ring DIP", "Ring Tip",
        "Pinky MCP", "Pinky PIP", "Pinky DIP", "Pinky Tip",
    ]
    feature_names = []
    for name in landmark_names:
        feature_names.extend([f"{name} X", f"{name} Y"])

    top_n = 20
    indices = np.argsort(importances)[::-1][:top_n]
    top_names = [feature_names[i] for i in indices]
    top_vals = importances[indices]

    fig, ax = plt.subplots(figsize=(10, 7))
    colors_grad = plt.cm.RdYlGn(np.linspace(0.7, 0.3, top_n))
    ax.barh(range(top_n), top_vals[::-1], color=colors_grad, edgecolor="white")
    ax.set_yticks(range(top_n))
    ax.set_yticklabels(top_names[::-1], fontsize=10)
    ax.set_xlabel("Feature Importance (Mean Decrease Impurity)")
    ax.set_title(f"Top {top_n} Most Important Features\n(Random Forest)", fontsize=16, fontweight="bold", pad=15)
    ax.grid(axis="x", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "5_feature_importance.png", bbox_inches="tight")
    plt.close(fig)


# ── Chart 6: PCA 2D scatter of gesture classes ───────────────────────────────
def chart_pca_scatter(x, y):
    pca = PCA(n_components=2, random_state=42)
    x_pca = pca.fit_transform(x)
    var_ratio = pca.explained_variance_ratio_

    fig, ax = plt.subplots(figsize=(9, 7))
    for class_id in actual_classes(y):
        mask = y == class_id
        ax.scatter(
            x_pca[mask, 0],
            x_pca[mask, 1],
            c=COLORS[class_id],
            label=LABEL_NAMES[class_id],
            alpha=0.5,
            s=25,
            edgecolors="none",
        )

    ax.set_xlabel(f"PC1 ({var_ratio[0]*100:.1f}% variance)", fontsize=12)
    ax.set_ylabel(f"PC2 ({var_ratio[1]*100:.1f}% variance)", fontsize=12)
    ax.set_title("PCA Projection of Gesture Data (2D)", fontsize=16, fontweight="bold", pad=15)
    ax.legend(fontsize=11, loc="best")
    ax.grid(alpha=0.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "6_pca_scatter.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  PCA variance explained: PC1={var_ratio[0]*100:.1f}%, PC2={var_ratio[1]*100:.1f}%")


# ── Chart 7: Learning curve (n_estimators effect) ───────────────────────────
def chart_estimators_accuracy(x, y):
    from sklearn.ensemble import RandomForestClassifier

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )

    n_list = [5, 10, 20, 30, 50, 75, 100, 150, 200]
    train_scores, test_scores = [], []

    for n in n_list:
        clf = RandomForestClassifier(n_estimators=n, random_state=42, n_jobs=-1)
        clf.fit(x_train, y_train)
        train_scores.append(clf.score(x_train, y_train) * 100)
        test_scores.append(clf.score(x_test, y_test) * 100)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(n_list, train_scores, "o-", color="#457B9D", linewidth=2, label="Train Accuracy")
    ax.plot(n_list, test_scores, "s-", color="#E63946", linewidth=2, label="Test Accuracy")
    ax.axvline(100, color="#F4A261", linestyle="--", linewidth=1.5, label="Current (n=100)")
    ax.set_xlabel("Number of Trees (n_estimators)")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Effect of n_estimators on Accuracy", fontsize=16, fontweight="bold", pad=15)
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    ax.set_ylim(80, 102)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "7_estimators_curve.png", bbox_inches="tight")
    plt.close(fig)


def main():
    print("Loading data...")
    x, y = load_data()
    print(f"  {len(x)} samples, {x.shape[1]} features, {len(np.unique(y))} classes\n")

    print("Loading model...")
    model = load_model()

    print("\n[1/7] Class distribution chart...")
    chart_class_distribution(y)

    print("\n[2/7] Confusion matrix...")
    chart_confusion_matrix(model, x, y)

    print("\n[3/7] Per-class metrics...")
    chart_per_class_metrics(model, x, y)

    print("\n[4/7] Cross-validation...")
    chart_cross_validation(model, x, y)

    print("\n[5/7] Feature importance...")
    chart_feature_importance(model)

    print("\n[6/7] PCA scatter...")
    chart_pca_scatter(x, y)

    print("\n[7/7] n_estimators curve...")
    chart_estimators_accuracy(x, y)

    print(f"\nAll charts saved to {OUT_DIR}")
    print("Files:")
    for f in sorted(OUT_DIR.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
