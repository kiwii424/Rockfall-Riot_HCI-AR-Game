"""One-shot installer for the pre-trained TCN+DBN beat-tracking backend.

The pip package `beat_tracking_tcn` (ben-hayes) ships incomplete: it omits the
`utils/` module and the pre-trained checkpoints, and its spectrogram helper uses
a librosa<0.10 positional API. madmom (its DBN dependency) also needs old
collections/numpy aliases on Python 3.12. This script makes the backend usable:

  1. pip install torch (CPU), madmom, and the git package if missing
  2. copy vendored checkpoints + utils (assets/tcn/) into the installed package
  3. ensure utils/__init__.py exists

After running this, `analyze_music(path, backend="tcn")` works, and the game's
default ("auto") backend will prefer TCN. Everything still degrades gracefully
to librosa if any of this is absent.

Run:  python scripts/setup_tcn.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR = PROJECT_ROOT / "assets" / "tcn"


def _pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", *args], check=True)


def _ensure_packages() -> None:
    import importlib.util as u

    if u.find_spec("torch") is None:
        print("[setup_tcn] installing torch (CPU)...")
        _pip("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
    if u.find_spec("madmom") is None:
        print("[setup_tcn] installing madmom...")
        _pip("madmom")
    if u.find_spec("beat_tracking_tcn") is None:
        print("[setup_tcn] installing beat_tracking_tcn from GitHub...")
        _pip("git+https://github.com/ben-hayes/beat-tracking-tcn.git")


def _patch_package() -> None:
    import beat_tracking_tcn

    pkg = Path(beat_tracking_tcn.__file__).resolve().parent
    print(f"[setup_tcn] package at {pkg}")

    # checkpoints
    ckpt_dst = pkg / "checkpoints"
    ckpt_dst.mkdir(exist_ok=True)
    for f in (VENDOR / "checkpoints").glob("*.torch"):
        shutil.copy2(f, ckpt_dst / f.name)
        print(f"[setup_tcn]   checkpoint -> {f.name}")

    # utils (vendored spectrograms.py is already patched for librosa>=0.10)
    utils_dst = pkg / "utils"
    utils_dst.mkdir(exist_ok=True)
    (utils_dst / "__init__.py").touch(exist_ok=True)
    for f in (VENDOR / "utils").glob("*.py"):
        shutil.copy2(f, utils_dst / f.name)
        print(f"[setup_tcn]   utils -> {f.name}")


def _smoke_test() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from game.rhythm import analyze_music  # applies numpy/collections shims

    sample = next((PROJECT_ROOT / "assets" / "music").glob("*.mp3"), None)
    if sample is None:
        print("[setup_tcn] no sample mp3 found; skipping smoke test")
        return
    a = analyze_music(str(sample), backend="tcn")
    ok = a.backend.startswith("tcn")
    print(f"[setup_tcn] smoke test on {sample.name}: backend={a.backend} "
          f"tempo={a.tempo:.1f} events={len(a.events)} -> {'OK' if ok else 'FELL BACK'}")


def main() -> None:
    _ensure_packages()
    _patch_package()
    _smoke_test()
    print("[setup_tcn] done.")


if __name__ == "__main__":
    main()
