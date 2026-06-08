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


def _music_end_time(y, sr) -> float:
    """Return timestamp where audio content ends (skip trailing silence)."""
    import librosa
    _, trim_indices = librosa.effects.trim(y, top_db=28)
    end_sample = int(trim_indices[1])
    total = len(y)
    return float(end_sample / sr) if end_sample < total else float(total / sr)


def _snap_to_grid(beat_times: list[float], true_ibi: float) -> list[float]:
    """
    Select TCN beats that align with a regular grid spaced true_ibi apart.
    Builds grid from beat_times[0], advances one true_ibi at a time,
    snaps each grid position to the nearest TCN beat (within true_ibi/2).
    Removes duplicates while preserving TCN's timing precision.
    """
    if not beat_times or true_ibi <= 0:
        return beat_times
    t = beat_times[0]
    t_end = beat_times[-1]
    result: list[float] = []
    seen: set[float] = set()
    while t <= t_end + true_ibi * 0.5:
        closest = min(beat_times, key=lambda bt: abs(bt - t))
        if abs(closest - t) <= true_ibi * 0.5 and closest not in seen:
            result.append(closest)
            seen.add(closest)
            t = closest  # follow actual timing
        t += true_ibi
    return result


def _thin_double_tempo(
    beat_times: list[float],
    onset_strengths: list[float],
    beats_per_bar: int,
) -> tuple[list[float], list[float], int]:
    """
    When TCN runs at 2x tempo (beats_per_bar 6 or 8), halve the beat list.
    Try both even/odd alternations; keep whichever has higher total onset energy.
    """
    if beats_per_bar not in (6, 8) or len(beat_times) < 2:
        return beat_times, onset_strengths, beats_per_bar

    even = list(zip(beat_times[::2], onset_strengths[::2]))
    odd  = list(zip(beat_times[1::2], onset_strengths[1::2]))
    score_even = sum(s for _, s in even)
    score_odd  = sum(s for _, s in odd)
    chosen = even if score_even >= score_odd else odd
    t_out, s_out = zip(*chosen) if chosen else ([], [])
    return list(t_out), list(s_out), beats_per_bar // 2


def _infer_downbeats(
    beat_times: list[float],
    tcn_downbeats: list[float],
    onset_strengths: list[float],
    ibi: float,
) -> list[float]:
    """
    Infer downbeat positions by brute-forcing all phase offsets and picking the
    phase whose inferred downbeats have the highest total onset energy.

    TCN downbeats are only used to determine beats_per_bar (3/4 or 4/4,
    plus double-tempo variants 6/8); their exact positions are NOT trusted.
    """
    import numpy as np

    if not beat_times or ibi <= 0:
        return []

    strength_map = dict(zip(beat_times, onset_strengths))

    # --- 1. Determine beats_per_bar from TCN downbeat spacing ---
    if len(tcn_downbeats) >= 2:
        db_intervals = [tcn_downbeats[i + 1] - tcn_downbeats[i]
                        for i in range(len(tcn_downbeats) - 1)]
        avg_db_interval = float(np.median(db_intervals))
        candidates = [3, 4]
        beats_per_bar = min(candidates, key=lambda n: abs(avg_db_interval - n * ibi))
    else:
        beats_per_bar = 4

    bar_duration = ibi * beats_per_bar
    t_start, t_end = beat_times[0], beat_times[-1]

    def _generate(anchor: float) -> list[float]:
        # Walk backwards to first bar
        t = anchor
        while t - bar_duration >= t_start - bar_duration * 0.1:
            t -= bar_duration

        result, seen = [], set()
        while t <= t_end + bar_duration * 0.5:
            if t >= t_start - bar_duration * 0.1:
                closest = min(beat_times, key=lambda bt: abs(bt - t))
                if abs(closest - t) <= ibi * 0.5 and closest not in seen:
                    result.append(closest)
                    seen.add(closest)
            t += bar_duration
        return sorted(result)

    # --- 2. Try each beat in first bar as phase anchor, score by onset energy ---
    best_score, best_downbeats = -1.0, []
    for phase_beat in beat_times[:beats_per_bar]:
        downbeats = _generate(phase_beat)
        score = sum(strength_map.get(db, 0.0) for db in downbeats)
        if score > best_score:
            best_score, best_downbeats = score, downbeats

    return best_downbeats


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

    result: list[float] = []
    for t, s in zip(beat_times, onset_strengths):
        is_downbeat = any(abs(t - db) <= tol for db in downbeat_times)
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
        music_end = _music_end_time(y, sr)
        beat_times = [t for t in beat_times if music_start <= t <= music_end]
        downbeat_times = [t for t in downbeat_times if music_start <= t <= music_end]
        if not beat_times:
            return None

        ibi = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 60.0 / DEFAULT_BPM

        # --- Correct double-tempo using librosa tempo as ground truth ---
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        lib_tempo_arr = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)
        lib_tempo = float(np.asarray(lib_tempo_arr).reshape(-1)[0])
        lib_ibi = 60.0 / lib_tempo if lib_tempo > 0 else ibi

        if ibi < lib_ibi * 0.65:
            # TCN running at ~2x tempo → snap TCN beats to librosa tempo grid
            beat_times = _snap_to_grid(beat_times, lib_ibi)
            ibi = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else lib_ibi

        onset_s = _onset_strengths(y, sr, beat_times)

        # Use librosa beat times to anchor downbeats — fixes TCN tempo drift
        _, lib_beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, units="frames")
        lib_beat_times = [float(t) for t in librosa.frames_to_time(lib_beat_frames, sr=sr)
                          if music_start <= float(t) <= music_end]
        lib_downbeats = [lib_beat_times[i] for i in range(0, len(lib_beat_times), 4)]

        # Snap each librosa downbeat to nearest TCN beat
        snapped_downbeats = []
        for ld in lib_downbeats:
            closest = min(beat_times, key=lambda bt: abs(bt - ld))
            if abs(closest - ld) <= ibi and closest not in snapped_downbeats:
                snapped_downbeats.append(closest)

        strengths = _meter_strengths(beat_times, snapped_downbeats, onset_s)
        tempo = 60.0 / lib_ibi if lib_ibi > 0 else float(DEFAULT_BPM)

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
        music_end = _music_end_time(y, sr)
        beat_times = [t for t in beat_times if music_start <= t <= music_end]
        downbeat_times = [t for t in downbeat_times if music_start <= t <= music_end]
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
        music_end = _music_end_time(y, sr)
        # Filter leading/trailing silence and re-index
        valid = [(i, float(t)) for i, t in enumerate(times) if music_start <= float(t) <= music_end]
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


def _apply_sidecar(events: tuple[BeatEvent, ...], strong_times: list[float]) -> tuple[BeatEvent, ...]:
    """
    Use sidecar tap timestamps as phase anchors to extrapolate all strong beats.
    If >= 2 taps: derive bar_duration from median tap interval, extrapolate full song.
    If 1 tap: mark only that beat as strong.
    """
    import numpy as np
    if not strong_times or not events:
        return events

    beat_times = [ev.timestamp for ev in events]
    tol = 0.15  # 150ms snap

    if len(strong_times) >= 2:
        st_sorted = sorted(strong_times)
        intervals = [st_sorted[i+1] - st_sorted[i] for i in range(len(st_sorted)-1)]
        bar_duration = float(np.median(intervals))
        anchor = st_sorted[0]
        t_start, t_end = beat_times[0], beat_times[-1]

        # Walk backwards from anchor
        t = anchor
        while t - bar_duration >= t_start - bar_duration * 0.1:
            t -= bar_duration

        # Generate from theoretical grid and snap each bar independently
        # Do NOT update t from snapped position — keeps librosa timing, no drift
        strong_set: set[float] = set()
        while t <= t_end + bar_duration * 0.5:
            if t >= t_start - bar_duration * 0.1:
                closest = min(beat_times, key=lambda bt: abs(bt - t))
                if abs(closest - t) <= bar_duration * 0.4:
                    strong_set.add(closest)
            t += bar_duration
    else:
        strong_set = set(strong_times)

    result = []
    for ev in events:
        is_strong = any(abs(ev.timestamp - st) <= tol for st in strong_set)
        if is_strong:
            result.append(BeatEvent(timestamp=ev.timestamp, strength=max(0.85, ev.strength), index=ev.index))
        else:
            result.append(BeatEvent(timestamp=ev.timestamp, strength=min(0.75, ev.strength), index=ev.index))
    return tuple(result)


def analyze_music(path: str, backend: str | None = None) -> MusicAnalysis:
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

    sidecar_times = _load_sidecar(music_path)

    def _make(events, tempo, backend_name):
        final_events = _apply_sidecar(events, sidecar_times) if sidecar_times else events
        return MusicAnalysis(
            path=str(music_path),
            title=music_path.stem,
            duration=duration,
            tempo=tempo,
            events=final_events,
            backend=backend_name + ("+sidecar" if sidecar_times else ""),
        )

    b = (backend or "").lower()

    # --- Primary: librosa dynamic-programming beat tracker ---
    if b in ("", "librosa"):
        librosa_result = _analyze_with_librosa(str(music_path))
        if librosa_result is not None:
            events, tempo, _ = librosa_result
            if events:
                return _make(events, tempo, "librosa-dp")
        if b == "librosa":
            raise RuntimeError("librosa backend failed")

    # --- Secondary: real TCN model (Davies & Böck, EUSIPCO 2019) ---
    if b in ("", "tcn"):
        tcn_result = _analyze_with_tcn(str(music_path))
        if tcn_result is not None:
            events, tempo = tcn_result
            if events:
                return _make(events, tempo, "tcn-dbn")
        if b == "tcn":
            raise RuntimeError("TCN backend failed or not installed")

    # --- Tertiary: madmom RNN+DBN pipeline ---
    if b in ("", "madmom"):
        madmom_result = _analyze_with_madmom(str(music_path))
        if madmom_result is not None:
            events, tempo = madmom_result
            if events:
                return _make(events, tempo, "madmom-dbn")
        if b == "madmom":
            raise RuntimeError("madmom backend failed or not installed")

    # --- Last resort: metronome at default BPM ---
    return _make(default_events(duration=duration, bpm=DEFAULT_BPM), float(DEFAULT_BPM), "default")


def _load_sidecar(music_path: Path) -> list[float] | None:
    import json as _json
    sidecar = music_path.with_suffix(".json")
    if sidecar.exists():
        try:
            data = _json.loads(sidecar.read_text())
            times = data.get("strong_beats", [])
            return [float(t) for t in times] if times else None
        except Exception:
            return None
    return None


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
