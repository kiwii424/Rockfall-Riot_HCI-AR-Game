"""Real-time performance benchmark for the AR pipeline.

Measures, per frame, the latency of each stage on the live webcam feed:
  - camera capture  (CameraFeed.read_rgb)
  - hand tracking + gesture inference  (HandTracker.process: MediaPipe + RandomForest)
  - end-to-end (capture + process)

Reports mean / median / p95 latency (ms) and achievable FPS. These are the
numbers an AR Results section should report (cf. ms-level latency papers).

Run:  python scripts/benchmark_fps.py [n_frames]
Show your hand to the camera so the tracker actually runs inference.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.camera import CameraFeed
from game.config import SCREEN_HEIGHT, SCREEN_WIDTH
from game.gestures import HandTracker

WARMUP = 15  # discard first frames (model/camera warmup)


def _stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(samples)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return {
        "mean": statistics.mean(samples),
        "median": statistics.median(samples),
        "p95": p95,
        "min": s[0],
        "max": s[-1],
    }


def _line(label: str, st: dict[str, float]) -> str:
    return (f"  {label:<26} mean {st['mean']*1000:6.2f} ms | median {st['median']*1000:6.2f} ms"
            f" | p95 {st['p95']*1000:6.2f} ms")


def main() -> None:
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300

    tracker = HandTracker()
    print(f"[bench] tracker backend = {tracker._backend}  available = {tracker.available}")
    print(f"[bench] ML classifier loaded = {tracker.clf is not None}")
    camera = CameraFeed(SCREEN_WIDTH, SCREEN_HEIGHT)
    if not camera.available:
        print(f"[bench] camera unavailable: {camera.error}")
        return

    cap_t: list[float] = []
    proc_t: list[float] = []
    e2e_t: list[float] = []
    hand_frames = 0
    collected = 0

    print(f"[bench] warming up {WARMUP} frames, then measuring {n_frames}...")
    total = WARMUP + n_frames
    i = 0
    while collected < n_frames and i < total * 4:  # cap attempts in case of dropped frames
        i += 1
        t0 = time.perf_counter()
        frame = camera.read_rgb()
        t1 = time.perf_counter()
        if frame is None:
            continue
        gesture = tracker.process(frame, (SCREEN_WIDTH, SCREEN_HEIGHT))
        t2 = time.perf_counter()

        if i <= WARMUP:
            continue

        cap_t.append(t1 - t0)
        proc_t.append(t2 - t1)
        e2e_t.append(t2 - t0)
        if gesture.tracking_points:
            hand_frames += 1
        collected += 1

    camera.close()
    tracker.close()

    cap = _stats(cap_t)
    proc = _stats(proc_t)
    e2e = _stats(e2e_t)
    mean_fps = 1.0 / e2e["mean"] if e2e["mean"] > 0 else 0.0
    p95_fps = 1.0 / e2e["p95"] if e2e["p95"] > 0 else 0.0

    print("\n" + "=" * 64)
    print(f"RESULTS  ({collected} frames, hand present in {hand_frames})")
    print("=" * 64)
    print(_line("camera capture", cap))
    print(_line("hand track + inference", proc))
    print(_line("end-to-end (cap+proc)", e2e))
    print("-" * 64)
    print(f"  Achievable FPS (1/mean e2e): {mean_fps:5.1f}")
    print(f"  Worst-case FPS (1/p95 e2e):  {p95_fps:5.1f}")
    print("  Note: game render/update + 60 FPS cap not included; this is the")
    print("        perception-pipeline ceiling, the AR-relevant latency metric.")


if __name__ == "__main__":
    main()
