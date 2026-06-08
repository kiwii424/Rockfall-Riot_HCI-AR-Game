from __future__ import annotations

from dataclasses import dataclass

import pygame

from .config import (
    ACCENT_COLOR,
    BACKGROUND_COLOR,
    FEVER_COLOR,
    MUTED_TEXT_COLOR,
    PANEL_COLOR,
    TEXT_COLOR,
)


@dataclass(frozen=True)
class Button:
    rect: pygame.Rect
    label: str
    action: str

    def draw(self, surface, font, active: bool = True) -> None:
        bg = ACCENT_COLOR if active else (74, 86, 101)
        fg = (7, 16, 24) if active else (200, 207, 216)
        pygame.draw.rect(surface, bg, self.rect, border_radius=8)
        pygame.draw.rect(surface, (255, 255, 255), self.rect, 2, border_radius=8)
        text = font.render(self.label, True, fg)
        surface.blit(text, text.get_rect(center=self.rect.center))


def draw_text(
    surface,
    text: str,
    font,
    color: tuple[int, int, int],
    position: tuple[int, int],
    anchor: str = "topleft",
) -> pygame.Rect:
    rendered = font.render(text, True, color)
    rect = rendered.get_rect()
    setattr(rect, anchor, position)
    surface.blit(rendered, rect)
    return rect


def draw_dim_overlay(surface, alpha: int = 150) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, alpha))
    surface.blit(overlay, (0, 0))


def draw_gauge(
    surface,
    rect: pygame.Rect,
    value: float,
    fill_color: tuple[int, int, int] = FEVER_COLOR,
    label: str = "",
    font=None,
) -> None:
    value = max(0.0, min(1.0, value))
    pygame.draw.rect(surface, (35, 44, 58), rect, border_radius=6)
    fill_rect = pygame.Rect(rect.x, rect.y, int(rect.width * value), rect.height)
    pygame.draw.rect(surface, fill_color, fill_rect, border_radius=6)
    pygame.draw.rect(surface, (234, 240, 248), rect, 2, border_radius=6)
    if label and font is not None:
        draw_text(surface, label, font, TEXT_COLOR, rect.center, "center")


def draw_camera_placeholder(surface, font, status: str) -> None:
    surface.fill(BACKGROUND_COLOR)
    width, height = surface.get_size()
    for x in range(0, width, 64):
        pygame.draw.line(surface, (20, 30, 42), (x, 0), (x, height), 1)
    for y in range(0, height, 64):
        pygame.draw.line(surface, (20, 30, 42), (0, y), (width, y), 1)
    pygame.draw.circle(surface, (28, 39, 54), (width // 2, height // 2), 118, 3)
    draw_text(surface, status, font, MUTED_TEXT_COLOR, (width // 2, height // 2), "center")


def draw_hud(
    surface,
    fonts,
    score,
    game_time: float,
    duration: float,
    fever_timer: float,
    cooldown: float,
    title: str,
    beat_index: int = -1,
    beat_strength: float = 0.0,
    beat_pulse: float = 0.0,
) -> None:
    width, _ = surface.get_size()
    bar = pygame.Rect(0, 0, width, 72)
    hud = pygame.Surface((width, 72), pygame.SRCALPHA)
    hud.fill((10, 16, 24, 182))
    surface.blit(hud, bar)

    draw_text(surface, f"Score {score.score}", fonts["medium"], TEXT_COLOR, (24, 18))
    draw_text(surface, f"Combo {score.combo}", fonts["medium"], TEXT_COLOR, (214, 18))
    draw_text(surface, f"Miss {score.misses}", fonts["medium"], TEXT_COLOR, (392, 18))

    remaining = max(0, int(duration - game_time))
    draw_text(surface, f"{remaining:02d}s", fonts["medium"], TEXT_COLOR, (width - 174, 18))

    gauge_label = "FEVER" if fever_timer <= 0 else f"FEVER {fever_timer:.1f}"
    gauge_color = FEVER_COLOR if cooldown <= 0 else (128, 137, 148)
    draw_gauge(surface, pygame.Rect(width - 356, 20, 144, 24), score.fever_gauge, gauge_color, gauge_label, fonts["small"])

    clipped_title = title if len(title) <= 28 else title[:25] + "..."
    draw_text(surface, clipped_title, fonts["small"], MUTED_TEXT_COLOR, (572, 25))

    if beat_index >= 0:
        strong = beat_strength >= 0.84
        base_color = FEVER_COLOR if strong else ACCENT_COLOR
        alpha = int(60 + beat_pulse * 120)
        dot_surf = pygame.Surface((14, 14), pygame.SRCALPHA)
        pygame.draw.circle(dot_surf, (*base_color, alpha), (7, 7), 7)
        surface.blit(dot_surf, (width - 124, 28))
        label = f"B{beat_index + 1} {'●' if strong else '○'}"
        draw_text(surface, label, fonts["small"], base_color, (width - 108, 26))


def draw_screen_panel(surface, fonts, title: str, subtitle: str, buttons: list[Button]) -> None:
    draw_dim_overlay(surface, 170)
    width, height = surface.get_size()
    panel_rect = pygame.Rect(0, 0, 560, 360)
    panel_rect.center = (width // 2, height // 2)
    pygame.draw.rect(surface, PANEL_COLOR, panel_rect, border_radius=8)
    pygame.draw.rect(surface, (255, 255, 255), panel_rect, 2, border_radius=8)
    draw_text(surface, title, fonts["title"], TEXT_COLOR, (width // 2, panel_rect.y + 58), "center")
    if subtitle:
        draw_text(surface, subtitle, fonts["medium"], MUTED_TEXT_COLOR, (width // 2, panel_rect.y + 116), "center")
    for button in buttons:
        button.draw(surface, fonts["button"])
