# AR Fruit Ninja ML Project

A Python desktop AR game for a machine learning project. The game uses `assets/background/BG.png` as the playfield background, while the webcam runs only for MediaPipe hand tracking. One raised index finger acts as a light-saber blade to shatter falling rocks, and a fist catches the small Pikmin-style creatures that run out.

## Setup

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

On macOS, allow camera access for your terminal app or IDE in **System Settings > Privacy & Security > Camera**. The game will not start unless the camera and hand tracker detect your hand during the hand-check stage.

If settings look correct but OpenCV still reports camera denied, reset macOS Camera permission and approve the prompt again:

```bash
tccutil reset Camera
python3 scripts/check_camera.py
python3 main.py
```

Depending on how Python was installed, macOS may show the permission entry as **Python**, **Terminal**, VS Code, or Cursor. Enable the app that appears after running the camera check.

The app prefers the Mac's built-in camera and skips iPhone Continuity Camera / virtual cameras by default. To see which camera index macOS reports, run:

```bash
python3 scripts/check_camera.py
```

If your built-in camera is index `1`, start the game with:

```bash
ARFN_CAMERA_INDEX=1 python3 main.py
```

You can test a specific index first:

```bash
python3 scripts/check_camera.py 1
```

If the window closes unexpectedly, check `data/crash.log`. The MediaPipe/TFLite `GL version`, `XNNPACK delegate`, and `landmark_projection_calculator` lines are warnings, not fatal errors.

The app hides noisy native macOS/MediaPipe warnings by default. To debug those logs, run:

```bash
ARFN_SHOW_NATIVE_LOGS=1 python3 main.py
```

## MediaPipe on Python 3.13

Recent `mediapipe` builds may expose the newer `mp.tasks` API instead of the older `mp.solutions.hands` API. For real hand tracking with that package shape, download Google's Hand Landmarker model and place it here:

```text
assets/models/hand_landmarker.task
```

You can also set `HAND_LANDMARKER_MODEL=/path/to/hand_landmarker.task` before running the game.

```bash
mkdir -p assets/models
curl -L -o assets/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

If MediaPipe cannot initialize on the current Python/macOS combination, the game uses an OpenCV camera-based color hand tracker. It still requires an actual hand in the webcam frame; there is no mouse gameplay fallback.

## Controls

- Index finger: shatter rocks with the light-saber trail.
- Fist: catch escaping Pikmin-style creatures.
- Open palm: trigger Fever mode when the gauge is full.
- Start flow: type your name, run the hand-check stage, complete the cut/catch tutorial, then start the game.
- Mouse: the game shows a custom cursor, hover glow, and click ripple on clickable buttons.
- Hand UI: point at a button and hold to activate it. On the start screen, the hand cursor must fill the dwell circle above the hovered button for about 1.5 seconds.
- Difficulty: choose one of five drop-speed levels on the start screen. The rock drop speed is slowed to one-tenth of the earlier baseline.
- Buttons: start, start training, pause, resume, restart, choose music, quit.
- Keyboard shortcuts: `Enter` hand check from the name screen, `Space` start/pause/resume, `M` choose music, `R` restart, `Esc` quit.

The lower-right camera preview shows the webcam feed, hand tracking overlay, and `HAND DETECTED` / `NO HAND` status so players can adjust position and lighting.

The lower-right preview also shows a yellow game-frame box. The bottom of that box is the game's screen bottom, leaving extra camera space below it so the full palm can remain visible while the fingertip reaches the bottom of the playfield.

The on-screen detection box marks the reliable tracking area. If your hand stays outside it or disappears during gameplay for too long, the game pauses and asks you to run Hand Check again.

When the Music button is activated by hand, the game cycles through audio files in `assets/music` instead of opening the OS file picker.

During the tutorial, the player must:
- cut a practice rock with the index-finger saber
- catch a practice Pikmin with a fist

## Stages

- Stage 1: image background, webcam hand gesture tracking, hand-check stage, required tutorial, saber trail, rock shattering, UI screens.
- Stage 2: local music selection and automatic beat/onset analysis for rhythm-based rock spawning.
- Stage 3: score, combo, timing judgements, Fever multiplier, misses, Pikmin gallery, final grade, leaderboard.

## Notes

The project uses procedural rock and creature graphics, not external game assets. If `librosa` is unavailable or music analysis fails, the game falls back to a default beat pattern. The leaderboard keeps only each player's best score; a new personal high score triggers a confetti celebration. If any creatures are caught, the game shows the gallery before the score screen.
