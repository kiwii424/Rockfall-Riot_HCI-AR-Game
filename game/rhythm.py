from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from .config import (
    DEFAULT_BPM,
    DEFAULT_DURATION,
    ROCK_TYPES,
    GRAVITY,
    HIT_LINE_Y_RATIO,
    ROCK_BEAT_SPEED_MAX,
    ROCK_BEAT_SPEED_MIN,
    SPAWN_LEAD_TIME,
)
from .entities import Rock


@dataclass(frozen=True)
class BeatEvent:
    timestamp: float
    strength: float = 0.5
    index: int = 0


@dataclass(frozen=True)
class MusicAnalysis:
    path: str | None
    title: str
    duration: float
    tempo: float
    events: tuple[BeatEvent, ...]
    backend: str = "default"


def default_events(duration: float = DEFAULT_DURATION, bpm: float = DEFAULT_BPM) -> tuple[BeatEvent, ...]:
    interval = 60.0 / bpm
    events: list[BeatEvent] = []
    timestamp = 1.0
    index = 0
    while timestamp <= duration:
        strength = 0.88 if index % 8 == 0 else 0.62 if index % 4 == 0 else 0.46
        events.append(BeatEvent(timestamp=timestamp, strength=strength, index=index))
        timestamp += interval
        index += 1
    return tuple(events)


def default_analysis() -> MusicAnalysis:
    return MusicAnalysis(
        path=None,
        title="Default Beat",
        duration=DEFAULT_DURATION,
        tempo=float(DEFAULT_BPM),
        events=default_events(),
        backend="default",
    )


def _music_start_time(y, sr) -> float:
    """Return timestamp where audio content begins (skip leading silence)."""
    import librosa
    _, trim_indices = librosa.effects.trim(y, top_db=28)
    start_sample = int(trim_indices[0])
    return float(start_sample / sr) if start_sample > 0 else 0.0


def _onset_strengths(y, sr, beat_times) -> list[float]:
    """Map beat timestamps to normalised onset-envelope strengths."""
    import librosa
    import numpy as np

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    if onset_env.size == 0:
        return [0.5 for _ in beat_times]

    beat_values: list[float] = []
    for t in beat_times:
        frame = int(librosa.time_to_frames(float(t), sr=sr))
        frame = max(0, min(frame, len(onset_env) - 1))
        beat_values.append(float(onset_env[frame]))
    return _normalize_strengths(beat_values)


def _normalize_strengths(values: list[float]) -> list[float]:
    import numpy as np

    if not values:
        return []

    arr = np.asarray(values, dtype=float)
    low = float(np.percentile(arr, 10))
    high = float(np.percentile(arr, 95))
    if not math.isfinite(low):
        low = float(np.min(arr))
    if not math.isfinite(high):
        high = float(np.max(arr))
    if high - low < 1e-6:
        max_strength = float(np.max(arr))
        if max_strength <= 1e-6:
            return [0.5 for _ in values]
        scaled = arr / max_strength
    else:
        scaled = (arr - low) / (high - low)

    scaled = np.clip(scaled, 0.0, 1.0)
    return [float(0.25 + value * 0.75) for value in scaled]


def _meter_strengths(
    beat_times: list[float],
    downbeat_times: list[float],
    onset_strengths: list[float],
) -> list[float]:
    """
    Merge meter position with onset strength.

    Downbeats → strength clamped to [0.85, 1.0] (guarantees 2 rocks).
    Other beats → onset strength kept in [0.25, 0.75] (guarantees 1 rock).

    Fallback: if downbeat_times is empty, treat every 4th beat (0, 4, 8, ...)
    as downbeat so the game always has strong beats.
    First beat is always treated as a downbeat (song entry point).
    """
    tol = 0.08  # 80 ms tolerance for downbeat matching

    # Fallback: no model downbeats → index-based
    if not downbeat_times and beat_times:
        downbeat_times = [beat_times[i] for i in range(0, len(beat_times), 4)]

    # First beat = song entry point → always downbeat
    entry_time = beat_times[0] if beat_times else None

    result: list[float] = []
    for t, s in zip(beat_times, onset_strengths):
        is_downbeat = (
            (entry_time is not None and abs(t - entry_time) < 1e-6)
            or any(abs(t - db) <= tol for db in downbeat_times)
        )
        if is_downbeat:
            result.append(max(0.85, min(1.0, s)))
        else:
            result.append(min(0.75, s))
    return result


def _numpy_compat_shim() -> None:
    """
    Restore deprecated numpy scalar aliases removed in NumPy 1.24.
    Required for compiled madmom Cython extensions (.pyd) that still
    reference np.int, np.float, etc. at runtime.
    """
    import numpy as np
    _aliases = {
        "int": np.int64, "float": np.float64, "bool": np.bool_,
        "complex": np.complex128, "object": object, "str": str,
    }
    for name, alias in _aliases.items():
        if not hasattr(np, name):
            setattr(np, name, alias)


def _analyze_with_tcn(path: str) -> tuple[tuple[BeatEvent, ...], float] | None:
    """
    Beat tracking via real TCN model (Davies & Böck, EUSIPCO 2019).

    Architecture: CNN front-end (mel-spectrogram) → 11-layer dilated TCN
    (dilation = 2^i, i=0..10) → DBN post-processor.
    F-measure ~91% on standard benchmarks.

    Pre-trained weights: beat_tracking_tcn/checkpoints/default_checkpoint.torch
    Source: https://github.com/ben-hayes/beat-tracking-tcn

    Returns (events, tempo_bpm) or None on any failure.
    """
    try:
        import librosa
        import numpy as np

        _numpy_compat_shim()

        from beat_tracking_tcn.beat_tracker import beatTracker

        # beatTracker returns (beat_times, downbeat_times) in seconds
        beat_times_arr, downbeat_times_arr = beatTracker(path, downbeats=True)
        beat_times: list[float] = list(beat_times_arr)
        downbeat_times: list[float] = list(downbeat_times_arr)

        if not beat_times:
            return None

        y, sr = librosa.load(path, sr=None, mono=True)
        music_start = _music_start_time(y, sr)
        beat_times = [t for t in beat_times if t >= music_start]
        downbeat_times = [t for t in downbeat_times if t >= music_start]
        if not beat_times:
            return None

        onset_s = _onset_strengths(y, sr, beat_times)
        strengths = _meter_strengths(beat_times, downbeat_times, onset_s)

        ibi = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 60.0 / DEFAULT_BPM
        tempo = 60.0 / ibi if ibi > 0 else float(DEFAULT_BPM)

        events = tuple(
            BeatEvent(timestamp=t, strength=s, index=i)
            for i, (t, s) in enumerate(zip(beat_times, strengths))
        )
        return events, tempo

    except Exception:
        return None


def _analyze_with_madmom(path: str) -> tuple[tuple[BeatEvent, ...], float] | None:
    """
    Beat tracking via madmom RNN+DBN pipeline (Böck et al.).

    Uses Bi-LSTM RNNBeatProcessor (the baseline TCN paper compares against).
    F-measure ~88% on standard benchmarks.

    Returns (events, tempo_bpm) or None on any failure.
    """
    try:
        import librosa
        import numpy as np

        _numpy_compat_shim()

        from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

        # Try downbeat-aware tracking first (returns [[time, beat_pos], ...])
        try:
            db_act = RNNDownBeatProcessor()(path)
            db_proc = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
            db_result = db_proc(db_act)
            beat_times = [float(row[0]) for row in db_result]
            downbeat_times = [float(row[0]) for row in db_result if int(row[1]) == 1]
        except Exception:
            # Fallback: plain beat tracking, estimate downbeats from meter
            act = RNNBeatProcessor()(path)
            beat_times = list(DBNBeatTrackingProcessor(fps=100)(act))
            downbeat_times = [t for i, t in enumerate(beat_times) if i % 4 == 0]

        if not beat_times:
            return None

        y, sr = librosa.load(path, sr=None, mono=True)
        music_start = _music_start_time(y, sr)
        beat_times = [t for t in beat_times if t >= music_start]
        downbeat_times = [t for t in downbeat_times if t >= music_start]
        if not beat_times:
            return None

        onset_s = _onset_strengths(y, sr, beat_times)
        strengths = _meter_strengths(beat_times, downbeat_times, onset_s)

        # Estimate tempo from median inter-beat interval
        ibi = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 60.0 / DEFAULT_BPM
        tempo = 60.0 / ibi if ibi > 0 else float(DEFAULT_BPM)

        events = tuple(
            BeatEvent(timestamp=t, strength=s, index=i)
            for i, (t, s) in enumerate(zip(beat_times, strengths))
        )
        return events, tempo

    except Exception:
        return None


def _analyze_with_librosa(path: str) -> tuple[tuple[BeatEvent, ...], float, float] | None:
    """
    Fallback beat tracking via librosa (Ellis 2007 dynamic-programming).
    Returns (events, tempo, duration) or None on failure.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(path, sr=None, mono=True)
        duration = float(librosa.get_duration(y=y, sr=sr))
        if duration <= 0:
            return None

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, units="frames")
        tempo_value = float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else float(DEFAULT_BPM)

        if len(beat_frames) == 0:
            beat_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="frames")

        times = librosa.frames_to_time(beat_frames, sr=sr)
        if len(times) == 0:
            return None

        music_start = _music_start_time(y, sr)
        # Filter silence and re-index
        valid = [(i, float(t)) for i, t in enumerate(times) if float(t) >= music_start]
        if not valid:
            return None
        orig_indices, beat_times_list = zip(*valid)
        beat_times_list = list(beat_times_list)
        valid_frames = beat_frames[[i for i in orig_indices]]

        frame_strengths = onset_env[valid_frames]
        onset_s = _normalize_strengths([float(v) for v in frame_strengths])
        downbeat_times = [t for i, t in enumerate(beat_times_list) if i % 4 == 0]
        strengths = _meter_strengths(beat_times_list, downbeat_times, onset_s)

        events = tuple(
            BeatEvent(timestamp=t, strength=s, index=i)
            for i, (t, s) in enumerate(zip(beat_times_list, strengths))
        )
        return events, tempo_value, duration

    except Exception:
        return None


def analyze_music(path: str) -> MusicAnalysis:
    try:
        import librosa
    except ModuleNotFoundError as exc:
        raise RuntimeError("librosa and numpy are required for music analysis") from exc

    music_path = Path(path)

    import librosa as _librosa
    y_meta, sr_meta = _librosa.load(str(music_path), sr=None, mono=True)
    duration = float(_librosa.get_duration(y=y_meta, sr=sr_meta))
    if duration <= 0:
        raise RuntimeError("music file has no playable duration")

    # --- Primary: real TCN model (Davies & Böck, EUSIPCO 2019) ---
    tcn_result = _analyze_with_tcn(str(music_path))
    if tcn_result is not None:
        events, tempo = tcn_result
        if events:
            return MusicAnalysis(
                path=str(music_path),
                title=music_path.stem,
                duration=duration,
                tempo=tempo,
                events=events,
                backend="tcn-dbn",
            )

    # --- Secondary: madmom RNN+DBN pipeline (Böck et al., TCN paper baseline) ---
    madmom_result = _analyze_with_madmom(str(music_path))
    if madmom_result is not None:
        events, tempo = madmom_result
        if events:
            return MusicAnalysis(
                path=str(music_path),
                title=music_path.stem,
                duration=duration,
                tempo=tempo,
                events=events,
                backend="madmom-dbn",
            )

    # --- Fallback: librosa dynamic-programming beat tracker ---
    librosa_result = _analyze_with_librosa(str(music_path))
    if librosa_result is not None:
        events, tempo, _ = librosa_result
        if events:
            return MusicAnalysis(
                path=str(music_path),
                title=music_path.stem,
                duration=duration,
                tempo=tempo,
                events=events,
                backend="librosa-dp",
            )

    # --- Last resort: metronome at default BPM ---
    return MusicAnalysis(
        path=str(music_path),
        title=music_path.stem,
        duration=duration,
        tempo=float(DEFAULT_BPM),
        events=default_events(duration=duration, bpm=DEFAULT_BPM),
        backend="default",
    )


class RhythmSpawner:
    def __init__(
        self,
        events: tuple[BeatEvent, ...],
        lead_time: float = SPAWN_LEAD_TIME,
        speed_multiplier: float = 1.0,
        seed: int | None = None,
    ) -> None:
        self.events = tuple(sorted(events, key=lambda event: event.timestamp))
        self.lead_time = lead_time
        self.speed_multiplier = max(0.05, speed_multiplier)
        self._next_index = 0
        self._rng = random.Random(seed)

    def reset(self) -> None:
        self._next_index = 0

    @property
    def done(self) -> bool:
        return self._next_index >= len(self.events)

    def due_rocks(
        self,
        game_time: float,
        width: int,
        height: int,
        next_rock_id: int,
    ) -> tuple[list[Rock], int]:
        rocks: list[Rock] = []
        while self._next_index < len(self.events):
            event = self.events[self._next_index]
            if event.timestamp - self.lead_time > game_time:
                break
            event_rocks = self._build_rocks(event, game_time, width, height, next_rock_id)
            rocks.extend(event_rocks)
            next_rock_id += len(event_rocks)
            self._next_index += 1
        return rocks, next_rock_id

    def _build_rocks(
        self,
        event: BeatEvent,
        game_time: float,
        width: int,
        height: int,
        next_rock_id: int,
    ) -> list[Rock]:
        count = 2 if event.strength >= 0.84 else 1
        event_speed_multiplier = self._event_speed_multiplier(event)
        rocks: list[Rock] = []
        for offset in range(count):
            spec = self._rng.choice(ROCK_TYPES)
            radius = float(spec["radius"]) * (0.92 + event.strength * 0.22)
            target_x = self._lane_x(width, event.index + offset * 2)
            target_y = height * HIT_LINE_Y_RATIO + self._rng.uniform(-76, 76)
            start_x = target_x + self._rng.uniform(-110, 110)
            start_y = -radius - self._rng.uniform(20, 120)
            flight_time = max(0.72, event.timestamp - game_time)

            vx = (target_x - start_x) / flight_time
            gravity = GRAVITY * event_speed_multiplier
            vy = (target_y - start_y - 0.5 * gravity * flight_time * flight_time) / flight_time
            if not math.isfinite(vy):
                vy = 0.0

            rocks.append(
                Rock(
                    rock_id=next_rock_id + offset,
                    kind=str(spec["name"]),
                    x=start_x,
                    y=start_y,
                    vx=vx,
                    vy=vy,
                    radius=radius,
                    color=spec["color"],
                    accent=spec["accent"],
                    target_time=event.timestamp,
                    strength=event.strength,
                    gravity_scale=event_speed_multiplier,
                    spin=self._rng.uniform(-4.2, 4.2),
                )
            )
        return rocks

    def _event_speed_multiplier(self, event: BeatEvent) -> float:
        strength = max(0.0, min(1.0, event.strength))
        beat_speed_scale = ROCK_BEAT_SPEED_MIN + (ROCK_BEAT_SPEED_MAX - ROCK_BEAT_SPEED_MIN) * strength
        return max(0.05, self.speed_multiplier * beat_speed_scale)

    def _lane_x(self, width: int, index: int) -> float:
        lane_count = 7
        lane = index % lane_count
        lane_width = width / (lane_count + 1)
        return lane_width * (lane + 1) + self._rng.uniform(-34, 34)
