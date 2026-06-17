from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = PROJECT_ROOT / "data" / "gesture_data.csv"
CHART_PATH = PROJECT_ROOT / "data" / "confusion_matrix.png"
MODEL_PATH = PROJECT_ROOT / "assets" / "models" / "gesture_classifier.pkl"


def train() -> None:
    df = pd.read_csv(DATA_PATH, header=None)
    x = df.iloc[:, 1:]
    y = df.iloc[:, 0]

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=42,
    )

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(x_train, y_train)

    y_pred = model.predict(x_test)
    score = model.score(x_test, y_test)
    print("=== Model Evaluation ===")
    print(f"Accuracy: {score * 100:.2f}%\n")
    print("Classification Report:")
    print(classification_report(y_test, y_pred))

    cm = confusion_matrix(y_test, y_pred)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=model.classes_)
    fig, ax = plt.subplots(figsize=(8, 6))
    disp.plot(cmap=plt.cm.Blues, ax=ax)
    plt.title("Gesture Classification Confusion Matrix")
    plt.savefig(CHART_PATH)
    plt.close(fig)
    print(f"Saved confusion matrix to {CHART_PATH}")

    joblib.dump(model, MODEL_PATH)
    print(f"Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    train()
