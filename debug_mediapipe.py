"""Run this from the project root: python debug_mediapipe.py"""
import sys, pathlib

print(f"Python {sys.version}")

# 1. import mediapipe
try:
    import mediapipe as mp
    print(f"mediapipe {mp.__version__} OK")
except Exception as e:
    print(f"FAIL import mediapipe: {e}")
    sys.exit(1)

# 2. solutions.hands
print("\n--- mp.solutions.hands ---")
try:
    h = mp.solutions.hands
    print(f"  attribute exists: {h}")
    hands = h.Hands(static_image_mode=True, max_num_hands=1)
    hands.close()
    print("  Hands() init: OK")
except Exception as e:
    print(f"  FAIL: {e}")

# 3. mp.tasks.vision
print("\n--- mp.tasks.vision.HandLandmarker ---")
try:
    model_path = pathlib.Path(__file__).parent / "assets" / "models" / "hand_landmarker.task"
    print(f"  model path: {model_path}")
    print(f"  model exists: {model_path.exists()}")
    print(f"  model size: {model_path.stat().st_size if model_path.exists() else 'N/A'} bytes")

    # MediaPipe C++ cannot handle non-ASCII paths on Windows.
    # Pass the model as raw bytes instead of a file path.
    model_bytes = model_path.read_bytes()
    print(f"  model loaded into memory: {len(model_bytes)} bytes")

    # try delegate
    try:
        base_options = mp.tasks.BaseOptions(
            model_asset_buffer=model_bytes,
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        )
        print("  BaseOptions with model_asset_buffer + Delegate.CPU: OK")
    except AttributeError as e:
        print(f"  Delegate.CPU not found ({e}), falling back")
        base_options = mp.tasks.BaseOptions(model_asset_buffer=model_bytes)

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    print("  HandLandmarkerOptions: OK")

    landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
    landmarker.close()
    print("  HandLandmarker.create_from_options: OK  <-- tasks backend should work")

except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()
