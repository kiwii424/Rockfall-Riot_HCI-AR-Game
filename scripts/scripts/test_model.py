from collections import Counter, deque
from pathlib import Path
import sys

import cv2
import joblib
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.camera import CameraFeed
from game.gestures import HandTracker


MODEL_PATH = PROJECT_ROOT / "assets" / "models" / "gesture_classifier.pkl"
SMOOTH_WINDOW = 10

LABEL_NAMES = {
    0: "Sword (0)",
    1: "Fist (1)",
    2: "Stop (2)",
    3: "Speed Up (3)",
    4: "Skill (4)",
}

LABEL_COLORS = {
    0: (0, 200, 255),
    1: (0, 255, 120),
    2: (200, 200, 200),
    3: (255, 100, 0),
    4: (200, 0, 255),
}


def test_realtime() -> None:
    print("Loading gesture model...")
    try:
        model = joblib.load(MODEL_PATH)
    except FileNotFoundError:
        print(f"Model not found: {MODEL_PATH}")
        return

    tracker = HandTracker()
    camera = CameraFeed(640, 480)
    prediction_buffer = deque(maxlen=SMOOTH_WINDOW)

    print(f"Starting real-time test with smoothing window {SMOOTH_WINDOW}. Press Esc to quit.")

    running = True
    while running:
        rgb = camera.read_rgb()
        if rgb is None:
            continue

        gesture = tracker.process(rgb, (640, 480))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        if gesture.tracking_points:
            wrist = gesture.tracking_points[0]
            features = []
            for point in gesture.tracking_points:
                features.extend([point[0] - wrist[0], point[1] - wrist[1]])

            max_val = max(abs(value) for value in features) if features else 1.0
            if max_val == 0:
                max_val = 1.0
            features = [value / max_val for value in features]
            features_array = np.array(features).reshape(1, -1)

            raw_pred = model.predict(features_array)[0]
            prediction_buffer.append(raw_pred)

            vote_counts = Counter(prediction_buffer)
            smooth_pred = vote_counts.most_common(1)[0][0]
            confidence = vote_counts[smooth_pred] / len(prediction_buffer)

            label_name = LABEL_NAMES.get(smooth_pred, "Unknown")
            color = LABEL_COLORS.get(smooth_pred, (255, 255, 255))

            cv2.putText(
                bgr,
                f"Gesture: {label_name}",
                (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                color,
                3,
                cv2.LINE_AA,
            )

            bar_x, bar_y, bar_w, bar_h = 10, 65, 300, 18
            cv2.rectangle(bgr, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (60, 60, 60), -1)
            cv2.rectangle(
                bgr,
                (bar_x, bar_y),
                (bar_x + int(bar_w * confidence), bar_y + bar_h),
                color,
                -1,
            )
            cv2.putText(
                bgr,
                f"Smoothed confidence: {confidence * 100:.0f}%",
                (bar_x, bar_y + bar_h + 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
                cv2.LINE_AA,
            )

            raw_name = LABEL_NAMES.get(raw_pred, "Unknown")
            cv2.putText(
                bgr,
                f"Raw: {raw_name}",
                (bgr.shape[1] - 200, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (180, 180, 180),
                1,
                cv2.LINE_AA,
            )
        else:
            prediction_buffer.clear()
            cv2.putText(
                bgr,
                "No Hand Detected",
                (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )

        cv2.imshow("Real-time Model Test (Press Esc to quit)", bgr)
        if (cv2.waitKey(1) & 0xFF) == 27:
            running = False

    camera.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    test_realtime()
