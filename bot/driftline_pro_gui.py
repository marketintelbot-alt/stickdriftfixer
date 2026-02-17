#!/usr/bin/env python3
"""Driftline Pro Studio.

Apple-clean UI with fixed controller hero image and full controller diagnostics.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

import drift_bot as core
import drift_engine as engine

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "Missing dependency: PySide6. Install with `pip install -r requirements.txt`."
    ) from exc

try:  # Optional runtime dependency for mic/audio diagnostics.
    import numpy as np
except Exception:  # pragma: no cover - optional
    np = None

try:  # Optional runtime dependency for mic/audio diagnostics.
    import sounddevice as sd
except Exception:  # pragma: no cover - optional
    sd = None


ACCENT = QtGui.QColor("#D8DF3A")
RAW_DOT = QtGui.QColor("#F4B057")
FIX_DOT = QtGui.QColor("#16C47F")


PLAYSTATION_BUTTONS = {
    0: "Cross",
    1: "Circle",
    2: "Square",
    3: "Triangle",
    4: "L1",
    5: "R1",
    6: "L2",
    7: "R2",
    8: "Create/Share",
    9: "Options",
    10: "L3",
    11: "R3",
    12: "PS",
    13: "Touchpad",
    14: "Mute",
}

XBOX_BUTTONS = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "LB",
    5: "RB",
    6: "View",
    7: "Menu",
    8: "Xbox",
    9: "L3",
    10: "R3",
    11: "Share",
}

GENERIC_GAMEPAD_BUTTONS = {
    0: "South",
    1: "East",
    2: "West",
    3: "North",
    4: "L1",
    5: "R1",
    6: "L2",
    7: "R2",
    8: "Back",
    9: "Start",
    10: "L3",
    11: "R3",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_vec(value: Tuple[float, float]) -> str:
    return f"({value[0]:+0.3f}, {value[1]:+0.3f})"


def detect_controller_family(name: str) -> str:
    lowered = name.lower()
    ps_tokens = [
        "dualsense",
        "dualshock",
        "wireless controller",
        "playstation",
        "ps4",
        "ps5",
        "sony",
    ]
    xbox_tokens = [
        "xbox",
        "x-input",
        "xinput",
        "elite",
        "series controller",
    ]

    if any(token in lowered for token in ps_tokens):
        return "playstation"
    if any(token in lowered for token in xbox_tokens):
        return "xbox"
    return "generic"


def button_label_for(family: str, index: int) -> str:
    if family == "playstation":
        mapping = PLAYSTATION_BUTTONS
    elif family == "xbox":
        mapping = XBOX_BUTTONS
    else:
        mapping = GENERIC_GAMEPAD_BUTTONS

    return mapping.get(index, f"Button {index}")


def audio_tokens_for_controller(name: str, family: str) -> list[str]:
    lowered = name.lower()
    tokens = []
    if family == "playstation":
        tokens.extend(["dualsense", "dualshock", "wireless controller", "playstation", "sony"])
    elif family == "xbox":
        tokens.extend(["xbox", "xinput", "controller"])

    tokens.extend(part for part in lowered.replace("-", " ").split() if len(part) > 3)

    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


@dataclass
class SidePanel:
    side: str
    frame: QtWidgets.QFrame
    scope: "StickScope"
    auto_radio: QtWidgets.QRadioButton
    manual_radio: QtWidgets.QRadioButton
    x_slider: QtWidgets.QSlider
    y_slider: QtWidgets.QSlider
    response_slider: QtWidgets.QSlider
    smoothing_slider: QtWidgets.QSlider
    x_value: QtWidgets.QLabel
    y_value: QtWidgets.QLabel
    response_value: QtWidgets.QLabel
    smoothing_value: QtWidgets.QLabel
    raw_label: QtWidgets.QLabel
    fixed_label: QtWidgets.QLabel
    drift_label: QtWidgets.QLabel
    suppression_label: QtWidgets.QLabel


class StickScope(QtWidgets.QWidget):
    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.raw = (0.0, 0.0)
        self.fixed = (0.0, 0.0)
        self.deadzone = 0.08
        self.trail: Deque[Tuple[float, float]] = deque(maxlen=100)
        self.setMinimumSize(220, 220)

    def set_state(self, raw: Tuple[float, float], fixed: Tuple[float, float], deadzone: float) -> None:
        self.raw = raw
        self.fixed = fixed
        self.deadzone = clamp(deadzone, 0.01, 0.50)
        self.trail.append(fixed)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(6, 6, -6, -6)
        painter.setPen(QtGui.QPen(QtGui.QColor("#E2E4EA"), 1.2))
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        painter.drawRoundedRect(rect, 14, 14)

        title_font = painter.font()
        title_font.setPointSize(10)
        title_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QtGui.QColor("#2D3242"))
        painter.drawText(rect.adjusted(12, 9, -12, -9), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, self.title)

        inner = rect.adjusted(16, 34, -16, -14)
        size = min(inner.width(), inner.height())
        square = QtCore.QRectF(inner.center().x() - size / 2, inner.center().y() - size / 2, size, size)

        center = square.center()
        radius = square.width() / 2 - 8

        painter.setPen(QtGui.QPen(QtGui.QColor("#D4D8E1"), 1))
        painter.drawLine(center.x() - radius, center.y(), center.x() + radius, center.y())
        painter.drawLine(center.x(), center.y() - radius, center.x(), center.y() + radius)

        painter.setPen(QtGui.QPen(QtGui.QColor("#BFC6D4"), 1.5))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QtGui.QPen(ACCENT, 1.4, QtCore.Qt.DashLine))
        painter.drawEllipse(center, radius * self.deadzone, radius * self.deadzone)

        if self.trail:
            for idx, point in enumerate(self.trail):
                alpha = int(20 + (idx / len(self.trail)) * 100)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(77, 172, 255, alpha))
                painter.drawEllipse(
                    QtCore.QPointF(center.x() + point[0] * radius, center.y() - point[1] * radius),
                    1.9,
                    1.9,
                )

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(RAW_DOT)
        painter.drawEllipse(
            QtCore.QPointF(center.x() + self.raw[0] * radius, center.y() - self.raw[1] * radius),
            4.6,
            4.6,
        )

        painter.setBrush(FIX_DOT)
        painter.drawEllipse(
            QtCore.QPointF(center.x() + self.fixed[0] * radius, center.y() - self.fixed[1] * radius),
            3.8,
            3.8,
        )


class ButtonCheckDialog(QtWidgets.QDialog):
    def __init__(
        self,
        joystick: core.pygame.joystick.Joystick,
        controller_name: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.joystick = joystick
        self.controller_name = controller_name
        self.family = detect_controller_family(controller_name)

        self.setWindowTitle("Controller Diagnostics")
        self.resize(760, 620)

        self.button_count = self.joystick.get_numbuttons()
        self.hat_count = self.joystick.get_numhats()

        self.button_seen = [False] * self.button_count
        self.button_labels: list[QtWidgets.QLabel] = []

        self.hat_seen: dict[tuple[int, str], bool] = {}
        self.hat_labels: dict[tuple[int, str], QtWidgets.QLabel] = {}

        self._build_ui()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        self.timer.stop()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #F5F5F7; }
            QLabel { color: #2B3345; }
            QFrame#card {
                background: #FFFFFF;
                border: 1px solid #E1E6EE;
                border-radius: 12px;
            }
            QPushButton {
                background: #F3F5F9;
                border: 1px solid #DBE0E9;
                border-radius: 8px;
                padding: 6px 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #EDF1F6;
            }
            """
        )

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        family_label = "PlayStation" if self.family == "playstation" else "Xbox" if self.family == "xbox" else "Generic"
        header = QtWidgets.QLabel(
            f"Controller: {self.controller_name}\n"
            f"Detected profile: {family_label}\n"
            "Press every button and D-pad direction once."
        )
        header.setStyleSheet("font-size:13px; font-weight:600;")
        root.addWidget(header)

        button_card = QtWidgets.QFrame(objectName="card")
        button_layout = QtWidgets.QVBoxLayout(button_card)
        button_layout.setContentsMargins(12, 12, 12, 12)
        button_layout.setSpacing(10)

        title = QtWidgets.QLabel("Button Map")
        title.setStyleSheet("font-weight:700;")
        button_layout.addWidget(title)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        for index in range(self.button_count):
            label_text = f"{button_label_for(self.family, index)}\n(#{index})"
            chip = QtWidgets.QLabel(label_text)
            chip.setAlignment(QtCore.Qt.AlignCenter)
            chip.setMinimumWidth(120)
            chip.setMinimumHeight(46)
            chip.setStyleSheet(self._chip_style(False))
            self.button_labels.append(chip)

            row = index // 4
            col = index % 4
            grid.addWidget(chip, row, col)

        if self.button_count == 0:
            none_label = QtWidgets.QLabel("No digital buttons reported by this controller.")
            none_label.setStyleSheet("color:#6C748A;")
            grid.addWidget(none_label, 0, 0, 1, 4)

        button_layout.addLayout(grid)

        if self.hat_count > 0:
            hats_title = QtWidgets.QLabel("D-pad / Hat")
            hats_title.setStyleSheet("font-weight:700;")
            button_layout.addWidget(hats_title)

            hats_layout = QtWidgets.QVBoxLayout()
            hats_layout.setSpacing(8)

            for hat in range(self.hat_count):
                row_layout = QtWidgets.QHBoxLayout()
                row_layout.addWidget(QtWidgets.QLabel(f"Hat {hat}"))
                for direction in ["UP", "DOWN", "LEFT", "RIGHT"]:
                    key = (hat, direction)
                    self.hat_seen[key] = False
                    chip = QtWidgets.QLabel(direction)
                    chip.setAlignment(QtCore.Qt.AlignCenter)
                    chip.setMinimumWidth(68)
                    chip.setStyleSheet(self._chip_style(False))
                    self.hat_labels[key] = chip
                    row_layout.addWidget(chip)
                row_layout.addStretch(1)
                hats_layout.addLayout(row_layout)

            button_layout.addLayout(hats_layout)

        root.addWidget(button_card, 1)

        test_card = QtWidgets.QFrame(objectName="card")
        test_layout = QtWidgets.QVBoxLayout(test_card)
        test_layout.setContentsMargins(12, 12, 12, 12)
        test_layout.setSpacing(10)

        test_title = QtWidgets.QLabel("Hardware Tests")
        test_title.setStyleSheet("font-weight:700;")
        test_layout.addWidget(test_title)

        hint = QtWidgets.QLabel(
            "Audio/Mic tests try to target the controller audio endpoints automatically.\n"
            "If not found, tests use system default devices."
        )
        hint.setStyleSheet("color:#6D7590;")
        test_layout.addWidget(hint)

        buttons_row = QtWidgets.QHBoxLayout()
        buttons_row.setSpacing(8)

        rumble_btn = QtWidgets.QPushButton("Test Vibration")
        rumble_btn.clicked.connect(self._run_rumble_test)
        buttons_row.addWidget(rumble_btn)

        led_btn = QtWidgets.QPushButton("Test Colors")
        led_btn.clicked.connect(self._run_led_test)
        buttons_row.addWidget(led_btn)

        audio_btn = QtWidgets.QPushButton("Test Audio Out")
        audio_btn.clicked.connect(self._run_audio_test)
        buttons_row.addWidget(audio_btn)

        mic_btn = QtWidgets.QPushButton("Test Mic")
        mic_btn.clicked.connect(self._run_mic_test)
        buttons_row.addWidget(mic_btn)

        buttons_row.addStretch(1)
        test_layout.addLayout(buttons_row)

        self.rumble_status = QtWidgets.QLabel("Vibration: not tested")
        self.led_status = QtWidgets.QLabel("Colors: not tested")
        self.audio_status = QtWidgets.QLabel("Audio out: not tested")
        self.mic_status = QtWidgets.QLabel("Mic: not tested")

        for label in [self.rumble_status, self.led_status, self.audio_status, self.mic_status]:
            label.setStyleSheet("color:#4B546E;")
            test_layout.addWidget(label)

        root.addWidget(test_card)

        footer = QtWidgets.QHBoxLayout()
        self.progress_label = QtWidgets.QLabel("Waiting for input...")
        self.progress_label.setStyleSheet("font-weight:700;")
        footer.addWidget(self.progress_label)
        footer.addStretch(1)

        reset_btn = QtWidgets.QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        footer.addWidget(reset_btn)

        close_btn = QtWidgets.QPushButton("Done")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        root.addLayout(footer)

        self._refresh_progress()

    def _chip_style(self, active: bool) -> str:
        if active:
            return (
                "background:#EAF9F2; border:1px solid #90D8B5; border-radius:8px; "
                "padding:6px 8px; color:#1A6C46; font-weight:700;"
            )
        return (
            "background:#F4F6FA; border:1px solid #DDE3ED; border-radius:8px; "
            "padding:6px 8px; color:#57607A; font-weight:600;"
        )

    def _reset(self) -> None:
        self.button_seen = [False] * self.button_count
        for label in self.button_labels:
            label.setStyleSheet(self._chip_style(False))

        for key in self.hat_seen:
            self.hat_seen[key] = False
        for label in self.hat_labels.values():
            label.setStyleSheet(self._chip_style(False))

        self._refresh_progress()

    def _poll(self) -> None:
        try:
            core.pygame.event.pump()
        except core.pygame.error:
            self.progress_label.setText("Controller disconnected.")
            return

        for index in range(self.button_count):
            if self.joystick.get_button(index):
                self.button_seen[index] = True
                self.button_labels[index].setStyleSheet(self._chip_style(True))

        for hat in range(self.hat_count):
            x_axis, y_axis = self.joystick.get_hat(hat)
            if y_axis > 0:
                self._mark_hat(hat, "UP")
            if y_axis < 0:
                self._mark_hat(hat, "DOWN")
            if x_axis < 0:
                self._mark_hat(hat, "LEFT")
            if x_axis > 0:
                self._mark_hat(hat, "RIGHT")

        self._refresh_progress()

    def _mark_hat(self, hat: int, direction: str) -> None:
        key = (hat, direction)
        if key in self.hat_seen:
            self.hat_seen[key] = True
            label = self.hat_labels.get(key)
            if label is not None:
                label.setStyleSheet(self._chip_style(True))

    def _refresh_progress(self) -> None:
        total_buttons = self.button_count
        passed_buttons = sum(1 for seen in self.button_seen if seen)

        total_hats = len(self.hat_seen)
        passed_hats = sum(1 for seen in self.hat_seen.values() if seen)

        total = total_buttons + total_hats
        passed = passed_buttons + passed_hats

        if total == 0:
            self.progress_label.setText("No testable controls were reported by this controller.")
            return

        pct = (passed / total) * 100.0
        if passed == total:
            self.progress_label.setText(f"All controls detected: {passed}/{total} (100%)")
        else:
            self.progress_label.setText(f"Detected {passed}/{total} controls ({pct:.0f}%)")

    def _set_test_status(self, label: QtWidgets.QLabel, text: str, status: str) -> None:
        if status == "ok":
            color = "#1A6C46"
        elif status == "warn":
            color = "#8A6200"
        else:
            color = "#9B2F2F"
        label.setText(text)
        label.setStyleSheet(f"color:{color}; font-weight:600;")

    def _run_rumble_test(self) -> None:
        if not hasattr(self.joystick, "rumble"):
            self._set_test_status(self.rumble_status, "Vibration: unsupported by this driver.", "fail")
            return

        try:
            ok = self.joystick.rumble(0.95, 0.95, 850)
            if ok:
                self._set_test_status(self.rumble_status, "Vibration: success (850ms).", "ok")
            else:
                self._set_test_status(
                    self.rumble_status,
                    "Vibration: command sent, but controller did not confirm.",
                    "warn",
                )
        except Exception as exc:
            self._set_test_status(self.rumble_status, f"Vibration: failed ({exc}).", "fail")

    def _run_led_test(self) -> None:
        if not hasattr(self.joystick, "set_led"):
            self._set_test_status(
                self.led_status,
                "Colors: LED API unavailable on this connection/driver.",
                "warn",
            )
            return

        colors = [(255, 0, 0), (0, 255, 0), (0, 140, 255), (255, 255, 255)]
        try:
            for red, green, blue in colors:
                self.joystick.set_led(red, green, blue)
                QtWidgets.QApplication.processEvents()
                time.sleep(0.28)
            self._set_test_status(self.led_status, "Colors: success (cycle completed).", "ok")
        except Exception as exc:
            self._set_test_status(self.led_status, f"Colors: failed ({exc}).", "fail")

    def _resolve_audio_device(self, kind: str) -> tuple[Optional[int], str, bool]:
        if sd is None:
            return None, "sounddevice not installed", False

        try:
            devices = sd.query_devices()
        except Exception as exc:
            return None, f"device query failed: {exc}", False

        if kind not in {"input", "output"}:
            return None, "invalid audio kind", False

        channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
        tokens = audio_tokens_for_controller(self.controller_name, self.family)

        best_index = None
        best_score = -1

        for index, device in enumerate(devices):
            channels = int(device.get(channel_key, 0))
            if channels <= 0:
                continue

            name = str(device.get("name", ""))
            lowered = name.lower()
            score = sum(1 for token in tokens if token in lowered)

            if score > best_score:
                best_score = score
                best_index = index

        # Use matched controller endpoint if possible.
        if best_index is not None and best_score > 0:
            return best_index, str(devices[best_index].get("name", "unknown")), True

        # Fall back to default device.
        try:
            default = sd.default.device
            if isinstance(default, (tuple, list)) and len(default) >= 2:
                default_index = int(default[0] if kind == "input" else default[1])
            elif isinstance(default, int):
                default_index = default
            else:
                default_index = -1
        except Exception:
            default_index = -1

        if 0 <= default_index < len(devices):
            dev = devices[default_index]
            if int(dev.get(channel_key, 0)) > 0:
                return default_index, str(dev.get("name", "unknown")), False

        # Last resort: first compatible device.
        for index, device in enumerate(devices):
            if int(device.get(channel_key, 0)) > 0:
                return index, str(device.get("name", "unknown")), False

        return None, "no compatible audio device", False

    def _run_audio_test(self) -> None:
        if np is None or sd is None:
            self._set_test_status(
                self.audio_status,
                "Audio out: requires numpy + sounddevice.",
                "fail",
            )
            return

        device_index, name, matched = self._resolve_audio_device("output")
        if device_index is None:
            self._set_test_status(self.audio_status, f"Audio out: {name}.", "fail")
            return

        sample_rate = 48000
        duration = 1.0
        t = np.linspace(0.0, duration, int(sample_rate * duration), endpoint=False)
        tone = (0.26 * np.sin(2.0 * np.pi * 660.0 * t)).astype(np.float32)

        try:
            sd.stop()
            sd.play(tone, samplerate=sample_rate, device=device_index, blocking=False)
            if matched:
                self._set_test_status(
                    self.audio_status,
                    f"Audio out: test tone sent to controller endpoint ({name}).",
                    "ok",
                )
            else:
                self._set_test_status(
                    self.audio_status,
                    f"Audio out: test tone sent to default/closest endpoint ({name}).",
                    "warn",
                )
        except Exception as exc:
            self._set_test_status(self.audio_status, f"Audio out: failed ({exc}).", "fail")

    def _run_mic_test(self) -> None:
        if np is None or sd is None:
            self._set_test_status(
                self.mic_status,
                "Mic: requires numpy + sounddevice.",
                "fail",
            )
            return

        device_index, name, matched = self._resolve_audio_device("input")
        if device_index is None:
            self._set_test_status(self.mic_status, f"Mic: {name}.", "fail")
            return

        seconds = 3.0
        sample_rate = 16000

        self._set_test_status(self.mic_status, f"Mic: recording {seconds:.0f}s on {name}...", "warn")
        QtWidgets.QApplication.processEvents()

        try:
            recording = sd.rec(
                int(seconds * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=device_index,
            )
            sd.wait()
        except Exception as exc:
            self._set_test_status(self.mic_status, f"Mic: failed ({exc}).", "fail")
            return

        if recording.size == 0:
            self._set_test_status(self.mic_status, "Mic: no captured samples.", "fail")
            return

        peak = float(np.max(np.abs(recording)))
        rms = float(np.sqrt(np.mean(np.square(recording))))

        if peak >= 0.02:
            label = "controller endpoint" if matched else "default/closest endpoint"
            self._set_test_status(
                self.mic_status,
                f"Mic: signal detected on {label} ({name}) peak={peak:.3f} rms={rms:.3f}.",
                "ok",
            )
        else:
            self._set_test_status(
                self.mic_status,
                (
                    f"Mic: very low signal on {name} peak={peak:.3f}. "
                    "Try speaking directly into controller mic."
                ),
                "warn",
            )


class ControllerHero(QtWidgets.QWidget):
    def __init__(self, image_path: pathlib.Path, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.left_raw = (0.0, 0.0)
        self.right_raw = (0.0, 0.0)
        self.left_fixed = (0.0, 0.0)
        self.right_fixed = (0.0, 0.0)
        self.controller_name = "No controller"

        self.image_path = image_path
        self.pixmap = QtGui.QPixmap(str(image_path))

        # Anchors tuned for assets/controller_only.png crop.
        self.left_anchor = QtCore.QPointF(0.278, 0.649)
        self.right_anchor = QtCore.QPointF(0.691, 0.649)

        self.setMinimumSize(700, 430)

    def set_name(self, name: str) -> None:
        self.controller_name = name
        self.update()

    def set_state(
        self,
        left_raw: Tuple[float, float],
        right_raw: Tuple[float, float],
        left_fixed: Tuple[float, float],
        right_fixed: Tuple[float, float],
    ) -> None:
        self.left_raw = left_raw
        self.right_raw = right_raw
        self.left_fixed = left_fixed
        self.right_fixed = right_fixed
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        rect = self.rect().adjusted(6, 6, -6, -6)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QtGui.QColor("#0E0E16"))
        gradient.setColorAt(1.0, QtGui.QColor("#1A1326"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#2E3246"), 1.2))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRoundedRect(rect, 18, 18)

        caption_font = painter.font()
        caption_font.setPointSize(10)
        caption_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(caption_font)
        painter.setPen(QtGui.QColor("#DCE1EE"))
        painter.drawText(rect.adjusted(12, 10, -12, -10), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, "Controller")
        painter.drawText(
            rect.adjusted(12, 10, -12, -10),
            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight,
            self.controller_name,
        )

        image_rect = QtCore.QRectF(rect.left() + 18, rect.top() + 40, rect.width() - 36, rect.height() - 52)

        if self.pixmap.isNull():
            painter.setPen(QtGui.QPen(QtGui.QColor("#A7AFC4"), 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(image_rect, 14, 14)
            painter.setPen(QtGui.QColor("#CFD5E6"))
            painter.drawText(image_rect, QtCore.Qt.AlignCenter, f"Missing image:\n{self.image_path}")
            return

        scaled = self.pixmap.scaled(
            int(image_rect.width()),
            int(image_rect.height()),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

        pix_rect = QtCore.QRectF(
            image_rect.center().x() - scaled.width() / 2,
            image_rect.center().y() - scaled.height() / 2,
            float(scaled.width()),
            float(scaled.height()),
        )

        painter.drawPixmap(QtCore.QPointF(pix_rect.left(), pix_rect.top()), scaled)

        left_center = QtCore.QPointF(
            pix_rect.left() + self.left_anchor.x() * pix_rect.width(),
            pix_rect.top() + self.left_anchor.y() * pix_rect.height(),
        )
        right_center = QtCore.QPointF(
            pix_rect.left() + self.right_anchor.x() * pix_rect.width(),
            pix_rect.top() + self.right_anchor.y() * pix_rect.height(),
        )
        overlay_radius = min(pix_rect.width(), pix_rect.height()) * 0.06

        self._draw_stick_overlay(painter, left_center, overlay_radius, self.left_raw, self.left_fixed)
        self._draw_stick_overlay(painter, right_center, overlay_radius, self.right_raw, self.right_fixed)

    def _draw_stick_overlay(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        raw: Tuple[float, float],
        fixed: Tuple[float, float],
    ) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 180), 1.0))
        painter.setBrush(QtGui.QColor(17, 20, 30, 70))
        painter.drawEllipse(center, radius, radius)

        raw_pt = QtCore.QPointF(center.x() + raw[0] * radius * 0.85, center.y() - raw[1] * radius * 0.85)
        fix_pt = QtCore.QPointF(center.x() + fixed[0] * radius * 0.85, center.y() - fixed[1] * radius * 0.85)

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(RAW_DOT)
        painter.drawEllipse(raw_pt, 4.3, 4.3)
        painter.setBrush(FIX_DOT)
        painter.drawEllipse(fix_pt, 3.4, 3.4)


class DriftlineProWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Driftline Pro Studio")
        self.resize(1480, 920)

        self.joystick: Optional[core.pygame.joystick.Joystick] = None
        self.controller_info: Optional[core.ControllerInfo] = None
        self.profile: Optional[core.ControllerProfile] = None
        self.profile_path: Optional[pathlib.Path] = None

        self.compensator = engine.DriftCompensator()
        self.live_enabled = False
        self.last_frame = time.monotonic()

        core.init_input_system()
        self._build_ui()
        self.refresh_controllers(select_first=True)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        self.live_enabled = False
        if self.joystick is not None:
            try:
                self.joystick.quit()
            except Exception:
                pass
        core.shutdown_input_system()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #F5F5F7; }
            QWidget {
                color: #1F2432;
                font-family: 'SF Pro Text', 'SF Pro Display', '.AppleSystemUIFont', 'Helvetica Neue', sans-serif;
                font-size: 12px;
            }
            QFrame#shell, QFrame#topBar, QFrame#panel, QFrame#actions {
                background: #FFFFFF;
                border: 1px solid #E2E5EC;
                border-radius: 14px;
            }
            QLabel#brand {
                color: #222737;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0.2px;
            }
            QLabel#chip {
                background: #F2F4F8;
                border: 1px solid #DDE2EA;
                border-radius: 11px;
                padding: 4px 10px;
                font-weight: 600;
                color: #3A4257;
            }
            QPushButton {
                background: #F3F5F9;
                border: 1px solid #DBE0E9;
                border-radius: 9px;
                padding: 7px 12px;
                font-weight: 650;
                color: #2B3244;
            }
            QPushButton:hover {
                background: #EDEFF4;
                border-color: #D2D8E3;
            }
            QPushButton#primary {
                background: #007AFF;
                color: #FFFFFF;
                border: none;
                font-weight: 700;
            }
            QPushButton#stop {
                background: #FF3B30;
                color: #FFFFFF;
                border: none;
                font-weight: 700;
            }
            QComboBox {
                background: #FFFFFF;
                border: 1px solid #D8DEE8;
                border-radius: 8px;
                padding: 6px 10px;
                min-width: 320px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #D0D6E2;
                height: 6px;
                background: #EFF2F7;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #007AFF;
                border: 1px solid #0065D2;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QRadioButton { spacing: 6px; color: #3A4257; }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
            }
            QRadioButton::indicator:unchecked {
                border: 1px solid #BFC7D7;
                background: #FFFFFF;
            }
            QRadioButton::indicator:checked {
                border: 1px solid #007AFF;
                background: #007AFF;
            }
            """
        )

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        shell = QtWidgets.QFrame(objectName="shell")
        shell_layout = QtWidgets.QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 12, 14, 12)
        shell_layout.setSpacing(12)
        outer.addWidget(shell)

        top = QtWidgets.QFrame(objectName="topBar")
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(8)

        brand = QtWidgets.QLabel("Driftline", objectName="brand")
        top_layout.addWidget(brand)

        self.controller_combo = QtWidgets.QComboBox()
        top_layout.addWidget(self.controller_combo)

        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_controllers)
        top_layout.addWidget(refresh_btn)

        connect_btn = QtWidgets.QPushButton("Connect")
        connect_btn.clicked.connect(self.connect_selected)
        top_layout.addWidget(connect_btn)

        top_layout.addStretch(1)

        mapping_btn = QtWidgets.QPushButton("MAPPING")
        mapping_btn.clicked.connect(self.calibrate)
        top_layout.addWidget(mapping_btn)

        profiles_btn = QtWidgets.QPushButton("PROFILES")
        profiles_btn.clicked.connect(self.load_profile_dialog)
        top_layout.addWidget(profiles_btn)

        save_as_btn = QtWidgets.QPushButton("SAVE AS")
        save_as_btn.clicked.connect(self.save_profile_dialog)
        top_layout.addWidget(save_as_btn)

        load_btn = QtWidgets.QPushButton("LOAD")
        load_btn.clicked.connect(self.load_profile_dialog)
        top_layout.addWidget(load_btn)

        self.status_chip = QtWidgets.QLabel("Idle", objectName="chip")
        top_layout.addWidget(self.status_chip)

        shell_layout.addWidget(top)

        center_row = QtWidgets.QHBoxLayout()
        center_row.setSpacing(12)

        self.left_panel = self._build_side_panel("Left")
        center_row.addWidget(self.left_panel.frame, 3)

        center_stack = QtWidgets.QVBoxLayout()
        center_stack.setSpacing(8)
        self.hero = ControllerHero(pathlib.Path("assets/controller_only.png"))
        center_stack.addWidget(self.hero, 10)

        stats = QtWidgets.QHBoxLayout()
        self.connected_label = QtWidgets.QLabel("Connected: none")
        self.profile_label = QtWidgets.QLabel("Profile: none")
        self.quality_label = QtWidgets.QLabel("Quality: unknown")
        self.quality_label.setStyleSheet("color:#A85555;")
        stats.addWidget(self.connected_label)
        stats.addWidget(self.profile_label, 1)
        stats.addWidget(self.quality_label)
        center_stack.addLayout(stats)

        center_row.addLayout(center_stack, 6)

        self.right_panel = self._build_side_panel("Right")
        center_row.addWidget(self.right_panel.frame, 3)

        shell_layout.addLayout(center_row, 10)

        actions = QtWidgets.QFrame(objectName="actions")
        actions_layout = QtWidgets.QHBoxLayout(actions)
        actions_layout.setContentsMargins(10, 8, 10, 8)
        actions_layout.setSpacing(8)

        quick_btn = QtWidgets.QPushButton("Quick Fix")
        quick_btn.setObjectName("primary")
        quick_btn.clicked.connect(self.quick_fix)
        actions_layout.addWidget(quick_btn)

        calibrate_btn = QtWidgets.QPushButton("Calibrate")
        calibrate_btn.clicked.connect(self.calibrate)
        actions_layout.addWidget(calibrate_btn)

        button_check_btn = QtWidgets.QPushButton("Button Check")
        button_check_btn.clicked.connect(self.open_button_check)
        actions_layout.addWidget(button_check_btn)

        start_btn = QtWidgets.QPushButton("Start Live")
        start_btn.clicked.connect(self.start_live)
        actions_layout.addWidget(start_btn)

        stop_btn = QtWidgets.QPushButton("Stop")
        stop_btn.setObjectName("stop")
        stop_btn.clicked.connect(self.stop_live)
        actions_layout.addWidget(stop_btn)

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self.save_profile_dialog)
        actions_layout.addWidget(save_btn)

        load_btn2 = QtWidgets.QPushButton("Load")
        load_btn2.clicked.connect(self.load_profile_dialog)
        actions_layout.addWidget(load_btn2)

        export_btn = QtWidgets.QPushButton("Steam Hint")
        export_btn.clicked.connect(self.export_steam_hint)
        actions_layout.addWidget(export_btn)

        doctor_btn = QtWidgets.QPushButton("Doctor")
        doctor_btn.clicked.connect(self.doctor)
        actions_layout.addWidget(doctor_btn)

        actions_layout.addStretch(1)

        self.message_label = QtWidgets.QLabel("Ready")
        self.message_label.setStyleSheet("color:#6C748A;")
        actions_layout.addWidget(self.message_label)

        shell_layout.addWidget(actions)

    def _build_side_panel(self, side: str) -> SidePanel:
        frame = QtWidgets.QFrame(objectName="panel")
        frame.setMinimumWidth(300)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QtWidgets.QLabel(f"{side} Stick")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setWeight(QtGui.QFont.DemiBold)
        title.setFont(title_font)
        layout.addWidget(title)

        section_label = QtWidgets.QLabel("Deadzone   Sensitivity")
        section_label.setStyleSheet("color:#7C849A; font-size:11px;")
        layout.addWidget(section_label)

        scope = StickScope(f"{side} scope")
        layout.addWidget(scope, 5)

        modes = QtWidgets.QHBoxLayout()
        auto_radio = QtWidgets.QRadioButton("Auto")
        manual_radio = QtWidgets.QRadioButton("Manual")
        auto_radio.setChecked(True)
        modes.addWidget(auto_radio)
        modes.addWidget(manual_radio)
        layout.addLayout(modes)

        x_slider, x_value = self._slider_row("X", layout, 1, 35, 8)
        y_slider, y_value = self._slider_row("Y", layout, 1, 35, 8)
        response_slider, response_value = self._slider_row("Response", layout, 50, 180, 100)
        smoothing_slider, smoothing_value = self._slider_row("Smoothing", layout, 0, 80, 35)

        raw_label = QtWidgets.QLabel("Raw: (0.000, 0.000)")
        fixed_label = QtWidgets.QLabel("Fixed: (0.000, 0.000)")
        drift_label = QtWidgets.QLabel("Drift index: 0.00")
        suppression_label = QtWidgets.QLabel("Suppression: 0.0%")

        for label in [raw_label, fixed_label, drift_label, suppression_label]:
            label.setStyleSheet("color:#59627B;")
            layout.addWidget(label)

        layout.addStretch(1)

        panel = SidePanel(
            side=side,
            frame=frame,
            scope=scope,
            auto_radio=auto_radio,
            manual_radio=manual_radio,
            x_slider=x_slider,
            y_slider=y_slider,
            response_slider=response_slider,
            smoothing_slider=smoothing_slider,
            x_value=x_value,
            y_value=y_value,
            response_value=response_value,
            smoothing_value=smoothing_value,
            raw_label=raw_label,
            fixed_label=fixed_label,
            drift_label=drift_label,
            suppression_label=suppression_label,
        )

        auto_radio.toggled.connect(lambda checked, p=panel: self._toggle_manual(p, not checked))
        self._toggle_manual(panel, False)

        return panel

    def _slider_row(
        self,
        name: str,
        parent: QtWidgets.QVBoxLayout,
        minimum: int,
        maximum: int,
        default: int,
    ) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)

        name_label = QtWidgets.QLabel(name)
        value_label = QtWidgets.QLabel(f"{default}%")
        value_label.setMinimumWidth(40)
        value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(default)
        slider.valueChanged.connect(lambda v, out=value_label: out.setText(f"{v}%"))

        row.addWidget(name_label)
        row.addWidget(slider, 1)
        row.addWidget(value_label)
        parent.addLayout(row)

        return slider, value_label

    def _toggle_manual(self, panel: SidePanel, manual_enabled: bool) -> None:
        panel.x_slider.setEnabled(manual_enabled)
        panel.y_slider.setEnabled(manual_enabled)

    def _message(self, text: str) -> None:
        self.message_label.setText(text)

    def _set_status(self, text: str) -> None:
        self.status_chip.setText(text)

    def refresh_controllers(self, select_first: bool = False) -> None:
        self.controller_combo.clear()
        controllers = core.list_controllers()
        for info in controllers:
            self.controller_combo.addItem(f"[{info.index}] {info.name}", info.index)

        if controllers and select_first:
            self.controller_combo.setCurrentIndex(0)

        self._set_status("Controllers found" if controllers else "No controller")

    def connect_selected(self) -> None:
        if self.controller_combo.count() == 0:
            self.refresh_controllers(select_first=True)
            if self.controller_combo.count() == 0:
                QtWidgets.QMessageBox.warning(self, "Controller", "No controller detected.")
                return

        index = self.controller_combo.currentData()
        if index is None:
            QtWidgets.QMessageBox.warning(self, "Controller", "Invalid controller selection.")
            return

        if self.joystick is not None:
            try:
                self.joystick.quit()
            except Exception:
                pass

        joystick, info = core.init_controller(int(index))
        self.joystick = joystick
        self.controller_info = info
        self.compensator.reset()

        self.connected_label.setText(f"Connected: {info.name} (#{info.index})")
        self.hero.set_name(info.name)
        self._set_status("Connected")
        self._message(f"Connected {info.name}")

        self.profile_path = core.choose_profile_path(info, None)
        self.profile_label.setText(f"Profile: {self.profile_path}")

        self.profile = None
        if self.profile_path.exists():
            try:
                self.profile = core.load_profile(self.profile_path)
                self._sync_from_profile()
                self._update_quality()
                self._message(f"Loaded profile {self.profile_path.name}")
            except Exception as exc:
                self._message(f"Profile load failed: {exc}")

    def _sync_from_profile(self) -> None:
        if self.profile is None:
            return
        self.left_panel.x_slider.setValue(int(round(self.profile.left.x.deadzone * 100)))
        self.left_panel.y_slider.setValue(int(round(self.profile.left.y.deadzone * 100)))
        self.right_panel.x_slider.setValue(int(round(self.profile.right.x.deadzone * 100)))
        self.right_panel.y_slider.setValue(int(round(self.profile.right.y.deadzone * 100)))

    def _update_quality(self) -> None:
        if self.profile is None:
            self.quality_label.setText("Quality: unknown")
            self.quality_label.setStyleSheet("color:#C05A5A;")
            return

        quality, _ = core.profile_quality(self.profile)
        if quality == "good":
            self.quality_label.setText("Quality: stable")
            self.quality_label.setStyleSheet("color:#14A36F;")
        elif quality == "warn":
            self.quality_label.setText("Quality: heavy but compensated")
            self.quality_label.setStyleSheet("color:#C8931A;")
        else:
            self.quality_label.setText("Quality: severe wear")
            self.quality_label.setStyleSheet("color:#C04F4F;")

    def _ensure_ready(self) -> bool:
        if self.controller_info is None or self.joystick is None:
            self.connect_selected()
        if self.controller_info is None or self.joystick is None:
            return False
        if self.profile is None:
            return False
        return True

    def _build_config(self, panel: SidePanel, x: core.AxisCalibration, y: core.AxisCalibration) -> engine.StickRuntimeConfig:
        return engine.StickRuntimeConfig(
            center_x=x.center,
            center_y=y.center,
            deadzone_x=x.deadzone,
            deadzone_y=y.deadzone,
            auto_deadzone=panel.auto_radio.isChecked(),
            manual_deadzone_x=panel.x_slider.value() / 100.0,
            manual_deadzone_y=panel.y_slider.value() / 100.0,
            anti_deadzone=0.02,
            response_gamma=panel.response_slider.value() / 100.0,
            smoothing=panel.smoothing_slider.value() / 100.0,
            adaptive_center=True,
            adaptive_learning_rate=0.015,
            adaptive_limit=0.14,
        )

    def quick_fix(self) -> None:
        if self.controller_info is None:
            self.connect_selected()
            if self.controller_info is None:
                return

        if self.profile is None and self.profile_path and self.profile_path.exists():
            try:
                self.profile = core.load_profile(self.profile_path)
                self._sync_from_profile()
                self._update_quality()
            except Exception:
                self.profile = None

        if self.profile is None:
            self.calibrate()
            if self.profile is None:
                return

        self.start_live()
        self._set_status("Quick Fix")

    def calibrate(self) -> None:
        if self.controller_info is None or self.joystick is None:
            self.connect_selected()
            if self.controller_info is None or self.joystick is None:
                return

        try:
            left_axes, right_axes = self._mapping_wizard()
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(self, "Mapping", str(exc))
            return

        attempts = 3
        best: Optional[core.ControllerProfile] = None
        best_score = float("inf")

        progress = QtWidgets.QProgressDialog("Calibrating... keep sticks untouched", "Cancel", 0, attempts, self)
        progress.setWindowTitle("Calibration")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()

        for attempt in range(attempts):
            if progress.wasCanceled():
                self._message("Calibration canceled")
                return

            progress.setValue(attempt)
            progress.setLabelText(f"Calibration pass {attempt + 1}/{attempts}")
            QtWidgets.QApplication.processEvents()

            samples = core.collect_axis_samples(
                self.joystick,
                [left_axes[0], left_axes[1], right_axes[0], right_axes[1]],
                3.5,
            )

            candidate = core.ControllerProfile(
                controller_name=self.controller_info.name,
                controller_guid=self.controller_info.guid,
                generated_at=dt.datetime.now().astimezone().isoformat(),
                axis_count=self.joystick.get_numaxes(),
                left=core.StickCalibration(
                    x=core.build_axis_calibration(samples[left_axes[0]], left_axes[0]),
                    y=core.build_axis_calibration(samples[left_axes[1]], left_axes[1]),
                ),
                right=core.StickCalibration(
                    x=core.build_axis_calibration(samples[right_axes[0]], right_axes[0]),
                    y=core.build_axis_calibration(samples[right_axes[1]], right_axes[1]),
                ),
            )

            score = (
                candidate.left.x.deadzone
                + candidate.left.y.deadzone
                + candidate.right.x.deadzone
                + candidate.right.y.deadzone
                + abs(candidate.left.x.center)
                + abs(candidate.left.y.center)
                + abs(candidate.right.x.center)
                + abs(candidate.right.y.center)
            )

            if score < best_score:
                best = candidate
                best_score = score

            quality, _ = core.profile_quality(candidate)
            if quality == "good":
                break

        progress.setValue(attempts)

        if best is None:
            QtWidgets.QMessageBox.critical(self, "Calibration", "Calibration failed.")
            return

        self.profile = best
        self.compensator.reset()
        if self.profile_path is None:
            self.profile_path = core.profile_path_for_controller(self.controller_info)

        core.save_profile(best, self.profile_path)
        hint_path = core.write_steam_hint(best, self.profile_path)

        self.profile_label.setText(f"Profile: {self.profile_path}")
        self._sync_from_profile()
        self._update_quality()
        self._set_status("Calibrated")
        self._message(f"Saved {self.profile_path.name} and {hint_path.name}")

        QtWidgets.QMessageBox.information(self, "Calibration complete", "Calibration complete and saved.")

    def _mapping_wizard(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        if self.joystick is None:
            raise RuntimeError("No controller connected.")
        if self.joystick.get_numaxes() < 4:
            raise RuntimeError("Controller does not expose 4+ axes.")

        prompts = [
            "Move LEFT stick in full circles for 2.5 seconds, then click OK.",
            "Keep moving LEFT stick in full circles for another 2.5 seconds, then click OK.",
            "Move RIGHT stick in full circles for 2.5 seconds, then click OK.",
            "Keep moving RIGHT stick in full circles for another 2.5 seconds, then click OK.",
        ]

        detected: list[int] = []
        spans: list[float] = []

        for instruction in prompts:
            QtWidgets.QMessageBox.information(self, "Axis Mapping", instruction)
            sample = self._sample_spans(2.5)
            axis, span = core.pick_top_axis(sample, excluded=detected)
            detected.append(axis)
            spans.append(span)

        left = (detected[0], detected[1])
        right = (detected[2], detected[3])

        if min(spans) < 0.18:
            left = (0, 1)
            right = (2, 3)

        return left, right

    def _sample_spans(self, duration: float) -> list[float]:
        if self.joystick is None:
            raise RuntimeError("No controller connected.")

        axis_count = self.joystick.get_numaxes()
        mins = [1.0] * axis_count
        maxs = [-1.0] * axis_count

        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            core.pygame.event.pump()
            for axis in range(axis_count):
                value = float(self.joystick.get_axis(axis))
                mins[axis] = min(mins[axis], value)
                maxs[axis] = max(maxs[axis], value)
            QtWidgets.QApplication.processEvents()
            time.sleep(1 / 220)

        return [maxs[i] - mins[i] for i in range(axis_count)]

    def open_button_check(self) -> None:
        if self.joystick is None:
            self.connect_selected()
            if self.joystick is None:
                return

        was_live = self.live_enabled
        self.live_enabled = False

        controller_name = self.controller_info.name if self.controller_info else self.joystick.get_name()
        dialog = ButtonCheckDialog(self.joystick, controller_name, self)
        dialog.exec()

        if was_live:
            self.live_enabled = True
            self._set_status("Live")
            self._message("Resumed live compensation")
        else:
            self._message("Controller diagnostics completed")

    def start_live(self) -> None:
        if not self._ensure_ready():
            QtWidgets.QMessageBox.warning(self, "Live", "Connect controller and calibrate/load profile first.")
            return
        self.live_enabled = True
        self.last_frame = time.monotonic()
        self._set_status("Live")
        self._message("Live compensation started")

    def stop_live(self) -> None:
        self.live_enabled = False
        self._set_status("Paused")
        self._message("Live compensation stopped")

    def _poll(self) -> None:
        if not self.live_enabled or self.joystick is None or self.profile is None:
            return

        now = time.monotonic()
        dt_frame = now - self.last_frame
        self.last_frame = now

        try:
            core.pygame.event.pump()
            left_raw = core.read_stick(self.joystick, self.profile.left)
            right_raw = core.read_stick(self.joystick, self.profile.right)
        except core.pygame.error:
            self.live_enabled = False
            self._set_status("Disconnected")
            self._message("Controller disconnected")
            return

        left_cfg = self._build_config(self.left_panel, self.profile.left.x, self.profile.left.y)
        right_cfg = self._build_config(self.right_panel, self.profile.right.x, self.profile.right.y)

        left_result, right_result = self.compensator.process_pair(
            left_raw,
            right_raw,
            left_cfg,
            right_cfg,
            dt_frame,
        )

        left_deadzone = max(left_result.deadzone_x, left_result.deadzone_y)
        right_deadzone = max(right_result.deadzone_x, right_result.deadzone_y)

        self.left_panel.scope.set_state(left_raw, left_result.corrected, left_deadzone)
        self.right_panel.scope.set_state(right_raw, right_result.corrected, right_deadzone)
        self.hero.set_state(left_raw, right_raw, left_result.corrected, right_result.corrected)

        self.left_panel.raw_label.setText(f"Raw: {format_vec(left_raw)}")
        self.left_panel.fixed_label.setText(f"Fixed: {format_vec(left_result.corrected)}")
        self.left_panel.drift_label.setText(f"Drift index: {left_result.metrics.drift_index:0.2f}")
        self.left_panel.suppression_label.setText(f"Suppression: {left_result.metrics.suppression:0.1f}%")

        self.right_panel.raw_label.setText(f"Raw: {format_vec(right_raw)}")
        self.right_panel.fixed_label.setText(f"Fixed: {format_vec(right_result.corrected)}")
        self.right_panel.drift_label.setText(f"Drift index: {right_result.metrics.drift_index:0.2f}")
        self.right_panel.suppression_label.setText(f"Suppression: {right_result.metrics.suppression:0.1f}%")

    def save_profile_dialog(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "Profile", "No profile loaded to save.")
            return

        default_path = str(self.profile_path or pathlib.Path("profiles/custom_profile.json"))
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save profile",
            default_path,
            "JSON files (*.json)",
        )
        if not filename:
            return

        path = pathlib.Path(filename)
        core.save_profile(self.profile, path)
        self.profile_path = path
        self.profile_label.setText(f"Profile: {path}")
        self._message(f"Saved {path.name}")

    def load_profile_dialog(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load profile",
            str(pathlib.Path("profiles")),
            "JSON files (*.json)",
        )
        if not filename:
            return

        path = pathlib.Path(filename)
        try:
            profile = core.load_profile(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Profile", f"Load failed: {exc}")
            return

        self.profile = profile
        self.profile_path = path
        self.profile_label.setText(f"Profile: {path}")
        self.compensator.reset()
        self._sync_from_profile()
        self._update_quality()
        self._message(f"Loaded {path.name}")

    def export_steam_hint(self) -> None:
        if self.profile is None or self.profile_path is None:
            QtWidgets.QMessageBox.warning(self, "Steam Hint", "Load or calibrate profile first.")
            return

        path = core.write_steam_hint(self.profile, self.profile_path)
        self._message(f"Saved {path.name}")
        QtWidgets.QMessageBox.information(self, "Steam Hint", f"Saved:\n{path}")

    def doctor(self) -> None:
        if self.profile is None:
            QtWidgets.QMessageBox.warning(self, "Doctor", "No profile loaded.")
            return

        quality, findings = core.profile_quality(self.profile)
        if quality == "good":
            headline = "Profile quality is stable."
        elif quality == "warn":
            headline = "Profile is usable but drift is heavy."
        else:
            headline = "Profile indicates severe stick wear."

        detail = "\n".join(findings) if findings else "No warning flags."
        QtWidgets.QMessageBox.information(self, "Drift Doctor", f"{headline}\n\n{detail}")


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = DriftlineProWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
