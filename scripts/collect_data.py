from pathlib import Path
import csv
import os
import sys

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.camera import CameraFeed
from game.gestures import HandTracker


DATA_DIR = PROJECT_ROOT / "data"
CSV_PATH = DATA_DIR / "gesture_data.csv"


def collect() -> None:
    tracker = HandTracker()
    camera = CameraFeed(640, 480)

    os.makedirs(DATA_DIR, exist_ok=True)

    print("Press 0-4 to save the current hand pose. Press Esc to quit.")
    print("0: Sword, 1: Fist, 2: Stop, 3: Speed Up, 4: Skill")

    with open(CSV_PATH, "a", newline="") as file:
        writer = csv.writer(file)
        running = True

        while running:
            rgb = camera.read_rgb()
            if rgb is None:
                continue

            gesture = tracker.process(rgb, (640, 480))

            cv2.imshow(
                "Data Collection (Press Esc to quit)",
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            )
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                running = False

            if gesture.tracking_points:
                label = None
                if key == ord("0"):
                    label = 0
                elif key == ord("1"):
                    label = 1
                elif key == ord("2"):
                    label = 2
                elif key == ord("3"):
                    label = 3
                elif key == ord("4"):
                    label = 4

                if label is not None:
                    wrist = gesture.tracking_points[0]
                    features = []
                    for point in gesture.tracking_points:
                        features.extend([point[0] - wrist[0], point[1] - wrist[1]])

                    max_val = max(abs(value) for value in features) if features else 1.0
                    if max_val == 0:
                        max_val = 1.0
                    features = [value / max_val for value in features]

                    writer.writerow([label] + features)
                    print(f"Saved label {label}        ", end="\r")

    camera.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    collect()
