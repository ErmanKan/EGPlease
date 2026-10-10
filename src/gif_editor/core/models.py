"""Immutable edit model. `EditState` is the single source of truth for every user edit."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any, ClassVar

MAX_FPS = 50.0
MIN_SPEED = 0.25
MAX_SPEED = 4.0


@dataclass(frozen=True, slots=True)
class CropRect:
    """Crop rectangle in source-canvas pixels."""

    x: int
    y: int
    w: int
    h: int

    def validate(self, canvas_w: int, canvas_h: int) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"crop size must be positive, got {self.w}x{self.h}")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"crop origin must be >= 0, got ({self.x}, {self.y})")
        if self.x + self.w > canvas_w or self.y + self.h > canvas_h:
            raise ValueError(f"crop {self} exceeds canvas {canvas_w}x{canvas_h}")


@dataclass(frozen=True, slots=True)
class OutputSize:
    """Final output size in pixels (applied after crop)."""

    width: int
    height: int

    def validate(self) -> None:
        if not (1 <= self.width <= 8192 and 1 <= self.height <= 8192):
            raise ValueError(f"output size must be 1..8192, got {self.width}x{self.height}")


@dataclass(frozen=True, slots=True)
class Quality:
    colors: int = 256
    dither: bool = True

    PRESETS: ClassVar[dict[str, tuple[int, bool]]] = {
        "high": (256, True),
        "medium": (128, True),
        "low": (64, False),
    }

    @classmethod
    def preset(cls, name: str) -> Quality:
        colors, dither = cls.PRESETS[name]
        return cls(colors, dither)

    def validate(self) -> None:
        if not 2 <= self.colors <= 256:
            raise ValueError(f"colors must be 2..256, got {self.colors}")


@dataclass(frozen=True, slots=True)
class EditState:
    trim_start_ms: int = 0
    trim_duration_ms: int | None = None  # None = until the end
    deleted: frozenset[int] = field(default_factory=frozenset)
    crop: CropRect | None = None
    speed: float = 1.0
    fps: float | None = None  # None = keep source timing
    size: OutputSize | None = None  # None = crop size (or canvas size)
    quality: Quality = field(default_factory=Quality)

    def with_(self, **changes: Any) -> EditState:
        """Return a copy with `changes` applied; validates field-level constraints."""
        names = {f.name for f in fields(self)}
        unknown = set(changes) - names
        if unknown:
            raise TypeError(f"unknown EditState fields: {sorted(unknown)}")
        if "deleted" in changes:
            changes["deleted"] = frozenset(changes["deleted"])
        new = replace(self, **changes)
        new._validate_fields()
        return new

    def _validate_fields(self) -> None:
        if self.trim_start_ms < 0:
            raise ValueError("trim_start_ms must be >= 0")
        if self.trim_duration_ms is not None and self.trim_duration_ms <= 0:
            raise ValueError("trim_duration_ms must be > 0 or None")
        if not MIN_SPEED <= self.speed <= MAX_SPEED:
            raise ValueError(f"speed must be {MIN_SPEED}..{MAX_SPEED}, got {self.speed}")
        if self.fps is not None and not 0 < self.fps <= MAX_FPS:
            raise ValueError(f"fps must be in (0, {MAX_FPS}], got {self.fps}")
        if any(i < 0 for i in self.deleted):
            raise ValueError("deleted indices must be >= 0")
        if self.size is not None:
            self.size.validate()
        self.quality.validate()

    def validate(self, canvas_w: int, canvas_h: int, frame_count: int) -> None:
        """Full validation against a loaded source."""
        self._validate_fields()
        if self.crop is not None:
            self.crop.validate(canvas_w, canvas_h)
        bad = [i for i in self.deleted if i >= frame_count]
        if bad:
            raise ValueError(f"deleted indices out of range: {sorted(bad)[:5]}")
