from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

import pygame

from .analytics import AnalyticsTracker, draw_radar_chart
from .audio import SfxPlayer
from .camera import CameraFeed, frame_to_surface
from .config import (
    ACCENT_COLOR,
    BACKGROUND_COLOR,
    CALIBRATION_MIN_MOVEMENT,
    CALIBRATION_MIN_SEEN,
    DEFAULT_DIFFICULTY_INDEX,
    DIFFICULTIES,
    FEVER_COLOR,
    FEVER_COOLDOWN,
    FEVER_DURATION,
    FPS,
    FRUIT_FALL_SPEED_SCALE,
    FRUIT_TYPES,
    GET_READY_SECONDS,
    GOOD_COLOR,
    HAND_LOST_PAUSE_SECONDS,
    HIT_LINE_Y_RATIO,
    MAX_MISSES,
    MISS_COLOR,
    PIKMIN_BASE_SPEED_MAX,
    PIKMIN_BASE_SPEED_MIN,
    PIKMIN_FAST_RUNNER_CHANCE,
    PIKMIN_FAST_SPEED_SCALE_MAX,
    PIKMIN_FAST_SPEED_SCALE_MIN,
    PIKMIN_NORMAL_SPEED_SCALE_MAX,
    PIKMIN_NORMAL_SPEED_SCALE_MIN,
    PIKMIN_SPAWN_MAX,
    PIKMIN_SPAWN_MIN,
    PIKMIN_VARIANTS,
    PERFECT_COLOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPAWN_LEAD_TIME,
    START_MENU_DWELL_SECONDS,
    TEXT_COLOR,
    TITLE,
    TUTORIAL_AUTO_START_SECONDS,
    TUTORIAL_PIKMIN_INITIAL_VX,
    TUTORIAL_PIKMIN_INITIAL_VY,
    TUTORIAL_PIKMIN_SPEED_SCALE,
    TUTORIAL_PIKMIN_TTL,
    CAMERA_GAME_BOTTOM,
    CAMERA_GAME_LEFT,
    CAMERA_GAME_RIGHT,
    CAMERA_GAME_TOP,
    TRACKING_SAFE_MARGIN_X,
    TRACKING_SAFE_MARGIN_Y,
)
from .entities import Fruit, PikminRunner, SliceSpark
from .gestures import HAND_CONNECTIONS, GestureState, HandTracker
from .leaderboard import Leaderboard, LeaderboardEntry
from .rhythm import MusicAnalysis, RhythmSpawner, analyze_music, default_analysis
from .scoring import ScoreKeeper
from .ui import Button, draw_dim_overlay, draw_gauge, draw_hud, draw_screen_panel, draw_text


@dataclass
class FloatingText:
    text: str
    x: float
    y: float
    color: tuple[int, int, int]
    ttl: float = 0.8

    def update(self, dt: float) -> None:
        self.ttl -= dt
        self.y -= 58.0 * dt


@dataclass
class CalibrationState:
    seen_time: float = 0.0
    movement: float = 0.0
    peak_speed: float = 0.0
    last_position: tuple[int, int] | None = None

    @property
    def ready(self) -> bool:
        return self.seen_time >= CALIBRATION_MIN_SEEN and self.movement >= CALIBRATION_MIN_MOVEMENT


@dataclass
class TutorialState:
    stage: str = "CUT"
    cut_done: bool = False
    catch_done: bool = False
    auto_start_timer: float = 0.0

    @property
    def ready(self) -> bool:
        return self.cut_done and self.catch_done


@dataclass
class ClickRipple:
    x: float
    y: float
    ttl: float = 0.38

    def update(self, dt: float) -> None:
        self.ttl -= dt

    @property
    def alive(self) -> bool:
        return self.ttl > 0


@dataclass
class ConfettiPiece:
    x: float
    y: float
    vx: float
    vy: float
    color: tuple[int, int, int]
    size: int
    ttl: float
    rotation: float
    spin: float

    def update(self, dt: float) -> None:
        self.ttl -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 420.0 * dt
        self.rotation += self.spin * dt


UI_DWELL_SECONDS = 0.9
QUIT_DWELL_SECONDS = 2.1
UI_ACTIVATION_COOLDOWN = 0.65
PREVIEW_SIZE = (320, 180)


class FruitNinjaARApp:
    def __init__(self) -> None:
        pygame.init()
        self.audio_ready = True
        try:
            pygame.mixer.init()
        except pygame.error:
            self.audio_ready = False

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(TITLE)
        pygame.mouse.set_visible(False)
        self.background = self._load_background()
        self.sfx = SfxPlayer(self.audio_ready)
        self.clock = pygame.time.Clock()
        self.fonts = {
            "title": pygame.font.SysFont("arial", 52, bold=True),
            "large": pygame.font.SysFont("arial", 40, bold=True),
            "medium": pygame.font.SysFont("arial", 28, bold=True),
            "button": pygame.font.SysFont("arial", 26, bold=True),
            "small": pygame.font.SysFont("arial", 18, bold=True),
        }

        self.camera = CameraFeed(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.tracker = HandTracker()
        self.analytics = AnalyticsTracker()
        self.analysis: MusicAnalysis = default_analysis()
        self.spawner = RhythmSpawner(self.analysis.events)
        self.score = ScoreKeeper()
        self.leaderboard = Leaderboard()
        self.leaderboard_entries: list[LeaderboardEntry] = self.leaderboard.load()

        self.mode = "START"
        self.running = True
        self.buttons: list[Button] = []
        self.player_name = ""
        self.latest_gesture = GestureState()
        self.latest_frame_available = False
        self.ui_hover_action: str | None = None
        self.ui_hover_time = 0.0
        self.ui_activation_cooldown = 0.0
        self.music_cycle_index = 0
        self.difficulty_index = DEFAULT_DIFFICULTY_INDEX
        self.hand_missing_time = 0.0
        self.hand_loss_pause = False
        self.pause_message = ""
        self.resume_after_calibration = False
        self.calibration = CalibrationState()
        self.tutorial = TutorialState()
        self.results_saved = False
        self.new_high = False
        self.game_time = 0.0
        self.duration = self.analysis.duration
        self.music_started = not bool(self.analysis.path)
        self.next_fruit_id = 0
        self.next_runner_id = 0
        self.fruits = []
        self.runners: list[PikminRunner] = []
        self.caught_pikmin: dict[str, int] = {str(item["name"]): 0 for item in PIKMIN_VARIANTS}
        self.sparks: list[SliceSpark] = []
        self.feedback: list[FloatingText] = []
        self.click_ripples: list[ClickRipple] = []
        self.confetti: list[ConfettiPiece] = []
        self.saber_points: list[tuple[tuple[float, float], float]] = []
        self.was_open_palm = False
        self.was_fist = False
        self.fever_timer = 0.0
        self.fever_cooldown = 0.0
        self.status_message = ""
        self.status_timer = 0.0
        self.rng = random.Random()
        if not self.tracker.available and self.tracker.error:
            self._set_status(f"Hand tracking offline: {self.tracker.error}", 6.0)
        elif self.tracker.error:
            self._set_status(self.tracker.error, 6.0)
        self._build_buttons()

    def _load_background(self):
        background_dir = Path("assets/background")
        candidates = []
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            candidates.extend(background_dir.glob(pattern))

        if not candidates:
            surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            surface.fill(BACKGROUND_COLOR)
            return surface

        try:
            image = pygame.image.load(str(sorted(candidates)[0])).convert()
        except pygame.error:
            surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            surface.fill(BACKGROUND_COLOR)
            return surface

        source_width, source_height = image.get_size()
        scale = max(SCREEN_WIDTH / source_width, SCREEN_HEIGHT / source_height)
        scaled_size = (int(source_width * scale), int(source_height * scale))
        scaled = pygame.transform.smoothscale(image, scaled_size)
        left = max(0, (scaled_size[0] - SCREEN_WIDTH) // 2)
        top = max(0, (scaled_size[1] - SCREEN_HEIGHT) // 2)
        return scaled.subsurface(pygame.Rect(left, top, SCREEN_WIDTH, SCREEN_HEIGHT)).copy()

    def run(self) -> int:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            frame = self.camera.read_rgb()
            self.latest_frame_available = frame is not None
            gesture = self._read_gesture(frame)
            self.latest_gesture = gesture
            self._handle_events()
            self._update(dt, gesture)
            self._draw(frame, gesture)

        self.camera.close()
        self.tracker.close()
        pygame.quit()
        return 0

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_key(self, event) -> None:
        key = event.key
        if key == pygame.K_ESCAPE:
            self.running = False
        elif self.mode == "START":
            self._handle_name_key(event)
        elif key == pygame.K_SPACE:
            if self.mode == "CALIBRATION":
                self.continue_from_calibration()
            elif self.mode == "RESULTS":
                self.begin_calibration()
            elif self.mode == "PLAYING":
                self.pause_game()
            elif self.mode == "PAUSED":
                self.resume_game()
        elif key == pygame.K_m:
            self.select_music()
        elif key == pygame.K_r:
            self.begin_calibration()
        elif key == pygame.K_f and self.mode == "PLAYING":
            self._trigger_fever(force=True)

    def _handle_name_key(self, event) -> None:
        if event.key == pygame.K_RETURN:
            self.begin_calibration()
        elif event.key == pygame.K_BACKSPACE:
            self.player_name = self.player_name[:-1]
        elif event.unicode and event.unicode.isprintable() and len(self.player_name) < 16:
            self.player_name += event.unicode

    def _handle_click(self, pos: tuple[int, int]) -> None:
        self.click_ripples.append(ClickRipple(float(pos[0]), float(pos[1])))
        for button in self.buttons:
            if button.rect.collidepoint(pos) and self._button_enabled(button):
                self._run_action(button.action)
                break

    def _run_action(self, action: str, source: str = "mouse") -> None:
        if action == "start":
            self.begin_calibration()
        elif action == "calibration_start":
            self.continue_from_calibration()
        elif action == "back":
            if self.resume_after_calibration:
                self.resume_after_calibration = False
                self._set_mode("PAUSED")
            else:
                self._reset_tutorial()
                self._set_mode("START")
        elif action == "pause":
            self.pause_game()
        elif action == "resume":
            self.resume_game()
        elif action == "restart":
            self.begin_calibration()
        elif action == "music":
            self.select_music(use_dialog=source != "hand")
        elif action == "quit":
            self.running = False
        elif action == "results":
            self.show_results()
        elif action.startswith("difficulty:"):
            try:
                index = int(action.split(":", 1)[1])
            except ValueError:
                return
            if 0 <= index < len(DIFFICULTIES):
                self.difficulty_index = index
                self._set_status(f"Difficulty: {self.current_difficulty['label']}", 2.0)

    def _build_buttons(self) -> None:
        center_x = SCREEN_WIDTH // 2
        if self.mode == "START":
            difficulty_buttons = [
                Button(pygame.Rect(center_x - 304 + index * 122, 392, 112, 44), item["label"], f"difficulty:{index}")
                for index, item in enumerate(DIFFICULTIES)
            ]
            self.buttons = [
                *difficulty_buttons,
                Button(pygame.Rect(center_x - 160, 456, 320, 52), "Start", "start"),
                Button(pygame.Rect(center_x - 160, 520, 320, 52), "Music", "music"),
                Button(pygame.Rect(center_x - 160, 584, 320, 52), "Quit", "quit"),
            ]
        elif self.mode == "CALIBRATION":
            start_label = "Resume Game" if self.resume_after_calibration else "Start Training"
            self.buttons = [
                Button(pygame.Rect(center_x - 160, 532, 320, 52), start_label, "calibration_start"),
                Button(pygame.Rect(center_x - 160, 596, 320, 52), "Back", "back"),
            ]
        elif self.mode == "TUTORIAL":
            self.buttons = [
                Button(pygame.Rect(center_x - 160, 596, 320, 52), "Back", "back"),
            ]
        elif self.mode == "PAUSED":
            if self.hand_loss_pause:
                self.buttons = [
                    Button(pygame.Rect(center_x - 160, 342, 320, 52), "Hand Check", "start"),
                    Button(pygame.Rect(center_x - 160, 406, 320, 52), "Restart", "restart"),
                    Button(pygame.Rect(center_x - 160, 470, 320, 52), "Music", "music"),
                    Button(pygame.Rect(center_x - 160, 534, 320, 52), "Quit", "quit"),
                ]
            else:
                self.buttons = [
                    Button(pygame.Rect(center_x - 160, 342, 320, 52), "Resume", "resume"),
                    Button(pygame.Rect(center_x - 160, 406, 320, 52), "Restart", "restart"),
                    Button(pygame.Rect(center_x - 160, 470, 320, 52), "Music", "music"),
                    Button(pygame.Rect(center_x - 160, 534, 320, 52), "Quit", "quit"),
                ]
        elif self.mode == "RESULTS":
            self.buttons = [
                Button(pygame.Rect(center_x - 160, 438, 320, 52), "Restart", "restart"),
                Button(pygame.Rect(center_x - 160, 502, 320, 52), "Music", "music"),
                Button(pygame.Rect(center_x - 160, 566, 320, 52), "Quit", "quit"),
            ]
        elif self.mode == "GALLERY":
            self.buttons = [
                Button(pygame.Rect(center_x - 160, 566, 320, 52), "Show Score", "results"),
            ]
        elif self.mode == "PLAYING":
            self.buttons = [Button(pygame.Rect(SCREEN_WIDTH - 72, 14, 48, 44), "II", "pause")]
        else:
            self.buttons = []

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._build_buttons()

    @property
    def current_difficulty(self) -> dict[str, float | str]:
        return DIFFICULTIES[self.difficulty_index]

    @property
    def current_fruit_speed_multiplier(self) -> float:
        return float(self.current_difficulty["speed"]) * FRUIT_FALL_SPEED_SCALE

    def begin_calibration(self) -> None:
        if not self.player_name.strip():
            self.player_name = "Player"
        resuming_paused_game = self.mode == "PAUSED" and self.hand_loss_pause
        self.resume_after_calibration = resuming_paused_game
        if self.audio_ready and self.mode in {"PLAYING", "PAUSED"} and not resuming_paused_game:
            pygame.mixer.music.stop()
        self.calibration = CalibrationState()
        if not resuming_paused_game:
            self.fruits.clear()
            self.runners.clear()
            self.sparks.clear()
            self.fever_timer = 0.0
            self.fever_cooldown = 0.0
            self._reset_tutorial()
        self.saber_points.clear()
        self.feedback.clear()
        self.hand_missing_time = 0.0
        if not resuming_paused_game:
            self.hand_loss_pause = False
            self.pause_message = ""
        self._set_mode("CALIBRATION")
        if not self._hand_input_available():
            self._block_start(self._hand_issue_message(self.latest_gesture))

    def continue_from_calibration(self) -> None:
        if not self._can_start_play(self.latest_gesture):
            self._block_start(self._hand_issue_message(self.latest_gesture))
            return

        if self.resume_after_calibration:
            self.resume_after_calibration = False
            self.hand_loss_pause = False
            self.pause_message = ""
            self.hand_missing_time = 0.0
            if self.audio_ready and self.music_started:
                pygame.mixer.music.unpause()
            self._set_mode("PLAYING")
            return

        self._start_tutorial()

    def _start_tutorial(self) -> None:
        self._reset_tutorial()
        self.fruits.clear()
        self.runners.clear()
        self.sparks.clear()
        self.feedback.clear()
        self.saber_points.clear()
        self.hand_missing_time = 0.0
        self._set_mode("TUTORIAL")

    def _launch_new_game(self) -> None:
        self.score.reset()
        self.analytics.reset()
        speed = self.current_fruit_speed_multiplier
        lead_time = min(SPAWN_LEAD_TIME / max(0.05, speed), GET_READY_SECONDS)
        self.spawner = RhythmSpawner(
            self.analysis.events,
            lead_time=lead_time,
            speed_multiplier=speed,
        )
        self.game_time = -GET_READY_SECONDS
        self.duration = max(self.analysis.duration, self.analysis.events[-1].timestamp + 3.0 if self.analysis.events else 30.0)
        self.music_started = not bool(self.analysis.path)
        self.next_fruit_id = 0
        self.next_runner_id = 0
        self.fruits.clear()
        self.runners.clear()
        self.sparks.clear()
        self.feedback.clear()
        self.saber_points.clear()
        self.was_open_palm = False
        self.was_fist = False
        self.caught_pikmin = {str(item["name"]): 0 for item in PIKMIN_VARIANTS}
        self.fever_timer = 0.0
        self.fever_cooldown = 0.0
        self.results_saved = False
        self.new_high = False
        self.confetti.clear()
        self.hand_missing_time = 0.0
        self.hand_loss_pause = False
        self.pause_message = ""
        self._reset_tutorial()

        if self.audio_ready:
            pygame.mixer.music.stop()

        self.sfx.play_start()
        self._set_mode("PLAYING")

    def pause_game(self, reason: str = "", require_hand_check: bool = False) -> None:
        if self.mode != "PLAYING":
            return
        if self.audio_ready and self.music_started:
            pygame.mixer.music.pause()
        self.hand_loss_pause = require_hand_check
        self.pause_message = reason
        self._set_mode("PAUSED")

    def resume_game(self) -> None:
        if self.mode != "PAUSED":
            return
        if self.hand_loss_pause:
            self._block_start("Run Hand Check again before resuming.")
            return
        if self.audio_ready and self.music_started:
            pygame.mixer.music.unpause()
        self.pause_message = ""
        self._set_mode("PLAYING")

    def finish_game(self) -> None:
        if self.audio_ready:
            pygame.mixer.music.stop()
        self.sfx.play_end()
        if self.total_caught_pikmin() > 0:
            self._set_mode("GALLERY")
        else:
            self.show_results()

    def show_results(self) -> None:
        if not self.results_saved:
            self.leaderboard_entries, self.new_high = self.leaderboard.add_score(self.player_name, self.score)
            self.results_saved = True
            if self.new_high:
                self._spawn_confetti()
                self._add_feedback("New High!", SCREEN_WIDTH / 2, 128, FEVER_COLOR)
        self._set_mode("RESULTS")

    def _reset_tutorial(self) -> None:
        self.tutorial = TutorialState()
        self._clear_tutorial_targets()

    def _clear_tutorial_targets(self) -> None:
        self.fruits.clear()
        self.runners.clear()

    def total_caught_pikmin(self) -> int:
        return sum(self.caught_pikmin.values())

    def select_music(self, use_dialog: bool = True) -> None:
        was_playing = self.mode == "PLAYING"
        if was_playing:
            self.pause_game()

        path = self._open_music_dialog() if use_dialog else self._next_local_music()
        if not path:
            if was_playing:
                self.resume_game()
            if not use_dialog:
                self._set_status("Put music files in assets/music for hand-controlled music select.", 4.0)
            return

        self._draw_loading("Analyzing music")
        try:
            self.analysis = analyze_music(path)
            self._set_status(f"Loaded {self.analysis.title}", 3.0)
        except RuntimeError as exc:
            self.analysis = default_analysis()
            self._set_status(f"Using default beat: {exc}", 4.0)

        self.duration = self.analysis.duration
        if was_playing or self.mode == "PAUSED":
            if self.audio_ready:
                pygame.mixer.music.stop()
            self._set_mode("START")
        if self.mode in {"START", "PAUSED", "RESULTS"}:
            self._build_buttons()

    def _next_local_music(self) -> str | None:
        music_dir = Path("assets/music")
        files = []
        for pattern in ("*.mp3", "*.wav", "*.ogg", "*.flac", "*.m4a"):
            files.extend(music_dir.glob(pattern))
        files = sorted(files)
        if not files:
            return None
        path = files[self.music_cycle_index % len(files)]
        self.music_cycle_index += 1
        return str(path)

    def _open_music_dialog(self) -> str | None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ModuleNotFoundError:
            self._set_status("tkinter is unavailable", 3.0)
            return None

        root = tk.Tk()
        root.withdraw()
        root.update()
        path = filedialog.askopenfilename(
            title="Choose music",
            filetypes=(
                ("Audio files", "*.mp3 *.wav *.ogg *.flac *.m4a"),
                ("All files", "*.*"),
            ),
        )
        root.destroy()
        return path or None

    def _read_gesture(self, frame) -> GestureState:
        if frame is None or not self.tracker.available:
            return GestureState(source="unavailable")
        return self.tracker.process(frame, (SCREEN_WIDTH, SCREEN_HEIGHT))

    def _update(self, dt: float, gesture: GestureState) -> None:
        self.status_timer = max(0.0, self.status_timer - dt)
        self.ui_activation_cooldown = max(0.0, self.ui_activation_cooldown - dt)
        self._update_feedback(dt)
        self._update_click_ripples(dt)
        self._update_confetti(dt)

        if self._update_ui_gesture(dt, gesture):
            return

        if self.mode == "CALIBRATION":
            self._update_calibration(dt, gesture)
            self._update_sparks(dt)
            return

        if self.mode == "TUTORIAL":
            self._update_tutorial(dt, gesture)
            self._update_sparks(dt)
            return

        if self.mode != "PLAYING":
            self._update_saber(dt, gesture, allow_new_points=False)
            return

        if self._pause_if_hand_lost(dt, gesture):
            return

        self.game_time += dt
        self._update_music_playback()
        self._update_timers(dt)
        self._update_saber(dt, gesture, allow_new_points=True)
        self._handle_fever_gesture(gesture)
        self._spawn_due_fruits()
        self._update_fruits(dt)
        self._update_runners(dt)
        self._catch_runners(gesture)
        self._check_slices()
        self._update_sparks(dt)

        if self.score.misses >= MAX_MISSES:
            self.finish_game()
        elif self.game_time >= self.duration and self.spawner.done and not self.fruits and not self.runners:
            self.finish_game()

    def _pause_if_hand_lost(self, dt: float, gesture: GestureState) -> bool:
        if self._gesture_ready_in_safe_area(gesture):
            self.hand_missing_time = 0.0
            return False

        self.hand_missing_time += dt
        if self.hand_missing_time < HAND_LOST_PAUSE_SECONDS:
            return False

        self.hand_missing_time = 0.0
        self.pause_game(
            reason="Hand tracking was lost. Move inside the detection box and run Hand Check again.",
            require_hand_check=True,
        )
        self._set_status("Paused: hand tracking lost. Run Hand Check again.", 5.0)
        return True

    def _update_ui_gesture(self, dt: float, gesture: GestureState) -> bool:
        pointer = self._gesture_ui_pointer(gesture)
        if pointer is None or not self.buttons:
            self.ui_hover_action = None
            self.ui_hover_time = 0.0
            return False

        hovered_button = self._button_at(pointer)
        if hovered_button is None:
            self.ui_hover_action = None
            self.ui_hover_time = 0.0
            return False

        if hovered_button.action != self.ui_hover_action:
            self.ui_hover_action = hovered_button.action
            self.ui_hover_time = 0.0
        else:
            self.ui_hover_time += dt

        if self.ui_activation_cooldown > 0:
            return False

        dwell_click = self.ui_hover_time >= self._button_dwell_seconds(hovered_button)
        if not dwell_click:
            return False

        self.click_ripples.append(ClickRipple(float(pointer[0]), float(pointer[1])))
        self.ui_activation_cooldown = UI_ACTIVATION_COOLDOWN
        self.ui_hover_time = 0.0
        self._run_action(hovered_button.action, source="hand")
        return True

    def _update_calibration(self, dt: float, gesture: GestureState) -> None:
        self._update_saber(dt, gesture, allow_new_points=gesture.mode == "INDEX_SWORD")
        if not self._gesture_ready_in_safe_area(gesture):
            self.calibration.last_position = None
            return

        self.calibration.seen_time += dt
        if self.calibration.last_position is not None:
            dx = gesture.fingertip[0] - self.calibration.last_position[0]
            dy = gesture.fingertip[1] - self.calibration.last_position[1]
            distance = math.hypot(dx, dy)
            self.calibration.movement += distance
            if dt > 0:
                self.calibration.peak_speed = max(self.calibration.peak_speed, distance / dt)
        self.calibration.last_position = gesture.fingertip

    def _update_click_ripples(self, dt: float) -> None:
        for ripple in self.click_ripples:
            ripple.update(dt)
        self.click_ripples = [ripple for ripple in self.click_ripples if ripple.alive]

    def _update_confetti(self, dt: float) -> None:
        for piece in self.confetti:
            piece.update(dt)
        self.confetti = [piece for piece in self.confetti if piece.ttl > 0 and piece.y < SCREEN_HEIGHT + 80]

    def _update_timers(self, dt: float) -> None:
        if self.fever_timer > 0:
            self.fever_timer = max(0.0, self.fever_timer - dt)
            if self.fever_timer == 0.0:
                self.fever_cooldown = FEVER_COOLDOWN
        elif self.fever_cooldown > 0:
            self.fever_cooldown = max(0.0, self.fever_cooldown - dt)

    def _update_saber(self, dt: float, gesture: GestureState, allow_new_points: bool) -> None:
        self.saber_points = [(point, ttl - dt) for point, ttl in self.saber_points if ttl - dt > 0]
        if allow_new_points and gesture.mode == "INDEX_SWORD" and gesture.fingertip:
            self.saber_points.append((gesture.fingertip, 0.24))
            self.saber_points = self.saber_points[-18:]

    def _recent_saber_segments(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        if len(self.saber_points) < 2:
            return []
        points = [point for point, _ in self.saber_points[-8:]]
        return list(zip(points, points[1:]))

    def _update_music_playback(self) -> None:
        if not self.audio_ready or self.music_started or not self.analysis.path or self.game_time < 0:
            return
        try:
            pygame.mixer.music.load(self.analysis.path)
            pygame.mixer.music.play()
        except pygame.error as exc:
            self._set_status(f"Audio unavailable: {exc}", 3.0)
        self.music_started = True

    def _update_tutorial(self, dt: float, gesture: GestureState) -> None:
        allow_saber = self.tutorial.stage == "CUT"
        self._update_saber(dt, gesture, allow_new_points=allow_saber)

        if self.tutorial.stage == "CUT":
            if not self.fruits:
                self._spawn_tutorial_rock()
            for fruit in self.fruits:
                fruit.rotation += 0.8 * dt
            self._check_tutorial_slice()
            return

        if self.tutorial.stage == "CATCH":
            if not self.runners:
                self._spawn_tutorial_runner()
            self._update_runners(dt)
            self._check_tutorial_catch(gesture)
            return

        self.tutorial.auto_start_timer += dt
        if self.tutorial.auto_start_timer >= TUTORIAL_AUTO_START_SECONDS:
            self._launch_new_game()

    def _spawn_tutorial_rock(self) -> None:
        spec = self.rng.choice(FRUIT_TYPES)
        self.fruits = [
            Fruit(
                fruit_id=self.next_fruit_id,
                kind=str(spec["name"]),
                x=SCREEN_WIDTH * 0.5,
                y=SCREEN_HEIGHT * 0.53,
                vx=0.0,
                vy=0.0,
                radius=float(spec["radius"]) * 1.15,
                color=spec["color"],
                accent=spec["accent"],
                target_time=0.0,
                strength=0.6,
                gravity_scale=0.0,
                spin=0.55,
            )
        ]
        self.next_fruit_id += 1

    def _spawn_tutorial_runner(self) -> None:
        x = SCREEN_WIDTH * 0.34
        y = SCREEN_HEIGHT * 0.56
        variant = self.rng.choice(PIKMIN_VARIANTS)
        self.runners = [
            PikminRunner(
                runner_id=self.next_runner_id,
                variant=str(variant["name"]),
                x=x,
                y=y,
                vx=TUTORIAL_PIKMIN_INITIAL_VX,
                vy=TUTORIAL_PIKMIN_INITIAL_VY,
                color=variant["color"],
                target_x=SCREEN_WIDTH * 0.82,
                target_y=SCREEN_HEIGHT * 0.34,
                wiggle=self.rng.uniform(0, math.tau),
                speed_scale=TUTORIAL_PIKMIN_SPEED_SCALE,
                ttl=TUTORIAL_PIKMIN_TTL,
            )
        ]
        self.next_runner_id += 1

    def _check_tutorial_slice(self) -> None:
        if not self.fruits:
            return
        fruit = self.fruits[0]
        hit = any(fruit.intersects_segment(start, end) for start, end in self._recent_saber_segments())
        if not hit:
            return
        self.fruits.clear()
        self.tutorial.cut_done = True
        self.tutorial.stage = "CATCH"
        self._burst(fruit.x, fruit.y, fruit.color, amount=16)
        self.sfx.play_hit()
        self._add_feedback("Cut OK", fruit.x, fruit.y - 72, GOOD_COLOR)

    def _check_tutorial_catch(self, gesture: GestureState) -> None:
        if gesture.mode != "FIST" or gesture.palm_center is None:
            return

        remaining = []
        caught_runner: PikminRunner | None = None
        for runner in self.runners:
            if runner.catchable_by(gesture.palm_center, radius=84.0):
                runner.caught = True
                caught_runner = runner
            else:
                remaining.append(runner)
        self.runners = remaining
        if caught_runner is None:
            return

        self.tutorial.catch_done = True
        self.tutorial.stage = "DONE"
        self.tutorial.auto_start_timer = 0.0
        self.sfx.play_hit()
        self._burst(caught_runner.x, caught_runner.y, caught_runner.color, amount=9)
        self._add_feedback("Catch OK", caught_runner.x, caught_runner.y - 48, GOOD_COLOR)

    def _handle_fever_gesture(self, gesture: GestureState) -> None:
        open_palm = gesture.mode == "OPEN_PALM"
        if open_palm and not self.was_open_palm:
            self._trigger_fever(force=False)
        self.was_open_palm = open_palm

    def _trigger_fever(self, force: bool = False) -> None:
        if self.fever_timer > 0 or self.fever_cooldown > 0:
            return
        if force:
            if self.score.can_trigger_fever():
                self.score.trigger_fever()
            else:
                self.score.fever_gauge = 0.0
                self.score.fever_uses += 1
        elif not self.score.trigger_fever():
            return
        self.fever_timer = FEVER_DURATION
        cleared = list(self.fruits)
        self.fruits.clear()
        points = self.score.register_fever_clear(len(cleared))
        for fruit in cleared:
            self._shatter_rock(fruit, amount=8)
        self._add_feedback("Fever", SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 - 80, FEVER_COLOR)
        if points:
            self._add_feedback(f"+{points}", SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 - 24, FEVER_COLOR)

    def _spawn_due_fruits(self) -> None:
        new_fruits, self.next_fruit_id = self.spawner.due_fruits(
            self.game_time,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            self.next_fruit_id,
        )
        gate = self.analytics.spawn_gate
        if gate < 1.0:
            new_fruits = [f for f in new_fruits if self.rng.random() < gate]
        self.fruits.extend(new_fruits)

    def _update_fruits(self, dt: float) -> None:
        alive = []
        for fruit in self.fruits:
            fruit.update(dt)
            if fruit.is_offscreen(SCREEN_HEIGHT):
                self.score.register_miss()
                self.analytics.record_miss(self.game_time)
                self._add_feedback("Miss", fruit.x, SCREEN_HEIGHT - 120, MISS_COLOR)
            else:
                alive.append(fruit)
        self.fruits = alive

    def _update_runners(self, dt: float) -> None:
        alive = []
        for runner in self.runners:
            runner.update(dt)
            if not runner.escaped(SCREEN_WIDTH, SCREEN_HEIGHT) and not runner.caught:
                alive.append(runner)
        self.runners = alive

    def _catch_runners(self, gesture: GestureState) -> None:
        fist_active = gesture.mode == "FIST"
        if not fist_active or gesture.palm_center is None:
            self.was_fist = fist_active
            return

        remaining = []
        caught_now = 0
        for runner in self.runners:
            if runner.catchable_by(gesture.palm_center):
                runner.caught = True
                caught_now += 1
                self.caught_pikmin[runner.variant] = self.caught_pikmin.get(runner.variant, 0) + 1
                self.analytics.record_catch(self.game_time, runner.variant)
                self._add_feedback(f"Caught {runner.variant}", runner.x, runner.y - 28, GOOD_COLOR)
                self._burst(runner.x, runner.y, runner.color, amount=7)
            else:
                remaining.append(runner)
        self.runners = remaining
        if caught_now:
            self.sfx.play_hit()
        self.was_fist = fist_active

    def _check_slices(self) -> None:
        segments = self._recent_saber_segments()
        if not segments:
            return
        remaining = []
        for fruit in self.fruits:
            hit = any(fruit.intersects_segment(start, end) for start, end in segments)
            if not hit:
                remaining.append(fruit)
                continue
            offset = self.game_time - fruit.target_time
            result = self.score.register_slice(offset, fever_active=self.fever_timer > 0)
            self.analytics.record_hit(self.game_time, result.time_offset, result.judgement)
            color = PERFECT_COLOR if result.judgement == "Perfect" else GOOD_COLOR
            self._add_feedback(result.judgement, fruit.x, fruit.y - fruit.radius - 20, color)
            self._shatter_rock(fruit, amount=14)
            self.sfx.play_hit()
        self.fruits = remaining

    def _shatter_rock(self, fruit, amount: int) -> None:
        self._burst(fruit.x, fruit.y, fruit.color, amount=amount)
        self._spawn_runners_from_rock(fruit.x, fruit.y, fruit.strength)

    def _spawn_runners_from_rock(self, x: float, y: float, strength: float) -> None:
        count = self.rng.randint(PIKMIN_SPAWN_MIN, PIKMIN_SPAWN_MAX)
        for _ in range(count):
            variant = self.rng.choice(PIKMIN_VARIANTS)
            target_x, target_y = self._random_edge_target()
            angle = math.atan2(target_y - y, target_x - x) + self.rng.uniform(-0.75, 0.75)
            fast_runner = self.rng.random() < PIKMIN_FAST_RUNNER_CHANCE
            speed_scale = (
                self.rng.uniform(PIKMIN_FAST_SPEED_SCALE_MIN, PIKMIN_FAST_SPEED_SCALE_MAX)
                if fast_runner
                else self.rng.uniform(PIKMIN_NORMAL_SPEED_SCALE_MIN, PIKMIN_NORMAL_SPEED_SCALE_MAX)
            )
            speed = self.rng.uniform(PIKMIN_BASE_SPEED_MIN, PIKMIN_BASE_SPEED_MAX) * speed_scale
            self.runners.append(
                PikminRunner(
                    runner_id=self.next_runner_id,
                    variant=str(variant["name"]),
                    x=x + self.rng.uniform(-18, 18),
                    y=y + self.rng.uniform(-18, 18),
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed,
                    color=variant["color"],
                    target_x=target_x,
                    target_y=target_y,
                    wiggle=self.rng.uniform(0, math.tau),
                    speed_scale=speed_scale,
                )
            )
            self.next_runner_id += 1

    def _random_edge_target(self) -> tuple[float, float]:
        side = self.rng.choice(("top", "right", "bottom", "left"))
        if side == "top":
            return self.rng.uniform(0, SCREEN_WIDTH), -80.0
        if side == "right":
            return SCREEN_WIDTH + 80.0, self.rng.uniform(0, SCREEN_HEIGHT)
        if side == "bottom":
            return self.rng.uniform(0, SCREEN_WIDTH), SCREEN_HEIGHT + 80.0
        return -80.0, self.rng.uniform(0, SCREEN_HEIGHT)

    def _update_sparks(self, dt: float) -> None:
        for spark in self.sparks:
            spark.update(dt)
        self.sparks = [spark for spark in self.sparks if spark.alive()]

    def _update_feedback(self, dt: float) -> None:
        for item in self.feedback:
            item.update(dt)
        self.feedback = [item for item in self.feedback if item.ttl > 0]

    def _burst(self, x: float, y: float, color: tuple[int, int, int], amount: int) -> None:
        for index in range(amount):
            angle = (math.tau / amount) * index + self.rng.uniform(-0.2, 0.2)
            speed = self.rng.uniform(130, 310)
            self.sparks.append(
                SliceSpark(
                    x=x,
                    y=y,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed,
                    color=color,
                )
            )

    def _spawn_confetti(self) -> None:
        colors = (FEVER_COLOR, ACCENT_COLOR, GOOD_COLOR, PERFECT_COLOR, (255, 128, 164), (170, 132, 255))
        for _ in range(120):
            side = self.rng.choice((-1, 1))
            x = SCREEN_WIDTH / 2 + self.rng.uniform(-120, 120)
            y = self.rng.uniform(-40, 80)
            self.confetti.append(
                ConfettiPiece(
                    x=x,
                    y=y,
                    vx=side * self.rng.uniform(60, 360),
                    vy=self.rng.uniform(-160, 80),
                    color=self.rng.choice(colors),
                    size=self.rng.randint(5, 12),
                    ttl=self.rng.uniform(2.2, 4.0),
                    rotation=self.rng.uniform(0, math.tau),
                    spin=self.rng.uniform(-9, 9),
                )
            )

    def _add_feedback(self, text: str, x: float, y: float, color: tuple[int, int, int]) -> None:
        self.feedback.append(FloatingText(text=text, x=x, y=y, color=color))

    def _set_status(self, text: str, seconds: float) -> None:
        self.status_message = text
        self.status_timer = seconds

    def _block_start(self, message: str) -> None:
        self._set_status(message, 5.0)
        print(f"Cannot start: {message}")

    def _hand_input_available(self) -> bool:
        return self.camera.available and self.tracker.available

    def _can_start_play(self, gesture: GestureState) -> bool:
        if not self.calibration.ready:
            return False
        return self._hand_input_available() and self._gesture_ready_in_safe_area(gesture)

    def _hand_issue_message(self, gesture: GestureState) -> str:
        if not self.camera.available:
            return self.camera.error or "Camera unavailable. Enable camera permission, close apps using the webcam, then restart."
        if not self.latest_frame_available:
            return "No camera frame. Check webcam permission or reconnect the camera."
        if not self.tracker.available:
            return f"Hand tracker unavailable. {self.tracker.error or 'Check MediaPipe and model setup.'}"
        if gesture.mode not in {"INDEX_SWORD", "OPEN_PALM", "FIST"}:
            return "No hand detected. Put your hand fully in frame with good lighting."
        if gesture.fingertip is not None and not self._point_in_safe_area(gesture.fingertip):
            return "Move your hand inside the detection box. Edges are less accurate."
        if not self.calibration.ready:
            return "Hand check incomplete. Move your index finger until the meter is full."
        return "Hand input is not ready yet."

    def _gesture_ready_in_safe_area(self, gesture: GestureState) -> bool:
        return (
            gesture.mode in {"INDEX_SWORD", "OPEN_PALM", "FIST"}
            and gesture.fingertip is not None
            and self._point_in_safe_area(gesture.fingertip)
        )

    def _tracking_safe_rect(self) -> pygame.Rect:
        margin_x = int(SCREEN_WIDTH * TRACKING_SAFE_MARGIN_X)
        margin_y = int(SCREEN_HEIGHT * TRACKING_SAFE_MARGIN_Y)
        return pygame.Rect(
            margin_x,
            margin_y,
            SCREEN_WIDTH - margin_x * 2,
            SCREEN_HEIGHT - margin_y * 2,
        )

    def _point_in_safe_area(self, point: tuple[int, int]) -> bool:
        return self._tracking_safe_rect().collidepoint(point)

    def _gesture_ui_pointer(self, gesture: GestureState) -> tuple[int, int] | None:
        if gesture.fingertip is None:
            return None
        if gesture.mode not in {"INDEX_SWORD", "OPEN_PALM"}:
            return None
        return gesture.fingertip

    def _button_enabled(self, button: Button) -> bool:
        if button.action == "calibration_start":
            return self._can_start_play(self.latest_gesture)
        return True

    def _button_at(self, position: tuple[int, int]) -> Button | None:
        for button in self.buttons:
            if button.rect.collidepoint(position) and self._button_enabled(button):
                return button
        return None

    def _button_hovered(self, button: Button) -> bool:
        mouse_position = pygame.mouse.get_pos()
        if button.rect.collidepoint(mouse_position):
            return True
        pointer = self._gesture_ui_pointer(self.latest_gesture)
        return pointer is not None and button.rect.collidepoint(pointer)

    def _button_dwell_progress(self, button: Button) -> float:
        if button.action != self.ui_hover_action:
            return 0.0
        return max(0.0, min(1.0, self.ui_hover_time / self._button_dwell_seconds(button)))

    def _button_dwell_seconds(self, button: Button) -> float:
        if self.mode == "START":
            return START_MENU_DWELL_SECONDS if button.action != "quit" else START_MENU_DWELL_SECONDS + 0.6
        return QUIT_DWELL_SECONDS if button.action == "quit" else UI_DWELL_SECONDS

    def _draw(self, frame, gesture: GestureState) -> None:
        self._draw_background()
        self._draw_playfield(gesture)

        if self.mode in {"PLAYING", "PAUSED", "RESULTS"}:
            draw_hud(
                self.screen,
                self.fonts,
                self.score,
                max(0.0, self.game_time),
                self.duration,
                self.fever_timer,
                self.fever_cooldown,
                f"{self.analysis.title} / {self.current_difficulty['label']}",
            )
            for button in self.buttons if self.mode == "PLAYING" else []:
                self._draw_button(button)

        if self.mode == "START":
            self._draw_start_screen()
        elif self.mode == "CALIBRATION":
            self._draw_calibration_screen(gesture)
        elif self.mode == "TUTORIAL":
            self._draw_tutorial_screen()
        elif self.mode == "PAUSED":
            self._draw_pause_screen()
        elif self.mode == "GALLERY":
            self._draw_gallery_screen()
        elif self.mode == "RESULTS":
            self._draw_results_screen()

        if self.status_timer > 0 and self.status_message:
            draw_text(self.screen, self.status_message, self.fonts["small"], TEXT_COLOR, (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 28), "center")

        self._draw_confetti()
        self._draw_camera_preview(frame, gesture)
        self._draw_click_ripples()
        self._draw_pointer_markers(gesture)
        pygame.display.flip()

    def _draw_background(self) -> None:
        self.screen.blit(self.background, (0, 0))
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 82))
        self.screen.blit(overlay, (0, 0))

    def _draw_playfield(self, gesture: GestureState) -> None:
        self._draw_tracking_safe_area()
        hit_y = int(SCREEN_HEIGHT * HIT_LINE_Y_RATIO)
        pygame.draw.line(self.screen, (255, 255, 255, 48), (0, hit_y), (SCREEN_WIDTH, hit_y), 2)

        for fruit in self.fruits:
            fruit.draw(self.screen)

        for runner in self.runners:
            runner.draw(self.screen)

        for spark in self.sparks:
            spark.draw(self.screen)

        self._draw_saber()
        self._draw_gesture_marker(gesture)

        if self.mode == "PLAYING" and -GET_READY_SECONDS <= self.game_time < 0:
            ready_text = f"Get Ready {max(1, math.ceil(-self.game_time))}"
            draw_text(
                self.screen,
                ready_text,
                self.fonts["title"],
                FEVER_COLOR,
                (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2),
                "center",
            )

        for item in self.feedback:
            alpha = max(0, min(255, int(255 * item.ttl / 0.8)))
            text = self.fonts["medium"].render(item.text, True, item.color)
            text.set_alpha(alpha)
            self.screen.blit(text, text.get_rect(center=(int(item.x), int(item.y))))

    def _draw_tracking_safe_area(self) -> None:
        safe_rect = self._tracking_safe_rect()
        layer = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(layer, (*ACCENT_COLOR, 36), safe_rect, border_radius=8)
        pygame.draw.rect(layer, (*ACCENT_COLOR, 128), safe_rect, 2, border_radius=8)
        corner = 38
        for start, end in (
            ((safe_rect.x, safe_rect.y), (safe_rect.x + corner, safe_rect.y)),
            ((safe_rect.x, safe_rect.y), (safe_rect.x, safe_rect.y + corner)),
            ((safe_rect.right, safe_rect.y), (safe_rect.right - corner, safe_rect.y)),
            ((safe_rect.right, safe_rect.y), (safe_rect.right, safe_rect.y + corner)),
            ((safe_rect.x, safe_rect.bottom), (safe_rect.x + corner, safe_rect.bottom)),
            ((safe_rect.x, safe_rect.bottom), (safe_rect.x, safe_rect.bottom - corner)),
            ((safe_rect.right, safe_rect.bottom), (safe_rect.right - corner, safe_rect.bottom)),
            ((safe_rect.right, safe_rect.bottom), (safe_rect.right, safe_rect.bottom - corner)),
        ):
            pygame.draw.line(layer, (*FEVER_COLOR, 180), start, end, 4)
        self.screen.blit(layer, (0, 0))

    def _draw_start_screen(self) -> None:
        draw_dim_overlay(self.screen, 145)
        panel = pygame.Rect(0, 0, 700, 640)
        panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        pygame.draw.rect(self.screen, (18, 25, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel, 2, border_radius=8)

        draw_text(self.screen, "AR Fruit Ninja", self.fonts["title"], TEXT_COLOR, (panel.centerx, panel.y + 50), "center")
        draw_text(self.screen, f"Music: {self.analysis.title}", self.fonts["small"], (205, 216, 228), (panel.centerx, panel.y + 104), "center")

        label_y = panel.y + 146
        draw_text(self.screen, "Player Name", self.fonts["small"], (205, 216, 228), (panel.x + 70, label_y))
        input_rect = pygame.Rect(panel.x + 70, label_y + 28, panel.width - 140, 50)
        pygame.draw.rect(self.screen, (9, 15, 23), input_rect, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT_COLOR, input_rect, 2, border_radius=8)
        name = self.player_name if self.player_name else "Type your name"
        color = TEXT_COLOR if self.player_name else (119, 132, 148)
        draw_text(self.screen, name, self.fonts["medium"], color, (input_rect.x + 18, input_rect.centery), "midleft")

        draw_text(self.screen, "Leaderboard", self.fonts["small"], (205, 216, 228), (panel.x + 70, panel.y + 248))
        top_entries = self.leaderboard_entries[:3]
        if not top_entries:
            draw_text(self.screen, "No scores yet", self.fonts["small"], (142, 154, 170), (panel.x + 70, panel.y + 278))
        for index, entry in enumerate(top_entries, start=1):
            line = f"{index}. {entry.name}  {entry.score}  {entry.grade}"
            draw_text(self.screen, line, self.fonts["small"], TEXT_COLOR, (panel.x + 70, panel.y + 256 + index * 28))

        difficulty = self.current_difficulty
        draw_text(
            self.screen,
            f"Difficulty: {difficulty['label']}  Drop Speed x{self.current_fruit_speed_multiplier:.2f}",
            self.fonts["small"],
            (205, 216, 228),
            (panel.centerx, panel.y + 328),
            "center",
        )

        for button in self.buttons:
            self._draw_button(button)

    def _draw_calibration_screen(self, gesture: GestureState) -> None:
        draw_dim_overlay(self.screen, 108)
        panel = pygame.Rect(0, 0, 680, 440)
        panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        pygame.draw.rect(self.screen, (18, 25, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel, 2, border_radius=8)

        draw_text(self.screen, "Hand Check", self.fonts["title"], TEXT_COLOR, (panel.centerx, panel.y + 48), "center")
        status = "Ready" if self._can_start_play(gesture) else self._hand_issue_message(gesture)
        if len(status) > 78:
            status = status[:75] + "..."
        status_color = GOOD_COLOR if self._can_start_play(gesture) else (255, 201, 111)
        draw_text(self.screen, status, self.fonts["small"], status_color, (panel.centerx, panel.y + 104), "center")

        seen_value = min(1.0, self.calibration.seen_time / CALIBRATION_MIN_SEEN)
        movement_value = min(1.0, self.calibration.movement / CALIBRATION_MIN_MOVEMENT)
        draw_text(self.screen, "Tracking", self.fonts["small"], TEXT_COLOR, (panel.x + 86, panel.y + 154))
        draw_gauge(self.screen, pygame.Rect(panel.x + 210, panel.y + 152, 360, 24), seen_value, GOOD_COLOR)
        draw_text(self.screen, "Movement", self.fonts["small"], TEXT_COLOR, (panel.x + 86, panel.y + 204))
        draw_gauge(self.screen, pygame.Rect(panel.x + 210, panel.y + 202, 360, 24), movement_value, ACCENT_COLOR)

        speed = int(self.calibration.peak_speed)
        draw_text(
            self.screen,
            f"Peak speed {speed} px/s",
            self.fonts["medium"],
            TEXT_COLOR,
            (panel.centerx, panel.y + 272),
            "center",
        )

        for button in self.buttons:
            active = button.action != "calibration_start" or self._can_start_play(gesture)
            self._draw_button(button, active=active)

    def _draw_tutorial_screen(self) -> None:
        draw_dim_overlay(self.screen, 82)
        panel = pygame.Rect(0, 0, 860, 268)
        panel.center = (SCREEN_WIDTH // 2, 166)
        pygame.draw.rect(self.screen, (18, 25, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel, 2, border_radius=8)

        stage_title = "Prompt 1: Cut" if self.tutorial.stage == "CUT" else "Prompt 2: Catch"
        if self.tutorial.stage == "DONE":
            stage_title = "Training Complete"

        draw_text(self.screen, "New Player Training", self.fonts["title"], TEXT_COLOR, (panel.centerx, panel.y + 38), "center")
        draw_text(self.screen, stage_title, self.fonts["medium"], FEVER_COLOR, (panel.centerx, panel.y + 90), "center")

        cut_color = GOOD_COLOR if self.tutorial.cut_done else TEXT_COLOR
        catch_color = GOOD_COLOR if self.tutorial.catch_done else TEXT_COLOR
        draw_text(
            self.screen,
            f"[{'x' if self.tutorial.cut_done else ' '}] Cut: Use one raised index finger and slash the rock.",
            self.fonts["small"],
            cut_color,
            (panel.x + 56, panel.y + 138),
        )
        draw_text(
            self.screen,
            f"[{'x' if self.tutorial.catch_done else ' '}] Catch: Make a fist and grab the running Pikmin.",
            self.fonts["small"],
            catch_color,
            (panel.x + 56, panel.y + 176),
        )

        if self.tutorial.stage == "DONE":
            subtitle = "Nice work. Starting the game now..."
        elif self.tutorial.stage == "CUT":
            subtitle = "Slash through the rock in the center with your index-finger saber."
        else:
            subtitle = "Grab the Pikmin with a fist before it runs away."
        draw_text(self.screen, subtitle, self.fonts["small"], (205, 216, 228), (panel.centerx, panel.y + 220), "center")

        for button in self.buttons:
            self._draw_button(button)

    def _draw_pause_screen(self) -> None:
        draw_dim_overlay(self.screen, 170)
        panel_rect = pygame.Rect(0, 0, 560, 360)
        panel_rect.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        pygame.draw.rect(self.screen, (18, 25, 35), panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel_rect, 2, border_radius=8)
        draw_text(self.screen, "Paused", self.fonts["title"], TEXT_COLOR, (SCREEN_WIDTH // 2, panel_rect.y + 58), "center")
        subtitle = self.pause_message if self.pause_message else self.analysis.title
        draw_text(self.screen, subtitle, self.fonts["small"], (255, 201, 111) if self.pause_message else (162, 174, 190), (SCREEN_WIDTH // 2, panel_rect.y + 116), "center")
        for button in self.buttons:
            self._draw_button(button)

    def _draw_gallery_screen(self) -> None:
        draw_dim_overlay(self.screen, 155)
        panel = pygame.Rect(0, 0, 760, 560)
        panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        pygame.draw.rect(self.screen, (18, 25, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel, 2, border_radius=8)

        total = self.total_caught_pikmin()
        draw_text(self.screen, "Pikmin Gallery", self.fonts["title"], TEXT_COLOR, (panel.centerx, panel.y + 46), "center")
        draw_text(self.screen, f"Caught {total}", self.fonts["large"], FEVER_COLOR, (panel.centerx, panel.y + 106), "center")

        variants = [item for item in PIKMIN_VARIANTS if self.caught_pikmin.get(str(item["name"]), 0) > 0]
        start_x = panel.x + 94
        start_y = panel.y + 180
        for index, variant in enumerate(variants):
            col = index % 3
            row = index // 3
            x = start_x + col * 205
            y = start_y + row * 112
            count = self.caught_pikmin.get(str(variant["name"]), 0)
            card = pygame.Rect(x, y, 160, 82)
            pygame.draw.rect(self.screen, (10, 16, 24), card, border_radius=8)
            pygame.draw.rect(self.screen, variant["color"], card, 2, border_radius=8)
            self._draw_gallery_pikmin(card.x + 36, card.centery + 10, variant["color"])
            draw_text(self.screen, str(variant["name"]), self.fonts["small"], TEXT_COLOR, (card.x + 72, card.y + 18))
            draw_text(self.screen, f"x {count}", self.fonts["medium"], FEVER_COLOR, (card.x + 72, card.y + 42))

        for button in self.buttons:
            self._draw_button(button)

    def _draw_gallery_pikmin(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        body_rect = pygame.Rect(0, 0, 24, 34)
        body_rect.center = (x, y)
        pygame.draw.ellipse(self.screen, color, body_rect)
        pygame.draw.ellipse(self.screen, (255, 255, 255), body_rect, 2)
        pygame.draw.circle(self.screen, (20, 24, 28), (x - 5, y - 6), 2)
        pygame.draw.circle(self.screen, (20, 24, 28), (x + 5, y - 6), 2)
        pygame.draw.line(self.screen, (82, 198, 96), (x, y - 18), (x, y - 38), 3)
        pygame.draw.polygon(self.screen, (90, 210, 110), [(x, y - 39), (x + 14, y - 46), (x + 10, y - 31)])

    def _draw_results_screen(self) -> None:
        draw_dim_overlay(self.screen, 155)
        panel = pygame.Rect(0, 0, 980, 590)
        panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        pygame.draw.rect(self.screen, (18, 25, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), panel, 2, border_radius=8)

        # ── header (full width) ────────────────────────────────────────────────
        draw_text(self.screen, "Results", self.fonts["title"], TEXT_COLOR, (panel.centerx, panel.y + 46), "center")
        summary = f"{self.player_name or 'Player'}  Grade {self.score.grade()}  Score {self.score.score}  Max Combo {self.score.max_combo}"
        draw_text(self.screen, summary, self.fonts["medium"], TEXT_COLOR, (panel.centerx, panel.y + 100), "center")
        if self.new_high:
            draw_text(self.screen, "New High!", self.fonts["large"], FEVER_COLOR, (panel.centerx, panel.y + 138), "center")

        # ── left column: leaderboard ───────────────────────────────────────────
        leaderboard_y = panel.y + 186 if self.new_high else panel.y + 154
        draw_text(self.screen, "Leaderboard", self.fonts["medium"], (205, 216, 228), (panel.x + 52, leaderboard_y))
        entries = self.leaderboard_entries[:5]
        if not entries:
            draw_text(self.screen, "No scores yet", self.fonts["small"], (142, 154, 170), (panel.x + 52, leaderboard_y + 42))
        for index, entry in enumerate(entries, start=1):
            line = f"{index}. {entry.name:<14} {entry.score:>6}  {entry.grade}  x{entry.max_combo}"
            color = FEVER_COLOR if entry.name == (self.player_name.strip() or "Player") and entry.score == self.score.score else TEXT_COLOR
            draw_text(self.screen, line, self.fonts["small"], color, (panel.x + 52, leaderboard_y + 12 + index * 34))

        # ── right column: radar chart ──────────────────────────────────────────
        stats = self.analytics.radar_stats(self.score.max_combo)
        radar_cx = panel.x + 770
        radar_cy = panel.y + 360
        draw_radar_chart(
            self.screen, radar_cx, radar_cy, 140, stats,
            self.fonts["small"],
        )
        draw_text(
            self.screen, "Player Profile",
            self.fonts["medium"], (205, 216, 228),
            (radar_cx, panel.y + 168), "center",
        )

        for button in self.buttons:
            self._draw_button(button)

    def _draw_button(self, button: Button, active: bool = True) -> None:
        enabled = active and self._button_enabled(button)
        hovered = enabled and self._button_hovered(button)
        pointer = self._gesture_ui_pointer(self.latest_gesture)
        hand_hovered = enabled and pointer is not None and button.rect.collidepoint(pointer)
        selected_difficulty = False
        if button.action.startswith("difficulty:"):
            try:
                selected_difficulty = int(button.action.split(":", 1)[1]) == self.difficulty_index
            except ValueError:
                selected_difficulty = False
        if hovered:
            glow = pygame.Surface((button.rect.width + 38, button.rect.height + 38), pygame.SRCALPHA)
            glow_rect = glow.get_rect()
            for index, alpha in enumerate((42, 28, 16)):
                inset = index * 7
                pygame.draw.rect(
                    glow,
                    (*FEVER_COLOR, alpha),
                    glow_rect.inflate(-inset, -inset),
                    border_radius=12,
                    width=4,
                )
            self.screen.blit(glow, (button.rect.x - 19, button.rect.y - 19))
            pygame.draw.line(
                self.screen,
                (255, 255, 255),
                (button.rect.x + 16, button.rect.y + 8),
                (button.rect.right - 16, button.rect.y + 8),
                2,
            )

        button.draw(
            self.screen,
            self.fonts["button"],
            active=enabled and (hovered or selected_difficulty or not button.action.startswith("difficulty:")),
        )
        if selected_difficulty:
            pygame.draw.rect(self.screen, FEVER_COLOR, button.rect.inflate(8, 8), 3, border_radius=10)

        progress = self._button_dwell_progress(button) if hand_hovered else 0.0
        if progress > 0:
            center = (button.rect.centerx, button.rect.y - 20)
            pygame.draw.circle(self.screen, (25, 33, 44), center, 16)
            pygame.draw.circle(self.screen, (255, 255, 255), center, 16, 2)
            pygame.draw.arc(
                self.screen,
                FEVER_COLOR,
                pygame.Rect(center[0] - 16, center[1] - 16, 32, 32),
                -math.pi / 2,
                -math.pi / 2 + math.tau * progress,
                4,
            )
            pygame.draw.circle(self.screen, FEVER_COLOR, center, 3)

    def _draw_camera_preview(self, frame, gesture: GestureState) -> None:
        preview_width, preview_height = PREVIEW_SIZE
        rect = pygame.Rect(
            SCREEN_WIDTH - preview_width - 24,
            SCREEN_HEIGHT - preview_height - 24,
            preview_width,
            preview_height,
        )
        pygame.draw.rect(self.screen, (8, 13, 20), rect, border_radius=8)

        if frame is not None:
            try:
                preview = pygame.transform.smoothscale(frame_to_surface(frame), (preview_width, preview_height))
                self.screen.blit(preview, rect)
            except Exception:
                pygame.draw.rect(self.screen, (16, 24, 34), rect)
                draw_text(self.screen, "Camera preview error", self.fonts["small"], (205, 216, 228), rect.center, "center")
        else:
            pygame.draw.rect(self.screen, (16, 24, 34), rect)
            draw_text(self.screen, "Camera off", self.fonts["small"], (205, 216, 228), rect.center, "center")

        self._draw_tracking_overlay(rect, gesture)
        game_frame = self._camera_game_rect(rect)
        pygame.draw.rect(self.screen, (*FEVER_COLOR, 190), game_frame, 2, border_radius=6)
        pygame.draw.line(self.screen, FEVER_COLOR, (game_frame.x, game_frame.bottom), (game_frame.right, game_frame.bottom), 4)
        draw_text(
            self.screen,
            "screen bottom",
            self.fonts["small"],
            FEVER_COLOR,
            (game_frame.centerx, game_frame.bottom + 4),
            "midtop",
        )
        safe = pygame.Rect(
            rect.x + int(rect.width * TRACKING_SAFE_MARGIN_X),
            rect.y + int(rect.height * TRACKING_SAFE_MARGIN_Y),
            rect.width - int(rect.width * TRACKING_SAFE_MARGIN_X) * 2,
            rect.height - int(rect.height * TRACKING_SAFE_MARGIN_Y) * 2,
        )
        pygame.draw.rect(self.screen, (*ACCENT_COLOR, 170), safe, 2, border_radius=6)

        status_band = pygame.Surface((preview_width, 30), pygame.SRCALPHA)
        status_band.fill((0, 0, 0, 156))
        self.screen.blit(status_band, (rect.x, rect.y))
        detected = gesture.mode in {"INDEX_SWORD", "OPEN_PALM", "FIST"} and gesture.fingertip is not None
        inside = detected and self._point_in_safe_area(gesture.fingertip)
        label = "HAND DETECTED" if inside else "MOVE INSIDE BOX" if detected else "NO HAND"
        color = GOOD_COLOR if inside else (255, 201, 111) if detected else MISS_COLOR
        draw_text(self.screen, label, self.fonts["small"], color, (rect.x + 12, rect.y + 7))
        draw_text(self.screen, gesture.source, self.fonts["small"], (205, 216, 228), (rect.right - 12, rect.y + 7), "topright")
        pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=8)

    def _camera_game_rect(self, rect: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(
            rect.x + int(rect.width * CAMERA_GAME_LEFT),
            rect.y + int(rect.height * CAMERA_GAME_TOP),
            int(rect.width * (CAMERA_GAME_RIGHT - CAMERA_GAME_LEFT)),
            int(rect.height * (CAMERA_GAME_BOTTOM - CAMERA_GAME_TOP)),
        )

    def _draw_tracking_overlay(self, rect: pygame.Rect, gesture: GestureState) -> None:
        if not gesture.tracking_points:
            return

        mapped = [
            (
                int(rect.x + max(0.0, min(1.0, x)) * rect.width),
                int(rect.y + max(0.0, min(1.0, y)) * rect.height),
            )
            for x, y in gesture.tracking_points
        ]
        if len(mapped) == 21:
            for start, end in HAND_CONNECTIONS:
                pygame.draw.line(self.screen, FEVER_COLOR, mapped[start], mapped[end], 2)
            for point in mapped:
                pygame.draw.circle(self.screen, (255, 255, 255), point, 3)
        elif len(mapped) >= 3:
            pygame.draw.lines(self.screen, FEVER_COLOR, True, mapped, 2)

        if gesture.camera_palm_center:
            palm = self._camera_to_preview(rect, gesture.camera_palm_center)
            pygame.draw.circle(self.screen, GOOD_COLOR, palm, 6, 2)
        if gesture.camera_fingertip:
            tip = self._camera_to_preview(rect, gesture.camera_fingertip)
            pygame.draw.circle(self.screen, (255, 255, 255), tip, 5)
            pygame.draw.circle(self.screen, ACCENT_COLOR, tip, 10, 2)

    def _camera_to_preview(self, rect: pygame.Rect, point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(rect.x + max(0.0, min(1.0, point[0])) * rect.width),
            int(rect.y + max(0.0, min(1.0, point[1])) * rect.height),
        )

    def _draw_click_ripples(self) -> None:
        for ripple in self.click_ripples:
            progress = max(0.0, min(1.0, 1.0 - ripple.ttl / 0.38))
            radius = int(10 + progress * 34)
            alpha = int(190 * (1.0 - progress))
            layer = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
            center = (radius + 3, radius + 3)
            pygame.draw.circle(layer, (*FEVER_COLOR, alpha), center, radius, 3)
            pygame.draw.circle(layer, (255, 255, 255, min(255, alpha + 40)), center, 4)
            self.screen.blit(layer, (int(ripple.x - radius - 3), int(ripple.y - radius - 3)))

    def _draw_confetti(self) -> None:
        for piece in self.confetti:
            alpha = max(0, min(255, int(255 * min(1.0, piece.ttl / 1.0))))
            layer_size = piece.size * 3
            layer = pygame.Surface((layer_size, layer_size), pygame.SRCALPHA)
            rect = pygame.Rect(0, 0, piece.size, max(3, piece.size // 2))
            rect.center = (layer_size // 2, layer_size // 2)
            pygame.draw.rect(layer, (*piece.color, alpha), rect, border_radius=2)
            rotated = pygame.transform.rotate(layer, math.degrees(piece.rotation))
            self.screen.blit(rotated, rotated.get_rect(center=(int(piece.x), int(piece.y))))

    def _draw_pointer_markers(self, gesture: GestureState) -> None:
        pointer = self._gesture_ui_pointer(gesture)
        hand_active = pointer is not None and (self.mode != "PLAYING" or self._button_at(pointer) is not None)
        mouse_active = pygame.mouse.get_focused() and not hand_active

        if mouse_active:
            mouse_position = pygame.mouse.get_pos()
            hovered = self._button_at(mouse_position) is not None
            color = FEVER_COLOR if hovered else (255, 255, 255)
            pygame.draw.circle(self.screen, (0, 0, 0), mouse_position, 11)
            pygame.draw.circle(self.screen, color, mouse_position, 9, 2)
            pygame.draw.line(self.screen, color, (mouse_position[0] - 14, mouse_position[1]), (mouse_position[0] + 14, mouse_position[1]), 2)
            pygame.draw.line(self.screen, color, (mouse_position[0], mouse_position[1] - 14), (mouse_position[0], mouse_position[1] + 14), 2)

        if hand_active:
            pygame.draw.circle(self.screen, (0, 0, 0), pointer, 18)
            pygame.draw.circle(self.screen, ACCENT_COLOR, pointer, 16, 3)
            pygame.draw.circle(self.screen, (255, 255, 255), pointer, 5)

    def _draw_saber(self) -> None:
        if len(self.saber_points) < 2:
            return
        points = [point for point, _ in self.saber_points]
        blade_color = FEVER_COLOR if self.fever_timer > 0 else ACCENT_COLOR
        for width, color in ((18, (*blade_color, 54)), (9, (*blade_color, 135)), (3, (255, 255, 255, 235))):
            layer = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            pygame.draw.lines(layer, color, False, points, width)
            self.screen.blit(layer, (0, 0))

    def _draw_gesture_marker(self, gesture: GestureState) -> None:
        if gesture.mode == "OPEN_PALM" and gesture.palm_center:
            pygame.draw.circle(self.screen, FEVER_COLOR, gesture.palm_center, 34, 4)
        elif gesture.mode == "FIST" and gesture.palm_center:
            pygame.draw.circle(self.screen, GOOD_COLOR, gesture.palm_center, 42, 4)
            pygame.draw.circle(self.screen, (255, 255, 255), gesture.palm_center, 12, 2)
        elif gesture.mode == "INDEX_SWORD" and gesture.fingertip:
            pygame.draw.circle(self.screen, (255, 255, 255), gesture.fingertip, 8)
            pygame.draw.circle(self.screen, ACCENT_COLOR, gesture.fingertip, 18, 2)

    def _draw_loading(self, text: str) -> None:
        self._draw_background()
        draw_text(self.screen, text, self.fonts["large"], TEXT_COLOR, (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2), "center")
        pygame.display.flip()


def run() -> int:
    return FruitNinjaARApp().run()
