#!/usr/bin/env python3
"""Pro-grade stick drift compensation engine.

This module provides a stateful compensation pipeline with:
- adaptive center tracking
- elliptical deadzone removal
- anti-deadzone injection
- response curve shaping
- temporal smoothing
- rolling drift/jitter/suppression metrics
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Tuple


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def percentile(values: Iterable[float], p: float) -> float:
    array = sorted(float(v) for v in values)
    if not array:
        return 0.0

    index = (len(array) - 1) * clamp(p, 0.0, 1.0)
    low_index = int(math.floor(index))
    high_index = int(math.ceil(index))
    if low_index == high_index:
        return array[low_index]

    low = array[low_index]
    high = array[high_index]
    frac = index - low_index
    return low + (high - low) * frac


@dataclass
class StickRuntimeConfig:
    center_x: float
    center_y: float
    deadzone_x: float
    deadzone_y: float
    auto_deadzone: bool = True
    manual_deadzone_x: float = 0.08
    manual_deadzone_y: float = 0.08
    anti_deadzone: float = 0.02
    response_gamma: float = 1.0
    smoothing: float = 0.35
    adaptive_center: bool = True
    adaptive_learning_rate: float = 0.015
    adaptive_limit: float = 0.14
    neutral_capture_radius: float = 0.24

    def resolved_deadzone(self) -> Tuple[float, float]:
        if self.auto_deadzone:
            return (
                clamp(self.deadzone_x, 0.01, 0.60),
                clamp(self.deadzone_y, 0.01, 0.60),
            )
        return (
            clamp(self.manual_deadzone_x, 0.01, 0.60),
            clamp(self.manual_deadzone_y, 0.01, 0.60),
        )


@dataclass
class StickMetrics:
    drift_index: float = 0.0
    jitter_index: float = 0.0
    suppression: float = 0.0
    neutral_p95: float = 0.0
    corrected_p95: float = 0.0
    adaptive_x: float = 0.0
    adaptive_y: float = 0.0


@dataclass
class StickProcessed:
    raw: Tuple[float, float]
    centered_raw: Tuple[float, float]
    corrected: Tuple[float, float]
    metrics: StickMetrics
    deadzone_x: float
    deadzone_y: float
    effective_center_x: float
    effective_center_y: float


@dataclass
class _StickState:
    adaptive_x: float = 0.0
    adaptive_y: float = 0.0
    prev_out_x: float = 0.0
    prev_out_y: float = 0.0
    history_raw_neutral: Deque[float] = field(default_factory=lambda: deque(maxlen=240))
    history_out_neutral: Deque[float] = field(default_factory=lambda: deque(maxlen=240))
    history_out_delta: Deque[float] = field(default_factory=lambda: deque(maxlen=240))


class StickProcessor:
    def __init__(self) -> None:
        self.state = _StickState()

    def reset(self) -> None:
        self.state = _StickState()

    def process(self, raw: Tuple[float, float], config: StickRuntimeConfig, dt: float) -> StickProcessed:
        dt = clamp(float(dt), 1 / 500.0, 0.25)

        deadzone_x, deadzone_y = config.resolved_deadzone()

        effective_center_x = config.center_x + self.state.adaptive_x
        effective_center_y = config.center_y + self.state.adaptive_y

        centered_x = raw[0] - effective_center_x
        centered_y = raw[1] - effective_center_y
        centered_mag = math.hypot(centered_x, centered_y)

        if config.adaptive_center and centered_mag <= config.neutral_capture_radius:
            # Make center tracking framerate-stable.
            frame_rate_scale = dt / (1 / 60.0)
            alpha = clamp(config.adaptive_learning_rate * frame_rate_scale, 0.0005, 0.20)

            target_adaptive_x = raw[0] - config.center_x
            target_adaptive_y = raw[1] - config.center_y

            self.state.adaptive_x += alpha * (target_adaptive_x - self.state.adaptive_x)
            self.state.adaptive_y += alpha * (target_adaptive_y - self.state.adaptive_y)

            limit = clamp(config.adaptive_limit, 0.01, 0.35)
            self.state.adaptive_x = clamp(self.state.adaptive_x, -limit, limit)
            self.state.adaptive_y = clamp(self.state.adaptive_y, -limit, limit)

            effective_center_x = config.center_x + self.state.adaptive_x
            effective_center_y = config.center_y + self.state.adaptive_y
            centered_x = raw[0] - effective_center_x
            centered_y = raw[1] - effective_center_y
            centered_mag = math.hypot(centered_x, centered_y)

        shaped_x, shaped_y = self._apply_elliptical_deadzone(
            centered_x,
            centered_y,
            deadzone_x,
            deadzone_y,
            anti_deadzone=clamp(config.anti_deadzone, 0.0, 0.30),
            gamma=clamp(config.response_gamma, 0.35, 2.5),
        )

        # Exponential smoothing: higher smoothing value -> stronger filtering.
        alpha = clamp(1.0 - config.smoothing, 0.03, 1.0)
        out_x = self.state.prev_out_x + alpha * (shaped_x - self.state.prev_out_x)
        out_y = self.state.prev_out_y + alpha * (shaped_y - self.state.prev_out_y)

        delta = math.hypot(out_x - self.state.prev_out_x, out_y - self.state.prev_out_y)

        self.state.prev_out_x = out_x
        self.state.prev_out_y = out_y

        out_mag = math.hypot(out_x, out_y)

        if centered_mag <= config.neutral_capture_radius:
            self.state.history_raw_neutral.append(centered_mag)
            self.state.history_out_neutral.append(out_mag)
        self.state.history_out_delta.append(delta)

        metrics = self._build_metrics()

        return StickProcessed(
            raw=raw,
            centered_raw=(centered_x, centered_y),
            corrected=(out_x, out_y),
            metrics=metrics,
            deadzone_x=deadzone_x,
            deadzone_y=deadzone_y,
            effective_center_x=effective_center_x,
            effective_center_y=effective_center_y,
        )

    def _build_metrics(self) -> StickMetrics:
        raw_neutral = list(self.state.history_raw_neutral)
        out_neutral = list(self.state.history_out_neutral)
        deltas = list(self.state.history_out_delta)

        raw_mean = statistics.fmean(raw_neutral) if raw_neutral else 0.0
        out_mean = statistics.fmean(out_neutral) if out_neutral else 0.0

        if raw_mean > 1e-6:
            suppression = clamp(1.0 - (out_mean / raw_mean), 0.0, 1.0) * 100.0
        else:
            suppression = 100.0 if out_mean == 0.0 else 0.0

        jitter = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
        drift = out_mean

        return StickMetrics(
            drift_index=drift * 100.0,
            jitter_index=jitter * 100.0,
            suppression=suppression,
            neutral_p95=percentile(raw_neutral, 0.95) * 100.0,
            corrected_p95=percentile(out_neutral, 0.95) * 100.0,
            adaptive_x=self.state.adaptive_x,
            adaptive_y=self.state.adaptive_y,
        )

    def _apply_elliptical_deadzone(
        self,
        x: float,
        y: float,
        deadzone_x: float,
        deadzone_y: float,
        anti_deadzone: float,
        gamma: float,
    ) -> Tuple[float, float]:
        magnitude = math.hypot(x, y)
        if magnitude <= 1e-9:
            return 0.0, 0.0

        ux = x / magnitude
        uy = y / magnitude

        dx = clamp(deadzone_x, 0.001, 0.95)
        dy = clamp(deadzone_y, 0.001, 0.95)

        boundary = 1.0 / math.sqrt((ux * ux) / (dx * dx) + (uy * uy) / (dy * dy))
        boundary = clamp(boundary, 0.0, 0.95)

        if magnitude <= boundary:
            return 0.0, 0.0

        normalized = (magnitude - boundary) / max(1e-6, 1.0 - boundary)
        normalized = clamp(normalized, 0.0, 1.0)

        if normalized > 0.0 and anti_deadzone > 0.0:
            normalized = anti_deadzone + normalized * (1.0 - anti_deadzone)

        normalized = normalized ** gamma
        normalized = clamp(normalized, 0.0, 1.0)

        return ux * normalized, uy * normalized


class DriftCompensator:
    def __init__(self) -> None:
        self.left = StickProcessor()
        self.right = StickProcessor()

    def reset(self) -> None:
        self.left.reset()
        self.right.reset()

    def process_pair(
        self,
        raw_left: Tuple[float, float],
        raw_right: Tuple[float, float],
        left_config: StickRuntimeConfig,
        right_config: StickRuntimeConfig,
        dt: float,
    ) -> Tuple[StickProcessed, StickProcessed]:
        return (
            self.left.process(raw_left, left_config, dt),
            self.right.process(raw_right, right_config, dt),
        )
