"""
Beat analysis visualizer.

Usage:
    python scripts/test_beats.py [music_file]

If no file given, opens a file dialog.
Shows a full-screen flash on each detected beat (strong = bright),
plays the audio, and prints tempo / backend / accuracy info.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.rhythm import analyze_music, default_analysis


WIDTH, HEIGHT = 900, 360
FPS = 60
BEAT_FLASH_DECAY = 0.18  # seconds to fade out


def pick_file(arg: str | None) -> str | None:
    if arg:
        return arg
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.update()
        path = filedialog.askopenfilename(
            title="Choose music file",
            filetypes=(("Audio", "*.mp3 *.wav *.ogg *.flac *.m4a"), ("All", "*.*")),
        )
        root.destroy()
        return path or None
    except Exception:
        print("No file given and tkinter unavailable.")
        return None


def run(path: str) -> None:
    import pygame

    print(f"\nAnalyzing: {path}")
    t0 = time.perf_counter()
    analysis = analyze_music(path)
    elapsed = time.perf_counter() - t0

    strong_beats = [e for e in analysis.events if e.strength >= 0.84]
    weak_beats   = [e for e in analysis.events if e.strength <  0.84]
    first_ts = analysis.events[0].timestamp if analysis.events else 0.0

    print(f"  Backend : {analysis.backend}")
    print(f"  Tempo   : {analysis.tempo:.1f} BPM")
    print(f"  Duration: {analysis.duration:.1f}s")
    print(f"  Entry pt: {first_ts:.3f}s  (first musical beat)")
    print(f"  Beats   : {len(analysis.events)}  (strong={len(strong_beats)} weak={len(weak_beats)})")
    print(f"  Analysis time: {elapsed:.2f}s")
    print()
    print("  Beat list (first 20):")
    for ev in analysis.events[:20]:
        tag = "STRONG ●" if ev.strength >= 0.84 else "weak   ○"
        print(f"    [{ev.index:3d}] t={ev.timestamp:.3f}s  s={ev.strength:.3f}  {tag}")
    print("\nControls: Space = pause/resume  |  Esc = quit\n")

    pygame.init()
    try:
        pygame.mixer.init()
        audio_ok = True
    except pygame.error:
        audio_ok = False

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Beat Test — {analysis.title}")
    clock = pygame.time.Clock()
    font_large = pygame.font.SysFont("arial", 52, bold=True)
    font_med   = pygame.font.SysFont("arial", 26, bold=True)
    font_small = pygame.font.SysFont("arial", 18)

    if audio_ok and analysis.path:
        try:
            pygame.mixer.music.load(analysis.path)
        except pygame.error as exc:
            print(f"Audio load failed: {exc}")
            audio_ok = False

    events = analysis.events
    beat_idx = 0          # next beat to trigger
    flash = 0.0           # current flash brightness [0,1]
    flash_strength = 0.0
    game_time = 0.0
    paused = False
    started = False

    def start_playback():
        nonlocal started
        if audio_ok and analysis.path and not started:
            pygame.mixer.music.play()
        started = True

    start_playback()

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                    if audio_ok and analysis.path:
                        if paused:
                            pygame.mixer.music.pause()
                        else:
                            pygame.mixer.music.unpause()

        if not paused and started:
            game_time += dt

        # trigger beat flash
        while beat_idx < len(events) and events[beat_idx].timestamp <= game_time:
            flash = 1.0
            flash_strength = events[beat_idx].strength
            beat_idx += 1

        flash = max(0.0, flash - dt / BEAT_FLASH_DECAY)

        # ── draw ──────────────────────────────────────────────────────────
        bg = (11, 17, 25)
        screen.fill(bg)

        # beat flash overlay
        if flash > 0:
            strong = flash_strength >= 0.84
            color = (255, 211, 77) if strong else (54, 210, 255)
            alpha = int(flash * 180)
            surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            surf.fill((*color, alpha))
            screen.blit(surf, (0, 0))

        # beat index & strength
        current_beat = beat_idx - 1
        if 0 <= current_beat < len(events):
            ev = events[current_beat]
            beat_text = font_large.render(f"Beat {ev.index + 1}", True, (245, 248, 252))
            screen.blit(beat_text, beat_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30)))
            strength_text = font_med.render(
                f"strength {ev.strength:.2f}  {'STRONG' if ev.strength >= 0.84 else 'weak'}",
                True,
                (255, 211, 77) if ev.strength >= 0.84 else (54, 210, 255),
            )
            screen.blit(strength_text, strength_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 26)))
        else:
            waiting = font_large.render("Waiting...", True, (162, 174, 190))
            screen.blit(waiting, waiting.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 10)))

        # timeline bar
        bar_x, bar_y, bar_w, bar_h = 40, HEIGHT - 60, WIDTH - 80, 14
        pygame.draw.rect(screen, (35, 45, 58), (bar_x, bar_y, bar_w, bar_h), border_radius=7)
        progress = min(1.0, game_time / max(1.0, analysis.duration))
        pygame.draw.rect(screen, (54, 210, 255), (bar_x, bar_y, int(bar_w * progress), bar_h), border_radius=7)

        # beat markers on timeline
        for ev in events:
            mx = bar_x + int(bar_w * ev.timestamp / max(1.0, analysis.duration))
            color = (255, 211, 77) if ev.strength >= 0.84 else (120, 140, 160)
            pygame.draw.line(screen, color, (mx, bar_y - 2), (mx, bar_y + bar_h + 2), 1)

        # time / next beat
        next_beat_time = events[beat_idx].timestamp if beat_idx < len(events) else None
        time_str = f"{game_time:.2f}s / {analysis.duration:.1f}s"
        next_str = f"next beat: {next_beat_time:.3f}s  (in {next_beat_time - game_time:.3f}s)" if next_beat_time else "end"
        screen.blit(font_small.render(time_str, True, (162, 174, 190)), (bar_x, bar_y - 22))
        screen.blit(font_small.render(next_str, True, (162, 174, 190)), (bar_x + 280, bar_y - 22))

        # header
        header = f"{analysis.title}  |  {analysis.tempo:.1f} BPM  |  {analysis.backend}  |  {len(events)} beats"
        screen.blit(font_small.render(header, True, (205, 216, 228)), (40, 18))
        if paused:
            screen.blit(font_med.render("PAUSED", True, (255, 211, 77)), (WIDTH // 2 - 40, 16))

        pygame.display.flip()

        if game_time > analysis.duration + 1.0:
            running = False

    pygame.quit()


def main() -> None:
    path = pick_file(sys.argv[1] if len(sys.argv) > 1 else None)
    if not path:
        print("No file selected.")
        return
    run(path)


if __name__ == "__main__":
    main()
